"""Conditional payload symbols attached to existing native output occurrences.

This is a small bridge into the existing v2 ValueGraph.  It preserves the
ProgramGraph ReferenceValue and ExecutionModel denotation, and stores only a
single ValueGraph delta plus qualified references to the existing output
occurrence, ETO port, and EvidenceEdge.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from scar.ir.program.ids import ValueID

from scar.ir.execution.codec import SCHEMA as EXECUTION_SCHEMA
from scar.ir.execution.content import (
    EvidenceEdgeRef, NativeOutputRef, ObjectIdentity,
)
from scar.ir.execution.coordinates import ProgramSnapshot
from scar.ir.execution.ids import DenotationID, ValueOccurrenceID
from scar.ir.execution.model import ExecutionModel
from scar.ir.program.codec import SCHEMA as PROGRAM_SCHEMA
from scar.ir.program.model import ProgramGraph, ReferenceValue
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2.evidence import (
    EvidenceEdge, EvidenceNodeKind, EvidenceRelation, EvidenceStatus, OperationInstance,
    ProviderReference,
)
from scar.ir.v2.ids import (
    LogicalValueID, MaterializationID, OperationDefinitionID,
    OperationInstanceID, ProvenanceID, ValueSlotID, ValueVersionID,
)
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.values import (
    EquivalenceClaim, LogicalValue, Materialization, ProvenanceRecord,
    ProvenanceRelation, ValueGraph, ValueVersion,
)
from scar.trace.native_port_sidecar import (
    NativeBoxedPort, NativeInstancePorts, NativePortIndex, read_native_port_index,
)
from scar.ir.execution.coordinates import BlockVisitID


_SCHEMA = "scar.execution.symbolic-native-output"
_SCHEMA_VERSION = 2
_MAX_PUBLICATION_BYTES = 131_072
_IDENTITY_SEMANTICS = (
    "endpoint-symbol-only; distinct symbol IDs do not imply numerically different tensor contents"
)
_UNKNOWN_FACTS = (
    "numeric_tensor_contents",
    "input_content_versions",
    "alias_or_copy_relation",
    "normal_completion_and_effects",
    "device_readiness",
    "storage_region_and_bytes",
)


def _artifact(value: object, name: str) -> None:
    if type(value) is not ProviderArtifact:
        raise TypeError(f"{name} must be ProviderArtifact")
    value.__post_init__()


def _identifier(value: object, kind: type, name: str) -> None:
    if type(value) is not kind:
        raise TypeError(f"{name} must be {kind.__name__}")
    value.__post_init__()


def _nonnegative(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative exact integer")


def _read_stable_small_file(path: str | Path) -> bytes:
    """Read one small, regular publication without following or racing a path."""
    target = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("symbolic output publication must be a regular file")
        if before.st_size <= 0 or before.st_size > _MAX_PUBLICATION_BYTES:
            raise ValueError("symbolic output publication exceeds its fixed byte bound")
        chunks = bytearray()
        while len(chunks) < before.st_size:
            chunk = os.read(fd, min(16_384, before.st_size - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) != before.st_size or os.read(fd, 1):
            raise ValueError("symbolic output publication changed size during read")
        after = os.fstat(fd)
        signature = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                  item.st_mtime_ns, item.st_ctime_ns)
        if not stat.S_ISREG(after.st_mode) or signature(before) != signature(after):
            raise ValueError("symbolic output publication changed during read")
        current = os.stat(target, follow_symlinks=False)
        if (not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)):
            raise ValueError("symbolic output publication path changed during read")
        return bytes(chunks)
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class NativeOutputPortRef:
    """Address of one existing output port in a receipt-bound port index."""

    index_artifact: ProviderArtifact
    instance: OperationInstanceID
    definition: OperationDefinitionID
    source_ordinal: int
    path: tuple[int, ...]
    source_fact: ProviderFactReference
    formal_slot: ValueSlotID
    provider_reference: str
    descriptor_id: str

    def __post_init__(self) -> None:
        _artifact(self.index_artifact, "native port index artifact")
        _identifier(self.instance, OperationInstanceID, "native port operation instance")
        _identifier(self.definition, OperationDefinitionID, "native port definition")
        _nonnegative(self.source_ordinal, "native port source ordinal")
        if (type(self.path) is not tuple or not self.path
                or any(type(item) is not int or item < 0 for item in self.path)):
            raise ValueError("native output path must be a nonempty ordered integer tuple")
        if type(self.source_fact) is not ProviderFactReference:
            raise TypeError("native output source must be a ProviderFactReference")
        self.source_fact.__post_init__()
        _identifier(self.formal_slot, ValueSlotID, "native output formal slot")
        for field_name in ("provider_reference", "descriptor_id"):
            if type(getattr(self, field_name)) is not str or not getattr(self, field_name):
                raise ValueError(f"{field_name} must be nonempty text")


@dataclass(frozen=True, slots=True)
class SymbolicNativeOutputProjection:
    """One inferred relation between a canonical output and an observed port.

    The relation adds no operation, occurrence, evidence edge, object identity,
    input version, alias claim, or storage region.  Its ValueGraph IDs name the
    endpoint projection only; they do not claim numeric inequality.
    """

    projection_id: str
    status: EvidenceStatus
    snapshot: ProgramSnapshot
    execution_artifact: ProviderArtifact
    output_occurrence: ValueOccurrenceID
    program_value: ValueID
    original_denotation: DenotationID
    native_output: NativeOutputRef
    native_port: NativeOutputPortRef
    original_edge: EvidenceEdgeRef
    base_value_graph: ProviderArtifact
    symbolic_value: LogicalValueID
    symbolic_version: ValueVersionID
    symbolic_provenance: ProvenanceID
    symbolic_materialization: MaterializationID
    identity_semantics: str = _IDENTITY_SEMANTICS
    unknowns: tuple[str, ...] = _UNKNOWN_FACTS

    def __post_init__(self) -> None:
        if type(self.projection_id) is not str or not re.fullmatch(r"native-output-symbol:[0-9a-f]{64}", self.projection_id):
            raise ValueError("projection ID must be a stable native-output-symbol digest")
        if type(self.status) is not EvidenceStatus or self.status is not EvidenceStatus.INFERRED:
            raise ValueError("payload projection status must remain Inferred")
        if type(self.snapshot) is not ProgramSnapshot:
            raise TypeError("projection snapshot must be ProgramSnapshot")
        self.snapshot.__post_init__()
        _artifact(self.execution_artifact, "execution artifact")
        if self.execution_artifact.schema != EXECUTION_SCHEMA:
            raise ValueError("projection execution artifact schema differs from ExecutionModel")
        _identifier(self.output_occurrence, ValueOccurrenceID, "output occurrence")
        _identifier(self.program_value, ValueID, "program value")
        _identifier(self.original_denotation, DenotationID, "original denotation")
        if type(self.native_output) is not NativeOutputRef:
            raise TypeError("projection must reuse the original NativeOutputRef")
        self.native_output.__post_init__()
        if type(self.native_port) is not NativeOutputPortRef:
            raise TypeError("projection must reference one existing native output port")
        self.native_port.__post_init__()
        if type(self.original_edge) is not EvidenceEdgeRef:
            raise TypeError("projection must reuse an original EvidenceEdgeRef")
        self.original_edge.__post_init__()
        _artifact(self.base_value_graph, "base ValueGraph artifact")
        _identifier(self.symbolic_value, LogicalValueID, "symbolic logical value")
        if type(self.symbolic_version) is not ValueVersionID:
            raise TypeError("symbolic version must be ValueVersionID")
        self.symbolic_version.__post_init__()
        if self.symbolic_version.logical_value != self.symbolic_value or self.symbolic_version.version != 0:
            raise ValueError("symbolic result uses its own endpoint-local revision zero")
        _identifier(self.symbolic_provenance, ProvenanceID, "symbolic provenance")
        _identifier(self.symbolic_materialization, MaterializationID, "symbolic materialization")
        if self.identity_semantics != _IDENTITY_SEMANTICS:
            raise ValueError("symbol identity semantics may not imply numeric inequality")
        if type(self.unknowns) is not tuple or self.unknowns != _UNKNOWN_FACTS:
            raise ValueError("symbolic projection must retain the complete unknown-fact list")


def _symbol_ids(scope: tuple[object, ...]) -> tuple[str, LogicalValueID, ValueVersionID,
                                                    ProvenanceID, MaterializationID]:
    payload = json.dumps(scope, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    digest = sha256(payload.encode("utf-8")).hexdigest()
    value = "native-output-symbol:" + digest
    logical = LogicalValueID(value)
    return (value, logical, ValueVersionID(logical, 0), ProvenanceID(value),
            MaterializationID(value))


def _projection_scope(snapshot: ProgramSnapshot, execution_artifact: ProviderArtifact,
                      output_occurrence: ValueOccurrenceID, program_value: ValueID,
                      original_denotation: DenotationID, native_output: NativeOutputRef,
                      native_port: NativeOutputPortRef) -> tuple[object, ...]:
    return (
        _SCHEMA_VERSION,
        snapshot.artifact.uri,
        snapshot.artifact.sha256,
        snapshot.schema_version,
        execution_artifact.uri,
        execution_artifact.sha256,
        output_occurrence.wire,
        program_value.wire,
        original_denotation.wire,
        native_output.boundary.wire,
        native_output.operation.wire,
        native_output.position,
        native_port.instance.wire,
        native_port.definition.wire,
        native_port.source_fact.artifact.sha256,
        native_port.source_ordinal,
        native_port.path,
        native_port.source_fact.locator,
        native_port.provider_reference,
        native_port.descriptor_id,
    )


def _expected_symbol_ids(projection: SymbolicNativeOutputProjection):
    return _symbol_ids(_projection_scope(
        projection.snapshot, projection.execution_artifact,
        projection.output_occurrence, projection.program_value,
        projection.original_denotation, projection.native_output,
        projection.native_port))


def _descriptor(provider: ProviderReference, port: NativeBoxedPort) -> tuple[str, str]:
    if provider.reference_id != port.provider_reference:
        raise ValueError("native output port does not point to the supplied original ProviderReference")
    descriptors = [item for item in provider.metadata.get("descriptors", ())
                   if type(item) is dict and item.get("descriptor_id") == port.descriptor_id]
    if len(descriptors) != 1:
        raise ValueError("native output descriptor is absent or ambiguous in the original provider record")
    descriptor = descriptors[0]
    representation = descriptor.get("type")
    if type(representation) is not str or representation != port.provider_type:
        raise ValueError("native output type differs from the original provider descriptor")
    device = descriptor.get("device")
    if device is None:
        tensor_tuple = descriptor.get("tensor_tuple")
        if type(tensor_tuple) is list and len(tensor_tuple) >= 6:
            device = tensor_tuple[5]
    if type(device) is not str or not device:
        raise ValueError("original provider descriptor has no exact device observation")
    return representation, device


def build_symbolic_native_output(
        program: ProgramGraph, execution: ExecutionModel,
        execution_artifact: ProviderArtifact, output_occurrence: ValueOccurrenceID,
        port_index: NativePortIndex, port_index_artifact: ProviderArtifact,
        port_row: NativeInstancePorts, native_instance: OperationInstance, port: NativeBoxedPort,
        provider_reference: ProviderReference, edge: EvidenceEdge,
        edge_artifact: ProviderArtifact,
        base_value_graph_artifact: ProviderArtifact,
        base_value_graph: ValueGraph) -> tuple[SymbolicNativeOutputProjection, ValueGraph]:
    """Join caller-limited typed records; this does not replay source artifacts or all port shards."""
    if type(program) is not ProgramGraph or type(execution) is not ExecutionModel:
        raise TypeError("native symbolic output bridge requires exact ProgramGraph and ExecutionModel")
    if type(port_index) is not NativePortIndex or type(port_row) is not NativeInstancePorts:
        raise TypeError("native symbolic output bridge requires a published typed port index row")
    if type(native_instance) is not OperationInstance:
        raise TypeError("native symbolic output bridge requires the original typed OperationInstance")
    if type(port) is not NativeBoxedPort or type(provider_reference) is not ProviderReference:
        raise TypeError("native symbolic output bridge requires original typed port/provider records")
    if type(edge) is not EvidenceEdge:
        raise TypeError("native symbolic output bridge requires an existing EvidenceEdge")
    _artifact(execution_artifact, "execution artifact")
    _artifact(port_index_artifact, "native port index artifact")
    _artifact(edge_artifact, "original evidence artifact")
    _artifact(base_value_graph_artifact, "base ValueGraph artifact")
    if execution_artifact.schema != EXECUTION_SCHEMA:
        raise ValueError("execution artifact schema differs from ExecutionModel")
    if port_index_artifact.schema != "scar.native-boxed-port-index":
        raise ValueError("native port index artifact has an unexpected schema")
    if read_native_port_index(port_index_artifact.uri,
                              expected_sha256=port_index_artifact.sha256) != port_index:
        raise ValueError("native port index artifact does not decode to the supplied receipt-bound index")
    if type(base_value_graph) is not ValueGraph:
        raise TypeError("base value graph must be the existing ValueGraph")
    base_value_graph.assert_valid()

    if execution.snapshot.artifact.schema != PROGRAM_SCHEMA:
        raise ValueError("execution snapshot does not identify a ProgramGraph artifact")
    if type(port_index_artifact.uri) is not str or not port_index_artifact.uri:
        raise ValueError("native port index artifact URI is required")
    if (type(output_occurrence) is not ValueOccurrenceID
            or type(output_occurrence.value) is not str):
        raise TypeError("output occurrence must be its exact existing ValueOccurrenceID")
    value_occurrences = [item for item in execution.values if item.id == output_occurrence]
    if len(value_occurrences) != 1:
        raise ValueError("output occurrence is absent or duplicated in original ExecutionModel")
    occurrence = value_occurrences[0]
    program_values = [item for item in program.values if item.id == occurrence.value]
    if len(program_values) != 1 or type(program_values[0]) is not ReferenceValue:
        raise ValueError("symbolic Tensor projection requires the existing ReferenceValue output")
    reference_value: ReferenceValue = program_values[0]

    denotations = [item for item in execution.denotations if item.value == output_occurrence]
    if len(denotations) != 1:
        raise ValueError("output occurrence must retain exactly one original denotation")
    denotation = denotations[0]
    if type(denotation.basis) is not NativeOutputRef:
        raise ValueError("output denotation is not grounded by an existing NativeOutputRef")
    if type(denotation.source) is not ProviderFactReference:
        raise ValueError("output denotation does not retain its original ETO source fact")
    native_output = denotation.basis
    boundaries = [item for item in program.native_boundaries if item.id == native_output.boundary]
    if len(boundaries) != 1:
        raise ValueError("NativeOutputRef boundary is absent or duplicated in ProgramGraph")
    boundary = boundaries[0]
    native_slots = [item for item in boundary.outputs if item.position == native_output.position]
    if len(native_slots) != 1:
        raise ValueError("NativeOutputRef does not resolve to one original declared output slot")
    slot = native_slots[0]
    if (slot.port.region != reference_value.region or slot.port.exit_name != "normal"
            or slot.port.index != native_output.position):
        raise ValueError("Program ReferenceValue differs from the exact normal native output port")

    if (port.direction != "output" or port.kind != "TENSOR"
            or port.formal_status != "QUALIFIED" or port.formal_slot is None):
        raise ValueError("projection requires one formally qualified observed Tensor output port")
    if not any(item is port or item == port for item in port_row.ports):
        raise ValueError("selected output port is not present in its existing instance row")
    if (port_row.source_ordinal < port_index.first_source_ordinal
            or port_row.source_ordinal >= port_index.stop_source_ordinal):
        raise ValueError("native port index artifact/range does not qualify the port row")
    if (native_instance.id != port_row.instance
            or native_instance.definition != port_row.definition
            or native_instance.metadata.get("raw_reference")
            != f"sha256:{port_index.source_sha256}#/nodes/{port_row.source_ordinal}"):
        raise ValueError("port row differs from its original OperationInstance/source ordinal")
    tensor_slots = [item for item in native_instance.metadata.get("tensor_slots", ())
                    if type(item) is dict and item.get("role") == "outputs"
                    and item.get("ordered_path") == list(port.path)]
    if len(tensor_slots) != 1:
        raise ValueError("qualified port path does not resolve to one original ETO Tensor slot")
    tensor_slot = tensor_slots[0]
    schema_binding = tensor_slot.get("native_schema_binding")
    if (type(schema_binding) is not dict
            or schema_binding.get("formal_slot") is None
            or decode(ValueSlotID, schema_binding["formal_slot"]) != port.formal_slot
            or tensor_slot.get("provider_reference") != port.provider_reference
            or tensor_slot.get("descriptor_id") != port.descriptor_id):
        raise ValueError("port differs from its original ETO slot's formal/provider bindings")
    if port_index.source_sha256 != denotation.source.artifact.sha256:
        raise ValueError("native port index and output denotation refer to different ETO source bytes")
    if port_index.source_uri != denotation.source.artifact.uri:
        raise ValueError("native port index and output denotation refer to different ETO source URIs")
    expected_locator = "#/nodes/" + str(port_row.source_ordinal) + port.source_locator
    if denotation.source.locator != expected_locator:
        raise ValueError("native output port path differs from the original denotation source locator")

    output_operation = [item for item in execution.operations
                        if item.id == native_output.operation]
    if len(output_operation) != 1:
        raise ValueError("NativeOutputRef operation occurrence is absent or duplicated")
    if type(occurrence.origin) is not BlockVisitID:
        raise ValueError("native output occurrence is not anchored at its existing return block visit")
    if output_operation[0].visit != occurrence.origin:
        raise ValueError("output occurrence and NativeOutputRef do not share the existing return visit")
    bindings = [item for item in execution.evidence_bindings
                if item.operation == native_output.operation]
    if len(bindings) != 1:
        raise ValueError("native return occurrence must have exactly one original evidence binding")
    binding = bindings[0]
    if binding.legacy.instance != port_row.instance:
        raise ValueError("native return does not resolve to the port row's existing operation instance")
    if binding.legacy.artifact != edge_artifact:
        raise ValueError("original EvidenceEdge artifact differs from the execution's bound evidence artifact")
    if binding.source.artifact.sha256 != denotation.source.artifact.sha256:
        raise ValueError("execution binding and native output denote different ETO sources")
    if binding.source.locator != "#/nodes/" + str(port_row.source_ordinal) + "/outputs":
        raise ValueError("execution binding does not name the original ETO node's output tree")
    if (provider_reference.reference_id != port.provider_reference
            or port.provider_reference is None or port.descriptor_id is None):
        raise ValueError("qualified output port has no exact original provider/descriptor reference")
    expected_edge_ref = ("sha256:" + port_index.source_sha256
                         + "#/nodes/" + str(port_row.source_ordinal) + port.source_locator)
    if (edge.relation is not EvidenceRelation.OUTPUT_REFERENCE
            or edge.source.kind is not EvidenceNodeKind.OPERATION_INSTANCE
            or edge.source.reference != port_row.instance
            or edge.target.kind is not EvidenceNodeKind.PROVIDER_REFERENCE
            or edge.target.reference != provider_reference.reference_id
            or expected_edge_ref not in edge.evidence.references
            or edge.evidence.scope != provider_reference.scope):
        raise ValueError("original EvidenceEdge does not qualify this exact native output port")
    original_edge = EvidenceEdgeRef(binding.legacy.artifact, edge.edge_id)
    representation, device = _descriptor(provider_reference, port)

    if type(denotation.identity) is ObjectIdentity:
        # Keep this original object reference only as the denotation.  It is not
        # converted into a data version and no ObjectBinding is emitted.
        if denotation.identity.object.artifact != base_value_graph_artifact:
            raise ValueError("base ValueGraph artifact differs from the original ObjectIdentity source")
        if not base_value_graph.has_object(denotation.identity.object.object):
            raise ValueError("original ReferenceValue ObjectIdentity is absent from its source ValueGraph")
    else:
        raise ValueError("symbolic payload projection requires the existing tensor ObjectIdentity reference")

    port_ref = NativeOutputPortRef(
        port_index_artifact, port_row.instance, port_row.definition,
        port_row.source_ordinal, port.path, denotation.source,
        port.formal_slot, provider_reference.reference_id, port.descriptor_id)
    (projection_id, logical_id, version_id, provenance_id,
     materialization_id) = _symbol_ids(_projection_scope(
         execution.snapshot, execution_artifact, output_occurrence,
         occurrence.value, denotation.id, native_output, port_ref))
    projection = SymbolicNativeOutputProjection(
        projection_id, EvidenceStatus.INFERRED, execution.snapshot, execution_artifact,
        output_occurrence, occurrence.value, denotation.id, native_output, port_ref,
        original_edge, base_value_graph_artifact,
        logical_id, version_id, provenance_id, materialization_id)

    delta = ValueGraph()
    semantic_type = "torch.tensor.payload.symbolic"
    delta.add_logical_value(LogicalValue(
        logical_id, semantic_type,
        "Symbol for the payload associated with this exact observed output endpoint; numerical contents unknown.",
        {"projection_id": projection_id, "identity_semantics": _IDENTITY_SEMANTICS,
         "evidence_status": EvidenceStatus.INFERRED.value,
         "representation_observation": representation}))
    delta.add_provenance(ProvenanceRecord(
        provenance_id, ProvenanceRelation.UNKNOWN, (), (version_id,), producer=None,
        equivalence=EquivalenceClaim.UNKNOWN, evidence="Inferred",
        metadata={"projection_id": projection_id,
                  "candidate_native_operation": port_row.instance.wire,
                  "input_content_versions": "UNKNOWN",
                  "alias_or_copy_relation": "UNKNOWN",
                  "normal_completion_and_effects": "UNKNOWN",
                  "device_readiness": "UNKNOWN"}))
    delta.add_version(ValueVersion(
        version_id, provenance_id, (), semantic_type, metadata={
            "projection_id": projection_id,
            "revision_semantics": "endpoint-local-symbol-revision; not Torch Tensor._version",
            "identity_semantics": _IDENTITY_SEMANTICS,
        }))
    delta.add_materialization(Materialization(
        materialization_id, version_id, representation, device, region=None,
        producer=None, ready_event=None, validity_scope=None, evidence="Inferred",
        metadata={"projection_id": projection_id,
                  "placement_observation": "Observed",
                  "output_endpoint_association": "Inferred",
                  "storage_region": "UNKNOWN",
                  "ready_state": "UNKNOWN"}))
    delta.assert_valid()
    _validate_projection_delta(projection, delta)
    return projection, delta


def _validate_projection_delta(projection: SymbolicNativeOutputProjection,
                                delta: ValueGraph) -> None:
    delta.assert_valid()
    (projection_id, logical_id, version_id, provenance_id,
     materialization_id) = _expected_symbol_ids(projection)
    if (projection.projection_id, projection.symbolic_value,
            projection.symbolic_version, projection.symbolic_provenance,
            projection.symbolic_materialization) != (
                projection_id, logical_id, version_id, provenance_id,
                materialization_id):
        raise ValueError("projection IDs do not match their qualified snapshot/execution/output scope")
    counts = delta.validate()["counts"]
    expected = {"logical_values": 1, "versions": 1, "provenance": 1,
                "allocations": 0, "regions": 0, "materializations": 1,
                "bindings": 0, "objects": 0}
    if any(counts.get(key, 0) != count for key, count in expected.items()):
        raise ValueError("symbolic output ValueGraph delta must contain exactly one symbol and no storage/object graph")
    logical = delta.logical_values.get(projection.symbolic_value)
    version = delta.versions.get(projection.symbolic_version)
    provenance = delta.provenance.get(projection.symbolic_provenance)
    materialization = delta.materializations.get(projection.symbolic_materialization)
    if any(item is None for item in (logical, version, provenance, materialization)):
        raise ValueError("projection does not resolve to all four existing ValueGraph record kinds")
    if (logical.semantic_type != "torch.tensor.payload.symbolic"
            or logical.metadata != {
                "projection_id": projection.projection_id,
                "identity_semantics": _IDENTITY_SEMANTICS,
                "evidence_status": EvidenceStatus.INFERRED.value,
                "representation_observation": logical.metadata.get("representation_observation"),
            }
            or type(logical.metadata.get("representation_observation")) is not str
            or not logical.metadata["representation_observation"]):
        raise ValueError("logical payload symbol metadata/status is not the locked inferred form")
    if (version.provenance_id != provenance.id or version.parent_versions != ()
            or version.semantic_type != logical.semantic_type or version.control_scope is not None
            or version.metadata != {
                "projection_id": projection.projection_id,
                "revision_semantics": "endpoint-local-symbol-revision; not Torch Tensor._version",
                "identity_semantics": _IDENTITY_SEMANTICS,
            }
            or provenance.relation is not ProvenanceRelation.UNKNOWN
            or provenance.inputs != () or provenance.outputs != (version.id,)
            or provenance.producer is not None
            or provenance.equivalence is not EquivalenceClaim.UNKNOWN
            or provenance.evidence != "Inferred"
            or provenance.metadata != {
                "projection_id": projection.projection_id,
                "candidate_native_operation": projection.native_port.instance.wire,
                "input_content_versions": "UNKNOWN",
                "alias_or_copy_relation": "UNKNOWN",
                "normal_completion_and_effects": "UNKNOWN",
                "device_readiness": "UNKNOWN",
            }):
        raise ValueError("symbolic result provenance must remain unknown with no asserted inputs/producer")
    if (materialization.value_version != version.id
            or materialization.region is not None or materialization.producer is not None
            or materialization.ready_event is not None or materialization.validity_scope is not None
            or materialization.evidence != "Inferred"
            or materialization.representation != logical.metadata["representation_observation"]
            or not materialization.device
            or materialization.metadata != {
                "projection_id": projection.projection_id,
                "placement_observation": "Observed",
                "output_endpoint_association": "Inferred",
                "storage_region": "UNKNOWN",
                "ready_state": "UNKNOWN",
            }):
        raise ValueError("symbolic result materialization may not assert storage, producer, or readiness")


def write_symbolic_native_output(path: str | Path,
                                 projection: SymbolicNativeOutputProjection,
                                 delta: ValueGraph) -> str:
    """Write one deterministic association document; never overwrite an artifact."""
    _validate_projection_delta(projection, delta)
    document = {
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "projection": encode(projection),
        "value_graph_delta": delta.to_dict(),
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
    if len(payload) > _MAX_PUBLICATION_BYTES:
        raise ValueError("symbolic output publication exceeds its fixed byte bound")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError(f"symbolic output publication already exists: {target}") from None
    return sha256(payload).hexdigest()


def read_symbolic_native_output(path: str | Path, *,
                                expected_sha256: str | None = None
                                ) -> tuple[SymbolicNativeOutputProjection, ValueGraph]:
    """Decode one receipt-bounded publication; no source-artifact replay occurs."""
    payload = _read_stable_small_file(path)
    digest = sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("symbolic native output publication SHA256 mismatch")
    document = loads(payload)
    if (type(document) is not dict
            or set(document) != {"schema", "schema_version", "projection", "value_graph_delta"}
            or document["schema"] != _SCHEMA
            or type(document["schema_version"]) is not int
            or document["schema_version"] != _SCHEMA_VERSION):
        raise ValueError("symbolic native output publication header mismatch")
    projection = decode(SymbolicNativeOutputProjection, document["projection"])
    delta = values_from_dict(document["value_graph_delta"])
    _validate_projection_delta(projection, delta)
    return projection, delta


def query_symbolic_native_output(path: str | Path, occurrence: ValueOccurrenceID, *,
                                 expected_sha256: str | None = None
                                 ) -> tuple[SymbolicNativeOutputProjection, ValueGraph]:
    """Check transport/internal consistency and query an occurrence; no source replay."""
    _identifier(occurrence, ValueOccurrenceID, "query output occurrence")
    projection, delta = read_symbolic_native_output(path, expected_sha256=expected_sha256)
    if projection.output_occurrence != occurrence:
        raise KeyError("publication does not contain the requested original output occurrence")
    _validate_projection_delta(projection, delta)
    return projection, delta


def merge_symbolic_native_output(base: ValueGraph, delta: ValueGraph) -> ValueGraph:
    """Return a merged view while leaving the source ValueGraph untouched."""
    from scar.ir.v2.codec import values_from_dict as decode_values

    if type(base) is not ValueGraph or type(delta) is not ValueGraph:
        raise TypeError("ValueGraph merge requires exact base/delta ValueGraph records")
    if any(getattr(delta, name) for name in ("objects", "allocations", "regions", "bindings")):
        raise ValueError("symbolic output merge does not accept or silently discard object/storage/binding records")
    merged = decode_values(base.to_dict())
    delta.assert_valid()
    for record in delta.logical_values.values():
        merged.add_logical_value(record)
    for record in delta.provenance.values():
        merged.add_provenance(record)
    for record in delta.versions.values():
        merged.add_version(record)
    for record in delta.materializations.values():
        merged.add_materialization(record)
    merged.assert_valid()
    return merged


__all__ = [
    "NativeOutputPortRef", "SymbolicNativeOutputProjection",
    "build_symbolic_native_output", "write_symbolic_native_output",
    "read_symbolic_native_output", "query_symbolic_native_output",
    "merge_symbolic_native_output",
]

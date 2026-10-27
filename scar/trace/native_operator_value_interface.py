"""Operator-local value and state interfaces over original native ports.

This adapter reuses the existing ValueGraph for endpoint-local payload
symbols.  Original operations, definitions, ports, provider descriptors,
schema slots and EvidenceEdges stay in their source artifacts; this module
stores only qualified references and a small ValueGraph delta.

UNKNOWN provenance inputs mean that an operation reported these tensor
arguments and outputs together.  They do not claim a complete or minimal
content dependency set, a read, a write, completion, aliasing, or readiness.
Cross-operation provider recurrences remain separate reference-flow
candidates and are never ValueGraph parents.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence

from scar.ir.execution.content import EvidenceEdgeRef
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2.evidence import OperationInstance, ProviderReference
from scar.ir.v2.contracts import EffectSummary, EffectTargetKind
from scar.ir.v2.ids import (
    EffectSummaryID, LogicalValueID, MaterializationID, OperationDefinitionID,
    OperationInstanceID, ProvenanceID, ValueSlotID, ValueVersionID,
)
from scar.ir.v2.semantic import OperationDefinition, ValueSlot
from scar.ir.v2.values import (
    EquivalenceClaim, LogicalValue, Materialization, ProvenanceRecord,
    ProvenanceRelation, ValueGraph, ValueVersion,
)
from .native_port_sidecar import (
    NativeBoxedPort, NativeInstancePorts, NativePortIndex,
    NativePortShardReference, _identity_from_values, _manifest_identity,
    _read_shard, query_native_ports, read_native_port_index,
)
from .native_reference_flow import (
    NativeReferenceFlowIndex, NativeReferencePortOccurrence, _bucket,
    _endpoint, _group_key, _read_flow_shard, read_native_reference_flow_index,
)
from scar.store.bundle_partitions import BundlePartitions


_SCHEMA = "scar.native-operator-value-interface"
_VERSION = 1
_MAX_BYTES = 8_000_000
_IDENTITY_SEMANTICS = (
    "endpoint-local payload symbol; distinct IDs do not imply numerically different contents"
)
_UNKNOWN_INTERFACE_FACTS = (
    "actual tensor reads and writes",
    "complete or minimal content dependencies",
    "normal completion and effects",
    "cross-instance causality from source ordinal",
    "alias or copy realization",
    "storage binding and device readiness",
)


def _digest(value: object, name: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


def _artifact(value: object, name: str) -> None:
    if type(value) is not ProviderArtifact:
        raise TypeError(f"{name} must be ProviderArtifact")
    value.__post_init__()


def _id(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")
    value.__post_init__()


def _port_id(ordinal: int, direction: str, path: tuple[int, ...]) -> str:
    return f"eto:{ordinal}:{direction}:" + "/".join(map(str, path))


def _port_scope(manifest: ProviderArtifact, port_index: ProviderArtifact,
                eto: ProviderArtifact, row: NativeInstancePorts,
                port: NativeBoxedPort) -> tuple[object, ...]:
    return (_VERSION, manifest.uri, manifest.sha256, port_index.uri,
            port_index.sha256, eto.uri, eto.sha256, row.instance.wire,
            row.definition.wire, row.source_ordinal, port.direction,
            port.path, port.source_locator, port.formal_slot.wire
            if port.formal_slot else None, port.provider_reference,
            port.descriptor_id)


def _symbol_ids(scope: tuple[object, ...]) -> tuple[LogicalValueID, ValueVersionID,
                                                    ProvenanceID, MaterializationID]:
    digest = sha256(json.dumps(scope, ensure_ascii=True, separators=(",", ":"),
                               allow_nan=False).encode("utf-8")).hexdigest()
    token = "native-port-payload:" + digest
    logical = LogicalValueID(token)
    return logical, ValueVersionID(logical, 0), ProvenanceID(token), MaterializationID(token)


@dataclass(frozen=True, slots=True)
class NativeOperatorPortBinding:
    """One original ordered port plus its optional ValueGraph payload symbol."""

    port_id: str
    direction: str
    path: tuple[int, ...]
    source_locator: str
    kind: str
    provider_type: str | None
    formal_slot: ValueSlotID | None
    formal_status: str
    provider_reference: str | None
    descriptor_id: str | None
    original_edge: EvidenceEdgeRef | None
    logical_value: LogicalValueID | None
    value_version: ValueVersionID | None
    materialization: MaterializationID | None

    def __post_init__(self) -> None:
        if type(self.port_id) is not str or not self.port_id:
            raise ValueError("port ID is required")
        if self.direction not in ("input", "output"):
            raise ValueError("port direction must be input or output")
        if (type(self.path) is not tuple or not self.path
                or any(type(part) is not int or part < 0 for part in self.path)):
            raise ValueError("port path must be a nonempty ordered integer tuple")
        expected = "/" + ("inputs" if self.direction == "input" else "outputs") + "/values/" + "/".join(map(str, self.path))
        if self.source_locator != expected:
            raise ValueError("port locator differs from its original ordered path")
        if self.kind == "TENSOR":
            if any(item is None for item in (self.logical_value, self.value_version,
                                              self.materialization)):
                raise ValueError("Tensor port must have an endpoint-local payload symbol")
            if self.value_version.logical_value != self.logical_value:
                raise ValueError("Tensor endpoint symbol/version identities disagree")
        elif any(item is not None for item in (self.logical_value, self.value_version,
                                                self.materialization)):
            raise ValueError("non-Tensor ports do not receive Tensor payload symbols")
        if self.provider_reference is None and self.descriptor_id is not None:
            raise ValueError("descriptor reference requires the original provider reference")
        if self.original_edge is not None:
            if type(self.original_edge) is not EvidenceEdgeRef:
                raise TypeError("original edge must be EvidenceEdgeRef")
            self.original_edge.__post_init__()


@dataclass(frozen=True, slots=True)
class NativeSchemaStateBoundary:
    """A schema-declared may-write or may-alias mapped to actual port paths."""

    relation: str
    effect_summary: EffectSummaryID | None
    schema_sha256: str
    left_formal_slot: ValueSlotID
    left_port_id: str
    right_formal_slot: ValueSlotID | None = None
    right_port_id: str | None = None
    status: str = "DECLARED_MAY_ONLY"

    def __post_init__(self) -> None:
        if self.relation not in ("DECLARED_MAY_WRITE", "SCHEMA_MAY_ALIAS"):
            raise ValueError("unsupported schema state boundary")
        if self.effect_summary is not None:
            _id(self.effect_summary, EffectSummaryID, "effect summary")
        _digest(self.schema_sha256, "schema SHA")
        _id(self.left_formal_slot, ValueSlotID, "left formal slot")
        if self.right_formal_slot is not None:
            _id(self.right_formal_slot, ValueSlotID, "right formal slot")
        if type(self.left_port_id) is not str or not self.left_port_id:
            raise ValueError("left actual port reference is required")
        if (self.relation == "SCHEMA_MAY_ALIAS") != (self.right_formal_slot is not None
                and type(self.right_port_id) is str and bool(self.right_port_id)):
            raise ValueError("alias boundaries require both exact actual formal ports")
        if self.status != "DECLARED_MAY_ONLY":
            raise ValueError("schema boundaries cannot claim actual effects")


@dataclass(frozen=True, slots=True)
class NativeOperatorValueInterface:
    interface_id: str
    instance: OperationInstanceID
    definition: OperationDefinitionID
    source_ordinal: int
    label: str
    schema_sha256: str | None
    provider_revision: str | None
    effect_summary: EffectSummaryID | None
    state_slots: tuple[ValueSlotID, ...]
    inputs: tuple[NativeOperatorPortBinding, ...]
    outputs: tuple[NativeOperatorPortBinding, ...]
    state_boundaries: tuple[NativeSchemaStateBoundary, ...]
    schema_alias_pair_inventory_complete: bool | None = None
    identity_semantics: str = _IDENTITY_SEMANTICS
    unknowns: tuple[str, ...] = _UNKNOWN_INTERFACE_FACTS

    def __post_init__(self) -> None:
        if type(self.interface_id) is not str or not re.fullmatch(r"native-operator-interface:[0-9a-f]{64}", self.interface_id):
            raise ValueError("interface ID must be a stable digest")
        _id(self.instance, OperationInstanceID, "native operation instance")
        _id(self.definition, OperationDefinitionID, "native operation definition")
        if type(self.source_ordinal) is not int or self.source_ordinal < 0:
            raise ValueError("source ordinal must be nonnegative")
        if type(self.label) is not str or not self.label:
            raise ValueError("native operation label is required")
        if self.schema_sha256 is not None:
            _digest(self.schema_sha256, "schema SHA")
        if (self.schema_alias_pair_inventory_complete is not None
                and type(self.schema_alias_pair_inventory_complete) is not bool):
            raise TypeError("schema alias inventory completeness must be bool or None")
        if self.effect_summary is not None:
            _id(self.effect_summary, EffectSummaryID, "effect summary")
        if type(self.inputs) is not tuple or any(type(item) is not NativeOperatorPortBinding for item in self.inputs):
            raise TypeError("ordered native input bindings must be typed")
        if type(self.outputs) is not tuple or any(type(item) is not NativeOperatorPortBinding for item in self.outputs):
            raise TypeError("ordered native output bindings must be typed")
        if any(item.direction != direction for direction, items in (("input", self.inputs), ("output", self.outputs)) for item in items):
            raise ValueError("native interface port direction is inconsistent")
        if len({item.port_id for item in self.inputs + self.outputs}) != len(self.inputs + self.outputs):
            raise ValueError("interface repeats an original ETO port ID")
        if type(self.state_boundaries) is not tuple or any(type(item) is not NativeSchemaStateBoundary for item in self.state_boundaries):
            raise TypeError("state boundaries must be typed schema references")
        if self.identity_semantics != _IDENTITY_SEMANTICS or self.unknowns != _UNKNOWN_INTERFACE_FACTS:
            raise ValueError("operator interface must preserve symbolic identity and unknown boundaries")


@dataclass(frozen=True, slots=True)
class NativePhysicalCandidateRef:
    """Original marker storage association navigated by provider token only."""

    association: ProviderFactReference
    provider_reference: str
    storage_region_id: str
    allocation_id: str
    marker_instance_id: str
    physical_locator: str
    object_reference: str | None = None
    association_basis: str = "PROVIDER_REFERENCE_CANDIDATE_ONLY"

    def __post_init__(self) -> None:
        if type(self.association) is not ProviderFactReference:
            raise TypeError("physical association must be an original ProviderFactReference")
        self.association.__post_init__()
        if type(self.provider_reference) is not str or not self.provider_reference:
            raise ValueError("original provider reference is required")
        if any(type(item) is not str or not item for item in
               (self.storage_region_id, self.allocation_id, self.marker_instance_id,
                self.physical_locator)):
            raise ValueError("original physical observation locator is required")
        if self.association_basis != "PROVIDER_REFERENCE_CANDIDATE_ONLY":
            raise ValueError("physical association is only a provider-reference candidate")


@dataclass(frozen=True, slots=True)
class NativeOperatorValueFragment:
    bundle_manifest: ProviderArtifact
    native_port_index: ProviderArtifact
    reference_flow_index: ProviderArtifact
    eto_source: ProviderArtifact
    interfaces: tuple[NativeOperatorValueInterface, ...]
    physical_candidates: tuple[NativePhysicalCandidateRef, ...] = ()
    schema: str = _SCHEMA
    schema_version: int = _VERSION

    def __post_init__(self) -> None:
        for value, name in ((self.bundle_manifest, "bundle manifest"),
                            (self.native_port_index, "native port index"),
                            (self.reference_flow_index, "reference-flow index"),
                            (self.eto_source, "ETO source")):
            _artifact(value, name)
        if self.schema != _SCHEMA or type(self.schema_version) is not int or self.schema_version != _VERSION:
            raise ValueError("unsupported native operator value fragment")
        if type(self.interfaces) is not tuple or not self.interfaces:
            raise ValueError("fragment must retain at least one original operation interface")
        if any(type(item) is not NativeOperatorValueInterface for item in self.interfaces):
            raise TypeError("fragment interfaces must be typed")
        if len({item.instance for item in self.interfaces}) != len(self.interfaces):
            raise ValueError("fragment repeats an original operation instance")
        if type(self.physical_candidates) is not tuple or any(type(item) is not NativePhysicalCandidateRef for item in self.physical_candidates):
            raise TypeError("physical candidates must be typed original references")


@dataclass(frozen=True, slots=True)
class NativeOperatorSourceShardSummary:
    """Full-scan receipt and counts for one original native-port source shard."""

    source: NativePortShardReference
    original_instances_verified: int
    input_ports: int
    output_ports: int
    tensor_input_ports: int
    tensor_output_ports: int
    tensor_ports_with_provider_descriptor: int
    tensor_ports_without_provider_descriptor: int
    tensor_ports_without_instance_tensor_slot: int
    formal_ports_resolved: int
    formal_ports_unresolved: int
    declared_may_write_boundaries: int
    schema_may_alias_boundaries: int
    operations_with_schema: int
    operations_without_schema: int
    schema_alias_inventory_incomplete_operations: int
    output_interface_input_versions: int
    output_interface_provenance_records: int

    def __post_init__(self) -> None:
        if type(self.source) is not NativePortShardReference:
            raise TypeError("summary must reuse its original NativePortShardReference")
        for name in (
            "original_instances_verified", "input_ports", "output_ports",
            "tensor_input_ports", "tensor_output_ports",
            "tensor_ports_with_provider_descriptor", "tensor_ports_without_provider_descriptor",
            "tensor_ports_without_instance_tensor_slot",
            "formal_ports_resolved", "formal_ports_unresolved",
            "declared_may_write_boundaries", "schema_may_alias_boundaries",
            "operations_with_schema", "operations_without_schema",
            "schema_alias_inventory_incomplete_operations",
            "output_interface_input_versions", "output_interface_provenance_records",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative exact integer")
        if self.original_instances_verified != self.source.operation_rows:
            raise ValueError("source shard instance count differs from its original port shard")
        if self.input_ports + self.output_ports != self.source.ports:
            raise ValueError("source shard port counts differ from its original receipt")
        if (self.tensor_ports_with_provider_descriptor + self.tensor_ports_without_provider_descriptor
                != self.tensor_input_ports + self.tensor_output_ports):
            raise ValueError("Tensor descriptor counts do not cover the original Tensor ports")
        if self.tensor_ports_without_instance_tensor_slot > self.tensor_input_ports + self.tensor_output_ports:
            raise ValueError("missing original Tensor-slot count exceeds Tensor ports")
        if self.tensor_input_ports > self.input_ports or self.tensor_output_ports > self.output_ports:
            raise ValueError("Tensor port counts exceed the original direction counts")
        if self.operations_with_schema + self.operations_without_schema != self.original_instances_verified:
            raise ValueError("schema qualification counts do not cover original operation rows")


@dataclass(frozen=True, slots=True)
class NativeOperatorValueDeclarationIndex:
    """Compact full-scan declaration; symbols are deterministically built on demand."""

    bundle_manifest: ProviderArtifact
    native_port_index: ProviderArtifact
    reference_flow_index: ProviderArtifact
    eto_source: ProviderArtifact
    source_first_ordinal: int
    source_stop_ordinal: int
    source_nodes: int
    operation_rows: int
    input_ports: int
    output_ports: int
    tensor_input_ports: int
    tensor_output_ports: int
    tensor_ports_with_provider_descriptor: int
    tensor_ports_without_provider_descriptor: int
    tensor_ports_without_instance_tensor_slot: int
    formal_ports_resolved: int
    formal_ports_unresolved: int
    declared_may_write_boundaries: int
    schema_may_alias_boundaries: int
    operations_with_schema: int
    operations_without_schema: int
    schema_alias_inventory_incomplete_operations: int
    output_interface_input_versions: int
    output_interface_provenance_records: int
    reference_flow_ports: int
    reference_flow_ports_with_one_original_edge: int
    reference_flow_ports_without_one_original_edge: int
    catalog_definitions: int
    catalog_slots: int
    catalog_effects: int
    catalog_provider_references: int
    catalog_decoded_bytes: int
    catalog_stored_bytes: int
    instance_chunks_decoded_bytes: int
    instance_chunks_stored_bytes: int
    port_shards_decoded_bytes: int
    port_shards_stored_bytes: int
    id_derivation_profile: str
    producer_source_sha256: str
    shard_summaries: tuple[NativeOperatorSourceShardSummary, ...]
    schema: str = "scar.native-operator-value-declaration-index"
    schema_version: int = 1
    terminal_status: str = "ALL_NATIVE_PORT_SHARDS_VALIDATED"
    persisted_operator_symbols: int = 0
    cross_instance_flow_as_parents: bool = False
    port_edge_resolution: str = "LAZY_FROM_SHARED_REFERENCE_FLOW_INDEX"

    def __post_init__(self) -> None:
        for value, name in ((self.bundle_manifest, "bundle manifest"),
                            (self.native_port_index, "native port index"),
                            (self.reference_flow_index, "reference-flow index"),
                            (self.eto_source, "ETO source")):
            _artifact(value, name)
        if self.schema != "scar.native-operator-value-declaration-index" or self.schema_version != 1:
            raise ValueError("unsupported native operator declaration index")
        _digest(self.producer_source_sha256, "producer source SHA")
        if self.id_derivation_profile != "native-port-payload-symbol-v1":
            raise ValueError("unsupported native symbol ID derivation profile")
        if (self.terminal_status != "ALL_NATIVE_PORT_SHARDS_VALIDATED"
                or self.persisted_operator_symbols != 0
                or self.cross_instance_flow_as_parents is not False
                or self.port_edge_resolution != "LAZY_FROM_SHARED_REFERENCE_FLOW_INDEX"):
            raise ValueError("declaration index must remain compact and non-authoritative")
        for name in (
            "source_first_ordinal", "source_stop_ordinal", "source_nodes", "operation_rows",
            "input_ports", "output_ports", "tensor_input_ports", "tensor_output_ports",
            "tensor_ports_with_provider_descriptor", "tensor_ports_without_provider_descriptor",
            "tensor_ports_without_instance_tensor_slot",
            "formal_ports_resolved", "formal_ports_unresolved",
            "declared_may_write_boundaries", "schema_may_alias_boundaries",
            "operations_with_schema", "operations_without_schema",
            "schema_alias_inventory_incomplete_operations",
            "output_interface_input_versions", "output_interface_provenance_records",
            "reference_flow_ports", "reference_flow_ports_with_one_original_edge",
            "reference_flow_ports_without_one_original_edge",
            "catalog_definitions", "catalog_slots", "catalog_effects",
            "catalog_provider_references", "catalog_decoded_bytes", "catalog_stored_bytes",
            "instance_chunks_decoded_bytes", "instance_chunks_stored_bytes",
            "port_shards_decoded_bytes", "port_shards_stored_bytes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative exact integer")
        if self.source_stop_ordinal <= self.source_first_ordinal or self.source_nodes != self.source_stop_ordinal - self.source_first_ordinal:
            raise ValueError("declaration index source range does not match source-node denominator")
        if type(self.shard_summaries) is not tuple or any(
                type(item) is not NativeOperatorSourceShardSummary for item in self.shard_summaries):
            raise TypeError("declaration index shard summaries must be typed")
        if not self.shard_summaries:
            raise ValueError("declaration index must verify every original native-port source shard")
        cursor = self.source_first_ordinal
        for summary in self.shard_summaries:
            if summary.source.first_source_ordinal != cursor:
                raise ValueError("validated native-port source shard ranges are not contiguous")
            cursor = summary.source.stop_source_ordinal
        if cursor != self.source_stop_ordinal:
            raise ValueError("validated native-port source shards do not reach source EOF")
        sum_fields = (
            "original_instances_verified", "input_ports", "output_ports", "tensor_input_ports",
            "tensor_output_ports", "tensor_ports_with_provider_descriptor",
            "tensor_ports_without_provider_descriptor", "tensor_ports_without_instance_tensor_slot",
            "formal_ports_resolved",
            "formal_ports_unresolved", "declared_may_write_boundaries",
            "schema_may_alias_boundaries", "operations_with_schema",
            "operations_without_schema", "schema_alias_inventory_incomplete_operations",
            "output_interface_input_versions", "output_interface_provenance_records",
        )
        for name in sum_fields:
            if sum(getattr(item, name) for item in self.shard_summaries) != getattr(self, name if name != "original_instances_verified" else "operation_rows"):
                raise ValueError(f"full-scan total {name} differs from per-shard sums")
        if self.port_shards_stored_bytes != sum(item.source.stored_bytes for item in self.shard_summaries):
            raise ValueError("port source stored-byte total differs from original shard receipts")
        if self.port_shards_decoded_bytes != sum(item.source.decoded_bytes for item in self.shard_summaries):
            raise ValueError("port source decoded-byte total differs from original shard receipts")
        if (self.reference_flow_ports_with_one_original_edge
                + self.reference_flow_ports_without_one_original_edge != self.reference_flow_ports):
            raise ValueError("shared reference-flow endpoint counts are inconsistent")


@dataclass(slots=True)
class NativeOperatorValueSourceCatalog:
    """In-memory shared source lookup tables; never persisted in the declaration index."""

    bundle_manifest_sha256: str
    definitions: dict[OperationDefinitionID, OperationDefinition]
    effects: dict[EffectSummaryID, EffectSummary]
    slots: dict[ValueSlotID, ValueSlot]
    provider_references: dict[str, ProviderReference]
    decoded_bytes: int
    stored_bytes: int


def _catalog_table_bytes(partitions: BundlePartitions, graph: str,
                         table: str) -> tuple[int, int]:
    descriptor = partitions.manifest["graphs"][graph]["tables"][table]
    return (sum(item["decoded_bytes"] for item in descriptor["chunks"]),
            sum(item["physical_bytes"] for item in descriptor["chunks"]))


def load_native_operator_value_source_catalog(
        bundle_partitions: BundlePartitions | str | Path
        ) -> NativeOperatorValueSourceCatalog:
    """Load shared source records once for one process; no database or new authority."""
    partitions = (bundle_partitions if type(bundle_partitions) is BundlePartitions
                  else BundlePartitions(bundle_partitions))
    definitions: dict[OperationDefinitionID, OperationDefinition] = {}
    effects: dict[EffectSummaryID, EffectSummary] = {}
    slots: dict[ValueSlotID, ValueSlot] = {}
    providers: dict[str, ProviderReference] = {}
    for envelope in partitions.iter_records("semantic", "definitions"):
        record = decode(OperationDefinition, envelope["record"])
        if record.id in definitions:
            raise ValueError("original semantic bundle repeats an OperationDefinition ID")
        definitions[record.id] = record
    for envelope in partitions.iter_records("semantic", "effects"):
        record = decode(EffectSummary, envelope["record"])
        if record.id in effects:
            raise ValueError("original semantic bundle repeats an EffectSummary ID")
        effects[record.id] = record
    for envelope in partitions.iter_records("semantic", "slots"):
        record = decode(ValueSlot, envelope["record"])
        if record.slot_id in slots:
            raise ValueError("original semantic bundle repeats a ValueSlot ID")
        slots[record.slot_id] = record
    for envelope in partitions.iter_records("evidence", "provider_references"):
        record = decode(ProviderReference, envelope["record"])
        if record.reference_id in providers:
            raise ValueError("original evidence bundle repeats a ProviderReference ID")
        providers[record.reference_id] = record
    catalog_tables = (("semantic", "definitions"), ("semantic", "effects"),
                      ("semantic", "slots"), ("evidence", "provider_references"))
    decoded_bytes = stored_bytes = 0
    for graph, table in catalog_tables:
        decoded, stored = _catalog_table_bytes(partitions, graph, table)
        decoded_bytes += decoded
        stored_bytes += stored
    return NativeOperatorValueSourceCatalog(
        partitions.manifest_receipt["physical_sha256"], definitions, effects,
        slots, providers, decoded_bytes, stored_bytes)


def _validate_original_instance_port_row(
        row: NativeInstancePorts, instance: OperationInstance,
        catalog: NativeOperatorValueSourceCatalog, source_sha256: str
        ) -> dict[str, int]:
    """Check one caller-free row against its original bundle facts; return counts only."""
    definition = catalog.definitions.get(row.definition)
    if type(definition) is not OperationDefinition:
        raise ValueError("native port definition is absent from the original semantic bundle")
    if (instance.id != row.instance or instance.definition != row.definition
            or definition.id != row.definition):
        raise ValueError("native port row, original instance and definition identities disagree")
    raw_reference = instance.metadata.get("raw_reference")
    if (instance.metadata.get("provider") != "ETO"
            or raw_reference != f"sha256:{source_sha256}#/nodes/{row.source_ordinal}"):
        raise ValueError("original OperationInstance does not resolve to this exact ETO ordinal")
    if len({(port.direction, port.path) for port in row.ports}) != len(row.ports):
        raise ValueError("original native operation row repeats an ordered port path")
    state_boundaries = _schema_state_boundaries(row, definition, catalog.slots, catalog.effects)
    inputs = [port for port in row.ports if port.direction == "input"]
    outputs = [port for port in row.ports if port.direction == "output"]
    tensor_inputs = [port for port in inputs if port.kind == "TENSOR"]
    tensor_outputs = [port for port in outputs if port.kind == "TENSOR"]
    formal_resolved = sum(port.formal_slot is not None for port in row.ports)
    tensor_descriptor_resolved = 0
    tensor_slot_missing = 0
    raw_tensor_slots = instance.metadata.get("tensor_slots", ())
    if type(raw_tensor_slots) is not list:
        raw_tensor_slots = []
    for port in tensor_inputs + tensor_outputs:
        role = "inputs" if port.direction == "input" else "outputs"
        matching = [item for item in raw_tensor_slots
                    if type(item) is dict and item.get("role") == role
                    and item.get("ordered_path") == list(port.path)]
        if len(matching) > 1:
            raise ValueError("original instance repeats one typed Tensor path")
        if not matching:
            tensor_slot_missing += 1
        else:
            original_slot = matching[0]
            if ((original_slot.get("provider_reference"), original_slot.get("descriptor_id"))
                    != (port.provider_reference, port.descriptor_id)):
                raise ValueError("original Tensor slot provider/descriptor differs from the retained boxed port")
            binding = original_slot.get("native_schema_binding")
            if type(binding) is dict and port.formal_slot is not None:
                actual_formal = binding.get("formal_slot")
                if (type(actual_formal) is not dict
                        or actual_formal.get("wire") != port.formal_slot.wire):
                    raise ValueError("original Tensor slot formal differs from its native port formal")
        provider = catalog.provider_references.get(port.provider_reference or "")
        representation, device = _descriptor(provider, port)
        if (port.provider_reference is not None and port.descriptor_id is not None
                and representation != "unknown.tensor.representation" and device != "unknown"):
            tensor_descriptor_resolved += 1
    contract = definition.metadata.get("native_schema_contract")
    has_schema = type(contract) is dict and type(contract.get("schema_sha256")) is str
    alias_inventory_incomplete = int(
        has_schema and contract.get("alias_pair_inventory_complete") is False)
    output_has_tensor = bool(tensor_outputs)
    return {
        "input_ports": len(inputs), "output_ports": len(outputs),
        "tensor_input_ports": len(tensor_inputs), "tensor_output_ports": len(tensor_outputs),
        "tensor_ports_with_provider_descriptor": tensor_descriptor_resolved,
        "tensor_ports_without_provider_descriptor": len(tensor_inputs) + len(tensor_outputs) - tensor_descriptor_resolved,
        "tensor_ports_without_instance_tensor_slot": tensor_slot_missing,
        "formal_ports_resolved": formal_resolved,
        "formal_ports_unresolved": len(row.ports) - formal_resolved,
        "declared_may_write_boundaries": sum(item.relation == "DECLARED_MAY_WRITE" for item in state_boundaries),
        "schema_may_alias_boundaries": sum(item.relation == "SCHEMA_MAY_ALIAS" for item in state_boundaries),
        "operations_with_schema": int(has_schema),
        "operations_without_schema": int(not has_schema),
        "schema_alias_inventory_incomplete_operations": alias_inventory_incomplete,
        "output_interface_input_versions": len(tensor_inputs) if output_has_tensor else 0,
        "output_interface_provenance_records": int(output_has_tensor),
    }


def _descriptor(provider: ProviderReference | None, port: NativeBoxedPort) -> tuple[str, str]:
    if (provider is None or port.provider_reference is None or port.descriptor_id is None):
        return (port.provider_type or "unknown.tensor.representation", "unknown")
    if provider.reference_id != port.provider_reference:
        raise ValueError("port provider token differs from original ProviderReference")
    descriptors = [item for item in provider.metadata.get("descriptors", ())
                   if type(item) is dict and item.get("descriptor_id") == port.descriptor_id]
    if not descriptors:
        return (port.provider_type or "unknown.tensor.representation", "unknown")
    if len(descriptors) != 1:
        raise ValueError("original provider descriptor is ambiguous")
    descriptor = descriptors[0]
    representation = descriptor.get("type")
    if type(representation) is not str or representation != port.provider_type:
        raise ValueError("provider type differs from original Tensor descriptor")
    device = descriptor.get("device")
    if device is None:
        tensor_tuple = descriptor.get("tensor_tuple")
        if type(tensor_tuple) is list and len(tensor_tuple) >= 6:
            device = tensor_tuple[5]
    if type(device) is not str or not device:
        device = "unknown"
    return representation, device


def _binding_ids(scope, tensor: bool):
    return _symbol_ids(scope) if tensor else (None, None, None, None)


def _exact_port_edge(row: NativeInstancePorts, port: NativeBoxedPort,
                     flow_index, flow_root: Path,
                     shard_cache: dict[int, dict[str, Any]] | None = None
                     ) -> EvidenceEdgeRef | None:
    if port.kind != "TENSOR" or not port.provider_reference or not port.descriptor_id:
        return None
    bucket = _bucket(port.provider_reference, flow_index.bucket_count)
    refs = [item for item in flow_index.shards if item.bucket == bucket]
    if len(refs) != 1:
        return None
    shard = shard_cache.get(bucket) if shard_cache is not None else None
    if shard is None:
        shard = _read_flow_shard(flow_root, refs[0])
        if shard_cache is not None:
            shard_cache[bucket] = shard
    group = shard["groups"].get(_group_key(port.provider_reference, port.descriptor_id))
    if group is None:
        return None
    if (group.get("provider_reference") != port.provider_reference
            or group.get("descriptor_id") != port.descriptor_id):
        raise ValueError("reference-flow group does not match the original port provider/descriptor")
    group_rows = group["inputs"] if port.direction == "input" else group["outputs"]
    expected_port_id = _port_id(row.source_ordinal, port.direction, port.path)
    matches = [raw for raw in group_rows
               if raw.get("instance", {}).get("wire") == row.instance.wire
               and raw.get("definition", {}).get("wire") == row.definition.wire
               and raw.get("source_ordinal") == row.source_ordinal
               and raw.get("port_id") == expected_port_id
               and raw.get("source_locator") == port.source_locator
               and raw.get("formal_slot") == (None if port.formal_slot is None else port.formal_slot.as_dict())
               and raw.get("provider_reference") == port.provider_reference
               and raw.get("descriptor_id") == port.descriptor_id]
    if len(matches) != 1:
        return None
    endpoint = _endpoint(matches[0], matches[0]["evidence_edge_id"])
    if (endpoint.instance != row.instance or endpoint.definition != row.definition
            or endpoint.path != port.path or endpoint.direction != port.direction):
        raise ValueError("reference-flow endpoint differs from the original native port")
    return EvidenceEdgeRef(flow_index.evidence_bundle_manifest, endpoint.evidence_edge_id)


def _schema_state_boundaries(row: NativeInstancePorts,
                             definition: OperationDefinition,
                             slots: Mapping[ValueSlotID, ValueSlot],
                             effects: Mapping[EffectSummaryID, EffectSummary]
                             ) -> tuple[NativeSchemaStateBoundary, ...]:
    contract = definition.metadata.get("native_schema_contract")
    if type(contract) is not dict:
        contract = {}
    schema_sha = contract.get("schema_sha256")
    if schema_sha is not None:
        _digest(schema_sha, "schema contract SHA")
    effect = effects.get(definition.effect_summary) if definition.effect_summary else None
    if definition.effect_summary is not None and (
            type(effect) is not EffectSummary or effect.id != definition.effect_summary):
        raise ValueError("operation definition does not resolve to its original EffectSummary")

    by_formal: dict[str, list[NativeBoxedPort]] = {}
    boundaries = []
    for port in row.ports:
        if port.formal_slot is None:
            continue
        slot = slots.get(port.formal_slot)
        if slot is None or slot.owner != row.definition:
            raise ValueError("native port formal slot is absent or owned by another definition")
        expected_direction = "input" if port.direction == "input" else "output"
        if slot.direction != expected_direction:
            raise ValueError("native port formal slot direction differs from its source port")
        by_formal.setdefault(slot.slot_id.wire, []).append(port)
        native_slot = slot.metadata.get("native_schema")
        declared_write = (type(native_slot) is dict
                          and native_slot.get("declared_may_write") is True)
        if port.direction == "input" and (slot.mutable is True or declared_write):
            if slot.mutable is not True or not declared_write:
                raise ValueError("mutable input slot and version-pinned schema may-write declaration disagree")
            if effect is None or not any(
                    target.kind is EffectTargetKind.VALUE_SLOT
                    and target.reference == slot.slot_id.wire
                    for target in effect.writes.members):
                raise ValueError("declared mutable formal does not resolve to the original EffectSummary write target")
            if type(native_slot.get("schema_sha256")) is not str:
                raise ValueError("declared may-write slot lacks its original schema SHA")
            boundaries.append(NativeSchemaStateBoundary(
                "DECLARED_MAY_WRITE", definition.effect_summary,
                native_slot["schema_sha256"], slot.slot_id,
                _port_id(row.source_ordinal, port.direction, port.path)))

    aliases = contract.get("possible_aliases", ())
    if type(aliases) is list:
        for pair in aliases:
            if (type(pair) is not dict or type(pair.get("left")) is not dict
                    or type(pair.get("right")) is not dict):
                continue
            left_wire = pair["left"].get("wire")
            right_wire = pair["right"].get("wire")
            if type(left_wire) is not str or type(right_wire) is not str:
                continue
            for left in by_formal.get(left_wire, ()):
                for right in by_formal.get(right_wire, ()):
                    if schema_sha is None:
                        raise ValueError("schema may-alias relation lacks its original schema SHA")
                    boundaries.append(NativeSchemaStateBoundary(
                        "SCHEMA_MAY_ALIAS", definition.effect_summary, schema_sha,
                        left.formal_slot, _port_id(row.source_ordinal, left.direction, left.path),
                        right.formal_slot, _port_id(row.source_ordinal, right.direction, right.path)))
    return tuple(boundaries)


def build_native_operator_value_fragment(
        port_rows: Sequence[NativeInstancePorts], *,
        instances: Mapping[OperationInstanceID, OperationInstance],
        definitions: Mapping[OperationDefinitionID, OperationDefinition],
        effects: Mapping[EffectSummaryID, EffectSummary],
        slots: Mapping[ValueSlotID, ValueSlot],
        provider_references: Mapping[str, ProviderReference],
        port_index: NativePortIndex, port_index_artifact: ProviderArtifact,
        bundle_manifest: ProviderArtifact, eto_source: ProviderArtifact,
        flow_index, flow_index_artifact: ProviderArtifact,
        flow_publication: str | Path,
        physical_candidates: Sequence[NativePhysicalCandidateRef] = (),
        resolve_original_edges: bool = True) -> tuple[NativeOperatorValueFragment, ValueGraph]:
    """Build a small ValueGraph delta for caller-qualified original instances.

    This function does not replay the complete bundle or ETO; it checks each
    supplied instance/definition against the supplied receipt-bound native
    port row, and names endpoint symbols from those original qualified IDs.
    """
    _artifact(port_index_artifact, "native port index artifact")
    _artifact(bundle_manifest, "bundle manifest")
    _artifact(eto_source, "ETO source")
    _artifact(flow_index_artifact, "reference-flow index artifact")
    if (eto_source.uri != port_index.source_uri or eto_source.sha256 != port_index.source_sha256):
        raise ValueError("supplied ETO artifact differs from the native port index source")
    if flow_index.native_port_index.sha256 != port_index_artifact.sha256:
        raise ValueError("reference-flow index was built from another native-port index")
    if flow_index.evidence_bundle_manifest.sha256 != bundle_manifest.sha256:
        raise ValueError("reference-flow index was built from another evidence bundle")
    if flow_index.eto_source.sha256 != eto_source.sha256:
        raise ValueError("flow and native port indexes refer to different original ETO sources")
    if len({row.instance for row in port_rows}) != len(port_rows):
        raise ValueError("input contains duplicate original operation rows")
    graph = ValueGraph()
    interfaces = []
    flow_root = Path(flow_publication).resolve()
    edge_shard_cache: dict[int, dict[str, Any]] = {}

    for row in sorted(port_rows, key=lambda item: item.source_ordinal):
        instance = instances.get(row.instance)
        definition = definitions.get(row.definition)
        if type(instance) is not OperationInstance or type(definition) is not OperationDefinition:
            raise ValueError("each native port row needs its original instance and semantic definition")
        if instance.id != row.instance or instance.definition != row.definition or definition.id != row.definition:
            raise ValueError("native port row, original instance, and definition identities disagree")
        effect_summary = effects.get(definition.effect_summary) if definition.effect_summary else None
        if definition.effect_summary is not None and (
                type(effect_summary) is not EffectSummary
                or effect_summary.id != definition.effect_summary):
            raise ValueError("operation definition does not resolve to its original EffectSummary")
        raw_ref = instance.metadata.get("raw_reference")
        expected_ref = f"sha256:{port_index.source_sha256}#/nodes/{row.source_ordinal}"
        if raw_ref != expected_ref or instance.metadata.get("provider") != "ETO":
            raise ValueError("original operation does not resolve to this exact ETO source ordinal")
        if not port_index.first_source_ordinal <= row.source_ordinal < port_index.stop_source_ordinal:
            raise ValueError("original operation source ordinal lies outside native-port index range")

        input_ports = [item for item in row.ports if item.direction == "input"]
        output_ports = [item for item in row.ports if item.direction == "output"]
        if input_ports + output_ports != sorted(row.ports, key=lambda item: (0 if item.direction == "input" else 1, item.path)):
            raise ValueError("native ports are not represented in stable direction/path order")
        input_symbols = []
        output_symbols = []
        provisional: dict[tuple[str, tuple[int, ...]], tuple[LogicalValueID | None, ValueVersionID | None, ProvenanceID | None, MaterializationID | None]] = {}
        for port in row.ports:
            if port.kind != "TENSOR":
                continue
            ids = _binding_ids(_port_scope(bundle_manifest, port_index_artifact,
                                           eto_source, row, port), True)
            logical_id, version_id, provenance_id, materialization_id = ids
            semantic_type = "torch.tensor.payload.symbolic"
            role = "reported_argument_payload" if port.direction == "input" else "reported_result_payload"
            graph.add_logical_value(LogicalValue(
                logical_id, semantic_type,
                "Endpoint-local symbol for this original ETO Tensor port; numeric contents unknown.",
                {"role": role, "identity_semantics": _IDENTITY_SEMANTICS,
                 "provider_reference": port.provider_reference,
                 "descriptor_id": port.descriptor_id,
                 "source_ordinal": row.source_ordinal, "source_locator": port.source_locator,
                 "formal_slot": None if port.formal_slot is None else port.formal_slot.wire,
                 "evidence_status": "Inferred"}))
            provisional[(port.direction, port.path)] = ids
            if port.direction == "input":
                input_symbols.append((logical_id, version_id, provenance_id, materialization_id))
            else:
                output_symbols.append((logical_id, version_id, provenance_id, materialization_id))

        op_provenance = None
        input_versions = tuple(item[1] for item in input_symbols)
        output_versions = tuple(item[1] for item in output_symbols)
        if output_symbols:
            token = sha256((row.instance.wire + "\0reported-argument-interface").encode()).hexdigest()
            op_provenance = ProvenanceID("native-operator-interface:" + token)
            graph.add_provenance(ProvenanceRecord(
                op_provenance, ProvenanceRelation.UNKNOWN, input_versions,
                output_versions, producer=row.instance,
                equivalence=EquivalenceClaim.UNKNOWN, evidence="Inferred",
                metadata={"relation_semantics": "reported-argument-interface-dependency-only",
                          "interface_input_universe": "Tensor input port symbols only; scalar/container port values retain original ordered ports without payload symbols",
                          "content_transform": "UNKNOWN",
                          "actual_read": "UNKNOWN",
                          "actual_write": "UNKNOWN",
                          "parent_set_complete": False,
                          "parent_set_minimal": False,
                          "normal_completion": "UNKNOWN",
                          "alias_and_copy": "UNKNOWN",
                          "storage_binding": "UNKNOWN",
                          "ready_state": "UNKNOWN",
                          "cross_instance_candidates_are_not_parents": True,
                          "source_ordinal_is_not_causality": True,
                          "original_operation_instance": row.instance.wire}))

        bindings: dict[tuple[str, tuple[int, ...]], NativeOperatorPortBinding] = {}
        for port in row.ports:
            tensor_ids = provisional.get((port.direction, port.path))
            logical_id, version_id, port_prov_id, materialization_id = tensor_ids or (None, None, None, None)
            if tensor_ids is not None:
                representation, device = _descriptor(
                    provider_references.get(port.provider_reference or ""), port)
                parents = input_versions if port.direction == "output" else ()
                provenance = op_provenance if port.direction == "output" else port_prov_id
                if port.direction == "input":
                    graph.add_provenance(ProvenanceRecord(
                        port_prov_id, ProvenanceRelation.UNKNOWN, (), (version_id,),
                        producer=None, equivalence=EquivalenceClaim.UNKNOWN,
                        evidence="Inferred", metadata={
                            "relation_semantics": "reported-argument-endpoint-symbol",
                            "content_origin": "UNKNOWN", "identity_semantics": _IDENTITY_SEMANTICS,
                            "source_ordinal": row.source_ordinal,
                            "source_locator": port.source_locator}))
                graph.add_version(ValueVersion(
                    version_id, provenance, parents, "torch.tensor.payload.symbolic",
                    metadata={"identity_semantics": _IDENTITY_SEMANTICS,
                              "endpoint_role": "reported_argument" if port.direction == "input" else "reported_result",
                              "revision_semantics": "endpoint-local-symbol; not Tensor._version"}))
                graph.add_materialization(Materialization(
                    materialization_id, version_id, representation, device, region=None,
                    producer=row.instance if port.direction == "output" else None,
                    ready_event=None, validity_scope=None, evidence="Inferred",
                    metadata={"representation_device_source": port.descriptor_id or "unresolved-provider-descriptor",
                              "association": "reported native Tensor port symbol",
                              "storage_region": "UNKNOWN",
                              "normal_completion": "UNKNOWN",
                              "ready_state": "UNKNOWN",
                              "physical_candidate_binding": "NOT_ASSERTED"}))
            binding = NativeOperatorPortBinding(
                _port_id(row.source_ordinal, port.direction, port.path),
                port.direction, port.path, port.source_locator, port.kind,
                port.provider_type, port.formal_slot, port.formal_status,
                port.provider_reference, port.descriptor_id,
                (_exact_port_edge(row, port, flow_index, flow_root, edge_shard_cache)
                 if resolve_original_edges else None),
                logical_id, version_id, materialization_id)
            bindings[(port.direction, port.path)] = binding

        schema_contract = definition.metadata.get("native_schema_contract")
        if type(schema_contract) is not dict:
            schema_contract = {}
        schema_sha = schema_contract.get("schema_sha256")
        if schema_sha is not None:
            _digest(schema_sha, "schema contract SHA")
        state_boundaries = _schema_state_boundaries(row, definition, slots, effects)

        identity_scope = (bundle_manifest.uri, bundle_manifest.sha256,
                          port_index_artifact.uri, port_index_artifact.sha256,
                          eto_source.sha256, row.instance.wire,
                          row.definition.wire, row.source_ordinal)
        interface_id = "native-operator-interface:" + sha256(json.dumps(
            identity_scope, separators=(",", ":")).encode()).hexdigest()
        interfaces.append(NativeOperatorValueInterface(
            interface_id, row.instance, row.definition, row.source_ordinal,
            definition.label, schema_sha, schema_contract.get("provider_revision"),
            definition.effect_summary, tuple(definition.state_slots),
            tuple(bindings[("input", item.path)] for item in input_ports),
            tuple(bindings[("output", item.path)] for item in output_ports),
            state_boundaries,
            schema_alias_pair_inventory_complete=schema_contract.get(
                "alias_pair_inventory_complete")))

    fragment = NativeOperatorValueFragment(
        bundle_manifest, port_index_artifact, flow_index_artifact,
        eto_source, tuple(interfaces), tuple(physical_candidates))
    graph.assert_valid()
    _validate_fragment(fragment, graph)
    return fragment, graph


def _validate_fragment(fragment: NativeOperatorValueFragment, graph: ValueGraph) -> None:
    graph.assert_valid()
    expected_tensor_ports = [binding for interface in fragment.interfaces
                             for binding in interface.inputs + interface.outputs
                             if binding.kind == "TENSOR"]
    counts = graph.validate()["counts"]
    expected_input_ports = sum(1 for interface in fragment.interfaces
                               for item in interface.inputs if item.kind == "TENSOR")
    expected_counts = {"logical_values": len(expected_tensor_ports),
                  "versions": len(expected_tensor_ports),
                  "provenance": expected_input_ports + sum(
                      1 for interface in fragment.interfaces
                      if any(item.kind == "TENSOR" for item in interface.outputs)),
                  "allocations": 0, "regions": 0,
                  "materializations": len(expected_tensor_ports), "bindings": 0}
    if counts != expected_counts:
        raise ValueError(f"ValueGraph delta count does not match original Tensor ports: {counts!r} != {expected_counts!r}")
    for interface in fragment.interfaces:
        input_versions = tuple(item.value_version for item in interface.inputs
                               if item.kind == "TENSOR")
        output_versions = tuple(item.value_version for item in interface.outputs
                                if item.kind == "TENSOR")
        for binding in interface.inputs + interface.outputs:
            if binding.kind == "TENSOR" and (binding.value_version not in graph.versions
                    or binding.materialization not in graph.materializations):
                raise ValueError("native Tensor port does not resolve to its existing ValueGraph symbol")
        if output_versions:
            version = graph.versions[output_versions[0]]
            record = graph.provenance[version.provenance_id]
            if (record.relation is not ProvenanceRelation.UNKNOWN
                    or record.evidence != "Inferred"
                    or record.producer != interface.instance
                    or record.inputs != input_versions
                    or record.outputs != output_versions
                    or version.parent_versions != input_versions
                    or record.metadata.get("parent_set_complete") is not False
                    or record.metadata.get("parent_set_minimal") is not False
                    or record.metadata.get("content_transform") != "UNKNOWN"
                    or record.metadata.get("actual_read") != "UNKNOWN"
                    or record.metadata.get("actual_write") != "UNKNOWN"
                    or record.metadata.get("normal_completion") != "UNKNOWN"
                    or record.metadata.get("ready_state") != "UNKNOWN"
                    or record.metadata.get("cross_instance_candidates_are_not_parents") is not True):
                raise ValueError("operator result provenance exceeds reported interface boundary")
        for binding in interface.inputs:
            if binding.kind != "TENSOR":
                continue
            version = graph.versions[binding.value_version]
            record = graph.provenance[version.provenance_id]
            if (record.relation is not ProvenanceRelation.UNKNOWN
                    or record.evidence != "Inferred" or record.producer is not None
                    or record.inputs or record.outputs != (version.id,)
                    or record.metadata.get("content_origin") != "UNKNOWN"):
                raise ValueError("reported input symbol was upgraded to an observed payload origin")
        port_by_id = {binding.port_id: binding
                      for binding in interface.inputs + interface.outputs}
        for boundary in interface.state_boundaries:
            if boundary.status != "DECLARED_MAY_ONLY" or boundary.effect_summary != interface.effect_summary:
                raise ValueError("schema state boundary changed its original effect reference/status")
            left = port_by_id.get(boundary.left_port_id)
            right = port_by_id.get(boundary.right_port_id) if boundary.right_port_id else None
            if (left is None or left.formal_slot != boundary.left_formal_slot
                    or (boundary.relation == "SCHEMA_MAY_ALIAS"
                        and (right is None or right.formal_slot != boundary.right_formal_slot))):
                raise ValueError("schema state boundary does not resolve to its exact original formal port(s)")


def write_native_operator_value_fragment(path: str | Path,
                                         fragment: NativeOperatorValueFragment,
                                         graph: ValueGraph) -> str:
    _validate_fragment(fragment, graph)
    document = {"schema": _SCHEMA, "schema_version": _VERSION,
                "fragment": encode(fragment), "value_graph_delta": graph.to_dict()}
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
    if len(payload) > _MAX_BYTES:
        raise ValueError("native operator value fragment exceeds its fixed byte bound")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(payload).hexdigest()


def _read_small(path: str | Path) -> bytes:
    target = Path(path)
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > _MAX_BYTES:
            raise ValueError("native operator value fragment is not a bounded regular file")
        payload = bytearray()
        while len(payload) < before.st_size:
            block = os.read(fd, min(16_384, before.st_size - len(payload)))
            if not block:
                break
            payload.extend(block)
        after = os.fstat(fd)
        if len(payload) != before.st_size or (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino,
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("native operator value fragment changed during read")
        return bytes(payload)
    finally:
        os.close(fd)


def read_native_operator_value_fragment(path: str | Path, *, expected_sha256: str | None = None
                                        ) -> tuple[NativeOperatorValueFragment, ValueGraph]:
    payload = _read_small(path)
    digest = sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("native operator value fragment SHA mismatch")
    document = loads(payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "fragment", "value_graph_delta"}
            or document["schema"] != _SCHEMA or type(document["schema_version"]) is not int
            or document["schema_version"] != _VERSION):
        raise ValueError("native operator value fragment header mismatch")
    fragment = decode(NativeOperatorValueFragment, document["fragment"])
    graph = values_from_dict(document["value_graph_delta"])
    _validate_fragment(fragment, graph)
    return fragment, graph


def build_native_operator_value_declaration_publication(
        native_port_publication: str | Path,
        bundle_partitions: BundlePartitions | str | Path,
        reference_flow_publication: str | Path,
        output_dir: str | Path, *,
        expected_native_port_index_sha256: str | None = None,
        expected_reference_flow_index_sha256: str | None = None,
        catalog: NativeOperatorValueSourceCatalog | None = None
        ) -> tuple[NativeOperatorValueDeclarationIndex, str]:
    """Validate every original native port shard and publish only a compact recipe/index.

    The full pass writes no per-operation ValueGraph, symbols, schema records,
    or EvidenceEdges. A selected endpoint gets its normal typed fragment from
    ``query_native_operator_value_fragment_from_declaration`` on demand.
    """
    partitions = (bundle_partitions if type(bundle_partitions) is BundlePartitions
                  else BundlePartitions(bundle_partitions))
    port_root = Path(native_port_publication).resolve()
    port_index = read_native_port_index(
        port_root, expected_sha256=expected_native_port_index_sha256)
    port_index_path = (port_root / "index.json").resolve()
    port_index_payload = port_index_path.read_bytes()
    port_index_sha = sha256(port_index_payload).hexdigest()
    port_index_artifact = ProviderArtifact(
        str(port_index_path), port_index_sha, len(port_index_payload),
        "scar.native-boxed-port-index")
    if _manifest_identity(partitions) != _identity_from_values(port_index):
        raise ValueError("native port publication belongs to another evidence bundle")
    bundle_artifact = ProviderArtifact(
        partitions.manifest_receipt["path"], partitions.manifest_receipt["physical_sha256"],
        partitions.manifest_receipt["physical_bytes"], partitions.manifest["schema"])
    flow_root = Path(reference_flow_publication).resolve()
    flow_index, flow_sha = read_native_reference_flow_index(
        flow_root, expected_sha256=expected_reference_flow_index_sha256)
    flow_index_path = (flow_root / "index.json").resolve()
    flow_index_payload = flow_index_path.read_bytes()
    flow_artifact = ProviderArtifact(
        str(flow_index_path), flow_sha, len(flow_index_payload),
        "scar.native-reference-flow-index")
    eto_artifact = ProviderArtifact(
        port_index.source_uri, port_index.source_sha256,
        port_index.source_raw_bytes, "pytorch.execution-trace.v1")
    if (flow_index.native_port_index.uri != str(port_index_path)
            or flow_index.native_port_index.sha256 != port_index_sha
            or flow_index.evidence_bundle_manifest.sha256 != bundle_artifact.sha256
            or flow_index.evidence_bundle_manifest.uri != bundle_artifact.uri
            or flow_index.eto_source.sha256 != eto_artifact.sha256
            or flow_index.eto_source.uri != eto_artifact.uri):
        raise ValueError("native port, bundle, ETO and reference-flow receipts do not share one source scope")
    if (flow_index.source_nodes != port_index.source_nodes
            or flow_index.operation_rows != port_index.operation_rows
            or flow_index.native_ports != port_index.input_ports + port_index.output_ports):
        raise ValueError("reference-flow and native-port full-source denominators disagree")

    if catalog is None:
        catalog = load_native_operator_value_source_catalog(partitions)
    if (type(catalog) is not NativeOperatorValueSourceCatalog
            or catalog.bundle_manifest_sha256 != bundle_artifact.sha256):
        raise ValueError("in-memory source catalog belongs to another original bundle")

    count_names = (
        "original_instances_verified", "input_ports", "output_ports",
        "tensor_input_ports", "tensor_output_ports",
        "tensor_ports_with_provider_descriptor", "tensor_ports_without_provider_descriptor",
        "tensor_ports_without_instance_tensor_slot", "formal_ports_resolved",
        "formal_ports_unresolved", "declared_may_write_boundaries",
        "schema_may_alias_boundaries", "operations_with_schema", "operations_without_schema",
        "schema_alias_inventory_incomplete_operations", "output_interface_input_versions",
        "output_interface_provenance_records",
    )
    shard_counts = [{name: 0 for name in count_names} for _ in port_index.shards]
    instance_chunk_receipts: dict[str, dict[str, Any]] = {}
    seen_instances: set[OperationInstanceID] = set()
    port_root = port_root.resolve()

    def ordered_port_rows():
        previous_ordinal = port_index.first_source_ordinal - 1
        for shard_number, shard_ref in enumerate(port_index.shards):
            source_shard = _read_shard(port_root, shard_ref)
            if len(source_shard.rows) != shard_ref.operation_rows:
                raise ValueError("receipt-checked native port shard row count changed")
            ordinals = tuple(row.source_ordinal for row in source_shard.rows)
            if len(set(ordinals)) != len(ordinals):
                raise ValueError("native port source shard repeats an ETO ordinal")
            for row in source_shard.rows:
                if row.source_ordinal <= previous_ordinal:
                    raise ValueError("native port source ordinals are not globally increasing")
                previous_ordinal = row.source_ordinal
                yield shard_number, row

    row_iter = iter(ordered_port_rows())
    pending = next(row_iter, None)
    instance_chunks = partitions.manifest["graphs"]["evidence"]["tables"]["instances"]["chunks"]
    for instance_chunk in instance_chunks:
        first, last = instance_chunk["first_ordinal"], instance_chunk["last_ordinal"]
        batch = []
        while pending is not None and pending[1].source_ordinal <= last:
            if pending[1].source_ordinal < first:
                raise ValueError("native port source ordinal is outside the original instance chunk range")
            batch.append(pending)
            pending = next(row_iter, None)
        if not batch:
            continue
        ordinals = tuple(row.source_ordinal for _, row in batch)
        original_rows = partitions.selected_records("evidence", "instances", ordinals)
        by_ordinal: dict[int, OperationInstance] = {}
        for envelope, ordinal in zip(original_rows, ordinals, strict=True):
            if envelope["ordinal"] != ordinal:
                raise ValueError("bundle instance ordinal differs from the original ETO source ordinal")
            chunk = envelope["locator"]["artifact"]
            if chunk != instance_chunk:
                raise ValueError("selected original instance did not resolve to its ordered bundle chunk")
            previous = instance_chunk_receipts.get(chunk["uri"])
            if previous is not None and previous != chunk:
                raise ValueError("bundle instance chunk receipt changed during the full-source pass")
            instance_chunk_receipts[chunk["uri"]] = chunk
            instance = decode(OperationInstance, envelope["record"])
            if instance.id in seen_instances:
                raise ValueError("native port publication repeats an original operation instance")
            seen_instances.add(instance.id)
            by_ordinal[ordinal] = instance

        for shard_number, row in batch:
            instance = by_ordinal.get(row.source_ordinal)
            if instance is None:
                raise ValueError("receipt-selected original operation instance is absent")
            delta = _validate_original_instance_port_row(
                row, instance, catalog, port_index.source_sha256)
            if instance.definition != row.definition:
                raise ValueError("original operation definition differs from its native port row")
            counts = shard_counts[shard_number]
            counts["original_instances_verified"] += 1
            for key, value in delta.items():
                counts[key] += value

    if pending is not None:
        raise ValueError("native port source ordinal lies beyond the original instance table EOF")
    shard_summaries = []
    for shard_ref, counts in zip(port_index.shards, shard_counts, strict=True):
        shard_summaries.append(NativeOperatorSourceShardSummary(shard_ref, **counts))

    if sum(item.original_instances_verified for item in shard_summaries) != port_index.operation_rows:
        raise ValueError("full-source native operation row total differs from the receipt-bound index")
    instance_decoded = sum(item["decoded_bytes"] for item in instance_chunk_receipts.values())
    instance_stored = sum(item["physical_bytes"] for item in instance_chunk_receipts.values())
    total = lambda name: sum(getattr(item, name) for item in shard_summaries)
    index = NativeOperatorValueDeclarationIndex(
        bundle_manifest=bundle_artifact,
        native_port_index=port_index_artifact,
        reference_flow_index=flow_artifact,
        eto_source=eto_artifact,
        source_first_ordinal=port_index.first_source_ordinal,
        source_stop_ordinal=port_index.stop_source_ordinal,
        source_nodes=port_index.source_nodes,
        operation_rows=port_index.operation_rows,
        input_ports=port_index.input_ports,
        output_ports=port_index.output_ports,
        tensor_input_ports=total("tensor_input_ports"),
        tensor_output_ports=total("tensor_output_ports"),
        tensor_ports_with_provider_descriptor=total("tensor_ports_with_provider_descriptor"),
        tensor_ports_without_provider_descriptor=total("tensor_ports_without_provider_descriptor"),
        tensor_ports_without_instance_tensor_slot=total("tensor_ports_without_instance_tensor_slot"),
        formal_ports_resolved=total("formal_ports_resolved"),
        formal_ports_unresolved=total("formal_ports_unresolved"),
        declared_may_write_boundaries=total("declared_may_write_boundaries"),
        schema_may_alias_boundaries=total("schema_may_alias_boundaries"),
        operations_with_schema=total("operations_with_schema"),
        operations_without_schema=total("operations_without_schema"),
        schema_alias_inventory_incomplete_operations=total("schema_alias_inventory_incomplete_operations"),
        output_interface_input_versions=total("output_interface_input_versions"),
        output_interface_provenance_records=total("output_interface_provenance_records"),
        reference_flow_ports=flow_index.reference_ports,
        reference_flow_ports_with_one_original_edge=flow_index.ports_with_one_original_edge,
        reference_flow_ports_without_one_original_edge=flow_index.ports_without_one_original_edge,
        catalog_definitions=len(catalog.definitions),
        catalog_slots=len(catalog.slots),
        catalog_effects=len(catalog.effects),
        catalog_provider_references=len(catalog.provider_references),
        catalog_decoded_bytes=catalog.decoded_bytes,
        catalog_stored_bytes=catalog.stored_bytes,
        instance_chunks_decoded_bytes=instance_decoded,
        instance_chunks_stored_bytes=instance_stored,
        port_shards_decoded_bytes=sum(item.source.decoded_bytes for item in shard_summaries),
        port_shards_stored_bytes=sum(item.source.stored_bytes for item in shard_summaries),
        id_derivation_profile="native-port-payload-symbol-v1",
        producer_source_sha256=sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        shard_summaries=tuple(shard_summaries))
    payload = json.dumps({"schema": index.schema, "schema_version": index.schema_version,
                          "value": encode(index)}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8") + b"\n"
    if len(payload) > _MAX_BYTES:
        raise ValueError("compact native operator declaration index exceeds its fixed byte budget")
    target = Path(output_dir).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=False)
    index_path = target / "index.json"
    with index_path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return index, sha256(payload).hexdigest()


def read_native_operator_value_declaration_index(
        publication: str | Path, *, expected_sha256: str | None = None
        ) -> tuple[NativeOperatorValueDeclarationIndex, str]:
    path = Path(publication)
    if path.is_dir():
        path = path / "index.json"
    payload = _read_small(path)
    digest = sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("native operator declaration index SHA mismatch")
    document = loads(payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "value"}
            or document["schema"] != "scar.native-operator-value-declaration-index"
            or type(document["schema_version"]) is not int or document["schema_version"] != 1):
        raise ValueError("native operator declaration index header mismatch")
    index = decode(NativeOperatorValueDeclarationIndex, document["value"])
    return index, digest


def query_native_operator_value_fragment_from_declaration(
        publication: str | Path, instance: OperationInstance, *,
        expected_index_sha256: str | None = None,
        catalog: NativeOperatorValueSourceCatalog | None = None
        ) -> tuple[NativeOperatorValueFragment, ValueGraph]:
    """Derive one normal typed interface from a fully validated compact index."""
    if type(instance) is not OperationInstance:
        raise TypeError("on-demand native value query requires an original OperationInstance")
    index, _ = read_native_operator_value_declaration_index(
        publication, expected_sha256=expected_index_sha256)
    if sha256(Path(__file__).resolve().read_bytes()).hexdigest() != index.producer_source_sha256:
        raise ValueError("declaration ID recipe was produced by another source version")
    prefix = f"sha256:{index.eto_source.sha256}#/nodes/"
    raw_reference = instance.metadata.get("raw_reference")
    if type(raw_reference) is not str or not raw_reference.startswith(prefix):
        raise ValueError("original operation instance does not reference the declaration ETO source")
    suffix = raw_reference[len(prefix):]
    if not suffix.isdecimal():
        raise ValueError("original operation instance lacks an exact ETO source ordinal")
    ordinal = int(suffix)
    shard_summaries = [item for item in index.shard_summaries
                       if item.source.first_source_ordinal <= ordinal < item.source.stop_source_ordinal]
    if len(shard_summaries) != 1:
        raise KeyError("original source ordinal is not covered by one validated native port shard")
    bundle_path = index.bundle_manifest.uri
    partitions = BundlePartitions(bundle_path)
    if partitions.manifest_receipt["physical_sha256"] != index.bundle_manifest.sha256:
        raise ValueError("query source bundle differs from the compact declaration index")
    port_publication = Path(index.native_port_index.uri).parent
    port_index = read_native_port_index(
        port_publication, expected_sha256=index.native_port_index.sha256)
    flow_publication = Path(index.reference_flow_index.uri).parent
    flow_index, _ = read_native_reference_flow_index(
        flow_publication, expected_sha256=index.reference_flow_index.sha256)
    original_row = query_native_ports(
        instance, port_publication, bundle_path,
        expected_index_sha256=index.native_port_index.sha256)
    if original_row.source_ordinal != ordinal or original_row.definition != instance.definition:
        raise ValueError("query native port row differs from the validated original operation reference")
    if catalog is None:
        catalog = load_native_operator_value_source_catalog(partitions)
    if (type(catalog) is not NativeOperatorValueSourceCatalog
            or catalog.bundle_manifest_sha256 != index.bundle_manifest.sha256):
        raise ValueError("query in-memory source catalog belongs to another original bundle")
    fragment, graph = build_native_operator_value_fragment(
        (original_row,), instances={instance.id: instance},
        definitions=catalog.definitions, effects=catalog.effects,
        slots=catalog.slots, provider_references=catalog.provider_references,
        port_index=port_index, port_index_artifact=index.native_port_index,
        bundle_manifest=index.bundle_manifest, eto_source=index.eto_source,
        flow_index=flow_index, flow_index_artifact=index.reference_flow_index,
        flow_publication=flow_publication, resolve_original_edges=True)
    return fragment, graph


def query_native_operator_value_port_from_declaration(
        publication: str | Path, instance: OperationInstance, direction: str,
        path: tuple[int, ...], *, expected_index_sha256: str | None = None,
        catalog: NativeOperatorValueSourceCatalog | None = None
        ) -> tuple[NativeOperatorValueInterface, NativeOperatorPortBinding, ValueGraph]:
    fragment, graph = query_native_operator_value_fragment_from_declaration(
        publication, instance, expected_index_sha256=expected_index_sha256,
        catalog=catalog)
    interface = next(item for item in fragment.interfaces if item.instance == instance.id)
    ports = interface.inputs if direction == "input" else interface.outputs if direction == "output" else ()
    matches = [item for item in ports if item.path == path]
    if len(matches) != 1:
        raise KeyError("requested ordered native value port is absent or ambiguous")
    return interface, matches[0], graph


def query_native_operator_value_port(
        publication: str | Path, instance: OperationInstance, direction: str,
        path: tuple[int, ...], native_port_publication: str | Path,
        bundle_partitions: str | Path, *, expected_fragment_sha256: str | None = None,
        expected_native_port_index_sha256: str | None = None
        ) -> tuple[NativeOperatorValueInterface, NativeOperatorPortBinding, ValueGraph]:
    """Query from an original instance through its verified native port to ValueGraph."""
    if type(instance) is not OperationInstance:
        raise TypeError("query must start from an original OperationInstance")
    if direction not in ("input", "output"):
        raise ValueError("port direction must be input or output")
    if type(path) is not tuple or not path or any(type(part) is not int or part < 0 for part in path):
        raise ValueError("port path must be a nonempty ordered integer tuple")
    fragment, graph = read_native_operator_value_fragment(
        publication, expected_sha256=expected_fragment_sha256)
    matches = [item for item in fragment.interfaces if item.instance == instance.id]
    if len(matches) != 1 or matches[0].definition != instance.definition:
        raise KeyError("original operation instance is not in this value-interface fragment")
    interface = matches[0]
    original_row = query_native_ports(
        instance, native_port_publication, bundle_partitions,
        expected_index_sha256=expected_native_port_index_sha256)
    original = [port for port in original_row.ports
                if port.direction == direction and port.path == path]
    bindings = [port for port in (interface.inputs if direction == "input" else interface.outputs)
                if port.path == path]
    if len(original) != 1 or len(bindings) != 1:
        raise KeyError("requested exact original native port is absent or ambiguous")
    if interface.source_ordinal != original_row.source_ordinal:
        raise ValueError("native interface source ordinal differs from the original instance reference")
    source = original[0]
    binding = bindings[0]
    if (binding.port_id != _port_id(original_row.source_ordinal, direction, path)
            or binding.source_locator != source.source_locator
            or binding.kind != source.kind
            or binding.provider_type != source.provider_type
            or binding.formal_slot != source.formal_slot
            or binding.formal_status != source.formal_status
            or binding.provider_reference != source.provider_reference
            or binding.descriptor_id != source.descriptor_id):
        raise ValueError("value-interface port reference differs from the receipt-bound original native port")
    return interface, binding, graph


__all__ = [
    "NativeOperatorPortBinding", "NativeSchemaStateBoundary",
    "NativeOperatorValueInterface", "NativePhysicalCandidateRef",
    "NativeOperatorValueFragment", "NativeOperatorSourceShardSummary",
    "NativeOperatorValueDeclarationIndex", "NativeOperatorValueSourceCatalog",
    "load_native_operator_value_source_catalog",
    "build_native_operator_value_declaration_publication",
    "read_native_operator_value_declaration_index",
    "query_native_operator_value_fragment_from_declaration",
    "query_native_operator_value_port_from_declaration",
    "build_native_operator_value_fragment",
    "write_native_operator_value_fragment", "read_native_operator_value_fragment",
    "query_native_operator_value_port",
]

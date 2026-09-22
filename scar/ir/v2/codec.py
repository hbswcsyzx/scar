"""Strict JSON decoders for the IR v2 graph bundle."""
from __future__ import annotations

from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from functools import lru_cache, wraps
import json
import math
from types import UnionType
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from .common import (
    Completeness,
    EvidenceClaim,
    EvidenceKind,
    ProofClaim,
    ProofStatus,
    SourceReference,
)
from .contracts import (
    ContractDefinition,
    ContractFacet,
    EffectPresence,
    EffectSet,
    EffectSummary,
    EffectTarget,
    EffectTargetKind,
    FacetRequirement,
    MeasurementRecord,
    ResourceKind,
    ResourceRequirement,
)
from .correspondence import (
    CorrespondenceGraph,
    CorrespondenceKind,
    CorrespondenceRecord,
)
from .evidence import (
    EvidenceEdge,
    EvidenceEndpoint,
    EvidenceGraph,
    EvidenceNodeKind,
    EvidenceRelation,
    EvidenceStatus,
    OperationInstance,
    ValueObservation,
)
from .ids import (
    ContractID,
    ControlRegionID,
    CorrespondenceID,
    EffectSummaryID,
    Identifier,
    LogicalValueID,
    MaterializationID,
    MeasurementID,
    ModuleID,
    ObjectID,
    OperationDefinitionID,
    OperationInstanceID,
    OptimizationRegionID,
    PackageID,
    PlanAlternativeID,
    PlanID,
    ProvenanceID,
    ResourceID,
    SourceAtomID,
    StorageAllocationID,
    StorageRegionID,
    ValueSlotID,
    ValueVersionID,
)
from .optimization import (
    CostRequest,
    GuardSpec,
    InstructionKind,
    InvalidationSpec,
    LiteralValue,
    MeasurementMode,
    OptimizationGraph,
    OptimizationRegion,
    PlanAlternative,
    PlanDisposition,
    PlanInstruction,
    PlanSelection,
    RegionGranularity,
    RegionMove,
    RegionPort,
    RegionPortKind,
    ResidualEffect,
    TransformDelta,
    TransformKind,
    ValidationRequest,
    ValuePattern,
    ValueSubstitution,
)
from .semantic import (
    ControlRegion,
    ModuleDefinition,
    OperationDefinition,
    OperationKind,
    PackageDefinition,
    SemanticEdge,
    SemanticEndpoint,
    SemanticGraph,
    SemanticNodeKind,
    SemanticRelation,
    SourceAtom,
    ValueSlot,
)
from .values import (
    BindingRelation,
    EquivalenceClaim,
    LogicalValue,
    Materialization,
    ObjectBinding,
    ProvenanceRecord,
    ProvenanceRelation,
    StorageAllocation,
    StorageRegion,
    ValueGraph,
    ValueVersion,
)


I = TypeVar("I", bound=Identifier)


def _json_value(value: Any, path: str = "document") -> None:
    """Reject data that canonical JSON cannot represent, including NaN/Inf."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: JSON object keys must be strings")
            _json_value(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _json_value(child, f"{path}[{index}]")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite JSON number")
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError(f"{path}: unsupported JSON value {type(value).__name__}")


@lru_cache(maxsize=None)
def _record_schema(cls):
    return fields(cls), get_type_hints(cls)


def _wire_type(value: Any, expected: Any, path: str) -> None:
    """Validate wire shapes before tuple conversion or truthiness can hide errors."""
    if expected is Any:
        return
    origin, arguments = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        for alternative in arguments:
            try:
                _wire_type(value, alternative, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path}: does not match {expected}")
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{path}: expected array")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            for index, child in enumerate(value):
                _wire_type(child, arguments[0], f"{path}[{index}]")
        else:
            if len(value) != len(arguments):
                raise ValueError(f"{path}: incorrect array length")
            for index, (child, child_type) in enumerate(zip(value, arguments)):
                _wire_type(child, child_type, f"{path}[{index}]")
        return
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected object")
        for key, child in value.items():
            _wire_type(key, arguments[0], f"{path}.key")
            _wire_type(child, arguments[1], f"{path}.{key}")
        return
    if isinstance(expected, type) and issubclass(expected, Identifier):
        if expected is Identifier:
            # Endpoint-specific decoding checks the exact identifier namespace.
            if not isinstance(value, dict) or set(value) != {"kind", "value", "wire"}:
                raise ValueError(f"{path}: expected identifier object")
            if any(not isinstance(value[key], str) or not value[key]
                   for key in ("kind", "value", "wire")):
                raise ValueError(f"{path}: identifier fields must be non-empty strings")
        else:
            _required_id(value, expected)
        return
    if expected is ValueVersionID:
        _required_version(value)
        return
    if isinstance(expected, type) and issubclass(expected, Enum):
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected enum string")
        expected(value)
        return
    if is_dataclass(expected):
        _record(value, expected, path)
        return
    valid = type(value) in (int, float) if expected is float else type(value) is expected
    if not valid:
        raise ValueError(f"{path}: expected {expected.__name__}")


def _record(data: Any, cls: type, path: str) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected {cls.__name__} object")
    members, hints = _record_schema(cls)
    unknown = set(data) - {item.name for item in members}
    if unknown:
        raise ValueError(f"{path}: unknown fields {sorted(unknown)}")
    for member in members:
        if member.name not in data:
            if member.default is MISSING and member.default_factory is MISSING:
                raise ValueError(f"{path}: missing required field {member.name}")
            continue
        value = data[member.name]
        if cls is ValuePattern and member.name == "constraints":
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{path}.constraints: expected array")
            for constraint in value:
                if not isinstance(constraint, dict) or set(constraint) != {"name", "value"}:
                    raise ValueError(f"{path}.constraints: expected name/value object")
                _wire_type(constraint, dict[str, str], f"{path}.constraints")
        else:
            _wire_type(value, hints[member.name], f"{path}.{member.name}")


def _document(data: Any, cls: type, collections: dict[str, type],
              extra_fields: tuple[str, ...] = ()) -> None:
    if not isinstance(data, dict) or data.get("schema") != cls.SCHEMA:
        raise ValueError(f"not a {cls.__name__} document")
    version = data.get("schema_version")
    if type(version) is not int or version != cls.SCHEMA_VERSION:
        raise ValueError(f"{cls.SCHEMA}: unsupported schema_version {version!r}; "
                         f"expected {cls.SCHEMA_VERSION}")
    unknown = set(data) - {"schema", "schema_version", "validation", *collections, *extra_fields}
    if unknown:
        raise ValueError(f"{cls.SCHEMA}: unknown fields {sorted(unknown)}")
    _json_value(data)
    for name, record_type in collections.items():
        records = data.get(name, ())
        if not isinstance(records, (list, tuple)):
            raise ValueError(f"{cls.SCHEMA}.{name}: expected array")
        seen = set()
        for index, record in enumerate(records):
            path = f"{cls.SCHEMA}.{name}[{index}]"
            _record(record, record_type, path)
            identity_key = next((key for key in ("id", "slot_id", "edge_id",
                                "observation_id", "port_id") if key in record), None)
            if identity_key is not None:
                identity = json.dumps(record[identity_key], sort_keys=True)
                if identity in seen:
                    raise ValueError(f"{path}: duplicate {identity_key} {identity}")
                seen.add(identity)


def _decoder(function):
    """Expose one stable error type for invalid input, also under python -O."""
    @wraps(function)
    def decode(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, RecursionError) as error:
            raise ValueError(f"invalid {function.__name__} document: {error}") from error
    return decode


def _id(data: dict[str, Any] | None, cls: type[I]) -> I | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != {"kind", "value", "wire"}:
        raise ValueError(f"expected {cls.prefix} identifier object")
    if data.get("kind") != cls.prefix:
        raise ValueError(f"expected {cls.prefix} ID, got {data.get('kind')}")
    result = cls(data["value"])
    if data.get("wire") != result.wire:
        raise ValueError(f"invalid wire form for {result.wire}")
    return result


def _required_id(data: dict[str, Any], cls: type[I]) -> I:
    result = _id(data, cls)
    if result is None:
        raise ValueError(f"required {cls.prefix} ID cannot be null")
    return result


def _version(data: dict[str, Any] | None) -> ValueVersionID | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != {"logical_value", "version", "wire"}:
        raise ValueError("expected value-version identifier object")
    if type(data["version"]) is not int:
        raise ValueError("value-version version must be an integer")
    result = ValueVersionID(
        _required_id(data["logical_value"], LogicalValueID), data["version"])
    if data.get("wire") != result.wire:
        raise ValueError(f"invalid value-version wire form for {result.wire}")
    return result


def _required_version(data: dict[str, Any]) -> ValueVersionID:
    result = _version(data)
    if result is None:
        raise ValueError("required value-version ID cannot be null")
    return result


def _evidence(data: dict[str, Any]) -> EvidenceClaim:
    return EvidenceClaim(
        EvidenceKind(data["kind"]), tuple(data.get("references", ())),
        data.get("scope"), data.get("confidence"),
        tuple(data.get("assumptions", ())))


def _proof(data: dict[str, Any]) -> ProofClaim:
    return ProofClaim(
        data["obligation"], ProofStatus(data["status"]),
        tuple(_evidence(item) for item in data.get("evidence", ())),
        data.get("reason", ""), data.get("required_next"))


def _source(data: dict[str, Any]) -> SourceReference:
    return SourceReference(
        _required_id(data["atom_id"], SourceAtomID), data["path"],
        data["fingerprint"], data["start_line"], data["end_line"],
        data.get("start_column", 0), data.get("end_column"))


def _effect_set(data: dict[str, Any]) -> EffectSet:
    return EffectSet(
        tuple(EffectTarget(EffectTargetKind(item["kind"]), item["reference"])
              for item in data.get("members", ())),
        Completeness(data["completeness"]))


def _effect_summary(data: dict[str, Any]) -> EffectSummary:
    return EffectSummary(
        _required_id(data["id"], EffectSummaryID),
        reads=_effect_set(data["reads"]), writes=_effect_set(data["writes"]),
        allocates=_effect_set(data["allocates"]), frees=_effect_set(data["frees"]),
        aliases=_effect_set(data["aliases"]), escapes=_effect_set(data["escapes"]),
        rng=EffectPresence(data["rng"]), may_raise=EffectPresence(data["may_raise"]),
        external=EffectPresence(data["external"]),
        ordering=EffectPresence(data["ordering"]),
        evidence=tuple(_evidence(item) for item in data.get("evidence", ())))


@_decoder
def semantic_from_dict(data: dict[str, Any]) -> SemanticGraph:
    _document(data, SemanticGraph, {
        "packages": PackageDefinition, "modules": ModuleDefinition,
        "source_atoms": SourceAtom, "controls": ControlRegion,
        "effects": EffectSummary, "resources": ResourceRequirement,
        "contracts": ContractDefinition, "definitions": OperationDefinition,
        "slots": ValueSlot, "edges": SemanticEdge,
    })
    graph = SemanticGraph()
    for item in data.get("packages", ()):
        node = PackageDefinition(_required_id(item["id"], PackageID), item["name"],
                                 item.get("root"), item.get("fingerprint"))
        graph.packages[node.id] = node
    for item in data.get("modules", ()):
        node = ModuleDefinition(
            _required_id(item["id"], ModuleID), item["name"],
            _id(item.get("package"), PackageID), item.get("path"),
            item.get("fingerprint"),
            _id(item.get("initializer"), OperationDefinitionID))
        graph.modules[node.id] = node
    for item in data.get("source_atoms", ()):
        node = SourceAtom(_required_id(item["id"], SourceAtomID),
                          _source(item["reference"]), item["kind"],
                          item.get("text_fingerprint"))
        graph.source_atoms[node.id] = node
    for item in data.get("controls", ()):
        node = ControlRegion(
            _required_id(item["id"], ControlRegionID), item["kind"],
            _id(item.get("parent_id"), ControlRegionID),
            _id(item.get("owner"), OperationDefinitionID),
            tuple(_required_id(value, SourceAtomID)
                  for value in item.get("source_atoms", ())),
            item.get("metadata", {}))
        graph.controls[node.id] = node
    for item in data.get("effects", ()):
        node = _effect_summary(item)
        graph.effects[node.id] = node
    for item in data.get("resources", ()):
        node = ResourceRequirement(
            _required_id(item["id"], ResourceID), ResourceKind(item["kind"]),
            item["selector"], item.get("capacity", {}), item.get("exclusive", False),
            tuple(_evidence(value) for value in item.get("evidence", ())))
        graph.resources[node.id] = node
    for item in data.get("contracts", ()):
        facets = tuple(FacetRequirement(
            ContractFacet(value["facet"]), value["required"],
            value.get("tolerance", {}), value.get("description", ""))
            for value in item.get("facets", ()))
        node = ContractDefinition(
            _required_id(item["id"], ContractID), item["name"],
            tuple(_required_id(value, ValueSlotID)
                  for value in item.get("required_outputs", ())),
            facets, tuple(item.get("assumptions", ())),
            tuple(_evidence(value) for value in item.get("evidence", ())))
        graph.contracts[node.id] = node
    for item in data.get("definitions", ()):
        node = OperationDefinition(
            _required_id(item["id"], OperationDefinitionID),
            OperationKind(item["kind"]), item["label"], item.get("code_id"),
            item.get("source_file"), item.get("source_start"), item.get("source_end"),
            _id(item.get("parent_id"), OperationDefinitionID),
            _id(item.get("control_region"), ControlRegionID),
            tuple(_required_id(value, ValueSlotID) for value in item.get("input_slots", ())),
            tuple(_required_id(value, ValueSlotID) for value in item.get("output_slots", ())),
            tuple(_required_id(value, ValueSlotID) for value in item.get("state_slots", ())),
            tuple(_required_id(value, SourceAtomID) for value in item.get("source_atoms", ())),
            _id(item.get("contract"), ContractID),
            _id(item.get("effect_summary"), EffectSummaryID),
            tuple(_required_id(value, ResourceID)
                  for value in item.get("resource_requirements", ())),
            item.get("metadata", {}))
        graph.definitions[node.id] = node
    for item in data.get("slots", ()):
        node = ValueSlot(
            _required_id(item["slot_id"], ValueSlotID), item["name"],
            item["direction"], item.get("semantic_type"),
            _id(item.get("owner"), OperationDefinitionID), item.get("mutable"),
            item.get("metadata", {}))
        graph.slots[node.slot_id] = node
    for item in data.get("edges", ()):
        source = item["source"]
        target = item["target"]
        source_kind = SemanticNodeKind(source["kind"])
        target_kind = SemanticNodeKind(target["kind"])
        type_map = {
            SemanticNodeKind.PACKAGE: PackageID, SemanticNodeKind.MODULE: ModuleID,
            SemanticNodeKind.SOURCE_ATOM: SourceAtomID,
            SemanticNodeKind.OPERATION: OperationDefinitionID,
            SemanticNodeKind.VALUE_SLOT: ValueSlotID,
            SemanticNodeKind.CONTROL: ControlRegionID,
            SemanticNodeKind.CONTRACT: ContractID,
            SemanticNodeKind.EFFECT: EffectSummaryID,
            SemanticNodeKind.RESOURCE: ResourceID,
        }
        edge = SemanticEdge(
            item["edge_id"], SemanticRelation(item["relation"]),
            SemanticEndpoint(source_kind, _required_id(source["id"], type_map[source_kind])),
            SemanticEndpoint(target_kind, _required_id(target["id"], type_map[target_kind])),
            _evidence(item["evidence"]))
        graph.edges[edge.edge_id] = edge
    graph.assert_valid()
    return graph


@_decoder
def values_from_dict(data: dict[str, Any]) -> ValueGraph:
    _document(data, ValueGraph, {
        "logical_values": LogicalValue, "versions": ValueVersion,
        "provenance": ProvenanceRecord, "allocations": StorageAllocation,
        "regions": StorageRegion, "materializations": Materialization,
        "bindings": ObjectBinding,
    })
    graph = ValueGraph()
    for item in data.get("logical_values", ()):
        node = LogicalValue(_required_id(item["id"], LogicalValueID),
                            item["semantic_type"], item.get("description", ""),
                            item.get("metadata", {}))
        graph.logical_values[node.id] = node
    for item in data.get("versions", ()):
        node = ValueVersion(
            _required_version(item["id"]), _id(item.get("provenance_id"), ProvenanceID),
            tuple(_required_version(value) for value in item.get("parent_versions", ())),
            item.get("semantic_type"), item.get("control_scope"),
            item.get("metadata", {}))
        graph.versions[node.id] = node
    for item in data.get("provenance", ()):
        node = ProvenanceRecord(
            _required_id(item["id"], ProvenanceID),
            ProvenanceRelation(item["relation"]),
            tuple(_required_version(value) for value in item.get("inputs", ())),
            tuple(_required_version(value) for value in item.get("outputs", ())),
            _id(item.get("producer"), OperationInstanceID),
            EquivalenceClaim(item["equivalence"]), item.get("evidence", "Observed"),
            item.get("metadata", {}))
        graph.provenance[node.id] = node
    for item in data.get("allocations", ()):
        node = StorageAllocation(
            _required_id(item["id"], StorageAllocationID), item["device"],
            item.get("nbytes"), item.get("allocator_token"),
            item.get("lifetime_scope"), item.get("metadata", {}))
        graph.allocations[node.id] = node
    for item in data.get("regions", ()):
        node = StorageRegion(
            _required_id(item["id"], StorageRegionID),
            _required_id(item["allocation"], StorageAllocationID), item["offset"],
            tuple(item["shape"]), tuple(item["strides"]), item["dtype"],
            item["device"], item.get("layout", "strided"), item.get("metadata", {}))
        graph.regions[node.id] = node
    for item in data.get("materializations", ()):
        node = Materialization(
            _required_id(item["id"], MaterializationID),
            _required_version(item["value_version"]), item["representation"],
            item["device"], _id(item.get("region"), StorageRegionID),
            _id(item.get("producer"), OperationInstanceID), item.get("ready_event"),
            item.get("validity_scope"), item.get("evidence", "Observed"),
            item.get("metadata", {}))
        graph.materializations[node.id] = node
    for item in data.get("bindings", ()):
        graph.bindings.append(ObjectBinding(
            _required_id(item["object_id"], ObjectID),
            _required_version(item["value_version"]),
            BindingRelation(item["relation"]), item.get("scope"),
            item.get("evidence", "Observed"), item.get("metadata", {})))
    graph.assert_valid()
    return graph


_EVIDENCE_ID_TYPES: dict[EvidenceNodeKind, type] = {
    EvidenceNodeKind.OPERATION_INSTANCE: OperationInstanceID,
    EvidenceNodeKind.VALUE_VERSION: ValueVersionID,
    EvidenceNodeKind.MATERIALIZATION: MaterializationID,
    EvidenceNodeKind.OBJECT: ObjectID,
    EvidenceNodeKind.ALLOCATION: StorageAllocationID,
    EvidenceNodeKind.STORAGE_REGION: StorageRegionID,
    EvidenceNodeKind.RESOURCE: ResourceID,
    EvidenceNodeKind.MEASUREMENT: MeasurementID,
}


def _evidence_endpoint(data: dict[str, Any]) -> EvidenceEndpoint:
    kind = EvidenceNodeKind(data["kind"])
    reference = data["reference"]
    if kind in {EvidenceNodeKind.VALUE_OBSERVATION, EvidenceNodeKind.CONTROL_EVENT}:
        return EvidenceEndpoint(kind, reference)
    cls = _EVIDENCE_ID_TYPES[kind]
    if cls is ValueVersionID:
        return EvidenceEndpoint(kind, _required_version(reference))
    return EvidenceEndpoint(kind, _required_id(reference, cls))


@_decoder
def evidence_from_dict(data: dict[str, Any]) -> EvidenceGraph:
    _document(data, EvidenceGraph, {
        "instances": OperationInstance, "observations": ValueObservation,
        "measurements": MeasurementRecord, "edges": EvidenceEdge,
    }, extra_fields=("control_events", "external_references"))
    graph = EvidenceGraph()
    for item in data.get("instances", ()):
        node = OperationInstance(
            _required_id(item["id"], OperationInstanceID),
            _required_id(item["definition"], OperationDefinitionID),
            item["process_id"], item["thread_id"],
            _id(item.get("parent"), OperationInstanceID), item.get("control_scope"),
            item.get("iteration", {}), item.get("start_ns"), item.get("end_ns"),
            EvidenceStatus(item["status"]), item.get("metadata", {}))
        graph.instances[node.id] = node
    for item in data.get("observations", ()):
        node = ValueObservation(
            item["observation_id"], _required_version(item["version"]),
            _id(item.get("operation"), OperationInstanceID),
            _id(item.get("materialization"), MaterializationID), item.get("role", "value"),
            EvidenceStatus(item["status"]), item.get("metadata", {}))
        graph.observations[node.observation_id] = node
    for item in data.get("measurements", ()):
        node = MeasurementRecord(
            _required_id(item["id"], MeasurementID), item["metric"], item["value"],
            item["unit"], item["scope"], item.get("samples", 1),
            item.get("minimum"), item.get("maximum"), item.get("variance"),
            item.get("instrumented", True),
            tuple(_evidence(value) for value in item.get("evidence", ())))
        graph.measurements[node.id] = node
    control_events = data.get("control_events", ())
    _wire_type(control_events, tuple[str, ...], "control_events")
    for control_event in control_events:
        if not control_event or control_event in graph.control_events:
            raise ValueError("control_events must contain unique non-empty IDs")
        graph.control_events.add(control_event)
    references = data.get("external_references", ())
    _wire_type(references, tuple[dict[str, str], ...], "external_references")
    for item in references:
        if set(item) != {"kind", "wire"} or not item["wire"]:
            raise ValueError("external reference requires kind and non-empty wire")
        reference = (EvidenceNodeKind(item["kind"]), item["wire"])
        if reference in graph.external_references:
            raise ValueError(f"duplicate external reference {reference}")
        graph.external_references.add(reference)
    for item in data.get("edges", ()):
        edge = EvidenceEdge(
            item["edge_id"], EvidenceRelation(item["relation"]),
            _evidence_endpoint(item["source"]), _evidence_endpoint(item["target"]),
            _evidence(item["evidence"]))
        graph.edges[edge.edge_id] = edge
    graph.assert_valid()
    return graph


@_decoder
def correspondence_from_dict(data: dict[str, Any]) -> CorrespondenceGraph:
    _document(data, CorrespondenceGraph, {"records": CorrespondenceRecord})
    graph = CorrespondenceGraph()
    for item in data.get("records", ()):
        node = CorrespondenceRecord(
            _required_id(item["id"], CorrespondenceID),
            CorrespondenceKind(item["kind"]),
            _id(item.get("definition"), OperationDefinitionID),
            _id(item.get("instance"), OperationInstanceID),
            _id(item.get("source_atom"), SourceAtomID),
            _id(item.get("value_slot"), ValueSlotID),
            _version(item.get("value_version")), _evidence(item["evidence"]),
            item.get("ambiguous", False))
        graph.records[node.id] = node
    return graph


def _value_pattern(data: dict[str, Any] | None) -> ValuePattern | None:
    if data is None:
        return None
    return ValuePattern(
        tuple(_required_version(item) for item in data.get("versions", ())),
        tuple(_required_id(item, ProvenanceID) for item in data.get("provenance", ())),
        tuple(_required_id(item, MaterializationID)
              for item in data.get("materializations", ())),
        data.get("semantic_type"),
        tuple((item["name"], item["value"]) for item in data.get("constraints", ())))


@dataclass(frozen=True)
class _RegionPortV1:
    """Wire fields from OIR schema 1; new payloads cannot masquerade as v1."""

    port_id: str
    kind: RegionPortKind
    name: str
    value: ValuePattern | None = None
    control: ControlRegionID | None = None
    resource: ResourceID | None = None
    required: bool = True


class _OptimizationDocumentV1:
    SCHEMA = OptimizationGraph.SCHEMA
    SCHEMA_VERSION = 1


def _upgrade_optimization_document_v1(data):
    """Validate legacy wire shape, then add empty new fields without mutation.

    No value, effect or slot identity is synthesized. Payloads invalid under
    current kind semantics remain rejected; in particular a legacy ORDERING
    value pattern needs an explicit control/resource/effect representation.
    """
    if (not isinstance(data, dict) or data.get("schema") != OptimizationGraph.SCHEMA
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1):
        return data
    _document(data, _OptimizationDocumentV1, {
        "ports": _RegionPortV1, "regions": OptimizationRegion,
        "alternatives": PlanAlternative, "plans": PlanSelection,
    })
    if any(item["kind"] == RegionPortKind.EFFECT.value for item in data.get("ports", ())):
        raise ValueError("schema_version 1 has no effect port kind")
    return {**data, "schema_version": OptimizationGraph.SCHEMA_VERSION,
            "ports": [{**item, "slot": None, "effect": None, "operation": None}
                      for item in data.get("ports", ())]}


@_decoder
def optimization_from_dict(data: dict[str, Any], context) -> OptimizationGraph:
    data = _upgrade_optimization_document_v1(data)
    _document(data, OptimizationGraph, {
        "ports": RegionPort, "regions": OptimizationRegion,
        "alternatives": PlanAlternative, "plans": PlanSelection,
    })
    graph = OptimizationGraph(context)
    for item in data.get("ports", ()):
        node = RegionPort(
            item["port_id"], RegionPortKind(item["kind"]), item["name"],
            _value_pattern(item.get("value")), _id(item.get("control"), ControlRegionID),
            _id(item.get("resource"), ResourceID), item.get("required", True),
            _id(item.get("slot"), ValueSlotID),
            EffectTarget(EffectTargetKind(item["effect"]["kind"]), item["effect"]["reference"])
            if item.get("effect") is not None else None,
            _id(item["operation"], OperationDefinitionID if item["operation"]["kind"] == "opdef"
                else OperationInstanceID) if item.get("operation") is not None else None)
        graph.ports[node.port_id] = node
    for item in data.get("regions", ()):
        node = OptimizationRegion(
            _required_id(item["id"], OptimizationRegionID),
            RegionGranularity(item["granularity"]), item["label"],
            tuple(_required_id(value, OperationDefinitionID)
                  for value in item.get("definitions", ())),
            tuple(_required_id(value, OperationInstanceID)
                  for value in item.get("instances", ())),
            _id(item.get("parent"), OptimizationRegionID),
            tuple(item.get("ports", ())),
            _id(item.get("effect_summary"), EffectSummaryID),
            _id(item.get("contract"), ContractID),
            tuple(_required_id(value, SourceAtomID)
                  for value in item.get("source_atoms", ())),
            tuple(_required_id(value, MeasurementID)
                  for value in item.get("measurements", ())))
        graph.regions[node.id] = node
    for item in data.get("alternatives", ()):
        delta_data = item["delta"]
        delta = TransformDelta(
            tuple(_required_id(value, OperationDefinitionID)
                  for value in delta_data.get("removed_definitions", ())),
            tuple(_required_id(value, OperationInstanceID)
                  for value in delta_data.get("removed_instances", ())),
            tuple(ValueSubstitution(
                _required_version(value["original"]),
                _version(value.get("replacement_version")),
                LiteralValue(value["literal"]["value"])
                if value.get("literal") is not None else None,
                value.get("equivalence", "exact"))
                for value in delta_data.get("substitutions", ())),
            tuple(RegionMove(
                _required_id(value["region"], OptimizationRegionID),
                _required_id(value["from_control"], ControlRegionID),
                _required_id(value["to_control"], ControlRegionID))
                for value in delta_data.get("moves", ())),
            tuple(delta_data.get("added_operations", ())))
        cost_data = item.get("cost_request")
        validation_data = item.get("validation_request")
        node = PlanAlternative(
            _required_id(item["id"], PlanAlternativeID),
            _required_id(item["region"], OptimizationRegionID), item["label"],
            TransformKind(item["transform"]), delta, item.get("original", False),
            tuple(_proof(value) for value in item.get("proofs", ())),
            tuple(GuardSpec(value["guard_id"], value["expression"],
                            tuple(value.get("inputs", ())),
                            value.get("estimated_cost_ns"))
                  for value in item.get("guards", ())),
            tuple(InvalidationSpec(value["invalidation_id"], value["trigger"],
                                   tuple(value.get("affected", ())))
                  for value in item.get("invalidations", ())),
            tuple(ResidualEffect(
                _required_id(value["effect"], EffectSummaryID), value["reason"],
                value["placement"]) for value in item.get("residual_effects", ())),
            CostRequest(
                _required_id(cost_data["scope"], OptimizationRegionID),
                tuple(cost_data["metrics"]), MeasurementMode(cost_data["mode"]),
                cost_data.get("warmup", 0), cost_data.get("repetitions", 1))
            if cost_data is not None else None,
            ValidationRequest(
                _required_id(validation_data["contract"], ContractID),
                tuple(validation_data["levels"]), tuple(validation_data["snapshots"]),
                validation_data.get("clean_benchmark", True))
            if validation_data is not None else None,
            tuple(PlanInstruction(
                value["instruction_id"], InstructionKind(value["kind"]),
                value["target"], _source(value["source"])
                if value.get("source") is not None else None,
                value.get("replacement"), value.get("rationale", ""),
                tuple(value.get("depends_on", ())))
                for value in item.get("instructions", ())),
            _id(item.get("fallback"), PlanAlternativeID))
        graph.alternatives[node.id] = node
    for item in data.get("plans", ()):
        node = PlanSelection(
            _required_id(item["id"], PlanID),
            _required_id(item["region"], OptimizationRegionID),
            PlanDisposition(item["disposition"]),
            _id(item.get("selected"), PlanAlternativeID), item["reason"],
            tuple(item.get("requests", ())))
        graph.plans[node.id] = node
    graph.assert_valid()
    return graph


@_decoder
def bundle_from_dict(data: dict[str, Any]):
    from .schemas import IRBundle, optimization_context

    _document(data, IRBundle, {}, extra_fields=(
        "semantic", "evidence", "values", "correspondence", "optimization"))
    semantic = semantic_from_dict(data["semantic"])
    evidence = evidence_from_dict(data["evidence"])
    values = values_from_dict(data["values"])
    correspondence = (correspondence_from_dict(data["correspondence"])
                      if data.get("correspondence") is not None else None)
    optimization = (optimization_from_dict(
        data["optimization"], optimization_context(semantic, evidence, values))
        if data.get("optimization") is not None else None)
    bundle = IRBundle(semantic, evidence, values, correspondence, optimization)
    bundle.assert_valid()
    return bundle


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


@_decoder
def bundle_from_json(payload: str):
    document = json.loads(payload, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    if not isinstance(document, dict):
        raise ValueError("IR bundle JSON must contain an object")
    return bundle_from_dict(document)


__all__ = [
    "bundle_from_dict", "bundle_from_json", "correspondence_from_dict",
    "evidence_from_dict", "optimization_from_dict", "semantic_from_dict",
    "values_from_dict",
]

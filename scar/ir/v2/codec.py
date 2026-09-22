"""Strict JSON decoders for the IR v2 graph bundle."""
from __future__ import annotations

import json
from typing import Any, TypeVar

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


def _id(data: dict[str, Any] | None, cls: type[I]) -> I | None:
    if data is None:
        return None
    if data.get("kind") != cls.prefix:
        raise ValueError(f"expected {cls.prefix} ID, got {data.get('kind')}")
    result = cls(data["value"])
    if data.get("wire") != result.wire:
        raise ValueError(f"invalid wire form for {result.wire}")
    return result


def _required_id(data: dict[str, Any], cls: type[I]) -> I:
    result = _id(data, cls)
    assert result is not None
    return result


def _version(data: dict[str, Any] | None) -> ValueVersionID | None:
    if data is None:
        return None
    result = ValueVersionID(
        _required_id(data["logical_value"], LogicalValueID), data["version"])
    if data.get("wire") != result.wire:
        raise ValueError(f"invalid value-version wire form for {result.wire}")
    return result


def _required_version(data: dict[str, Any]) -> ValueVersionID:
    result = _version(data)
    assert result is not None
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


def semantic_from_dict(data: dict[str, Any]) -> SemanticGraph:
    if data.get("schema") != SemanticGraph.SCHEMA:
        raise ValueError("not a SemanticGraph document")
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


def values_from_dict(data: dict[str, Any]) -> ValueGraph:
    if data.get("schema") != ValueGraph.SCHEMA:
        raise ValueError("not a ValueGraph document")
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


def evidence_from_dict(data: dict[str, Any]) -> EvidenceGraph:
    if data.get("schema") != EvidenceGraph.SCHEMA:
        raise ValueError("not an EvidenceGraph document")
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
    graph.control_events.update(data.get("control_events", ()))
    for item in data.get("external_references", ()):
        graph.external_references.add((EvidenceNodeKind(item["kind"]), item["wire"]))
    for item in data.get("edges", ()):
        edge = EvidenceEdge(
            item["edge_id"], EvidenceRelation(item["relation"]),
            _evidence_endpoint(item["source"]), _evidence_endpoint(item["target"]),
            _evidence(item["evidence"]))
        graph.edges[edge.edge_id] = edge
    graph.assert_valid()
    return graph


def correspondence_from_dict(data: dict[str, Any]) -> CorrespondenceGraph:
    if data.get("schema") != CorrespondenceGraph.SCHEMA:
        raise ValueError("not a CorrespondenceGraph document")
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


def optimization_from_dict(data: dict[str, Any], context) -> OptimizationGraph:
    if data.get("schema") != OptimizationGraph.SCHEMA:
        raise ValueError("not an OptimizationGraph document")
    graph = OptimizationGraph(context)
    for item in data.get("ports", ()):
        node = RegionPort(
            item["port_id"], RegionPortKind(item["kind"]), item["name"],
            _value_pattern(item.get("value")), _id(item.get("control"), ControlRegionID),
            _id(item.get("resource"), ResourceID), item.get("required", True))
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
            if cost_data else None,
            ValidationRequest(
                _required_id(validation_data["contract"], ContractID),
                tuple(validation_data["levels"]), tuple(validation_data["snapshots"]),
                validation_data.get("clean_benchmark", True))
            if validation_data else None,
            tuple(PlanInstruction(
                value["instruction_id"], InstructionKind(value["kind"]),
                value["target"], _source(value["source"]) if value.get("source") else None,
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


def bundle_from_dict(data: dict[str, Any]):
    from .schemas import IRBundle, optimization_context

    if data.get("schema") != IRBundle.SCHEMA:
        raise ValueError("not an IRBundle document")
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


def bundle_from_json(payload: str):
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError("IR bundle JSON must contain an object")
    return bundle_from_dict(document)


__all__ = [
    "bundle_from_dict", "bundle_from_json", "correspondence_from_dict",
    "evidence_from_dict", "optimization_from_dict", "semantic_from_dict",
    "values_from_dict",
]

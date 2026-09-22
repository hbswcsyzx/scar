"""Typed semantic/effect ports, explicit legacy migration and bounded validation."""
from copy import deepcopy
from dataclasses import replace

import pytest

import scar.ir.v2 as ir


def _bundle(*, slot_port=True):
    semantic, evidence, values = ir.SemanticGraph(), ir.EvidenceGraph(), ir.ValueGraph()
    definition = ir.OperationDefinitionID("compute")
    slot = ir.ValueSlotID("argument")
    control, resource = ir.ControlRegionID("body"), ir.ResourceID("device")
    semantic.add_definition(ir.OperationDefinition(definition, ir.OperationKind.FUNCTION,
                                                    "compute", input_slots=(slot,)))
    semantic.slots[slot] = ir.ValueSlot(slot, "argument", "input", owner=definition)
    semantic.controls[control] = ir.ControlRegion(control, "function", owner=definition)
    semantic.resources[resource] = ir.ResourceRequirement(resource, ir.ResourceKind.GPU, "cuda:0")
    logical, version = ir.LogicalValueID("data"), ir.ValueVersionID(ir.LogicalValueID("data"), 0)
    values.add_logical_value(ir.LogicalValue(logical, "tensor"))
    values.add_version(ir.ValueVersion(version))
    graph = ir.OptimizationGraph(ir.optimization_context(semantic, evidence, values))
    payload = {"slot": slot} if slot_port else {"value": ir.ValuePattern(versions=(version,))}
    graph.add_port(ir.RegionPort("input", ir.RegionPortKind.INPUT, "argument", **payload))
    region = ir.OptimizationRegionID("region")
    graph.add_region(ir.OptimizationRegion(region, ir.RegionGranularity.FUNCTION, "compute",
                                           definitions=(definition,), ports=("input",)))
    graph.add_alternative(ir.PlanAlternative(ir.PlanAlternativeID("original"), region,
                                            "original", ir.TransformKind.NO_OP, original=True))
    return ir.IRBundle(semantic, evidence, values, optimization=graph), slot, version, control, resource


_PAYLOADS = {
    "value": ir.ValuePattern(semantic_type="explicit value pattern"),
    "slot": ir.ValueSlotID("slot"),
    "control": ir.ControlRegionID("control"),
    "resource": ir.ResourceID("resource"),
    "effect": ir.EffectTarget(ir.EffectTargetKind.FILE, "/output"),
    "operation": ir.OperationDefinitionID("operation"),
}
_ALLOWED = {
    ir.RegionPortKind.INPUT: {"value", "slot"},
    ir.RegionPortKind.OUTPUT: {"value", "slot"},
    ir.RegionPortKind.STATE: {"value", "slot", "effect"},
    ir.RegionPortKind.ESCAPE: {"value", "slot", "effect"},
    ir.RegionPortKind.CONTROL: {"control", "operation"},
    ir.RegionPortKind.RESOURCE: {"resource"},
    ir.RegionPortKind.ORDERING: {"control", "resource", "effect", "operation"},
    ir.RegionPortKind.EFFECT: {"effect"},
}


@pytest.mark.parametrize("kind", tuple(ir.RegionPortKind))
@pytest.mark.parametrize("payload", tuple(_PAYLOADS))
def test_port_kind_rejects_semantically_wrong_payload_domains(kind, payload):
    if payload in _ALLOWED[kind]:
        port = ir.RegionPort("port", kind, "boundary", **{payload: _PAYLOADS[payload]})
        assert getattr(port, payload) == _PAYLOADS[payload]
    else:
        with pytest.raises(ValueError, match="does not permit"):
            ir.RegionPort("port", kind, "boundary", **{payload: _PAYLOADS[payload]})


def test_exactly_one_payload_and_post_construction_mutation_are_checked():
    with pytest.raises(ValueError, match="exactly one"):
        ir.RegionPort("empty", ir.RegionPortKind.INPUT, "missing payload")
    with pytest.raises(ValueError, match="exactly one"):
        ir.RegionPort("multiple", ir.RegionPortKind.STATE, "ambiguous payload",
                      slot=ir.ValueSlotID("slot"), effect=_PAYLOADS["effect"])
    bundle, *_ = _bundle()
    object.__setattr__(bundle.optimization.ports["input"], "effect", _PAYLOADS["effect"])
    assert not bundle.validate()["valid"]


def test_semantic_and_effect_ports_roundtrip_without_fabricating_dynamic_values():
    bundle, slot, version, control, resource = _bundle()
    graph = bundle.optimization
    ports = (
        ir.RegionPort("state", ir.RegionPortKind.STATE, "state slot", slot=slot),
        ir.RegionPort("effect", ir.RegionPortKind.EFFECT, "file effect", effect=_PAYLOADS["effect"]),
        ir.RegionPort("effect-slot", ir.RegionPortKind.EFFECT, "slot effect",
                      effect=ir.EffectTarget(ir.EffectTargetKind.VALUE_SLOT, slot.wire)),
        ir.RegionPort("effect-version", ir.RegionPortKind.EFFECT, "version effect",
                      effect=ir.EffectTarget(ir.EffectTargetKind.VALUE_VERSION, version.wire)),
        ir.RegionPort("escape", ir.RegionPortKind.ESCAPE, "escape effect", effect=_PAYLOADS["effect"]),
        ir.RegionPort("order", ir.RegionPortKind.ORDERING, "order control", control=control),
        ir.RegionPort("resource", ir.RegionPortKind.RESOURCE, "device", resource=resource),
    )
    for port in ports:
        graph.add_port(port)
    region = next(iter(graph.regions.values()))
    region.ports += tuple(port.port_id for port in ports)
    assert graph.context.value_slots == frozenset((slot,))
    before_values = ir.canonical_json(bundle.values)
    document = bundle.to_dict()
    assert document["optimization"]["schema_version"] == 2
    restored = ir.IRBundle.from_json(ir.canonical_json(document))
    assert ir.canonical_json(restored) == ir.canonical_json(bundle)
    assert ir.canonical_json(restored.values) == before_values
    assert restored.optimization.ports["input"].value is None


def test_dangling_semantic_slot_is_rejected_even_for_an_unowned_registered_port():
    bundle, *_ = _bundle()
    bundle.optimization.add_port(ir.RegionPort("orphan", ir.RegionPortKind.OUTPUT, "unknown",
                                               slot=ir.ValueSlotID("missing")))
    assert any("unknown slot" in error for error in bundle.validate()["errors"])


@pytest.mark.parametrize("kind,reference", [
    (ir.EffectTargetKind.VALUE_SLOT, "slot:missing"),
    (ir.EffectTargetKind.VALUE_SLOT, "lv:argument"),
    (ir.EffectTargetKind.VALUE_VERSION, "lv:missing@v0"),
    (ir.EffectTargetKind.VALUE_VERSION, "lv:data@v00"),
    (ir.EffectTargetKind.VALUE_VERSION, "lv:data@v-1"),
    (ir.EffectTargetKind.VALUE_VERSION, "slot:data@v0"),
])
def test_local_effect_references_require_existing_canonical_identifiers(kind, reference):
    bundle, *_ = _bundle()
    bundle.optimization.add_port(ir.RegionPort("invalid", ir.RegionPortKind.EFFECT, "effect",
                                               effect=ir.EffectTarget(kind, reference)))
    assert not bundle.validate()["valid"]


def test_slot_context_must_match_the_actual_semantic_graph():
    bundle, *_ = _bundle(slot_port=False)
    bundle.optimization.context = replace(bundle.optimization.context, value_slots=frozenset())
    assert bundle.optimization.validate()["valid"]  # No slot port is needed to detect a stale context.
    assert any("context does not match" in error for error in bundle.validate()["errors"])


def _legacy_document():
    bundle, *_ = _bundle(slot_port=False)
    document = bundle.to_dict()
    legacy = document["optimization"]
    legacy["schema_version"] = 1
    for port in legacy["ports"]:
        del port["slot"]
        del port["effect"]
        del port["operation"]
    return document


def test_schema_one_reader_explicitly_upgrades_only_legacy_fields_without_mutation():
    document = _legacy_document()
    before = deepcopy(document)
    bundle = ir.IRBundle.from_dict(document)
    assert document == before
    assert bundle.optimization.to_dict()["schema_version"] == 2
    assert bundle.optimization.ports["input"].slot is None
    assert bundle.optimization.ports["input"].effect is None
    assert bundle.optimization.ports["input"].value is not None


@pytest.mark.parametrize("field", ("slot", "effect", "operation"))
def test_schema_one_documents_cannot_smuggle_new_fields_even_when_null(field):
    document = _legacy_document()
    document["optimization"]["ports"][0][field] = None
    with pytest.raises(ValueError, match="unknown fields"):
        ir.IRBundle.from_dict(document)


def test_schema_one_has_no_effect_kind_and_cannot_reinterpret_ordering_values():
    document = _legacy_document()
    document["optimization"]["ports"][0]["kind"] = "effect"
    with pytest.raises(ValueError, match="schema_version 1"):
        ir.IRBundle.from_dict(document)
    document["optimization"]["ports"][0]["kind"] = "ordering"
    with pytest.raises(ValueError, match="ordering port does not permit value"):
        ir.IRBundle.from_dict(document)


def test_decoding_rejects_wrong_namespace_in_semantic_slot_payload():
    bundle, *_ = _bundle()
    document = bundle.to_dict()
    document["optimization"]["ports"][0]["slot"] = ir.ResourceID("argument").as_dict()
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


def test_original_alternative_validation_visits_alternatives_linearly():
    definition = ir.OperationDefinitionID("shared-definition")
    graph = ir.OptimizationGraph(ir.OptimizationContext(definitions=frozenset((definition,))))
    for index in range(160):
        region = ir.OptimizationRegionID(str(index))
        graph.add_region(ir.OptimizationRegion(region, ir.RegionGranularity.REGION, "region",
                                               definitions=(definition,)))
        graph.add_alternative(ir.PlanAlternative(ir.PlanAlternativeID(str(index)), region,
                                                "original", ir.TransformKind.NO_OP, original=True))

    class VisitCounter(dict):
        visits = 0

        def values(self):
            for item in super().values():
                self.visits += 1
                yield item

    graph.alternatives = VisitCounter(graph.alternatives)
    assert graph.validate()["valid"]
    # Structural visit count is deterministic; this fails the old R*A scan
    # without relying on machine speed or noisy wall-clock thresholds.
    assert graph.alternatives.visits <= 4 * len(graph.alternatives)
    graph.alternatives.pop(ir.PlanAlternativeID("0"))
    assert any("exactly one original" in error for error in graph.validate()["errors"])


def test_duplicate_originals_still_fail_after_indexed_validation():
    bundle, *_ = _bundle()
    graph = bundle.optimization
    region = next(iter(graph.regions))
    graph.add_alternative(ir.PlanAlternative(ir.PlanAlternativeID("second-original"), region,
                                            "duplicate original", ir.TransformKind.NO_OP, original=True))
    assert any("exactly one original" in error for error in graph.validate()["errors"])


def test_control_and_ordering_operation_payloads_keep_definition_and_invocation_identities():
    bundle, *_ = _bundle()
    definition = next(iter(bundle.semantic.definitions))
    instance = ir.OperationInstanceID("invocation")
    bundle.evidence.add_instance(ir.OperationInstance(instance, definition, 1, 1))
    graph = bundle.optimization
    graph.context = ir.optimization_context(bundle.semantic, bundle.evidence, bundle.values)
    graph.add_port(ir.RegionPort("definition-control", ir.RegionPortKind.CONTROL,
                                "semantic control", operation=definition))
    graph.add_port(ir.RegionPort("instance-order", ir.RegionPortKind.ORDERING,
                                "execution order", operation=instance))
    next(iter(graph.regions.values())).ports += ("definition-control", "instance-order")
    before = ir.canonical_json(bundle)
    restored = ir.IRBundle.from_json(before)
    assert ir.canonical_json(restored) == before
    assert type(restored.optimization.ports["definition-control"].operation) is ir.OperationDefinitionID
    assert type(restored.optimization.ports["instance-order"].operation) is ir.OperationInstanceID
    assert graph.ports["definition-control"].control is None
    assert graph.ports["instance-order"].control is None


@pytest.mark.parametrize("identity", [ir.OperationDefinitionID("missing"), ir.OperationInstanceID("missing")])
def test_operation_port_requires_corresponding_context_identity(identity):
    bundle, *_ = _bundle()
    bundle.optimization.add_port(ir.RegionPort("dangling-operation", ir.RegionPortKind.ORDERING,
                                               "ordering", operation=identity))
    assert any("unknown operation" in error for error in bundle.validate()["errors"])


def test_operation_port_cannot_hide_wrong_namespace_inside_persisted_payload():
    bundle, *_ = _bundle()
    definition = next(iter(bundle.semantic.definitions))
    bundle.optimization.add_port(ir.RegionPort("control", ir.RegionPortKind.CONTROL,
                                               "control", operation=definition))
    document = bundle.to_dict()
    port = next(item for item in document["optimization"]["ports"] if item["port_id"] == "control")
    port["operation"] = ir.ValueSlotID("compute").as_dict()
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)

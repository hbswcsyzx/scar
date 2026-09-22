from copy import deepcopy
from dataclasses import replace
import json

import pytest

from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.analysis.regions_v2 import (
    BoundaryFacet, RegionInventory, RegionView, build_regions,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import (
    Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceGraph,
    EvidenceKind, IRBundle, OperationDefinition, OperationDefinitionID,
    OperationInstance, OperationInstanceID, OperationKind, RegionGranularity,
    SemanticGraph, TransformKind, ValueGraph,
)


CLAIM = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:closed-effects",))


def source_bundle(tmp_path, source="def f(x):\n    y = x + 1\n    return y\nf(2)\n"):
    target = tmp_path / "example.py"
    target.write_text(source)
    return IRBundle(build_semantic(target).graph, EvidenceGraph(), ValueGraph())


def runtime_bundle():
    semantic, evidence = SemanticGraph(), EvidenceGraph()
    outer, same = OperationDefinitionID("outer"), OperationDefinitionID("repeated")
    semantic.add_definition(OperationDefinition(outer, OperationKind.FUNCTION, "outer"))
    semantic.add_definition(OperationDefinition(same, OperationKind.FUNCTION, "same"))
    root, left, right = (OperationInstanceID(name) for name in ("root", "left", "right"))
    for identity, definition, parent in ((root, outer, None), (left, same, root), (right, same, root)):
        evidence.add_instance(OperationInstance(identity, definition, 1, 7, parent=parent,
                                                 metadata={"clock_domain": "clock"}))
    return IRBundle(semantic, evidence, ValueGraph()), (root, left, right)


def engine_for(bundle, *, mode=ScopeMode.DYNAMIC_PATH, closed=False):
    engine = EffectClosureEngine(bundle.semantic, bundle.evidence)
    engine.add_scope(ObservationScope("scope", "entry", "exit" if closed else None,
        "run", mode, "clock", "1", "7", closed=closed, evidence=(CLAIM,) if closed else ()))
    return engine


def test_top_down_source_regions_preserve_lexical_members_without_execution_claim(tmp_path):
    bundle = source_bundle(tmp_path, "def outer(x):\n    def inner(y):\n        return y\n    return inner(x)\n")
    inventory = build_regions(bundle, max_depth=1)
    regions = list(inventory.graph.regions.values())
    assert regions[0].parent is None
    assert set(regions[0].definitions) == set(bundle.semantic.definitions)
    assert any(item.unexpanded_children for item in inventory.constructions.values())
    assert all(item.mode is ScopeMode.ALL_PATHS and not item.effects_closed for item in inventory.constructions.values())
    assert any("Lexical" in gap.reason for gap in inventory.constructions[regions[0].id].gaps)
    assert all(not region.instances for region in regions)
    assert inventory.assert_valid()["valid"]


def test_depth_zero_keeps_full_root_membership_and_reports_unexpanded_children():
    bundle, (root, left, right) = runtime_bundle()
    inventory = build_regions(bundle, view="execution", roots=(root,), max_depth=0)
    record, = inventory.constructions.values()
    assert set(inventory.graph.regions[record.region].instances) == {root, left, right}
    assert record.children == ()
    assert record.unexpanded_children == (left, right)
    assert record.mode is ScopeMode.DYNAMIC_PATH


def test_repeated_definition_calls_keep_distinct_instance_regions():
    bundle, (root, left, right) = runtime_bundle()
    inventory = build_regions(bundle, view="execution", roots=(root,))
    siblings = [region for region in inventory.graph.regions.values() if region.parent is not None]
    assert len(siblings) == 2
    assert siblings[0].definitions == siblings[1].definitions
    assert {region.instances for region in siblings} == {(left,), (right,)}
    assert len(inventory.constructions[next(iter(inventory.graph.regions))].children) == 2


def test_explicit_noncontiguous_region_and_nesting_checks():
    bundle, (root, left, right) = runtime_bundle()
    inventory = build_regions(bundle, view="execution", roots=(root,), max_depth=0)
    outer = next(iter(inventory.graph.regions))
    selected = inventory.region((left, right), parent=outer, granularity=RegionGranularity.DATAFLOW_SUBGRAPH)
    assert inventory.graph.regions[selected].instances == (left, right)
    assert inventory.constructions[selected].direct_members == (left, right)
    with pytest.raises(ValueError, match="subset"):
        inventory.region((root,), parent=selected)
    assert inventory.assert_valid()["valid"]


def test_instance_effect_membership_does_not_collect_sibling_invocation():
    bundle, (_root, left, right) = runtime_bundle()
    engine = engine_for(bundle)
    definition = bundle.evidence.instances[left].definition
    for instance in (left, right):
        engine.add_occurrence(EffectOccurrence(instance.value, definition, EffectDimension.WRITES,
            EffectTarget(EffectTargetKind.OBJECT, instance.wire + ":state"), "scope", None, CLAIM,
            instance=instance))
    inventory = build_regions(bundle, view="execution", roots=(left,), effects=engine)
    record, = inventory.constructions.values()
    assert [item.instance for item in record.effect_occurrences] == [left]
    assert not record.effects_closed
    assert {link.occurrence_id for link in record.effect_links} == {"left"}


def test_complete_definition_effect_contract_does_not_close_instance_subset():
    bundle, (_root, left, _right) = runtime_bundle()
    engine = engine_for(bundle, closed=True)
    definition = bundle.evidence.instances[left].definition
    coverage = tuple(EffectCoverage("scope", dimension, Completeness.COMPLETE,
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
        evidence=(CLAIM,)) for dimension in EffectDimension)
    engine.add_operation_effects(OperationEffects(definition, "scope", coverage=coverage))
    record, = build_regions(bundle, view="execution", roots=(left,), effects=engine).constructions.values()
    assert not record.effects_closed
    assert record.effect_coverage == ()


def test_exact_semantic_member_effect_contract_is_preserved_but_control_stays_open():
    bundle, (_root, left, _right) = runtime_bundle()
    engine = engine_for(bundle, mode=ScopeMode.ALL_PATHS, closed=True)
    definition = bundle.evidence.instances[left].definition
    coverage = tuple(EffectCoverage("scope", dimension, Completeness.COMPLETE,
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
        evidence=(CLAIM,)) for dimension in EffectDimension)
    engine.add_operation_effects(OperationEffects(definition, "scope", coverage=coverage))
    inventory = build_regions(bundle, roots=(definition,), effects=engine)
    record, = inventory.constructions.values()
    assert record.effects_closed
    assert any(gap.facet is BoundaryFacet.CONTROL for gap in record.gaps)
    assert next(item for item in record.coverage if item.facet is BoundaryFacet.CONSUMERS).completeness is Completeness.UNKNOWN
    assert inventory.assert_valid()["valid"]
    assert RegionInventory.from_dict(inventory.to_dict(), bundle=bundle, effects=engine).to_dict() == inventory.to_dict()


def test_effect_children_outside_semantic_member_prevent_false_closure():
    bundle, (root, left, _right) = runtime_bundle()
    engine = engine_for(bundle, mode=ScopeMode.ALL_PATHS, closed=True)
    parent, child = (bundle.evidence.instances[item].definition for item in (root, left))
    coverage = tuple(EffectCoverage("scope", dimension, Completeness.COMPLETE,
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
        evidence=(CLAIM,)) for dimension in EffectDimension)
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=coverage, children=(child,)))
    engine.add_operation_effects(OperationEffects(child, "scope", coverage=coverage))
    record, = build_regions(bundle, roots=(parent,), effects=engine).constructions.values()
    assert not record.effects_closed


def test_source_slots_have_typed_ports_and_read_before_write_is_retained(tmp_path):
    bundle = source_bundle(tmp_path, "def f(x):\n    x = x + 1\n    return x\n")
    inventory = build_regions(bundle, max_depth=0)
    xs = {key for key, slot in bundle.semantic.slots.items() if slot.name == "x"}
    ports = list(inventory.graph.ports.values())
    assert any(port.kind.value == "input" and port.slot in xs for port in ports)
    assert any(port.kind.value == "output" and port.slot in xs for port in ports)
    assert any(dependency.port_ids for record in inventory.constructions.values() for dependency in record.dependencies)
    assert all(coverage.completeness is not Completeness.COMPLETE
               for record in inventory.constructions.values() for coverage in record.coverage)


@pytest.mark.parametrize("depth", [-1, True, 1.5])
def test_invalid_depth_rejected(depth):
    bundle, _ = runtime_bundle()
    with pytest.raises(ValueError, match="max_depth"):
        build_regions(bundle, view="execution", max_depth=depth)


def test_unknown_mistyped_and_nested_root_selection_rejected():
    bundle, (root, left, _right) = runtime_bundle()
    for roots in ((root, left), (OperationInstanceID("missing"),), (), (OperationDefinitionID("root"),)):
        with pytest.raises(ValueError):
            build_regions(bundle, view="execution", roots=roots)


def test_execution_cannot_adopt_all_path_or_cross_thread_scope():
    bundle, (_root, left, _right) = runtime_bundle()
    with pytest.raises(ValueError, match="ALL_PATHS"):
        build_regions(bundle, view="execution", roots=(left,), effects=engine_for(bundle, mode=ScopeMode.ALL_PATHS))
    engine = engine_for(bundle)
    bundle.evidence.instances[left].thread_id = 8
    with pytest.raises(ValueError, match="thread"):
        build_regions(bundle, view="execution", roots=(left,), effects=engine)


def test_unknown_multi_scope_selection_is_not_implicitly_merged():
    bundle, (_root, left, _right) = runtime_bundle()
    engine = engine_for(bundle)
    engine.add_scope(ObservationScope("other", "entry", None, "run", ScopeMode.DYNAMIC_PATH, "other-clock"))
    with pytest.raises(ValueError, match="explicit scope"):
        build_regions(bundle, view="execution", roots=(left,), effects=engine)
    assert build_regions(bundle, view="execution", roots=(left,), effects=engine, scope="scope").assert_valid()["valid"]


def test_builder_only_emits_original_noop_without_backend_selection(tmp_path):
    inventory = build_regions(source_bundle(tmp_path), max_depth=1)
    assert not inventory.graph.plans
    assert len(inventory.graph.alternatives) == len(inventory.graph.regions)
    assert all(item.original and item.transform is TransformKind.NO_OP and item.delta.is_empty
               for item in inventory.graph.alternatives.values())


def test_deterministic_serialization_roundtrip_and_construction_order(tmp_path):
    bundle = source_bundle(tmp_path)
    first = build_regions(bundle, max_depth=1)
    bundle.semantic.definitions = dict(reversed(list(bundle.semantic.definitions.items())))
    bundle.semantic.edges = dict(reversed(list(bundle.semantic.edges.items())))
    second = build_regions(bundle, max_depth=1)
    assert first.to_dict() == second.to_dict()
    wire = json.dumps(first.to_dict(), sort_keys=True)
    assert RegionInventory.from_json(wire, bundle=bundle).to_dict() == first.to_dict()


@pytest.mark.parametrize("corruption", ["unknown_field", "duplicate_record", "bad_scope", "bad_edge", "complete"])
def test_tampered_serialized_construction_rejected(tmp_path, corruption):
    bundle = source_bundle(tmp_path)
    inventory = build_regions(bundle, max_depth=0)
    document = deepcopy(inventory.to_dict())
    record = document["constructions"][0]
    if corruption == "unknown_field":
        record["trusted"] = True
    elif corruption == "duplicate_record":
        document["constructions"].append(deepcopy(record))
    elif corruption == "bad_scope":
        record["scope"] = "other"
    elif corruption == "bad_edge":
        record["dependencies"][0]["id"] = "absent"
    else:
        record["coverage"][0]["completeness"] = "COMPLETE"
    with pytest.raises(ValueError):
        RegionInventory.from_dict(document, bundle=bundle)


def test_mutated_member_effect_correspondence_is_revalidated():
    bundle, (_root, left, right) = runtime_bundle()
    engine = engine_for(bundle)
    occurrence = EffectOccurrence("left-write", bundle.evidence.instances[left].definition,
        EffectDimension.WRITES, EffectTarget(EffectTargetKind.OBJECT, "state"), "scope", None, CLAIM, instance=left)
    engine.add_occurrence(occurrence)
    inventory = build_regions(bundle, view="execution", roots=(left,), effects=engine)
    identity, record = next(iter(inventory.constructions.items()))
    inventory.constructions[identity] = replace(record, effect_occurrences=(replace(occurrence, instance=right),))
    assert not inventory.validate()["valid"]


def test_batch_builder_validates_input_once_not_once_per_region(monkeypatch):
    bundle, (root, _left, _right) = runtime_bundle()
    original = IRBundle.assert_valid
    calls = []
    def counting(self):
        calls.append(self)
        return original(self)
    monkeypatch.setattr(IRBundle, "assert_valid", counting)
    inventory = build_regions(bundle, view="execution", roots=(root,))
    assert len(inventory.graph.regions) == 3
    # One input validation plus one fresh projection validation, independent
    # of the number of emitted regions; no permanently trusted mutable index.
    assert calls == [bundle, bundle]


@pytest.mark.parametrize("corruption", ["dependency", "port", "effect", "effect_link"])
def test_omitted_known_boundary_records_rejected(tmp_path, corruption):
    bundle = source_bundle(tmp_path)
    engine = EffectClosureEngine(bundle.semantic)
    engine.add_scope(ObservationScope("scope", "enter", None, "run", ScopeMode.ALL_PATHS, "source"))
    definition = next(iter(bundle.semantic.definitions))
    engine.add_occurrence(EffectOccurrence("known-effect", definition, EffectDimension.MAY_RAISE,
        EffectTarget(EffectTargetKind.OPAQUE, "known-exception"), "scope", None, CLAIM))
    inventory = build_regions(bundle, max_depth=0, effects=engine)
    identity, record = next(iter(inventory.constructions.items()))
    if corruption == "dependency":
        inventory.constructions[identity] = replace(record, dependencies=record.dependencies[1:])
    elif corruption == "port":
        region = inventory.graph.regions[identity]
        victim = region.ports[0]
        inventory.constructions[identity] = replace(record, dependencies=tuple(
            replace(item, port_ids=tuple(key for key in item.port_ids if key != victim)) for item in record.dependencies),
            effect_links=tuple(item for item in record.effect_links if item.port_id != victim))
        region.ports = tuple(item for item in region.ports if item != victim)
        del inventory.graph.ports[victim]
    elif corruption == "effect":
        inventory.constructions[identity] = replace(record, effect_occurrences=(), effect_links=())
    else:
        inventory.constructions[identity] = replace(record, effect_links=())
    assert not inventory.validate()["valid"]


def test_mutated_graph_source_edge_invalidates_stale_inventory_indices(tmp_path):
    bundle = source_bundle(tmp_path)
    inventory = build_regions(bundle, max_depth=0)
    # Remove an edge from the source graph after constructing its indexed view.
    selected = next(item for item in bundle.semantic.edges.values() if item.relation.value == "reads_slot")
    del bundle.semantic.edges[selected.edge_id]
    assert not inventory.validate()["valid"]


def test_runtime_granularity_uses_typed_operation_kind_not_label():
    semantic, evidence = SemanticGraph(), EvidenceGraph()
    expected = {OperationKind.MODULE: RegionGranularity.FUNCTION,
                OperationKind.KERNEL: RegionGranularity.OPERATOR,
                OperationKind.OPERATOR: RegionGranularity.OPERATOR,
                OperationKind.ALLOCATION: RegionGranularity.INSTRUCTION,
                OperationKind.TRANSFER: RegionGranularity.INSTRUCTION,
                OperationKind.LOOP: RegionGranularity.INSTRUCTION}
    for kind in expected:
        definition, instance = OperationDefinitionID(kind.value), OperationInstanceID(kind.value)
        semantic.add_definition(OperationDefinition(definition, kind, "same misleading label"))
        evidence.add_instance(OperationInstance(instance, definition, 1, 1))
    inventory = build_regions(IRBundle(semantic, evidence, ValueGraph()), view="execution", max_depth=0)
    for region in inventory.graph.regions.values():
        definition = semantic.definitions[region.definitions[0]]
        assert region.granularity is expected[definition.kind]


def test_known_control_resource_exception_escape_and_data_interfaces_preserved():
    from scar.ir.v2 import (
        ControlRegion, ControlRegionID, EvidenceEdge, EvidenceEndpoint, EvidenceNodeKind,
        EvidenceRelation, LogicalValue, LogicalValueID, ResourceID, ResourceKind,
        ResourceRequirement, ValueVersion, ValueVersionID,
    )
    bundle, (root, left, right) = runtime_bundle()
    value = LogicalValueID("input")
    version = ValueVersionID(value, 0)
    bundle.values.add_logical_value(LogicalValue(value, "scalar"))
    bundle.values.add_version(ValueVersion(version))
    definition = bundle.evidence.instances[left].definition
    control, resource = ControlRegionID("branch"), ResourceID("gpu")
    bundle.semantic.add_control(ControlRegion(control, "branch", owner=definition))
    bundle.semantic.add_resource(ResourceRequirement(resource, ResourceKind.GPU, "cuda:0"))
    bundle.semantic.definitions[definition].control_region = control
    bundle.semantic.definitions[definition].resource_requirements = (resource,)
    bundle.evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.VALUE_VERSION, version))
    bundle.evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.RESOURCE, resource))
    instance_endpoint = lambda item: EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, item)
    for identity, relation, source, target in (
        ("read", EvidenceRelation.OBSERVED_READ, instance_endpoint(left), EvidenceEndpoint(EvidenceNodeKind.VALUE_VERSION, version)),
        ("write", EvidenceRelation.PRODUCES, instance_endpoint(left), EvidenceEndpoint(EvidenceNodeKind.VALUE_VERSION, version)),
        ("order", EvidenceRelation.HAPPENS_BEFORE, instance_endpoint(right), instance_endpoint(left)),
        ("dispatch", EvidenceRelation.CONTROLS_INSTANCE, instance_endpoint(root), instance_endpoint(left)),
        ("resource", EvidenceRelation.USES_RESOURCE, instance_endpoint(left), EvidenceEndpoint(EvidenceNodeKind.RESOURCE, resource)),
    ):
        bundle.evidence.add_edge(EvidenceEdge(identity, relation, source, target, CLAIM))
    engine = engine_for(bundle)
    for identity, dimension, target in (
        ("exception", EffectDimension.MAY_RAISE, EffectTarget(EffectTargetKind.OPAQUE, "possible-exception")),
        ("escape", EffectDimension.ESCAPES, EffectTarget(EffectTargetKind.EXTERNAL, "callback")),
        ("state", EffectDimension.WRITES, EffectTarget(EffectTargetKind.OBJECT, "hidden-state")),
    ):
        engine.add_occurrence(EffectOccurrence(identity, definition, dimension, target, "scope", None, CLAIM, instance=left))
    inventory = build_regions(bundle, view="execution", roots=(left,), effects=engine)
    ports = tuple(inventory.graph.ports.values())
    assert {"input", "output", "state", "control", "resource", "effect", "escape", "ordering"}.issubset({port.kind.value for port in ports})
    assert any(port.kind.value == "ordering" and port.operation == right for port in ports)
    assert any(port.kind.value == "control" and port.operation == root for port in ports)
    record, = inventory.constructions.values()
    assert all(item.port_ids for item in record.dependencies)
    assert inventory.assert_valid()["valid"]


class _CountedTuple(tuple):
    def __new__(cls, values):
        result = super().__new__(cls, values)
        result.iterations = 0
        result.membership_queries = 0
        return result

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()

    def __contains__(self, item):
        self.membership_queries += 1
        return super().__contains__(item)


@pytest.mark.parametrize("size", [8, 32])
def test_dependency_and_effect_validation_index_ports_once_per_region(tmp_path, size):
    """A larger boundary must not rescan its port tuple per edge or effect."""
    bundle = source_bundle(tmp_path, "\n".join(f"v{index} = {index}" for index in range(size)))
    engine = EffectClosureEngine(bundle.semantic)
    engine.add_scope(ObservationScope("scope", "entry", None, "run", ScopeMode.ALL_PATHS, "source"))
    definition = next(iter(bundle.semantic.definitions))
    for index in range(size):
        engine.add_occurrence(EffectOccurrence(f"effect:{index}", definition, EffectDimension.WRITES,
            EffectTarget(EffectTargetKind.OBJECT, f"state:{index}"), "scope", None, CLAIM))
    inventory = build_regions(bundle, max_depth=0, effects=engine)
    region, = inventory.graph.regions.values()
    construction = inventory.constructions[region.id]
    assert len(construction.dependencies) > size
    assert len(construction.effect_links) >= size
    ports = _CountedTuple(region.ports)
    region.ports = ports
    assert inventory.assert_valid()["valid"]
    # A constant number of complete schema/projection passes is allowed.
    # One tuple iteration per dependency would exceed this bound even at 8.
    assert ports.iterations <= 10
    assert ports.membership_queries == 0


@pytest.mark.parametrize("size", [8, 32])
def test_wide_region_hierarchy_batches_sibling_and_parent_membership_indexes(tmp_path, monkeypatch, size):
    """Do not repeatedly sort sibling prefixes or scan parent membership."""
    import scar.analysis.regions_v2 as regions_module
    from scar.ir.v2 import OptimizationGraph, OptimizationRegionID
    bundle = source_bundle(tmp_path, "\n".join(f"v{index} = {index}" for index in range(size)))
    original_ordered, original_add = regions_module._ordered, OptimizationGraph.add_region
    child_items, parent_members = [], []
    def counted_ordered(values):
        values = tuple(values)
        if values and isinstance(values[0], OptimizationRegionID):
            child_items.append(len(values))
        return original_ordered(values)
    def counted_add(self, region):
        original_add(self, region)
        if region.parent is None:
            region.definitions = _CountedTuple(region.definitions)
            parent_members.append(region.definitions)
    monkeypatch.setattr(regions_module, "_ordered", counted_ordered)
    monkeypatch.setattr(OptimizationGraph, "add_region", counted_add)
    inventory = build_regions(bundle, max_depth=1)
    assert len(inventory.graph.regions) > size
    # Initial build plus omission-check reconstruction: two complete sibling
    # lists, as opposed to a triangular sum of sibling prefixes.
    assert sum(child_items) <= 2 * len(inventory.graph.regions)
    assert all(values.iterations <= 10 for values in parent_members)
    root = next(region for region in inventory.graph.regions.values() if region.parent is None)
    children = _CountedTuple(inventory.constructions[root.id].children)
    inventory.constructions[root.id] = replace(inventory.constructions[root.id], children=children)
    assert inventory.assert_valid()["valid"]
    assert children.membership_queries == 0
    assert children.iterations <= 5

"""Independent source-model counterexamples for conditional dataflow edges."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis.constants_v2 import ConstantStatus, evaluate_constants
from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import (
    BindingStatus, BoundaryKind, ImportForm, ImportSpec, Opcode, SourceSemanticsGraph,
)


def capture(tmp_path, text, files=None):
    for relative, content in (files or {}).items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    path = tmp_path / "program.py"
    path.write_text(text)
    sg = build_semantic(path, project_root=tmp_path).graph
    return path, sg, extract_source_semantics(sg)


def named_use(sg, graph, name, line):
    return next(use for use in graph.uses.values()
                if sg.slots[use.slot].name == name and use.source.start_line == line)


def test_import_preserves_conditional_producer_without_upgrading_exact(tmp_path):
    _, sg, graph = capture(tmp_path, "import random_fixture as p\ny = p.TABLE[0]\n",
                          {"random_fixture.py": "TABLE = (7, 8)\n"})
    use = named_use(sg, graph, "p", 2)
    assert use.status is BindingStatus.UNRESOLVED and use.reaching == ()
    assert len(use.conditional_reaching) == 1
    binding = graph.bindings[use.conditional_reaching[0]]
    op = graph.operations[graph.values[binding.value].producer]
    assert op.opcode is Opcode.IMPORT and op.import_spec.bound_name == "p"
    assert any(item.kind is BoundaryKind.IMPORT for item in graph.boundaries)
    assert evaluate_constants(graph).facts[graph.operations[use.operation].result].status is not ConstantStatus.CONSTANT
    assert validate_source_semantics(graph, sg)["valid"]


@pytest.mark.parametrize("statement, name, module", [
    ("import a.b", "a", "a"),
    ("import a.b as p", "p", "a.b"),
    ("import a as p", "p", "a"),
])
def test_dotted_import_bound_module_is_not_requested_module(tmp_path, statement, name, module):
    _, sg, graph = capture(tmp_path, statement + "\n", {"a/__init__.py": "", "a/b.py": "TABLE = (2,)\n"})
    op, = [op for op in graph.operations.values() if op.opcode is Opcode.IMPORT]
    spec = op.import_spec
    assert spec.form is ImportForm.MODULE and spec.bound_name == name
    assert sg.modules[spec.bound_module].name == module
    assert spec.requested == ("a" if statement == "import a as p" else "a.b")


def test_relative_from_import_preserves_form_alias_and_requested_syntax(tmp_path):
    _, sg, graph = capture(tmp_path, "import pkg\n", {
        "pkg/__init__.py": "from .data import TABLE as PUBLIC\n",
        "pkg/data.py": "TABLE = (3, 4)\n",
    })
    op = next(op for op in graph.operations.values() if op.opcode is Opcode.IMPORT and op.import_spec.relative_level)
    spec = op.import_spec
    assert spec.form is ImportForm.FROM and spec.symbol == "TABLE"
    assert spec.relative_level == 1 and spec.requested == "data"
    assert spec.bound_name == "PUBLIC" and spec.asname == "PUBLIC"
    assert spec.bound_module is None
    assert graph.assert_valid(sg)["valid"]


def test_candidate_updates_on_explicit_rebind_and_does_not_cache_prior_version(tmp_path):
    _, sg, graph = capture(tmp_path, "import arbitrary as p\np = 9\nresult = p\n")
    use = named_use(sg, graph, "p", 3)
    assert use.status is BindingStatus.UNRESOLVED
    binding, = [graph.bindings[item] for item in use.conditional_reaching]
    assert binding.source.start_line == 2 and binding.epoch == 1
    assert any(item.kind is BoundaryKind.REBIND for item in graph.boundaries)


@pytest.mark.parametrize("text, kind, line", [
    ("x = 7\nopaque()\ny = x\n", BoundaryKind.CALL, 3),
    ("x = 7\nif condition:\n    x = 9\ny = x\n", BoundaryKind.CONTROL, 4),
    ("x = 7\nwhile condition:\n    x = 9\ny = x\n", BoundaryKind.CONTROL, 4),
    ("x = 7\ny = unknown + 1\nz = x\n", BoundaryKind.OPAQUE, 3),
])
def test_invalidation_boundary_keeps_candidate_and_specific_risk(tmp_path, text, kind, line):
    _, sg, graph = capture(tmp_path, text)
    use = named_use(sg, graph, "x", line)
    assert use.status is BindingStatus.UNRESOLVED and use.conditional_reaching
    binding = graph.bindings[use.conditional_reaching[0]]
    assert any(item.kind is kind and item.scope == use.scope and item.block == use.block
               and binding.position < item.position < use.position for item in graph.boundaries)
    assert evaluate_constants(graph).facts[graph.operations[use.operation].result].status is not ConstantStatus.CONSTANT


def test_parameters_and_cross_branch_bindings_do_not_gain_candidate_edges(tmp_path):
    _, sg, graph = capture(tmp_path, "outer = 7\ndef f(x):\n    y = x\n    return outer\n")
    for name, line in (("x", 3), ("outer", 4)):
        use = named_use(sg, graph, name, line)
        assert use.status is BindingStatus.UNRESOLVED and not use.conditional_reaching


def test_conditionally_linked_graph_roundtrip_is_deterministic_and_replays(tmp_path):
    _, sg, graph = capture(tmp_path, "import arbitrary as p\na = p.TABLE[0]\n")
    encoded = graph.to_json()
    restored = SourceSemanticsGraph.from_json(encoded, sg)
    assert restored.to_json() == encoded
    assert validate_source_semantics(restored, sg)["valid"]


def test_forged_boundary_kind_is_rejected_by_source_replay(tmp_path):
    _, sg, graph = capture(tmp_path, "x = 1\nopaque()\ny = x\n")
    graph.boundaries = tuple(replace(item, kind=BoundaryKind.IMPORT)
                             if item.kind is BoundaryKind.CALL else item for item in graph.boundaries)
    assert graph.assert_valid(sg)["valid"]
    assert not validate_source_semantics(graph, sg)["valid"]


@pytest.mark.parametrize("tamper", ["future", "different_slot", "duplicate_boundary"])
def test_structural_conditional_reference_forgery_is_rejected(tmp_path, tamper):
    _, sg, graph = capture(tmp_path, "x = 1\nopaque()\ny = x\nz = 2\n")
    use = named_use(sg, graph, "x", 3)
    binding = graph.bindings[use.conditional_reaching[0]]
    if tamper == "future":
        graph.bindings[binding.id] = replace(binding, position=use.position + 1)
    elif tamper == "different_slot":
        other = next(item for item in graph.bindings.values() if sg.slots[item.slot].name == "z")
        graph.uses[use.id] = replace(use, conditional_reaching=(other.id,))
    else:
        graph.boundaries += (graph.boundaries[0],)
    assert not graph.validate(sg)["valid"]


def legacy_document(graph):
    document = deepcopy(graph.to_dict())
    document["schema_version"] = 1
    document.pop("boundaries")
    for use in document["uses"]:
        use.pop("conditional_reaching")
    for op in document["operations"]:
        if op["import_spec"] is not None:
            for field in ("form", "bound_name", "asname", "bound_module"):
                op["import_spec"].pop(field)
    return document


def test_legacy_schema_migration_does_not_fabricate_source_links(tmp_path):
    _, sg, graph = capture(tmp_path, "import arbitrary as p\ny = p\n")
    old = legacy_document(graph)
    restored = SourceSemanticsGraph.from_dict(old, sg)
    assert restored.boundaries == ()
    assert all(not use.conditional_reaching for use in restored.uses.values())
    assert all(op.import_spec.bound_name is None for op in restored.operations.values() if op.import_spec)
    # A reader can retain historical records, but they do not attest the new
    # extractor's full source model or its conditional paths.
    assert not validate_source_semantics(restored, sg)["valid"]
    assert old == legacy_document(graph)


@pytest.mark.parametrize("field", ["boundaries", "conditional_reaching", "bound_name"])
def test_legacy_schema_cannot_smuggle_new_fields(tmp_path, field):
    _, sg, graph = capture(tmp_path, "import arbitrary as p\ny = p\n")
    old = legacy_document(graph)
    if field == "boundaries":
        old[field] = []
    elif field == "conditional_reaching":
        old["uses"][0][field] = []
    else:
        next(op for op in old["operations"] if op["import_spec"])["import_spec"][field] = "p"
    with pytest.raises(ValueError, match="fields mismatch"):
        SourceSemanticsGraph.from_dict(old, sg)


def test_analysis_keeps_target_source_and_import_side_effect_unexecuted(tmp_path):
    marker = tmp_path / "must_not_exist"
    _, sg, graph = capture(tmp_path, "import arbitrary as p\ny = p.TABLE[0]\n", {
        "arbitrary.py": f"open({str(marker)!r}, 'w').write('side effect')\nTABLE = (7,)\n",
    })
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.py")}
    assert validate_source_semantics(graph, sg)["valid"]
    assert not marker.exists()
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.py")}


def test_region_inventory_preserves_optional_source_overlay_context(tmp_path):
    from scar.analysis.regions_v2 import RegionInventory
    from scar.ir.v2 import EvidenceGraph, IRBundle, ValueGraph
    _, sg, graph = capture(tmp_path, "answer = 3 + 4\n")
    bundle = IRBundle(sg, EvidenceGraph(), ValueGraph(), source_semantics=graph)
    inventory = RegionInventory(bundle)
    op = next(op for op in graph.operations.values() if op.opcode is Opcode.ADD)
    region = inventory.region((op.operation,))
    assert inventory.assert_valid()["valid"]
    assert op.result in inventory.graph.context.static_values
    restored = RegionInventory.from_dict(inventory.to_dict(), bundle=bundle)
    assert region in restored.constructions
    assert restored.to_dict() == inventory.to_dict()


@pytest.mark.parametrize("form", ["read", "assignment", "import"])
def test_typed_sg_slot_edge_cannot_lie_about_source_identifier(tmp_path, form):
    from scar.ir.v2.semantic import SemanticEndpoint, SemanticNodeKind, SemanticRelation
    _, sg, graph = capture(tmp_path, "import arbitrary as p\nx = 11\ny = 99\nanswer = x + 2\n")
    if form == "read":
        operation = next(op for op in graph.operations.values() if op.opcode is Opcode.READ and op.source.start_line == 4)
        relation = SemanticRelation.READS_SLOT
    elif form == "assignment":
        operation = next(op for op in graph.operations.values() if op.opcode is Opcode.ALIAS and op.source.start_line == 2)
        relation = SemanticRelation.WRITES_SLOT
    else:
        operation = next(op for op in graph.operations.values() if op.opcode is Opcode.IMPORT)
        relation = SemanticRelation.WRITES_SLOT
    other = next(slot.slot_id for slot in sg.slots.values()
                 if slot.name == "y" and slot.owner == operation.scope)
    edge = next(edge for edge in sg.edges.values()
                if edge.relation is relation and edge.source.id == operation.operation)
    sg.edges[edge.edge_id] = replace(edge, target=SemanticEndpoint(SemanticNodeKind.VALUE_SLOT, other))
    assert sg.validate()["valid"]
    assert not validate_source_semantics(graph, sg)["valid"]
    with pytest.raises(ValueError, match="disagrees.*source"):
        extract_source_semantics(sg)

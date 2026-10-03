"""Known read interfaces must survive graph→invocation-slot joins."""
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import SemanticRelation
from scar.ir.v2.codec import semantic_from_dict
import pytest


def test_expression_call_and_import_actual_reads_are_separate_from_owned_ports(tmp_path):
    (tmp_path / "data.py").write_text("VALUE = 2\n")
    (tmp_path / "program.py").write_text(
        "from data import VALUE\n"
        "def function(x):\n"
        "    return callback(x + VALUE)\n"
        "result = function(VALUE)\n"
    )
    graph = build_semantic(tmp_path).graph
    reads = {}
    for edge in graph.edges.values():
        if edge.relation is SemanticRelation.READS_SLOT:
            reads.setdefault(edge.source.id, set()).add(edge.target.id)
    assert reads
    for operation, slots in reads.items():
        definition = graph.definitions[operation]
        assert all(graph.slots[slot].owner in (None, operation)
                   for slot in definition.input_slots)
        assert slots <= set(graph.slots)
        assert len(set(definition.input_slots)) == len(definition.input_slots)
        # An explicit read interface cannot upgrade the unknown effect model.
        assert not graph.effects[definition.effect_summary].is_complete


def test_duplicate_operand_uses_do_not_duplicate_distinct_slot_interfaces(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def run(x):\n    return x + x\n")
    graph = build_semantic(source).graph
    reads = [operation for operation in graph.definitions.values()
             if operation.label == "read x"]
    assert len(reads) == 2
    source_slots = [edge.target.id for edge in graph.edges.values()
                    if edge.relation is SemanticRelation.READS_SLOT
                    and edge.source.id in {operation.id for operation in reads}]
    assert len(source_slots) == 2 and source_slots[0] == source_slots[1]
    addition = next(operation for operation in graph.definitions.values()
                    if operation.label == "BinOp")
    expression_slots = [edge.target.id for edge in graph.edges.values()
                        if edge.relation is SemanticRelation.READS_SLOT
                        and edge.source.id == addition.id]
    assert len(set(expression_slots)) == 2  # distinct expression-result slots


def test_duplicate_formal_declarations_cannot_collapse_into_complete_coverage(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("def run(x):\n    return x\n")
    graph = build_semantic(source).graph
    function = next(operation for operation in graph.definitions.values()
                    if operation.input_slots)
    wire = graph.to_dict()
    function.input_slots += function.input_slots
    assert not graph.validate()["valid"]
    record = next(item for item in wire["definitions"]
                  if item["id"]["wire"] == function.id.wire)
    record["input_slots"] += record["input_slots"]
    with pytest.raises(ValueError, match="repeat a formal slot"):
        semantic_from_dict(wire)

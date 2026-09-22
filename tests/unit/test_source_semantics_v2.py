from dataclasses import replace

import pytest

from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import BindingStatus, Opcode, SourceSemanticsGraph


def model(tmp_path, text):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    return path, semantic, extract_source_semantics(semantic)


def test_ordered_operands_and_binding_versions_are_connected_to_source(tmp_path):
    _, sg, graph = model(tmp_path, "x = 10\ny = x - 3\nx = 4\nz = x - 1\n")
    subtract = sorted((op for op in graph.operations.values() if op.opcode is Opcode.SUB),
                      key=lambda op: op.source.start_line)
    assert len(subtract) == 2
    assert [[use.role for use in op.operands] for op in subtract] == [["left", "right"]] * 2
    reads = sorted(graph.uses.values(), key=lambda use: use.source.start_line)
    assert all(use.status is BindingStatus.EXACT for use in reads)
    assert reads[0].slot == reads[1].slot
    assert reads[0].reaching != reads[1].reaching
    assert graph.bindings[reads[0].reaching[0]].epoch == 0
    assert graph.bindings[reads[1].reaching[0]].epoch == 1
    assert graph.assert_valid(sg)["valid"]
    assert validate_source_semantics(graph, sg)["valid"]


def test_byte_offsets_and_source_snapshots_roundtrip_deterministically(tmp_path):
    _, sg, graph = model(tmp_path, "数 = 9; 结果 = 数 + 2\n")
    plus, = [op for op in graph.operations.values() if op.opcode is Opcode.ADD]
    assert plus.source.start_column == len("数 = 9; 结果 = ".encode())
    encoded = graph.to_dict()
    restored = SourceSemanticsGraph.from_dict(encoded, semantic=sg)
    assert restored.to_dict() == encoded
    assert validate_source_semantics(restored, sg)["valid"]


def test_while_condition_does_not_reuse_declaration_time_value(tmp_path):
    _, _, graph = model(tmp_path, "x = 1\nwhile x < 4:\n    x += 1\n")
    reads = [use for use in graph.uses.values() if use.source.start_line == 2]
    assert reads
    assert all(use.status is not BindingStatus.EXACT for use in reads)


def test_source_replay_rejects_stale_file_and_replaced_operator(tmp_path):
    path, sg, graph = model(tmp_path, "x = 9 - 2\n")
    subtraction, = [op for op in graph.operations.values() if op.opcode is Opcode.SUB]
    graph.operations[subtraction.operation] = replace(subtraction, opcode=Opcode.ADD)
    # Shape-valid IR still needs correspondence to what the source actually says.
    assert graph.assert_valid(sg)["valid"]
    assert not validate_source_semantics(graph, sg)["valid"]
    path.write_text("x = 9 + 2\n")
    with pytest.raises(ValueError, match="fingerprint"):
        extract_source_semantics(sg)


def test_mutable_containers_are_construction_operations_not_literals(tmp_path):
    _, _, graph = model(tmp_path, "a = [1, 2]\nb = (1, 2)\nc = {'x': 3}\n")
    operators = {op.opcode for op in graph.operations.values()}
    assert {Opcode.BUILD_LIST, Opcode.BUILD_TUPLE, Opcode.BUILD_DICT} <= operators
    assert all(op.literal is None for op in graph.operations.values()
               if op.opcode in {Opcode.BUILD_LIST, Opcode.BUILD_TUPLE, Opcode.BUILD_DICT})


def test_module_import_aliases_remain_operations_and_initialization_gap(tmp_path):
    _, sg, graph = model(tmp_path, "import arbitrary_dependency as p\nfrom another_dependency import x as a, y as b\ny = a\n")
    imports = [op for op in graph.operations.values() if op.opcode is Opcode.IMPORT]
    assert len(imports) == 3
    assert {(op.import_spec.requested, op.import_spec.symbol) for op in imports} == {
        ("arbitrary_dependency", None), ("another_dependency", "x"), ("another_dependency", "y")}
    assert all(op.import_spec.module is None for op in imports)
    assert any("Loader" in gap.reason for gap in graph.gaps)
    assert graph.assert_valid(sg)["valid"]


def test_opaque_binary_dispatch_prevents_stale_module_bindings(tmp_path):
    _, _, graph = model(tmp_path, "x = 3\na = opaque_object + 1\nb = x\n")
    last = next(use for use in graph.uses.values() if use.source.start_line == 3)
    assert last.status is BindingStatus.UNRESOLVED


def test_exact_builtin_arithmetic_does_not_erase_independent_local_bindings(tmp_path):
    _, _, graph = model(tmp_path, "x = 3\na = 1 + 2\nb = x\n")
    last = next(use for use in graph.uses.values() if use.source.start_line == 3)
    assert last.status is BindingStatus.EXACT


def test_deferred_method_body_is_modeled_without_trusting_custom_class_namespace(tmp_path):
    from scar.analysis.constants_v2 import ConstantStatus, evaluate_constants
    _, sg, graph = model(tmp_path, "class Model(metaclass=Unknown):\n    a = 3\n    b = a\n    def forward(self, x):\n        n = 10 - 3\n        return n\n")
    class_use = next(use for use in graph.uses.values() if use.source.start_line == 3)
    method_use = next(use for use in graph.uses.values() if use.source.start_line == 6)
    assert class_use.status is BindingStatus.UNRESOLVED
    assert method_use.status is BindingStatus.EXACT
    facts = evaluate_constants(graph)
    returned = graph.operations[method_use.operation].result
    assert facts.facts[returned].status is ConstantStatus.CONSTANT
    assert facts.facts[returned].literal.to_python() == 7
    assert validate_source_semantics(graph, sg)["valid"]

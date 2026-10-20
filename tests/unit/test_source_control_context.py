from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from scar.analysis.program_lowering import prepare_source
from scar.analysis.source_control_context import index_source_control_contexts
from scar.ir.control_flow_v2 import NodeKind
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.v2.semantic import OperationKind


def _prepared(tmp_path: Path, text: str, *, name: str = "context_case.py"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    prepared = prepare_source(path, project_root=tmp_path)
    index = index_source_control_contexts(
        prepared.semantic, prepared.semantics, prepared.control,
        source_path=prepared.path, source_text=prepared.text, max_work=10_000_000)
    return prepared, index


def _ref(prepared, node: ast.AST):
    start = (getattr(node, "lineno", None), getattr(node, "end_lineno", None),
             getattr(node, "col_offset", None), getattr(node, "end_col_offset", None))
    matches = [atom.reference for atom in prepared.semantic.source_atoms.values()
               if atom.kind == type(node).__name__
               and (atom.reference.start_line, atom.reference.end_line,
                    atom.reference.start_column, atom.reference.end_column) == start]
    assert len(matches) == 1, (type(node).__name__, start, matches)
    return matches[0]


def _call(prepared, name: str, line: int):
    matches = [node for node in ast.walk(prepared.tree)
               if isinstance(node, ast.Call) and node.lineno == line
               and isinstance(node.func, ast.Name) and node.func.id == name]
    assert len(matches) == 1, (name, line, matches)
    return matches[0]


def _scope(prepared, name: str, line: int) -> OperationDefinitionID:
    matches = [item.id for item in prepared.semantic.definitions.values()
               if item.kind in {OperationKind.FUNCTION, OperationKind.METHOD}
               and item.metadata.get("phase") == "call_time"
               and item.metadata.get("callable_name") == name
               and item.source_start == line]
    assert len(matches) == 1, (name, line, matches)
    return matches[0]


def _context(index, reference, scope=None):
    rows = index.query(reference, scope)
    matching = [item for item in rows if item.expression_source == reference]
    assert matching
    return matching[0]


def _assert_link(prepared, context, scope):
    assert context.scope == scope
    assert context.statement_source is not None
    assert context.control_nodes
    assert context.execution_proven is False
    for node_id in context.control_nodes:
        node = prepared.control.nodes[node_id]
        assert node.scope == scope
        assert node.source == context.statement_source
        assert node.kind in {NodeKind.STATEMENT, NodeKind.BRANCH_TEST,
                             NodeKind.LOOP_TEST, NodeKind.GAP}


def test_nested_same_line_calls_and_branch_loop_calls_keep_exact_structural_paths(tmp_path):
    prepared, index = _prepared(tmp_path, """\
def f(flag):
    result = outer(inner()); another = twin()
    if gate(flag) and second_gate():
        branch = consume(result)
    while condition():
        looped = tick()
    for item in values():
        seen(item)
    return result
""")
    scope = _scope(prepared, "f", 1)

    outer = _context(index, _ref(prepared, _call(prepared, "outer", 2)), scope)
    inner = _context(index, _ref(prepared, _call(prepared, "inner", 2)), scope)
    twin = _context(index, _ref(prepared, _call(prepared, "twin", 2)), scope)
    _assert_link(prepared, outer, scope)
    _assert_link(prepared, inner, scope)
    _assert_link(prepared, twin, scope)
    assert outer.statement_source == inner.statement_source
    assert outer.statement_source != twin.statement_source
    assert outer.field_path != inner.field_path
    # Both assignments can use the same relative "value" field. The anchor
    # and field path together identify the structural location.
    assert (outer.statement_source, outer.field_path) != (twin.statement_source, twin.field_path)

    branch_test = _context(index, _ref(prepared, _call(prepared, "second_gate", 3)), scope)
    branch_body = _context(index, _ref(prepared, _call(prepared, "consume", 4)), scope)
    loop_test = _context(index, _ref(prepared, _call(prepared, "condition", 5)), scope)
    loop_body = _context(index, _ref(prepared, _call(prepared, "tick", 6)), scope)
    iterator = _context(index, _ref(prepared, _call(prepared, "values", 7)), scope)
    for item in (branch_test, branch_body, loop_test, loop_body, iterator):
        _assert_link(prepared, item, scope)
    assert "BOOLEAN_SHORT_CIRCUIT" in branch_test.boundaries
    assert "WHILE_LOOP_TEST" in loop_test.boundaries
    assert "FOR_ITERATION_MAY_RAISE_OR_CALL_USER_CODE" in iterator.boundaries

    foreign = OperationDefinitionID("not-a-semantic-owner")
    unknown_owner = index.query(_ref(prepared, _call(prepared, "outer", 2)), foreign)
    assert len(unknown_owner) == 1
    assert unknown_owner[0].operation is None
    assert unknown_owner[0].scope == scope
    assert unknown_owner[0].control_nodes == ()
    assert unknown_owner[0].statement_source == outer.statement_source
    assert unknown_owner[0].gap == "QUERY_SCOPE_NOT_IN_SEMANTIC_GRAPH"
    assert unknown_owner[0].execution_proven is False


def test_defaults_decorators_class_and_with_function_phase_boundaries(tmp_path):
    prepared, index = _prepared(tmp_path, """\
def seeded(item=module_default()):
    return consume_seeded(item)
class Holder:
    @decorate(decorator_value())
    def method(self, item=class_default()):
        return consume_method(item)
with manager():
    def later(item=with_default()):
        return consume_later(item)
""")

    module_scope = next(module.initializer for module in prepared.semantic.modules.values()
                        if module.path == str(prepared.path))
    default = _context(index, _ref(prepared, _call(prepared, "module_default", 1)),
                       module_scope)
    _assert_link(prepared, default, module_scope)
    assert default.field_path
    assert [(step.field, step.index) for step in default.field_path[:2]] == [
        ("args", None), ("defaults", 0)]
    assert "FUNCTION_DEFAULT_DEFINITION_TIME" in default.boundaries

    class_default = _context(index, _ref(prepared, _call(prepared, "class_default", 5)))
    assert "FUNCTION_DEFAULT_DEFINITION_TIME" in class_default.boundaries
    assert class_default.gap and "CLASS_NAMESPACE_HAS_NO_RELIABLE_CFG_SUITE" in class_default.gap
    decorator = _context(index, _ref(prepared, _call(prepared, "decorator_value", 4)))
    assert "FUNCTION_DECORATOR_DEFINITION_TIME" in decorator.boundaries
    assert decorator.gap and "CLASS_NAMESPACE_HAS_NO_RELIABLE_CFG_SUITE" in decorator.gap

    method_scope = _scope(prepared, "method", 5)
    method_body = _context(index, _ref(prepared, _call(prepared, "consume_method", 6)), method_scope)
    _assert_link(prepared, method_body, method_scope)
    assert "CLASS_NAMESPACE_BODY" not in method_body.boundaries
    assert "CLASS_NAMESPACE_HAS_NO_RELIABLE_CFG_SUITE" not in (method_body.gap or "")

    later_scope = _scope(prepared, "later", 8)
    later_body = _context(index, _ref(prepared, _call(prepared, "consume_later", 9)), later_scope)
    _assert_link(prepared, later_body, later_scope)
    assert "WITH_FINALIZER_OR_RESOURCE_BOUNDARY" not in later_body.boundaries
    assert "WITH_CONTROL_HAS_NO_RELIABLE_SOURCE_CONTEXT" not in (later_body.gap or "")
    with_default = _context(index, _ref(prepared, _call(prepared, "with_default", 8)))
    assert "FUNCTION_DEFAULT_DEFINITION_TIME" in with_default.boundaries
    assert "WITH_FINALIZER_OR_RESOURCE_BOUNDARY" in with_default.boundaries


def test_short_circuit_deferred_and_optimization_boundaries_never_prove_execution(tmp_path):
    prepared, index = _prepared(tmp_path, """\
def f(value):
    boolean = left() and right()
    conditional = yes() if condition() else no()
    comparison = first() < second() < third()
    assert checked(), message()
    packed = collect(*items(), **options())
    values = [piece(item) for item in produce()
              for extra in extra_source() if allowed(extra)]
    callback = lambda: deferred()
    return boolean
async def af():
    await wait_for_it()
""")
    scope = _scope(prepared, "f", 1)

    cases = {
        ("right", 2): "BOOLEAN_SHORT_CIRCUIT",
        ("condition", 3): "CONDITIONAL_EXPRESSION",
        ("second", 4): "CHAINED_COMPARISON_SHORT_CIRCUIT",
        ("checked", 5): "ASSERT_ENABLED_BY_OPTIMIZATION_MODE_AND_MAY_RAISE",
        ("message", 5): "ASSERT_MESSAGE_CONDITIONAL",
        ("items", 6): "STARRED_ITERATION_OR_EXPANSION",
        ("collect", 6): "CALL_KEYWORD_UNPACK_MAY_MUTATE_OR_RAISE",
    }
    for (name, line), boundary in cases.items():
        context = _context(index, _ref(prepared, _call(prepared, name, line)), scope)
        assert boundary in context.boundaries
        assert context.execution_proven is False

    deferred = _context(index, _ref(prepared, _call(prepared, "deferred", 9)))
    assert deferred.gap and "LAMBDA_BODY_HAS_NO_RELIABLE_CFG_SUITE" in deferred.gap
    comprehension = _context(index, _ref(prepared, _call(prepared, "piece", 7)))
    assert comprehension.scope is None
    assert comprehension.gap and "COMPREHENSION_FRAME_HAS_NO_RELIABLE_CFG_SCOPE" in comprehension.gap
    extra_iter = _context(index, _ref(prepared, _call(prepared, "extra_source", 8)))
    filter_call = _context(index, _ref(prepared, _call(prepared, "allowed", 8)))
    for context in (extra_iter, filter_call):
        assert context.scope is None
        assert context.gap and "COMPREHENSION_FRAME_OWNER_NOT_UNIQUE" in context.gap
    first_iter = _context(index, _ref(prepared, _call(prepared, "produce", 7)), scope)
    _assert_link(prepared, first_iter, scope)
    assert "COMPREHENSION_FIRST_ITER_OUTER_SCOPE" in first_iter.boundaries
    async_scope = _scope(prepared, "af", 11)
    awaited = _context(index, _ref(prepared, _call(prepared, "wait_for_it", 12)), async_scope)
    assert "AWAIT_SUSPENSION" in awaited.boundaries
    assert awaited.execution_proven is False


def test_source_snapshot_query_and_exact_budget_guards(tmp_path):
    prepared, index = _prepared(tmp_path, """\
def f():
    return call()
""")
    reference = _ref(prepared, _call(prepared, "call", 2))
    with pytest.raises(ValueError, match="indexed source snapshot"):
        index.query(replace(reference, path=str(tmp_path / "other.py")))

    with pytest.raises(ValueError, match="fingerprint"):
        index_source_control_contexts(
            prepared.semantic, prepared.semantics, prepared.control,
            source_path=prepared.path, source_text=prepared.text + "# drift\n")
    for budgets in ({"max_source_bytes": True}, {"max_ast_nodes": False}, {"max_work": 0}):
        with pytest.raises(ValueError, match="positive exact integer"):
            index_source_control_contexts(
                prepared.semantic, prepared.semantics, prepared.control,
                source_path=prepared.path, source_text=prepared.text, **budgets)

    prepared.path.write_text(prepared.text + "# changed on disk\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        index_source_control_contexts(
            prepared.semantic, prepared.semantics, prepared.control,
            source_path=prepared.path)

"""Source-replayed structured CFG candidates; no MOVE authority is asserted."""
from dataclasses import replace

import pytest

from scar.analysis.control_flow_v2 import (
    build_source_control_flow, query_dominance, query_must_execute,
    query_reachability, validate_dominance_query, validate_must_execute_query,
    validate_reachability_query, validate_source_control_flow,
    _graph_validation_work,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.control_flow_v2 import (
    ControlFlowBudget, EdgeKind, InsertionKind, NodeKind, QueryMode, QueryStatus,
    SourceControlFlowGraph, SuiteKind,
)
from scar.ir.frontend_v2 import build_semantic


def _model(tmp_path, text):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    source_semantics = extract_source_semantics(semantic)
    graph = build_source_control_flow(semantic, source_semantics)
    return path, semantic, source_semantics, graph


def _suite(graph, kind, *, scope=None):
    matches = [item for item in graph.suites.values()
               if item.kind is kind and (scope is None or item.scope == scope)]
    assert len(matches) == 1
    return matches[0]


def _statement(graph, suite, line, *, kind=None):
    matches = [item for item in graph.nodes.values()
               if item.suite == suite.id and item.source is not None
               and item.source.start_line == line
               and item.kind not in {NodeKind.INSERTION, NodeKind.SCOPE_ENTRY,
                                     NodeKind.SUITE_ENTRY, NodeKind.NORMAL_EXIT,
                                     NodeKind.EXCEPTION_EXIT}
               and (kind is None or item.kind is kind)]
    assert len(matches) == 1, (line, matches)
    return matches[0]


def test_sequence_source_replay_and_typed_insertions_roundtrip(tmp_path):
    path, semantic, overlay, graph = _model(tmp_path,
        "def f():\n    first = 1\n    second = first + 1\n    return second\n")
    function = _suite(graph, SuiteKind.FUNCTION)
    first, second, returned = (_statement(graph, function, line) for line in (2, 3, 4))
    report = query_reachability(graph, function.id, first.id, second.id)
    assert report.status is QueryStatus.REACHABLE
    dominance = query_dominance(graph, function.id, first.id, second.id)
    assert dominance.status is QueryStatus.CANDIDATE
    assert validate_dominance_query(graph, dominance)["valid"]
    points = [item for item in graph.insertions.values() if item.anchor == second.id]
    assert {item.kind for item in points} == {InsertionKind.BEFORE, InsertionKind.AFTER}
    assert all(item.source.fingerprint == graph.sources[str(path)].fingerprint for item in points)
    assert graph.nodes[function.entry].kind is NodeKind.SCOPE_ENTRY
    assert graph.summary()["status"] == "CONSTRUCTION_ONLY"
    assert validate_source_control_flow(graph, semantic, overlay)["valid"]

    decoded = SourceControlFlowGraph.from_json(graph.to_json())
    assert decoded.to_dict() == graph.to_dict()
    assert validate_reachability_query(decoded, report)["valid"]
    assert not validate_reachability_query(
        decoded, replace(report, status=QueryStatus.NOT_REACHABLE))["valid"]
    assert returned.kind is NodeKind.STATEMENT


def test_if_keeps_both_edges_even_for_literal_true_and_does_not_prove_case_runs(tmp_path):
    _, _, _, graph = _model(tmp_path,
        "def f():\n    if True:\n        chosen = 1\n    after = 2\n    return after\n")
    function = _suite(graph, SuiteKind.FUNCTION)
    branch = _statement(graph, function, 2, kind=NodeKind.BRANCH_TEST)
    true_suite = _suite(graph, SuiteKind.IF_TRUE)
    chosen = _statement(graph, true_suite, 3)
    branch_edges = [item for item in graph.edges.values() if item.source == branch.id]
    assert {item.kind for item in branch_edges} >= {EdgeKind.IF_TRUE, EdgeKind.IF_FALSE}
    assert query_must_execute(graph, function.id, chosen.id,
                              mode=QueryMode.NORMAL).status is QueryStatus.UNKNOWN
    assert any(item.kind.value == "branch_feasibility" for item in graph.gaps)


def test_loop_has_zero_exit_backedge_break_and_continue_routes(tmp_path):
    _, _, _, graph = _model(tmp_path,
        "def f(x):\n    while x:\n        if x > 1:\n            break\n        continue\n    after = 3\n    return after\n")
    function = _suite(graph, SuiteKind.FUNCTION)
    loop = _statement(graph, function, 2, kind=NodeKind.LOOP_TEST)
    body = _suite(graph, SuiteKind.WHILE_BODY)
    loop_edges = [item for item in graph.edges.values() if item.source == loop.id]
    assert {item.kind for item in loop_edges} >= {EdgeKind.LOOP_BODY, EdgeKind.LOOP_ZERO_EXIT}
    assert any(item.kind is EdgeKind.LOOP_BACKEDGE for item in graph.edges.values())
    assert any(item.kind is EdgeKind.BREAK for item in graph.edges.values())
    assert any(item.kind is EdgeKind.CONTINUE for item in graph.edges.values())
    assert graph.nodes[body.entry].kind is NodeKind.SUITE_ENTRY
    assert any(item.kind.value == "loop_feasibility" for item in graph.gaps)


def test_return_does_not_flow_to_following_statement_and_may_raise_is_explicit(tmp_path):
    _, _, _, graph = _model(tmp_path,
        "def f(x):\n    value = x + 1\n    return value\n    unreachable = 9\n")
    function = _suite(graph, SuiteKind.FUNCTION)
    value = _statement(graph, function, 2)
    returned = _statement(graph, function, 3)
    unreachable = _statement(graph, function, 4)
    assert any(edge.kind is EdgeKind.RETURN and edge.source == returned.id
               for edge in graph.edges.values())
    assert any(edge.kind is EdgeKind.MAY_RAISE and edge.source == value.id
               for edge in graph.edges.values())
    assert query_reachability(graph, function.id, returned.id, unreachable.id).status \
        is QueryStatus.NOT_REACHABLE
    normal = query_must_execute(graph, function.id, returned.id, mode=QueryMode.NORMAL)
    all_paths = query_must_execute(graph, function.id, returned.id, mode=QueryMode.ALL_PATHS)
    assert normal.status is QueryStatus.CANDIDATE
    assert all_paths.status is QueryStatus.UNKNOWN
    assert validate_must_execute_query(graph, all_paths)["valid"]


@pytest.mark.parametrize("body,reason", [
    ("try:\n    risky()\nexcept Exception:\n    pass", "try_semantics"),
    ("with manager:\n    value = 1", "with_semantics"),
    ("match x:\n    case 1:\n        value = 1\n    case _:\n        value = 2", "unsupported_control"),
])
def test_unsupported_control_is_a_gap_not_a_fake_linear_body(tmp_path, body, reason):
    text = "def f(x):\n" + "\n".join("    " + line for line in body.splitlines()) \
        + "\n    after = 4\n    return after\n"
    _, _, _, graph = _model(tmp_path, text)
    function = _suite(graph, SuiteKind.FUNCTION)
    unknown = [item for item in graph.edges.values()
               if item.kind is EdgeKind.UNKNOWN_CONTINUATION]
    assert unknown
    assert any(item.kind.value == reason for item in graph.gaps)
    assert graph.suites[function.id].complete is False
    # Case/handler/body assignment rows were intentionally not turned into
    # ordinary parent-suite statement nodes.
    nested_lines = set(range(3, len(body.splitlines()) + 2))
    assert not any(item.source and item.source.start_line in nested_lines
                   and item.suite == function.id for item in graph.nodes.values())


def test_class_methods_and_nested_function_bodies_are_independent_scopes(tmp_path):
    _, semantic, _, graph = _model(tmp_path,
        "class Solver:\n"
        "    def forward(self, x):\n"
        "        while x:\n"
        "            x -= 1\n"
        "        return x\n"
        "def outer():\n"
        "    try:\n"
        "        def nested():\n"
        "            return 3\n"
        "    except Exception:\n"
        "        pass\n")
    methods = [item for item in graph.suites.values()
               if item.kind is SuiteKind.FUNCTION
               and semantic.definitions[item.scope].kind.value == "method"]
    assert len(methods) == 1
    method = methods[0]
    method_scope = semantic.definitions[method.scope]
    assert method_scope.label == "forward"
    assert graph.nodes[method.entry].kind is NodeKind.SCOPE_ENTRY
    method_loop = _statement(graph, method, 3, kind=NodeKind.LOOP_TEST)
    assert method_loop
    # No edge treats class declaration or the opaque class namespace as a call.
    class_suite = next(item for item in graph.suites.values()
                       if item.kind is SuiteKind.OPAQUE
                       and semantic.definitions[item.scope].label == "class Solver")
    assert not any(edge.target == method.entry
                   and graph.nodes[edge.source].suite != method.id
                   for edge in graph.edges.values())
    assert any(item.scope == class_suite.scope and item.kind.value == "class_namespace"
               for item in graph.gaps)
    nested = [item for item in graph.suites.values()
              if item.kind is SuiteKind.FUNCTION
              and semantic.definitions[item.scope].label == "nested"]
    assert len(nested) == 1
    assert graph.nodes[nested[0].entry].kind is NodeKind.SCOPE_ENTRY


def test_user_iteration_and_async_bodies_remain_explicit_gaps(tmp_path):
    _, semantic, _, graph = _model(tmp_path,
        "def iterate(values):\n"
        "    for item in values:\n"
        "        pass\n"
        "async def deferred(values):\n"
        "    async for item in values:\n"
        "        await consume(item)\n")
    assert any(item.kind.value == "user_iteration" for item in graph.gaps)
    assert any(item.kind.value == "async_semantics" for item in graph.gaps)
    async_scope = next(item for item in graph.suites.values()
                       if item.kind is SuiteKind.OPAQUE
                       and semantic.definitions[item.scope].label == "deferred")
    assert graph.nodes[async_scope.entry].kind is NodeKind.SCOPE_ENTRY
    assert not any(item.kind is NodeKind.LOOP_TEST and item.suite == async_scope.id
                   for item in graph.nodes.values())


def test_source_replay_rejects_wrong_source_edge_scope_and_insertion_anchor(tmp_path):
    path, semantic, overlay, graph = _model(tmp_path, "def f():\n    x = 1\n    return x\n")
    assert not validate_source_control_flow(graph, semantic, overlay,
        sources={str(path): "def f():\n    x = 2\n    return x\n"})["valid"]

    changed_edge = next(iter(graph.edges))
    edge = graph.edges[changed_edge]
    graph.edges[changed_edge] = replace(edge, kind=EdgeKind.MAY_RAISE)
    assert not validate_source_control_flow(graph, semantic, overlay)["valid"]
    graph.edges[changed_edge] = edge

    insertion_id = next(iter(graph.insertions))
    insertion = graph.insertions[insertion_id]
    graph.insertions[insertion_id] = replace(
        insertion, node=graph.suites[insertion.suite].normal_exit)
    assert not graph.validate()["valid"]
    graph.insertions[insertion_id] = insertion

    document = graph.to_dict()
    document["graph"]["nodes"].append(document["graph"]["nodes"][0])
    with pytest.raises(ValueError, match="duplicate"):
        SourceControlFlowGraph.from_dict(document)

    suite_id = next(iter(graph.suites))
    suite = graph.suites[suite_id]
    graph.suites[suite_id] = replace(suite, parent=suite.id)
    assert not graph.validate()["valid"]


@pytest.mark.parametrize("budget", [
    ControlFlowBudget(max_source_bytes=8),
    ControlFlowBudget(max_ast_nodes=2),
    ControlFlowBudget(max_nodes=2),
    ControlFlowBudget(max_edges=2),
    ControlFlowBudget(max_build_work=2),
    ControlFlowBudget(max_nesting=1),
])
def test_construction_budgets_fail_closed(tmp_path, budget):
    text = "def f(x):\n    if x:\n        while x:\n            x = x - 1\n    return x\n"
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    overlay = extract_source_semantics(semantic)
    with pytest.raises(ValueError, match="budget|nesting"):
        build_source_control_flow(semantic, overlay, budget=budget)


def test_query_budget_returns_unknown_and_summary_names_limits(tmp_path):
    _, _, _, graph = _model(tmp_path, "def f():\n    x = 1\n    return x\n")
    function = _suite(graph, SuiteKind.FUNCTION)
    first, second = _statement(graph, function, 2), _statement(graph, function, 3)
    result = query_reachability(graph, function.id, first.id, second.id,
                                budget=ControlFlowBudget(max_query_work=1))
    assert result.status is QueryStatus.UNKNOWN
    assert "budget" in result.reason
    summary = graph.summary()
    assert summary["status"] == "CONSTRUCTION_ONLY"
    assert summary["scopes"] >= 2 and summary["edge_kinds"]
    assert summary["unsupported_reasons"]


def test_deep_suite_parent_checks_are_charged_once_to_query_budget(tmp_path):
    lines = ["def f(x):", "    while x:"]
    indent = "        "
    for _ in range(40):
        lines.append(indent + "if x:")
        indent += "    "
    lines.append(indent + "break")
    lines.extend(("    return x", ""))
    _, _, _, graph = _model(tmp_path, "\n".join(lines))
    function = _suite(graph, SuiteKind.FUNCTION)
    loop = _statement(graph, function, 2, kind=NodeKind.LOOP_TEST)
    deepest_break = next(item for item in graph.nodes.values()
                         if item.label == "Break")
    validation_work = _graph_validation_work(graph)
    result = query_reachability(graph, function.id, loop.id, deepest_break.id,
        budget=ControlFlowBudget(max_query_work=validation_work - 1))
    assert result.status is QueryStatus.UNKNOWN
    assert result.reason == "query work budget exceeded during graph validation"

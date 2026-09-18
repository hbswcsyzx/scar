from scar.analysis import dead_expression_candidates
from scar.backends import eliminate_dead_expressions
from scar.ir import from_source


def test_static_graph_finds_discarded_call_but_rejects_without_contract(tmp_path):
    source = tmp_path / "dead.py"
    source.write_text("def work(x):\n    return x * 2\n\nwork(1)\ny = work(2)\n")
    graph = from_source(source)
    found = dead_expression_candidates(graph)
    assert len(found) == 1
    assert found[0].kind == "DeadExpressionCandidate"
    assert found[0].decision == "rejected"
    assert found[0].backend == "dead_expression_elimination"


def test_source_backend_requires_closed_world_and_reviewed_purity(tmp_path):
    source = "def work(x):\n    return x * 2\n\nwork(1)\ny = work(2)\n"
    no_scope = eliminate_dead_expressions(source, {4}, pure_lines={4})
    assert not no_scope.changed and "closed-world" in no_scope.reason
    no_contract = eliminate_dead_expressions(source, {4}, closed_world=True)
    assert not no_contract.changed and "reviewed pure" in no_contract.reason

    changed = eliminate_dead_expressions(source, {4}, closed_world=True, pure_lines={4})
    assert changed.changed and changed.removed_lines == [4]
    assert "work(1)" not in changed.source
    assert "y = work(2)" in changed.source


def test_source_backend_does_not_remove_assigned_call(tmp_path):
    source = "y = work(2)\n"
    changed = eliminate_dead_expressions(source, {1}, closed_world=True, pure_lines={1})
    assert not changed.changed

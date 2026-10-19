"""Finite budgets and caller contexts cannot manufacture copy consumers."""
from copy import deepcopy

from scar.ir.program.model import TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import call_return_program
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


QUERY_BUDGET = 100000


def _index(graph):
    require_valid(graph)
    return ProgramIndex(graph)


def _id(operation):
    return getattr(operation, "id", operation)


def _codes(gaps):
    return {gap if type(gap) is str else gap.get("code") if type(gap) is dict
            else getattr(gap, "code", None) for gap in gaps}


def _root(report):
    root, = tuple(frame for frame in report["frames"] if frame["key"] == ())
    return root


def _no_authority(report):
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_budget_one_preserves_root_and_original_call_boundaries_without_prefix_totals():
    graph, details = call_return_program(depth=2)
    root_region = next(region for region in graph.regions if region.id == graph.root)
    original = {identity for block in root_region.blocks for identity in block.operations
                if next(operation for operation in graph.operations if operation.id == identity).callee is not None}
    assert original
    report = _index(graph).copy_consumers(details["expected"], budget=1)

    root = _root(report)
    assert root["region"] == graph.root
    assert {_id(call["operation"]) for call in root["calls"]} == original
    assert all(call["status"] != "NOT_APPLICABLE" for call in root["calls"])
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["inventory"]["proofs_complete"] is False
    assert report["inventory"]["frames_total"] is None
    assert report["inventory"]["consumers_total"] is None
    assert report["inventory"]["cursor"] is not None
    assert report["cursor"] is not None
    assert report["budget"]["limit"] == 1
    assert report["budget"]["used"] <= 1
    assert report["budget"]["truncated"] is True
    _no_authority(report)


def test_late_budget_exhaustion_keeps_inventory_and_proof_completion_distinct():
    graph, details = call_return_program(depth=2, calls="chain")
    index = _index(graph)
    complete = index.copy_consumers(details["expected"], budget=QUERY_BUDGET)
    assert complete["budget"]["truncated"] is False
    assert complete["inventory"]["known_inventory_complete"] is True
    assert complete["inventory"]["proofs_complete"] is True
    limit = complete["budget"]["used"] - 1
    assert limit > 1

    report = index.copy_consumers(details["expected"], budget=limit)

    _root(report)
    assert report["budget"]["used"] <= limit
    assert report["budget"]["truncated"] is True
    assert report["inventory"]["proofs_complete"] is False
    assert report["cursor"] is not None
    assert report["status"] not in ("DECLARED", "CONTRADICTED")
    if report["inventory"]["known_inventory_complete"]:
        assert report["inventory"]["frames_total"] == len(report["frames"])
        assert report["inventory"]["consumers_total"] == sum(
            len(frame["consumers"]) for frame in report["frames"])
    else:
        assert report["inventory"]["frames_total"] is None
        assert report["inventory"]["consumers_total"] is None
    _no_authority(report)


def test_nested_frame_input_and_consumer_reports_are_detached_between_queries():
    graph, details = call_return_program(depth=2)
    index = _index(graph)
    first = index.copy_consumers(details["expected"], budget=QUERY_BUDGET)
    original = deepcopy(first)
    child = next(frame for frame in first["frames"] if frame["key"] and frame["inputs"])
    assert child["consumers"]
    child["inputs"][0]["binding"]["match"] = "detached-only mutation"
    child["consumers"][0]["gaps"] = ("detached-only mutation",)
    assert first != original

    again = index.copy_consumers(details["expected"], budget=QUERY_BUDGET)

    assert again == original
    assert index.graph == graph


def test_internal_root_source_retains_all_original_callers_as_unresolved_boundaries():
    graph, details = call_return_program(calls="siblings", internal=True)
    source, = details["helper_sources"]
    report = _index(graph).copy_consumers(source, budget=QUERY_BUDGET)

    root = _root(report)
    assert root["inputs"] == ()
    assert root["region"] != graph.root
    assert len(details["root_calls"]) == 2
    boundaries = tuple(boundary for boundary in root["boundaries"]
                       if boundary["kind"] == "ROOT_CALLER_CONTEXT")
    assert {boundary["operation"] for boundary in boundaries} == set(details["root_calls"])
    assert all(boundary["callee"] == root["region"] for boundary in boundaries)
    assert all(boundary["status"] == "PARTIAL" for boundary in boundaries)
    assert all("copy_consumer_root_caller_context_unresolved" in boundary["gaps"]
               for boundary in boundaries)
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["inventory"]["frames_total"] is None
    assert report["inventory"]["consumers_total"] is None
    assert all(frame["key"] == () for frame in report["frames"])
    _no_authority(report)


def test_unscoped_shared_callee_guard_does_not_supply_the_other_callers_entry():
    graph, details = call_return_state_program(two_callers=True)
    index = _index(graph)
    helper = details["callee"]
    entry = next(block for block in helper.blocks if block.id == helper.entry)
    branch = next(operation for operation in graph.operations
                  if operation.id == entry.operations[-1])
    assert branch.terminator.kind is TerminatorKind.BRANCH
    a, b = (details["callers"][label] for label in ("a", "b"))
    assert a["operation"].callee == b["operation"].callee == helper.id
    guard = ControlEdgeReference(branch.id, 0)

    report = index.copy_consumers(a["arguments"][0], guard=guard, budget=QUERY_BUDGET)

    assert "copy_consumer_guard_context_unresolved" in _codes(report["gaps"])
    assert report["inventory"]["proofs_complete"] is False
    other = tuple(frame for frame in report["frames"] if frame["key"] == (b["operation"].id,))
    for frame in other:
        assert details["callee_arguments"][0].id not in frame["must_seeds"]
        assert all(item["must"] is not True for item in frame["inputs"] if item["ordinal"] == 0)
    _no_authority(report)

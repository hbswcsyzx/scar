"""Execution8 joins for the original final-extractor child regions."""
import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_final_region_graphs import await_final_region_execution


QUERY_BUDGET = 1_048_576


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _report(program, model, details):
    return _index(program, model).await_body_links(
        details["static"]["acquisition_scope"], budget=QUERY_BUDGET)


def _implementation(report, details, example):
    rows = tuple(row for row in report["outcomes"]
        if row["definition"]["drive_outcome"] == details["drive_outcome"]
        and row["definition"]["advance_operation"] ==
            details["static"]["drivers"][-1]["caller_call"].id)
    assert len(rows) == 1
    occurrences = tuple(row for row in rows[0]["occurrences"]
        if row["advance"].id == example["advance"]
        and row["drive"].id == example["body_drives"][-1].drive)
    assert len(occurrences) == 1
    consumers = tuple(row for row in occurrences[0]["consumers"]
        if row["definition"]["actual"] == details["static"]["extract_input"]
        and row["definition"]["requires_final_extraction"] is True)
    assert len(consumers) == 1
    return consumers[0]["implementation"]


def _call_id(call):
    return call["association"].id if isinstance(call, dict) else call.id


def _declared_paths(implementation):
    return tuple(path for stage in implementation["stages"]
        for leg in stage["legs"] for result in leg["results"]
        for path in result["paths"] if path["status"] == "DECLARED")


@pytest.mark.parametrize(
    ("depth", "child_raised"),
    ((1, False), (2, True)),
    ids=("normal-child", "nested-raise-child"),
)
def test_child_completion_returns_through_each_exact_call_frame_to_two_parent_consumers(
        depth, child_raised):
    program, model, details = await_final_region_execution(
        depth=depth, instances=2, child_raised=child_raised)
    report = _report(program, model, details)
    kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL

    for example in details["implementation_instances"]:
        implementation = _implementation(report, details, example)
        expected_calls = (example["implementation_root_call"],
                          *example["implementation_nested_calls"])
        expected_terminals = tuple(
            frame["operations"][frame["definition"]["terminals"][kind].id]
            for frame in example["implementation_frames"])
        assert len(implementation["frames"]) == depth
        assert len(implementation["stages"]) == depth
        assert tuple(_call_id(frame["call"]) for frame in implementation["frames"]) == tuple(
            call.id for call in expected_calls)
        assert tuple(frame["completion"].id for frame in implementation["frames"]) == expected_terminals
        assert tuple(stage["occurrence"].operation for stage in implementation["stages"]) == tuple(
            row["definition"]["operation"].id for row in example["implementation_frames"])
        paths = _declared_paths(implementation)
        assert paths
        assert any({_call_id(hop["call"]) for hop in path["hops"]} == {
            call.id for call in expected_calls}
            and len(path["hops"]) == depth
            and all(hop["binding"]["match"] is True for hop in path["hops"])
            for path in paths)
        assert implementation["source_runtime_verified"] is False
        assert implementation["runtime_identity_verified"] is False
        assert implementation["value_identity_verified"] is False
        assert implementation["transformation_authorized"] is False

    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["value_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_missing_nested_child_call_keeps_its_frame_and_does_not_borrow_sibling_instance():
    program, model, details = await_final_region_execution(
        depth=2, instances=2, missing_child_call=(0, 0))
    report = _report(program, model, details)
    missing, sibling = details["implementation_instances"]

    partial = _implementation(report, details, missing)
    assert len(partial["frames"]) == 2
    assert partial["frames"][0]["call"] is not None
    assert partial["frames"][1]["call"] is None
    assert partial["status"] == "PARTIAL"
    assert partial["gaps"]

    complete = _implementation(report, details, sibling)
    assert len(complete["frames"]) == 2
    assert all(frame["call"] is not None for frame in complete["frames"])
    assert _declared_paths(complete)


def test_missing_child_terminal_use_keeps_sibling_and_original_child_result_slot():
    program, model, details = await_final_region_execution(
        depth=2, instances=2, child_raised=True, missing_child_use=(0, 1))
    report = _report(program, model, details)
    missing, sibling = details["implementation_instances"]

    partial = _implementation(report, details, missing)
    assert partial["status"] == "PARTIAL"
    assert partial["gaps"]
    assert partial["frames"][-1]["completion"] is not None
    assert _declared_paths(_implementation(report, details, sibling))


def test_missing_outer_return_capture_keeps_the_child_and_sibling_rows():
    program, model, details = await_final_region_execution(
        depth=1, instances=2, missing_return=0)
    missing_example, sibling = details["implementation_instances"]
    expected_call = missing_example["implementation_root_call"]
    assert type(expected_call.completion) is Unresolved
    report = _report(program, model, details)

    partial = _implementation(report, details, missing_example)
    assert len(partial["frames"]) == 1
    assert partial["frames"][0]["call"] is None or partial["frames"][0]["completion"] is None
    assert partial["status"] == "PARTIAL"
    assert partial["gaps"]
    assert _declared_paths(_implementation(report, details, sibling))


def test_wrong_child_raise_packet_is_a_failed_candidate_not_an_authorized_override():
    program, model, details = await_final_region_execution(
        depth=1, instances=1, child_raised=True, wrong_child_exit=True)
    report = _report(program, model, details)
    example, = details["implementation_instances"]
    implementation = _implementation(report, details, example)
    paths = tuple(path for stage in implementation["stages"]
        for leg in stage["legs"] if leg["definition"]["kind"] is ExitKind.RAISE
        for result in leg["results"] for path in result["paths"])
    assert paths
    assert any(path["binding"]["match"] is False for path in paths)
    assert implementation["status"] == "PARTIAL"
    assert implementation["source_runtime_verified"] is False


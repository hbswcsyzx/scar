"""Actual P segments retain their own completed H result and final Use."""
import pytest

from scar.ir.execution.coordinates import ControlTransfer, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_parent_post_cleanup_graphs import await_parent_post_cleanup_execution


_FLAGS = ("source_runtime_verified", "runtime_identity_verified",
          "value_identity_verified", "transformation_authorized")


def _index(program, model):
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program)


def _query(index, example, *, cross_resume=True):
    assert example["source_value"] is not None
    return index.completion_continuations(example["source_value"], example["anchor"],
                                         cross_resume=cross_resume, budget=1_048_576)


def _parent_receipts(report, details):
    return tuple(row for row in report["terminals"]
        if row["terminal"] == HostTerminal(details["static"]["parent_return"].id))


def _assert_parent_final(report, model, details, example):
    receipts = _parent_receipts(report, details)
    assert receipts
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    owned = details["static"]["parent_pending"]["actual"]
    expected_use = uses[(example["parent_final"], owned.use)]
    for receipt in receipts:
        assert receipt["actual"] == owned
        assert receipt["operation"].id == example["parent_final"]
        assert receipt["use"] == expected_use
        assert receipt["value"] == values[expected_use.value]
        assert receipt["binding"]["match"] is True
        assert receipt["root_binding"]["match"] is True
        assert receipt["root_preserved"] is True
        assert receipt["crossed_suspend"] is True
    assert tuple(segment.id for segment in report["segments"]) == example["parent_segments"]
    assert all(segment.activation == example["parent_activation"] for segment in report["segments"])
    for ordinal in (1, 2):
        expected = ControlTransfer(example["parent_drives"][ordinal - 1].outcome, 0,
                                   example["parent_entries"][ordinal])
        assert expected in report["transfers"]
    assert all(report[name] is False for name in _FLAGS)


@pytest.mark.parametrize(("depth", "helper_zero_cut"), ((1, True), (2, False)),
                         ids=("E-zero-B", "EG-two-cut-B"))
def test_two_parent_instances_keep_completed_h_call_separate_from_parent_future_resumes(
        depth, helper_zero_cut):
    program, model, details = await_parent_post_cleanup_execution(
        depth=depth, helper_zero_cut=helper_zero_cut, instances=2)
    index = _index(program, model)
    assert len({example["parent_activation"] for example in details["instances"]}) == 2
    segments = {segment.id: segment for segment in model.segments}
    for example in details["instances"]:
        assert len(example["parent_segments"]) == len(example["parent_drives"]) == 3
        assert example["helper_call"].caller == example["anchor"]
        assert example["helper_call"].activation == example["helper"]["caller_activation"]
        assert example["helper_call"].completion == example["helper"]["final"]
        assert example["anchor"] in example["parent_operations"][0].values()
        assert all(details["static"]["parent_helper_call"].id not in mapped
                   for mapped in example["parent_operations"][1:])
        assert {drive.activation for drive in example["parent_drives"]} == {example["parent_activation"]}
        for ordinal in (1, 2):
            ingress = segments[example["parent_segments"][ordinal]].ingress
            assert type(ingress) is ResumeIngress
            assert ingress.suspension == example["parent_drives"][ordinal - 1].outcome
        stopped = _query(index, example, cross_resume=False)
        assert _parent_receipts(stopped, details) == ()
        assert any(row["kind"] == "SUSPENSION" for row in stopped["boundaries"])
        assert tuple(segment.id for segment in stopped["segments"]) == example["parent_segments"][:1]
        _assert_parent_final(_query(index, example), model, details, example)


@pytest.mark.parametrize("missing", ("resume", "terminal-use", "H-association"))
def test_missing_parent_capture_cannot_borrow_the_other_instance_continuation(missing):
    switches = {"missing_resume": 0} if missing == "resume" else (
        {"missing_terminal_use": 0} if missing == "terminal-use" else {"missing_helper_call": 0})
    program, model, details = await_parent_post_cleanup_execution(depth=2, instances=2, **switches)
    index = _index(program, model)
    absent, sibling = details["instances"]
    partial = _query(index, absent)
    assert partial["gaps"]
    receipts = _parent_receipts(partial, details)
    assert all(row["root_binding"]["match"] is not True
               or row["binding"]["match"] is not True for row in receipts)
    assert all(row.get("operation") is None or row["operation"].id != sibling["parent_final"]
               for row in partial["terminals"])
    assert all(segment.activation == absent["parent_activation"] for segment in partial["segments"])
    _assert_parent_final(_query(index, sibling), model, details, sibling)


def test_actual_h_raise_does_not_fabricate_a_normal_f_source_or_parent_future_segments():
    program, model, details = await_parent_post_cleanup_execution(depth=2, instances=1, helper_raised=True)
    _index(program, model)
    example, = details["instances"]
    assert example["source_value"] is None
    frame = example["helper"]["implementation_frames"][-1]
    assert not any(value.value == example["source_definition"] and value.origin in frame["visits"]
                   for value in model.values)
    assert len(example["parent_segments"]) == len(example["parent_drives"]) == 1
    final = details["static"]["parent_failure"]
    assert example["parent_final"] == example["parent_operations"][0][final.id]
    assert example["pending_constructor"] is None
    assert example["helper"]["implementation_kind"] is ExitKind.RAISE
    assert {edge.kind for edge in details["static"]["parent_helper_call"].terminator.successors} == {
        ExitKind.NORMAL, ExitKind.RAISE}

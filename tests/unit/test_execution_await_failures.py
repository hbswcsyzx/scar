"""Captured general-await failures stop before advance and body execution."""

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_failure_graphs import await_failure_execution


def test_lookup_raise_is_a_real_get_helper_call_without_later_body_execution():
    _assert_failure_capture("lookup_raise")


def test_method_call_raise_is_a_real_get_helper_call_without_later_body_execution():
    _assert_failure_capture("method_call_raise")


def test_qualification_type_error_is_captured_without_a_body_drive():
    _assert_failure_capture("qualification_reject")


def _assert_failure_capture(stage):
    program, model, details = await_failure_execution(stage)
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues

    assert model.call_activations == (details["call_activation"],)
    assert details["call_activation"].caller == details["parent_operations"][details["get"].id]
    assert details["call_activation"].completion == details["helper_operations"][
        details["failure_terminal"].id]
    captured_operations = {row.operation for row in model.operations}
    assert details["drive"].operation not in captured_operations
    assert model.body_drive_executions == ()
    assert model.body_activation_origins == ()

    index = ExecutionIndex(model, program)
    view = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert view["source_runtime_verified"] is False
    assert view["runtime_identity_verified"] is False
    assert view["transformation_authorized"] is False
    assert not any(route["drive"] is not None
                   for job in view["jobs"] for occurrence in job["occurrences"]
                   for route in occurrence["routes"])

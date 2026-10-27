"""One real GET helper activation connected to the later persistent body drive."""

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_general_graphs import await_general_execution


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def test_general_await_occurrence_joins_parent_helper_driver_and_create_origin():
    program, model, details = await_general_execution()
    index = _index(program, model)

    report = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == 2
    normal = next(job for job in report["jobs"]
                  if job["advance"].operation == details["call_rows"][0].operation
                  and job["advance"].slot == details["call_rows"][0].slot)
    occurrence, = normal["occurrences"]
    assert occurrence["advance_selected"] is True
    assert occurrence["matched_sources"]
    route, = occurrence["routes"]
    assert route["call_chain"]
    assert route["drive"]["association"] == details["body_execution"]
    assert route["drive"]["activation"].id == details["body_activation"]
    assert route["drive"]["instance"]["creation_handle"] is not None
    assert details["body_origin"].creation == details["helper_operations"][
        details["helper_create_operation"].id]
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["value_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_general_await_missing_link_keeps_the_actual_helper_and_drive_capture():
    program, model, details = await_general_execution(attach_link=False)
    index = _index(program, model)

    report = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == 2
    assert all(job["links"] == () for job in report["jobs"])
    assert all(job["occurrences"] for job in report["jobs"])
    assert any(any(getattr(gap, "code", None) == "await_body_link_missing"
                   for gap in occurrence["gaps"])
               for job in report["jobs"] for occurrence in job["occurrences"])
    assert model.call_activations == (details["acquisition_call"], details["driver_call"])
    assert model.body_drive_executions == (details["body_execution"],)

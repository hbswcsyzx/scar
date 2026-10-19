"""Join the self-await ports to one finite P3 capture, without authority flags."""
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_pipeline_graphs import await_self_pipeline_execution


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def test_self_await_occurrence_route_uses_exact_call_drive_and_create_origin():
    program, model, details = await_self_pipeline_execution()
    index = _index(program, model)

    report = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == 2
    jobs = {job["advance"].slot: job for job in report["jobs"]}
    assert set(jobs) == {0, 1}

    normal = jobs[0]
    occurrence, = normal["occurrences"]
    assert occurrence["advance"].id == details["factory_operations"][details["call"].id]
    assert occurrence["advance_selected"] is True
    assert occurrence["iterator_use"] is not None
    assert occurrence["matched_sources"]
    route, = occurrence["routes"]
    assert route["drive_occurrence"].id == details["drive_occurrence"]
    assert route["call_chain"]
    assert route["call_chain"][0]["association"] == details["call_activation"]
    drive = route["drive"]
    assert drive["association"] == details["body_drive_execution"]
    assert drive["drive"].id == details["drive_occurrence"]
    assert drive["instance"]["creation_handle"] is not None
    assert drive["activation"].id == details["body_activation"]
    assert all(report[key] is False for key in (
        "source_runtime_verified", "runtime_identity_verified",
        "value_identity_verified", "transformation_authorized"))


def test_missing_await_body_link_keeps_source_and_actual_p3_routes_in_inventory():
    program, model, details = await_self_pipeline_execution(attach_link=False)
    assert not any(type(row) is AwaitBodyLink for row in program.protocol_bindings)
    index = _index(program, model)

    report = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == 2
    assert all(job["links"] == () for job in report["jobs"])
    assert any("await_body_link_missing" in job["gaps"] for job in report["jobs"])
    assert all(job["occurrences"] for job in report["jobs"])
    assert model.call_activations == (details["call_activation"],)
    assert model.body_drive_executions == (details["body_drive_execution"],)
    assert report["status"] == "PARTIAL"


def test_tiny_budget_retains_await_source_inventory_and_cursor():
    program, model, details = await_self_pipeline_execution()
    report = _index(program, model).await_body_links(
        details["acquisition_scope"], budget=1)

    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] >= 1
    assert report["budget"]["limit"] == 1
    assert report["budget"]["used"] <= 1
    assert report["budget"]["truncated"] is True
    assert report["cursor"] is not None
    assert report["status"] == "PARTIAL"
    assert report["source_runtime_verified"] is False

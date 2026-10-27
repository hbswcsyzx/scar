"""Actual declared W/getter/B ports, without native identity authority."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import validate
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_wrapper_graphs import await_wrapper_execution


def _index(program, model, details):
    require_valid(program)
    validation = validate(model, program, evidence_graphs=details["evidence_graphs"])
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program, evidence_graphs=details["evidence_graphs"])


def _normal(report):
    job = next(job for job in report["jobs"] if job["advance"].slot == 0)
    occurrence, = job["occurrences"]
    route, = occurrence["routes"]
    return occurrence, route


def _codes(report):
    return {getattr(gap, "code", gap) for gap in report["gaps"]}


def test_explicit_native_wrapper_routes_distinct_w_to_held_b_without_copy_union():
    program, model, details = await_wrapper_execution()
    report = _index(program, model, details).await_body_links(
        details["construction_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == 2
    assert report["issues"] == ()
    occurrence, route = _normal(report)
    assert occurrence["matched_sources"]
    assert tuple(row["association"] for row in route["call_chain"]) == details["calls"]
    assert route["drive_occurrence"].id == details["drive_occurrence"]
    projection, = route["projections"]
    assert projection["constructor"].id == details["factory_operations"][details["constructor"].id]
    bindings = {binding["role"]: binding for binding in projection["bindings"]}
    assert set(bindings) == {
        "wrapper_input", "getter_to_drive", "native_held_body", "held_body_origin"}
    for role in ("wrapper_input", "getter_to_drive"):
        assert bindings[role]["original_copy"] is True
    for role in ("native_held_body", "held_body_origin"):
        assert bindings[role]["original_copy"] is None
        assert bindings[role]["conditional_native_projection"] is True
        assert bindings[role]["compatibility"]["status"] == "DECLARED_SAME_OBJECT"
    assert details["wrapper_object"] != details["body_object"]
    assert projection["distinctness"]["status"] == "DECLARED_DISTINCT_OBJECTS"
    assert all(report[key] is False for key in (
        "source_runtime_verified", "runtime_identity_verified",
        "value_identity_verified", "transformation_authorized"))


def test_native_wrapper_cannot_declare_w_and_b_the_same_scoped_object():
    program, model, details = await_wrapper_execution(same_object=True)
    index = _index(program, model, details)
    report = index.await_body_links(details["construction_scope"], budget=65536)
    assert details["wrapper_object"] == details["body_object"]
    assert report["status"] == "CONTRADICTED"
    assert "body_reference_distinct_conflict" in {issue.code for issue in report["issues"]}
    assert report["runtime_identity_verified"] is False


def test_another_true_create_of_the_same_body_cannot_replace_wrappers_expected_b():
    program, model, details = await_wrapper_execution(other_body=True)
    index = _index(program, model, details)
    assert details["create"].body == details["second_create"].body
    assert details["create"].operation != details["second_create"].operation
    assert details["actual_body_object"] != details["body_object"]
    report = index.await_body_links(details["construction_scope"], budget=65536)
    assert report["status"] == "CONTRADICTED"
    assert "await_wrapper_body_source" in {issue.code for issue in report["issues"]}
    _, route = _normal(report)
    projection, = route["projections"]
    by_role = {binding["role"]: binding for binding in projection["bindings"]}
    assert by_role["getter_to_drive"]["original_copy"] is True
    assert by_role["native_held_body"]["compatibility"]["status"] == "CONFLICT"
    origin = index.body_activation_origin(details["body_activation"], budget=65536)
    assert origin["creation"].operation == details["second_create"].operation


def test_missing_inner_call_never_guesses_the_only_visible_driver_activation():
    program, model, details = await_wrapper_execution()
    changed = replace(model, call_activations=model.call_activations[:1])
    report = _index(program, changed, details).await_body_links(
        details["construction_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1 and report["job_count"] == 2
    normal = next(job for job in report["jobs"] if job["advance"].slot == 0)
    occurrence, = normal["occurrences"]
    assert occurrence["routes"] == ()
    assert "await_drive_call_chain_missing" in _codes(report)
    assert report["status"] == "PARTIAL"


@pytest.mark.parametrize("missing", ("drive", "origin", "link"))
def test_missing_association_retains_original_constructor_and_drive_obligations(missing):
    program, model, details = await_wrapper_execution(attach_link=missing != "link")
    if missing == "drive":
        model = replace(model, body_drive_executions=())
    elif missing == "origin":
        model = replace(model, body_activation_origins=())
    report = _index(program, model, details).await_body_links(
        details["construction_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1 and report["job_count"] == 2
    occurrence, route = _normal(report)
    assert occurrence["matched_sources"]
    assert route["drive_occurrence"].id == details["drive_occurrence"]
    assert report["status"] == "PARTIAL"
    if missing == "link":
        assert all(job["links"] == () for job in report["jobs"])
        assert "await_body_link_missing" in _codes(report)
    elif missing == "drive":
        assert route["drive"]["association"] is None
    else:
        assert route["drive"]["instance"]["creation_handle"] is None


def test_uncaptured_getter_preserves_source_and_never_invents_a_native_b_read():
    program, model, details = await_wrapper_execution()
    read = details["wrapper_operations"][details["read"].id]
    absent = {value.id for value in model.values if value.origin == read}
    unknown = Unresolved("native held-body getter not captured", model.activations[0].entry)
    changed = replace(model,
        operations=tuple(row for row in model.operations if row.id != read),
        values=tuple(row for row in model.values if row.id not in absent),
        uses=tuple(replace(row, value=unknown) if row.value in absent else row
                   for row in model.uses if row.operation != read),
        denotations=tuple(row for row in model.denotations if row.value not in absent))
    report = _index(program, changed, details).await_body_links(
        details["construction_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1 and report["job_count"] == 2
    assert "await_wrapper_read_occurrence_unproved" in _codes(report)
    _, route = _normal(report)
    projection, = route["projections"]
    assert projection["reads"] == () and projection["bindings"] == ()
    assert report["status"] == "PARTIAL"


def test_missing_constructor_capture_does_not_select_w_by_object_identity_alone():
    program, model, details = await_wrapper_execution()
    constructor = details["factory_operations"][details["constructor"].id]
    changed = replace(model,
        operations=tuple(row for row in model.operations if row.id != constructor),
        uses=tuple(row for row in model.uses if row.operation != constructor),
        transfers=tuple(row for row in model.transfers if row.operation != constructor))
    report = _index(program, changed, details).await_body_links(
        details["construction_scope"], budget=65536)
    assert report["inventory"]["source_count"] == 1 and report["job_count"] == 2
    job = next(job for job in report["jobs"] if job["advance"].slot == 0)
    assert job["source_occurrence_count"] == 0
    assert all(row["matched_sources"] == () for row in job["occurrences"])
    assert "await_source_occurrence_unproved" in _codes(report)
    assert report["status"] == "PARTIAL"


@pytest.mark.parametrize("scope", ("missing", "cross_artifact"))
def test_wrapper_distinctness_is_unproved_without_one_complete_object_scope(scope):
    program, model, details = await_wrapper_execution()
    wrappers = {value for value, name in details["object_assignments"].items() if name == "wrapper"}
    if scope == "missing":
        model = replace(model, denotations=tuple(row for row in model.denotations
                                               if row.value not in wrappers))
    else:
        graph = EvidenceGraph()
        graph.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID("wrapper")))
        artifact = external_artifact(graph, "memory:another-wrapper-object-scope")
        model = replace(model, denotations=tuple(replace(row,
            identity=ObjectIdentity(ObjectRef(artifact, ObjectID("wrapper"))))
            if row.value in wrappers else row for row in model.denotations))
        details = {**details, "evidence_graphs": {**details["evidence_graphs"], artifact.sha256: graph}}
    report = _index(program, model, details).await_body_links(
        details["construction_scope"], budget=65536)
    _, route = _normal(report)
    projection, = route["projections"]
    assert projection["distinctness"]["status"] == "UNPROVED"
    assert report["issues"] == () and report["status"] == "PARTIAL"
    assert ("body_reference_distinct_identity_unproved" if scope == "missing"
            else "body_reference_distinct_scope_unproved") in _codes(report)
    assert report["runtime_identity_verified"] is False


def test_wrapper_tiny_budget_keeps_inventory_masks_unchecked_projections_and_has_cursor():
    program, model, details = await_wrapper_execution()
    report = _index(program, model, details).await_body_links(details["construction_scope"], budget=1)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] >= 1
    assert report["budget"]["used"] <= 1 and report["budget"]["truncated"] is True
    assert report["cursor"] is not None and report["status"] == "PARTIAL"
    for job in report["jobs"]:
        for occurrence in job["occurrences"]:
            assert occurrence["matched_sources"] == () and occurrence["bindings"] == ()
    assert report["transformation_authorized"] is False


def test_wrapper_query_detaches_returns_and_rechecks_a_changed_external_identity_catalog():
    program, model, details = await_wrapper_execution()
    index = _index(program, model, details)
    report = index.await_body_links(details["construction_scope"], budget=65536)
    _, route = _normal(report)
    projection, = route["projections"]
    projection["bindings"] = ()
    again = index.await_body_links(details["construction_scope"], budget=65536)
    _, route = _normal(again)
    assert len(route["projections"][0]["bindings"]) == 4
    graph, = details["evidence_graphs"].values()
    graph.add_control_event("catalog changed after index construction")
    with pytest.raises(ValueError, match="snapshot|artifact|external"):
        index.await_body_links(details["construction_scope"], budget=65536)
    assert index.report.valid
    assert route["projections"][0]["distinctness"]["status"] == "DECLARED_DISTINCT_OBJECTS"

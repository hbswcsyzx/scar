"""Strict parser tests for the bounded endpoint byte profile."""
from hashlib import sha256
from dataclasses import replace

import pytest

from scar.ir.execution.endpoint_protocol import (
    PROFILE_MAX_BYTES, PROFILE_NAME, PROFILE_SCHEMA, resolve_endpoint_profile,
)
from scar.ir.execution.snapshot import ExternalSnapshots
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from tests.fixtures.execution_endpoint_protocol import parser_context, profile_bytes


@pytest.mark.parametrize("length", [True, "8", -1, 0])
def test_invalid_length_is_not_masked_by_unsupported_nonzero_offset(length):
    payload = profile_bytes("READ", offset=1, length=length)
    ctx, reference = parser_context(payload, name=f"offset-invalid-{type(length).__name__}-{length!r}")

    assert resolve_endpoint_profile(ctx, reference, "profile") is None
    assert [code for code, _, _ in ctx.issues] == ["endpoint_profile_invalid"]
    assert not any(code == "endpoint_profile_offset_unsupported" for code, _, _ in ctx.gaps)


def test_valid_nonzero_offset_is_retained_as_an_unsupported_profile_gap():
    payload = profile_bytes("READ", offset=1, length=8)
    ctx, reference = parser_context(payload, name="offset-valid")

    assert resolve_endpoint_profile(ctx, reference, "profile") is None
    assert not ctx.issues
    assert [code for code, _, _ in ctx.gaps] == ["endpoint_profile_offset_unsupported"]


def test_oversized_declared_profile_is_rejected_before_payload_lookup(monkeypatch):
    payload = profile_bytes("READ", length=8)
    ctx, reference = parser_context(payload, declared_size=PROFILE_MAX_BYTES + 1,
                                   name="oversized-declaration")
    calls = []

    def forbidden_payload_lookup(artifact):
        calls.append(artifact)
        raise AssertionError("oversized profile must be rejected before payload lookup")

    monkeypatch.setattr(ctx.snapshots, "payload", forbidden_payload_lookup)
    assert resolve_endpoint_profile(ctx, reference, "profile") is None
    assert not calls
    assert [code for code, _, _ in ctx.issues] == ["endpoint_profile_size"]
    assert not ctx.gaps


def test_valid_profile_keeps_the_independent_operation_and_range():
    payload = profile_bytes("WRITE_ACTUAL", length=4)
    ctx, reference = parser_context(payload, name="valid")

    resolved = resolve_endpoint_profile(ctx, reference, "profile")

    assert resolved is not None
    assert resolved["schema"] == PROFILE_SCHEMA
    assert resolved["profile"] == PROFILE_NAME
    assert resolved["operation"] == "WRITE_ACTUAL"
    assert resolved["offset_bytes"] == 0
    assert resolved["length_bytes"] == 4
    assert resolved["reference"] is reference
    assert not ctx.issues and not ctx.gaps


@pytest.mark.parametrize("payload", [
    b'{"schema":"x","schema":"y"}',
    b'{"schema":"x","schema_version":NaN}',
    b'{"schema":"x","schema_version":1,"extra":true}',
])
def test_profile_json_rejects_duplicate_nonfinite_and_extra_fields(payload):
    reference = ProviderFactReference(
        ProviderArtifact("memory:endpoint-profile:malformed", sha256(payload).hexdigest(),
                         len(payload), PROFILE_SCHEMA), "#")
    ctx, _ = parser_context(payload, name="malformed")

    assert resolve_endpoint_profile(ctx, reference, "profile") is None
    assert [code for code, _, _ in ctx.issues] == ["endpoint_profile_invalid"]
    assert not ctx.gaps


def test_same_version_different_endpoint_materialization_is_rejected():
    from copy import deepcopy
    from dataclasses import fields, is_dataclass

    from tests.fixtures.execution_io_pipeline import io_pipeline_execution
    from scar.ir.execution.snapshot import external_artifact
    from scar.ir.execution.work import MaterializationRef
    from scar.ir.v2.ids import MaterializationID
    from scar.ir.program.providers import ProviderArtifact

    program, model, catalogs, details = io_pipeline_execution()
    assert not validate(model, program, **catalogs).issues
    original = next(row for row in model.content_reads if row.id == details["endpoint_read"])
    old_artifact = details["mats"]["endpoint"].artifact
    graph = catalogs["value_graphs"][old_artifact.sha256]
    alternate_graph = deepcopy(graph)
    endpoint = alternate_graph.materializations[details["mats"]["endpoint"].materialization]
    alternate_id = MaterializationID("io.endpoint.same-version-alternate")
    alternate_graph.add_materialization(replace(endpoint, id=alternate_id))
    alternate_artifact = external_artifact(alternate_graph, old_artifact.uri)
    alternate_mat = MaterializationRef(alternate_artifact, alternate_id)
    assert alternate_graph.materializations[alternate_id].value_version == endpoint.value_version
    assert alternate_mat != details["mats"]["endpoint"]

    def rebind_value_graph_artifact(value):
        if type(value) is ProviderArtifact and value == old_artifact:
            return alternate_artifact
        if type(value) is tuple:
            items = tuple(rebind_value_graph_artifact(item) for item in value)
            return value if all(new is old for new, old in zip(items, value, strict=True)) else items
        if type(value) is list:
            items = [rebind_value_graph_artifact(item) for item in value]
            return value if all(new is old for new, old in zip(items, value, strict=True)) else items
        if type(value) is dict:
            items = {rebind_value_graph_artifact(key): rebind_value_graph_artifact(item)
                     for key, item in value.items()}
            return value if all(new_key is old_key and new_item is old_item
                                for (new_key, new_item), (old_key, old_item)
                                in zip(items.items(), value.items(), strict=True)) else items
        if is_dataclass(value) and not isinstance(value, type):
            updates = {}
            for field in fields(value):
                old = getattr(value, field.name)
                new = rebind_value_graph_artifact(old)
                if new is not old:
                    updates[field.name] = new
            return replace(value, **updates) if updates else value
        return value

    rebound = rebind_value_graph_artifact(model)
    changed_read = replace(original,
        placement=replace(original.placement, materialization=alternate_mat))
    assert changed_read.placement.materialization != original.placement.materialization

    changed = replace(rebound, content_reads=tuple(changed_read if row.id == original.id else row
                                                    for row in rebound.content_reads))
    alternate_catalogs = {**catalogs, "value_graphs": {alternate_artifact.sha256: alternate_graph}}
    report = validate(changed, program, **alternate_catalogs)
    assert "validity_endpoint_materialization" in {issue.code for issue in report.issues}


def test_endpoint_geometry_budget_preserves_demand_offers_and_pending_portion():
    from tests.fixtures.execution_io_pipeline import io_pipeline_execution
    from scar.ir.execution.query import ExecutionIndex
    from scar.ir.execution.validity_budget import ValidityBudget
    from scar.ir.execution.validity_query import _endpoint_coverage

    program, model, catalogs, details = io_pipeline_execution()
    index = ExecutionIndex(model, program, **catalogs)
    complete = index.validity(details["endpoint_read"], budget=131072)
    required = complete["conditional_fragment_coverage"]["required"]
    offered = tuple((fragment["label"], fragment["actual"])
                    for fragment in complete["contributions"]
                    if type(fragment["actual"]) is dict
                    and fragment["actual"].get("kind") == "endpoint-byte-range")
    assert offered

    # A single valid offer costs 2 for request/offer parsing, 3 to construct
    # boundaries and 6 to sort the two boundary points. The final portion scan
    # is therefore cut off at this limit while the complete offer is retained.
    budget = ValidityBudget(13)
    partial = _endpoint_coverage(required, offered, budget)

    assert partial["truncated"] is True and budget.truncated is True
    assert partial["status"] == "UNRESOLVED"
    assert partial["required"] == required
    assert partial["geometry"]["required_intervals"] == ((0, 8),)
    assert partial["geometry"]["covered_intervals"] == ((0, 8),)
    assert partial["offered"] == tuple(offer for _, offer in offered)
    assert partial["pending_portions"] == {
        "boundaries": (0, 8), "next_pair_index": 0}
    assert partial["budget_used"] == 13

    # If the offer scan itself stops, retain the full original offer inventory
    # and a cursor to the not-yet-examined alternative.
    two_offers = (offered[0], ("unvisited-alternative", offered[0][1]))
    offer_budget = ValidityBudget(5)
    offer_partial = _endpoint_coverage(required, two_offers, offer_budget)
    assert offer_partial["truncated"] is True
    assert offer_partial["status"] == "UNRESOLVED"
    assert offer_partial["offered"] == tuple(offer for _, offer in two_offers)
    assert offer_partial["pending_offers"] == ("unvisited-alternative",)
    assert offer_partial["geometry"]["required_intervals"] == ((0, 8),)

    public_partial = index.validity(details["endpoint_read"], budget=1)
    assert public_partial["truncated"] is True
    assert public_partial["conditional_support"]["status"] == "TRUNCATED"


def test_work_outcome_production_retains_actual_selector_for_validity():
    from tests.fixtures.execution_io_pipeline import io_pipeline_execution
    from scar.ir.execution.ids import ContentReadID, OutcomeProductionID
    from scar.ir.execution.query import ExecutionIndex
    from scar.ir.execution.coverage import RegionRef

    program, model, catalogs, details = io_pipeline_execution()
    index = ExecutionIndex(model, program, **catalogs)
    row = next(item for item in model.produced if item.id == OutcomeProductionID("io.prepare.materialize"))
    production = index.outcome_production(row.id)

    assert type(production["actual_selector"]) is RegionRef
    assert production["actual_selector"] == row.actual
    report = index.validity(ContentReadID("io.prepare.materialize"), budget=131072)
    contribution = next(item for item in report["contributions"]
                       if item["production"] is not None
                       and item["production"]["row"].id == row.id)
    assert contribution["actual"] == row.actual


def test_public_validity_query_rechecks_endpoint_profile_bytes_from_fresh_snapshot():
    from tests.fixtures.execution_io_pipeline import io_pipeline_execution

    program, model, catalogs, details = io_pipeline_execution()
    index = ExecutionIndex(model, program, **catalogs)
    profile = details["read_profile"].artifact
    assert catalogs["artifact_bytes"][profile.sha256]
    catalogs["artifact_bytes"][profile.sha256] = b"{}"

    with pytest.raises(ValueError, match="endpoint_profile_artifact"):
        index.validity(details["endpoint_read"], budget=131072)


def test_zero_byte_write_actual_never_covers_nonempty_endpoint_read():
    from tests.fixtures.execution_io_pipeline import io_pipeline_execution

    program, model, catalogs, details = io_pipeline_execution(written=0)
    index = ExecutionIndex(model, program, **catalogs)
    result = index.validity(details["endpoint_read"], budget=131072)

    assert result["conditional_fragment_coverage"]["status"] == "INCOMPLETE"
    assert result["conditional_fragment_coverage"]["geometry"]["missing_intervals"] == ((0, 8),)
    assert result["conditional_support"]["status"] != "MATCHED"

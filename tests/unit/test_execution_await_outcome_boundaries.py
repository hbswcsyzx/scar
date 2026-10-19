"""Capture, scope and budget boundaries of the original await obligations."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import AwaitIteratorQualification
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import (
    OperationSiteSubject, OwnedUse, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_failure_graphs import await_failure_execution
from tests.fixtures.execution_await_resume_graphs import await_resume_execution
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_protocol_graphs import _scope


QUERY_BUDGET = 1048576


def _index(program, model):
    require_valid(program)
    report = validate_execution(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _static(program, scope):
    report = ProgramIndex(program).protocol_obligations(scope,
        budget=QUERY_BUDGET)["connections"]["families"]["await"]
    return {field: tuple(row for row in report[field] if row["scope"] == scope)
            for field in ("outcomes", "failure_paths")}


def _keys(report, field):
    return tuple(row["key"] for row in report[field])


@pytest.mark.parametrize("field,inventory_field,parent_field", (
    ("outcomes", "outcome_inventory", "advance_operation"),
    ("failure_paths", "failure_path_inventory", "source_operation"),
))
def test_original_parent_anchor_counts_are_not_derived_route_or_budget_prefix_counts(
        field, inventory_field, parent_field):
    program, model, details = await_resume_execution(zero_cut=True, instances=2)
    scope = details["static"]["acquisition_scope"]
    original = _static(program, scope)[field]
    assert original
    expected = {row["key"]: sum(occurrence.operation == row[parent_field]
        for occurrence in model.operations) for row in original}
    assert all(count == 2 for count in expected.values())
    index = _index(program, model)
    complete = index.await_body_links(scope, budget=QUERY_BUDGET)
    assert set(_keys(complete, field)) == set(expected)
    inventory = complete[inventory_field]
    assert inventory["occurrence_count"] == sum(expected.values())
    assert inventory["observed_occurrence_count"] == sum(expected.values())
    assert inventory["checked_occurrence_count"] == sum(expected.values())
    assert inventory["pending_occurrence_count"] == 0
    for row in complete[field]:
        assert row["occurrence_count"] == expected[row["key"]]

    bounded = index.await_body_links(scope, budget=1)
    inventory = bounded[inventory_field]
    assert inventory["known_inventory_complete"] is False
    assert inventory["jobs_total"] is None
    assert inventory["pending_count"] is None
    assert inventory["occurrence_count"] is None
    assert inventory["pending_occurrence_count"] is None
    assert inventory["observed_occurrence_count"] == sum(
        expected[row["key"]] for row in bounded[field])
    assert inventory["checked_occurrence_count"] <= inventory["observed_occurrence_count"]
    assert inventory["cursor"] is not None
    assert bounded["budget"]["used"] <= 1
    assert bounded["budget"]["truncated"] is True
    for row in bounded[field]:
        assert row["occurrence_count"] == expected[row["key"]]


def test_returned_dynamic_outcome_and_nested_conversion_views_are_detached():
    program, model, details = await_resume_execution(zero_cut=True)
    index = _index(program, model)
    original_receipt = deepcopy(index.report)
    first = index.await_body_links(details["static"]["acquisition_scope"], budget=QUERY_BUDGET)
    original = deepcopy(first)
    outcome = next(row for row in first["outcomes"] if row["occurrences"])
    occurrence = next(row for row in outcome["occurrences"] if row["conversion_legs"])
    leg = next(row for row in occurrence["conversion_legs"]
               if row["selected"] is True and type(row["input_binding"]) is dict)
    outcome["definition"]["kind"] = "detached-only mutation"
    leg["input_binding"]["match"] = "detached-only mutation"
    leg["states"] = ({"detached_only": True},)
    assert first != original

    again = index.await_body_links(details["static"]["acquisition_scope"], budget=QUERY_BUDGET)
    assert again == original
    assert index.report == original_receipt


@pytest.mark.parametrize("source_only_failure", (False, True), ids=("return", "source-failure"))
def test_whole_capture_deletion_keeps_static_outcome_and_failure_keys(source_only_failure):
    if source_only_failure:
        program, model, details = await_failure_execution("lookup_raise")
        scope = details["acquisition_scope"]
        assert not model.body_drive_executions
    else:
        program, model, details = await_resume_execution(zero_cut=True)
        scope = details["static"]["acquisition_scope"]
    index = _index(program, model)
    captured = index.await_body_links(scope, budget=QUERY_BUDGET)
    original = _static(program, scope)
    empty = replace(model, activations=(), segments=(), visits=(), operations=(),
        values=(), uses=(), transfers=(), call_activations=(),
        body_drive_executions=(), body_activation_origins=())
    assert empty.snapshot == model.snapshot
    assert empty.runs == model.runs and empty.processes == model.processes
    assert empty.threads == model.threads
    missing = _index(program, empty).await_body_links(scope, budget=QUERY_BUDGET)
    for field, inventory_field in (("outcomes", "outcome_inventory"),
                                   ("failure_paths", "failure_path_inventory")):
        assert set(_keys(captured, field)) == {row["key"] for row in original[field]}
        assert _keys(missing, field) == _keys(captured, field)
        assert missing[inventory_field]["enumerated_count"] == captured[inventory_field]["enumerated_count"]
        assert missing[inventory_field]["occurrence_count"] == 0
        for row in missing[field]:
            assert row["occurrence_count"] == 0
            assert row["occurrences"] == ()
            assert row["status"] in ("MISSING", "PARTIAL")
    assert missing["status"] == "PARTIAL"
    assert all(missing[flag] is False for flag in (
        "source_runtime_verified", "runtime_identity_verified",
        "value_identity_verified", "transformation_authorized"))


def _independent_qualification():
    """A real uncalled predicate/branch region, with its own external input."""
    owner = RegionID("outcome.boundary.side")
    entry, accepted, rejected = (BlockID("outcome.boundary.side." + label)
        for label in ("entry", "accepted", "rejected"))
    qid, bid = (OperationID("outcome.boundary.side." + label)
                for label in ("qualify", "branch"))
    refs = tuple(ReferenceValue(ValueID("outcome.boundary.side." + label), owner,
        BlockArgument(block, 0)) for label, block in (
            ("input", entry), ("accepted.value", accepted), ("rejected.value", rejected)))
    checked = Use(UseID("outcome.boundary.side.checked"), refs[0].id, UseRole.REFERENCE)
    boolean = DataValue(ValueID("outcome.boundary.side.bool"), owner,
        OperationResult(qid, 0), "builtins.bool")
    qualification = Operation(qid, "this region's own candidate check", (Behavior.COMPUTE,),
        (checked,), (boolean.id,), effects_complete=True)
    condition = Use(UseID("outcome.boundary.side.condition"), boolean.id, UseRole.DATA)
    copies = tuple(Use(UseID(f"outcome.boundary.side.copy.{number}"), refs[0].id,
        UseRole.REFERENCE) for number in range(2))
    branch = Operation(bid, "branch on this exact own bool", (Behavior.CONTROL,),
        (condition, *copies), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(accepted, (copies[0].id,)), Successor(rejected, (copies[1].id,))),
            condition=condition.id))
    returns = []
    for number, ref in enumerate(refs[1:]):
        actual = Use(UseID(f"outcome.boundary.side.return.{number}.value"), ref.id,
            UseRole.REFERENCE)
        returns.append(Operation(OperationID(f"outcome.boundary.side.return.{number}"),
            "return this arm's original input", (Behavior.CONTROL,), (actual,),
            effects_complete=True, terminator=Terminator(TerminatorKind.RETURN,
                exit="normal", values=(actual.id,))))
    blocks = (Block(entry, (refs[0].id,), (qualification.id, branch.id)),
        Block(accepted, (refs[1].id,), (returns[0].id,)),
        Block(rejected, (refs[2].id,), (returns[1].id,)))
    region = Region(owner, "independent predicate region", entry, blocks,
        (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),)),))
    missing = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope = ProtocolScope(ProtocolScopeID("outcome.boundary.side.scope"),
        ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
        OperationSiteSubject(owner, qualification.id), missing)
    row = ProtocolOperation(scope.id, ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
        qid, 0, AwaitIteratorQualification(checked.id, BlockArgument(entry, 0),
            OperationResult(qid, 0), (), bid, True), missing)
    site = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
    graph = ProgramGraph(owner, (region,), (qualification, branch, *returns), (*refs, boolean),
        control_scopes=(_scope(owner, blocks),), protocol_scopes=(scope,),
        protocol_operations=(row,), protocol_result_consumers=(
            ProtocolResultConsumers(site, (OwnedUse(bid, condition.id),)),))
    return graph, qualification


def test_captured_unrelated_qualification_does_not_pollute_the_requested_scope():
    program, model, details = await_resume_execution(zero_cut=True)
    scope = details["static"]["acquisition_scope"]
    before = _index(program, model).await_body_links(scope, budget=QUERY_BUDGET)
    side, predicate = _independent_qualification()
    require_valid(side)
    region = side.regions[0]
    combined = replace(program,
        regions=(*program.regions, replace(region, parent=program.root)),
        operations=(*program.operations, *side.operations), values=(*program.values, *side.values),
        control_scopes=(*program.control_scopes, *side.control_scopes),
        protocol_scopes=(*program.protocol_scopes, *side.protocol_scopes),
        protocol_operations=(*program.protocol_operations, *side.protocol_operations),
        protocol_result_consumers=(*program.protocol_result_consumers, *side.protocol_result_consumers))
    assert all(operation.callee != region.id for operation in combined.operations)
    rows, _, _, captured = _activation(combined, region.id,
        ((region.entry, 0), (region.blocks[1].id, None)), "outcome.boundary.side.capture",
        details["point"], model.threads[0].id)
    assert predicate.id in captured
    names = ("activations", "segments", "visits", "operations", "values", "uses", "transfers")
    extended = replace(model, snapshot=snapshot_for(combined),
        **{name: (*getattr(model, name), *rows[name]) for name in names})
    assert any(occurrence.operation == predicate.id for occurrence in extended.operations)

    after = _index(combined, extended).await_body_links(scope, budget=QUERY_BUDGET)
    for field in ("outcomes", "failure_paths"):
        assert _keys(after, field) == _keys(before, field)
        assert all(row["definition"]["scope"] == scope for row in after[field])
    assert after["qualifications"] == before["qualifications"]
    assert after["qualification_inventory"]["records"] == before["qualification_inventory"]["records"]
    assert after["qualification_inventory"]["occurrence_count"] == before["qualification_inventory"]["occurrence_count"]


def test_expanded_qualification_keeps_only_its_exact_source_helper_activation():
    program, model, details = await_failure_execution("qualification_reject")
    scope = details["acquisition_scope"]
    expected = details["helper_operations"][details["qualification"].id]
    before = _index(program, model).await_body_links(scope, budget=QUERY_BUDGET)
    assert before["qualification_inventory"]["records"] == 1
    assert before["qualification_inventory"]["occurrence_count"] == 1
    assert {row["occurrence"].id for row in before["qualifications"]} == {expected}
    assert details["call_activation"].activation == details["helper_activation"]

    visits = {visit.id: visit for visit in model.visits}
    operations = {operation.id: operation for operation in program.operations}
    transfers = {transfer.operation: transfer for transfer in model.transfers}
    path = []
    for identity in details["helper_visits"]:
        visit = visits[identity]
        block = next(block for block in details["helper"].blocks if block.id == visit.block)
        last = operations[block.operations[-1]]
        actual = details["helper_operations"][last.id]
        transfer = transfers.get(actual)
        path.append((block.id, None if transfer is None else transfer.successor_index))
    point = EvidencePoint(model.runs[0].id, model.processes[0].id, details["source"])
    rows, sibling_activation, _, captured = _activation(program, details["helper"].id,
        tuple(path), "outcome.boundary.unlinked.same-helper", point, model.threads[0].id)
    assert sibling_activation != details["helper_activation"]
    assert captured[details["qualification"].id] != expected
    names = ("activations", "segments", "visits", "operations", "values", "uses", "transfers")
    extended = replace(model, **{name: (*getattr(model, name), *rows[name]) for name in names})
    assert sum(occurrence.operation == details["qualification"].id
               for occurrence in extended.operations) == 2
    assert all(call.activation != sibling_activation for call in extended.call_activations)

    after = _index(program, extended).await_body_links(scope, budget=QUERY_BUDGET)
    assert after["qualification_inventory"]["records"] == 1
    assert after["qualification_inventory"]["occurrence_count"] == 1
    assert {row["occurrence"].id for row in after["qualifications"]} == {expected}


def test_each_conversion_packet_is_joined_to_its_exact_terminal_before_parent_delivery():
    program, model, details = await_resume_execution(zero_cut=True, instances=2)
    report = _index(program, model).await_body_links(details["static"]["acquisition_scope"],
        budget=QUERY_BUDGET)
    expected = {instance["call_activations"][-1].caller for instance in details["instances"]}
    checked, packets = set(), set()
    for outcome in report["outcomes"]:
        for occurrence in outcome["occurrences"]:
            if occurrence["selected"] is not True:
                continue
            for leg in occurrence["conversion_legs"]:
                if leg["selected"] is not True or leg["definition"]["role"] != "COMPLETION":
                    continue
                assert leg["packets"]
                whole = leg["packets"][0]["value"]
                assert whole is not None
                terminals = tuple(terminal for terminal in leg["terminals"]
                    if terminal["selected"] is True)
                assert terminals
                for terminal in terminals:
                    packet = terminal["packet_value"]
                    assert packet is not None
                    binding = terminal["packet_binding"]
                    assert {"source_value", "target_value", "match", "support", "compatibility"} <= set(binding)
                    assert binding["source_value"] == whole
                    assert binding["target_value"] == packet
                    assert binding["match"] is True
                    assert whole.id == packet.id or binding["support"]
                    # This remains a separate original call-output relation.
                    parent_binding = terminal["binding"]
                    assert parent_binding["source_value"] == packet
                    assert parent_binding["target_value"] == terminal["parent_value"]
                    assert parent_binding["match"] is True
                checked.add(occurrence["advance"].id)
                packets.add(whole.id)
    assert checked == expected
    assert len(packets) == 2
    assert report["budget"]["truncated"] is False

"""New exact protocol connections, not a native Python conformance test."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import ProtocolScopeID
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.model import ExitKind
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.protocols import (
    ContractResult, DriverSubject, DriveResult, HostTerminal, NoEntryOutcome,
    OperationSiteSubject, OutcomeAdapter, OutcomeAdapterRule, OwnedUse,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope, RequestOperandBinding,
    StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ExistingAccess
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_protocol_graphs import (
    closed_request_program, generator_protocol_program, no_entry_throw_program,
    request_processing_program,
)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _replace_row(graph, old, new):
    return replace(graph, protocol_operations=tuple(new if row == old else row
                                                   for row in graph.protocol_operations))


def _replace_use(graph, operation, use, value):
    return replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(item, value=value) if item.id == use else item for item in op.uses))
        if op.id == operation else op for op in graph.operations))


def _scope(view, identity):
    return next(item for item in view["scopes"] if item["scope"].id == identity)


@pytest.mark.parametrize("loop", (False, True))
def test_raw_pack_processing_and_packet_keep_their_original_distinct_owned_uses(loop):
    graph, details = request_processing_program(loop=loop)
    require_valid(graph)
    processor = next(op for op in graph.operations if op.id == details["processing"])
    raw_pack = next(op for op in graph.operations if op.id == details["pack"])
    assert raw_pack.uses[0].id != processor.uses[1].id
    assert raw_pack.uses[0].value == processor.uses[1].value
    report = ProgramIndex(graph).protocol_obligations(details["scope"])
    assert _scope(report, details["scope"])["obligations"]
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False


def test_same_typed_packet_q_cannot_replace_the_selected_normalized_components():
    graph, details = request_processing_program()
    row = details["rows"][1]
    bad = replace(row, operation=details["other_packet_operation"],
                  contract=replace(row.contract, packet=details["other_packet"]))
    assert {"protocol_copy", "protocol_packet_source"} & _codes(_replace_row(graph, row, bad))


def test_packet_component_cannot_use_its_own_destination_use_as_provenance():
    graph, details = request_processing_program()
    row = details["rows"][1]
    bad = replace(row, contract=replace(row.contract,
        exception_source=OwnedUse(details["packet_operation"], details["consumer_use"])))
    assert "protocol_packet_source" in _codes(_replace_row(graph, row, bad))


def test_contract_result_cannot_choose_another_same_typed_result_of_its_producer():
    graph, details = request_processing_program()
    row = details["rows"][1]
    source = row.contract.exception_source
    assert isinstance(source, ContractResult)
    bad = replace(row, contract=replace(row.contract,
        exception_source=replace(source, result_port=details["other_result"])))
    assert "protocol_contract_result" in _codes(_replace_row(graph, row, bad))


def test_raw_ordinal_uses_the_actual_pack_position_not_another_equal_type():
    graph, details = request_processing_program()
    row = details["rows"][0]
    binding, = row.contract.operand_bindings
    bad = replace(row, contract=replace(row.contract,
        operand_bindings=(replace(binding, request_ordinal=1),)))
    assert "protocol_raw_operand" in _codes(_replace_row(graph, row, bad))


def test_pack_owned_use_cannot_be_reused_as_the_processing_operations_actual():
    graph, details = request_processing_program()
    row = details["rows"][0]
    pack = next(op for op in graph.operations if op.id == details["pack"])
    bad = replace(row, contract=replace(row.contract,
        operand_bindings=(RequestOperandBinding(0, pack.uses[0].id),)))
    assert "protocol_raw_operand" in _codes(_replace_row(graph, row, bad))


def test_a_reference_operand_is_not_an_external_raw_request_boundary():
    graph, details = request_processing_program()
    row = details["rows"][0]
    binding, = row.contract.operand_bindings
    # Remove the binding when assigning that Use to the raw role so the
    # constructor remains well-formed.  The unchanged core operation is valid.
    bad = replace(row, contract=replace(row.contract, raw_use=binding.operation_use,
                                       operand_bindings=()))
    assert {"protocol_raw_kind", "protocol_result_owner"} & _codes(_replace_row(graph, row, bad))


def test_same_static_producer_on_a_loop_backedge_does_not_mean_current_evaluation():
    graph, _ = request_processing_program(loop=True, previous_iteration=True)
    assert "protocol_copy" in _codes(graph)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
@pytest.mark.parametrize("reject", (False, True))
def test_no_entry_uses_exact_helper_edge_and_only_that_edge_can_seed_finished(selected, reject):
    graph, details = no_entry_throw_program(selected=selected, reject=reject)
    require_valid(graph)
    assert not graph.body_drives
    index = ProgramIndex(graph)
    assert not index.lifecycle_before(details["processing"]).terminal.is_finished(details["owner"])
    for number, (terminal, owner) in enumerate(zip(details["terminals"], details["owner_formals"])):
        fact = index.lifecycle_before(terminal).terminal
        assert fact.is_finished(owner) is (not reject and number == details["selected_edge"])
        assert fact.source_operations(owner) == (
            frozenset((details["processing"],)) if not reject and number == details["selected_edge"]
            else frozenset())


def test_no_entry_selected_edge_must_match_its_original_slot_and_result():
    graph, details = no_entry_throw_program()
    row = details["row"]
    bad = replace(row, contract=replace(row.contract,
        selected_edge=ControlEdgeReference(details["processing"], 1)))
    assert "protocol_no_entry_edge" in _codes(_replace_row(graph, row, bad))


def test_no_entry_cannot_borrow_the_other_branchs_host_exception():
    graph, details = no_entry_throw_program()
    row = details["row"]
    bad = replace(row, contract=replace(row.contract,
        terminal=replace(row.contract.terminal, operation=details["terminals"][1])))
    assert {"protocol_copy", "protocol_no_entry_edge"} & _codes(_replace_row(graph, row, bad))


def test_no_entry_cannot_seed_finished_after_omitting_a_known_lifecycle_domain():
    graph, details = no_entry_throw_program()
    row = details["row"]
    assert len(row.contract.state_sites) > 1
    interface, = graph.driver_interfaces
    operation = next(op for op in graph.operations if op.id == row.operation)
    values, uses = {value.id: value for value in graph.values}, {use.id: use for use in operation.uses}
    remaining = tuple(site for site in row.contract.state_sites
                      if values[uses[site.state_use].value].location not in interface.lifecycle)
    assert remaining and len(remaining) < len(row.contract.state_sites)
    changed = _replace_row(graph, row, replace(row,
        contract=replace(row.contract, state_sites=remaining)))
    # An incomplete declaration is representable, but is not a terminal source.
    require_valid(changed)
    index = ProgramIndex(changed)
    assert not index.no_entry_publications(details["processing"])
    terminal = details["terminals"][details["selected_edge"]]
    owner = details["owner_formals"][details["selected_edge"]]
    assert not index.lifecycle_before(terminal).terminal.is_finished(owner)
    view = index.protocol_obligations(details["scope"])
    rows = [item for clause in view["scopes"][0]["obligations"] for item in clause["rows"]]
    assert any("no_entry_state_post_unresolved" in item["gaps"] for item in rows)


def test_no_entry_may_leave_unrelated_domains_to_original_core_state_flow():
    graph, details = no_entry_throw_program()
    row = details["row"]
    interface, = graph.driver_interfaces
    operation = next(op for op in graph.operations if op.id == row.operation)
    values, uses = {value.id: value for value in graph.values}, {use.id: use for use in operation.uses}
    lifecycle_sites = tuple(site for site in row.contract.state_sites
        if values[uses[site.state_use].value].location in interface.lifecycle)
    assert lifecycle_sites and len(lifecycle_sites) < len(row.contract.state_sites)
    changed = _replace_row(graph, row, replace(row,
        contract=replace(row.contract, state_sites=lifecycle_sites)))
    require_valid(changed)
    index = ProgramIndex(changed)
    assert index.no_entry_publications(details["processing"])
    terminal = details["terminals"][details["selected_edge"]]
    owner = details["owner_formals"][details["selected_edge"]]
    assert index.lifecycle_before(terminal).terminal.is_finished(owner)


@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_closed_requests_use_current_helper_outputs_without_driving_or_seeding_finished(kind):
    graph, details = closed_request_program(kind=kind)
    require_valid(graph)
    assert not graph.body_drives
    index = ProgramIndex(graph)
    for terminal, owner in zip(details["terminals"], details["owner_formals"]):
        assert not index.lifecycle_before(terminal).terminal.is_finished(owner)
    assert index.protocol_obligations(details["scope"])["source_runtime_verified"] is False


@pytest.mark.parametrize("kind", (RawRequestKind.NEXT, RawRequestKind.CLOSE))
def test_closed_requests_do_not_replay_a_previous_packet_or_return_value(kind):
    graph, details = closed_request_program(kind=kind)
    terminal = next(op for op in graph.operations if op.id == details["terminals"][0])
    old = details["old_return"] if kind is RawRequestKind.CLOSE else details["old_packet"]
    altered = _replace_use(graph, terminal.id, terminal.terminator.values[0], old)
    assert "protocol_copy" in _codes(altered)


@pytest.mark.parametrize("target", ("start", "value", "packet"))
def test_generator_routes_keep_yield_return_adapter_and_throw_consumer_distinct(target):
    graph, details = generator_protocol_program(target=target)
    require_valid(graph)
    report = ProgramIndex(graph).protocol_obligations(details["scope"])
    obligations = _scope(report, details["scope"])["obligations"]
    assert obligations
    assert report["source_runtime_verified"] is False
    if target == "value":
        # The caller-visible StopIteration construction can fail and has real
        # N/R ports.  A body RETURN is not an unchanged host RETURN shortcut.
        assert any(row.clause is ProtocolClause.HOST_ADAPTER for row in graph.protocol_operations)
        driver = next(region for region in graph.regions if region.id == graph.root)
        assert all(port.kind is ExitKind.RAISE for port in driver.exits)


def test_yield_host_item_cannot_be_replaced_by_an_available_unrelated_reference():
    graph, details = generator_protocol_program()
    drive = next(op for op in graph.operations if op.id == details["drive"])
    block = drive.terminator.successors[0].block
    driver = next(region for region in graph.regions if region.id == graph.root)
    landing = next(item for item in driver.blocks if item.id == block)
    terminal = next(op for op in graph.operations if op.id == landing.operations[-1])
    payload = terminal.terminator.values[0]
    unrelated = graph.driver_interfaces[0].receiver
    assert "protocol_copy" in _codes(_replace_use(graph, terminal.id, payload, unrelated))


@pytest.mark.parametrize("target", ("value", "packet"))
def test_processed_payload_cannot_be_replaced_by_old_entry_payload(target):
    graph, details = generator_protocol_program(target=target)
    gate_row, = graph.final_body_gates
    gate = next(op for op in graph.operations if op.id == gate_row.operation)
    delivery_use = gate.invoke_arguments[gate_row.delivery_arguments[0]]
    driver = next(region for region in graph.regions if region.id == graph.root)
    entry = next(block for block in driver.blocks if block.id == driver.entry)
    old_payload = entry.arguments[2]
    # Update the independent forward as well: D1 alone accepts the consistent
    # same-type route.  Protocol validation must still reject its wrong source.
    current = next(use.value for use in gate.uses if use.id == delivery_use)
    altered = replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(use, value=old_payload) if use.value == current else use for use in op.uses))
        if op.id == gate.id else op for op in graph.operations))
    assert "protocol_copy" in _codes(altered)


def test_generator_return_adapter_cannot_substitute_a_current_helper_result_for_body_return():
    graph, details = generator_protocol_program(target="value")
    processor = next(row for row in graph.protocol_operations
                     if row.operation == details["processing"] and row.slot == 0)
    substitute = ContractResult(processor.scope, processor.clause, processor.operation,
                                processor.slot, processor.contract.result)
    adapters = tuple(row for row in graph.protocol_operations
                     if row.clause is ProtocolClause.HOST_ADAPTER)
    changed = replace(graph, protocol_operations=tuple(
        replace(row, contract=replace(row.contract, input=substitute)) if row in adapters else row
        for row in graph.protocol_operations))
    adapter, = {row.operation for row in adapters}
    changed = _replace_use(changed, adapter, adapters[0].contract.input_use, details["payload"])
    # The mutation keeps both real constructor N/R branches, current states,
    # and dominant Reference input.  The protocol role alone is contradictory.
    require_valid(replace(changed, protocol_scopes=(), protocol_operations=()))
    assert "protocol_adapter_source" in _codes(changed)


@pytest.mark.parametrize("field", ("input", "output"))
def test_generator_return_adapter_cannot_treat_its_trailing_state_slot_as_the_payload(field):
    graph, _ = generator_protocol_program(target="value")
    row = next(row for row in graph.protocol_operations if row.clause is ProtocolClause.HOST_ADAPTER)
    adapter = next(op for op in graph.operations if op.id == row.operation)
    state_use = adapter.invoke_arguments[1]
    if field == "input":
        contract = replace(row.contract, input=replace(row.contract.input, index=1), input_use=state_use)
    else:
        contract = replace(row.contract, output=replace(row.contract.output,
            result=replace(row.contract.output.result, index=1)))
    changed = _replace_row(graph, row, replace(row, contract=contract))
    # All actual operation fields, Uses and edges are untouched.  Only the
    # declared semantic role has been redirected to the current world state.
    assert "protocol_adapter_source" in _codes(changed)


def test_annotating_an_old_host_return_does_not_turn_it_into_stop_iteration():
    graph = driver_program(target="value")
    require_valid(graph)
    interface, = graph.driver_interfaces
    drive, = graph.body_drives
    operation = next(op for op in graph.operations if op.id == drive.operation)
    edge, = operation.terminator.successors
    driver = next(region for region in graph.regions if region.id == interface.region)
    block = next(block for block in driver.blocks if block.id == edge.block)
    terminal = next(op for op in graph.operations if op.id == block.operations[-1])
    scope_id = ProtocolScopeID("old.generic.scope")
    missing = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope = ProtocolScope(scope_id, ProtocolProfile.GENERATOR_BODY_V1,
                          DriverSubject(interface.region), missing)
    contract = OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.operation, edge.source), 0),
        terminal.terminator.values[0], HostTerminal(terminal.id),
        OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION)
    row = ProtocolOperation(scope_id, ProtocolClause.HOST_ADAPTER, terminal.id, 0, contract, missing)
    altered = replace(graph, protocol_scopes=(scope,), protocol_operations=(row,))
    assert {"protocol_adapter_source", "protocol_host_adapter"} & _codes(altered)


@pytest.mark.parametrize("bad_state_index", (False, True))
def test_a_real_body_drive_is_not_a_no_entry_transition_and_bad_metadata_does_not_crash(bad_state_index):
    graph, details = generator_protocol_program()
    require_valid(graph)
    drive, = graph.body_drives
    operation = next(op for op in graph.operations if op.id == drive.operation)
    driver = next(region for region in graph.regions if region.id == graph.root)
    target = operation.terminator.successors[0].block
    block = next(block for block in driver.blocks if block.id == target)
    identity = ProtocolScopeID("incorrect.no.entry.scope")
    missing = StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)
    scope = ProtocolScope(identity, ProtocolProfile.CREATED_THROW_V1,
        OperationSiteSubject(driver.id, drive.operation), missing)
    contract = NoEntryOutcome(drive.instance, drive.scheduler_request, missing,
        (ExistingAccess(drive.operation, 0),) if bad_state_index else (),
        ControlEdgeReference(drive.operation, 0), HostTerminal(block.operations[-1]))
    row = ProtocolOperation(identity, ProtocolClause.INITIAL_THROW_DELIVERED,
                            drive.operation, 0, contract, missing)
    altered = replace(graph, protocol_scopes=(*graph.protocol_scopes, scope),
                      protocol_operations=(*graph.protocol_operations, row))
    assert "protocol_no_entry_edge" in _codes(altered)


def test_missing_scope_and_small_budget_keep_the_original_obligation_inventory():
    graph, details = request_processing_program()
    full = ProgramIndex(graph).protocol_obligations(details["scope"])
    limited = ProgramIndex(graph).protocol_obligations(details["scope"], budget=1)
    assert _scope(limited, details["scope"])["obligations"]
    assert limited["cursor"] is not None
    assert limited["budget"]["truncated"] is True
    assert full["source_runtime_verified"] is limited["source_runtime_verified"] is False
    removed = replace(graph, protocol_scopes=(), protocol_operations=())
    report = ProgramIndex(removed).protocol_obligations()
    assert report["gaps"]
    assert report["transformation_authorized"] is False

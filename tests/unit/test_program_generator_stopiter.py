"""Body escape adaptation differs from caught and no-user-entry initial throw."""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.drivers import BodyResume, RawRequestKind
from scar.ir.program.ids import OperationID, ProtocolScopeID
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue, TerminatorKind,
)
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.protocols import (
    ContractResult, DriverSubject, DriveResult, HostTerminal, OutcomeAdapter, OutcomeAdapterRule as A,
    OwnedUse, ProtocolClause as C, ProtocolOperation, ProtocolProfile, ProtocolScope,
    RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumeSlotKind, SuspendTerminator
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_stopiter_graphs import stopiter_program
from tests.fixtures.program_protocol_graphs import _source_gap


def _op(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=())


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation, identity, value):
    return replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(use, value=value) if use.id == identity else use for use in op.uses))
        if op.id == operation else op for op in graph.operations))


@pytest.mark.parametrize("route", ("internal", "escaping"))
def test_body_stopiteration_escape_uses_this_packet_and_both_own_constructor_results(route):
    graph, details = stopiter_program(route=route)
    require_valid(_core(graph))
    require_valid(graph)
    index, flow = ProgramIndex(graph), ProtocolFlow(graph)
    assert _op(graph, details["adapted_source"]).terminator.kind is TerminatorKind.RAISE
    assert {row.slot for row in details["adapters"]} == {0, 1}
    for row, terminal_id in zip(details["adapters"], details["host_terminals"], strict=True):
        assert row.contract.rule is A.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR
        assert row.contract.input.outcome.source == details["adapted_source"]
        assert row.contract.input.index == 0
        assert flow.forwards(row.contract.input, OwnedUse(row.operation, row.contract.input_use)) is True
        assert type(row.contract.output) is InvokeLiteralResult
        assert row.contract.output.edge.successor_index == row.slot
        terminal = _op(graph, terminal_id)
        assert terminal.terminator.kind is TerminatorKind.RAISE
        # NORMAL constructs an exception Reference and then its exact packet;
        # RAISE forwards the constructor's own already-complete packet.
        if row.slot == 0:
            packet = next(definition for definition in graph.exception_packets
                          if definition.value == index.use_site(terminal.terminator.values[0]).use.value)
            assert flow.forwards(row.contract.output, OwnedUse(OperationID("adapter.packet"), packet.exception)) is True
        else:
            assert flow.forwards(row.contract.output, OwnedUse(terminal.id, terminal.terminator.values[0])) is True
    if route == "internal":
        assert details["factory"] is not None
        packet = next(definition for definition in graph.exception_packets
                      if definition.value.value == "stopiter.body.packet")
        body_factory = _op(graph, details["factory"])
        assert len(body_factory.terminator.successors) == 2
        assert packet.value != details["old_packet"]
        source = _op(graph, details["adapted_source"])
        assert index.use_site(source.terminator.values[0]).use.value == packet.value
    else:
        drive = graph.body_drives[0]
        assert type(drive.target) is BodyResume
        assert flow.forwards(details["normal_result"], OwnedUse(drive.operation, drive.resume_inputs[0].source)) is True
        source = _op(graph, details["adapted_source"])
        delivered = next(use.value for use in source.uses if use.id == source.terminator.values[0])
        assert index.values[delivered].protocol is P.EXCEPTION_PACKET
    report = index.protocol_obligations(details["scope"], budget=65536)
    assert report["source_runtime_verified"] is report["transformation_authorized"] is False


def test_caught_external_stopiteration_is_a_real_yield_not_an_escape_adapter_or_finished_fact():
    graph, details = stopiter_program(route="caught")
    require_valid(graph)
    index, flow = ProgramIndex(graph), ProtocolFlow(graph)
    assert not details["adapters"]
    source = _op(graph, details["adapted_source"])
    assert type(source.terminator) is SuspendTerminator
    drive, = graph.body_drives
    ingress = _op(graph, drive.target.suspend).terminator.successors[drive.target.successor]
    assert any(slot.kind is ResumeSlotKind.THROWN_PACKET for slot in ingress.inputs)
    assert flow.forwards(details["normal_result"], OwnedUse(drive.operation, drive.resume_inputs[0].source)) is True
    terminal = _op(graph, details["host_terminals"][0])
    outcome = next(row.outcome for row in graph.body_outcome_commits if row.outcome.source == source.id)
    assert terminal.terminator.kind is TerminatorKind.RETURN
    assert flow.forwards(DriveResult(outcome, 0), OwnedUse(terminal.id, terminal.terminator.values[0])) is True
    commit = next(row for row in graph.body_outcome_commits if row.outcome == outcome)
    owner = index.use_site(commit.instance).use.value
    assert not index.lifecycle_after(commit.operation).terminal.is_finished(owner)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_created_stopiteration_is_initial_no_entry_termination_and_preserves_the_selected_original_packet(selected):
    graph, details = stopiter_program(route="created", selected=selected)
    require_valid(graph)
    index, flow = ProgramIndex(graph), ProtocolFlow(graph)
    assert not graph.body_drives and not graph.final_body_gates
    assert not any(type(row.contract) is OutcomeAdapter for row in graph.protocol_operations)
    raw = next(row for row in graph.raw_driver_requests if row.value == details["raw"])
    assert raw.kind is RawRequestKind.THROW
    publication, = index.no_entry_publications(details["processing"])
    assert publication.selected_edge.successor_index == int(selected is ExitKind.RAISE)
    terminal = _op(graph, details["host_terminals"][0])
    assert terminal.terminator.kind is TerminatorKind.RAISE
    assert flow.forwards(publication.declaration.contract.selected_input,
                         OwnedUse(terminal.id, terminal.terminator.values[0])) is True
    owner = details["owner_formals"][details["selected_edge"]]
    assert index.lifecycle_edge(details["processing"], details["selected_edge"]).terminal.is_finished(owner)


@pytest.mark.parametrize("route", ("internal", "escaping"))
@pytest.mark.parametrize("edge", (0, 1))
def test_escape_constructor_host_cannot_replay_an_available_same_typed_old_packet(route, edge):
    graph, details = stopiter_program(route=route)
    terminal = _op(graph, details["host_terminals"][edge])
    wrong = _change_use(graph, terminal.id, terminal.terminator.values[0], details["old_packet"])
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)


@pytest.mark.parametrize("route", ("internal", "escaping"))
def test_constructed_packet_cannot_replace_the_constructor_own_reference_with_another_reference(route):
    graph, _ = stopiter_program(route=route)
    packet = next(definition for definition in graph.exception_packets
                  if definition.value.value == "adapter.packet.value")
    wrong = _change_use(graph, OperationID("adapter.packet"), packet.exception,
                        graph.driver_interfaces[0].receiver)
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)


@pytest.mark.parametrize("route", ("internal", "escaping"))
def test_escape_host_cannot_reuse_the_state_from_before_its_driver_or_constructor(route):
    graph, details = stopiter_program(route=route)
    index = ProgramIndex(graph)
    terminal = _op(graph, details["host_terminals"][0])
    interface = graph.driver_interfaces[0]
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    states = {index.values[value].location: value for value in entry.arguments
              if isinstance(index.values[value], StateVersionValue)}
    actual = next(use for use in terminal.uses if isinstance(index.values[use.value], StateVersionValue))
    wrong = _change_use(graph, terminal.id, actual.id, states[index.values[actual.value].location])
    assert "stale_state" in _codes(wrong)


def test_yield_cannot_be_labelled_as_escaping_stopiteration_without_changing_any_core_source():
    graph, _ = stopiter_program(route="caught", wrong_source_kind=True)
    require_valid(_core(graph))
    assert "protocol_adapter_source" in _codes(graph)


@pytest.mark.parametrize("mutation", ("state-input", "state-output", "return-rule"))
def test_same_core_graph_rejects_wrong_payload_role_or_wrong_body_outcome_rule(mutation):
    graph, details = stopiter_program()
    row = details["adapters"][0]
    if mutation == "state-input":
        contract = replace(row.contract, input=replace(row.contract.input, index=1))
    elif mutation == "state-output":
        contract = replace(row.contract, output=replace(row.contract.output, result=CompletionResult(1)))
    else:
        contract = replace(row.contract, rule=A.GENERATOR_RETURN_TO_STOP_ITERATION)
    changed = replace(row, contract=contract)
    graph = replace(graph, protocol_operations=tuple(changed if original == row else original
                                                    for original in graph.protocol_operations))
    require_valid(_core(graph))
    assert "protocol_adapter_source" in _codes(graph)


@pytest.mark.parametrize("route", ("internal", "escaping"))
def test_deleting_adapter_metadata_does_not_license_a_different_host_packet(route):
    graph, _ = stopiter_program(route=route)
    graph = replace(graph, protocol_operations=tuple(row for row in graph.protocol_operations
                                                    if type(row.contract) is not OutcomeAdapter))
    require_valid(_core(graph))
    assert "protocol_copy" in _codes(graph)


def test_initial_no_body_packet_cannot_be_relabelled_as_a_body_escape_adapter():
    graph, details = stopiter_program(route="created")
    terminal = _op(graph, details["host_terminals"][0])
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID("stopiter.wrong.initial.adapter"), ProtocolProfile.GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    initial = details["row"].contract
    processing = ProtocolOperation(scope.id, C.REQUEST_PROCESSING, details["processing"], details["selected_edge"],
        RequestProcessing(initial.effective_request_use, (), initial.selected_input,
                          initial.state_sites, RequestProcessingRule.CHECK_THROW), _source_gap())
    source = ContractResult(scope.id, processing.clause, processing.operation, processing.slot,
                            processing.contract.result)
    row = ProtocolOperation(scope.id, C.HOST_ADAPTER, terminal.id, 0,
        OutcomeAdapter(source, terminal.terminator.values[0], HostTerminal(terminal.id),
                       A.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR), _source_gap())
    graph = replace(graph, protocol_scopes=(*graph.protocol_scopes, scope),
                    protocol_operations=(*graph.protocol_operations, processing, row))
    require_valid(_core(graph))
    assert "protocol_adapter_source" in _codes(graph)

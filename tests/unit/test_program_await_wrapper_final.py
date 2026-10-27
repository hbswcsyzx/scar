"""Native Create/W/getter/body/own-results form one canonical final chain."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.control import ExceptionPacketDefinition
from scar.ir.program.drivers import BodyResume, BodyStart
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, CompletionSuccessor, ExitKind,
    InvokeLiteralResult, LiteralOrigin, Operation, OperationResult, ReferenceValue,
    Terminator, TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.protocol_await_records import CoroutineAwaitWrapper, WrapperHeldBody
from scar.ir.program.protocol_await import _result_copy
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import HostTerminal, OwnedUse, ProtocolProfile, OutcomeAdapterRule
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program
from tests.fixtures.program_driver_graphs import _Builder
from tests.fixtures.program_protocol_graphs import _scope


_FLAGS = ("source_runtime_verified", "runtime_identity_verified",
          "value_identity_verified", "transformation_authorized")
_CORNERS = ((True, 1), (True, 2), (False, 1), (False, 2))


def _report(program, details, *, budget=1_048_576):
    require_valid(program)
    return ProgramIndex(program).protocol_obligations(
        details["construction_scope"], budget=budget)["connections"]["families"]["await"]


def _consumer(report, details):
    outcome, = tuple(row for row in report["outcomes"]
        if row["source"] == details["source"]
        and row["advance_operation"] == details["advance_operation"]
        and row["drive_outcome"] == details["drive_outcome"])
    consumer, = tuple(row for row in outcome["consumers"]
        if row["actual"] == details["extract_input"]
        and row["requires_final_extraction"] is True)
    return outcome, consumer


def _result(operation, kind, slot):
    number, = tuple(number for number, edge in enumerate(operation.terminator.successors)
                     if edge.kind is kind)
    return InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(slot))


def _assert_own_slots(program, details, consumer):
    implementation = consumer["implementation"]
    assert implementation is not None
    assert implementation["entry_frame"] == (details["parent_call"].id,)
    frames, path = [], (details["parent_call"].id,)
    for record in details["stage_records"]:
        frames.append(path)
        path = (*path, record["operation"].id)
    primitive, = tuple(stage for stage in implementation["stages"]
        if stage["key"] == (frames[-1], details["primitive"].id))
    assert primitive["expanded"] is False
    assert len(primitive["inputs"]) == 3
    assert primitive["inputs"][0]["actual"] == details["stage_records"][-1]["arguments"][0]
    assert primitive["inputs"][0]["binding"]["match"] is True
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    operations = {operation.id: operation for operation in program.operations}
    expected_outputs = set()
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        leg, = tuple(row for row in primitive["legs"] if row["kind"] is kind)
        assert leg["own_result"] == _result(details["primitive"], kind, 0)
        assert {row["slot"] for row in leg["results"]} == {0, 1, 2}
        for result in leg["results"]:
            slot = result["slot"]
            source = _result(details["primitive"], kind, slot)
            assert result["source"] == source
            paths = tuple(path for path in result["paths"] if path["binding"]["match"] is True)
            assert paths
            interface = _result(details["parent_call"], kind, slot)
            expected_outputs.add(interface)
            caller_edge = details["parent_call"].terminator.successors[interface.edge.successor_index]
            final = operations[blocks[caller_edge.block].operations[-1]]
            target = HostTerminal(final.id) if slot == 0 else OwnedUse(
                final.id, final.terminator.values[slot])
            for path in paths:
                assert path["interface_result"] == interface
                assert len(path["hops"]) == details["depth"]
                current = source
                for hop, number in zip(path["hops"], reversed(range(details["depth"]))):
                    record = details["stage_records"][number]
                    parent = details["parent_call"] if number == 0 else details["stage_records"][number - 1]["operation"]
                    assert hop["frame"] == frames[number]
                    assert getattr(hop["call"], "id", hop["call"]) == parent.id
                    assert hop["source"] == current
                    assert hop["terminal"] == record["terminal_uses"][kind][slot]
                    assert hop["kind"] is kind and hop["slot"] == slot
                    current = _result(parent, kind, slot)
                    assert hop["caller_result"] == current
                    parent_edge = parent.terminator.successors[current.edge.successor_index]
                    position, = tuple(number for number, actual in enumerate(parent_edge.arguments)
                        if type(actual) is CompletionResult and actual.index == slot)
                    assert hop["landing_position"] == position
                    assert hop["binding"]["match"] is True
                assert any(row["target"] == target and row["binding"]["match"] is True
                           for row in path["targets"])
            output, = tuple(row for row in implementation["outputs"] if row["source"] == interface)
            assert output["kind"] is kind and output["slot"] == slot
            assert output["terminals"]
            assert all(row["match"] is True for row in output["terminals"])
    assert {row["source"] for row in implementation["outputs"]} == expected_outputs
    assert implementation["inventory"]["enumerated_outputs"] == 6
    assert implementation["status"] == "PARTIAL"


@pytest.mark.parametrize(("zero_cut", "depth"), _CORNERS,
    ids=("zero-E", "zero-EG", "two-cut-E", "two-cut-EG"))
def test_native_wrapper_source_to_real_body_return_to_every_child_own_slot(zero_cut, depth):
    program, details = await_wrapper_final_program(zero_cut=zero_cut, depth=depth)
    report = _report(program, details)
    assert report["inventory"]["source_count"] == 1
    assert len(report["inventory"]["jobs"]) == len(details["call_rows"])
    assert details["body_definition"].kind is ResumableKind.COROUTINE
    body_scopes = tuple(row for row in program.protocol_scopes
        if row.profile in (ProtocolProfile.COROUTINE_BODY_V1,
                           ProtocolProfile.GENERATOR_COROUTINE_BODY_V1))
    assert len(body_scopes) == (1 if zero_cut else 3)
    assert all(row.profile is ProtocolProfile.COROUTINE_BODY_V1 for row in body_scopes)
    assert all(row.contract.rule is OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION
               for row in details["conversion_rows"])
    assert all(type(row.contract) is CoroutineAwaitWrapper for row in details["constructor_rows"])
    assert details["constructor_rows"][0].contract.expected_body == details["constructor_expected"]
    assert details["constructor_body"].value != details["wrapper_records"][0]["entry"][0]
    caller_blocks = {block.id: block for block in details["caller"].blocks}
    executed = tuple(operation for block, _ in details["caller_path"]
                     for operation in caller_blocks[block].operations)
    assert executed.index(details["constructor"].id) < executed.index(details["calls"][0].id)
    suspends = tuple(operation for operation in program.operations
                     if type(operation.terminator) is SuspendTerminator)
    assert len(suspends) == (0 if zero_cut else 2)
    assert all(row.terminator.flavor is SuspensionFlavor.AWAIT for row in suspends)
    assert type(details["drivers"][0]["drive"].target) is BodyStart
    for ordinal, item in enumerate(details["drivers"]):
        wrapper = item["wrapper"]
        assert item["caller_call"].callee == wrapper["region"].id
        assert wrapper["inner_call"].callee == item["driver_region"].id
        assert wrapper["inner_call"].uses[0].value == wrapper["read_body"]
        assert wrapper["read"].uses[0].value == wrapper["entry"][0]
        assert type(wrapper["projection"]) is WrapperHeldBody
        assert wrapper["projection"].body_result == OperationResult(wrapper["read"].id, 0)
        assert wrapper["projection"].body == OwnedUse(details["constructor"].id,
                                                     details["constructor_body"].id)
        if ordinal:
            target = item["drive"].target
            assert type(target) is BodyResume
            assert target.suspend == details["drivers"][ordinal - 1]["outcome_source"]
    outcome, consumer = _consumer(report, details)
    assert outcome["drive_outcome"] == details["drive_outcome"]
    assert consumer["final_rows"] == details["final_rows"]
    _assert_own_slots(program, details, consumer)
    child_ids = {operation.id for operation in details["stage_operations"]}
    assert not any(row.operation in child_ids for row in program.protocol_operations)
    assert all(report[name] is False for name in _FLAGS)


def test_removing_all_wrapper_links_preserves_constructor_advance_and_final_denominator():
    original, details = await_wrapper_final_program(zero_cut=False, depth=2)
    removed, missing = await_wrapper_final_program(zero_cut=False, depth=2, attach_link=False)
    assert original.operations == removed.operations and original.values == removed.values
    assert original.regions == removed.regions
    before, after = _report(original, details), _report(removed, missing)
    assert after["inventory"]["source_count"] == before["inventory"]["source_count"] == 1
    assert tuple(row["advance"] for row in after["inventory"]["jobs"]) == tuple(
        row["advance"] for row in before["inventory"]["jobs"])
    assert all(row["links"] == () for row in after["inventory"]["jobs"])
    _, consumer = _consumer(after, missing)
    _assert_own_slots(removed, missing, consumer)
    assert after["status"] == "PARTIAL"


def test_prior_child_state_never_covers_the_primitive_current_state_result():
    program, details = await_wrapper_final_program(zero_cut=False, depth=2, stale_child_state=True)
    # First-red showed the original state SSA gate already rejects this exact
    # unsafe Use. It cannot be admitted to a subsequent copy query.
    issues = validate(program)
    expected = {str(details["stage_records"][-1]["terminal_uses"][kind][1].use)
                for kind in (ExitKind.NORMAL, ExitKind.RAISE)}
    assert {issue.code for issue in issues} == {"stale_state"}
    assert {issue.path for issue in issues} == expected
    with pytest.raises(ValueError, match="stale_state"):
        require_valid(program)
    with pytest.raises(ValueError, match="stale_state"):
        ProgramIndex(program)


def test_tiny_budget_keeps_the_wrapper_source_and_unproved_original_jobs():
    program, details = await_wrapper_final_program(zero_cut=False, depth=2)
    require_valid(program)
    report = ProgramIndex(program).protocol_obligations(details["construction_scope"], budget=1)
    await_ = report["connections"]["families"]["await"]
    assert await_["inventory"]["source_count"] == 1
    assert await_["inventory"]["jobs"]
    assert await_["status"] == "PARTIAL"
    assert report["budget"]["used"] <= 1
    assert report["budget"]["truncated"] is True
    assert report["cursor"] is not None or await_["inventory"]["cursor"] is not None
    assert await_["transformation_authorized"] is False


def _driver_packet_delivery(program, details):
    require_valid(program)
    accounting = ValidityBudget(1_048_576)
    context = ConnectionContext(program, index=ProgramIndex(program), budget=accounting)
    driver = details["drivers"][-1]
    terminal = driver["host_terminal"]
    source = OwnedUse(terminal.id, terminal.terminator.values[0])
    target = _result(driver["caller_call"], ExitKind.RAISE, 0)
    report = _result_copy(context, source, target, (target.edge,))
    assert not accounting.truncated and accounting.used <= accounting.limit
    return report


def _assert_completion_consumer_is_unproved(program, details):
    report = _report(program, details)
    outcome, = tuple(row for row in report["outcomes"]
        if row["source"] == details["source"]
        and row["advance_operation"] == details["advance_operation"]
        and row["drive_outcome"] == details["drive_outcome"])
    consumers = tuple(row for row in outcome["consumers"]
        if row["actual"] == details["extract_input"] and row["role"] == "COMPLETION")
    assert consumers
    assert all(row["requires_final_extraction"] is not True for row in consumers)
    assert report["inventory"]["source_count"] == 1
    assert all(report[name] is False for name in _FLAGS)


def test_second_actual_inner_driver_caller_cannot_be_selected_by_the_requested_outer_result():
    program, details = await_wrapper_final_program(zero_cut=True, depth=1)
    original = details["drivers"][-1]["wrapper"]["inner_call"]
    values = {value.id: value for value in program.values}
    uses = {use.id: use for use in original.uses}
    b = _Builder("await.wrapper.final.second.driver.caller",
                 tuple(location.id for location in program.locations))
    entry = b.formals(b.region.value + ".entry", tuple(value_type(values[uses[identity].value])
        for identity in original.invoke_arguments))
    arguments = tuple(replace(uses[identity], id=UseID(b.region.value + f".argument.{slot}"),
        value=formal) for slot, (identity, formal) in enumerate(zip(
            original.invoke_arguments, entry, strict=True)))
    edges = []
    for signature in original.completions:
        label = "normal" if signature.kind is ExitKind.NORMAL else "failure"
        name = b.region.value + "." + label
        landing = b.formals(name, signature.types)
        terminal = b.terminal(name + ".exit", landing, fail=signature.kind is ExitKind.RAISE)
        b.block(name, landing, (terminal,))
        edges.append(CompletionSuccessor(signature.kind, BlockID(name),
            tuple(CompletionResult(slot) for slot in range(len(landing)))))
    call = b.add(b.region.value + ".call", arguments, effects_complete=True,
        callee=original.callee, invoke_arguments=tuple(use.id for use in arguments),
        completions=original.completions,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    b.block(b.region.value + ".entry", entry, (call,))
    region = b.finish(b.region.value + ".entry", parent=program.root)
    region = replace(region, exits=tuple(exit_ for exit_ in region.exits
        if any(signature.kind is exit_.kind for signature in original.completions)))
    changed = replace(program, regions=(*program.regions, region),
        operations=(*program.operations, *b.operations), values=(*program.values, *b.values),
        control_scopes=(*program.control_scopes, _scope(region.id, region.blocks)))
    require_valid(changed)
    assert {operation.id for operation in changed.operations if operation.callee == original.callee} == {
        original.id, call.id}
    delivery = _driver_packet_delivery(changed, details)
    assert delivery["match"] is None
    assert "call_return_caller_context_unresolved" in delivery["gaps"]
    _assert_completion_consumer_is_unproved(changed, details)


def test_another_wrapper_terminal_packet_cannot_match_the_driver_packet_result():
    program, details = await_wrapper_final_program(zero_cut=True, depth=1)
    wrapper = details["wrapper_records"][-1]
    terminal = wrapper["terminals"][ExitKind.RAISE]
    payload, = tuple(use for use in terminal.uses if use.id == terminal.terminator.values[0])
    original_value = next(value for value in program.values if value.id == payload.value)
    producer_id = OperationID("await.wrapper.final.other.packet")
    packet = replace(original_value, id=ValueID(producer_id.value + ".value"),
                     origin=OperationResult(producer_id, 0))
    exception_id = OperationID(producer_id.value + ".exception")
    exception = ReferenceValue(ValueID(exception_id.value + ".value"), wrapper["region"].id,
                               OperationResult(exception_id, 0))
    exception_producer = Operation(exception_id, "independent exception Reference",
        (Behavior.COMPUTE,), results=(exception.id,), effects_complete=True)
    traceback = ReferenceValue(ValueID(producer_id.value + ".traceback.none"),
                               wrapper["region"].id, LiteralOrigin(None), targets=())
    packet_inputs = (
        Use(UseID(producer_id.value + ".exception.use"), exception.id, UseRole.REFERENCE),
        Use(UseID(producer_id.value + ".traceback.use"), traceback.id, UseRole.REFERENCE),
    )
    producer = Operation(producer_id, "packet of the independent exception", (Behavior.CONTROL,),
        packet_inputs, (packet.id,), effects_complete=True)
    changed_terminal = replace(terminal, uses=tuple(replace(use, value=packet.id)
        if use.id == payload.id else use for use in terminal.uses))
    region = replace(wrapper["region"], blocks=tuple(replace(block,
        operations=(exception_producer.id, producer.id, *block.operations)) if terminal.id in block.operations
        else block for block in wrapper["region"].blocks))
    changed = replace(program,
        regions=tuple(region if row.id == region.id else row for row in program.regions),
        operations=tuple(changed_terminal if row.id == terminal.id else row
                         for row in program.operations) + (exception_producer, producer),
        values=(*program.values, exception, traceback, packet),
        exception_packets=(*program.exception_packets, ExceptionPacketDefinition(
            packet.id, packet_inputs[0].id, packet_inputs[1].id)))
    require_valid(changed)
    delivery = _driver_packet_delivery(changed, details)
    assert delivery["match"] is False
    assert delivery["routes"]
    final = delivery["routes"][0]["frames"][-1]
    assert final["kind"] is ExitKind.RAISE and final["slot"] == 0
    assert any(item["use"] == OwnedUse(terminal.id, payload.id) and item["copy"] is False
        for projection in final["projection"]
        if projection["kind"] is ExitKind.RAISE and projection["slot"] == 0
        for item in projection["terminals"])
    _assert_completion_consumer_is_unproved(changed, details)

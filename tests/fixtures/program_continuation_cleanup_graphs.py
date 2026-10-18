"""Delegated close across a genuine active cleanup suspension and replacement."""
from dataclasses import replace

from scar.ir.literals import PythonLiteral
from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.literal_sources import UnlocatedLiteral
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, DataValue,
    InvokeLiteralResult, LiteralEvaluation, Operation, OperationResult, ProtocolValue,
    ReferenceValue, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import (
    InjectedPacketTrigger, ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    OperationSiteSubject, OwnedUse, ProtocolCall, ProtocolCallRule,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.resumption import ResumeSlotKind, SavedRole, SuspendTerminator, SuspensionFlavor
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program


def continuation_close_cleanup_program():
    """Return ``(graph, details)``; no Python/native execution is recovered.

    The parent really suspends inside cleanup. Pending reason, context, frame
    and delegate use the original saved recipes. A fresh injected GE packet
    arrives through the real DELEGATE_PACKET slot. Close NORMAL's own None is
    discarded and the old injection continues; close RAISE overrides it. Both
    selected routes merge into one real fresh pending pack and CleanupReplace.
    A separate original category-test branch can suppress another injected
    exception and Resume the older pending return. It supplies a genuine body
    return route; it is not a fabricated NORMAL completion of the close call.
    """
    graph = resumption_cleanup_invoke_program()
    region = graph.regions[0]
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    helper = operations[OperationID("finally.invoke")]
    cut = operations[OperationID("finally.suspend")]
    landing = next(block for block in region.blocks if block.id == BlockID("finally.landing"))
    normal = next(block for block in region.blocks if block.id == helper.terminator.successors[0].block)
    shared = next(block for block in region.blocks if block.id == helper.terminator.successors[1].block)
    injected_value = ValueID("finally.landing.sent")
    old = values[injected_value]
    values[injected_value] = ProtocolValue(old.id, old.region, old.origin, P.EXCEPTION_PACKET)
    successors = tuple(replace(edge, inputs=tuple(replace(slot, kind=ResumeSlotKind.DELEGATE_PACKET)
        if slot.kind is not ResumeSlotKind.STATE else slot for slot in edge.inputs)) for edge in cut.terminator.successors)
    saved = tuple(replace(slot, role=SavedRole.DELEGATE_REFERENCE) if slot.role is SavedRole.VALUE else slot
                  for slot in cut.terminator.saved)
    operations[cut.id] = replace(cut, terminator=replace(cut.terminator,
        flavor=SuspensionFlavor.DELEGATION, successors=successors, saved=saved))

    def role(value):
        return (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
                UseRole.PROTOCOL if isinstance(value, ProtocolValue) else UseRole.REFERENCE)

    def forward(name, actuals, target):
        uses = tuple(Use(UseID(f"{name}.u{index}"), identity, role(values[identity]))
                     for index, identity in enumerate(actuals))
        operation = Operation(OperationID(name), "original selected cleanup transfer", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(target, tuple(use.id for use in uses)),)))
        operations[operation.id] = operation
        return operation

    close_normal_id = BlockID("finally.close.normal")
    close_normal_values = tuple(replace(values[identity], id=ValueID(f"finally.close.normal.v{index}"),
        origin=BlockArgument(close_normal_id, index)) for index, identity in enumerate(normal.arguments))
    values.update((value.id, value) for value in close_normal_values)
    none_value = ReferenceValue(ValueID("finally.close.none"), region.id, BlockArgument(close_normal_id, len(normal.arguments)))
    normal_packet = ProtocolValue(ValueID("finally.close.normal.packet"), region.id,
                                  BlockArgument(close_normal_id, len(normal.arguments) + 1), P.EXCEPTION_PACKET)
    values[none_value.id], values[normal_packet.id] = none_value, normal_packet
    packet_forward = Use(UseID("finally.invoke.normal.injection"), injected_value, UseRole.PROTOCOL)
    normal_edge, failure_edge = helper.terminator.successors
    normal_arguments = tuple(CompletionResult(actual.index + 1) if type(actual) is CompletionResult else actual
                             for actual in normal_edge.arguments)
    normal_edge = replace(normal_edge, block=close_normal_id,
                          arguments=(*normal_arguments, CompletionResult(0), packet_forward.id))
    failure_id = BlockID("finally.close.failure")
    failure_values = tuple(replace(values[identity], id=ValueID(f"finally.close.failure.v{index}"),
        origin=BlockArgument(failure_id, index)) for index, identity in enumerate(shared.arguments))
    values.update((value.id, value) for value in failure_values)
    failure_edge = replace(failure_edge, block=failure_id)
    signatures = tuple(replace(signature, types=(ValueType(ValueKind.REFERENCE), *signature.types))
        if signature.kind.value == "NORMAL" else signature for signature in helper.completions)
    call_block = BlockID("finally.close.call")
    call_state_values = tuple(StateVersionValue(ValueID(f"finally.close.call.state{index}"), region.id,
        BlockArgument(call_block, index), location) for index, location in enumerate(location.id for location in graph.locations))
    values.update((value.id, value) for value in call_state_values)
    call_caller = ProtocolValue(ValueID("finally.close.call.caller"), region.id,
                                BlockArgument(call_block, len(call_state_values)), P.DRIVE_CALLER_CONTEXT)
    values[call_caller.id] = call_caller
    state_replacements = {UseID("finally.invoke.world"): call_state_values[0].id,
                          UseID("finally.invoke.context"): call_state_values[1].id,
                          UseID("finally.invoke.normal.caller"): call_caller.id,
                          UseID("finally.invoke.raise.caller"): call_caller.id}
    helper = replace(helper, uses=tuple(replace(use, value=state_replacements.get(use.id, use.value))
        for use in (*helper.uses, packet_forward)), completions=signatures,
                     terminator=replace(helper.terminator, successors=(normal_edge, failure_edge)))
    operations[helper.id] = helper
    # Shared target formal order is packet,pending,world,caller,saved,context.
    n = tuple(value.id for value in close_normal_values)
    normal_jump = forward("finally.close.normal.to-pending", (normal_packet.id, n[1], n[0], n[2], n[4], n[3]), shared.id)
    failure_jump = forward("finally.close.failure.to-pending", tuple(value.id for value in failure_values), shared.id)
    predicate_id = OperationID("finally.close.category")
    predicate = DataValue(ValueID("finally.close.category.result"), region.id, OperationResult(predicate_id, 0), "builtins.bool")
    values[predicate.id] = predicate
    predicate_use = Use(UseID("finally.close.category.packet"), injected_value, UseRole.PROTOCOL)
    operations[predicate_id] = Operation(predicate_id, "source-relative injected category test", (Behavior.COMPUTE,),
                                         (predicate_use,), (predicate.id,), effects_complete=True)
    current_states = (ValueID("finally.landing.world"), ValueID("finally.landing.attach.after"))
    choose_uses = [Use(UseID("finally.close.choose.condition"), predicate.id, UseRole.DATA)]
    true_uses = tuple(Use(UseID(f"finally.close.choose.true{index}"), value, UseRole.STATE_CONTENT)
                      for index, value in enumerate(current_states))
    true_uses = (*true_uses, Use(UseID("finally.close.choose.true.caller"),
                                ValueID("finally.landing.attach.caller"), UseRole.PROTOCOL))
    false_values = (current_states[0], ValueID("finally.landing.pending"), ValueID("finally.landing.attach.caller"),
                    current_states[1], ValueID("finally.landing.saved-context"))
    false_uses = tuple(Use(UseID(f"finally.close.choose.false{index}"), value, role(values[value]))
                       for index, value in enumerate(false_values))
    choose_uses.extend((*true_uses, *false_uses))
    choose = Operation(OperationID("finally.close.choose"), "original handled-vs-close branch", (Behavior.CONTROL,),
        tuple(choose_uses), terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(call_block, tuple(use.id for use in true_uses)),
            Successor(normal.id, tuple(use.id for use in false_uses))), condition=choose_uses[0].id))
    operations[choose.id] = choose
    blocks = tuple(replace(block, operations=(block.operations[0], predicate_id, choose.id))
        if block.id == landing.id else block for block in region.blocks)
    blocks = (*blocks, Block(failure_id, tuple(value.id for value in failure_values), (failure_jump.id,)),
              Block(close_normal_id, (*n, none_value.id, normal_packet.id), (normal_jump.id,)),
              Block(call_block, (*(value.id for value in call_state_values), call_caller.id), (helper.id,)))
    scopes = tuple(replace(scope, blocks=(*scope.blocks, failure_id, close_normal_id, call_block))
                   if scope.id.value == "finally.cleanup.scope" else scope for scope in graph.control_scopes)
    gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope_id = ProtocolScopeID("finally.close.protocol")
    scope = ProtocolScope(scope_id, ProtocolProfile.DELEGATION_SITE_V1,
                          OperationSiteSubject(region.id, helper.id), gap)
    ports = tuple(InvokeLiteralResult(ControlEdgeReference(helper.id, index), CompletionResult(0)) for index in range(2))
    rows = tuple(ProtocolOperation(scope_id, ProtocolClause.DELEGATE_CLOSE, helper.id, index,
        ProtocolCall(UseID("finally.invoke.x"), (), port,
            (InvokeStateOperand(helper.id, UseID("finally.invoke.world")),
             InvokeStateOperand(helper.id, UseID("finally.invoke.context"))), ProtocolCallRule.DELEGATE_CLOSE), gap)
        for index, port in enumerate(ports))
    inputs = tuple(ProtocolCallInputs(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
        (ProtocolCallInputCase(None, BlockArgument(landing.id, 6), (),
                              InjectedPacketTrigger(BlockArgument(landing.id, 5))),)) for row in rows)
    consumers = (ProtocolResultConsumers(inputs[0].site, ()),
        ProtocolResultConsumers(inputs[1].site,
            (OwnedUse(OperationID("finally.new-raise"), UseID("finally.new-raise.packet")),)))
    graph = replace(graph, regions=(replace(region, blocks=blocks),), operations=tuple(operations.values()),
        values=tuple(values.values()), control_scopes=scopes,
        protocol_scopes=(scope,), protocol_operations=rows, protocol_call_inputs=inputs,
        protocol_result_consumers=consumers,
        literal_evaluations=(LiteralEvaluation(ports[0], PythonLiteral.from_python(None, exact=True),
                                              UnlocatedLiteral("declared native close NORMAL result")),))
    return graph, {"scope": scope_id, "rows": rows, "helper": helper.id,
        "normal_jump": normal_jump.id, "failure_jump": failure_jump.id,
        "pending_pack": OperationID("finally.new-raise"), "shared": shared.id,
        "replacement": OperationID("finally.raise-replace"), "injected": injected_value,
        "raise_packet": failure_values[0].id, "none_result": ports[0]}

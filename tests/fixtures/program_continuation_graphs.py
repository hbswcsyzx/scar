"""Canonical continuation sites; the native protocol interpretation is conditional.

Lookup, invocation, exceptional completion, extraction and the final consumer
are separate original operations.  No parent body ingress is invented for the
delegate-only host route.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, LocationID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, InvokeLiteralResult, LiteralOrigin, Operation,
    OperationResult, ProgramGraph, ProtocolValue, ReferenceValue, Region,
    StateLocation, StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OperationSiteSubject, OutcomeAdapter,
    OutcomeAdapterRule as AR, OwnedUse, ProtocolCall, ProtocolCallRule as CR,
    ProtocolClause as C, ProtocolOperation, ProtocolProfile as F, ProtocolScope,
    StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_protocol_graphs import _scope


REFERENCE = ValueType(ValueKind.REFERENCE)
PACKET = ProtocolValueType(P.EXCEPTION_PACKET)


def _gap():
    return StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)


class _Site:
    def __init__(self):
        self.region = RegionID("continuation")
        self.domain = LocationID("continuation.world")
        self.state_type = ValueType(ValueKind.STATE, location=self.domain)
        self.values, self.operations, self.blocks = [], [], []

    def formal(self, block, index, type_):
        identity = ValueID(f"{block.value}.v{index}")
        origin = BlockArgument(block, index)
        value = (StateVersionValue(identity, self.region, origin, self.domain)
                 if type_ == self.state_type else
                 ProtocolValue(identity, self.region, origin, type_.protocol)
                 if isinstance(type_, ProtocolValueType) else
                 ReferenceValue(identity, self.region, origin))
        self.values.append(value)
        return identity

    def use(self, name, value):
        record = next(item for item in self.values if item.id == value)
        role = (UseRole.STATE_CONTENT if isinstance(record, StateVersionValue) else
                UseRole.PROTOCOL if isinstance(record, ProtocolValue) else UseRole.REFERENCE)
        return Use(UseID(name), value, role)

    def terminal(self, name, block, payload, state, *, raised=False, prefix=()):
        identity = OperationID(name)
        uses = (self.use(name + ".payload", payload), self.use(name + ".state", state))
        operation = Operation(identity, "original terminal", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
                exit="failure" if raised else "normal", values=tuple(use.id for use in uses)))
        self.operations.append(operation)
        arguments = tuple(value.id for value in self.values if value.origin == BlockArgument(block, 0)
                          or isinstance(value.origin, BlockArgument) and value.origin.block == block)
        self.blocks.append(Block(block, arguments, (*prefix, identity)))
        return operation

    def invoke(self, name, block, receiver, arguments, state, *, prefix=()):
        identity = OperationID(name)
        normal, failure = BlockID(name + ".n"), BlockID(name + ".r")
        normal_values = (self.formal(normal, 0, REFERENCE), self.formal(normal, 1, self.state_type))
        failure_values = (self.formal(failure, 0, PACKET), self.formal(failure, 1, self.state_type))
        actuals = tuple(self.use(f"{name}.a{index}", value)
                        for index, value in enumerate((receiver, *arguments, state)))
        operation = Operation(identity, "original callable boundary", (Behavior.CONTROL,), actuals,
            effects_complete=False, invoke_arguments=tuple(use.id for use in actuals),
            completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, self.state_type)),
                         CompletionSignature(ExitKind.RAISE, (PACKET, self.state_type))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, normal, (CompletionResult(0), CompletionResult(1))),
                CompletionSuccessor(ExitKind.RAISE, failure, (CompletionResult(0), CompletionResult(1))))))
        self.operations.append(operation)
        block_arguments = tuple(value.id for value in self.values
            if isinstance(value.origin, BlockArgument) and value.origin.block == block)
        self.blocks.append(Block(block, block_arguments, (*prefix, identity)))
        return {"operation": operation, "normal": normal, "failure": failure,
                "normal_values": normal_values, "failure_values": failure_values,
                "receiver": actuals[0].id, "arguments": tuple(use.id for use in actuals[1:-1]),
                "state_sites": (InvokeStateOperand(identity, actuals[-1].id),),
                "ports": tuple(InvokeLiteralResult(ControlEdgeReference(identity, index), CompletionResult(0))
                               for index in range(2))}


def continuation_site_program(*, kind="delegate", request="next", throw_arity=3,
                              exhaustion=True, initial=False):
    """Return ``(graph, details)`` for real lookup/call and item/exhaustion paths.

    ``kind`` is delegate, await, or wrapper.  Await and wrapper preserve their
    NORMAL iterator result and use a separate delegation scope to advance it.
    THROW's one to three actual arguments retain their original raw ordinals.
    ``initial`` uses the exact just-evaluated iterator without a fake request.
    All INVOKEs retain their real N/R successors and fresh current state.
    """
    if kind not in ("delegate", "await", "wrapper"):
        raise ValueError("unknown continuation fixture kind")
    request_kind = RawRequestKind(request.upper())
    count = {RawRequestKind.NEXT: 0, RawRequestKind.SEND: 1,
             RawRequestKind.THROW: throw_arity, RawRequestKind.CLOSE: 0}[request_kind]
    b = _Site()
    entry = BlockID("continuation.entry")
    root_inputs = tuple(b.formal(entry, index, REFERENCE) for index in range(5))
    initial_state = b.formal(entry, 5, b.state_type)
    raw_operation = OperationID("continuation.pack")
    raw = ProtocolValue(ValueID("continuation.raw"), b.region,
                        OperationResult(raw_operation, 0), P.RAW_DRIVER_REQUEST)
    b.values.append(raw)
    pack_uses = tuple(b.use(f"continuation.pack.u{index}", value)
                      for index, value in enumerate(root_inputs[2:2 + count]))
    pack = Operation(raw_operation, "abstract original request pack", (Behavior.REPRESENT,),
                     pack_uses, (raw.id,), effects_complete=True)
    b.operations.append(pack)
    lookup = b.invoke("continuation.lookup", entry, root_inputs[0], (), initial_state, prefix=(pack.id,))
    lookup_failure = b.terminal("continuation.lookup.error", lookup["failure"],
                               *lookup["failure_values"], raised=True)
    lookup_scope = ProtocolScopeID("continuation.lookup.scope")
    delegate_scope = ProtocolScopeID("continuation.delegate.scope")
    if kind == "delegate":
        profile, lookup_clause, lookup_rule = F.DELEGATION_SITE_V1, C.DELEGATE_ITER_LOOKUP, CR.DELEGATE_ITER
        lookup_scope = delegate_scope
    else:
        profile = F.AWAIT_SITE_V1 if kind == "await" else F.COROUTINE_AWAIT_WRAPPER_V1
        lookup_clause = C.AWAIT_LOOKUP if kind == "await" else C.WRAPPER_LOOKUP
        lookup_rule = CR.AWAIT_LOOKUP
    scopes = [ProtocolScope(lookup_scope, profile, OperationSiteSubject(b.region, lookup["operation"].id), _gap())]
    rows = []

    def call_rows(view, scope, clause, rule):
        records = tuple(ProtocolOperation(scope, clause, view["operation"].id, index,
            ProtocolCall(view["receiver"], view["arguments"], port, view["state_sites"], rule), _gap())
            for index, port in enumerate(view["ports"]))
        rows.extend(records)
        return records

    lookup_rows = call_rows(lookup, lookup_scope, lookup_clause, lookup_rule)
    iterator_row = lookup_rows[0]
    iterator_value, iterator_state = lookup["normal_values"]
    iterator_block = lookup["normal"]
    await_call, await_failure = None, None
    if kind != "delegate":
        await_call = b.invoke("continuation.await.call", iterator_block, iterator_value, (), iterator_state)
        await_failure = b.terminal("continuation.await.call.error", await_call["failure"],
                                  *await_call["failure_values"], raised=True)
        call_clause = C.AWAIT_CALL if kind == "await" else C.WRAPPER_CALL
        call_records = call_rows(await_call, lookup_scope, call_clause, CR.AWAIT_CALL)
        iterator_row = call_records[0]
        iterator_value, iterator_state = await_call["normal_values"]
        iterator_block = await_call["normal"]
        scopes.append(ProtocolScope(delegate_scope, F.DELEGATION_SITE_V1,
            OperationSiteSubject(b.region, OperationID("continuation.advance")), _gap()))
    trigger_use = b.use("continuation.trigger.raw", raw.id)
    marker = Operation(OperationID("continuation.trigger"), "original request observation",
                       (Behavior.COMPUTE,), (trigger_use,), effects_complete=True)
    b.operations.append(marker)
    advance = b.invoke("continuation.advance", iterator_block, iterator_value,
                      root_inputs[2:2 + count], iterator_state, prefix=(marker.id,))
    advance_clause = {RawRequestKind.NEXT: C.DELEGATE_ADVANCE, RawRequestKind.SEND: C.DELEGATE_ADVANCE,
                      RawRequestKind.THROW: C.DELEGATE_THROW, RawRequestKind.CLOSE: C.DELEGATE_CLOSE}[request_kind]
    advance_rule = {RawRequestKind.NEXT: CR.DELEGATE_NEXT, RawRequestKind.SEND: CR.DELEGATE_SEND,
                    RawRequestKind.THROW: CR.DELEGATE_THROW, RawRequestKind.CLOSE: CR.DELEGATE_CLOSE}[request_kind]
    advance_rows = call_rows(advance, delegate_scope, advance_clause, advance_rule)
    item_exit = b.terminal("continuation.item", advance["normal"], *advance["normal_values"])
    item_row = ProtocolOperation(delegate_scope, C.DELEGATE_PARENT_OR_HOST_RESULT, item_exit.id, 0,
        OutcomeAdapter(ContractResult(delegate_scope, advance_clause, advance["operation"].id, 0,
                                      advance["ports"][0]), item_exit.uses[0].id,
                       HostTerminal(item_exit.id), AR.DELEGATE_ONLY_HOST_ITEM), _gap())
    rows.append(item_row)
    extraction, extraction_rows, await_adapter_rows, value_exit = None, (), (), None
    if exhaustion:
        extraction = b.invoke("continuation.extract", advance["failure"],
                              advance["failure_values"][0], (), advance["failure_values"][1])
        value_exit = b.terminal("continuation.value", extraction["normal"], *extraction["normal_values"])
        error_exit = b.terminal("continuation.extract.error", extraction["failure"],
                               *extraction["failure_values"], raised=True)
        extraction_rows = tuple(ProtocolOperation(delegate_scope, C.DELEGATE_PARENT_OR_HOST_RESULT,
            extraction["operation"].id, index,
            OutcomeAdapter(ContractResult(delegate_scope, advance_clause, advance["operation"].id, 1,
                                          advance["ports"][1]), extraction["receiver"], port,
                           AR.DELEGATE_STOPITER_TO_PARENT_VALUE if index == 0 else AR.DELEGATE_ONLY_HOST_EXCEPTION),
            _gap()) for index, port in enumerate(extraction["ports"]))
        rows.extend(extraction_rows)
        if kind != "delegate":
            adapter_clause = C.AWAIT_RESULT_ADAPTER if kind == "await" else C.WRAPPER_RESULT_ROUTE
            await_adapter_rows = tuple(ProtocolOperation(lookup_scope, adapter_clause,
                extraction["operation"].id, index,
                OutcomeAdapter(ContractResult(delegate_scope, advance_clause, advance["operation"].id, 1,
                    advance["ports"][1]), extraction["receiver"], port, AR.AWAIT_STOPITER_TO_EXPRESSION), _gap())
                for index, port in enumerate(extraction["ports"]))
            rows.extend(await_adapter_rows)
    else:
        error_exit = b.terminal("continuation.failure", advance["failure"],
                               *advance["failure_values"], raised=True)
        rows.append(ProtocolOperation(delegate_scope, C.DELEGATE_PARENT_OR_HOST_RESULT, error_exit.id, 0,
            OutcomeAdapter(ContractResult(delegate_scope, advance_clause, advance["operation"].id, 1,
                                          advance["ports"][1]), error_exit.uses[0].id,
                           HostTerminal(error_exit.id), AR.DELEGATE_ONLY_HOST_EXCEPTION), _gap()))
    region = Region(b.region, "declared original continuation boundary", entry, tuple(b.blocks),
        (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, b.state_type)),
         ExitPort("failure", ExitKind.RAISE, (PACKET, b.state_type))))
    graph = ProgramGraph(b.region, (region,), tuple(b.operations), tuple(b.values),
        locations=(StateLocation(b.domain, "shared canonical world"),),
        control_scopes=(_scope(b.region, b.blocks),),
        raw_driver_requests=(RawRequestDefinition(raw.id, request_kind, tuple(use.id for use in pack_uses)),),
        protocol_scopes=tuple(scopes), protocol_operations=tuple(rows))
    details = {"kind": kind, "scope": delegate_scope, "lookup_scope": lookup_scope,
        "lookup": lookup, "lookup_rows": lookup_rows, "await_call": await_call,
        "lookup_failure": lookup_failure, "await_failure": await_failure,
        "iterator_row": iterator_row, "advance": advance, "advance_rows": advance_rows,
        "item_row": item_row, "item_exit": item_exit, "error_exit": error_exit,
        "extraction": extraction, "extraction_rows": extraction_rows, "value_exit": value_exit,
        "await_adapter_rows": await_adapter_rows,
        "raw": OwnedUse(marker.id, trigger_use.id), "root_inputs": root_inputs,
        "initial": initial, "request_kind": request_kind}
    return graph, details


def with_continuation_connections(graph, details):
    """Attach the P4 expected sources without altering any canonical operation."""
    from scar.ir.program.protocol_connections import (
        InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
        ProtocolResultConsumers, RawOperandSource, RawRequestTrigger,
    )

    def site(row):
        return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)

    def source(row):
        return ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)

    inputs, consumers = [], []
    for row in details["lookup_rows"]:
        inputs.append(ProtocolCallInputs(site(row), (ProtocolCallInputCase(None,
            BlockArgument(BlockID("continuation.entry"), 0), (), None),)))
    consumers.append(ProtocolResultConsumers(site(details["lookup_rows"][1]),
        (HostTerminal(details["lookup_failure"].id),)))
    if details["await_call"] is not None:
        records = [row for row in graph.protocol_operations
                   if row.operation == details["await_call"]["operation"].id]
        for row in records:
            inputs.append(ProtocolCallInputs(site(row), (ProtocolCallInputCase(None,
                source(details["lookup_rows"][0]), (), None),)))
        consumers.append(ProtocolResultConsumers(site(details["lookup_rows"][0]),
            (OwnedUse(records[0].operation, records[0].contract.receiver_use),)))
        consumers.append(ProtocolResultConsumers(site(records[1]), (HostTerminal(details["await_failure"].id),)))
    for row in details["advance_rows"]:
        trigger = InitialAdvance(source(details["iterator_row"])) if details["initial"] else RawRequestTrigger(details["raw"])
        inputs.append(ProtocolCallInputs(site(row), (ProtocolCallInputCase(None,
            source(details["iterator_row"]), tuple(RawOperandSource(details["raw"], ordinal)
                for ordinal in range(len(row.contract.argument_uses))), trigger),)))
    consumers.append(ProtocolResultConsumers(site(details["iterator_row"]),
        (OwnedUse(details["advance_rows"][0].operation, details["advance_rows"][0].contract.receiver_use),)))
    consumers.append(ProtocolResultConsumers(site(details["advance_rows"][0]),
        () if details["request_kind"] is RawRequestKind.CLOSE else (HostTerminal(details["item_exit"].id),)))
    consumers.append(ProtocolResultConsumers(site(details["advance_rows"][1]),
        (OwnedUse(details["extraction"]["operation"].id, details["extraction"]["receiver"]),)
        if details["extraction"] is not None else (HostTerminal(details["error_exit"].id),)))
    if details["extraction"] is not None:
        for records in (details["extraction_rows"], details["await_adapter_rows"]):
            for row, terminal in zip(records, (details["value_exit"], details["error_exit"])):
                consumers.append(ProtocolResultConsumers(site(row), (HostTerminal(terminal.id),)))
    return replace(graph, protocol_call_inputs=tuple(inputs), protocol_result_consumers=tuple(consumers)), details


def continuation_parent_program(*, slot="DELEGATE_VALUE", flavor="DELEGATION", cleanup=False):
    """A processed result enters the real parent slot with current state.

    The cleanup variant preserves its existing pending/context/frame saved
    recipes and post-resume INVOKE NORMAL/RAISE cleanup routes. The new rows
    select the actual slot instead of deducing its role from AWAIT flavor.
    """
    from scar.ir.program.protocol_connections import ResumeSourceBinding
    from scar.ir.program.protocols import DriverSubject, RequestProcessing, RequestProcessingRule
    from scar.ir.program.resumption import ResumableKind, ResumeSlotKind, SuspendTerminator, SuspensionFlavor
    from tests.fixtures.program_driver_graphs import driver_program
    from tests.fixtures.program_protocol_graphs import _adapt_return, _insert_processing
    from tests.fixtures.program_resumption_graphs import resumption_program, resumption_cleanup_invoke_program

    requested = ResumeSlotKind(slot)
    packet = requested in (ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET)
    body = resumption_cleanup_invoke_program() if cleanup else resumption_program()
    operations = []
    for operation in body.operations:
        term = operation.terminator
        if type(term) is SuspendTerminator:
            successors = tuple(replace(edge, inputs=tuple(
                replace(port, kind=requested) if port.kind is not ResumeSlotKind.STATE
                and (port.kind in (ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET)) == packet
                else port for port in edge.inputs)) for edge in term.successors)
            operation = replace(operation, terminator=replace(term, flavor=SuspensionFlavor(flavor), successors=successors))
        operations.append(operation)
    body = replace(body, operations=tuple(operations), resumable_bodies=tuple(
        replace(record, kind=ResumableKind.COROUTINE if flavor == "AWAIT" else ResumableKind.GENERATOR)
        for record in body.resumable_bodies))
    target = "packet" if packet else "value"
    graph = driver_program(target=target, body_graph=body)
    graph, processing = _insert_processing(graph, target=target)
    drive, = graph.body_drives
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID("parent.continuation.scope"),
        F.COROUTINE_BODY_V1 if flavor == "AWAIT" else F.GENERATOR_BODY_V1,
        DriverSubject(interface.region), _gap())
    selected = drive.resume_inputs[0]
    source = ContractResult(scope.id, C.REQUEST_PROCESSING, processing["processing"], 0,
                            processing["normal_result"])
    processing_rows = tuple(ProtocolOperation(scope.id, C.REQUEST_PROCESSING, processing["processing"], number,
        RequestProcessing(processing["raw_use"], (), processing[name], processing["state_sites"],
            RequestProcessingRule.NORMALIZE_THROW_INSTANCE if packet else RequestProcessingRule.CHECK_SEND), _gap())
        for number, name in enumerate(("normal_result", "raise_result")))
    binding = ProtocolOperation(scope.id, C.BODY_INGRESS, drive.operation, selected.slot,
                                ResumeSourceBinding(source), _gap())
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=(*processing_rows, binding))
    drive_operation = next(operation for operation in graph.operations if operation.id == drive.operation)
    return_edges = tuple(edge for edge in drive_operation.terminator.successors
        if next(operation for operation in graph.operations if operation.id == edge.source).terminator.kind
        is TerminatorKind.RETURN)
    if return_edges:
        # Adapt the genuine Return edge while retaining the other actual body
        # sources. This temporary projection is never validated or returned.
        projected = replace(graph, operations=tuple(replace(operation,
            terminator=replace(operation.terminator, successors=return_edges))
            if operation.id == drive.operation else operation for operation in graph.operations))
        graph = _adapt_return(projected, scope.id)
        graph = replace(graph, operations=tuple(drive_operation if operation.id == drive.operation else operation
            for operation in graph.operations))
        if flavor == "AWAIT":
            graph = replace(graph, protocol_operations=tuple(replace(row, clause=C.AWAIT_COMPLETION_ADAPTER,
                contract=replace(row.contract, rule=AR.COROUTINE_RETURN_TO_STOP_ITERATION))
                if type(row.contract) is OutcomeAdapter and row.contract.rule is AR.GENERATOR_RETURN_TO_STOP_ITERATION
                else row for row in graph.protocol_operations))
    return graph, {"scope": scope.id, "row": binding, "drive": drive,
        "slot": requested, "processing": processing, "source": source,
        "cleanup": cleanup, "saved": tuple((operation.id, operation.terminator.saved)
            for operation in body.operations if type(operation.terminator) is SuspendTerminator)}


def continuation_initial_loop_program():
    """The same iterator is advanced again on a real CFG backedge.

    Its receiver still copies the exact lookup result. Only the false assertion
    that every visit is an InitialAdvance is wrong; no invalid SSA/FK is used.
    """
    graph, details = with_continuation_connections(*continuation_site_program(initial=True))
    header, exit_block = BlockID("continuation.loop"), BlockID("continuation.loop.exit")
    iterator = ReferenceValue(ValueID("continuation.loop.iterator"), graph.root, BlockArgument(header, 0))
    state = StateVersionValue(ValueID("continuation.loop.state"), graph.root, BlockArgument(header, 1), graph.locations[0].id)
    item = ReferenceValue(ValueID("continuation.loop.item"), graph.root, BlockArgument(exit_block, 0))
    last_state = StateVersionValue(ValueID("continuation.loop.final.state"), graph.root,
                                  BlockArgument(exit_block, 1), graph.locations[0].id)
    condition = DataValue(ValueID("continuation.loop.again"), graph.root, LiteralOrigin(True), "builtins.bool")
    lookup = details["lookup"]
    advance = details["advance"]["operation"]
    old_item = details["item_exit"]
    forwarding = (Use(UseID("continuation.to.loop.iterator"), lookup["normal_values"][0], UseRole.REFERENCE),
                  Use(UseID("continuation.to.loop.state"), lookup["normal_values"][1], UseRole.STATE_CONTENT))
    jump = Operation(OperationID("continuation.to.loop"), "ordinary initial copy", (Behavior.CONTROL,), forwarding,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(header, tuple(use.id for use in forwarding)),)))
    values = {lookup["normal_values"][0]: iterator.id, lookup["normal_values"][1]: state.id}
    new_advance = replace(advance, uses=tuple(replace(use, value=values.get(use.value, use.value)) for use in advance.uses))
    branch_uses = (
        Use(UseID("continuation.loop.condition"), condition.id, UseRole.DATA),
        Use(UseID("continuation.loop.back.iterator"), iterator.id, UseRole.REFERENCE),
        Use(UseID("continuation.loop.back.state"), details["advance"]["normal_values"][1], UseRole.STATE_CONTENT),
        Use(UseID("continuation.loop.out.item"), details["advance"]["normal_values"][0], UseRole.REFERENCE),
        Use(UseID("continuation.loop.out.state"), details["advance"]["normal_values"][1], UseRole.STATE_CONTENT))
    branch = replace(old_item, uses=branch_uses, terminator=Terminator(TerminatorKind.BRANCH, (
        Successor(header, (branch_uses[1].id, branch_uses[2].id)),
        Successor(exit_block, (branch_uses[3].id, branch_uses[4].id))), condition=branch_uses[0].id))
    terminal_uses = (Use(UseID("continuation.loop.exit.item"), item.id, UseRole.REFERENCE),
                     Use(UseID("continuation.loop.exit.state"), last_state.id, UseRole.STATE_CONTENT))
    terminal = Operation(OperationID("continuation.loop.exit"), "actual item sink", (Behavior.CONTROL,), terminal_uses,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(use.id for use in terminal_uses)))
    old_normal = next(block for block in graph.regions[0].blocks if block.id == lookup["normal"])
    blocks = tuple(replace(block, operations=(jump.id,)) if block.id == old_normal.id else block
                   for block in graph.regions[0].blocks)
    blocks = (*blocks, Block(header, (iterator.id, state.id), old_normal.operations),
              Block(exit_block, (item.id, last_state.id), (terminal.id,)))
    item_row = replace(details["item_row"], operation=terminal.id,
        contract=replace(details["item_row"].contract, input_use=terminal_uses[0].id, output=HostTerminal(terminal.id)))
    graph = replace(graph, regions=(replace(graph.regions[0], blocks=blocks),),
        operations=tuple(new_advance if operation.id == advance.id else branch if operation.id == old_item.id else operation
                         for operation in graph.operations) + (jump, terminal),
        values=(*graph.values, iterator, state, item, last_state, condition),
        protocol_operations=tuple(item_row if row == details["item_row"] else row for row in graph.protocol_operations),
        protocol_result_consumers=tuple(replace(row, targets=tuple(HostTerminal(terminal.id)
            if type(target) is HostTerminal and target.operation == old_item.id else target
            for target in row.targets)) for row in graph.protocol_result_consumers),
        control_scopes=(_scope(graph.root, blocks),))
    return graph, {**details, "header": header, "terminal": terminal}


def continuation_close_program(*, kind="delegate", parent=False):
    """Close NORMAL continues the injected packet; RAISE supplies a new one.

    The injected packet is an explicit original entry boundary, not a claim
    that an arbitrary class is GeneratorExit. Its category remains conditional.
    ``parent`` is reserved for the separately constructed real resume fixture.
    """
    if parent:
        raise ValueError("use continuation_parent_program for a real body ingress")
    from scar.ir.literals import PythonLiteral
    from scar.ir.program.literal_sources import UnlocatedLiteral
    from scar.ir.program.model import LiteralEvaluation
    from scar.ir.program.protocol_connections import InjectedPacketTrigger

    graph, details = with_continuation_connections(*continuation_site_program(kind=kind, request="close", exhaustion=False))
    entry = graph.regions[0].entry
    arguments = next(block.arguments for block in graph.regions[0].blocks if block.id == entry)
    packet = ProtocolValue(ValueID("continuation.current.injection"), graph.root,
                           BlockArgument(entry, len(arguments)), P.EXCEPTION_PACKET)
    old = details["item_exit"]
    current = Use(UseID("continuation.close.continue.packet"), packet.id, UseRole.PROTOCOL)
    terminal = replace(old, uses=(current, old.uses[1]), terminator=Terminator(
        TerminatorKind.RAISE, exit="failure", values=(current.id, old.uses[1].id)))
    blocks = tuple(replace(block, arguments=(*block.arguments, packet.id)) if block.id == entry else block
                   for block in graph.regions[0].blocks)
    graph = replace(graph, regions=(replace(graph.regions[0], blocks=blocks,
        exits=tuple(port for port in graph.regions[0].exits if port.kind is ExitKind.RAISE)),), values=(*graph.values, packet),
        operations=tuple(terminal if operation.id == terminal.id else operation for operation in graph.operations),
        protocol_operations=tuple(row for row in graph.protocol_operations if row != details["item_row"]),
        protocol_call_inputs=tuple(replace(declaration, cases=tuple(replace(case,
            trigger=InjectedPacketTrigger(BlockArgument(entry, len(arguments)))) for case in declaration.cases))
            if declaration.site.operation == details["advance"]["operation"].id else declaration
            for declaration in graph.protocol_call_inputs),
        literal_evaluations=(LiteralEvaluation(details["advance"]["ports"][0], PythonLiteral.from_python(None, exact=True),
                                                UnlocatedLiteral("declared close helper None result")),))
    return graph, {**details, "item_exit": terminal, "injected_packet": packet,
                   "normal_terminal": terminal, "raise_terminal": details["error_exit"]}


def continuation_paired_program(*, crossed=False, omitted=False):
    """Two real lookup/request tuples merge upstream of the SEND call.

    Guards select the original merge predecessors, followed by a separate
    ordinary copy/JUMP into the call. RAW is never added to the helper actuals.
    ``crossed`` changes only an expected same-type raw source in one case.
    """
    from scar.ir.program.protocol_connections import (
        ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
        ProtocolResultConsumers, RawOperandSource, RawRequestTrigger,
    )
    b = _Site()
    entry = BlockID("paired.entry")
    source_a, source_b, arg_a, arg_b = tuple(b.formal(entry, index, REFERENCE) for index in range(4))
    state = b.formal(entry, 4, b.state_type)
    condition = DataValue(ValueID("paired.condition"), b.region, BlockArgument(entry, 5), "builtins.bool")
    b.values.append(condition)
    branch_uses = (Use(UseID("paired.choose.condition"), condition.id, UseRole.DATA),
                  b.use("paired.choose.a", state), b.use("paired.choose.b", state))
    choose = Operation(OperationID("paired.choose"), "original alternative evaluation", (Behavior.CONTROL,), branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID("paired.a"), (branch_uses[1].id,)),
            Successor(BlockID("paired.b"), (branch_uses[2].id,))), condition=branch_uses[0].id))
    b.operations.append(choose)
    b.blocks.append(Block(entry, (source_a, source_b, arg_a, arg_b, state, condition.id), (choose.id,)))
    scope_id = ProtocolScopeID("paired.scope")
    merge, call_block = BlockID("paired.merge"), BlockID("paired.call")
    merge_values = tuple(b.formal(merge, index, type_) for index, type_ in enumerate((REFERENCE, REFERENCE, b.state_type)))
    call_values = tuple(b.formal(call_block, index, type_) for index, type_ in enumerate((REFERENCE, REFERENCE, b.state_type)))
    rows, attachments, consumers, sources, triggers, guards = [], [], [], [], [], []

    def site(row):
        return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)

    for label, root, argument in (("a", source_a, arg_a), ("b", source_b, arg_b)):
        block = BlockID("paired." + label)
        incoming_state = b.formal(block, 0, b.state_type)
        lookup = b.invoke("paired.lookup." + label, block, root, (), incoming_state)
        b.terminal("paired.lookup." + label + ".error", lookup["failure"], *lookup["failure_values"], raised=True)
        selected_rows = tuple(ProtocolOperation(scope_id, C.DELEGATE_ITER_LOOKUP, lookup["operation"].id, number,
            ProtocolCall(lookup["receiver"], (), port, lookup["state_sites"], CR.DELEGATE_ITER), _gap())
            for number, port in enumerate(lookup["ports"]))
        rows.extend(selected_rows)
        for row in selected_rows:
            attachments.append(ProtocolCallInputs(site(row), (ProtocolCallInputCase(None,
                BlockArgument(entry, 0 if label == "a" else 1), (), None),)))
        iterator = ContractResult(scope_id, C.DELEGATE_ITER_LOOKUP, lookup["operation"].id, 0, lookup["ports"][0])
        sources.append(iterator)
        raw_op = OperationID("paired.pack." + label)
        raw_value = ProtocolValue(ValueID("paired.raw." + label), b.region, OperationResult(raw_op, 0), P.RAW_DRIVER_REQUEST)
        b.values.append(raw_value)
        operand = b.use("paired.pack." + label + ".argument", argument)
        pack = Operation(raw_op, "original branch request", (Behavior.REPRESENT,), (operand,), (raw_value.id,), effects_complete=True)
        b.operations.append(pack)
        observation = b.use("paired.observe." + label + ".raw", raw_value.id)
        marker = Operation(OperationID("paired.observe." + label), "original branch raw anchor", (Behavior.COMPUTE,),
                           (observation,), effects_complete=True)
        b.operations.append(marker)
        raw_ref = OwnedUse(marker.id, observation.id)
        triggers.append(raw_ref)
        forwarding = (b.use("paired.merge." + label + ".receiver", lookup["normal_values"][0]),
                      b.use("paired.merge." + label + ".argument", argument),
                      b.use("paired.merge." + label + ".state", lookup["normal_values"][1]))
        jump = Operation(OperationID("paired.merge." + label), "exact original merge edge", (Behavior.CONTROL,), forwarding,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(merge, tuple(use.id for use in forwarding)),)))
        b.operations.append(jump)
        b.blocks.append(Block(lookup["normal"], lookup["normal_values"], (pack.id, marker.id, jump.id)))
        guards.append(ControlEdgeReference(jump.id, 0))
    copied = tuple(b.use(f"paired.to.call.u{index}", value) for index, value in enumerate(merge_values))
    to_call = Operation(OperationID("paired.to.call"), "separate post-merge copy", (Behavior.CONTROL,), copied,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(call_block, tuple(use.id for use in copied)),)))
    b.operations.append(to_call)
    b.blocks.append(Block(merge, merge_values, (to_call.id,)))
    call = b.invoke("paired.send", call_block, call_values[0], (call_values[1],), call_values[2])
    b.terminal("paired.item", call["normal"], *call["normal_values"])
    b.terminal("paired.failure", call["failure"], *call["failure_values"], raised=True)
    send_rows = tuple(ProtocolOperation(scope_id, C.DELEGATE_ADVANCE, call["operation"].id, number,
        ProtocolCall(call["receiver"], call["arguments"], port, call["state_sites"], CR.DELEGATE_SEND), _gap())
        for number, port in enumerate(call["ports"]))
    rows.extend(send_rows)
    for row in send_rows:
        cases = tuple(ProtocolCallInputCase(guard, receiver,
            (RawOperandSource(triggers[1 - index] if crossed and index == 0 else triggers[index], 0),),
            RawRequestTrigger(triggers[index])) for index, (guard, receiver) in enumerate(zip(guards, sources)))
        attachments.append(ProtocolCallInputs(site(row), cases[:1] if omitted else cases))
    for row in rows:
        if row.operation in (source.operation for source in sources) and row.slot == 0:
            consumers.append(ProtocolResultConsumers(site(row), (OwnedUse(call["operation"].id, call["receiver"]),)))
    region = Region(b.region, "original correlated continuation branches", entry, tuple(b.blocks), (
        ExitPort("normal", ExitKind.NORMAL, (REFERENCE, b.state_type)),
        ExitPort("failure", ExitKind.RAISE, (PACKET, b.state_type))))
    raw_records = tuple(RawRequestDefinition(value.id, RawRequestKind.SEND,
        (UseID("paired.pack." + label + ".argument"),)) for label in ("a", "b")
        for value in b.values if value.id == ValueID("paired.raw." + label))
    graph = ProgramGraph(b.region, (region,), tuple(b.operations), tuple(b.values),
        locations=(StateLocation(b.domain, "shared canonical world"),), control_scopes=(_scope(b.region, b.blocks),),
        raw_driver_requests=raw_records, protocol_scopes=(ProtocolScope(scope_id, F.DELEGATION_SITE_V1,
            OperationSiteSubject(b.region, choose.id), _gap()),), protocol_operations=tuple(rows),
        protocol_call_inputs=tuple(attachments), protocol_result_consumers=tuple(consumers))
    return graph, {"scope": scope_id, "send_rows": send_rows, "sources": tuple(sources),
                   "triggers": tuple(triggers), "guards": tuple(guards), "merge": merge,
                   "call": call, "consumers": tuple(consumers)}

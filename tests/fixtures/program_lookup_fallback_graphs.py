"""Three independent packet routes over the original delegate lookup graph.

The injected whole packet is an explicit input boundary.  For THROW its
relationship to the raw normalization remains a declared, unproved source
obligation.  The fixture does not infer that relationship from the true exit.
"""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.exception_matches import (
    BuiltinExceptionCategory, ExceptionHandlerOperand, ExceptionMatcher, FixedBuiltinHandler,
)
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, InvokeLiteralResult, Operation,
    OperationResult, ProtocolValue, ReferenceValue, StateAccess, StateVersionValue,
    Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import (
    DelegateLookupFallback, InjectedPacketTrigger, NormalizedThrowSource, ProtocolOperationRef,
)
from scar.ir.program.protocols import ContractResult, OwnedUse, StaticGapReason, StaticProtocolGap
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_method_lookup_graphs import method_lookup_program


def lookup_fallback_program(*, kind="close", matcher="ordinary", throw_arity=1, attach=True,
                            two_lookups=False):
    """Return ``(graph, details)`` without changing an existing fixture.

    All original method NORMAL paths and ordered THROW arguments remain.
    EL is the method lookup's own RAISE, E0 an independent entry packet, and
    EM the matcher's own RAISE.  Dynamic N/R edges are deliberately R first;
    bool is completion slot 1 and landing formal 2, not successor index 0.
    """
    if kind not in ("throw", "close") or matcher not in ("ordinary", "invoke", "raise-only"):
        raise ValueError("unsupported lookup fallback fixture")
    if type(throw_arity) is not int or throw_arity not in (1, 2, 3):
        raise ValueError("THROW fixture arity must be one to three")
    graph, prior = method_lookup_program(request=kind, throw_arity=throw_arity, two_lookups=two_lookups)
    region, = graph.regions
    entry = next(block for block in region.blocks if block.id == region.entry)
    lookup_row = prior["method_rows"][1]
    lookup = ProtocolOperationRef(lookup_row.scope, lookup_row.clause,
                                  lookup_row.operation, lookup_row.slot)
    old_exit = prior["method_failure"]
    by_value = {value.id: value for value in graph.values}
    el, before = (by_value[identity] for identity in prior["method"]["failure_values"])
    state_type = ValueType(ValueKind.STATE, location=before.location)
    bool_type = ValueType(ValueKind.DATA, "builtins.bool")
    packet_type = next(signature.types[0] for signature in prior["method"]["operation"].completions
                       if signature.kind is ExitKind.RAISE)
    added_values, operations, blocks = [], [], []

    def use(name, value):
        role = (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
                UseRole.DATA if isinstance(value, DataValue) else
                UseRole.PROTOCOL if isinstance(value, ProtocolValue) else UseRole.REFERENCE)
        return Use(UseID(name), value.id, role)

    def formal(name, block, ordinal, prototype):
        value = replace(prototype, id=ValueID(name), origin=BlockArgument(block, ordinal))
        added_values.append(value)
        return value

    entry_arguments = list(entry.arguments)
    if kind == "close":
        e0 = prior["injected_packet"]
    else:
        e0 = ProtocolValue(ValueID("fallback.original.injection"), region.id,
                           BlockArgument(entry.id, len(entry_arguments)), ProtocolValueKind.EXCEPTION_PACKET)
        added_values.append(e0)
        entry_arguments.append(e0.id)
    wrong_e0 = ProtocolValue(ValueID("fallback.other.injection"), region.id,
        BlockArgument(entry.id, len(entry_arguments)), ProtocolValueKind.EXCEPTION_PACKET)
    added_values.append(wrong_e0)
    entry_arguments.append(wrong_e0.id)
    raw = next(value for value in graph.values if isinstance(value, ProtocolValue)
               and value.protocol is ProtocolValueKind.RAW_DRIVER_REQUEST)
    raw_use = use("fallback.raw.before-lookup", raw)
    raw_marker = Operation(OperationID("fallback.raw.anchor"), "original raw observation before method lookup",
        (Behavior.COMPUTE,), (raw_use,), effects_complete=True)
    operations.append(raw_marker)
    raw_source = OwnedUse(raw_marker.id, raw_use.id)
    request = (NormalizedThrowSource(raw_source, e0.origin) if kind == "throw"
               else InjectedPacketTrigger(e0.origin))
    el_source = ContractResult(lookup_row.scope, lookup_row.clause, lookup_row.operation,
                               lookup_row.slot, lookup_row.contract.result)
    match_id = OperationID("fallback.match")
    input_use, state_use = use("fallback.match.lookup-packet", el), use("fallback.match.world", before)
    handler = FixedBuiltinHandler(BuiltinExceptionCategory.ATTRIBUTE_ERROR,
        StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN))
    normal_result, raise_result, boolean, branch, em = None, None, None, None, None
    normal_state, normal_el = before, el
    terminals, edges = {}, {}

    def terminal(name, block, packet, state):
        actuals = (use(name + ".packet", packet), use(name + ".state", state))
        operation = Operation(OperationID(name), "original fallback packet exit", (Behavior.CONTROL,),
            actuals, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=tuple(use.id for use in actuals)))
        operations.append(operation)
        return operation

    if matcher == "ordinary":
        boolean = DataValue(ValueID("fallback.match.bool"), region.id, OperationResult(match_id, 0), "builtins.bool")
        added_values.append(boolean)
        match_operation = Operation(match_id, "fixed builtin lookup exception match",
            (Behavior.COMPUTE, Behavior.READ), (input_use, state_use), (boolean.id,),
            accesses=(StateAccess(before.location, state_use.id, AccessMode.READ),), effects_complete=True)
        operations.append(match_operation)
        normal_result = OperationResult(match_id, 0)
        state_sites = (ExistingAccess(match_id, 0),)
        branch_block = next(block.id for block in region.blocks if old_exit.id in block.operations)
    else:
        handler_value = by_value[prior["root_inputs"][1]]
        handler_use = use("fallback.match.handler", handler_value)
        handler = ExceptionHandlerOperand(handler_use.id, handler_value.origin, handler)
        failure = BlockID("fallback.matcher-raised")
        em = formal("fallback.matcher-raised.packet", failure, 0, el)
        raised_state = formal("fallback.matcher-raised.world", failure, 1, before)
        raise_result = InvokeLiteralResult(ControlEdgeReference(match_id, 0), CompletionResult(1))
        signatures = [CompletionSignature(ExitKind.RAISE, (state_type, packet_type))]
        successors = [CompletionSuccessor(ExitKind.RAISE, failure, (CompletionResult(1), CompletionResult(0)))]
        actuals = (input_use, handler_use, state_use)
        uses = list(actuals)
        if matcher == "invoke":
            branch_block = BlockID("fallback.matcher-normal")
            normal_el = formal("fallback.matcher-normal.lookup-packet", branch_block, 0, el)
            normal_state = formal("fallback.matcher-normal.world", branch_block, 1, before)
            boolean = DataValue(ValueID("fallback.matcher-normal.bool"), region.id,
                                BlockArgument(branch_block, 2), "builtins.bool")
            added_values.append(boolean)
            forwarded = use("fallback.match.normal.lookup-packet", el)
            uses.append(forwarded)
            signatures.append(CompletionSignature(ExitKind.NORMAL, (state_type, bool_type)))
            successors.append(CompletionSuccessor(ExitKind.NORMAL, branch_block,
                (forwarded.id, CompletionResult(0), CompletionResult(1))))
            normal_result = InvokeLiteralResult(ControlEdgeReference(match_id, 1), CompletionResult(1))
        match_operation = Operation(match_id, "dynamic exception matching boundary", (Behavior.CONTROL,),
            tuple(uses), effects_complete=False, invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(signatures), terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
        operations.append(match_operation)
        raised_exit = terminal("fallback.matcher-raised.exit", failure, em, raised_state)
        blocks.append(Block(failure, (em.id, raised_state.id), (raised_exit.id,)))
        terminals["MATCHER_RAISE"] = raised_exit
        edges["MATCHER_RAISE"] = ControlEdgeReference(match_id, 0)
        state_sites = (InvokeStateOperand(match_id, state_use.id),)
    if matcher != "raise-only":
        branch_id = OperationID("fallback.match.branch")
        condition = use("fallback.match.condition", boolean)
        actuals, successors = [condition], []
        for ordinal, (leg, source_packet) in enumerate((("MATCH", e0), ("NO_MATCH", normal_el))):
            block = BlockID("fallback." + leg.lower())
            payload = formal(block.value + ".packet", block, 0, el)
            state = formal(block.value + ".world", block, 1, before)
            forwards = (use(block.value + ".forward.packet", source_packet),
                        use(block.value + ".forward.world", normal_state))
            actuals.extend(forwards)
            successors.append(Successor(block, tuple(use.id for use in forwards)))
            exit_ = terminal(block.value + ".exit", block, payload, state)
            blocks.append(Block(block, (payload.id, state.id), (exit_.id,)))
            terminals[leg], edges[leg] = exit_, ControlEdgeReference(branch_id, ordinal)
        branch = Operation(branch_id, "original matched/mismatched lookup branch", (Behavior.CONTROL,),
            tuple(actuals), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=condition.id))
        operations.append(branch)
        if matcher == "invoke":
            blocks.append(Block(branch_block, (normal_el.id, normal_state.id, boolean.id), (branch.id,)))
    matcher_row = ExceptionMatcher(match_id, input_use.id, el_source, handler, normal_result,
        raise_result, None if branch is None else branch.id, state_sites)
    fallback = DelegateLookupFallback(lookup, match_id, request)
    failure_operations = ((match_id, branch.id) if matcher == "ordinary" else (match_id,))
    rewritten = []
    for block in region.blocks:
        if block.id == entry.id:
            # Keep the old pack and original lookup, adding only the real
            # marker Use after raw production and before either lookup edge.
            block = replace(block, arguments=tuple(entry_arguments),
                operations=(block.operations[0], raw_marker.id, *block.operations[1:]))
        if old_exit.id in block.operations:
            block = replace(block, operations=failure_operations)
        rewritten.append(block)
    all_blocks = (*rewritten, *blocks)
    consumers = tuple(replace(row, targets=(OwnedUse(match_id, input_use.id),))
        if row.site == lookup else row for row in graph.protocol_result_consumers)
    graph = replace(graph, regions=(replace(region, blocks=all_blocks),),
        values=(*graph.values, *added_values),
        operations=tuple(operation for operation in graph.operations if operation.id != old_exit.id) + tuple(operations),
        protocol_result_consumers=consumers, exception_matches=(*graph.exception_matches, matcher_row),
        protocol_bindings=(*graph.protocol_bindings, *((fallback,) if attach else ())),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in all_blocks))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, {"kind": kind, "matcher_mode": matcher, "prior": prior,
        "lookup_row": lookup_row, "lookup": lookup, "matcher": matcher_row, "fallback": fallback,
        "request": request, "e0": e0, "el": el, "em": em,
        "e0_source": e0.origin, "el_source": el_source, "em_source": raise_result,
        "wrong_e0": wrong_e0, "wrong_e0_source": wrong_e0.origin,
        "raw": raw_source, "raw_marker": raw_marker, "operation": match_operation,
        "branch": branch, "terminals": terminals, "edges": edges}


def lookup_fallback_receiver_merge_program():
    """One lookup, two genuine incoming receiver cases, one E0 boundary.

    Both alternatives copy the same independently required iterator and its
    current world.  Each input case is valid on its own incoming edge; the
    two mutually exclusive choices must not be conjoined with one another.
    """
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    region, = graph.regions
    method = details["prior"]["method"]["operation"]
    block = next(block for block in region.blocks if method.id in block.operations)
    values = {value.id: value for value in graph.values}
    receiver_use, state_use = (next(use for use in method.uses if use.id == identity)
                               for identity in method.invoke_arguments)
    receiver, state = values[receiver_use.value], values[state_use.value]
    added_values, operations, added_blocks = [], [], []
    merge = BlockID("fallback.receiver.merge")
    m_receiver = replace(receiver, id=ValueID("fallback.receiver.merge.reference"), origin=BlockArgument(merge, 0))
    m_state = replace(state, id=ValueID("fallback.receiver.merge.world"), origin=BlockArgument(merge, 1))
    added_values.extend((m_receiver, m_state))
    evaluate_id = OperationID("fallback.receiver.choice")
    boolean = DataValue(ValueID("fallback.receiver.choice.bool"), region.id,
                        OperationResult(evaluate_id, 0), "builtins.bool")
    added_values.append(boolean)
    read = Use(UseID("fallback.receiver.choice.world"), state.id, UseRole.STATE_CONTENT)
    evaluate = Operation(evaluate_id, "original receiver control choice", (Behavior.COMPUTE, Behavior.READ),
        (read,), (boolean.id,), accesses=(StateAccess(state.location, read.id, AccessMode.READ),), effects_complete=True)
    condition = Use(UseID("fallback.receiver.choose.bool"), boolean.id, UseRole.DATA)
    branch_uses, successors, guards = [condition], [], []
    for label in ("left", "right"):
        destination = BlockID("fallback.receiver." + label)
        r = replace(receiver, id=ValueID(destination.value + ".reference"), origin=BlockArgument(destination, 0))
        w = replace(state, id=ValueID(destination.value + ".world"), origin=BlockArgument(destination, 1))
        added_values.extend((r, w))
        forwarded = (Use(UseID(destination.value + ".from-choice.reference"), receiver.id, UseRole.REFERENCE),
                     Use(UseID(destination.value + ".from-choice.world"), state.id, UseRole.STATE_CONTENT))
        branch_uses.extend(forwarded)
        successors.append(Successor(destination, tuple(use.id for use in forwarded)))
        outgoing = (Use(UseID(destination.value + ".to-merge.reference"), r.id, UseRole.REFERENCE),
                    Use(UseID(destination.value + ".to-merge.world"), w.id, UseRole.STATE_CONTENT))
        jump = Operation(OperationID(destination.value + ".jump"), "original incoming receiver copy",
            (Behavior.CONTROL,), outgoing, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(merge, tuple(use.id for use in outgoing)),)))
        operations.append(jump)
        added_blocks.append(Block(destination, (r.id, w.id), (jump.id,)))
        guards.append(ControlEdgeReference(jump.id, 0))
    choose = Operation(OperationID("fallback.receiver.choose"), "original mutually exclusive paths",
        (Behavior.CONTROL,), tuple(branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=condition.id))
    changed = replace(method, uses=tuple(replace(use, value=m_receiver.id)
        if use.id == receiver_use.id else replace(use, value=m_state.id)
        if use.id == state_use.id else use for use in method.uses))
    old_blocks = tuple(replace(old, operations=(*old.operations[:-1], evaluate.id, choose.id))
        if old.id == block.id else old for old in region.blocks)
    all_blocks = (*old_blocks, *added_blocks, Block(merge, (m_receiver.id, m_state.id), (changed.id,)))
    inputs = tuple(replace(row, cases=tuple(replace(row.cases[0], guard=guard) for guard in guards))
        if row.site.operation == method.id else row for row in graph.protocol_call_inputs)
    graph = replace(graph, regions=(replace(region, blocks=all_blocks),),
        values=(*graph.values, *added_values),
        operations=tuple(changed if operation.id == changed.id else operation for operation in graph.operations)
                   + (evaluate, choose, *operations), protocol_call_inputs=inputs,
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in all_blocks))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, {**details, "receiver_guards": tuple(guards), "receiver_merge": merge,
                   "receiver_lookup": changed}


__all__ = ["lookup_fallback_program", "lookup_fallback_receiver_merge_program"]

"""Expanded delegate-method lookups over original INVOKE/state/result ports.

These supplied graphs declare the Python method interpretation. They do not
parse descriptors, exception categories or runtime object identities.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import AccessMode, Block, BlockArgument, ReferenceValue, TerminatorKind, Use, UseRole
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
    ProtocolResultConsumers, RawOperandSource, RawRequestTrigger,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OwnedUse, ProtocolCall, ProtocolCallRule as CR,
    ProtocolOperation,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, ObjectField, ReferenceOwner, StateAddressRefinement,
)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_continuation_graphs import (
    _Site, _gap, continuation_close_program, continuation_site_program,
    with_continuation_connections, continuation_paired_program, continuation_initial_loop_program,
)
from tests.fixtures.program_protocol_graphs import _scope


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _source(row):
    return ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)


def _insert_method(graph, details, *, name, receiver_formal=False):
    """Insert one real lookup before the existing advance, preserving its N/R."""
    call = next(operation for operation in graph.operations
                if operation.id == details["advance"]["operation"].id)
    region = graph.regions[0]
    old_block = next(block for block in region.blocks if call.id in block.operations)
    receiver = details["lookup"]["normal_values"][0]
    state_use = next(use for use in call.uses if use.id == call.invoke_arguments[-1])
    builder = _Site()
    builder.values = list(graph.values)
    method = builder.invoke(name, old_block.id, receiver, (), state_use.value,
                            prefix=old_block.operations[:-1])
    failure = builder.terminal(name + ".error", method["failure"],
                               *method["failure_values"], raised=True)
    old_receiver = details["advance"]["receiver"]
    changed = replace(call, uses=tuple(replace(use, value=method["normal_values"][0])
        if use.id == old_receiver else replace(use, value=method["normal_values"][1])
        if use.id == state_use.id else use for use in call.uses))
    clause = details["advance_rows"][0].clause
    rule = getattr(CR, "DELEGATE_" + details["request_kind"].value + "_LOOKUP")
    rows = tuple(ProtocolOperation(details["scope"], clause, method["operation"].id,
        index, ProtocolCall(method["receiver"], (), port, method["state_sites"], rule), _gap())
        for index, port in enumerate(method["ports"]))
    normal = _source(rows[0])
    iterator = _source(details["iterator_row"])
    expected_receiver = (BlockArgument(method["normal"], 0) if receiver_formal else normal)
    attachments = tuple(replace(row, cases=tuple(replace(case, receiver=expected_receiver)
        for case in row.cases)) if row.site.operation == call.id else row
        for row in graph.protocol_call_inputs)
    lookup_expected = (BlockArgument(details["lookup"]["normal"], 0)
                       if receiver_formal else iterator)
    attachments += tuple(ProtocolCallInputs(_site(row),
        (ProtocolCallInputCase(None, lookup_expected, (), None),)) for row in rows)
    previous = details.get("method_rows")
    consumers = []
    for attachment in graph.protocol_result_consumers:
        if attachment.site == _site(details["iterator_row"]):
            # Each independent lookup reads the iterator, not another lookup's
            # bound method. Retain both consumers in the two-lookup variant.
            targets = tuple(target for target in attachment.targets
                            if target != OwnedUse(call.id, old_receiver))
            targets += (OwnedUse(method["operation"].id, method["receiver"]),)
            attachment = replace(attachment, targets=targets)
        elif previous is not None and attachment.site == _site(previous[0]):
            attachment = replace(attachment, targets=())
        consumers.append(attachment)
    consumers += [ProtocolResultConsumers(_site(rows[0]), (OwnedUse(call.id, old_receiver),)),
                  ProtocolResultConsumers(_site(rows[1]), (HostTerminal(failure.id),))]
    blocks = tuple(builder.blocks[0] if block.id == old_block.id else block for block in region.blocks)
    blocks += (Block(method["normal"], method["normal_values"], (call.id,)), builder.blocks[1])
    refinement = StateAddressRefinement(method["state_sites"][0], (
        AddressEffect(ReferenceOwner(method["receiver"]),
            (ObjectField({"NEXT": "__next__", "SEND": "send", "THROW": "throw", "CLOSE": "close"}[
                details["request_kind"].value]),), AccessMode.READ),), AddressCoverage.PARTIAL)
    graph = replace(graph, regions=(replace(region, blocks=blocks),),
        operations=tuple(changed if operation.id == call.id else operation for operation in graph.operations)
            + tuple(builder.operations), values=tuple(builder.values),
        protocol_operations=(*graph.protocol_operations, *rows), protocol_call_inputs=attachments,
        protocol_result_consumers=tuple(consumers),
        state_address_refinements=(*graph.state_address_refinements, refinement),
        control_scopes=(_scope(graph.root, blocks),))
    return graph, {**details, "advance": {**details["advance"], "operation": changed},
        "method": method, "method_rows": rows, "method_failure": failure,
        "method_source": normal, "iterator_source": iterator,
        "all_methods": (*details.get("all_methods", ()), method)}


def method_lookup_program(*, request="next", throw_arity=3, receiver_formal=False,
                          two_lookups=False, initial=False):
    """Return ``(program, details)`` with real lookup N/R and bound-method call.

    request is next/send/throw/close. ``receiver_formal`` names original exact
    landing formals instead of ContractResult in expected fields. With two
    lookups, only the second bound-method result is the call's actual receiver;
    the first is retained as an explicitly unconsumed conditional stage.
    """
    if request == "close":
        if initial:
            raise ValueError("close is not InitialAdvance")
        graph, details = continuation_close_program()
    else:
        graph, details = with_continuation_connections(*continuation_site_program(
            request=request, throw_arity=throw_arity, initial=initial))
    graph, details = _insert_method(graph, details, name="method.first",
                                    receiver_formal=receiver_formal)
    if two_lookups:
        graph, details = _insert_method(graph, details, name="method.second",
                                        receiver_formal=receiver_formal)
    return graph, details


def method_lookup_paired_program(*, crossed=False):
    """Two independently selected method lookups feed one guarded SEND call."""
    graph, details = continuation_paired_program()
    methods, sources, method_rows = [], [], []
    for index, iterator in enumerate(details["sources"]):
        region = graph.regions[0]
        origin = next(operation for operation in graph.operations if operation.id == iterator.operation)
        normal_block = origin.terminator.successors[iterator.slot].block
        old = next(block for block in region.blocks if block.id == normal_block)
        jump = next(operation for operation in graph.operations if operation.id == old.operations[-1])
        builder = _Site()
        builder.values = list(graph.values)
        method = builder.invoke(f"paired.method.{index}", old.id, old.arguments[0], (), old.arguments[1],
                                prefix=old.operations[:-1])
        failure = builder.terminal(f"paired.method.{index}.error", method["failure"],
                                   *method["failure_values"], raised=True)
        changed = replace(jump, uses=tuple(replace(use, value=method["normal_values"][0]) if number == 0 else
            replace(use, value=method["normal_values"][1]) if number == 2 else use
            for number, use in enumerate(jump.uses)))
        rows = tuple(ProtocolOperation(details["scope"], details["send_rows"][0].clause,
            method["operation"].id, slot, ProtocolCall(method["receiver"], (), port,
            method["state_sites"], CR.DELEGATE_SEND_LOOKUP), _gap())
            for slot, port in enumerate(method["ports"]))
        consumers = tuple(replace(row, targets=(OwnedUse(method["operation"].id, method["receiver"]),))
            if row.site.operation == iterator.operation and row.site.slot == 0 else row
            for row in graph.protocol_result_consumers)
        consumers += (ProtocolResultConsumers(_site(rows[0]),
            (OwnedUse(details["call"]["operation"].id, details["call"]["receiver"]),)),
            ProtocolResultConsumers(_site(rows[1]), (HostTerminal(failure.id),)))
        blocks = tuple(builder.blocks[0] if block.id == old.id else block for block in region.blocks)
        blocks += (Block(method["normal"], method["normal_values"], (jump.id,)), builder.blocks[1])
        graph = replace(graph, operations=tuple(changed if operation.id == jump.id else operation
            for operation in graph.operations) + tuple(builder.operations), values=tuple(builder.values),
            regions=(replace(region, blocks=blocks),), control_scopes=(_scope(graph.root, blocks),),
            protocol_operations=(*graph.protocol_operations, *rows),
            protocol_call_inputs=(*graph.protocol_call_inputs, *(ProtocolCallInputs(_site(row),
                (ProtocolCallInputCase(None, iterator, (), None),)) for row in rows)),
            protocol_result_consumers=consumers)
        methods.append(method)
        sources.append(_source(rows[0]))
        method_rows.extend(rows)
    attachments = tuple(replace(row, cases=tuple(replace(case,
        receiver=sources[1 - index] if crossed else sources[index])
        for index, case in enumerate(row.cases))) if row.site.operation == details["call"]["operation"].id else row
        for row in graph.protocol_call_inputs)
    return replace(graph, protocol_call_inputs=attachments), {**details,
        "methods": tuple(methods), "method_sources": tuple(sources), "method_rows": tuple(method_rows)}


def method_lookup_loop_program(*, stale=False):
    """One static lookup runs each iteration; an old bound method is not fresh."""
    graph, details = continuation_initial_loop_program()
    graph = replace(graph, protocol_call_inputs=tuple(replace(row, cases=tuple(
        replace(case, trigger=RawRequestTrigger(details["raw"])) for case in row.cases))
        if row.site.operation == details["advance"]["operation"].id else row
        for row in graph.protocol_call_inputs))
    graph, details = _insert_method(graph, details, name="method.loop")
    region = graph.regions[0]
    header = next(block for block in region.blocks if block.id == details["header"])
    old = ReferenceValue(ValueID("method.loop.previous"), graph.root,
                         BlockArgument(header.id, len(header.arguments)))
    seed = next(operation for operation in graph.operations if operation.id == OperationID("continuation.to.loop"))
    seed_use = Use(UseID("method.loop.initial.carrier"), details["root_inputs"][1], UseRole.REFERENCE)
    seed = replace(seed, uses=(*seed.uses, seed_use), terminator=replace(seed.terminator,
        successors=(replace(seed.terminator.successors[0],
            arguments=(*seed.terminator.successors[0].arguments, seed_use.id)),)))
    branch = next(operation for operation in graph.operations if operation.id == details["item_exit"].id)
    back = Use(UseID("method.loop.save.current"), details["method"]["normal_values"][0], UseRole.REFERENCE)
    branch = replace(branch, uses=(*branch.uses, back), terminator=replace(branch.terminator,
        successors=(replace(branch.terminator.successors[0],
            arguments=(*branch.terminator.successors[0].arguments, back.id)), branch.terminator.successors[1])))
    call = details["advance"]["operation"]
    if stale:
        call = replace(call, uses=tuple(replace(use, value=old.id)
            if use.id == details["advance"]["receiver"] else use for use in call.uses))
    updates = {seed.id: seed, branch.id: branch, call.id: call}
    blocks = tuple(replace(block, arguments=(*block.arguments, old.id)) if block.id == header.id else block
                   for block in region.blocks)
    graph = replace(graph, operations=tuple(updates.get(operation.id, operation) for operation in graph.operations),
        values=(*graph.values, old), regions=(replace(region, blocks=blocks),),
        control_scopes=(_scope(graph.root, blocks),))
    return graph, {**details, "previous": old.id, "advance": {**details["advance"], "operation": call}}


def prior_advance_case_program():
    """A/B SEND receiver phi precedes an incorrectly marked A InitialAdvance.

    Iterator B is evaluated first. After A's own evaluation there is no opaque
    operation on the path to the typed SEND, so its known conditional receiver
    cannot be hidden by an unrelated unknown-callback boundary.
    """
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
    from scar.ir.program.ids import LocationID, ProtocolScopeID
    from scar.ir.program.model import (
        Behavior, DataValue, ExitKind, ExitPort, Operation, OperationResult, ProgramGraph,
        ProtocolValue, Region, StateLocation, Successor, Terminator, ValueKind, ValueType,
    )
    from scar.ir.program.protocols import OperationSiteSubject, ProtocolClause as C, ProtocolProfile, ProtocolScope
    from tests.fixtures.program_continuation_graphs import PACKET, REFERENCE

    builder = _Site()
    entry = BlockID("prior.entry")
    root_b, root_a, operand = (builder.formal(entry, index, REFERENCE) for index in range(3))
    state = builder.formal(entry, 3, builder.state_type)
    condition = DataValue(ValueID("prior.condition"), builder.region, BlockArgument(entry, 4), "builtins.bool")
    builder.values.append(condition)
    lookup_b = builder.invoke("prior.iterator.b", entry, root_b, (), state)
    builder.terminal("prior.iterator.b.error", lookup_b["failure"], *lookup_b["failure_values"], raised=True)
    lookup_a = builder.invoke("prior.iterator.a", lookup_b["normal"], root_a, (), lookup_b["normal_values"][1])
    builder.terminal("prior.iterator.a.error", lookup_a["failure"], *lookup_a["failure_values"], raised=True)
    scope_id = ProtocolScopeID("prior.scope")
    rows, inputs = [], []
    sources = []
    for index, lookup in enumerate((lookup_a, lookup_b)):
        selected = tuple(ProtocolOperation(scope_id, C.DELEGATE_ITER_LOOKUP, lookup["operation"].id, slot,
            ProtocolCall(lookup["receiver"], (), port, lookup["state_sites"], CR.DELEGATE_ITER), _gap())
            for slot, port in enumerate(lookup["ports"]))
        rows.extend(selected)
        sources.append(_source(selected[0]))
        inputs.extend(ProtocolCallInputs(_site(row), (ProtocolCallInputCase(None,
            BlockArgument(entry, 1 if index == 0 else 0), (), None),)) for row in selected)
    pack_id = OperationID("prior.pack")
    raw = ProtocolValue(ValueID("prior.raw"), builder.region, OperationResult(pack_id, 0), P.RAW_DRIVER_REQUEST)
    builder.values.append(raw)
    packed = builder.use("prior.pack.argument", operand)
    pack = Operation(pack_id, "original SEND pack", (Behavior.REPRESENT,), (packed,), (raw.id,), effects_complete=True)
    observed = builder.use("prior.observe.raw", raw.id)
    observation = Operation(OperationID("prior.observe"), "original raw anchor", (Behavior.COMPUTE,),
                            (observed,), effects_complete=True)
    builder.operations.extend((pack, observation))
    raw_source = OwnedUse(observation.id, observed.id)
    choose_uses = (Use(UseID("prior.choose.bool"), condition.id, UseRole.DATA),
                  builder.use("prior.choose.a", lookup_a["normal_values"][1]),
                  builder.use("prior.choose.b", lookup_a["normal_values"][1]))
    choose = Operation(OperationID("prior.choose"), "original receiver choice", (Behavior.CONTROL,), choose_uses,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID("prior.a"), (choose_uses[1].id,)),
            Successor(BlockID("prior.b"), (choose_uses[2].id,))), condition=choose_uses[0].id))
    builder.operations.append(choose)
    builder.blocks.append(Block(lookup_a["normal"], lookup_a["normal_values"], (pack.id, observation.id, choose.id)))
    merge = BlockID("prior.send.block")
    parameters = tuple(builder.formal(merge, index, type_) for index, type_ in enumerate(
        (REFERENCE, REFERENCE, builder.state_type)))
    guards = []
    for label, lookup in (("a", lookup_a), ("b", lookup_b)):
        block = BlockID("prior." + label)
        incoming = builder.formal(block, 0, builder.state_type)
        uses = tuple(builder.use(f"prior.merge.{label}.{index}", value) for index, value in enumerate(
            (lookup["normal_values"][0], operand, incoming)))
        jump = Operation(OperationID("prior.merge." + label), "original guarded receiver copy", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(merge, tuple(use.id for use in uses)),)))
        builder.operations.append(jump)
        builder.blocks.append(Block(block, (incoming,), (jump.id,)))
        guards.append(ControlEdgeReference(jump.id, 0))
    send = builder.invoke("prior.send", merge, parameters[0], (parameters[1],), parameters[2])
    builder.terminal("prior.send.error", send["failure"], *send["failure_values"], raised=True)
    following = builder.invoke("prior.next", send["normal"], lookup_a["normal_values"][0], (), send["normal_values"][1])
    builder.terminal("prior.next.item", following["normal"], *following["normal_values"])
    builder.terminal("prior.next.error", following["failure"], *following["failure_values"], raised=True)
    for call, rule in ((send, CR.DELEGATE_SEND), (following, CR.DELEGATE_NEXT)):
        selected = tuple(ProtocolOperation(scope_id, C.DELEGATE_ADVANCE, call["operation"].id, slot,
            ProtocolCall(call["receiver"], call["arguments"], port, call["state_sites"], rule), _gap())
            for slot, port in enumerate(call["ports"]))
        rows.extend(selected)
        for row in selected:
            cases = (tuple(ProtocolCallInputCase(guard, source, (RawOperandSource(raw_source, 0),),
                RawRequestTrigger(raw_source)) for guard, source in zip(guards, sources))
                if call is send else (ProtocolCallInputCase(None, sources[0], (), InitialAdvance(sources[0])),))
            inputs.append(ProtocolCallInputs(_site(row), cases))
    region = Region(builder.region, "conditional prior advance then another request", entry, tuple(builder.blocks), (
        ExitPort("normal", ExitKind.NORMAL, (REFERENCE, builder.state_type)),
        ExitPort("failure", ExitKind.RAISE, (PACKET, builder.state_type))))
    # These supplied control primitives only branch/copy/exit. Any native frame
    # cleanup/callback would be another original operation, not hidden here.
    # Leaving them incomplete would independently make InitialAdvance unknown
    # and conceal the conditional prior-receiver question being isolated.
    operations = tuple(replace(operation, effects_complete=True)
        if operation.terminator is not None and operation.terminator.kind in (
            TerminatorKind.BRANCH, TerminatorKind.JUMP, TerminatorKind.RETURN, TerminatorKind.RAISE)
        else operation for operation in builder.operations)
    graph = ProgramGraph(builder.region, (region,), operations, tuple(builder.values),
        locations=(StateLocation(builder.domain, "one original coarse world"),),
        control_scopes=(_scope(builder.region, builder.blocks),),
        raw_driver_requests=(RawRequestDefinition(raw.id, RawRequestKind.SEND, (packed.id,)),),
        protocol_scopes=(ProtocolScope(scope_id, ProtocolProfile.DELEGATION_SITE_V1,
            OperationSiteSubject(builder.region, lookup_b["operation"].id), _gap()),),
        protocol_operations=tuple(rows), protocol_call_inputs=tuple(inputs))
    return graph, {"send": send, "following": following, "sources": tuple(sources), "guards": tuple(guards)}

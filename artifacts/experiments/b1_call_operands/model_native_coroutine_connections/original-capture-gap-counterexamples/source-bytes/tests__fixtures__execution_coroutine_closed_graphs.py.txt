"""Supplied native completion/reuse and historical-read callback paths.

The old native graph stays intact. Every occurrence is recaptured from this
new graph; a selected rejection has no second BodyDrive or lifecycle seed.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, DataValue, ExitKind, LiteralOrigin,
    Operation, OperationResult, ProtocolValue, ReferenceValue, StateAccess,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    value_type,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStatePredicateRule, OwnedUse, ProtocolProfile,
    RequestOperandBinding,
)
from tests.fixtures.native_coroutine_common import capture_program
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE
from tests.fixtures.program_generator_admission_graphs import _guard
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_protocol_graphs import closed_request_program
from tests.unit.test_program_await_native_and_general_sources import _native_program


def _use(name, value):
    return Use(UseID(name), value.id,
        UseRole.STATE_CONTENT if type(value) is StateVersionValue else
        UseRole.PROTOCOL if type(value) is ProtocolValue else
        UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)


def _rename(value, maps):
    if type(value) in maps:
        return maps[type(value)].get(value, value)
    if type(value) is tuple:
        return tuple(_rename(item, maps) for item in value)
    if type(value) is dict:
        return {key: _rename(item, maps) for key, item in value.items()}
    if is_dataclass(value):
        return replace(value, **{field.name: _rename(getattr(value, field.name), maps)
                                for field in fields(value)})
    return value


def _closed_driver(kind):
    graph, prior = closed_request_program(kind=kind)
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(row for row in region.blocks if row.id == region.entry)
    dropped = {prior['old_packet']}
    if kind is RawRequestKind.NEXT:
        dropped.add(prior['old_return'])
    arguments = tuple(value for value in entry.arguments if value not in dropped)
    graph = replace(graph,
        values=tuple(replace(value, origin=BlockArgument(entry.id, arguments.index(value.id)))
            if value.id in arguments else value for value in graph.values if value.id not in dropped),
        regions=tuple(replace(row, blocks=tuple(replace(block, arguments=arguments)
            if block.id == entry.id else block for block in row.blocks))
            if row.id == region.id else row for row in graph.regions))
    if kind is RawRequestKind.SEND:
        helper = next(row for row in graph.operations if row.id == prior['processing'])
        operand = Use(UseID('closed.send.operand'), prior['old_return'], UseRole.REFERENCE)
        helper = replace(helper, uses=(*helper.uses, operand),
                         invoke_arguments=(*helper.invoke_arguments, operand.id))
        graph = replace(graph,
            operations=tuple(helper if row.id == helper.id else row for row in graph.operations),
            protocol_operations=tuple(replace(row, contract=replace(row.contract,
                operand_bindings=(RequestOperandBinding(0, operand.id),)))
                for row in graph.protocol_operations))
    graph, guard = _guard(graph, block_id=region.entry, owner=interface.receiver,
        raw=interface.scheduler_request, label='native.closed.read',
        rule=BodyStatePredicateRule.IS_CLOSED, request_kind=kind)
    graph = replace(graph, protocol_scopes=tuple(replace(row,
        profile=ProtocolProfile.COROUTINE_BODY_V1) for row in graph.protocol_scopes))
    part, maps = _driver_part(graph, 'native.closed.driver')
    return part, {'guard': _rename(guard, maps),
        'helper': _rename(prior['processing'], maps),
        'terminals': _rename(prior['terminals'], maps),
        'interface': part['driver_interfaces'][0]}


def coroutine_closed_program(*, kind=RawRequestKind.NEXT,
                             extractor_kind=ExitKind.NORMAL,
                             reject_kind=ExitKind.NORMAL):
    """One native Create/Start/Return, then a genuine same-owner reject call.

    Both extractor alternatives remain canonical. Each completion first has an
    actual observer; only its retry arm continues, carrying B independently of
    the completion payload and all current state. The original host terminal
    and its original semantic receipt remain on the other arm.
    """
    if kind not in (RawRequestKind.NEXT, RawRequestKind.SEND):
        raise ValueError('the completed-reuse pair is NEXT or SEND(None)')
    if extractor_kind not in (ExitKind.NORMAL, ExitKind.RAISE):
        raise ValueError('extractor completion must be original N/R')
    if reject_kind not in (ExitKind.NORMAL, ExitKind.RAISE):
        raise ValueError('reject constructor completion must be original N/R')
    graph, details = _native_program()
    part, retry = _closed_driver(kind)
    caller = details['caller']
    assert retry['interface'].body == details['body'].id
    part['region'] = replace(part['region'], parent=caller.id)
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {row.id: row for row in caller.blocks}
    additions = {name: [] for name in ('values', 'operations', 'blocks')}

    def formals(identity, templates):
        rows = tuple(replace(value, id=ValueID(f'{identity.value}.argument.{slot}'),
            region=caller.id, origin=BlockArgument(identity, slot))
            for slot, value in enumerate(templates))
        additions['values'].extend(rows)
        return rows

    # Copy the exact instance used by the first Drive's caller. Native self
    # acquisition applicability is still its original independent contract.
    first, = details['drivers']
    call = operations[first['caller_call'].id]
    owner = values[next(use.value for use in call.uses if use.id == call.invoke_arguments[0])]
    selected = first['selected_call_edge']
    edge = call.terminator.successors[selected]
    landing = blocks[edge.block]
    kept_owner = formals(landing.id, (owner,))[0]
    kept_owner = replace(kept_owner, origin=BlockArgument(landing.id, len(landing.arguments)))
    additions['values'][-1] = kept_owner
    carry = _use('native.closed.first.forward.body', owner)
    edges = tuple(replace(item, arguments=(*item.arguments, carry.id)) if index == selected else item
                  for index, item in enumerate(call.terminator.successors))
    call = replace(call, uses=(*call.uses, carry),
                   terminator=replace(call.terminator, successors=edges))
    operations[call.id] = call
    blocks[landing.id] = replace(landing, arguments=(*landing.arguments, kept_owner.id))

    extract = operations[details['extract'].id]
    new_edges, extract_forwards, endings, observers = [], [], {}, {}
    raw_definitions = []
    literal_none = ReferenceValue(ValueID('native.closed.none'), caller.id,
                                  LiteralOrigin(None), targets=())
    additions['values'].append(literal_none)
    for index, item in enumerate(extract.terminator.successors):
        block = blocks[item.block]
        old = tuple(values[identity] for identity in block.arguments)
        payload, *states = old
        label = 'native.closed.' + item.kind.value.lower()
        forwarded = _use(label + '.extract.forward.body', kept_owner)
        extract_forwards.append(forwarded)
        body = replace(owner, id=ValueID(label + '.body'),
                       origin=BlockArgument(block.id, len(old)))
        additions['values'].append(body)
        new_edges.append(replace(item, arguments=(*item.arguments, forwarded.id)))

        finish_id = BlockID(label + '.finish')
        finish_values = formals(finish_id, old)
        terminal = operations[block.operations[-1]]
        remap = {before.id: after.id for before, after in zip(old, finish_values, strict=True)}
        operations[terminal.id] = replace(terminal, uses=tuple(replace(use,
            value=remap.get(use.value, use.value)) for use in terminal.uses))
        additions['blocks'].append(Block(finish_id,
            tuple(value.id for value in finish_values), (terminal.id,)))

        observer_id = OperationID(label + '.observe')
        decision = DataValue(ValueID(label + '.retry'), caller.id,
                             OperationResult(observer_id, 0), 'builtins.bool')
        observed = tuple(_use(f'{label}.observe.{slot}', value) for slot, value in enumerate(old))
        observer = Operation(observer_id, 'consume this original extraction completion',
            (Behavior.COMPUTE, Behavior.READ), observed, (decision.id,),
            accesses=tuple(StateAccess(value.location, use.id, AccessMode.READ)
                for value, use in zip(old, observed, strict=True) if type(value) is StateVersionValue),
            effects_complete=True)
        additions['values'].append(decision)
        observers[index] = OwnedUse(observer.id, observed[0].id)

        retry_id = BlockID(label + '.retry.call')
        retry_values = formals(retry_id, (body, payload, *states))
        condition = _use(label + '.branch.condition', decision)
        attempting = tuple(_use(f'{label}.attempt.{slot}', value)
                           for slot, value in enumerate((body, payload, *states)))
        finishing = tuple(_use(f'{label}.finish.{slot}', value) for slot, value in enumerate(old))
        branch = Operation(OperationID(label + '.branch'), 'attempt another call or finish this completion',
            (Behavior.CONTROL,), (condition, *attempting, *finishing), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, (
                Successor(retry_id, tuple(use.id for use in attempting)),
                Successor(finish_id, tuple(use.id for use in finishing))), condition=condition.id))
        blocks[block.id] = replace(block, arguments=(*block.arguments, body.id),
                                  operations=(observer.id, branch.id))
        prefix, current = [], tuple(retry_values[2:])
        if item.kind is ExitKind.RAISE:
            context = next(value for value in current if value.location == graph.resumable_bodies[0].context_location)
            handler_id = OperationID(label + '.caught')
            after = replace(context, id=ValueID(label + '.caught.after'), origin=OperationResult(handler_id, 0))
            packet_use, before = _use(label + '.caught.packet', retry_values[1]), _use(label + '.caught.before', context)
            handler = Operation(handler_id, 'install this caught extraction packet in current context',
                (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (packet_use, before), (after.id,),
                (StateAccess(context.location, before.id, AccessMode.READ_WRITE, after.id),), effects_complete=True)
            additions['values'].append(after)
            prefix.append(handler)
            current = tuple(after if value.id == context.id else value for value in current)
        pack_id = OperationID(label + '.raw')
        raw = ProtocolValue(ValueID(label + '.raw.value'), caller.id,
                            OperationResult(pack_id, 0), ProtocolValueKind.RAW_DRIVER_REQUEST)
        operands = () if kind is RawRequestKind.NEXT else (_use(label + '.send.none', literal_none),)
        pack = Operation(pack_id, 'the current reuse raw request', (Behavior.COMPUTE,),
                         operands, (raw.id,), effects_complete=True)
        additions['values'].append(raw)
        raw_definitions.append(RawRequestDefinition(raw.id, kind, tuple(use.id for use in operands)))
        target_entry = next(row for row in part['region'].blocks if row.id == part['region'].entry)
        retry_values_by_id = {value.id: value for value in part['values']}
        actual_values = tuple(retry_values[0] if identity == retry['interface'].receiver else
            raw if identity == retry['interface'].scheduler_request else
            next(value for value in current if value.location == retry_values_by_id[identity].location)
                if type(retry_values_by_id[identity]) is StateVersionValue else literal_none
            for identity in target_entry.arguments)
        call_id = OperationID(label + '.call')
        actuals = tuple(_use(f'{label}.call.input.{slot}', value)
                        for slot, value in enumerate(actual_values))
        exit_, = part['region'].exits
        result_id = BlockID(label + '.rejected')
        templates = tuple(next(value for value in part['values'] if value_type(value) == type_)
                          for type_ in exit_.types)
        results = formals(result_id, templates)
        reject_call = Operation(call_id, 'call the same completed native body rejection interface',
            (Behavior.CONTROL,), actuals, effects_complete=True, callee=part['region'].id,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=(CompletionSignature(exit_.kind, exit_.types),),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(exit_.kind, result_id,
                    tuple(CompletionResult(slot) for slot in range(len(results)))),)))
        rejected_uses = tuple(_use(f'{label}.rejected.{slot}', value) for slot, value in enumerate(results))
        rejected = Operation(OperationID(label + '.raise'), 'raise this rejection own whole packet',
            (Behavior.CONTROL,), rejected_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit='failure',
                                  values=tuple(use.id for use in rejected_uses)))
        additions['operations'].extend((observer, branch, *prefix, pack, reject_call, rejected))
        additions['blocks'].extend((Block(retry_id, tuple(value.id for value in retry_values),
            tuple(op.id for op in (*prefix, pack, reject_call))),
            Block(result_id, tuple(value.id for value in results), (rejected.id,))))
        endings[item.kind] = {'observer': observer, 'branch': branch, 'call': reject_call,
            'raw': raw, 'raw_operation': pack, 'terminal': rejected,
            'receiver': OwnedUse(call_id, actuals[0].id), 'current_states': current,
            'selected_block': block.id}

    extract = replace(extract, uses=(*extract.uses, *extract_forwards),
                      terminator=replace(extract.terminator, successors=tuple(new_edges)))
    operations[extract.id] = extract
    caller = replace(caller, blocks=(*blocks.values(), *additions['blocks']))
    receipts = tuple(replace(row, targets=(*row.targets, observers[row.site.slot]))
        if row.site.operation == extract.id and row.site.slot in observers else row
        for row in graph.protocol_result_consumers)
    graph = replace(graph,
        regions=tuple(caller if row.id == caller.id else row for row in graph.regions) + (part['region'],),
        values=(*graph.values, *additions['values'], *part['values']),
        operations=(*operations.values(), *additions['operations'], *part['operations']),
        raw_driver_requests=(*graph.raw_driver_requests, *raw_definitions),
        protocol_result_consumers=receipts,
        control_scopes=tuple(replace(row, blocks=tuple(block.id for block in caller.blocks))
            if row.region == caller.id else row for row in graph.control_scopes) + part['control_scopes'],
        driver_interfaces=(*graph.driver_interfaces, *part['driver_interfaces']),
        driver_lifecycles=(*graph.driver_lifecycles, *part['driver_lifecycles']),
        protocol_scopes=(*graph.protocol_scopes, *part['protocol_scopes']),
        protocol_operations=(*graph.protocol_operations, *part['protocol_operations']))
    # No original source path is reexecuted. Exactly one selected extraction
    # branch attempts the second call, which has just its real RAISE completion.
    choices = {operations[next(block for block in details['caller'].blocks
        if block.id == identity).operations[-1]].id: selected
        for identity, selected in details['caller_path'] if selected is not None}
    extract_edge = next(index for index, edge in enumerate(extract.terminator.successors)
                        if edge.kind is extractor_kind)
    choices[extract.id] = extract_edge
    choices[endings[extractor_kind]['branch'].id] = 0
    choices[endings[extractor_kind]['call'].id] = 0
    path = _selected_path(graph, caller, choices)
    retry_choices = {retry['guard']['branch']: 0,
                     retry['helper']: 0 if reject_kind is ExitKind.NORMAL else 1}
    retry_path = _selected_path(graph, part['region'], retry_choices)
    first = {**first, 'caller_call': call}
    return graph, {**details, 'caller': caller, 'caller_path': path,
        'drivers': (first,), 'calls': (call,), 'extract': extract, 'endings': endings,
        'final': operations[details['final'].id],
        'closed': {**retry, 'region': part['region'], 'path': retry_path,
            'selected_terminal': retry['terminals'][0 if reject_kind is ExitKind.NORMAL else 1],
            'kind': kind, 'extractor_kind': extractor_kind, 'reject_kind': reject_kind}}


def coroutine_closed_execution(*, kind=RawRequestKind.NEXT,
                               extractor_kind=ExitKind.NORMAL,
                               reject_kind=ExitKind.NORMAL,
                               missing_retry_call=False):
    graph, details = coroutine_closed_program(kind=kind, extractor_kind=extractor_kind,
                                              reject_kind=reject_kind)
    stage, = details['stage_records']
    closed = details['closed']
    extra = (
        {'label': 'extract', 'parent': 'caller', 'caller': details['extract'].id,
         'region': stage['region'].id, 'path': stage['paths'][extractor_kind],
         'completion': stage['terminals'][extractor_kind].id},
        {'label': 'retry', 'parent': 'caller', 'caller': details['endings'][extractor_kind]['call'].id,
         'region': closed['region'].id, 'path': closed['path'],
         'completion': closed['selected_terminal']},
    )
    model, captured = capture_program(graph, details, label='native.closed', extra_calls=extra)
    example, = captured['instances']
    if missing_retry_call:
        missing = example['extra_call_activations']['retry']
        model = replace(model, call_activations=tuple(row for row in model.call_activations
                                                     if row.id != missing.id))
    return graph, model, {**captured, 'read': example['extra_scopes']['retry'][2][closed['guard']['predicate']]}


def coroutine_callback_program(*, callback_kind=ExitKind.NORMAL):
    """A native historical Created READ survives a real callback N/R boundary."""
    graph, details = _native_program()
    driver, = details['drivers']
    interface = next(row for row in graph.driver_interfaces if row.region == driver['driver_region'].id)
    # The shared guard only inspects its one-driver input; its body definition
    # and the actual native getter/extractor remain those of this graph.
    graph, guard = _guard(graph, block_id=driver['driver_region'].entry,
        owner=interface.receiver, raw=interface.scheduler_request,
        label='native.callback.phase', rule=BodyStatePredicateRule.IS_CREATED)
    region = next(row for row in graph.regions if row.id == interface.region)
    blocks = {row.id: row for row in region.blocks}
    values = {row.id: row for row in graph.values}
    original = blocks[guard['admitted']]
    arguments = tuple(values[identity] for identity in original.arguments)
    states = tuple(value for value in arguments if type(value) is StateVersionValue)
    carried = tuple(value for value in arguments if type(value) is not StateVersionValue)
    normal_id, failure_id = BlockID('native.callback.normal'), BlockID('native.callback.failure')
    additions = []

    def formal(identity, slot, template):
        value = replace(template, id=ValueID(f'{identity.value}.argument.{slot}'),
                        origin=BlockArgument(identity, slot))
        additions.append(value)
        return value

    normal = tuple(formal(normal_id, index, value) for index, value in enumerate(arguments))
    packet = ProtocolValue(ValueID('native.callback.failure.packet'), region.id,
        BlockArgument(failure_id, 0), ProtocolValueKind.EXCEPTION_PACKET)
    additions.append(packet)
    failure = (packet, *(formal(failure_id, index + 1, value) for index, value in enumerate(states)))
    callback_id = OperationID('native.callback.invoke')
    actual = tuple(_use(f'native.callback.input.{index}', value) for index, value in enumerate(states))
    forwards = tuple(_use(f'native.callback.forward.{index}', value) for index, value in enumerate(carried))
    state_slots = {value.id: index for index, value in enumerate(states)}
    forward_slots = {value.id: use.id for value, use in zip(carried, forwards, strict=True)}
    normal_arguments = tuple(CompletionResult(state_slots[value.id])
        if type(value) is StateVersionValue else forward_slots[value.id] for value in arguments)
    callback = Operation(callback_id, 'actual callback with unknown state effects',
        (Behavior.CONTROL,), (*actual, *forwards), effects_complete=False,
        invoke_arguments=tuple(use.id for use in actual),
        completions=(CompletionSignature(ExitKind.NORMAL, tuple(value_type(value) for value in states)),
            CompletionSignature(ExitKind.RAISE, (PACKET, *(value_type(value) for value in states)))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, normal_id, normal_arguments),
            CompletionSuccessor(ExitKind.RAISE, failure_id,
                tuple(CompletionResult(index) for index in range(len(failure)))))))
    remap = {before.id: after.id for before, after in zip(arguments, normal, strict=True)}
    moved = set(original.operations)
    operations = tuple(replace(row, uses=tuple(replace(use, value=remap.get(use.value, use.value))
        for use in row.uses)) if row.id in moved else row for row in graph.operations)
    raised_uses = tuple(_use(f'native.callback.raise.{index}', value) for index, value in enumerate(failure))
    raised = Operation(OperationID('native.callback.raise'), 'propagate this callback own packet',
        (Behavior.CONTROL,), raised_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit='failure',
                              values=tuple(use.id for use in raised_uses)))
    blocks[original.id] = replace(original, operations=(callback.id,))
    blocks[normal_id] = Block(normal_id, tuple(value.id for value in normal), original.operations)
    blocks[failure_id] = Block(failure_id, tuple(value.id for value in failure), (raised.id,))
    region = replace(region, blocks=tuple(blocks.values()))
    graph = replace(graph, operations=(*operations, callback, raised), values=(*graph.values, *additions),
        regions=tuple(region if row.id == region.id else row for row in graph.regions),
        control_scopes=tuple(replace(row, blocks=tuple(blocks)) if row.region == region.id else row
                             for row in graph.control_scopes))
    choices = {OperationID('native.callback.phase.branch'): 0, callback.id:
               0 if callback_kind is ExitKind.NORMAL else 1}
    old_driver_blocks = {row.id: row for row in driver['driver_region'].blocks}
    choices.update({old_driver_blocks[identity].operations[-1]: selected
        for identity, selected in driver['path'] if selected is not None})
    path = _selected_path(graph, region, choices)
    host = next(row for row in graph.operations if row.id ==
                (driver['host_terminal'].id if callback_kind is ExitKind.NORMAL else raised.id))
    driver = {**driver, 'driver_region': region, 'path': path, 'host_terminal': host}
    return graph, {**details, 'drivers': (driver,),
        'callback': {'operation': callback, 'guard': guard, 'kind': callback_kind,
                     'raise_terminal': raised}}


def coroutine_callback_execution(*, callback_kind=ExitKind.NORMAL):
    graph, details = coroutine_callback_program(callback_kind=callback_kind)
    stage, = details['stage_records']
    extra = ({'label': 'extract', 'parent': 'caller', 'caller': details['extract'].id,
              'region': stage['region'].id, 'path': stage['paths'][ExitKind.NORMAL],
              'completion': stage['terminals'][ExitKind.NORMAL].id},)
    model, captured = capture_program(graph, details, label='native.callback', extra_calls=extra)
    example, = captured['instances']
    read = example['driver_scopes'][0][2][details['callback']['guard']['predicate']]
    return graph, model, {**captured, 'read': read}

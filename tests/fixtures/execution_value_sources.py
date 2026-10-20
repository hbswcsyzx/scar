"""Composed primitive-slot sources on original values, states and call ports.

No object denotation, immutable-field assumption or derived copy edge is added.
The previous slot fixtures provide the same canonical access constructors.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.ids import CallActivationID
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    DataValue, ExitKind, ExitPort, InvokeLiteralResult, Operation, OperationResult, Region,
    StateAccess, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, CellContent, DomainOwner, InvokeStateOperand,
    ReferenceOwner, StateAddressRefinement, WholeOwner,
)
from scar.ir.program.stored_values import StoredValueRead
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.execution_stored_values import (
    BOOL, CONTEXT, DOMAINS, STATES, WORLD, _Build, _actual, _graph,
    stored_values_calls_execution, stored_values_control_execution,
)
from tests.fixtures.program_driver_graphs import PACKET, REFERENCE


def result_value(model, occurrence, value):
    return next(row for row in model.values if row.origin == occurrence and row.value == value.id)


def _incomplete(builder, operation):
    """Unknown produced-owner precision must not certify exhaustive aliases."""
    changed = replace(operation, effects_complete=False)
    builder.operations = [changed if row.id == operation.id else row for row in builder.operations]
    return changed


def layered_value_sources_execution(*, mode='payload', length=2, instances=2,
                                    opaque=False, overwrite=False):
    """Nested payloads, a loaded owner, or a long owner dependency chain.

    In owner mode the cell holding A is read before the actual A-cell write;
    no intervening write is silently declared disjoint. Every source is an
    original operand occurrence; every load result stays independently owned.
    """
    if mode not in ('payload', 'owner', 'owner-chain') or type(length) is not int or length < 1:
        raise ValueError('unsupported finite source composition')
    if mode == 'owner' and length != 2:
        raise ValueError('the loaded-owner composition has exactly two accesses')
    b = _Build('value.sources.' + mode)
    prefix = 'value.sources.' + mode
    entry = b.formals(prefix + '.entry', (REFERENCE, REFERENCE, REFERENCE, REFERENCE, *STATES),
                      owners=(2, 3))
    p, q, owner, holder, world, context = entry
    operations, writes, reads, write_rows, read_rows, results = [], [], [], [], [], []
    payload, current, loaded_owner = (owner if mode == 'owner-chain' else p), world, owner
    barrier = None
    for number in range(length):
        if mode == 'owner':
            store_owner, payload = (holder, owner) if number == 0 else (owner, p)
            read_owner = holder if number == 0 else loaded_owner
        elif mode == 'owner-chain':
            store_owner, payload, read_owner = owner, owner, loaded_owner
        else:
            store_owner, read_owner = owner, owner
        write, current, write_row = b.store(prefix + f'.write.{number}', payload, store_owner, current)
        operations.append(write)
        writes.append(write)
        write_rows.append(write_row)
        if opaque and number == length - 1:
            identity = OperationID(prefix + '.opaque')
            uses = b.uses(identity.value + '.use', (current, context))
            after = b.value(identity.value + '.after', OperationResult(identity, 0), STATES[0])
            barrier = Operation(identity, 'unknown callback inside the required interval',
                (Behavior.READ, Behavior.WRITE), uses, (after.id,),
                (StateAccess(WORLD, uses[0].id, AccessMode.READ_WRITE, after.id),
                 StateAccess(CONTEXT, uses[1].id, AccessMode.READ)), effects_complete=False)
            b.operations.append(barrier)
            operations.append(barrier)
            current = after
        read, result, read_row = b.read(prefix + f'.read.{number}', read_owner, current)
        if mode in ('owner', 'owner-chain') and number:
            read = _incomplete(b, read)
        operations.append(read)
        reads.append(read)
        results.append(result)
        read_rows.append(read_row)
        if mode == 'payload':
            payload = result
        else:
            loaded_owner = result
    if overwrite:
        write, current, row = b.store(prefix + '.overwrite', q, owner, current)
        read, result, read_row = b.read(prefix + '.read.overwrite', owner, current)
        writes.append(write)
        write_rows.append(row)
        reads.append(read)
        read_rows.append(read_row)
        results.append(result)
        operations.extend((write, read))
    terminal = b.terminal(prefix + '.return', ExitKind.NORMAL, (results[-1], current, context))
    b.block(prefix + '.entry', entry, (*operations, terminal))
    graph = _graph(b, ((b, b.finish(prefix + '.entry')),))
    path = ((BlockID(prefix + '.entry'), None),)
    model, scopes, source = _model(graph,
        tuple((graph.root, path, prefix + f'.actual.{number}') for number in range(instances)))
    examples = []
    for activation, visits, ids in scopes:
        write_occurrences = tuple(ids[operation.id] for operation in writes)
        read_occurrences = tuple(ids[operation.id] for operation in reads)
        payloads = tuple(_actual(model, occurrence, row.payload)
                         for occurrence, row in zip(write_occurrences, write_rows, strict=True))
        original_p = next(value for value in model.values if value.origin == visits[0] and value.value == p.id)
        original_owner = next(value for value in model.values if value.origin == visits[0] and value.value == owner.id)
        examples.append({'activation': activation, 'visits': visits, 'operations': ids,
            'writes': write_occurrences, 'reads': read_occurrences, 'payloads': payloads,
            'source': original_owner if mode == 'owner-chain' else original_p,
            'loaded_values': tuple(result_value(model, occurrence, value)
                for occurrence, value in zip(read_occurrences, results, strict=True)),
            'target': result_value(model, read_occurrences[-1], results[-1]),
            'terminal_value': _actual(model, ids[terminal.id], terminal.uses[0].id)})
    return graph, model, {'mode': mode, 'length': length, 'examples': tuple(examples),
        'write_rows': tuple(write_rows), 'read_rows': tuple(read_rows), 'writes': tuple(writes),
        'reads': tuple(reads), 'results': tuple(results), 'terminal': terminal,
        'barrier': barrier, 'locations': DOMAINS, 'source': source}


def cyclic_owner_sources_execution():
    """An unseeded owner dependency uses a future write, never a forward Use.

    The first read X precedes the store whose actual owner is X. Trying to use
    that post as X's source re-enters X's projection. A later ordinary seeded
    store/read remains independently provable in the same real context.
    """
    b = _Build('value.sources.cycle')
    entry = b.formals('value.sources.cycle.entry', (REFERENCE, REFERENCE, REFERENCE, *STATES), owners=(2,))
    p, q, owner, world, context = entry
    early, x, early_row = b.read('value.sources.cycle.early', owner, world)
    future, current, future_row = b.store('value.sources.cycle.future', q, x, world)
    future = _incomplete(b, future)
    seeded, current, seeded_row = b.store('value.sources.cycle.seeded', p, owner, current)
    final, y, final_row = b.read('value.sources.cycle.final', owner, current)
    terminal = b.terminal('value.sources.cycle.return', ExitKind.NORMAL, (y, current, context))
    b.block('value.sources.cycle.entry', entry, (early, future, seeded, final, terminal))
    graph = _graph(b, ((b, b.finish('value.sources.cycle.entry')),))
    model, scopes, source = _model(graph,
        ((graph.root, ((BlockID('value.sources.cycle.entry'), None),), 'value.sources.cycle.actual'),))
    activation, visits, ids = scopes[0]
    return graph, model, {'source': _actual(model, ids[seeded.id], seeded_row.payload),
        'unseeded': result_value(model, ids[early.id], x), 'seeded': result_value(model, ids[final.id], y),
        'early': early_row, 'final': final_row, 'early_occurrence': ids[early.id],
        'seeded_occurrence': ids[final.id], 'operations': ids, 'locations': DOMAINS}


def parallel_value_sources_execution(*, raised=False, instances=2):
    """The exact getter result has both original call-copy and stored edges.

    The two input References carry no distinct-object claim: the supplied
    boundary and implementation jointly require the returned argument to be
    the slot's value. A same-landing forwarded owner is a separate input port.
    """
    parent, child = _Build('value.parallel.caller'), _Build('value.parallel.getter')
    entry = parent.formals('value.parallel.entry',
        (REFERENCE, REFERENCE, REFERENCE, PACKET, BOOL, *STATES), owners=(2,))
    p, q, owner, packet, condition, world, context = entry
    write, post, write_row = parent.store('value.parallel.store', q, owner, world)
    child_entry = child.formals('value.parallel.getter.entry',
        (REFERENCE, REFERENCE, PACKET, BOOL, *STATES), owners=(1,))
    state_uses = child.uses('value.parallel.getter.read.use', child_entry[-2:])
    inspect = Operation(OperationID('value.parallel.getter.read'), 'original complete state READ',
        (Behavior.READ,), state_uses, accesses=tuple(StateAccess(location, use.id, AccessMode.READ)
            for location, use in zip(DOMAINS, state_uses, strict=True)), effects_complete=True)
    child.operations.append(inspect)
    n_types, r_types = (STATES[1], REFERENCE, STATES[0]), (STATES[0], PACKET, STATES[1])
    n = child.formals('value.parallel.getter.normal', (REFERENCE, PACKET, *STATES))
    r = child.formals('value.parallel.getter.raise', (REFERENCE, PACKET, *STATES))
    condition_use, = child.uses('value.parallel.getter.condition', (child_entry[3],))
    normal_forward = child.uses('value.parallel.getter.normal.forward',
        (child_entry[0], child_entry[2], child_entry[4], child_entry[5]))
    raise_forward = child.uses('value.parallel.getter.raise.forward',
        (child_entry[0], child_entry[2], child_entry[4], child_entry[5]))
    branch = child.add('value.parallel.getter.branch', (condition_use, *normal_forward, *raise_forward),
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID('value.parallel.getter.normal'), tuple(use.id for use in normal_forward)),
            Successor(BlockID('value.parallel.getter.raise'), tuple(use.id for use in raise_forward))),
            condition=condition_use.id))
    child.block('value.parallel.getter.entry', child_entry, (inspect, branch))
    returned = child.terminal('value.parallel.getter.return', ExitKind.NORMAL, (n[3], n[0], n[2]))
    failed = child.terminal('value.parallel.getter.failed', ExitKind.RAISE, (r[2], r[1], r[3]))
    child.block('value.parallel.getter.normal', n, (returned,))
    child.block('value.parallel.getter.raise', r, (failed,))
    child_region = Region(child.region, 'exact original getter implementation', BlockID('value.parallel.getter.entry'),
        tuple(child.blocks), (ExitPort('normal', ExitKind.NORMAL, n_types), ExitPort('raise', ExitKind.RAISE, r_types)),
        parent=parent.region)
    normal = parent.formals('value.parallel.normal', (REFERENCE, STATES[0], REFERENCE, STATES[1]), owners=(0,))
    failure = parent.formals('value.parallel.raise', (STATES[1], REFERENCE, PACKET, STATES[0]), owners=(1,))
    actuals = parent.uses('value.parallel.get.argument', (p, owner, packet, condition, post, context))
    normal_owner, raise_owner = parent.uses('value.parallel.get.forward', (owner, owner))
    call = parent.add('value.parallel.get', (*actuals, normal_owner, raise_owner), callee=child.region,
        invoke_arguments=tuple(use.id for use in actuals),
        completions=(CompletionSignature(ExitKind.NORMAL, n_types), CompletionSignature(ExitKind.RAISE, r_types)),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.RAISE, BlockID('value.parallel.raise'),
                (CompletionResult(2), raise_owner.id, CompletionResult(1), CompletionResult(0))),
            CompletionSuccessor(ExitKind.NORMAL, BlockID('value.parallel.normal'),
                (normal_owner.id, CompletionResult(2), CompletionResult(1), CompletionResult(0))))))
    site = InvokeStateOperand(call.id, actuals[4].id)
    parent.refinements.append(StateAddressRefinement(site,
        (AddressEffect(ReferenceOwner(actuals[1].id), (CellContent(),), AccessMode.READ),),
        AddressCoverage.DECLARED_COMPLETE))
    parent.refinements.append(StateAddressRefinement(InvokeStateOperand(call.id, actuals[5].id),
        (AddressEffect(DomainOwner(), (WholeOwner(),), AccessMode.READ),), AddressCoverage.DECLARED_COMPLETE))
    read_row = StoredValueRead(site, 0,
        InvokeLiteralResult(ControlEdgeReference(call.id, 1), CompletionResult(1)))
    parent.reads.append(read_row)
    parent.block('value.parallel.entry', entry, (write, call))
    normal_exit = parent.terminal('value.parallel.return', ExitKind.NORMAL, (normal[2], normal[1], normal[3]))
    raise_exit = parent.terminal('value.parallel.failed', ExitKind.RAISE, (failure[0], failure[2], failure[3]))
    parent.block('value.parallel.normal', normal, (normal_exit,))
    parent.block('value.parallel.raise', failure, (raise_exit,))
    graph = _graph(parent, ((parent, parent.finish('value.parallel.entry', raised=True)), (child, child_region)))
    caller_path = ((BlockID('value.parallel.entry'), 0 if raised else 1),
        (BlockID('value.parallel.raise' if raised else 'value.parallel.normal'), None))
    child_path = ((BlockID('value.parallel.getter.entry'), int(raised)),
        (BlockID('value.parallel.getter.raise' if raised else 'value.parallel.getter.normal'), None))
    paths = tuple(path for number in range(instances) for path in (
        (parent.region, caller_path, f'value.parallel.{number}.caller'),
        (child.region, child_path, f'value.parallel.{number}.getter')))
    model, scopes, source = _model(graph, paths)
    links, examples = [], []
    for number in range(instances):
        caller, getter = scopes[number * 2:number * 2 + 2]
        link = CallActivation(CallActivationID(f'value.parallel.{number}.get'), caller[2][call.id],
            getter[0], getter[1][0], getter[2][failed.id if raised else returned.id], source)
        links.append(link)
        landing = caller[1][-1]
        own = (None if raised else next(value for value in model.values
            if value.origin == landing and value.value == normal[2].id))
        forwarded = next(value for value in model.values if value.origin == landing
            and value.value == (failure[1].id if raised else normal[0].id))
        examples.append({'caller': caller, 'getter': getter, 'link': link,
            'operation': caller[2][call.id], 'ordinary_source': _actual(model, caller[2][call.id], actuals[0].id),
            'stored_source': _actual(model, caller[2][write.id], write_row.payload),
            'target': own, 'forwarded': forwarded,
            'terminal_value': _actual(model, caller[2][raise_exit.id if raised else normal_exit.id],
                (raise_exit if raised else normal_exit).uses[1 if raised else 0].id)})
    model = replace(model, call_activations=tuple(links))
    return graph, model, {'examples': tuple(examples), 'read_row': read_row, 'write_row': write_row,
        'call': call, 'branch': branch, 'kind': ExitKind.RAISE if raised else ExitKind.NORMAL,
        'normal_formals': normal, 'raise_formals': failure, 'locations': DOMAINS}


def copied_call_sources_execution(*, instances=2, missing=None):
    graph, model, original = stored_values_calls_execution(instances=instances, missing=missing)
    terminal = next(operation for operation in graph.operations if operation.id == OperationID('stored.caller.return'))
    examples = tuple({**example, 'source': example['payload'],
        'target': _actual(model, example['caller'][2][terminal.id], terminal.uses[0].id)}
        for example in original['examples'])
    return graph, model, {**original, 'examples': examples}


def shared_landing_value_sources_execution(*, arm=1):
    """Private getter completions forward to one shared consumer landing."""
    if arm not in (0, 1):
        raise ValueError('the supplied incoming must select one original arm')
    graph, _, original = parallel_value_sources_execution(instances=1)
    first = original['call']
    second_id = OperationID('value.parallel.get.other')
    remap = {use.id: UseID(f'value.parallel.get.other.use.{number}')
             for number, use in enumerate(first.uses)}
    second = replace(first, id=second_id, label='the other original getter call',
        uses=tuple(replace(use, id=remap[use.id]) for use in first.uses),
        invoke_arguments=tuple(remap[use] for use in first.invoke_arguments),
        terminator=replace(first.terminator, successors=tuple(replace(edge,
            arguments=tuple(remap[argument] if type(argument) is UseID else argument
                            for argument in edge.arguments)) for edge in first.terminator.successors)))
    # INVOKE owns private completion landings. Only ordinary jumps below share
    # the downstream consumer; its formals are not either call's own results.
    values = {value.id: value for value in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    extra_values, private_blocks, jumps, routed = [], [], [], []
    private_formals, private_targets = {}, {}
    use_builder = _Build(graph.root.value)
    for number, operation in enumerate((first, second)):
        successors = []
        for edge in operation.terminator.successors:
            original_block = blocks[edge.block]
            label = 'normal' if edge.kind is ExitKind.NORMAL else 'raise'
            private_id = BlockID(f'value.parallel.private.{number}.{label}')
            formals = tuple(replace(values[identity],
                id=ValueID(f'value.parallel.private.{number}.{label}.arg.{position}'),
                origin=BlockArgument(private_id, position))
                for position, identity in enumerate(original_block.arguments))
            extra_values.extend(formals)
            forwarded = use_builder.uses(f'value.parallel.private.{number}.{label}.forward', formals)
            jump = Operation(OperationID(f'value.parallel.private.{number}.{label}.jump'),
                'forward this private completion tuple to its consumer',
                (Behavior.CONTROL,), forwarded, effects_complete=True,
                terminator=Terminator(TerminatorKind.JUMP, (
                    Successor(original_block.id, tuple(use.id for use in forwarded)),)))
            private_blocks.append(Block(private_id, tuple(value.id for value in formals), (jump.id,)))
            jumps.append(jump)
            private_formals[number, edge.kind] = formals
            private_targets[number, edge.kind] = private_id
            successors.append(replace(edge, block=private_id))
        routed.append(replace(operation, terminator=replace(operation.terminator, successors=tuple(successors))))
    first, second = routed
    incoming_states = {values[use.value].location: values[use.value]
        for use in first.uses if use.id in first.invoke_arguments
        and type(values[use.value]) is StateVersionValue}
    arm_states, arm_forwards, arm_calls = [], [], []
    for number, operation in enumerate((first, second)):
        block_id = BlockID(f'value.parallel.arm.{number}')
        formals = tuple(StateVersionValue(ValueID(f'value.parallel.arm.{number}.state.{position}'),
            graph.root, BlockArgument(block_id, position), location)
            for position, location in enumerate(DOMAINS))
        extra_values.extend(formals)
        arm_states.append(formals)
        arm_forwards.append(use_builder.uses(f'value.parallel.arm.{number}.state.forward',
                                             tuple(incoming_states[location] for location in DOMAINS)))
        by_location = {value.location: value for value in formals}
        arm_calls.append(replace(operation, uses=tuple(
            replace(use, value=by_location[values[use.value].location].id)
            if type(values[use.value]) is StateVersionValue else use for use in operation.uses)))
    first, second = arm_calls
    source_entry = next(block for region in graph.regions if region.id == graph.root
                        for block in region.blocks if block.id == region.entry)
    # Caller dispatch and the callee's N/R branch have independent inputs.
    # An arm-1 caller must not simultaneously assert arm-0 for the same bool.
    condition = DataValue(ValueID('value.parallel.callsite.condition.value'), graph.root,
        BlockArgument(source_entry.id, len(source_entry.arguments)), 'builtins.bool')
    choose_use = Use(UseID('value.parallel.callsite.condition'), condition.id, UseRole.DATA)
    choose = Operation(OperationID('value.parallel.callsite.choose'), 'select one real getter callsite',
        (Behavior.CONTROL,), (choose_use, *arm_forwards[0], *arm_forwards[1]), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(BlockID('value.parallel.arm.0'), tuple(use.id for use in arm_forwards[0])),
            Successor(BlockID('value.parallel.arm.1'), tuple(use.id for use in arm_forwards[1]))),
            condition=choose_use.id))
    parent = next(region for region in graph.regions if region.id == graph.root)
    parent = replace(parent, blocks=tuple(replace(block,
        arguments=(*block.arguments, condition.id),
        operations=tuple(choose.id if identity == first.id else identity for identity in block.operations))
        if block.id == source_entry.id else block for block in parent.blocks) + (
            Block(BlockID('value.parallel.arm.0'), tuple(value.id for value in arm_states[0]), (first.id,)),
            Block(BlockID('value.parallel.arm.1'), tuple(value.id for value in arm_states[1]), (second.id,)),
            *private_blocks))
    extra_refinements = []
    for row in graph.state_address_refinements:
        if row.site.operation != first.id:
            continue
        effects = tuple(replace(effect, owner=ReferenceOwner(remap[effect.owner.use]))
            if type(effect.owner) is ReferenceOwner else effect for effect in row.effects)
        extra_refinements.append(replace(row,
            site=InvokeStateOperand(second.id, remap[row.site.state_use]), effects=effects))
    second_row = replace(original['read_row'],
        site=InvokeStateOperand(second.id, remap[original['read_row'].site.state_use]),
        result=InvokeLiteralResult(ControlEdgeReference(second.id, 1), CompletionResult(1)))
    graph = replace(graph, regions=tuple(parent if region.id == graph.root else region for region in graph.regions),
        operations=(*(first if operation.id == first.id else operation for operation in graph.operations),
                    second, choose, *jumps),
        values=(*graph.values, condition, *extra_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in parent.blocks))
            if scope.region == parent.id else scope for scope in graph.control_scopes),
        state_address_refinements=(*graph.state_address_refinements, *extra_refinements),
        stored_value_reads=(*graph.stored_value_reads, second_row))
    selected = first if arm == 0 else second
    selected_row = original['read_row'] if arm == 0 else second_row
    caller_path = ((source_entry.id, arm), (BlockID(f'value.parallel.arm.{arm}'), 1),
                   (private_targets[arm, ExitKind.NORMAL], 0),
                   (BlockID('value.parallel.normal'), None))
    child_path = ((BlockID('value.parallel.getter.entry'), 0),
                  (BlockID('value.parallel.getter.normal'), None))
    model, scopes, source = _model(graph, (
        (graph.root, caller_path, 'value.shared-landing.caller'),
        (first.callee, child_path, 'value.shared-landing.getter')))
    caller, getter = scopes
    link = CallActivation(CallActivationID('value.shared-landing.get'), caller[2][selected.id],
        getter[0], getter[1][0], getter[2][OperationID('value.parallel.getter.return')], source)
    model = replace(model, call_activations=(link,))
    target_definition = original['normal_formals'][2]
    return graph, model, {'source': _actual(model, caller[2][OperationID('value.parallel.store')], original['write_row'].payload),
        'target': next(value for value in model.values if value.origin == caller[1][-1]
                       and value.value == target_definition.id),
        'own_target': next(value for value in model.values if value.origin == caller[1][-2]
            and value.value == private_formals[arm, ExitKind.NORMAL][2].id),
        'selected': selected, 'selected_row': selected_row, 'rows': (original['read_row'], second_row),
        'operation': caller[2][selected.id], 'caller': caller, 'getter': getter, 'link': link, 'arm': arm}


def repeated_loop_sources_execution():
    graph, model, original = stored_values_control_execution(route='loop', iterations=2)
    values = {value.id: value for value in graph.values}
    definition = values[next(identity for identity in original['read'].results)]
    targets = tuple(result_value(model, occurrence, definition) for occurrence in original['reads'])
    return graph, model, {**original, 'targets': targets}


__all__ = ['layered_value_sources_execution', 'cyclic_owner_sources_execution',
           'parallel_value_sources_execution', 'copied_call_sources_execution',
           'shared_landing_value_sources_execution', 'repeated_loop_sources_execution']

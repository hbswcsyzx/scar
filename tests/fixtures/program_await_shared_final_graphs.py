"""A complete general await with repeated incoming tuples and shared extraction.

The only loop is a synchronous copy/control loop before the first body drive.
Both incoming arms carry the same B. Two distinct extraction calls share the
original E/F implementation; each keeps its own complete NORMAL/RAISE ports.
These supplied declarations do not prove native source or runtime semantics.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSuccessor,
    DataValue, ExitKind, InvokeLiteralResult, Operation, OperationResult,
    ProtocolValue, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_general_final_graphs import await_general_final_program


_CASE_MODES = ('explicit', 'universal', 'partial', 'missing')


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _use(name, value):
    role = (UseRole.STATE_CONTENT if type(value) is StateVersionValue else
            UseRole.PROTOCOL if type(value) is ProtocolValue else
            UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)
    return Use(UseID(name), value.id, role)


def shared_final_caller_path(program, details, *, arms=(0, 1), extractor=0,
                             child_raised=False):
    """Select a finite original path, retaining repeated visits to one site.

    Each arm except the last is followed by the real backedge; the final arm
    continues to the first advance. No body operation or source is reevaluated.
    """
    if type(arms) is not tuple or not arms or any(type(arm) is not int or arm not in (0, 1) for arm in arms):
        raise ValueError('arms requires a nonempty tuple of exact incoming ordinals')
    if type(extractor) is not int or extractor not in (0, 1) or type(child_raised) is not bool:
        raise ValueError('extractor and child completion require exact selections')
    shared = details['shared_final']
    caller = shared['caller']
    blocks = {block.id: block for block in caller.blocks}
    operations = {operation.id: operation for operation in program.operations}
    choices = dict(shared['base_choices'])
    selected_kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL
    selected_call = shared['extractors'][extractor]['operation']
    choices[selected_call.id] = next(number for number, edge in enumerate(selected_call.terminator.successors)
                                     if edge.kind is selected_kind)
    choices[shared['extractor_branch'].id] = extractor
    current, path, visits = caller.entry, [], 0
    while len(path) <= len(blocks) * (len(arms) + 2):
        operation = operations[blocks[current].operations[-1]]
        if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            path.append((current, None))
            if visits != len(arms):
                raise AssertionError('the complete caller path must consume every supplied incoming')
            return tuple(path)
        if operation.id == shared['split_branch'].id:
            if visits >= len(arms):
                raise AssertionError('the copy loop exceeded its finite supplied arm sequence')
            selected = arms[visits]
            visits += 1
        elif operation.id == shared['retry_branch'].id:
            selected = 0 if visits < len(arms) else 1
        else:
            selected = choices[operation.id]
        path.append((current, selected))
        current = operation.terminator.successors[selected].block
    raise AssertionError('the supplied caller choices do not reach a finite terminal')


def await_shared_final_program(*, zero_cut=False, depth=2, case_mode='explicit'):
    """Return the original full await graph plus independent tuple metadata."""
    if type(zero_cut) is not bool or type(depth) is not int or depth not in (1, 2):
        raise ValueError('zero_cut/depth require their exact supported values')
    if type(case_mode) is not str or case_mode not in _CASE_MODES:
        raise ValueError('unknown original incoming declaration mode')
    graph, original = await_general_final_program(zero_cut=zero_cut, depth=depth)
    caller = original['caller']
    blocks = {block.id: block for block in caller.blocks}
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    additions = {key: [] for key in ('values', 'operations', 'blocks')}
    entry = blocks[caller.entry]
    counter = DataValue(ValueID('await.shared.counter'), caller.id,
                        BlockArgument(entry.id, len(entry.arguments)), 'builtins.int')
    extractor_choice = DataValue(ValueID('await.shared.extractor.choice'), caller.id,
        BlockArgument(entry.id, len(entry.arguments) + 1), 'builtins.bool')
    additions['values'].extend((counter, extractor_choice))
    values.update((value.id, value) for value in (counter, extractor_choice))
    blocks[entry.id] = replace(entry, arguments=(*entry.arguments, counter.id, extractor_choice.id))

    def formals(name, templates):
        identity = BlockID(name)
        rows = tuple(replace(value, id=ValueID(f'{name}.argument.{slot}'),
            region=caller.id, origin=BlockArgument(identity, slot)) for slot, value in enumerate(templates))
        additions['values'].extend(rows)
        values.update((value.id, value) for value in rows)
        return rows

    def add(operation):
        additions['operations'].append(operation)
        operations[operation.id] = operation
        return operation

    def jump(name, target, actuals):
        uses = tuple(_use(f'{name}.argument.{slot}', value) for slot, value in enumerate(actuals))
        return add(Operation(OperationID(name), 'copy the current original tuple',
            (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(target, tuple(use.id for use in uses)),))))

    def branch(name, condition, destinations, actuals):
        condition_use = _use(name + '.condition', condition)
        groups = tuple(tuple(_use(f'{name}.arm.{arm}.{slot}', value)
            for slot, value in enumerate(actuals)) for arm in range(2))
        return add(Operation(OperationID(name), 'select an original supplied control edge',
            (Behavior.CONTROL,), (condition_use, *groups[0], *groups[1]), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH,
                tuple(Successor(destination, tuple(use.id for use in group))
                      for destination, group in zip(destinations, groups, strict=True)),
                condition=condition_use.id)))

    first = original['calls'][0]
    first_block = next(block for block in caller.blocks if first.id in block.operations)
    if first_block.operations[-1] != first.id:
        raise AssertionError('the existing first advance must end its own original block')
    # Pack the original NEXT request once, then carry every live block value,
    # actual call operand, and the explicit loop-control value around the loop.
    live_ids = list(first_block.arguments)
    for identity in first_block.operations[:-1]:
        live_ids.extend(value for value in operations[identity].results if value not in live_ids)
    live_ids.extend(use.value for use in first.uses if use.value not in live_ids)
    live_ids = list(dict.fromkeys((*live_ids, counter.id)))
    initial = tuple(values[identity] for identity in live_ids)
    counter_slot = live_ids.index(counter.id)
    split_id, merge_id, proceed_id = (BlockID('await.shared.' + label)
                                      for label in ('split', 'merge', 'proceed'))
    arm_ids = tuple(BlockID(f'await.shared.arm.{arm}') for arm in range(2))
    split = formals(split_id.value, initial)
    arms = tuple(formals(identity.value, initial) for identity in arm_ids)
    merged = formals(merge_id.value, initial)
    proceeded = formals(proceed_id.value, initial)
    into = jump('await.shared.enter', split_id, initial)
    blocks[first_block.id] = replace(blocks[first_block.id],
        operations=(*first_block.operations[:-1], into.id))
    choose_id = OperationID('await.shared.choose')
    choose = DataValue(ValueID('await.shared.choose.value'), caller.id,
                       OperationResult(choose_id, 0), 'builtins.bool')
    additions['values'].append(choose)
    add(Operation(choose_id, 'declared choice using this loop-control input',
        (Behavior.COMPUTE,), (_use('await.shared.choose.counter', split[counter_slot]),),
        (choose.id,), effects_complete=True))
    split_branch = branch('await.shared.split.branch', choose, arm_ids, split)
    additions['blocks'].append(Block(split_id, tuple(value.id for value in split),
                                     (choose_id, split_branch.id)))
    jumps = []
    for arm, arguments in enumerate(arms):
        transfer = jump(f'await.shared.arm.{arm}.jump', merge_id, arguments)
        jumps.append(transfer)
        additions['blocks'].append(Block(arm_ids[arm], tuple(value.id for value in arguments), (transfer.id,)))
    step_id = OperationID('await.shared.retry.step')
    next_counter = DataValue(ValueID('await.shared.retry.counter'), caller.id,
                             OperationResult(step_id, 0), 'builtins.int')
    retry = DataValue(ValueID('await.shared.retry.value'), caller.id,
                      OperationResult(step_id, 1), 'builtins.bool')
    additions['values'].extend((next_counter, retry))
    add(Operation(step_id, 'declared next loop-control value and continuation decision',
        (Behavior.COMPUTE,), (_use('await.shared.retry.input', merged[counter_slot]),),
        (next_counter.id, retry.id), effects_complete=True))
    forwarded = tuple(next_counter if slot == counter_slot else value for slot, value in enumerate(merged))
    retry_branch = branch('await.shared.retry.branch', retry, (split_id, proceed_id), forwarded)
    additions['blocks'].append(Block(merge_id, tuple(value.id for value in merged),
                                     (step_id, retry_branch.id)))
    first_map = {old.id: new.id for old, new in zip(initial, proceeded, strict=True)}
    first = replace(first, uses=tuple(replace(use, value=first_map.get(use.value, use.value))
                                     for use in first.uses))
    operations[first.id] = first
    additions['blocks'].append(Block(proceed_id, tuple(value.id for value in proceeded), (first.id,)))
    guards = tuple(ControlEdgeReference(operation.id, 0) for operation in jumps)
    attachments = []
    first_inputs = []
    for attachment in graph.protocol_call_inputs:
        if attachment.site.operation != first.id:
            attachments.append(attachment)
            continue
        template = attachment.cases[0]
        if case_mode == 'missing':
            continue
        cases = ((replace(template, guard=None),) if case_mode == 'universal' else
                 tuple(replace(template, guard=guard) for guard in guards[:1 if case_mode == 'partial' else 2]))
        updated = replace(attachment, cases=cases)
        attachments.append(updated)
        first_inputs.append(updated)

    # Select between two real extraction operations. Both call the very same
    # implementation region; each has private N/R result landings and returns
    # the complete produced tuple to the original shared caller consumers.
    old_extract = original['extract']
    extract_block = blocks[next(block.id for block in caller.blocks if old_extract.id in block.operations)]
    original_actuals = {use.id: use for use in old_extract.uses}
    extract_values = tuple(values[original_actuals[identity].value] for identity in old_extract.invoke_arguments)
    if len(extract_values) != 3 or type(extract_values[0]) is not ProtocolValue:
        raise AssertionError('the real final interface must consume packet/world/context')
    extractor_blocks = tuple(BlockID(f'await.shared.extract.{arm}.entry') for arm in range(2))
    extractor_branch = branch('await.shared.extract.branch', extractor_choice, extractor_blocks, extract_values)
    blocks[extract_block.id] = replace(extract_block,
        operations=(*extract_block.operations[:-1], extractor_branch.id))
    extractor_records, right_rows, right_receipts = [], [], []
    left_rows = tuple(row for row in original['final_rows'] if row.operation == old_extract.id)
    left_input = original['extract_input']
    for arm, entry_id in enumerate(extractor_blocks):
        inputs = formals(entry_id.value, extract_values)
        identity = old_extract.id if arm == 0 else OperationID('await.shared.extract.right')
        use_map = {use.id: use.id if arm == 0 else UseID('await.shared.extract.right.' + use.id.value)
                   for use in old_extract.uses}
        actual_map = {old.id: new.id for old, new in zip(extract_values, inputs, strict=True)}
        uses = tuple(replace(use, id=use_map[use.id], value=actual_map.get(use.value, use.value))
                     for use in old_extract.uses)
        edges, landings, returns, own_results, targets = [], {}, {}, {}, {}
        for number, original_edge in enumerate(old_extract.terminator.successors):
            kind = original_edge.kind
            label = 'normal' if kind is ExitKind.NORMAL else 'raise'
            target = blocks[original_edge.block]
            output_templates = tuple(values[value] for value in target.arguments)
            landing_id = BlockID(f'await.shared.extract.{arm}.{label}')
            outputs = formals(landing_id.value, output_templates)
            handoff = jump(f'await.shared.extract.{arm}.{label}.join', target.id, outputs)
            landing = Block(landing_id, tuple(value.id for value in outputs), (handoff.id,))
            additions['blocks'].append(landing)
            edges.append(CompletionSuccessor(kind, landing_id,
                tuple(CompletionResult(slot) for slot in range(len(outputs)))))
            port = ControlEdgeReference(identity, number)
            own_results[kind] = tuple(InvokeLiteralResult(port, CompletionResult(slot))
                                      for slot in range(len(outputs)))
            landings[kind], returns[kind] = landing, handoff
            targets[kind] = operations[target.operations[-1]]
        operation = replace(old_extract, id=identity, uses=uses,
            invoke_arguments=tuple(use_map[use] for use in old_extract.invoke_arguments),
            terminator=replace(old_extract.terminator, successors=tuple(edges)))
        if arm == 0:
            operations[identity] = operation
        else:
            add(operation)
        input_ = OwnedUse(identity, use_map[left_input.use])
        rows = left_rows if arm == 0 else tuple(replace(row, operation=identity,
            contract=replace(row.contract, input_use=input_.use,
                output=InvokeLiteralResult(ControlEdgeReference(identity, row.slot),
                                          row.contract.output.result))) for row in left_rows)
        if arm:
            right_rows.extend(rows)
            for row in rows:
                kind = operation.terminator.successors[row.slot].kind
                right_receipts.append(ProtocolResultConsumers(_ref(row), (HostTerminal(targets[kind].id),)))
        additions['blocks'].append(Block(entry_id, tuple(value.id for value in inputs), (operation.id,)))
        extractor_records.append({
            'operation': operation, 'extract': operation, 'parent_call': operation,
            'block': additions['blocks'][-1], 'input': input_, 'extract_input': input_,
            'rows': rows, 'final_rows': rows, 'sites': tuple(_ref(row) for row in rows),
            'own_results_by_kind': own_results, 'landings': landings,
            'return_jumps': returns, 'terminals': targets,
            'final': targets[ExitKind.NORMAL],
            'primitive': original['primitive'], 'stage_operations': original['stage_operations'],
            'stage_records': original['stage_records'],
        })
    caller = replace(caller, blocks=tuple(blocks[block.id] for block in caller.blocks) + tuple(additions['blocks']))
    right_input = extractor_records[1]['input']
    receipts = tuple(replace(receipt, targets=(*receipt.targets, right_input))
        if left_input in receipt.targets else receipt for receipt in graph.protocol_result_consumers)
    graph = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions),
        operations=tuple(operations[operation.id] for operation in graph.operations) + tuple(additions['operations']),
        values=(*graph.values, *additions['values']),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in caller.blocks))
            if scope.region == caller.id else scope for scope in graph.control_scopes),
        protocol_call_inputs=tuple(attachments),
        protocol_operations=(*graph.protocol_operations, *right_rows),
        protocol_result_consumers=(*receipts, *right_receipts))
    block_index = {block.id: block for block in caller.blocks}
    calls = (first, *original['calls'][1:])
    drivers = ({**original['drivers'][0], 'caller_call': first}, *original['drivers'][1:])
    shared = {
        'caller': caller, 'case_mode': case_mode, 'entry': block_index[first_block.id],
        'enter': into, 'first_advance': first,
        'first_rows': tuple(row for row in original['call_rows'] if row.operation == first.id),
        'first_inputs': tuple(first_inputs),
        'first_links': tuple(row for row in original['links'] if row.advance.operation == first.id),
        'split': block_index[split_id], 'split_branch': split_branch,
        'arms': tuple(block_index[identity] for identity in arm_ids), 'jumps': tuple(jumps),
        'merge': block_index[merge_id], 'guards': guards, 'retry_branch': retry_branch,
        'backedge': ControlEdgeReference(retry_branch.id, 0),
        'proceed_edge': ControlEdgeReference(retry_branch.id, 1),
        'proceed': block_index[proceed_id], 'condition': retry,
        'counter': counter, 'counter_slot': counter_slot,
        'conditions': {'split': choose, 'retry': retry, 'extractor': extractor_choice},
        'tuples': {'initial': initial, 'split': split, 'arms': arms, 'merge': merged,
                   'backedge': forwarded, 'proceed': proceeded},
        'extractor_branch': extractor_branch, 'selection_block': block_index[extract_block.id],
        'extractors': tuple(extractor_records),
        'shared_callee': old_extract.callee, 'stage_records': original['stage_records'],
        'stage_operations': original['stage_operations'], 'primitive': original['primitive'],
        'base_choices': {**original['caller_choices'], into.id: 0,
            **{operation.id: 0 for operation in jumps},
            **{operation.id: 0 for record in extractor_records for operation in record['return_jumps'].values()}},
    }
    result_details = {**original, 'caller': caller, 'calls': calls, 'drivers': tuple(drivers),
        'extract': extractor_records[0]['operation'], 'parent_call': extractor_records[0]['operation'],
        'extract_input': extractor_records[0]['input'],
        'final_rows': (*left_rows, *right_rows),
        'final_sites': tuple(_ref(row) for row in (*left_rows, *right_rows)),
        'extraction_ports': tuple(record['own_results_by_kind'][kind][0]
            for record in extractor_records for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
        'case_mode': case_mode, 'shared_final': shared}
    result_details['caller_path'] = shared_final_caller_path(graph, result_details)
    shared['caller_path'] = result_details['caller_path']
    return graph, result_details


__all__ = ['await_shared_final_program', 'shared_final_caller_path']

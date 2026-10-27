"""Call-context projections of original copy-dependent Uses.

Frames are static call paths, never invocations or alternative producers.
This query does not treat computations, packet projections or state writes as
identity edges. All derived work shares the caller's ConnectionContext budget.
"""
from collections import deque
from copy import deepcopy

from .copy_flow import flow, inventory_flow, selected
from .model import (CompletionResult, ExitKind, InvokeLiteralResult,
                    OperationResult, TerminatorKind)
from .protocol_flow import ProtocolPort
from .protocols import OwnedUse
from .structured import ControlEdgeReference


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                value_identity_verified=False, transformation_authorized=False)


def _status(may, must):
    return ('NOT_CHECKED' if may is None or must is None else
            'DECLARED' if must else 'CONDITIONAL' if may else 'NOT_APPLICABLE')


def _binding(may, must):
    return {'match': must, 'may': may, 'routes': (),
            'gaps': ('copy_consumer_membership_unresolved',)
                    if may is None or must is None else (), **_flags()}


def prepare_index(index):
    """Once per validated ProgramIndex; original anchors, no return joins.

    Templates are private and never mutated. Public reports detach them. This
    preparation and raw-anchor presentation cost is separate from derived work.
    """
    calls, arguments, all_arguments = {r: [] for r in index.regions}, {}, {}
    for operation in index.graph.operations:
        term = operation.terminator
        invoke = term is not None and term.kind is TerminatorKind.INVOKE
        if operation.callee is None and not invoke:
            all_arguments[operation.id] = tuple({'ordinal': ordinal,
                'actual': OwnedUse(operation.id, use.id), 'formal': None,
                'may': None, 'must': None, 'binding': _binding(None, None)}
                for ordinal, use in enumerate(operation.uses))
            continue
        calls[index._blocks[index._operation_blocks[operation.id]]].append(operation)
        actuals = operation.invoke_arguments if invoke else operation.call_arguments
        entry = (None if operation.callee is None else
                 index._block_records[index.regions[operation.callee].entry])
        arguments[operation.id] = tuple({'ordinal': ordinal,
            'actual': OwnedUse(operation.id, identity),
            'formal': None if entry is None else index.values[entry.arguments[ordinal]].origin,
            'may': None, 'must': None, 'binding': _binding(None, None)}
            for ordinal, identity in enumerate(actuals))
        all_arguments[operation.id] = arguments[operation.id]
    index._copy_consumer_originals = ({region: tuple(rows) for region, rows in calls.items()}, arguments)
    index._operation_argument_templates = all_arguments
    index._copy_consumer_preparation = {
        'copy_consumer_original_calls': sum(map(len, calls.values())),
        'copy_consumer_original_arguments': sum(map(len, arguments.values())),
        'copy_consumer_index_operations': len(index.operations),
        'operation_original_argument_templates': sum(map(len, all_arguments.values())),
        'copy_consumer_return_joins_precomputed': 0}


def _prepare(ctx):
    ctx.preparation.update(ctx.index._copy_consumer_preparation)
    ctx.preparation['copy_consumer_program_index_reused'] = True
    ctx.preparation['copy_consumer_prepared_value_use_index_reused'] = True
    return ctx.index._copy_consumer_originals


def _return_rows(ctx, parent_call, may, must):
    """Derive interfaces only for this frame and stop at the first failed charge."""
    if parent_call is None:
        return
    call = ctx.operations[parent_call]
    term = call.terminator
    invoke = term is not None and term.kind is TerminatorKind.INVOKE
    for exit_ in ctx.regions[call.callee].exits:
        if not ctx.spend('copy_consumer_return_exits'):
            return
        for slot in range(len(exit_.types)):
            if not ctx.spend('copy_consumer_return_slots'):
                return
            targets = []
            if not invoke and exit_.kind is ExitKind.NORMAL:
                targets.append((OperationResult(call.id, slot), None))
            elif invoke:
                for number, edge in enumerate(term.successors):
                    if not ctx.spend('copy_consumer_return_edges'):
                        return
                    if edge.kind is not exit_.kind:
                        continue
                    for position, actual in enumerate(edge.arguments):
                        if not ctx.spend('copy_consumer_return_positions'):
                            return
                        if type(actual) is CompletionResult and actual.index == slot:
                            targets.append((InvokeLiteralResult(
                                ControlEdgeReference(call.id, number), actual), position))
            if not targets:
                continue
            for site in ctx.index._exit_ports[(call.callee, exit_.name, slot)]:
                for target, position in targets:
                    if not ctx.spend('copy_consumer_returns'):
                        return
                    possible = _membership(ctx, may, site.operation, site.use.value, 'may')
                    definite = _membership(ctx, must, site.operation, site.use.value, 'must')
                    binding = _binding(possible, definite)
                    yield dict(kind=exit_.kind, slot=slot,
                        actual=OwnedUse(site.operation, site.use.id),
                        caller_result=target, landing_position=position,
                        may=possible, must=definite, binding=binding,
                        status=_status(possible, definite), gaps=binding['gaps'])


def _membership(ctx, before, operation, value, mode):
    if before is None:
        return None
    if value in before.get(operation, ()):
        return True
    return None if any(current == mode for current, _ in ctx._copy_consumer_bound_events) else False


def consumer_graph(ctx, source, choices=()):
    """Internal projection; cached only within this shared query context."""
    choices = selected(ctx, ctx._returns.guards, choices)
    cache = getattr(ctx, '_copy_consumer_graphs', None)
    if cache is None:
        cache = ctx._copy_consumer_graphs = {}
    cache_key = source, choices
    if cache_key in cache:
        return cache[cache_key]
    original_calls, original_arguments = _prepare(ctx)
    port = ctx._ports.get(source) or ctx.port(source)
    operation = None if port is None else port.operation
    if operation is None:
        operation = getattr(source, 'operation', None)
    if operation not in ctx.region_of:
        # A budget can stop resolution but must not select an unrelated root.
        result = dict(source=source, choices=choices, frames=(), status='PARTIAL',
            gaps=('copy_consumer_source_unresolved',), cursor={'phase': 'source'},
            inventory=dict(enumerated_frames=0, checked_frames=0, frames_total=None,
                enumerated_consumers=0, consumers_total=None,
                known_inventory_complete=False, proofs_complete=False, cursor={'phase': 'source'}),
            budget=_budget(ctx), preparation=dict(ctx.preparation), **_flags())
        cache[cache_key] = result
        return result
    root_region = ctx.region_of[operation]
    pending = deque([((), root_region, None, (), (), (), (root_region,))])
    frames, all_gaps, cursor = [], [], None
    inventory_complete, proofs_complete, checked = True, True, 0
    conditional_inventory = False
    previous = ctx._returns.guards
    previous_bounds = getattr(ctx, '_copy_consumer_bounds', False)
    previous_events = getattr(ctx, '_copy_consumer_bound_events', [])
    ctx._copy_consumer_bounds = True
    ctx._copy_consumer_bound_events = []
    ctx._returns.guards = choices
    try:
        while pending:
            key, region, parent_call, inputs, may_seeds, must_seeds, ancestry = pending.popleft()
            local, boundaries, consumers, call_rows, return_rows = [], [], [], [], []
            may = must = None
            # Keep root and raw call anchors even when the first charge fails.
            if ctx.spend('copy_consumer_frames', len(key) + 1):
                if not key:
                    membership = inventory_flow(ctx, source, choices)
                    may = membership['before']
                    conditional_inventory = membership['conditional']
                    must = None if conditional_inventory else flow(ctx, source, choices, mode='must')
                    if conditional_inventory:
                        local.extend(membership['gaps'])
                        inventory_complete = proofs_complete = False
                    may_seeds = () if port is None else port.values
                    must_seeds = may_seeds
                else:
                    entry = ctx.blocks[ctx.regions[region].entry]
                    guard = ctx.selected_edges(choices, region=region)
                    may = ctx._fresh_copies(ProtocolPort(None, entry.operations[0],
                        may_seeds, 'before'), guard=guard or None, mode='may')
                    must = None if conditional_inventory else ctx._fresh_copies(
                        ProtocolPort(None, entry.operations[0], must_seeds, 'before'),
                        guard=guard or None, mode='must')
            if may is None or must is None:
                local.append('copy_consumer_flow_unresolved')
                proofs_complete = False
            if may is None:
                inventory_complete = False
            if 'call_return_guard_context_unresolved' in ctx._returns.gaps:
                local.append('copy_consumer_guard_context_unresolved')
                inventory_complete = proofs_complete = False
            if may is not None:
                seen = set()
                from .protocol_connection_validation import _consumer_role
                for at, values in may.items():
                    if not ctx.spend('copy_consumer_positions', 1 + len(values)):
                        break
                    if values and not ctx.operations[at].effects_complete:
                        local.append('copy_consumer_effects_incomplete')
                        inventory_complete = False
                    for value in sorted(values, key=lambda item: item.wire):
                        for site in ctx.index._consumers[value]:
                            if not ctx.spend('copy_consumer_indexed_uses'):
                                break
                            if site.operation != at or site.use.id in seen:
                                continue
                            seen.add(site.use.id)
                            owner = ctx.operations[at]
                            if not _consumer_role(owner, site.use.id):
                                continue
                            actual = OwnedUse(at, site.use.id)
                            definite = _membership(ctx, must, at, value, 'must')
                            term = owner.terminator
                            terminal = term is not None and term.kind in (
                                TerminatorKind.RETURN, TerminatorKind.RAISE)
                            call = owner.callee is not None or term is not None and term.kind is TerminatorKind.INVOKE
                            kind = (next(exit_.kind for exit_ in ctx.regions[region].exits
                                if exit_.name == term.exit) if terminal else None)
                            slot = term.values.index(site.use.id) if terminal else None
                            binding = _binding(True, definite)
                            consumers.append(dict(key=(key, actual), actual=actual,
                                role='EXIT' if terminal else 'CALL_ARGUMENT' if call else 'OPERATION',
                                kind=kind, slot=slot, may=True, must=definite, binding=binding,
                                status=_status(True, definite), gaps=binding['gaps']))
                            if not owner.effects_complete:
                                local.append('copy_consumer_effects_incomplete')
                                inventory_complete = False
                        if ctx.budget.truncated:
                            break
                    if ctx.budget.truncated:
                        break
            for call in original_calls[region]:
                args, checked_arguments = [], True
                for raw in original_arguments[call.id]:
                    if not ctx.spend('copy_consumer_arguments'):
                        # Preserve the prepared complete unknown tuple without
                        # walking/rebuilding its unexamined suffix.
                        args = original_arguments[call.id]
                        checked_arguments = False
                        break
                    use = ctx.owned_use(call.id, raw['actual'].use)
                    possible = _membership(ctx, may, call.id, use.value, 'may')
                    definite = _membership(ctx, must, call.id, use.value, 'must')
                    args.append({**raw, 'may': possible, 'must': definite,
                                 'binding': _binding(possible, definite)})
                args = tuple(args)
                affected = (True if any(row['may'] is True for row in args) else
                            None if not checked_arguments or any(row['may'] is None for row in args) else False)
                call_gaps, child = [], None
                if affected is not False:
                    if call.callee is None:
                        call_gaps.append('copy_consumer_native_boundary_unresolved')
                    elif call.callee in ancestry:
                        call_gaps.append('copy_consumer_recursion_unresolved')
                    elif (ctx.selected_edges(choices, region=call.callee)
                          and len(ctx._returns.callers[call.callee]) > 1):
                        call_gaps.append('copy_consumer_guard_context_unresolved')
                    elif affected is True and ctx.spend('copy_consumer_call_paths', len(key) + 1):
                        child = (*key, call.id)
                        entry = ctx.blocks[ctx.regions[call.callee].entry]
                        child_may = tuple(entry.arguments[row['ordinal']] for row in args if row['may'] is True)
                        child_must = tuple(entry.arguments[row['ordinal']] for row in args if row['must'] is True)
                        pending.append((child, call.callee, call.id, args, child_may,
                                        child_must, (*ancestry, call.callee)))
                    else:
                        call_gaps.append('copy_consumer_call_membership_unresolved')
                if call_gaps:
                    local.extend(call_gaps)
                    inventory_complete = proofs_complete = False
                call_rows.append(dict(key=(key, call.id), operation=call.id, callee=call.callee,
                    arguments=args, child_frame=child,
                    status='NOT_APPLICABLE' if affected is False else
                           'PARTIAL' if call_gaps or child is None else 'DECLARED',
                    gaps=tuple(call_gaps)))
            return_rows.extend(_return_rows(ctx, parent_call, may, must))
            if not key and ctx._returns.callers.get(region) and (may is None or any(
                    row['role'] == 'EXIT' for row in consumers) or any(
                    mode == 'may' for mode, _ in ctx._copy_consumer_bound_events)):
                local.append('copy_consumer_root_caller_context_unresolved')
                inventory_complete = proofs_complete = False
                boundaries.extend(dict(kind='ROOT_CALLER_CONTEXT', operation=call.id,
                    callee=region, status='PARTIAL',
                    gaps=('copy_consumer_root_caller_context_unresolved',))
                    for call in ctx._returns.callers[region])
            if ctx.budget.truncated:
                local.append('copy_consumer_budget')
                inventory_complete = proofs_complete = False
                cursor = cursor or {'phase': 'copy_consumer_frames', 'frame': key}
            if ctx._copy_consumer_bound_events:
                local.append('copy_consumer_partial_bounds')
                proofs_complete = False
                if any(mode == 'may' for mode, _ in ctx._copy_consumer_bound_events):
                    inventory_complete = False
            checked += int(not local)
            frames.append(dict(key=key, region=region, parent_call=parent_call,
                may_seeds=tuple(may_seeds), must_seeds=tuple(must_seeds), inputs=inputs,
                consumers=tuple(consumers), calls=tuple(call_rows), returns=tuple(return_rows),
                boundaries=tuple(boundaries), status='PARTIAL' if local else 'DECLARED',
                gaps=tuple(dict.fromkeys(local))))
            all_gaps.extend(local)
    finally:
        ctx._returns.guards = previous
        ctx._copy_consumer_bounds = previous_bounds
        ctx._copy_consumer_bound_events = previous_events
    count = sum(len(frame['consumers']) for frame in frames)
    ctx.preparation['copy_consumer_raw_call_anchors_presented'] = sum(
        len(frame['calls']) for frame in frames)
    result = dict(source=source, choices=choices, frames=tuple(frames),
        inventory=dict(enumerated_frames=len(frames), checked_frames=checked,
            frames_total=len(frames) if inventory_complete else None,
            enumerated_consumers=count, consumers_total=count if inventory_complete else None,
            known_inventory_complete=inventory_complete, proofs_complete=proofs_complete,
            cursor=cursor), status='PARTIAL' if all_gaps else 'DECLARED',
        gaps=tuple(dict.fromkeys(all_gaps)), cursor=cursor, budget=_budget(ctx),
        preparation=dict(ctx.preparation), **_flags())
    cache[cache_key] = result
    return result


def _budget(ctx):
    return dict(limit=ctx.budget.limit, used=ctx.budget.used,
                truncated=ctx.budget.truncated, costs=dict(ctx.budget.costs))


def copy_consumers(index, source, *, guard=None, budget=4096):
    from scar.ir.execution.validity_budget import ValidityBudget
    from .protocol_connection_flow import ConnectionContext
    ctx = ConnectionContext(index.graph, index=index, budget=ValidityBudget(budget))
    return deepcopy(consumer_graph(ctx, source, ctx.selected_edges(guard)))

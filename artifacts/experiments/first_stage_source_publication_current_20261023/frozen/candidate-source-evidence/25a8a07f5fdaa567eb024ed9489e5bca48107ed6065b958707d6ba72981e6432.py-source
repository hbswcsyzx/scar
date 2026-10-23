"""Evaluation-relative copy flow over the original CFG, shared by projections."""
from .structured import ControlEdgeReference

def selected(ctx, *groups):
    return ctx.selected_edges(tuple(edge for group in groups for edge in ctx.selected_edges(group)))


def required_choices(ctx, source):
    """Original edges necessary to reach this source evaluation point.

    This is conditional on the source being evaluated, not a prediction that
    it will be evaluated. An edge cut must make that original point unreachable.
    """
    port = ctx.port(source)
    if port is None or port.operation is None or port.gap is not None:
        return (), False
    operation = ctx.operations[port.operation]
    point = (operation.terminator.successors[port.edge].block if port.phase == 'edge'
             else ctx.block_of[port.operation])
    key = ctx.region_of[port.operation], point
    if not hasattr(ctx, '_await_required_source_edges'):
        ctx._await_required_source_edges = {}
    if key not in ctx._await_required_source_edges:
        region, outgoing, incoming, reached, _ = ctx._edges(key[0])
        pending, ancestors = [point], set()
        while pending:
            if not ctx.spend('await_source_ancestor_blocks'):
                return (), False
            block = pending.pop()
            if block in ancestors:
                continue
            ancestors.add(block)
            for parent, _ in incoming[block]:
                if not ctx.spend('await_source_ancestor_edges'):
                    return (), False
                pending.append(parent)
        needed = []
        for block in sorted(ancestors, key=lambda item: item.wire):
            if not ctx.spend('await_source_control_candidates'):
                return (), False
            edges = outgoing[block]
            relevant = tuple(edge for edge in edges if edge[2] in ancestors)
            if len(edges) < 2 or len(relevant) != 1:
                continue
            chosen = relevant[0]
            todo, seen = [region.entry], set()
            while todo:
                if not ctx.spend('await_source_control_cut_blocks'):
                    return (), False
                current = todo.pop()
                if current in seen:
                    continue
                seen.add(current)
                for edge in outgoing[current]:
                    if not ctx.spend('await_source_control_cut_edges'):
                        return (), False
                    if edge[:2] != chosen[:2]:
                        todo.append(edge[2])
            if point in reached and point not in seen:
                needed.append(ControlEdgeReference(chosen[0], chosen[1]))
        ctx._await_required_source_edges[key] = tuple(needed), point in reached
    edges, complete = ctx._await_required_source_edges[key]
    if port.phase == 'edge':
        edges = selected(ctx, edges, ControlEdgeReference(port.operation, port.edge))
    return edges, complete


def flow(ctx, source, choices=(), *, mode='must'):
    port = ctx.port(source)
    if port is None or port.gap is not None or port.operation is None:
        return None
    previous = ctx._returns.guards
    try:
        required, complete = required_choices(ctx, source)
        if not complete:
            return None
        try:
            ctx._returns.guards = selected(ctx, previous, choices, required)
        except ValueError:
            if not hasattr(ctx, '_await_flow_choice_conflicts'):
                ctx._await_flow_choice_conflicts = set()
            ctx._await_flow_choice_conflicts.add((source, ctx.selected_edges(choices), previous))
            return {}
        local = ctx.selected_edges(ctx._returns.guards, region=ctx.region_of[port.operation])
        return ctx._fresh_copies(port, guard=local or None, mode=mode)
    finally:
        ctx._returns.guards = previous


def inventory_flow(ctx, source, choices=()):
    """Conditional may inventory for independently proved multi-visit guards.

    Ordinary must flow is untouched. The relaxed choices enumerate candidate
    Uses only; the original context and prefix remain separate receipts.
    """
    previous = ctx._returns.guards
    key = source, ctx.selected_edges(choices), previous
    originals = ctx.selected_edges((*previous, *choices))
    scopes = getattr(ctx, '_copy_inventory_scopes', None)
    if scopes is None:
        scopes = ctx._copy_inventory_scopes = {}
    port = ctx._ports.get(source)
    scope_key = (None if port is None else
                 (port.operation, port.phase, port.edge, originals))
    before = flow(ctx, source, choices, mode='may')
    result = {'before': before, 'guarded_flow': before, 'conditional': False,
              'choices': choices, 'required_prefix': (), 'relaxed_choices': (), 'gaps': ()}

    def unfinished():
        # Only a previously established source-point/control receipt may
        # survive an unpaid value-slot join. No flow or bounds result is
        # cached/replayed here; ordinary flow retains its existing hooks.
        known = scopes.get(scope_key)
        if ctx.budget.truncated and known is not None:
            return {**result, **known, 'before': None, 'conditional': True,
                'pending': True, 'gaps': ('copy_inventory_loop_context_unproved',
                                        'copy_inventory_context_join_budget')}
        return result

    conflict = key in getattr(ctx, '_await_flow_choice_conflicts', ())
    if ctx.budget.truncated:
        return unfinished()
    port = ctx.port(source)
    if port is not None:
        scope_key = port.operation, port.phase, port.edge, originals
    required, complete = required_choices(ctx, source)
    if port is None or not complete or ctx.budget.truncated:
        return unfinished()
    absent_source = before is not None and port.operation not in before
    if before is not None and not conflict and not absent_source:
        return result

    def cyclic(edge):
        memo = getattr(ctx, '_copy_inventory_cycles', None)
        if memo is None:
            memo = ctx._copy_inventory_cycles = {}
        if edge in memo:
            return memo[edge]
        region = ctx.region_of[edge.operation]
        _, outgoing, _, _, _ = ctx._edges(region)
        start = ctx.operations[edge.operation].terminator.successors[edge.successor_index].block
        target = ctx.block_of[edge.operation]
        pending, seen = [start], set()
        while pending:
            if not ctx.spend('copy_inventory_cycle_blocks'):
                return None
            block = pending.pop()
            if block == target:
                memo[edge] = True
                return True
            if block in seen:
                continue
            seen.add(block)
            for original in outgoing[block]:
                if not ctx.spend('copy_inventory_cycle_edges'):
                    return None
                pending.append(original[2])
        memo[edge] = False
        return False

    own = ControlEdgeReference(port.operation, port.edge) if port.phase == 'edge' else None
    if own is not None and any(edge.operation == own.operation and edge != own for edge in originals):
        return result
    if absent_source and not conflict:
        reason = any(edge != own and cyclic(edge) is True for edge in originals)
    elif conflict:
        by_operation, conflicting = {}, []
        for prefix in required:
            if not ctx.spend('copy_inventory_required_choices'):
                return unfinished()
            by_operation[prefix.operation] = prefix
        for edge in originals:
            if not ctx.spend('copy_inventory_conflicting_choices'):
                return unfinished()
            prefix = by_operation.get(edge.operation)
            if prefix is not None and prefix != edge:
                conflicting.append(edge)
        reason = bool(conflicting) and all(cyclic(edge) is True for edge in conflicting)
    else:
        combined = selected(ctx, originals, required)
        local = ctx.selected_edges(combined, region=ctx.region_of[port.operation])
        reason = ctx._guard_entry_ambiguity(port, local) == 'selected_loop_entry_requires_occurrence_context'
    if not reason or ctx.budget.truncated:
        return unfinished()
    relaxed = []
    for edge in originals:
        if not ctx.spend('copy_inventory_guard_candidates'):
            break
        repeated = cyclic(edge)
        if repeated is None:
            break
        if edge == own or not repeated:
            relaxed.append(edge)
    if ctx.budget.truncated:
        return unfinished()
    try:
        ctx._returns.guards = ()
        candidate = flow(ctx, source, tuple(relaxed), mode='may')
    finally:
        ctx._returns.guards = previous
    if ctx.budget.truncated:
        return unfinished()
    if candidate is not None and port.operation not in candidate:
        return result
    if candidate is not None and not ctx.budget.truncated:
        scopes[scope_key] = {'required_prefix': required, 'relaxed_choices': tuple(relaxed)}
    result = {**result, 'before': candidate, 'conditional': True,
        'required_prefix': required, 'relaxed_choices': tuple(relaxed),
        'gaps': ('copy_inventory_loop_context_unproved',)}
    return result



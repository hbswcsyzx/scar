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



"""Conditional host order from original CFG and synchronous call links.

These are query-local indexes of validated records, never another producer,
clock or resource-completion graph. Source/runtime applicability stays open.
"""
from collections import deque
from dataclasses import dataclass
from itertools import chain

from scar.ir.program.model import TerminatorKind

from .coordinates import OccurrencePhase, OccurrencePoint, UnresolvedHostThread
from .ids import BlockVisitID, OperationOccurrenceID


@dataclass(frozen=True, slots=True)
class HostOrderStep:
    source: OccurrencePoint
    target: OccurrencePoint
    rule: str
    support: tuple


def _known(ctx, point):
    if type(point) is not OccurrencePoint or point.operation not in ctx.occurrences:
        return False
    if point.phase is OccurrencePhase.EDGE:
        transfer = ctx.outgoing.get(point.operation)
        return transfer is not None and transfer.successor_index == point.successor_index
    return True


def local_point_precedes(ctx, left, right):
    """Preserve the original same-activation True/False/None semantics."""
    if not _known(ctx, left) or not _known(ctx, right):
        return None
    a, b = ctx.occurrences[left.operation], ctx.occurrences[right.operation]
    if ctx.activation_of(a.id) != ctx.activation_of(b.id):
        return None
    phases = {OccurrencePhase.BEFORE: 0, OccurrencePhase.AFTER: 1, OccurrencePhase.EDGE: 2}
    if a.visit == b.visit:
        positions = getattr(ctx, 'host_operation_positions', None)
        if positions is None:
            block = ctx.blocks[ctx.visits[a.visit].block]
            return (block.operations.index(a.operation), phases[left.phase]) <= (
                block.operations.index(b.operation), phases[right.phase])
        return (positions[a.operation], phases[left.phase]) <= (positions[b.operation], phases[right.phase])
    chains = getattr(ctx, 'host_visit_chains', None)
    if chains is not None:
        component, rank = chains
        return True if component[a.visit] == component[b.visit] and rank[a.visit] < rank[b.visit] else None
    # Only construction before index preparation can use this finite fallback.
    cursor, seen = b.visit, set()
    while cursor not in seen and cursor in ctx.incoming:
        seen.add(cursor)
        cursor = ctx.occurrences[ctx.incoming[cursor].operation].visit
        if cursor == a.visit:
            return True
    return None


def prepare_host_order(ctx):
    """Prepare immutable step tuples once, after core flow and call validation."""
    ctx.host_operation_positions = {identity: index for block in ctx.blocks.values()
                                    for index, identity in enumerate(block.operations)}
    occurrences = {(row.visit, row.operation): row for row in ctx.occurrences.values()}
    adjacency, sources = {}, {}

    def thread(operation):
        row = ctx.occurrences[operation]
        return ctx.segments[ctx.visits[row.visit].segment].host_thread

    def same_thread(caller, child):
        a, b = thread(caller), thread(child)
        return type(a) is not UnresolvedHostThread and type(b) is not UnresolvedHostThread and a == b

    def add(left, right, rule, association):
        step = HostOrderStep(left, right, rule, (association,))
        adjacency.setdefault(left, []).append(step)
        owner = ctx.activation_of(left.operation)
        sources.setdefault(owner, {}).setdefault(left, None)

    for row in ctx.model.call_activations:
        operation = ctx.core_operations[ctx.occurrences[row.caller].operation]
        if type(row.entry) is BlockVisitID:
            visit = ctx.visits[row.entry]
            block = ctx.blocks[visit.block]
            first = None if not block.operations else occurrences.get((visit.id, block.operations[0]))
            if first is not None and same_thread(row.caller, first.id):
                add(OccurrencePoint(row.caller, OccurrencePhase.BEFORE),
                    OccurrencePoint(first.id, OccurrencePhase.BEFORE), 'synchronous-call-entry', row)
        if type(row.completion) is OperationOccurrenceID and same_thread(row.caller, row.completion):
            if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
                transfer = ctx.outgoing.get(row.caller)
                if transfer is None:
                    continue
                target = OccurrencePoint(row.caller, OccurrencePhase.EDGE, transfer.successor_index)
            else:
                target = OccurrencePoint(row.caller, OccurrencePhase.AFTER)
            add(OccurrencePoint(row.completion, OccurrencePhase.AFTER), target,
                'synchronous-call-completion', row)
    ctx.host_call_adjacency = {point: tuple(steps) for point, steps in adjacency.items()}
    ctx.host_call_sources = {activation: tuple(points) for activation, points in sources.items()}


def _spend(budget, kind, path):
    return budget is None or budget.spend(kind, path=path)


def host_steps(ctx, point, targets=(), *, budget=None):
    """Original call bridges and local paths to needed host endpoints only."""
    if not _known(ctx, point):
        return
    for step in getattr(ctx, 'host_call_adjacency', {}).get(point, ()):
        if not _spend(budget, 'host_order_edges', 'order.host.call'):
            return
        yield step
    owner = ctx.activation_of(point.operation)
    seen = set()
    for target in chain(getattr(ctx, 'host_call_sources', {}).get(owner, ()), targets):
        if target == point:
            continue
        if not _spend(budget, 'host_order_edges', 'order.host.local'):
            return
        if target in seen:
            continue
        seen.add(target)
        if (_known(ctx, target)
                and ctx.activation_of(target.operation) == owner
                and local_point_precedes(ctx, point, target) is True):
            yield HostOrderStep(point, target, 'actual-host-path', ())


def host_path(ctx, left, right, *, budget=None):
    """Finite reachability; query callers pass the same derived budget."""
    if not _known(ctx, left) or not _known(ctx, right):
        return None
    if left == right:
        return ()
    pending, previous = deque((left,)), {left: None}
    while pending:
        if not _spend(budget, 'host_order_nodes', 'order.host.search'):
            return None
        current = pending.popleft()
        for step in host_steps(ctx, current, (right,), budget=budget):
            if step.target in previous:
                continue
            previous[step.target] = (current, step)
            if step.target == right:
                result, cursor = [], right
                while previous[cursor] is not None:
                    cursor, edge = previous[cursor]
                    result.append(edge)
                return tuple(reversed(result))
            pending.append(step.target)
        if budget is not None and budget.truncated:
            break
    return None


__all__ = ['HostOrderStep', 'prepare_host_order', 'local_point_precedes', 'host_steps', 'host_path']

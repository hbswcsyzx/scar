"""Conditional host order from original CFG, calls and body drives.

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

    def add(left, right, rule, association, gaps=()):
        step = HostOrderStep(left, right, rule, (association, *gaps))
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
    for view in getattr(ctx, 'resolved_body_drives', {}).values():
        caller, association = view['drive'], view['association']
        if view['entry_bridge']:
            add(OccurrencePoint(caller.id, OccurrencePhase.BEFORE),
                OccurrencePoint(view['entry_first'].id, OccurrencePhase.BEFORE),
                'resumable-body-entry', association)
        if view['outcome_bridge']:
            transfer = view['transfer']
            add(OccurrencePoint(view['outcome'].id, OccurrencePhase.AFTER),
                OccurrencePoint(caller.id, OccurrencePhase.EDGE, transfer.successor_index),
                'resumable-body-completion', association, view['canonical_gaps'])
    ctx.host_call_adjacency = {point: tuple(steps) for point, steps in adjacency.items()}
    ctx.host_call_sources = {activation: tuple(points) for activation, points in sources.items()}


def host_cycle_errors(ctx, *, budget=None):
    """Check the union of actual local order and admitted conditional bridges.

    Only bridge endpoints are needed: adjacent points on each captured visit
    chain preserve all local reachability between them. This permits repeated
    body activations while rejecting a causal cycle involving calls and drives.
    A default complete scan is canonical preparation; an explicitly supplied
    query budget is shared and truncation never reports an acyclic graph.
    """
    adjacency, indegree, groups = {}, {}, {}
    preparation = {'endpoints': 0, 'local_edges': 0, 'bridge_edges': 0,
                   'visited': 0, 'status': 'PARTIAL',
                   'cost_scope': 'finite canonical endpoint indexing, sorting and cycle validation'}
    ctx.host_cycle_preparation = preparation

    def spend(kind):
        if _spend(budget, kind, 'order.host.cycle'):
            return True
        ctx.gap('host_cycle_unresolved', 'host_order',
                'shared budget exhausted before the joint occurrence cycle check completed')
        return False

    def edge(left, right):
        adjacency[left].append(right)
        indegree[right] += 1

    phases = {OccurrencePhase.BEFORE: 0, OccurrencePhase.AFTER: 1, OccurrencePhase.EDGE: 2}
    component, rank = ctx.host_visit_chains
    for left, steps in ctx.host_call_adjacency.items():
        for step in steps:
            if not spend('host_cycle_bridges'):
                return None
            for point in (left, step.target):
                if point in adjacency:
                    continue
                if not spend('host_cycle_endpoints'):
                    return None
                adjacency[point], indegree[point] = [], 0
                occurrence = ctx.occurrences[point.operation]
                key = (rank[occurrence.visit], ctx.host_operation_positions[occurrence.operation],
                       phases[point.phase])
                groups.setdefault(component[occurrence.visit], []).append((key, point))
                preparation['endpoints'] += 1
            edge(left, step.target)
            preparation['bridge_edges'] += 1
    # Sorting is charged before work is performed; comparisons have the stated
    # O(P log P) bound, not an assertion that total validation CPU is a budget.
    for points in groups.values():
        if budget is not None and not budget.spend(
                'host_cycle_sort', len(points) * max(1, (len(points) - 1).bit_length()),
                path='order.host.cycle'):
            ctx.gap('host_cycle_unresolved', 'host_order',
                    'shared budget exhausted before joint occurrence endpoint sorting')
            return None
        points.sort(key=lambda item: item[0])
        for (_, left), (_, right) in zip(points, points[1:]):
            if not spend('host_cycle_local_edges'):
                return None
            edge(left, right)
            preparation['local_edges'] += 1
    pending = deque(point for point, count in indegree.items() if count == 0)
    while pending:
        if not spend('host_cycle_nodes'):
            return None
        current = pending.popleft()
        preparation['visited'] += 1
        for target in adjacency[current]:
            if not spend('host_cycle_edges'):
                return None
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    if preparation['visited'] != preparation['endpoints']:
        preparation['status'] = 'CONFLICT'
        ctx.issue('host_occurrence_cycle', 'host_order',
                  'CALL/body bridges and actual local CFG form a strict occurrence causal cycle')
        return False
    preparation['status'] = 'DECLARED_ACYCLIC'
    return True


def _spend(budget, kind, path):
    return budget is None or budget.spend(kind, path=path)


def host_steps(ctx, point, targets=(), *, budget=None):
    """Original call/body bridges and local paths to needed host endpoints only."""
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


__all__ = ['HostOrderStep', 'prepare_host_order', 'host_cycle_errors',
           'local_point_precedes', 'host_steps', 'host_path']

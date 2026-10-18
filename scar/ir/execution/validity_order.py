"""Conditional causal queries over canonical execution and resource boundaries.

Association declarations are retained as assumptions unless an existing
structural relation or an exactly paired HAPPENS_BEFORE source interprets them.
No native clock, producer, or runtime authority is created here.
"""
from collections import deque

from scar.ir.v2.evidence import EvidenceNodeKind, EvidenceRelation

from .common import EvidencePoint, Unresolved
from .content_validation import artifact_key, point_scope
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from .order import EventSignal, PrefixEnd, WorkEnd, WorkStart
from .production import RawRecordRef, SourceEdgeRef
from .work import InvokeBoundaryStateEffect, WithinOperation


def point_run(ctx, point):
    """Return a known run, without treating a host caller as a device executor."""
    if type(point) in (OccurrencePoint, EvidencePoint):
        return point_scope(ctx, point)[0]
    if type(point) in (WorkStart, WorkEnd):
        work = ctx.submissions.get(point.ticket)
        if work is None:
            return None
        origin = work.origin
        return (point_scope(ctx, OccurrencePoint(origin.operation, OccurrencePhase.BEFORE))[0]
                if type(origin) is WithinOperation else origin.point.run)
    if type(point) is PrefixEnd:
        prefix = ctx.queue_prefixes.get(point.prefix)
        return None if prefix is None else point_run(ctx, prefix.observed_at)
    if type(point) is EventSignal:
        record = ctx.event_records.get(point.record)
        return None if record is None else point_run(ctx, record.observed_at)
    return None


def check_validity_point(ctx, point, path):
    if type(point) in (OccurrencePoint, EvidencePoint):
        ctx.check_point(point, path)
        return
    if type(point) in (WorkStart, WorkEnd):
        registry, identity = ctx.submissions, point.ticket
    elif type(point) is PrefixEnd:
        registry, identity = ctx.queue_prefixes, point.prefix
    elif type(point) is EventSignal:
        registry, identity = ctx.event_records, point.record
    else:
        ctx.issue('validity_point', path, 'point is not an exact execution/resource boundary')
        return
    if identity not in registry:
        ctx.issue('validity_point', path, 'point references an absent resource boundary')


def resolve_order_basis(ctx, basis, path):
    """Check all known foreign keys even when the protocol is unsupported."""
    from .effects import resolve_canonical_effect
    from .source_validation import resolve_edge, resolve_raw

    if type(basis) is RawRecordRef:
        return resolve_raw(ctx, basis, path)
    if type(basis) is SourceEdgeRef:
        return resolve_edge(ctx, basis, path)
    if type(basis) in (AccessRef, InvokeBoundaryStateEffect):
        return resolve_canonical_effect(ctx, basis, path)
    if type(basis) is UseRef:
        occurrence = ctx.occurrences.get(basis.operation)
        original = ctx.core_uses.get(basis.use)
        if occurrence is None or original is None or original[0].id != occurrence.operation:
            ctx.issue('validity_basis_use', path, 'basis is not an original Use of this occurrence')
            return None
        return {'use': original[1], 'operation': occurrence,
                'actual': ctx.uses.get((basis.operation, basis.use))}
    if type(basis) is Unresolved:
        ctx.check_point(basis.point, path)
        ctx.gap('validity_basis_unresolved', path, basis.reason)
        return None
    ctx.issue('validity_basis', path, 'unsupported basis variant')
    return None


def _known_point(ctx, point):
    if type(point) is OccurrencePoint:
        if point.operation not in ctx.occurrences:
            return False
        if point.phase is OccurrencePhase.EDGE:
            transfer = ctx.outgoing.get(point.operation)
            return transfer is not None and transfer.successor_index == point.successor_index
        return True
    return ((type(point) in (WorkStart, WorkEnd) and point.ticket in ctx.submissions)
            or (type(point) is PrefixEnd and point.prefix in ctx.queue_prefixes)
            or (type(point) is EventSignal and point.record in ctx.event_records))


def _canonical(ctx, left, right):
    if left == right and _known_point(ctx, left):
        return True
    if type(left) is OccurrencePoint and type(right) is OccurrencePoint:
        return ctx.point_precedes(left, right)
    return None


def _source_pair(ctx, point, artifact, instance):
    key = artifact_key(artifact)
    if type(point) is OccurrencePoint:
        matches = {row.legacy.instance for row in ctx.model.evidence_bindings
                   if row.operation == point.operation and artifact_key(row.legacy.artifact) == key}
        return matches == {instance}
    if type(point) in (WorkStart, WorkEnd):
        matches = {row.instance for row in ctx.model.work_evidence_bindings
                   if row.ticket == point.ticket and artifact_key(row.artifact) == key}
        return matches == {instance}
    return False


def association_strength(ctx, row, basis, path):
    """Interpret only canonical order or an exact original HB source edge."""
    if _canonical(ctx, row.before, row.after) is True and row.before != row.after:
        return 'CONDITIONAL'
    if type(row.basis) is SourceEdgeRef and basis is not None:
        edge = basis['edge']
        if (edge.relation is EvidenceRelation.HAPPENS_BEFORE
                and edge.source.kind is EvidenceNodeKind.OPERATION_INSTANCE
                and edge.target.kind is EvidenceNodeKind.OPERATION_INSTANCE):
            artifact = basis['artifact']
            if type(row.before) in (WorkStart, WorkEnd) or type(row.after) in (WorkStart, WorkEnd):
                ctx.gap('validity_order_whole_boundary_unresolved', path,
                        'source instance pairing does not identify a whole-ticket start/end extent')
                return 'ASSUMPTION'
            aligned = (type(row.before) is OccurrencePoint and type(row.after) is OccurrencePoint
                       and row.before.phase in (OccurrencePhase.AFTER, OccurrencePhase.EDGE)
                       and row.after.phase is OccurrencePhase.BEFORE)
            if (aligned and _source_pair(ctx, row.before, artifact, edge.source.reference)
                    and _source_pair(ctx, row.after, artifact, edge.target.reference)):
                return 'CONDITIONAL'
            ctx.gap('validity_order_pair_unresolved', path,
                    'HAPPENS_BEFORE endpoints have no exact original occurrence/work pairing')
    ctx.gap('validity_order_assumption', path,
            'unparsed causal declaration is an assumption, not a native order interpretation')
    return 'ASSUMPTION'


def _steps(ctx, point, endpoints, associations, budget, *, assumptions):
    for step in ctx.order_adjacency.get(point, ()):
        if not budget.spend('order_edges', path='order.resource'):
            return
        yield step.target, {'source': step.source, 'target': step.target,
                           'rule': step.rule, 'support': step.support}, False
    if type(point) is OccurrencePoint:
        for target in endpoints:
            if target == point:
                continue
            if not budget.spend('order_edges', path='order.host'):
                return
            if _canonical(ctx, point, target) is True:
                yield target, {'source': point, 'target': target,
                               'rule': 'actual-host-path', 'support': ()}, False
    for resolved in associations.get(point, ()):
        is_assumption = resolved['strength'] != 'CONDITIONAL'
        if is_assumption and not assumptions:
            continue
        if not budget.spend('order_edges', path='order.association'):
            return
        row = resolved['row']
        yield row.after, {'source': row.before, 'target': row.after,
                          'rule': 'order-association', 'support': (row,)}, is_assumption


def point_order(ctx, left, right, *, budget):
    """Query causal order without promoting unparsed declarations to support."""
    if not budget.spend('order_queries', path='order.query'):
        return {'status': 'UNRESOLVED', 'path': (), 'truncated': True}
    if _canonical(ctx, left, right) is True:
        return {'status': 'CONDITIONAL', 'path': (), 'truncated': budget.truncated}
    if left != right and _canonical(ctx, right, left) is True:
        return {'status': 'CONTRADICTED', 'path': (), 'truncated': budget.truncated}
    run_left, run_right = point_run(ctx, left), point_run(ctx, right)
    if run_left is not None and run_right is not None and run_left != run_right:
        return {'status': 'CONTRADICTED', 'path': (), 'truncated': budget.truncated}
    associations = {}
    endpoints = dict.fromkeys(point for point in (left, right) if type(point) is OccurrencePoint)
    for resolved in getattr(ctx, 'resolved_order_associations', {}).values():
        if not budget.spend('order_associations', path='order.association-index'):
            break
        if resolved.get('status') == 'CONTRADICTED':
            continue
        row = resolved['row']
        associations.setdefault(row.before, []).append(resolved)
        for point in (row.before, row.after):
            if type(point) is OccurrencePoint:
                endpoints.setdefault(point, None)
    for step in ctx.order_steps:
        if not budget.spend('order_edges', path='order.endpoint-index'):
            break
        for point in (step.source, step.target):
            if type(point) is OccurrencePoint:
                endpoints.setdefault(point, None)

    # Search supported paths first, so an earlier assumption cannot hide a
    # longer supported path. Each phase uses the same finite shared budget.
    for allow_assumptions in (False, True):
        pending, previous = deque([(left, False)]), {(left, False): None}
        found = None
        while pending and not budget.truncated:
            current, assumed = pending.popleft()
            for target, step, extra in _steps(ctx, current, endpoints, associations, budget,
                                              assumptions=allow_assumptions):
                state = target, assumed or extra
                if state in previous:
                    continue
                previous[state] = ((current, assumed), step)
                if target == right:
                    found = state
                    break
                pending.append(state)
            if found is not None:
                break
        if found is not None:
            chain, cursor = [], found
            while previous[cursor] is not None:
                cursor, step = previous[cursor]
                chain.append(step)
            return {'status': 'ASSUMPTION' if found[1] else 'CONDITIONAL',
                    'path': tuple(reversed(chain)), 'truncated': budget.truncated}
        if budget.truncated:
            break
    return {'status': 'UNRESOLVED', 'path': (), 'truncated': budget.truncated}


__all__ = ['point_order', 'point_run', 'check_validity_point',
           'resolve_order_basis', 'association_strength']

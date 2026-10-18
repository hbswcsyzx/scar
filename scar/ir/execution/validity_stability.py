"""Bounded whole-interval invalidator and lifetime inspection.

The independent source universe and canonical effects are both scanned. State
at a single anchor, identical endpoint content, and retention do not erase an
intervening write. Results describe conditional declarations, never authority.
"""
from itertools import chain

from scar.ir.program.model import AccessMode, TerminatorKind

from .common import Unresolved
from .content import EndpointContent, HostConsumer, ObservationConsumer, ResourceConsumer
from .content_validation import artifact_key, target_key
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from .coverage import RegionRef, _Coverage, _ValueCatalog
from .order import WorkEnd, WorkStart
from .production import ExternalEstablishment, HostWrite, RawRecordRef, StateProduction, WorkWrite
from .resources import AllocationTarget, EndedAt, ExplicitHandle
from .validity_order import point_order, point_run
from .work import DirectExecution, Queued


def production_interval(ctx, write):
    """Conservative extent; an outer post is not an exact native last write."""
    from .validity_validation import _actual_post
    writer = write.writer
    if type(writer) is WorkWrite:
        return WorkStart(writer.ticket), WorkEnd(writer.ticket)
    if type(writer) is HostWrite:
        return OccurrencePoint(writer.operation, OccurrencePhase.BEFORE), _actual_post(ctx, writer.operation)
    if type(writer) is ExternalEstablishment:
        return writer.point, writer.point
    return None, None


def read_interval(ctx, resolved):
    read = resolved['read']
    if type(read.consumer) is HostConsumer:
        return read.consumer.interval.start, read.consumer.interval.end
    if type(read.consumer) is ResourceConsumer:
        # An unparsed NativeWorkRead declaration cannot narrow obligations.
        return WorkStart(read.consumer.read.ticket), WorkEnd(read.consumer.read.ticket)
    root = resolved.get('observation_root')
    return (None, None) if root is None else (root.interval.start, root.interval.end)


def read_domain(ctx, resolved):
    from .validity import EndpointDomain, HostDomain, QueueDomain
    read = resolved['read']
    if type(read.placement) is EndpointContent:
        return EndpointDomain(read.placement.target)
    if type(read.consumer) is ResourceConsumer:
        work = ctx.submissions.get(read.consumer.read.ticket)
        if work is not None and type(work.scheduling) is Queued:
            access = ctx.accesses.get(work.scheduling.queue_access)
            binding = None if access is None else ctx.requirements.get(access.requirement)
            from .resources import InstanceTarget
            if binding is not None and type(binding.target) is InstanceTarget:
                return QueueDomain(binding.target.instance)
        if work is not None and type(work.scheduling) is DirectExecution:
            if work.scheduling.thread in ctx.threads:
                return HostDomain(work.scheduling.thread)
        return None
    if type(read.consumer) is HostConsumer:
        identity = read.consumer.subject.operation
    else:
        root = resolved.get('observation_root')
        identity = root.anchor.operation if root is not None and type(root.anchor) is OccurrencePoint else None
    occurrence = ctx.occurrences.get(identity)
    if occurrence is not None:
        thread = ctx.segments[ctx.visits[occurrence.visit].segment].host_thread
        if thread in ctx.threads:
            return HostDomain(thread)
    return None


def _region(ctx, reference):
    if type(reference) is not RegionRef:
        return None
    from scar.ir.v2.values import ValueGraph
    graph = ctx.snapshots.graph(reference.artifact, ValueGraph)
    return None if graph is None else graph.regions.get(reference.region)


def _spatial(ctx, left, right, budget):
    if type(left) is not RegionRef or type(right) is not RegionRef:
        return 'UNRESOLVED'
    if artifact_key(left.artifact) != artifact_key(right.artifact):
        return 'UNRESOLVED'

    class SharedGeometryBudget:
        @property
        def remaining(self):
            return budget.remaining

        def take(self, amount=1):
            return budget.spend('geometry', amount, path='stability.selector')

    geometry = _Coverage(left, (right,), _ValueCatalog.from_snapshots(ctx.snapshots), 1)
    geometry.budget = SharedGeometryBudget()
    a_ref, b_ref = geometry.resolve(left), geometry.resolve(right)
    if a_ref is None or b_ref is None:
        return 'UNRESOLVED'
    a, b = geometry.describe(left, a_ref), geometry.describe(right, b_ref)
    for gap in geometry.gaps:
        item = {'code': gap.code, 'path': 'stability.selector', 'message': gap.reason}
        if item not in budget.gaps:
            budget.gaps.append(item)
    if a is None or b is None:
        return 'UNRESOLVED'
    row_a, bounds_a = a
    row_b, bounds_b = b
    if row_a.allocation != row_b.allocation or bounds_a == () or bounds_b == ():
        return 'DISJOINT'
    if left.region == right.region:
        return 'OVERLAP'
    if bounds_a is None or bounds_b is None:
        return 'POSSIBLE'
    if bounds_a[0][0] >= bounds_b[0][1] or bounds_b[0][0] >= bounds_a[0][1]:
        return 'DISJOINT'
    return 'OVERLAP'


def _selector(write, resolved):
    if resolved is not None and resolved.get('placement') is not None:
        return resolved['placement'][1]
    return getattr(write.placement, 'selector', None)


def _effect_of(write):
    return write.production.effect if type(write.production) is StateProduction else None


def _post(ctx, operation):
    from .validity_validation import _actual_post
    return _actual_post(ctx, operation)


def _read_target(ctx, resolved):
    placement = resolved['read'].placement
    if type(placement) is EndpointContent:
        return placement.target
    selected = None if resolved.get('placement') is None else resolved['placement'][1]
    region = _region(ctx, selected)
    return None if region is None else AllocationTarget(selected.artifact, region.allocation)


def _read_handles(ctx, resolved):
    read = resolved['read']
    if type(read.consumer) is ObservationConsumer:
        return ()
    operation = read.consumer.subject.operation
    subject = resolved.get('subject')
    access = None if subject is None else subject.get('access')
    handle_use = None if access is None else access.reference
    if subject is not None and subject.get('use') is not None:
        handle_use = subject['use'].id
    original = ctx.occurrences.get(operation)
    requirements = {row.requirement for row in ctx.program.resource_uses
                    if original is not None and row.operation == original.operation
                    and row.handle == handle_use and handle_use is not None}
    result = {}
    for row in ctx.accesses.values():
        binding = ctx.requirements.get(row.requirement)
        if (row.operation == operation and binding is not None
                and binding.requirement in requirements and type(row.handle) is ExplicitHandle):
            result.setdefault(row.handle.binding, None)
    return tuple(result)


def stability(ctx, read_resolved, fragment, *, budget):
    """Inspect all declared threats, preserving unresolved native phase/alias."""
    start, end = read_interval(ctx, read_resolved)
    production_start, production_end = production_interval(ctx, fragment['write'])
    production_start = fragment.get('production_start', production_start)
    production_end = fragment.get('production_end', production_end)
    write = fragment['write']
    original_effect = _effect_of(write)
    selector = fragment.get('actual') or fragment.get('requested')
    demand_selector = None if read_resolved.get('placement') is None else read_resolved['placement'][1]
    if selector is None:
        selector = demand_selector
    run = point_run(ctx, start) if start is not None else None
    invalidators, potential, exclusions, lifetime, conditions = [], [], [], [], []
    source_universe = fragment.get('source_universe') or {}
    conditions.append('native phase, alias capture and source completeness remain conditional')
    from .content import NativeWorkRead
    if type(read_resolved['read'].consumer) is ResourceConsumer and type(read_resolved['read'].consumer.read) is NativeWorkRead:
        conditions.append('unparsed narrow read interval does not replace whole-work stability')
    if any(point is None or type(point) is Unresolved for point in (start, end, production_start, production_end)):
        conditions.append('production/read extent is unresolved')

    def classify(identity, *, begin=None, finish=None, spatial='UNRESOLVED', original=None, definite=False):
        item = {'id': identity, 'original': original, 'start': begin, 'end': finish,
                'spatial': spatial, 'reason': None}
        if spatial == 'DISJOINT':
            item['reason'] = 'exact-disjoint-selector'
            exclusions.append(item)
            return
        if run is not None and begin is not None:
            other_run = point_run(ctx, begin)
            if other_run is not None and other_run != run:
                item['reason'] = 'different-known-run'
                exclusions.append(item)
                return
        # Exclude only before the conservative *start* of production, never
        # before an outer/native end that merely bounds the last write.
        if finish is not None and production_start is not None and type(production_start) is not Unresolved:
            prior = point_order(ctx, finish, production_start, budget=budget)
            if prior['status'] == 'CONDITIONAL':
                item.update(reason='before-production-extent', order=prior)
                exclusions.append(item)
                return
        if end is not None and begin is not None and type(end) is not Unresolved:
            later = point_order(ctx, end, begin, budget=budget)
            if later['status'] == 'CONDITIONAL':
                item.update(reason='after-whole-read-interval', order=later)
                exclusions.append(item)
                return
        contained = False
        if begin is not None and finish is not None and production_end is not None and end is not None:
            # Writes inside production may be repaired by a later producer
            # phase. Only a write after the conservative production end is a
            # definite conflict; the entire earlier extent is still scanned.
            left = point_order(ctx, production_end, begin, budget=budget)
            right = point_order(ctx, finish, end, budget=budget)
            contained = left['status'] == right['status'] == 'CONDITIONAL'
            item['order'] = (left, right)
        if definite and contained and spatial == 'OVERLAP':
            item['reason'] = 'declared-overlapping-write-within-protected-extent'
            invalidators.append(item)
        else:
            item['reason'] = 'alias-selector-or-native-phase-order-unresolved'
            potential.append(item)

    # Independent canonical enumeration: no Work/Write association is needed
    # to keep an original write or opaque call in the threat universe.
    for occurrence in ctx.occurrences.values():
        if not budget.spend('invalidator_scan', path='stability.canonical'):
            break
        before = OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE)
        if run is not None and point_run(ctx, before) != run:
            continue
        operation = ctx.core_operations[occurrence.operation]
        for index, access in enumerate(operation.accesses):
            if not budget.spend('invalidator_scan', path='stability.access'):
                break
            if access.mode is AccessMode.READ:
                continue
            effect = AccessRef(occurrence.id, index)
            if effect == original_effect:
                exclusions.append({'id': ('effect', effect), 'original': effect,
                                   'reason': 'exact-establishing-effect-only'})
                conditions.append('exact effect exclusion does not prove absence of other native phases')
                continue
            relations, actuals = [], []
            for resolved in ctx.resolved_writes.values():
                if not budget.spend('association_joins', path='stability.effect-placement'):
                    break
                other = resolved['row']
                if _effect_of(other) != effect:
                    continue
                relations.append(_spatial(ctx, _selector(other, resolved), selector, budget))
                for produced in chain(ctx.resolved_produced.values(),
                                      getattr(ctx, 'resolved_establishments', {}).values()):
                    if not budget.spend('association_joins', path='stability.actual-write'):
                        break
                    if produced['row'].write == other.id:
                        actuals.append(_spatial(ctx, produced['row'].actual, selector, budget))
            spatial = ('OVERLAP' if 'OVERLAP' in actuals else 'POSSIBLE'
                       if any(item != 'DISJOINT' for item in relations) else 'UNRESOLVED')
            if not actuals and relations and all(item == 'DISJOINT' for item in relations):
                spatial = 'DISJOINT'
            elif actuals and all(item == 'DISJOINT' for item in actuals):
                # Only the mapped phase is known disjoint. The independent
                # broad canonical effect can still contain unknown phases.
                spatial = 'POSSIBLE'
            classify(('effect', effect), begin=before, finish=_post(ctx, occurrence.id),
                     spatial=spatial, original=effect, definite='OVERLAP' in actuals)
        is_invoke = operation.terminator is not None and operation.terminator.kind in (
            TerminatorKind.INVOKE, TerminatorKind.BODY_DRIVE)
        if is_invoke or not operation.effects_complete:
            # An exact phase inside an opaque call does not exempt the entire
            # call from possible other phases/effects, even for its own writer.
            classify(('opaque', occurrence.id), begin=before, finish=_post(ctx, occurrence.id),
                     original=occurrence, definite=False)

    own_candidates = set(fragment.get('source_candidates', ()))
    for candidate in source_universe.get('candidates', ()):
        if not budget.spend('source_invalidators', path='stability.sources'):
            break
        identity = candidate['id']
        exact_stage = identity in own_candidates and candidate.get('source') == write.stage
        other_writes = candidate.get('write_associations', ())
        exact = (exact_stage and other_writes and all(
            resolved['row'].production == write.production
            and resolved['row'].placement == write.placement
            and resolved['row'].writer == write.writer for resolved in other_writes))
        if exact:
            exclusions.append({'id': identity, 'original': candidate,
                               'reason': 'exact-source-stage-only'})
            conditions.append('source-stage correspondence does not close other alias/native effects')
            continue
        # Inspect every candidate, including raw/ESCAPES with unknown relevance;
        # deleting an optional join cannot remove it from this list.
        relevance = candidate.get('relevance', ())
        spatial_relations = candidate.get('spatial_relations', ())
        if spatial_relations and all(item in ('disjoint', 'different_allocation') for item in spatial_relations):
            classify(identity, spatial='DISJOINT', original=candidate)
            continue
        if not other_writes:
            classify(identity, original=candidate)
        for resolved in other_writes:
            if not budget.spend('association_joins', path='stability.source-write'):
                break
            other = resolved['row']
            if exact_stage and other.id == write.id:
                exclusions.append({'id': (identity, other.id), 'original': candidate,
                                   'reason': 'exact-source-stage-effect-only'})
                continue
            begin, finish = production_interval(ctx, other)
            actual_relations = []
            for produced in chain(ctx.resolved_produced.values(),
                                  getattr(ctx, 'resolved_establishments', {}).values()):
                if not budget.spend('association_joins', path='stability.source-actual'):
                    break
                if produced['row'].write == other.id:
                    actual_relations.append(_spatial(ctx, produced['row'].actual, selector, budget))
            spatial = _spatial(ctx, _selector(other, resolved), selector, budget)
            if actual_relations:
                spatial = ('OVERLAP' if 'OVERLAP' in actual_relations else 'DISJOINT'
                           if all(item == 'DISJOINT' for item in actual_relations) else 'UNRESOLVED')
            classify((identity, other.id), begin=begin, finish=finish,
                     spatial=spatial, original=candidate,
                     definite='OVERLAP' in actual_relations)
    if source_universe.get('pending_sources'):
        conditions.append('unvisited/unresolved independent sources remain possible invalidators')

    target = _read_target(ctx, read_resolved)
    from .validity import LifetimeEventKind
    live = False
    from .resources import CreatedAt, ImportedAt, InstanceTarget
    if type(target) is InstanceTarget:
        resource = ctx.resources.get(target.instance)
        origin = None if resource is None else resource.origin
        at = (_post(ctx, origin.operation) if type(origin) is CreatedAt else
              origin.point if type(origin) is ImportedAt else None)
        if at is not None and production_start is not None:
            birth = point_order(ctx, at, production_start, budget=budget)
            live = birth['status'] == 'CONDITIONAL'
            lifetime.append({'resource': resource, 'at': at, 'order': birth,
                             'conditions': ('resource creation/import native correspondence remains conditional',)})
    for resolved in getattr(ctx, 'resolved_lifetime_events', {}).values():
        if not budget.spend('lifetime_scan', path='stability.lifetime'):
            break
        row = resolved['row']
        if target is None or target_key(target) != target_key(row.target):
            continue
        item = {'row': row, 'target': row.target, 'at': row.at, 'conditions': resolved.get('conditions', ())}
        lifetime.append(item)
        if type(row.at) is Unresolved:
            potential.append({'id': ('lifetime', row.id), 'original': row, 'reason': 'lifetime-point-unresolved'})
            continue
        if row.kind is LifetimeEventKind.LIVE:
            order = point_order(ctx, row.at, production_start, budget=budget) if production_start is not None else None
            live = live or order is not None and order['status'] == 'CONDITIONAL'
            item['order'] = order
        else:
            after = point_order(ctx, end, row.at, budget=budget) if end is not None else None
            if after is not None and after['status'] == 'CONDITIONAL':
                exclusions.append({'id': ('lifetime', row.id), 'original': row,
                                   'reason': 'retirement-after-read', 'order': after})
            else:
                before_end = point_order(ctx, row.at, end, budget=budget) if end is not None else None
                destination = invalidators if before_end is not None and before_end['status'] == 'CONDITIONAL' else potential
                destination.append({'id': ('lifetime', row.id), 'original': row,
                                    'reason': 'declared-target-retirement', 'order': before_end,
                                    'conditions': resolved.get('conditions', ())})
    for identity in _read_handles(ctx, read_resolved):
        if not budget.spend('lifetime_scan', path='stability.handle-end'):
            break
        handle = ctx.handles.get(identity)
        if handle is None or type(handle.end) is not EndedAt:
            continue
        order = point_order(ctx, handle.end.point, end, budget=budget) if end is not None else None
        destination = invalidators if order is not None and order['status'] == 'CONDITIONAL' else potential
        destination.append({'id': ('handle', identity), 'original': handle,
                            'reason': 'exact-consumer-handle-ended', 'order': order})
    if not live:
        conditions.append('allocation/resource incarnation lacks an exact live-at-start correspondence')
    if budget.truncated:
        conditions.append('unvisited threats after shared budget exhaustion remain unresolved')
    return {'start': start, 'end': end, 'production_start': production_start,
            'production_end': production_end, 'invalidators': tuple(invalidators),
            'potential_invalidators': tuple(potential), 'exclusions': tuple(exclusions),
            'lifetime': tuple(lifetime), 'conditions': tuple(dict.fromkeys(conditions)),
            'status': 'CONTRADICTED' if invalidators else 'MISSING' if potential or not live or budget.truncated else 'MATCHED',
            'truncated': budget.truncated}


__all__ = ['stability', 'production_interval', 'read_interval', 'read_domain']

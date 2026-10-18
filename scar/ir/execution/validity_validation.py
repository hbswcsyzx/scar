"""Validate content-support associations against original execution facts.

Successful structural matching is conditional. Native applicability, source
closure, lifetime truth and transformation authority are never inferred from
a protocol label or an enum value.
"""
from collections import deque

from scar.ir.program.model import BlockArgument, CompletionResult, LiteralOrigin, TerminatorKind

from .common import EvidencePoint, Unresolved
from .content import EndpointContent, HostConsumer, ObservationConsumer, ProtocolSelector, ResourceConsumer
from .endpoint_protocol import (
    resolve_endpoint_profile, same_fact_reference, same_materialization,
)
from .content_validation import check_target, target_key
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from .ids import OperationOccurrenceID, ValueOccurrenceID
from .effects import resolve_canonical_effect
from .order import WorkEnd, WorkStart
from .production import ExternalEstablishment, HostWrite, RawRecordRef, SourceEdgeRef, WorkWrite
from .resources import ProcessRealm
from .validity_order import (
    association_strength, check_validity_point, point_order, point_run, resolve_order_basis,
)
from .work import InvokeBoundaryStateEffect, Queued


def _conditions(ctx, start):
    return tuple(ctx.gaps[start:])


def _actual_post(ctx, identity):
    occurrence = ctx.occurrences.get(identity)
    if occurrence is None:
        return None
    operation = ctx.core_operations[occurrence.operation]
    if operation.terminator is not None and operation.terminator.kind in (
            TerminatorKind.INVOKE, TerminatorKind.BODY_DRIVE):
        transfer = ctx.outgoing.get(identity)
        return None if transfer is None else OccurrencePoint(
            identity, OccurrencePhase.EDGE, transfer.successor_index)
    return OccurrencePoint(identity, OccurrencePhase.AFTER)


def _source_run(ctx, reference):
    if type(reference) not in (RawRecordRef, SourceEdgeRef):
        return None
    inventory = ctx.source_inventories.get(reference.source.inventory)
    return None if inventory is None else inventory.run


def source_result_barrier(ctx, write, *, budget=None):
    """Block future/request fallback when original result evidence is present.

    This does not infer a work terminal state or an actual output selector.
    Source-edge coordinates are recovered only from the fixed normalizer's
    exact same-bundle raw line/hash metadata, never a host/parent heuristic.
    """
    from scar.ir.v2.evidence import EvidenceNodeKind
    from .effects import effect_context
    from .production_ranges import _profile
    from .source_validation import resolve_edge, resolve_raw

    path = f'writes[{write.id}].source_result'
    raw_refs, unresolved = {}, False
    conditions, profiles, raws = [], [], []
    references = (write.stage, *write.evidence)
    for reference in references:
        if budget is not None and not budget.spend('source_result_joins', path=path):
            unresolved = True
            break
        if type(reference) is RawRecordRef:
            raw_refs.setdefault(reference, None)
        elif type(reference) is SourceEdgeRef:
            resolved = resolve_edge(ctx, reference, path)
            if resolved is None:
                unresolved = True
                continue
            edge, graph = resolved['edge'], resolved['graph']
            instances = {}
            for endpoint in (edge.source, edge.target):
                if endpoint.kind is EvidenceNodeKind.OPERATION_INSTANCE:
                    instances.setdefault(endpoint.reference, None)
                elif endpoint.kind is EvidenceNodeKind.VALUE_OBSERVATION:
                    observation = graph.observations.get(endpoint.reference)
                    if observation is not None and observation.operation is not None:
                        instances.setdefault(observation.operation, None)
            found = False
            for identity in instances:
                instance = graph.instances.get(identity)
                if instance is None:
                    continue
                for metadata in (instance.metadata, instance.metadata.get('return_boundary')):
                    if type(metadata) is not dict:
                        continue
                    raw_reference, digest = metadata.get('raw_reference'), metadata.get('raw_sha256')
                    if type(raw_reference) is not str or type(digest) is not str:
                        continue
                    _, separator, line = raw_reference.rpartition('#L')
                    if separator and line.isascii() and line.isdecimal() and int(line) > 0:
                        raw_refs.setdefault(RawRecordRef(reference.source, int(line), digest), None)
                        found = True
            if not found:
                unresolved = True
                conditions.append('source edge has no exact original raw-result coordinate')
        else:
            unresolved = True
            conditions.append('source result status has no parsed original raw coordinate')
    present = False
    for reference in raw_refs:
        if budget is not None and not budget.spend('source_result_joins', path=path):
            unresolved = True
            break
        raw = resolve_raw(ctx, reference, path)
        if raw is None:
            unresolved = True
            continue
        raws.append(raw)
        payload = raw['record'].payload
        metadata = payload.get('metadata') if type(payload) is dict else None
        if type(metadata) is dict and 'scar_native_result' in metadata:
            present = True
            # Without a selected production rule, an unsupported result is a
            # source obstacle rather than proof of this fixed native schema.
            diagnostics = effect_context(ctx, issue=lambda code, p, message:
                ctx.gap('validity_source_result_unparsed', p, message))
            parsed = _profile(diagnostics, raw, path)
            if parsed is not None:
                profiles.append(parsed)
    if present:
        conditions.append('unjoined observed source result cannot become a hypothetical whole future write')
    if unresolved:
        conditions.append('original result-to-stage mapping remains unresolved')
    return {'blocked': present or unresolved, 'source_result_present': present,
            'rawprofile': profiles[0] if len(profiles) == 1 else None,
            'raw': raws[0] if len(raws) == 1 else None,
            'profiles': tuple(profiles), 'raws': tuple(raws),
            'conditions': tuple(dict.fromkeys(conditions))}


def _establishments(ctx):
    from .production_ranges import resolve_actual_range

    ctx.resolved_establishments = {}
    for row in ctx.established_productions.values():
        path = f'established_productions[{row.id}]'
        gaps, issues = len(ctx.gaps), len(ctx.issues)
        write = ctx.writes.get(row.write)
        ctx.check_point(row.established, path)
        if write is None:
            ctx.issue('validity_establishment_write', path, 'establishment references an absent write')
            continue
        if type(write.writer) is WorkWrite:
            ctx.issue('validity_establishment_work', path,
                      'work writers must use the original outcome production, not host establishment')
        elif type(write.writer) is HostWrite:
            expected = _actual_post(ctx, write.writer.operation)
            if expected is None:
                ctx.gap('validity_establishment_post_unresolved', path, 'actual host completion is unobserved')
            elif row.established != expected:
                ctx.issue('validity_establishment_point', path,
                          'host establishment must retain this occurrence actual AFTER/EDGE')
        elif type(write.writer) is ExternalEstablishment:
            if row.established != write.writer.point:
                ctx.issue('validity_establishment_point', path,
                          'external establishment must retain its original evidence point')
        else:
            ctx.gap('validity_establishment_writer_unresolved', path, 'writer is unresolved')
        if type(row.result) is ValueOccurrenceID:
            result = ctx.values.get(row.result)
            if result is None:
                ctx.issue('validity_establishment_result', path, 'specified result occurrence is absent')
            else:
                result_run = ctx.processes[ctx.activations[ctx.value_activation(result.id)].process].run
                writer_run = point_run(ctx, row.established)
                if writer_run is not None and result_run != writer_run:
                    ctx.issue('validity_establishment_result_run', path,
                              'specified result belongs to another run')
                if type(write.writer) is HostWrite and write.writer.operation in ctx.occurrences:
                    definition = ctx.core_values[result.value]
                    owner = write.writer.operation
                    operation = ctx.core_operations[ctx.occurrences[owner].operation]
                    if type(definition.origin) is LiteralOrigin:
                        ctx.gap('validity_establishment_result_port_unverified', path,
                                'literal/count equality is not an original native return-port correspondence')
                    elif type(result.origin) is OperationOccurrenceID:
                        if result.origin != owner:
                            if ctx.value_activation(result.id) == ctx.activation_of(owner):
                                ctx.issue('validity_establishment_result_owner', path,
                                          'specified result was produced by another sequential operation')
                            else:
                                ctx.gap('validity_establishment_result_port_unverified', path,
                                        'nested result has no exact return-to-writer pairing')
                    elif operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
                        transfer = ctx.outgoing.get(owner)
                        origin = definition.origin
                        successor = (None if transfer is None else
                                     operation.terminator.successors[transfer.successor_index])
                        if (successor is not None and (type(origin) is not BlockArgument
                                or result.origin != transfer.target or origin.block != successor.block
                                or origin.index >= len(successor.arguments)
                                or type(successor.arguments[origin.index]) is not CompletionResult)):
                            ctx.issue('validity_establishment_result_port', path,
                                      'result is not an actual CompletionResult landing of this invocation')
                    else:
                        ctx.issue('validity_establishment_result_port', path,
                                  'specified result is not an original result of this host writer')
        resolved = ctx.resolved_writes.get(write.id)
        ranges = resolve_actual_range(ctx, write, row.actual, row.rule, row.result, path)
        ctx.gap('validity_establishment_native_unverified', path,
                'actual range matching does not establish physical write or stable content at the outer completion')
        ctx.resolved_establishments[row.id] = {
            'row': row, 'write': resolved, 'original_write': write,
            **ranges, 'actual_ref': row.actual, 'established': row.established,
            'status': 'CONTRADICTED' if len(ctx.issues) != issues else 'MATCHED',
            'conditions': ('native establishment/content correspondence remains unverified',),
            'gaps': _conditions(ctx, gaps),
        }


def _lifetime_events(ctx):
    from .validity import LifetimeEventKind

    ctx.resolved_lifetime_events = {}
    for row in ctx.target_lifetime_events.values():
        path = f'target_lifetime_events[{row.id}]'
        gaps, issues = len(ctx.gaps), len(ctx.issues)
        check_target(ctx, row.target, path)
        if type(row.at) is Unresolved:
            ctx.check_point(row.at.point, path)
            ctx.gap('validity_lifetime_point_unresolved', path, row.at.reason)
        else:
            check_validity_point(ctx, row.at, path)
        stage = resolve_order_basis(ctx, row.stage, path)
        effect = None
        if type(row.effect) in (AccessRef, InvokeBoundaryStateEffect):
            effect = resolve_canonical_effect(ctx, row.effect, path)
        elif type(row.effect) is Unresolved:
            ctx.check_point(row.effect.point, path)
            ctx.gap('validity_lifetime_effect_unresolved', path, row.effect.reason)
        if effect is not None:
            operation = effect['operation'].id
            if type(row.at) is OccurrencePoint:
                expected = _actual_post(ctx, operation)
                if expected is not None and row.at != expected:
                    ctx.issue('validity_lifetime_effect_point', path,
                              'lifetime event and original effect use different completion points')
            elif type(row.at) is WorkEnd:
                work = ctx.submissions.get(row.at.ticket)
                if work is not None and row.effect not in work.effects:
                    from scar.ir.v2.common import Completeness
                    if work.effects_coverage is Completeness.COMPLETE:
                        ctx.issue('validity_lifetime_effect_ticket', path,
                                  'lifetime effect contradicts this work complete effect list')
                    else:
                        ctx.gap('validity_lifetime_effect_ticket_unresolved', path,
                                'lifetime effect has no exact association with this work')
        run = None if type(row.at) is Unresolved else point_run(ctx, row.at)
        source_run = _source_run(ctx, row.stage)
        if run is not None and source_run is not None and run != source_run:
            ctx.issue('validity_lifetime_run', path, 'lifetime stage and point belong to different runs')
        from .resources import InstanceTarget, ProcessTarget, ThreadTarget, RunRealm
        target_run, target_process = None, None
        if type(row.target) is InstanceTarget:
            resource = ctx.resources.get(row.target.instance)
            if resource is not None:
                if type(resource.realm) is ProcessRealm:
                    target_process = resource.realm.process
                elif type(resource.realm) is RunRealm:
                    target_run = resource.realm.run
        elif type(row.target) is ProcessTarget:
            target_process = row.target.process
        elif type(row.target) is ThreadTarget:
            thread = ctx.threads.get(row.target.thread)
            target_process = None if thread is None else thread.process
        if target_process in ctx.processes:
            target_run = ctx.processes[target_process].run
        if run is not None and target_run is not None and run != target_run:
            ctx.issue('validity_lifetime_target_run', path, 'target belongs to another known run')
        # No existing native profile interprets free/live from an arbitrary
        # source line. The declaration is retained, including RETIRED, but is
        # never silently upgraded to a physical lifetime proof.
        ctx.gap('validity_lifetime_protocol_unverified', path,
                'LIVE/RETIRED requires a parsed target/effect/native lifetime correspondence')
        ctx.resolved_lifetime_events[row.id] = {
            'row': row, 'target': row.target, 'at': row.at, 'stage': stage, 'effect': effect,
            'retired': row.kind is LifetimeEventKind.RETIRED,
            'status': 'CONTRADICTED' if len(ctx.issues) != issues else 'ASSUMPTION',
            'conditions': ('declared lifetime event; native target/retirement semantics unverified',),
            'gaps': _conditions(ctx, gaps),
        }


def _associations(ctx):
    ctx.resolved_order_associations = {}
    for row in ctx.order_associations.values():
        path = f'order_associations[{row.id}]'
        gaps, issues = len(ctx.gaps), len(ctx.issues)
        check_validity_point(ctx, row.before, path)
        check_validity_point(ctx, row.after, path)
        basis = resolve_order_basis(ctx, row.basis, path)
        if row.before == row.after:
            ctx.issue('validity_order_strict', path, 'strict causal relation cannot be a self-edge/coincidence')
        left, right = point_run(ctx, row.before), point_run(ctx, row.after)
        if left is not None and right is not None and left != right:
            ctx.issue('validity_order_run', path, 'causal endpoints belong to different runs')
        source_run = _source_run(ctx, row.basis)
        if source_run is not None and any(run is not None and run != source_run for run in (left, right)):
            ctx.issue('validity_order_source_run', path, 'causal source belongs to another run')
        if (type(row.before) is OccurrencePoint and type(row.after) is OccurrencePoint
                and ctx.point_precedes(row.after, row.before) is True):
            ctx.issue('validity_order_reverse', path, 'strict causal declaration reverses known actual host order')
        strength = association_strength(ctx, row, basis, path)
        ctx.resolved_order_associations[row.id] = {
            'row': row, 'before': row.before, 'after': row.after, 'basis': basis,
            'strength': strength,
            'status': 'CONTRADICTED' if len(ctx.issues) != issues else strength,
            'gaps': _conditions(ctx, gaps),
        }
    # Cycle validation covers all declaration families together, even when a
    # declaration's native meaning is unsupported. Unknown does not waive an
    # inconsistent strict causal contract.
    adjacency, degree = {}, {}

    def add(left, right):
        targets = adjacency.setdefault(left, set())
        if right in targets:
            return
        targets.add(right)
        degree.setdefault(left, 0)
        degree[right] = degree.get(right, 0) + 1

    host = set()
    for step in ctx.order_steps:
        add(step.source, step.target)
    for resolved in ctx.resolved_order_associations.values():
        row = resolved['row']
        add(row.before, row.after)
        host.update(point for point in (row.before, row.after) if type(point) is OccurrencePoint)
    for left in host:
        for right in host:
            if left != right and ctx.point_precedes(left, right) is True:
                add(left, right)
    pending = deque(point for point, count in degree.items() if count == 0)
    seen = 0
    while pending:
        point = pending.popleft()
        seen += 1
        for target in adjacency.get(point, ()):
            degree[target] -= 1
            if degree[target] == 0:
                pending.append(target)
    if seen != len(degree):
        ctx.issue('validity_order_cycle', 'order_associations',
                  'combined canonical/resource/declaration strict causal order contains a cycle')


def _read_thread(ctx, resolved):
    read = resolved['read']
    if type(read.consumer) is HostConsumer:
        point = read.consumer.subject.operation
    elif type(read.consumer) is ObservationConsumer:
        root = resolved['observation_root']
        point = root.anchor.operation if root is not None and type(root.anchor) is OccurrencePoint else None
    elif type(read.consumer) is ResourceConsumer:
        from .work import DirectExecution
        work = ctx.submissions.get(read.consumer.read.ticket)
        return (work.scheduling.thread if work is not None
                and type(work.scheduling) is DirectExecution else None)
    else:
        return None
    occurrence = ctx.occurrences.get(point)
    if occurrence is None:
        return None
    return ctx.segments[ctx.visits[occurrence.visit].segment].host_thread


def _queue(ctx, read):
    if type(read.consumer) is not ResourceConsumer:
        return None
    work = ctx.submissions.get(read.consumer.read.ticket)
    if work is None or type(work.scheduling) is not Queued:
        return None
    access = ctx.accesses.get(work.scheduling.queue_access)
    binding = None if access is None else ctx.requirements.get(access.requirement)
    from .resources import InstanceTarget
    return (None if binding is None or type(binding.target) is not InstanceTarget
            else binding.target.instance)


def _supports(ctx):
    from .validity import (
        CompletedVisibility, EndpointDomain, HostDomain, OrderedVisibility, QueueDomain,
    )
    from .validity_budget import ValidityBudget

    ctx.resolved_supports = {}
    for row in ctx.contribution_supports.values():
        path = f'contribution_supports[{row.id}]'
        gaps, issues = len(ctx.gaps), len(ctx.issues)
        read = ctx.resolved_content_reads.get(row.read)
        write = ctx.resolved_writes.get(row.write)
        if read is None:
            ctx.issue('validity_support_read', path, 'support references an absent original content read')
        if write is None:
            ctx.issue('validity_support_write', path, 'support references an absent original write')
        production = None
        if row.production is not None and type(row.production) is not Unresolved:
            production = ctx.resolved_produced.get(row.production) or ctx.resolved_establishments.get(row.production)
            if production is None:
                ctx.issue('validity_support_production', path, 'support references an absent actual production')
            elif production['row'].write != row.write:
                ctx.issue('validity_support_production_write', path, 'actual production belongs to another write')
        elif type(row.production) is Unresolved:
            ctx.check_point(row.production.point, path)
            ctx.gap('validity_support_production_unresolved', path, row.production.reason)
        if read is None or write is None:
            continue
        original = write['row']
        work = ctx.submissions.get(original.writer.ticket) if type(original.writer) is WorkWrite else None
        terminal = () if work is None else ctx.work_outcomes.get(work.id, ())
        if terminal and row.production is None:
            ctx.issue('validity_support_terminal_actual', path,
                      'known terminal work requires its exact actual production; requested range cannot bypass it')
        actual_ref = None if production is None else production['row'].actual
        domain, order, basis = None, None, None
        visibility = row.visibility
        if type(visibility) is CompletedVisibility:
            domain = visibility.domain
            check_validity_point(ctx, visibility.established, path)
            basis = resolve_order_basis(ctx, visibility.basis, path)
            if type(domain) is HostDomain:
                thread = ctx.threads.get(domain.thread)
                expected = _read_thread(ctx, read)
                if thread is None:
                    ctx.issue('validity_host_thread', path, 'visibility domain references an absent thread')
                elif expected not in ctx.threads:
                    ctx.gap('validity_host_thread_unresolved', path, 'original consumer has no exact host thread')
                elif domain.thread != expected:
                    ctx.issue('validity_host_domain', path, 'visibility names another consumer thread/process')
            elif type(domain) is QueueDomain:
                expected = _queue(ctx, read['read'])
                if domain.queue not in ctx.resources:
                    ctx.issue('validity_queue_domain', path, 'visibility references an absent queue lifetime')
                elif expected is None:
                    ctx.issue('validity_queue_consumer', path, 'queue visibility requires an actual queued consumer')
                elif domain.queue != expected:
                    ctx.issue('validity_queue_domain', path, 'visibility names another actual consumer queue')
            elif type(domain) is EndpointDomain:
                check_target(ctx, domain.target, path)
                placement = read['read'].placement
                if type(placement) is not EndpointContent:
                    ctx.issue('validity_endpoint_domain', path, 'endpoint visibility requires an endpoint-backed read')
                elif target_key(domain.target) != target_key(placement.target):
                    ctx.issue('validity_endpoint_domain', path, 'visibility names another endpoint incarnation')
                else:
                    profile_budget = ValidityBudget(4096)
                    profile_gap_count = len(ctx.gaps)
                    read_profile = (resolve_endpoint_profile(ctx, placement.selector, path,
                                                             budget=profile_budget)
                                    if type(placement.selector) is ProtocolSelector else None)
                    visibility_profile = resolve_endpoint_profile(ctx, visibility.protocol, path,
                                                                  budget=profile_budget)
                    from .content_validation import _content_interval
                    interval = _content_interval(ctx, read['read'].consumer,
                                                 read['observation_root'])
                    interval_profile = (None if interval is None else
                        resolve_endpoint_profile(ctx, interval.protocol, path,
                                                 budget=profile_budget))
                    if read_profile is None or visibility_profile is None or interval_profile is None:
                        if any(gap.code == 'endpoint_profile_unsupported'
                               for gap in ctx.gaps[profile_gap_count:]):
                            ctx.gap('validity_endpoint_interpreter_unsupported', path,
                                    'same Q protocol reference is not a parsed observation/facet/selector visibility interpretation')
                        ctx.gap('validity_endpoint_protocol_unresolved', path,
                                'endpoint read selector, interval and visibility need the same parsed byte-prefix profile')
                    elif (read_profile['operation'] != 'READ'
                            or visibility_profile['operation'] != 'READ'
                            or interval_profile['operation'] != 'READ'
                            or not same_fact_reference(read_profile['reference'], visibility_profile['reference'])
                            or not same_fact_reference(read_profile['reference'], interval_profile['reference'])):
                        ctx.issue('validity_endpoint_protocol', path,
                                  'visibility must retain the exact READ profile used by the endpoint selector and interval')
            else:
                ctx.check_point(domain.point, path)
                ctx.gap('validity_visibility_domain_unresolved', path, domain.reason)
        elif type(visibility) is OrderedVisibility:
            queue = _queue(ctx, read['read'])
            domain = None if queue is None else QueueDomain(queue)
            if queue is None:
                ctx.issue('validity_ordered_consumer', path, 'ordered visibility requires a real queued consumer')
            if work is None:
                ctx.issue('validity_ordered_writer', path, 'ordered visibility requires a real contributing work')
            elif queue is not None and production is None:
                actual_ref = original.placement.selector if hasattr(original.placement, 'selector') else None
                ctx.gap('validity_ordered_future_production', path,
                        'pending ordered support is conditional on successful content production and error propagation')
        else:
            ctx.check_point(visibility.point, path)
            ctx.gap('validity_visibility_unresolved', path, visibility.reason)
        ctx.gap('validity_visibility_native_unverified', path,
                'matched domain/protocol association does not establish physical coherence, capture or native applicability')
        status = 'CONTRADICTED' if len(ctx.issues) != issues else 'MISSING'
        ctx.resolved_supports[row.id] = {
            'row': row, 'read': read, 'write': write, 'production': production,
            'actual': actual_ref, 'domain': domain, 'visibility': visibility,
            'order': order, 'basis': basis, 'status': status,
            'conditions': ('native visibility and protocol applicability remain unverified',),
            'gaps': _conditions(ctx, gaps),
        }
        # Query and validation interpret exactly the same protocol rules. The
        # public query repeats the traversal with its own shared budget.
        view = resolve_support(ctx, ctx.resolved_supports[row.id], {}, read,
                               budget=ValidityBudget(4096))
        ctx.resolved_supports[row.id]['status'] = view['status']


def _point_thread(ctx, point):
    if type(point) is OccurrencePoint and point.operation in ctx.occurrences:
        occurrence = ctx.occurrences[point.operation]
        return ctx.segments[ctx.visits[occurrence.visit].segment].host_thread
    if type(point) is WorkEnd:
        from .work import DirectExecution
        work = ctx.submissions.get(point.ticket)
        if work is not None and type(work.scheduling) is DirectExecution:
            return work.scheduling.thread
    return None


def _anchored_basis(ctx, visibility):
    basis, point = visibility.basis, visibility.established
    operation = (basis.operation if type(basis) in (AccessRef,) else basis.invocation
                 if type(basis) is InvokeBoundaryStateEffect else getattr(basis, 'operation', None))
    if type(point) is OccurrencePoint:
        return operation == point.operation and point == _actual_post(ctx, operation)
    if type(point) is WorkEnd:
        work = ctx.submissions.get(point.ticket)
        return work is not None and basis in work.effects
    return False


def _endpoint_visibility_matches(ctx, support, read, production, budget, path, conditions):
    """Interpret only the fixed byte-prefix read-after-completed-write rule."""
    from .content import DataIdentity, EndpointContent, ProtocolSelector
    from .endpoint_protocol import endpoint_extent, resolve_endpoint_profile, same_fact_reference, same_materialization

    read_row, visibility = read['read'], support['visibility']
    if type(read_row.placement) is not EndpointContent:
        return False
    if type(read_row.placement.selector) is not ProtocolSelector:
        conditions.append('endpoint read selector has no parsed byte-prefix profile')
        return False
    profile_refs = [read_row.placement.selector]
    interval = None
    from .content_validation import _content_interval
    interval = _content_interval(ctx, read_row.consumer, read.get('observation_root'))
    if interval is None:
        conditions.append('endpoint read interval is not available for the fixed byte-prefix rule')
        return False
    profile_refs.append(interval.protocol)
    profile_refs.append(visibility.protocol)
    read_profile = None
    for index, reference in enumerate(profile_refs):
        if not budget.spend('endpoint_profile_ranges', path=path):
            conditions.append('shared budget ended before endpoint profile interpretation')
            return False
        current = resolve_endpoint_profile(ctx, reference, path, budget=budget)
        if current is None:
            conditions.append('endpoint profile bytes are missing, unsupported or malformed')
            return False
        if current['operation'] != 'READ':
            ctx.issue('validity_endpoint_profile_role', path,
                      'read selector, interval and visibility must use READ profiles')
            return False
        if index == 0:
            read_profile = current
        elif not same_fact_reference(read_profile['reference'], current['reference']):
            ctx.issue('validity_endpoint_profile_identity', path,
                      'endpoint selector, read interval and visibility use different profile artifacts')
            return False

    read_extent = read.get('endpoint_extent')
    if read_extent is None:
        read_extent = endpoint_extent(ctx, read_row.placement.target, read_profile, path,
            expected_operation='READ', materialization=read_row.placement.materialization)
    if read_extent is None:
        conditions.append('endpoint read byte extent is unresolved')
        return False
    if production is None:
        conditions.append('endpoint visibility requires an actual completed write range')
        return False
    write_resolved = support['write']
    write_row = write_resolved['row']
    if type(write_row.placement) is not EndpointContent:
        conditions.append('contribution does not declare an endpoint byte write')
        return False
    request = write_resolved.get('endpoint_request')
    actual = production.get('actual_selector')
    if request is None or actual is None or type(request) is not dict or type(actual) is not dict:
        conditions.append('endpoint request or actual prefix range is unresolved')
        return False

    target_matches = (target_key(read_extent['target']) == target_key(request['target'])
                      == target_key(actual['target']))
    mat_matches = (same_materialization(read_row.placement.materialization,
                                        write_row.placement.materialization)
                   and same_materialization(read_row.placement.materialization,
                                           request.get('materialization'))
                   and same_materialization(read_row.placement.materialization,
                                           actual.get('materialization')))
    if not target_matches:
        ctx.issue('validity_endpoint_target', path,
                  'read, write request and actual prefix must name the same endpoint instance')
        return False
    if not mat_matches:
        ctx.issue('validity_endpoint_materialization', path,
                  'read and endpoint write must name the same exact materialization, not merely the same logical version')
        return False
    read_mat = read.get('placement')
    write_mat = write_resolved.get('placement')
    if (read_mat is None or write_mat is None or read_mat[0] is None or write_mat[0] is None
            or read_mat[0].value_version != write_mat[0].value_version):
        ctx.issue('validity_endpoint_version', path,
                  'read and endpoint write materialization do not establish the same scoped logical version')
        return False
    if (request['operation'] != 'WRITE_REQUEST' or actual['operation'] != 'WRITE_ACTUAL'
            or request['profile'] != actual['profile']
            or request['offset_bytes'] != actual['offset_bytes']
            or actual['offset_bytes'] != 0):
        ctx.issue('validity_endpoint_range', path,
                  'request and actual must use the fixed zero-offset byte-prefix profile')
        return False
    source_input = write_resolved.get('source_byte_input')
    if source_input is None or source_input.get('extent') is None:
        conditions.append('endpoint write has no unique original byte Data Use/ContentRead geometry')
        return False
    if (request['length_bytes'] != source_input['extent']['length_bytes']
            or actual['length_bytes'] > request['length_bytes']):
        ctx.issue('validity_endpoint_source_extent', path,
                  'write request differs from its exact source byte input or actual prefix exceeds the request')
        return False
    if actual['length_bytes'] < read_extent['length_bytes']:
        conditions.append('actual written prefix is shorter than the independent read selector extent')
        return False
    if production.get('placement_match') is not True:
        conditions.append('actual prefix has not matched its original request, raw byte counts and endpoint placement')
        return False

    from .production import HostWrite, WorkWrite
    if type(write_row.writer) is WorkWrite:
        outcome = production.get('outcome')
        from .work import WorkOutcomeKind
        if outcome is None or outcome.ticket != write_row.writer.ticket:
            conditions.append('actual endpoint write has no exact work outcome')
            return False
        if outcome.kind is not WorkOutcomeKind.COMPLETED:
            conditions.append('failed, cancelled or still-pending work cannot satisfy read-after-completed-write')
            return False
        quiescence = ctx.quiescences.get(outcome.quiescence) if type(outcome.quiescence) is not Unresolved else None
        if quiescence is None or quiescence.ticket != outcome.ticket:
            conditions.append('completed work has no exact validated quiescence association')
            return False
    elif type(write_row.writer) is not HostWrite:
        conditions.append('external establishment has no interpreted host/work completion for this endpoint rule')
        return False
    return True


def resolve_support(ctx, support, fragment, read, *, budget):
    """Bounded interpretation shared with the detached validity query.

    Validation facts never supply a free cached path. Unknown raw/protocol
    declarations stay missing even when every record is well typed.
    """
    from .validity import CompletedVisibility, EndpointDomain, HostDomain, OrderedVisibility, QueueDomain
    from .validity_stability import read_interval

    row, visibility = support['row'], support['visibility']
    issue_start = len(ctx.issues)
    paths, conditions = [], list(support.get('conditions', ()))
    if not budget.spend('support_joins', path=f'contribution_supports[{row.id}]'):
        return {'row': row, 'status': 'TRUNCATED', 'paths': (), 'conditions': tuple(conditions)}
    if support.get('status') == 'CONTRADICTED':
        return {'row': row, 'status': 'CONTRADICTED', 'paths': (), 'conditions': tuple(conditions)}
    write = support['write']['row']
    production = support.get('production')
    matched = True
    if fragment:
        expected = fragment.get('production')
        if fragment.get('write') != write or (expected is not None and (production is None
                or expected['row'].id != production['row'].id)):
            matched = False
    if type(visibility) is OrderedVisibility:
        if type(read['read'].placement) is EndpointContent:
            matched = False
            conditions.append('queue order alone does not establish endpoint read-after-completed-write visibility')
        elif _queue(ctx, read['read']) is None or type(write.writer) is not WorkWrite:
            matched = False
        else:
            paths.append(point_order(ctx, WorkEnd(write.writer.ticket),
                WorkStart(read['read'].consumer.read.ticket), budget=budget))
            if production is None:
                matched = matched and row.production is None and not ctx.work_outcomes.get(write.writer.ticket)
                conditions.append('future production and error propagation are required')
                barrier = source_result_barrier(ctx, write, budget=budget)
                matched = matched and not barrier['blocked']
                conditions.extend(barrier['conditions'])
                if barrier['blocked']:
                    ctx.gap('validity_unjoined_observed_result', f'contribution_supports[{row.id}]',
                            'original source result is observed or unresolved; no requested-range future fallback')
    elif type(visibility) is CompletedVisibility:
        matched = production is not None and _anchored_basis(ctx, visibility)
        domain = visibility.domain
        if type(domain) is HostDomain:
            expected = _read_thread(ctx, read)
            matched = (matched and domain.thread == expected
                       and _point_thread(ctx, visibility.established) == expected)
        elif type(domain) is QueueDomain:
            matched = matched and _queue(ctx, read['read']) == domain.queue
        elif type(domain) is EndpointDomain:
            placement = read['read'].placement
            matched = (matched and type(placement) is EndpointContent
                       and target_key(placement.target) == target_key(domain.target))
            matched = (matched and _endpoint_visibility_matches(
                ctx, support, read, production, budget,
                f'contribution_supports[{row.id}]', conditions))
        else:
            matched = False
        begin, _ = read_interval(ctx, read)
        if begin is not None:
            paths.append(point_order(ctx, visibility.established, begin, budget=budget))
        else:
            matched = False
        if type(write.writer) is WorkWrite:
            completed = WorkEnd(write.writer.ticket)
            if completed != visibility.established:
                paths.append(point_order(ctx, completed, visibility.established, budget=budget))
        elif production is not None and 'established' in production:
            established = production['established']
            if established != visibility.established:
                paths.append(point_order(ctx, established, visibility.established, budget=budget))
    else:
        matched = False
    matched = matched and all(path['status'] == 'CONDITIONAL' for path in paths)
    if any(path['status'] == 'ASSUMPTION' for path in paths):
        conditions.append('causal path contains unsupported/unparsed assumptions')
    status = ('TRUNCATED' if budget.truncated else 'CONTRADICTED'
              if len(ctx.issues) > issue_start else 'MATCHED' if matched else 'MISSING')
    return {'row': row, 'status': status,
            'domain': support.get('domain'), 'visibility': visibility, 'paths': tuple(paths),
            'conditions': tuple(dict.fromkeys(conditions)), 'gaps': support.get('gaps', ())}


def validity_errors(ctx):
    ctx.resolved_establishments = {}
    ctx.resolved_lifetime_events = {}
    ctx.resolved_order_associations = {}
    ctx.resolved_supports = {}
    if not any((ctx.established_productions, ctx.target_lifetime_events,
                ctx.order_associations, ctx.contribution_supports)):
        return
    _establishments(ctx)
    _lifetime_events(ctx)
    _associations(ctx)
    _supports(ctx)


__all__ = ['validity_errors', 'resolve_support', 'source_result_barrier']

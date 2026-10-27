"""Conditional resource order, derived from original associations, never ready.

Endpoints deliberately distinguish consumer start from its completion. Protocol
references remain conditions: neither validation nor reachability verifies a
native protocol, produces content, or establishes host visibility.
"""
from collections import deque
from dataclasses import dataclass

from scar.ir.program.model import AccessMode, BlockArgument, StateVersionValue, TerminatorKind
from scar.ir.program.resources import ResourceRole
from scar.ir.program.resumption import saved_actual_use
from .common import EvidencePoint, Unresolved
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from .effects import effect_context, resolve_canonical_effect
from .ids import QueuePrefixID
from .order import EventSignal, PrefixEnd, WorkEnd, WorkStart
from .resources import InstanceTarget, ProcessRealm, RunRealm
from .work import ActualCompletionState, InvokeBoundaryStateEffect, QueueStart, Queued, WithinOperation


@dataclass(frozen=True, slots=True)
class OrderStep:
    source: object
    target: object
    rule: str
    support: tuple


def _scope(ctx, point):
    if type(point) is EvidencePoint:
        return point.run, point.process
    if point.operation not in ctx.occurrences:
        return None, None
    process = ctx.activations[ctx.activation_of(point.operation)].process
    return ctx.processes[process].run, process


def _work_scope(ctx, work):
    point = (OccurrencePoint(work.origin.operation, OccurrencePhase.BEFORE)
             if type(work.origin) is WithinOperation else work.origin.point)
    return _scope(ctx, point)


def _state_root(ctx, identity):
    """Only actual CFG forwarding; a write/completion is a new state root."""
    seen = set()
    while identity in ctx.values and identity not in seen:
        seen.add(identity)
        row = ctx.values[identity]
        core = ctx.core_values[row.value]
        if type(core.origin) is not BlockArgument:
            return identity
        transfer = ctx.incoming.get(row.origin)
        if transfer is None:
            return identity
        operation = ctx.core_operations[ctx.occurrences[transfer.operation].operation]
        argument = operation.terminator.successors[transfer.successor_index].arguments[core.origin.index]
        use = saved_actual_use(operation, argument)
        if use is None:
            return identity
        binding = ctx.uses.get((transfer.operation, use))
        if binding is None or type(binding.value) is Unresolved:
            return None
        identity = binding.value
    return None


def order_errors(ctx):
    ctx.order_steps, ctx.order_adjacency = [], {}

    def issue(code, path, message):
        ctx.issue('order_' + code, path, message)

    def gap(code, path, message):
        ctx.gap('order_' + code, path, message)

    def edge(source, target, rule, *support):
        step = OrderStep(source, target, rule, tuple(support))
        ctx.order_steps.append(step)
        ctx.order_adjacency.setdefault(source, []).append(step)

    def same_scope(expected, actual, path):
        if expected[0] is not None and actual[0] is not None and expected[0] != actual[0]:
            issue('run_scope', path, 'association crosses known execution runs')
            return False
        if (expected[1] is None or actual[1] is None or expected[1] != actual[1]
                or expected[0] is None or actual[0] is None):
            gap('scope_unresolved', path, 'cross-process/external protocol sharing needs an explicit correspondence')
            return False
        return True

    def resource_scope(identity):
        resource = ctx.resources[identity]
        if type(resource.realm) is ProcessRealm:
            return ctx.processes[resource.realm.process].run, resource.realm.process
        if type(resource.realm) is RunRealm:
            return resource.realm.run, None
        return None, None

    def point_for_work(point, work, path):
        ctx.check_point(point, path)
        aligned = same_scope(_work_scope(ctx, work), _scope(ctx, point), path)
        if type(work.origin) is WithinOperation:
            before = OccurrencePoint(work.origin.operation, OccurrencePhase.BEFORE)
            order = ctx.point_precedes(before, point)
            if point == before or order is False:
                issue('observation_before_submission', path, 'order observation precedes its enclosing submission')
                return False
            if order is None:
                gap('host_alignment_unresolved', path, 'no actual host path aligns this observation to the submission')
                aligned = False
        return aligned

    def queue(work, path):
        if type(work.scheduling) is not Queued:
            gap('queue_unresolved', path, 'event marker/wait needs an exact queued submission')
            return None
        return ctx.queue_prefixes[work.scheduling.prefix]

    def event_access(identity, event, work, location, path):
        if type(identity) is Unresolved:
            gap('event_access_unresolved', path, identity.reason)
            return False
        access = ctx.accesses.get(identity)
        if access is None:
            issue('event_access', path, 'event access does not name a ResourceAccessBinding')
            return False
        binding = ctx.requirements[access.requirement]
        if type(binding.target) is not InstanceTarget or binding.target.instance != event:
            issue('event_instance', path, 'event access targets a different resource lifetime')
            return False
        if type(work.origin) is WithinOperation and access.operation != work.origin.operation:
            issue('event_access_owner', path, 'event access belongs to another submission occurrence')
            return False
        if location is None:
            gap('generation_location_unresolved', path, 'no exact canonical event state location')
            return False
        operation = ctx.occurrences[access.operation].operation
        definitions = {row.definition for row in ctx.program.resource_uses
                       if row.operation == operation and row.requirement == binding.requirement}
        locations = {row.resource for row in ctx.program.resource_locations if row.location == location}
        if not definitions.intersection(locations):
            if None not in definitions:
                issue('event_location', path, 'event state location and original resource Use do not match')
                return False
            # A requirement-only original Use has no fixed static target. Join
            # its exact dynamic target to a realization in this activation;
            # omission is not evidence that a different resource was accessed.
            activation = ctx.activation_of(access.operation)
            realized = {row.definition for row in ctx.model.realizations
                        if row.target == binding.target and (
                            row.site == activation or row.site in ctx.occurrences
                            and ctx.activation_of(row.site) == activation)}
            if not realized.intersection(locations):
                gap('event_location_unresolved', path, 'requirement-only resource Use needs an exact location-owner realization')
                return False
        return same_scope(_work_scope(ctx, work), resource_scope(event), path)

    def generation(record, work, path):
        effect = record.generation
        if type(effect) is Unresolved:
            gap('generation_unresolved', path, effect.reason)
            return None, None
        if work is not None and effect not in work.effects:
            issue('generation_effect', path, 'generation must select an original effect of this marker work')
            return None, None
        effect_issue_codes = {
            'effect_operation': 'order_generation_effect',
            'effect_access': 'order_generation_effect',
            'invoke_kind': 'order_generation_effect',
            'invoke_input': 'order_generation_effect',
            'invoke_successor': 'order_generation_effect',
            'invoke_actual_edge': 'order_generation_effect',
            'invoke_formal': 'order_generation_effect',
            'invoke_result': 'order_generation_effect',
            'invoke_formal_visit': 'order_generation_effect',
            'invoke_formal_scope': 'order_generation_effect',
        }
        effect_gap_codes = {
            'invoke_input_unobserved': 'order_generation_unresolved',
            'invoke_completion_unobserved': 'order_generation_unresolved',
            'invoke_post_unresolved': 'order_generation_unresolved',
        }
        view = resolve_canonical_effect(effect_context(
            ctx,
            issue=lambda code, p, message: ctx.issue(
                effect_issue_codes.get(code, 'order_generation_effect'), p, message),
            gap=lambda code, p, message: ctx.gap(
                effect_gap_codes.get(code, 'order_generation_unresolved'), p, message),
        ), effect, path)
        if view is None:
            return None, None
        if type(effect) is AccessRef:
            access = view['access']
            if access.after is None:
                issue('generation_write', path, 'record generation must define a post-state')
                return access.location, None
            post = view['after']
            if post is None:
                gap('generation_unobserved', path, 'record post-state occurrence was not captured')
            return access.location, None if post is None else post.id
        # For an unscoped marker, retain the existing global boundary-membership
        # condition. A shared resolver does not itself activate an event marker.
        if effect not in ctx.work_effects:
            gap('generation_boundary_unresolved', path, 'external invoke state needs a validated work boundary')
            return None, None
        if type(view['declared_post']) is not ActualCompletionState:
            gap('generation_unresolved', path, 'invoke record has no actual post-state')
            return None, None
        if view['actual_transfer'] is None or view['formal'] is None:
            gap('generation_unresolved', path, 'invoke completion has no observed post-state landing')
            return view['input_location'], None
        return view['input_location'], view['formal'].id

    # Intrinsic completion and explicit dependencies are conditional work-order
    # statements, not observations of completion or of successful production.
    for work in ctx.model.submissions:
        edge(WorkStart(work.id), WorkEnd(work.id), 'work-boundary', work)
        for dependency in work.dependencies:
            if same_scope(_work_scope(ctx, ctx.submissions[dependency]), _work_scope(ctx, work), work.id):
                edge(WorkEnd(dependency), WorkStart(work.id), 'declared-dependency', work)

    # Completion of a prefix includes each member, even without a FIFO profile.
    # This never points from prefix completion back to an included member start.
    aligned_prefixes = set()
    for prefix in ctx.model.queue_prefixes:
        if prefix.work is not None and same_scope(_work_scope(ctx, ctx.submissions[prefix.work]),
                                                  _scope(ctx, prefix.observed_at), prefix.id):
            edge(WorkEnd(prefix.work), PrefixEnd(prefix.id), 'prefix-member', prefix)
            aligned_prefixes.add(prefix.id)
        if type(prefix.previous) is QueuePrefixID:
            previous = ctx.queue_prefixes[prefix.previous]
            if same_scope(_scope(ctx, previous.observed_at), _scope(ctx, prefix.observed_at), prefix.id):
                edge(PrefixEnd(prefix.previous), PrefixEnd(prefix.id), 'prefix-frontier', prefix)

    for profile in ctx.model.queue_order_profiles:
        path = f'queue_order_profiles[{profile.id}]'
        resource = ctx.resources.get(profile.queue)
        current = ctx.queue_prefixes.get(profile.through)
        if resource is None or resource.role is not ResourceRole.QUEUE:
            issue('profile_queue', path, 'profile requires an existing QUEUE instance')
        if current is None or current.queue != profile.queue:
            issue('profile_prefix', path, 'profile boundary must belong to its exact queue lifetime')
            continue
        gap('protocol_applicability', path, 'FIFO profile and captured adjacency remain declared protocol conditions')
        while type(current.previous) is QueuePrefixID:
            previous = ctx.queue_prefixes[current.previous]
            if (previous.work is not None and current.work is not None
                    and previous.id in aligned_prefixes and current.id in aligned_prefixes
                    and same_scope(_work_scope(ctx, ctx.submissions[previous.work]),
                                   _work_scope(ctx, ctx.submissions[current.work]), profile.id)):
                edge(WorkEnd(previous.work), WorkStart(current.work), 'profile-fifo', profile, previous, current)
            current = previous
        if type(current.previous) is Unresolved:
            gap('prefix_coverage_unresolved', path, 'prefix head is not captured; no absent members are invented')

    generations, generation_owners = {}, {}
    active_records = set()
    for record in ctx.model.event_records:
        path = f'event_records[{record.id}]'
        if type(record.event_access) is not Unresolved and record.event_access not in ctx.accesses:
            issue('event_access', path, 'known event access references an absent resource access')
        if record.event not in ctx.resources:
            issue('event_instance', path, 'event record requires an existing resource lifetime')
            continue
        ctx.check_point(record.observed_at, path)
        same_scope(resource_scope(record.event), _scope(ctx, record.observed_at), path)
        captured = record.captured
        resource = ctx.resources.get(captured.queue)
        if resource is None or resource.role is not ResourceRole.QUEUE:
            issue('capture_queue', path, 'captured prefix requires an existing QUEUE instance')
            continue
        capture = None
        if type(captured.prefix) is QueuePrefixID:
            capture = ctx.queue_prefixes.get(captured.prefix)
            if capture is None or capture.queue != captured.queue:
                issue('capture_prefix', path, 'capture names an absent or different queue prefix')
                continue
        elif type(captured.prefix) is Unresolved:
            gap('capture_unresolved', path, captured.prefix.reason)
        if type(record.marker) is Unresolved:
            gap('marker_unresolved', path, record.marker.reason)
            generation(record, None, path)
            continue
        work = ctx.submissions.get(record.marker)
        if work is None:
            issue('marker_ticket', path, 'event marker references unknown work')
            continue
        aligned = point_for_work(record.observed_at, work, path)
        prefix = queue(work, path)
        if prefix is None:
            continue
        if prefix.queue != captured.queue:
            issue('marker_queue', path, 'record marker and captured frontier use different queue lifetimes')
            continue
        if type(prefix.previous) is Unresolved and type(captured.prefix) is not Unresolved:
            gap('capture_boundary_unresolved', path, 'marker predecessor is not captured; record cannot close that missing association')
            aligned = False
        elif (type(captured.prefix) is QueuePrefixID and prefix.previous != captured.prefix
                or type(captured.prefix) is QueueStart and type(prefix.previous) is not QueueStart):
            issue('capture_boundary', path, 'record capture must be this marker prefix exact predecessor')
            continue
        location, post = generation(record, work, path)
        bound = event_access(record.event_access, record.event, work, location, path)
        generations[record.id] = location, post
        if post is not None:
            key = record.event, _state_root(ctx, post)
            if key in generation_owners:
                issue('duplicate_generation', path, 'two record IDs claim the same exact event post-state occurrence')
            generation_owners[key] = record.id
        gap('protocol_applicability', path, 'event signal/captured frontier are conditional native protocol associations')
        if aligned and bound and type(captured.prefix) is not Unresolved:
            if capture is not None and not same_scope(_scope(ctx, capture.observed_at), _work_scope(ctx, work), path):
                continue
            if capture is not None:
                edge(PrefixEnd(capture.id), WorkEnd(work.id), 'record-capture', record, capture)
            edge(WorkEnd(work.id), EventSignal(record.id), 'record-signal', record)
            active_records.add(record.id)

    for wait in ctx.model.queue_waits:
        path = f'queue_waits[{wait.id}]'
        # Unknown selection/record does not waive other, explicitly known FKs.
        if type(wait.event_access) is not Unresolved and wait.event_access not in ctx.accesses:
            issue('event_access', path, 'known wait access references an absent resource access')
        if type(wait.selection) is not Unresolved:
            original = ctx.core_uses.get(wait.selection.use)
            occurrence = ctx.occurrences.get(wait.selection.operation)
            if occurrence is None or original is None or original[0].id != occurrence.operation:
                issue('wait_selection', path, 'known selection references an absent or mismatched original Use')
        work = ctx.submissions.get(wait.ticket)
        if work is None:
            issue('wait_ticket', path, 'queue wait references unknown work')
            continue
        aligned = point_for_work(wait.observed_at, work, path)
        prefix = queue(work, path)
        if type(wait.record) is Unresolved:
            gap('wait_record_unresolved', path, wait.record.reason)
            continue
        record = ctx.event_records.get(wait.record)
        if record is None:
            issue('wait_record', path, 'wait does not select an exact existing event record generation')
            continue
        if prefix is None or record.event not in ctx.resources:
            continue
        aligned = same_scope(_scope(ctx, record.observed_at), _work_scope(ctx, work), path) and aligned
        location, post = generations.get(record.id, (None, None))
        bound = event_access(wait.event_access, record.event, work, location, path)
        if type(wait.selection) is Unresolved:
            gap('wait_selection_unresolved', path, wait.selection.reason)
            continue
        selection = wait.selection
        original = ctx.core_uses.get(selection.use)
        if (selection.operation not in ctx.occurrences or original is None
                or original[0].id != ctx.occurrences[selection.operation].operation):
            issue('wait_selection', path, 'selection is not an original Use of this occurrence')
            continue
        if type(work.origin) is WithinOperation and selection.operation != work.origin.operation:
            issue('wait_selection_owner', path, 'selection belongs to another submission occurrence')
            continue
        state = ctx.core_values[original[1].value]
        if type(state) is not StateVersionValue or location is not None and state.location != location:
            issue('wait_selection_location', path, 'wait must read the exact event state location')
            continue
        operation = original[0]
        if not any(access.before == selection.use and access.location == state.location
                   and access.mode in (AccessMode.READ, AccessMode.READ_WRITE)
                   for access in operation.accesses):
            # INVOKE has no ordinary StateAccess. A bare argument is still not
            # a read association: require its validated exact boundary effect.
            is_invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
            if is_invoke and selection.use in operation.invoke_arguments:
                if not any(type(effect) is InvokeBoundaryStateEffect and effect.state_input == selection
                           for effect in work.effects):
                    gap('wait_selection_read_unresolved', path, 'invoke event argument lacks a validated work state-effect association')
                    continue
            else:
                issue('wait_selection_read', path, 'selection must be an original event-state read, not an unrelated operand')
                continue
        binding = ctx.uses.get((selection.operation, selection.use))
        actual = None if binding is None or type(binding.value) is Unresolved else _state_root(ctx, binding.value)
        expected = None if post is None else _state_root(ctx, post)
        if actual is None or expected is None:
            gap('wait_generation_unresolved', path, 'actual event state or record post-state is not established')
            continue
        if actual != expected:
            if (record.event, actual) in generation_owners:
                issue('wait_generation', path, 'wait selection denotes another known record generation, not the named record')
            else:
                gap('wait_generation_unresolved', path, 'an intervening state transition has no established record-generation correspondence')
            continue
        gap('protocol_applicability', path, 'wait association does not verify native enqueue, scope or error propagation')
        if aligned and bound and record.id in active_records:
            edge(EventSignal(record.id), WorkEnd(work.id), 'exact-event-wait', wait, record)

    # All sources participate together; checking each family separately misses
    # FIFO + dependency + wait cycles. Raw observations stay in EvidenceGraph.
    indegree = {}
    for step in ctx.order_steps:
        indegree.setdefault(step.source, 0)
        indegree[step.target] = indegree.get(step.target, 0) + 1
    pending = deque(node for node, degree in indegree.items() if not degree)
    count = 0
    while pending:
        node = pending.popleft()
        count += 1
        for step in ctx.order_adjacency.get(node, ()):
            indegree[step.target] -= 1
            if not indegree[step.target]:
                pending.append(step.target)
    if count != len(indegree):
        issue('cycle', 'order', 'combined declared strict order contains a cycle; it cannot prove itself')


__all__ = ['OrderStep', 'order_errors']

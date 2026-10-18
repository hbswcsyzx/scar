"""Check declared work against canonical ports without inferring ready or free."""
from collections import deque

from scar.ir.program.model import BlockArgument, CompletionResult, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.resources import ResourceRole
from scar.ir.v2.common import Completeness
from .common import EvidencePoint, Unresolved
from .coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from .ids import (
    OperationOccurrenceID, QueuePrefixID, ResourceAccessID, ValueOccurrenceID,
    WorkQuiescenceID,
)
from .resources import (
    AllocationTarget, InstanceTarget, ProcessRealm, ProcessTarget, RunRealm, ThreadTarget,
)
from .work import (
    ActualCompletionState, BorrowRelease, DirectExecution, ExternalWorkSource,
    HandleTarget, InvokeBoundaryStateEffect, MaterializationRef, QueueStart,
    Queued, WithinOperation,
)


def materialization_key(ref):
    return ref.artifact.sha256, ref.artifact.schema, ref.artifact.size_bytes, ref.materialization


def effect_key(effect):
    if type(effect) is AccessRef:
        return 'access', effect.operation, effect.index
    return 'invoke', effect.invocation, effect.state_input.use


def work_errors(ctx):
    requirements_by_id = {row.id: row for row in ctx.program.resource_requirements}
    def issue(code, path, message):
        ctx.issue('work_' + code, path, message)

    def gap(code, path, message):
        ctx.gap('work_' + code, path, message)

    def point_scope(point, path):
        ctx.check_point(point, path)
        if type(point) is EvidencePoint:
            return point.run, point.process
        if point.operation not in ctx.occurrences:
            return None, None
        activation = ctx.activations[ctx.activation_of(point.operation)]
        process = ctx.processes[activation.process]
        return process.run, process.id

    def operation_scope(identity, path):
        if identity not in ctx.occurrences:
            issue('operation', path, 'unknown core operation occurrence')
            return None, None
        return point_scope(OccurrencePoint(identity, OccurrencePhase.BEFORE), path)

    scopes = {}
    for row in ctx.model.submissions:
        path = f'submissions[{row.id}]'
        if type(row.origin) is WithinOperation:
            scopes[row.id] = operation_scope(row.origin.operation, path)
        else:
            scopes[row.id] = point_scope(row.origin.point, path)
            gap('external_alignment', path, 'external work has no established core submission occurrence')

    def ticket(identity, path):
        row = ctx.submissions.get(identity)
        if row is None:
            issue('ticket', path, 'unknown work submission ticket')
        return row

    def same_run(expected, actual, path):
        if expected is not None and actual is not None and expected != actual:
            issue('run_scope', path, 'work association crosses known execution runs')

    def point_for_work(point, work, path):
        run, process = point_scope(point, path)
        same_run(scopes.get(work.id, (None, None))[0], run, path)
        return run, process

    def terminal_point(point, work, path):
        point_for_work(point, work, path)
        if type(work.origin) is WithinOperation and work.origin.operation in ctx.occurrences:
            entry = OccurrencePoint(work.origin.operation, OccurrencePhase.BEFORE)
            order = ctx.point_precedes(entry, point)
            if point == entry or order is False:
                issue('observation_before_submission', path, 'work observation precedes entry to its enclosing submission operation')
            elif order is None:
                gap('observation_order_unresolved', path, 'submission-to-observation order needs an explicit cross-activation/native correspondence')

    def check_materialization(ref, path):
        graph = ctx.external_values(ref.artifact, path)
        if graph is None:
            return None, None
        row = graph.materializations.get(ref.materialization)
        if row is None:
            issue('materialization', path, 'materialization is absent from its exact ValueGraph')
            return graph, None
        if row.producer is not None:
            gap('materialization_producer_scope', path,
                'legacy materialization producer needs an artifact-scoped correspondence to core work')
        return graph, row

    def check_effect(effect, work, path):
        if type(effect) is AccessRef:
            occurrence = ctx.occurrences.get(effect.operation)
            if occurrence is None:
                issue('effect_operation', path, 'access references an unknown operation occurrence')
                return
            op = ctx.core_operations[occurrence.operation]
            if effect.index >= len(op.accesses):
                issue('effect_access', path, 'effect does not select an original StateAccess')
                return
            identity = effect.operation
        else:
            identity = effect.invocation
            occurrence = ctx.occurrences.get(identity)
            if occurrence is None:
                issue('effect_operation', path, 'boundary effect references an unknown invocation')
                return
            op = ctx.core_operations[occurrence.operation]
            if op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:
                issue('invoke_kind', path, 'boundary state effect requires an actual canonical INVOKE')
                return
            original = ctx.core_uses.get(effect.state_input.use)
            if (effect.state_input.operation != identity or original is None
                    or original[0].id != op.id or effect.state_input.use not in op.invoke_arguments):
                issue('invoke_input', path, 'state input is not an exact original invoke argument Use')
                return
            value = ctx.core_values[original[1].value]
            if type(value) is not StateVersionValue:
                issue('invoke_input', path, 'boundary effect input must be a StateVersionValue Use')
                return
            use = ctx.uses.get((identity, effect.state_input.use))
            if use is None or type(use.value) is Unresolved:
                gap('invoke_input_unobserved', path, 'actual state input occurrence is not established')
            else:
                ctx.check_support((use.value,), OccurrencePoint(identity, OccurrencePhase.BEFORE), path)
            if type(effect.post) is Unresolved:
                gap('invoke_post_unresolved', path, effect.post.reason)
            else:
                post = effect.post
                if post.successor_index >= len(op.terminator.successors):
                    issue('invoke_successor', path, 'post does not select a canonical completion successor')
                    return
                successor = op.terminator.successors[post.successor_index]
                transfer = ctx.outgoing.get(identity)
                if transfer is None:
                    gap('invoke_completion_unobserved', path, 'no actual completion transfer establishes this post')
                elif transfer.successor_index != post.successor_index:
                    issue('invoke_actual_edge', path, 'post selects a different outcome than this invocation actually took')
                formal = ctx.values.get(post.formal)
                core = None if formal is None else ctx.core_values[formal.value]
                if (type(core) is not StateVersionValue or type(core.origin) is not BlockArgument
                        or core.origin.block != successor.block or core.location != value.location):
                    issue('invoke_formal', path, 'post must reference the state formal of this exact completion and location')
                    return
                argument = successor.arguments[core.origin.index]
                if type(argument) is not CompletionResult or argument.index != post.result_index:
                    issue('invoke_result', path, 'post index is not the exact original CompletionResult at this formal')
                if transfer is not None and formal.origin != transfer.target:
                    issue('invoke_formal_visit', path, 'post formal comes from another landing traversal')
                if ctx.value_activation(post.formal) != ctx.activation_of(identity):
                    issue('invoke_formal_scope', path, 'post formal belongs to another body activation')
        run, _ = operation_scope(identity, path)
        same_run(scopes.get(work.id, (None, None))[0], run, path)
        if type(work.origin) is WithinOperation and work.origin.operation != identity:
            owner = work.origin.operation
            if owner in ctx.occurrences:
                if ctx.activation_of(owner) == ctx.activation_of(identity):
                    issue('effect_owner', path, 'another sequential operation is not an effect inside this exact submission occurrence')
                else:
                    gap('effect_nested_alignment', path, 'nested effect needs a precise dynamic parent/callee correspondence')
        gap('effect_physical_alignment', path, 'canonical boundary/access reference does not prove physical work-effect alignment')

    def access_target(identity, path, role=None):
        access = ctx.accesses.get(identity)
        if access is None:
            issue('resource_access', path, 'unknown exact ResourceAccessBinding')
            return None, None
        binding = ctx.requirements.get(access.requirement)
        if binding is None:
            issue('resource_binding', path, 'resource access has no exact requirement binding')
            return None, access
        requirement = requirements_by_id[binding.requirement]
        if role is not None and requirement.role is not role:
            issue('resource_role', path, 'resource access does not have the required executor/queue role')
        return binding.target, access

    def access_for_work(identity, work, path, role=None):
        target, access = access_target(identity, path, role)
        if access is not None:
            run, _ = operation_scope(access.operation, path)
            same_run(scopes.get(work.id, (None, None))[0], run, path)
            if type(work.origin) is WithinOperation and access.operation != work.origin.operation:
                gap('resource_access_alignment', path, 'resource access and internal submission need a precise occurrence correspondence')
        return target

    # Queue boundaries are persistent links, not a duplicated list or an ID order.
    for row in ctx.model.queue_prefixes:
        path = f'queue_prefixes[{row.id}]'
        observed_run, observed_process = point_scope(row.observed_at, path)
        resource = ctx.resources.get(row.queue)
        if resource is None or resource.role is not ResourceRole.QUEUE:
            issue('prefix_queue', path, 'queue prefix requires an existing QUEUE instance')
        elif type(resource.realm) is RunRealm:
            if observed_run is not None and resource.realm.run != observed_run:
                issue('prefix_scope', path, 'queue boundary belongs to another known run than its queue identity')
        elif type(resource.realm) is ProcessRealm:
            process = ctx.processes[resource.realm.process]
            if ((observed_run is not None and process.run != observed_run)
                    or (observed_process is not None and process.id != observed_process)):
                issue('prefix_scope', path, 'queue boundary belongs to another known process/run than its queue identity')
        else:
            gap('prefix_scope_unresolved', path, 'external queue realm needs an explicit capture-scope correspondence')
        if type(row.previous) is QueuePrefixID:
            previous = ctx.queue_prefixes.get(row.previous)
            if previous is None or previous.queue != row.queue:
                issue('prefix_previous', path, 'previous boundary is absent or belongs to another queue lifetime')
        elif type(row.previous) is Unresolved:
            gap('prefix_previous_unresolved', path, row.previous.reason)
        if row.work is not None:
            work = ticket(row.work, path)
            if work is not None:
                terminal_point(row.observed_at, work, path)
                if type(work.scheduling) is not Queued or work.scheduling.prefix != row.id:
                    issue('prefix_submission', path, 'boundary work must select this exact prefix in its Queued scheduling')
        gap('queue_protocol_unverified', path, 'declared queue protocol and boundary are not runtime ordering evidence')

    def acyclic(nodes, predecessors, code):
        indegree, successors = {key: 0 for key in nodes}, {key: [] for key in nodes}
        for key in nodes:
            for parent in predecessors(nodes[key]):
                if parent in nodes:
                    indegree[key] += 1
                    successors[parent].append(key)
        pending = deque(key for key in nodes if indegree[key] == 0)
        count = 0
        while pending:
            key = pending.popleft()
            count += 1
            for child in successors[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    pending.append(child)
        if count != len(nodes):
            issue(code, code, 'declared causal predecessor links contain a cycle')

    acyclic(ctx.queue_prefixes, lambda row: (row.previous,) if type(row.previous) is QueuePrefixID else (), 'prefix_cycle')
    acyclic(ctx.submissions, lambda row: row.dependencies, 'dependency_cycle')

    for work in ctx.model.submissions:
        path = f'submissions[{work.id}]'
        for dependency in work.dependencies:
            if ticket(dependency, path) is not None:
                same_run(scopes[work.id][0], scopes[dependency][0], path)
        if type(work.executor) is Unresolved:
            gap('executor_unresolved', path, work.executor.reason)
        else:
            access_for_work(work.executor, work, path, ResourceRole.EXECUTOR)
        if type(work.scheduling) is Queued:
            target = access_for_work(work.scheduling.queue_access, work, path, ResourceRole.QUEUE)
            prefix = ctx.queue_prefixes.get(work.scheduling.prefix)
            if prefix is None:
                issue('scheduling_prefix', path, 'queued work references an unknown queue prefix')
            elif type(target) is not InstanceTarget or prefix.queue != target.instance or prefix.work != work.id:
                issue('scheduling_queue', path, 'queue access, prefix instance and exact submission ticket do not match')
        elif type(work.scheduling) is DirectExecution:
            if type(work.scheduling.thread) is Unresolved:
                gap('direct_thread_unresolved', path, work.scheduling.thread.reason)
            else:
                thread = ctx.threads.get(work.scheduling.thread)
                if thread is None:
                    issue('direct_thread', path, 'direct execution references an unknown host thread incarnation')
                else:
                    process = ctx.processes[thread.process]
                    same_run(scopes[work.id][0], process.run, path)
                    if scopes[work.id][1] is not None and scopes[work.id][1] != process.id:
                        issue('direct_process', path, 'direct execution thread belongs to another process')
        else:
            gap('scheduling_unresolved', path, work.scheduling.reason)
        keys = [effect_key(effect) for effect in work.effects]
        if len(keys) != len(set(keys)):
            issue('effect_duplicate', path, 'one canonical effect endpoint has duplicate submitted associations')
        for effect in work.effects:
            check_effect(effect, work, path)
        mats = [materialization_key(ref) for ref in work.materializations]
        if len(mats) != len(set(mats)):
            issue('materialization_duplicate', path, 'source URI aliases do not create distinct materialization identities')
        for ref in work.materializations:
            check_materialization(ref, path)
        for name in ('dependencies', 'effects', 'materializations'):
            if getattr(work, name + '_coverage') is not Completeness.COMPLETE:
                gap(name + '_coverage', path, 'the declared ' + name + ' set has incomplete coverage')
        if type(work.retention) is Unresolved:
            gap('retention_unresolved', path, work.retention.reason)
        else:
            for identity in work.retention:
                row = ctx.retentions.get(identity)
                if row is None or row.ticket != work.id:
                    issue('retention_owner', path, 'retention reference is missing or belongs to another ticket')
        gap('submission_protocol_unverified', path, 'submission alignment/coverage and native protocol applicability remain unverified')

    for row in ctx.model.quiescences:
        path = f'quiescences[{row.id}]'
        work = ticket(row.ticket, path)
        if work is not None:
            terminal_point(row.observed_at, work, path)
        gap('quiescence_unverified', path, 'a declared quiescence observation is not a runtime/native verification')

    kinds = {}
    for row in ctx.model.outcomes:
        path = f'outcomes[{row.id}]'
        work = ticket(row.ticket, path)
        if work is None:
            continue
        terminal_point(row.observed_at, work, path)
        if row.ticket in kinds and kinds[row.ticket] is not row.kind:
            issue('outcome_conflict', path, 'one ticket has conflicting known terminal kinds; observations cannot overwrite each other')
        kinds[row.ticket] = row.kind
        submitted = {effect_key(effect) for effect in work.effects}
        frontier = [effect_key(effect) for effect in row.effect_frontier]
        if len(frontier) != len(set(frontier)):
            issue('frontier_duplicate', path, 'frontier repeats one canonical effect endpoint')
        for effect in row.effect_frontier:
            check_effect(effect, work, path)
            if effect_key(effect) not in submitted:
                if work.effects_coverage is Completeness.COMPLETE:
                    issue('frontier_submission', path, 'actual frontier contradicts the complete submitted effect association')
                else:
                    gap('frontier_alignment', path, 'actual frontier has no established submitted effect association')
        if type(row.protocol_result) is ValueOccurrenceID:
            result = ctx.values.get(row.protocol_result)
            if result is None:
                issue('protocol_result', path, 'protocol result is not an original value occurrence')
            else:
                activation = ctx.activations[ctx.value_activation(row.protocol_result)]
                same_run(scopes[row.ticket][0], ctx.processes[activation.process].run, path)
        elif type(row.protocol_result) is Unresolved:
            gap('protocol_result_unresolved', path, row.protocol_result.reason)
        if type(row.quiescence) is WorkQuiescenceID:
            quiet = ctx.quiescences.get(row.quiescence)
            if quiet is None or quiet.ticket != row.ticket:
                issue('outcome_quiescence', path, 'quiescence is missing or belongs to another ticket')
        else:
            gap('outcome_quiescence_unresolved', path, row.quiescence.reason)
        if row.frontier_coverage is not Completeness.COMPLETE:
            gap('frontier_coverage', path, 'actual effect frontier has incomplete coverage')
        gap('outcome_content_unverified', path, 'terminal kind/frontier does not establish whole produced content or visibility')

    def check_target(target, work, path):
        run = scopes.get(work.id, (None, None))[0]
        if type(target) is MaterializationRef:
            check_materialization(target, path)
        elif type(target) is AllocationTarget:
            graph = ctx.external_values(target.artifact, path)
            if graph is not None and target.allocation not in graph.allocations:
                issue('retention_allocation', path, 'retained allocation is absent from the exact external graph')
        elif type(target) is HandleTarget:
            handle = ctx.handles.get(target.binding)
            if handle is None:
                issue('retention_handle', path, 'retained handle binding is missing')
            else:
                actual, _ = point_scope(handle.start, path)
                same_run(run, actual, path)
        elif type(target) is InstanceTarget:
            resource = ctx.resources.get(target.instance)
            if resource is None:
                issue('retention_instance', path, 'retained resource instance is missing')
            elif type(resource.realm) is RunRealm:
                same_run(run, resource.realm.run, path)
            elif type(resource.realm) is ProcessRealm:
                same_run(run, ctx.processes[resource.realm.process].run, path)
        elif type(target) is ProcessTarget:
            process = ctx.processes.get(target.process)
            if process is None:
                issue('retention_process', path, 'retained process incarnation is missing')
            else:
                same_run(run, process.run, path)
        elif type(target) is ThreadTarget:
            thread = ctx.threads.get(target.thread)
            if thread is None:
                issue('retention_thread', path, 'retained thread incarnation is missing')
            else:
                same_run(run, ctx.processes[thread.process].run, path)

    def retained_resource_key(target, path):
        if type(target) is HandleTarget:
            handle = ctx.handles.get(target.binding)
            return None if handle is None else retained_resource_key(handle.target, path)
        if type(target) is MaterializationRef:
            graph, mat = check_materialization(target, path)
            if mat is None or mat.region is None:
                return None
            region = graph.regions[mat.region]
            return 'allocation', target.artifact.sha256, target.artifact.schema, target.artifact.size_bytes, region.allocation
        if type(target) is AllocationTarget:
            return 'allocation', target.artifact.sha256, target.artifact.schema, target.artifact.size_bytes, target.allocation
        if type(target) is InstanceTarget:
            return 'instance', target.instance
        if type(target) is ProcessTarget:
            return 'process', target.process
        if type(target) is ThreadTarget:
            return 'thread', target.thread
        return None

    for row in ctx.model.retentions:
        path = f'retentions[{row.id}]'
        work = ticket(row.ticket, path)
        if work is None:
            continue
        if type(work.retention) is tuple and row.id not in work.retention:
            issue('retention_backlink', path, 'retained work does not reference this retention in its declared set')
        check_target(row.target, work, path)
        if type(row.start) is WithinOperation:
            operation_scope(row.start.operation, path)
            entry = OccurrencePoint(row.start.operation, OccurrencePhase.BEFORE)
            point_for_work(entry, work, path)
            # WithinOperation is an enclosing interval, never an invented
            # BEFORE/AFTER location. Entry/post frontier values may be named;
            # this cannot establish which one was current at an internal start.
            possible_posts = set((ctx.after.get(row.start.operation) or {}).values())
            transfer = ctx.outgoing.get(row.start.operation)
            if transfer is not None:
                possible_posts.update((ctx.edges.get((row.start.operation, transfer.successor_index)) or {}).values())
            entry_support = tuple(value for value in row.support if value not in possible_posts)
            ctx.check_support(entry_support, entry, path)
            seen = set()
            for identity in row.support:
                occurrence = ctx.values.get(identity)
                value = None if occurrence is None else ctx.core_values[occurrence.value]
                if type(value) is not StateVersionValue:
                    issue('retention_support', path, 'internal start support must name original state occurrences')
                elif value.location in seen:
                    issue('retention_support', path, 'internal start support repeats a state location')
                else:
                    seen.add(value.location)
            start = None
            gap('retention_internal_start', path, 'internal borrow start has no exact host BEFORE/AFTER boundary')
        else:
            start = row.start
            point_for_work(start, work, path)
            ctx.check_support(row.support, start, path)
        if type(row.target) is HandleTarget:
            handle = ctx.handles.get(row.target.binding)
            if handle is not None:
                from .resources import EndedAt
                if type(handle.end) is EndedAt:
                    bound = entry if start is None else start
                    order = ctx.point_precedes(bound, handle.end.point)
                    if order is False or bound == handle.end.point:
                        issue('retention_handle_ended', path, 'borrow begins after the retained handle lifetime ended')
                    elif order is None or start is None:
                        gap('retention_handle_interval', path, 'handle lifetime does not establish the exact internal borrow interval')
        basis = row.basis
        if type(basis) is UseRef:
            original = ctx.core_uses.get(basis.use)
            occurrence = ctx.occurrences.get(basis.operation)
            if original is None or occurrence is None or original[0].id != occurrence.operation:
                issue('retention_use', path, 'retention basis is not an exact canonical Use occurrence')
            elif (basis.operation, basis.use) not in ctx.uses:
                gap('retention_use_unobserved', path, 'basis Use has no established dynamic binding')
            elif type(row.target) is HandleTarget:
                handle = ctx.handles.get(row.target.binding)
                endpoint = None if handle is None else getattr(handle.handle, 'value', None)
                actual = ctx.uses[basis.operation, basis.use].value
                if endpoint is not None and endpoint in ctx.values and type(actual) is ValueOccurrenceID:
                    held_value = ctx.core_values[ctx.values[endpoint].value]
                    basis_value = ctx.core_values[ctx.values[actual].value]
                    if (type(held_value) is ReferenceValue) != (type(basis_value) is ReferenceValue):
                        issue('retention_use_type', path, 'direct basis cannot denote both a Python reference handle and a native scalar handle')
                    elif endpoint != actual:
                        gap('retention_use_denotation', path, 'different same-kind values require a handle alias/denotation correspondence')
                else:
                    gap('retention_use_denotation', path, 'direct Use-to-handle correspondence is unresolved')
            else:
                gap('retention_use_denotation', path, 'Use-to-retained-target denotation is not established')
        elif type(basis) is AccessRef:
            check_effect(basis, work, path)
        elif type(basis) is ResourceAccessID:
            target = access_for_work(basis, work, path)
            accessed = retained_resource_key(target, path)
            held = retained_resource_key(row.target, path)
            if accessed is not None and held is not None:
                if accessed != held:
                    issue('retention_target_basis', path, 'direct resource access basis and retained referent contradict each other')
            else:
                gap('retention_target_basis_unresolved', path, 'basis and retained target have no established physical-resource correspondence')
        elif type(basis) is MaterializationRef:
            graph, mat = check_materialization(basis, path)
            if type(row.target) is MaterializationRef and materialization_key(row.target) != materialization_key(basis):
                issue('retention_target_basis', path, 'basis and target name different materializations')
            elif type(row.target) is AllocationTarget and mat is not None and mat.region is not None:
                region = graph.regions[mat.region]
                if (row.target.artifact.sha256 != basis.artifact.sha256 or row.target.allocation != region.allocation):
                    issue('retention_target_basis', path, 'materialization basis does not use the retained allocation lifetime')
        else:
            gap('retention_basis_unresolved', path, basis.reason)
        if type(row.release) is BorrowRelease:
            release = row.release
            point_for_work(release.point, work, path)
            if start is None:
                if ctx.point_precedes(entry, release.point) is False or release.point == entry:
                    issue('retention_interval', path, 'borrow release precedes the enclosing internal-start operation')
                gap('retention_interval_unresolved', path, 'exact internal borrow start cannot be placed at an invented host point')
            elif ctx.point_precedes(start, release.point) is False:
                issue('retention_interval', path, 'borrow release precedes its start')
            elif ctx.point_precedes(start, release.point) is None:
                gap('retention_interval_unresolved', path, 'borrow interval is not established by recorded host flow')
            if type(release.quiescence) is WorkQuiescenceID:
                quiet = ctx.quiescences.get(release.quiescence)
                if quiet is None or quiet.ticket != row.ticket:
                    issue('retention_quiescence', path, 'release references missing or another ticket quiescence')
                else:
                    ordered = ctx.point_precedes(quiet.observed_at, release.point)
                    if ordered is False:
                        issue('release_before_quiescence', path, 'release precedes the cited quiescence observation')
                    elif ordered is None:
                        gap('release_order_unresolved', path, 'quiescence-to-release order is not established')
            else:
                gap('release_quiescence_unresolved', path, release.quiescence.reason)
        else:
            gap('retention_release_unresolved', path, row.release.reason)
        gap('retention_lifetime_unverified', path, 'borrow coverage/release authority and all competing accesses remain unverified; no free is authorized')


__all__ = ['materialization_key', 'effect_key', 'work_errors']

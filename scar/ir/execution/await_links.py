"""Exact occurrence projections of declared await/body links.

Original program ports own the data, CFG and state. These temporary indexes
join their captured occurrences; they add neither an execution record nor an
ordinary identity/copy edge for the native wrapper's held body.
"""
from copy import deepcopy

from scar.ir.program.ids import ProtocolScopeID
from scar.ir.program.model import CompletionResult, InvokeLiteralResult, OperationResult
from scar.ir.program.protocols import OwnedUse, StaticProtocolGap

from .common import Unresolved
from .coordinates import OccurrencePhase, OccurrencePoint
from .resumable_flow import gap, value_for_use


def _flags():
    return {'source_runtime_verified': False, 'runtime_identity_verified': False,
            'value_identity_verified': False, 'transformation_authorized': False}


def _use(ctx, occurrence, owned):
    if occurrence is None or type(owned) is not OwnedUse:
        return None
    if occurrence.operation != owned.operation:
        return None
    return ctx.uses.get((occurrence.id, owned.use))


def _result(ctx, occurrence, port):
    """This occurrence's own selected port, including nonzero N/R/slot."""
    if occurrence is None:
        return None
    if type(port) is OperationResult:
        operation = ctx.core_operations[occurrence.operation]
        if port.operation != operation.id or port.index >= len(operation.results):
            return None
        return ctx.results.get((occurrence.id, operation.results[port.index]))
    if type(port) is InvokeLiteralResult:
        transfer = ctx.outgoing.get(occurrence.id)
        if (port.edge.operation != occurrence.operation or transfer is None
                or transfer.successor_index != port.edge.successor_index):
            return None
        operation = ctx.core_operations[occurrence.operation]
        edge = operation.terminator.successors[transfer.successor_index]
        block = ctx.blocks[ctx.visits[transfer.target].block]
        for actual, formal in zip(edge.arguments, block.arguments):
            if type(actual) is CompletionResult and actual.index == port.result.index:
                return ctx.results.get((transfer.target, formal))
    return None


def _source_value(ctx, occurrence, row):
    from scar.ir.program.protocol_await_records import AwaitIteratorQualification
    if row is None:
        return None, None
    contract = row.contract
    if type(contract) is AwaitIteratorQualification and contract.branch is not None:
        from scar.ir.program.structured import ControlEdgeReference
        accepted = ControlEdgeReference(contract.branch, 0 if contract.accepts_true else 1)
        return value_for_use(ctx, _use(ctx, occurrence,
            OwnedUse(row.operation, contract.input_use))), accepted
    return _result(ctx, occurrence, getattr(contract, 'result', None)), None


def _source_input(ctx, occurrence, row):
    """Expected body starts upstream of the observed Drive instance."""
    from scar.ir.program.protocol_await_records import (
        AwaitAcquisition, AwaitIteratorQualification, CoroutineAwaitWrapper,
    )
    if row is None:
        return None
    contract = row.contract
    from scar.ir.program.protocol_await_records import ExpandedAwaitCallee
    if type(contract) is AwaitAcquisition and type(contract.expansion) is ExpandedAwaitCallee:
        return None  # A general awaitable A is not the iterator B returned by its method.
    field = ('operand_use' if type(contract) is AwaitAcquisition else
             'input_use' if type(contract) is AwaitIteratorQualification else
             'body_use' if type(contract) is CoroutineAwaitWrapper else None)
    return None if field is None else _use(ctx, occurrence,
        OwnedUse(row.operation, getattr(contract, field)))


def _body_input(ctx, flow, occurrence, row, source_value, shared):
    """Select B at its independent source, before looking at any Drive."""
    from scar.ir.program.protocol_await_records import (
        AwaitAcquisition, AwaitIteratorQualification, ExpandedAwaitCallee,
    )
    if row is None:
        return None, ('await_body_source_row_missing',)
    contract = row.contract
    if type(contract) is not AwaitAcquisition:
        return _source_input(ctx, occurrence, row), ()
    if type(contract.expansion) is not ExpandedAwaitCallee:
        from scar.ir.program.evaluated_sources import evaluated_sources
        from scar.ir.program.resumption import ResumableKind
        report = evaluated_sources(flow, contract.expected,
            OwnedUse(row.operation, contract.operand_use), role='DIRECT_INPUT')
        if (report['classification_complete'] and all(case['kind'] in (
                ResumableKind.COROUTINE, ResumableKind.GENERATOR_COROUTINE)
                for case in report['cases'])):
            return _source_input(ctx, occurrence, row), ()
        return None, ('await_acquisition_body_route_unproved',)
    ref = contract.expansion.qualification
    if type(ref) is StaticProtocolGap:
        return None, ('await_general_qualification_missing',)
    qualifier = ctx.await_protocol_rows.get((ref.scope, ref.clause, ref.operation, ref.slot))
    if qualifier is None or type(qualifier.contract) is not AwaitIteratorQualification:
        return None, ('await_general_qualification_missing',)
    calls = tuple(ctx.resolved_call_activations[identity]
                  for identity in ctx.call_activations_by_caller.get(occurrence.id, ()))
    matched = []
    for candidate in ctx.await_occurrences_by_site.get(ref.operation, ()):
        if not shared.spend('await_general_candidate_occurrences', path='await.general.body_source'):
            break
        for call in calls:
            if ctx.activation_of(candidate.id) != call['activation'].id:
                continue
            accepted, edge = _source_value(ctx, candidate, qualifier)
            if _root(ctx, accepted) is None or _root(ctx, accepted) != _root(ctx, source_value):
                continue
            if edge is not None:
                completion = call['completion']
                if completion is None or _guard(ctx, completion, edge, shared) is not True:
                    continue
            matched.append(_use(ctx, candidate,
                OwnedUse(qualifier.operation, qualifier.contract.input_use)))
    if len(matched) == 1 and not shared.truncated:
        return matched[0], ()
    return None, ('await_general_body_source_occurrence_unproved',)


def _selected_row(ctx, occurrence, row):
    if row is None:
        return None
    port = getattr(row.contract, 'result', None)
    if type(port) is OperationResult:
        return occurrence.operation == port.operation
    if type(port) is InvokeLiteralResult:
        transfer = ctx.outgoing.get(occurrence.id)
        return None if transfer is None else transfer.successor_index == port.edge.successor_index
    return None


def _drive_routes(ctx, advance, drive_site, shared):
    """Only the exact advance's explicit child-activation call chain."""
    if drive_site is None:
        return ()
    if advance.operation == drive_site:
        return ({'call_chain': (), 'drive_occurrence': advance},)
    pending = [(ctx.resolved_call_activations[identity], ())
               for identity in ctx.call_activations_by_caller.get(advance.id, ())]
    result, visited = [], set()
    while pending:
        if not shared.spend('await_call_activations', path='await.call_chain.search'):
            break
        call, chain = pending.pop()
        key = call['association'].id
        if key in visited:
            continue
        visited.add(key)
        chain = (*chain, call)
        activation = call['activation'].id
        for occurrence in ctx.await_drives_by_activation.get((activation, drive_site), ()):
            if not shared.spend('await_drive_occurrences', path='await.call_chain.drive'):
                break
            result.append({'call_chain': chain, 'drive_occurrence': occurrence})
        for child in ctx.await_calls_by_parent.get(activation, ()):
            if not shared.spend('await_nested_calls', path='await.call_chain.child'):
                break
            pending.append((child, chain))
    return tuple(result)


def prepare_await_indexes(ctx):
    """Only original record/occurrence indexes; no path or identity search."""
    from scar.ir.program.protocols import ProtocolProfile
    profiles = {ProtocolProfile.AWAIT_ACQUISITION_V1,
                ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
                ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
                ProtocolProfile.AWAIT_SITE_V1,
                ProtocolProfile.COROUTINE_AWAIT_WRAPPER_V1}
    ctx.await_jobs = ()
    ctx.await_protocol_rows = {}
    ctx.await_occurrences_by_site, ctx.await_calls_by_parent = {}, {}
    ctx.await_drives_by_activation = {}
    ctx.await_preparation = {'static_jobs': 0, 'captured_advances': 0,
        'captured_sources': 0, 'cost_scope': 'original inventory and captured-call indexing; '
        'separate from bounded projection traversal and detached result copying'}
    if not any(scope.profile in profiles for scope in ctx.program.protocol_scopes):
        return
    from scar.ir.program.queries import ProgramIndex
    index = ctx.body_program_index
    if index is None:
        index = ctx.body_program_index = ProgramIndex(ctx.program)
        ctx.body_preparation['program_indexes'] = 1
    for occurrence in ctx.occurrences.values():
        ctx.await_occurrences_by_site.setdefault(occurrence.operation, []).append(occurrence)
        if occurrence.operation in ctx.body_drives:
            key = ctx.activation_of(occurrence.id), occurrence.operation
            ctx.await_drives_by_activation.setdefault(key, []).append(occurrence)
    for call in ctx.resolved_call_activations.values():
        parent = ctx.activation_of(call['caller'].id)
        ctx.await_calls_by_parent.setdefault(parent, []).append(call)
    ctx.await_protocol_rows = {(row.scope, row.clause, row.operation, row.slot): row
            for row in ctx.program.protocol_operations}


def project_await_links(ctx, scope, shared):
    """Derive this scope with the public query's one shared traversal budget."""
    from scar.ir.program.protocol_await import await_inventory
    from scar.ir.program.protocol_await_records import AwaitBodyLink
    from scar.ir.program.protocol_connection_flow import ConnectionContext
    if ctx.body_program_index is None:
        return
    flow = ConnectionContext(ctx.program, index=ctx.body_program_index, budget=shared)
    inventory = await_inventory(flow, scope)
    rows = ctx.await_protocol_rows
    jobs = []
    for inventory_job in inventory['jobs']:
        job = dict(inventory_job)
        source = job.get('source')
        source_row = None if source is None else rows.get(
            (source.scope, source.clause, source.operation, source.slot))
        source_site = job.get('source_operation')
        if hasattr(source_site, 'id'):
            source_site = source_site.id
        advance_site = job.get('advance_operation')
        if hasattr(advance_site, 'id'):
            advance_site = advance_site.id
        source_occurrences = ctx.await_occurrences_by_site.get(source_site, ())
        sources = []
        for occurrence in source_occurrences:
            if not shared.spend('await_source_occurrences', path='await.sources'):
                break
            value, accepted_edge = _source_value(ctx, occurrence, source_row)
            body_input, body_gaps = _body_input(ctx, flow, occurrence, source_row, value, shared)
            sources.append({'occurrence': occurrence, 'value': value,
                'body_input': body_input, 'body_source_gaps': body_gaps,
                'accepted_edge': accepted_edge})
        occurrences = []
        for advance in ctx.await_occurrences_by_site.get(advance_site, ()):
            admitted = shared.spend('await_advance_occurrences', path='await.advances')
            ref = job.get('advance')
            advance_row = None if ref is None else rows.get(
                (ref.scope, ref.clause, ref.operation, ref.slot))
            selected = _selected_row(ctx, advance, advance_row) if admitted else None
            case = job.get('case')
            case_guard = job.get('input_guard', None if case is None else case.guard)
            case_selected = (_guard(ctx, advance, case_guard, shared, incoming=True)
                             if admitted else None)
            iterator_use = _use(ctx, advance, job.get('iterator_use'))
            if iterator_use is None and job.get('advance') is not None:
                site = job['advance']
                row = rows.get((site.scope, site.clause, site.operation, site.slot))
                receiver = getattr(None if row is None else row.contract, 'receiver_use', None)
                if receiver is not None:
                    iterator_use = _use(ctx, advance, OwnedUse(advance.operation, receiver))
            routes = (() if selected is False or case_selected is False or not admitted else
                      _drive_routes(ctx, advance, job.get('drive'), shared))
            occurrences.append({'advance': advance, 'advance_selected': selected,
                'case_selected': case_selected, 'case_guard': case_guard,
                'iterator_use': iterator_use,
                'iterator_value': value_for_use(ctx, iterator_use), 'routes': routes,
                'source_candidates': tuple(sources), 'bindings': (), 'gaps': (),
                'derived_checked': admitted and not shared.truncated})
        links = tuple(link for link in job.get('links', ()) if type(link) is AwaitBodyLink)
        jobs.append({**job, 'links': links, 'source_row': source_row,
            'source_occurrences': tuple(sources), 'source_occurrence_count': len(source_occurrences),
            'checked_source_occurrence_count': len(sources),
            'pending_source_occurrence_count': len(source_occurrences) - len(sources),
            'occurrences': tuple(occurrences)})
    ctx.await_jobs = tuple(jobs)
    ctx.await_inventory_summary = {key: value for key, value in inventory.items() if key != 'jobs'}
    ctx.await_preparation.update(static_jobs=len(jobs),
        captured_advances=sum(len(job['occurrences']) for job in jobs),
        captured_sources=sum(job['source_occurrence_count'] for job in jobs),
        checked_source_occurrences=sum(job['checked_source_occurrence_count'] for job in jobs),
        original_flow_preparation=dict(flow.preparation))


def _root(ctx, value):
    if value is None or type(value) is Unresolved:
        return None
    return ctx.body_value_roots.get(value.id)


def _guard(ctx, anchor, edge, shared, *, incoming=False):
    """Exact captured predecessor choice; no match by another activation's site."""
    if edge is None:
        return True
    target = ctx.core_operations[edge.operation].terminator.successors[edge.successor_index].block
    visit, seen = ctx.visits[anchor.visit], set()
    while visit.id not in seen:
        if not shared.spend('await_guard_visits', path='await.guard'):
            return None
        seen.add(visit.id)
        transfer = ctx.incoming.get(visit.id)
        if transfer is None:
            return None
        occurrence = ctx.occurrences[transfer.operation]
        if ctx.activation_of(occurrence.id) != ctx.activation_of(anchor.id):
            return None
        if incoming and visit.block == target:
            # The closest entry of this exact merge owns the current tuple.
            # An older loop iteration or a different incoming arm cannot
            # select the case merely because both carry the same object.
            return (occurrence.operation == edge.operation
                    and transfer.successor_index == edge.successor_index)
        if occurrence.operation == edge.operation:
            return transfer.successor_index == edge.successor_index
        visit = ctx.visits[occurrence.visit]
    return None


def _port_point(ctx, source):
    occurrence = source['occurrence']
    transfer = ctx.outgoing.get(occurrence.id)
    return OccurrencePoint(occurrence.id, OccurrencePhase.AFTER) if transfer is None else (
        OccurrencePoint(occurrence.id, OccurrencePhase.EDGE, transfer.successor_index))


def _accepted_edge(ctx, source, advance, shared):
    """A bool qualification's actual branch may be inside a returned helper."""
    edge = source['accepted_edge']
    if edge is None:
        return True
    from .host_order import host_path
    answers = []
    for occurrence in ctx.await_occurrences_by_site.get(edge.operation, ()):
        if not shared.spend('await_qualification_edges', path='await.qualification.edge'):
            return None
        if ctx.activation_of(occurrence.id) != ctx.activation_of(source['occurrence'].id):
            continue
        transfer = ctx.outgoing.get(occurrence.id)
        if transfer is None:
            continue
        before = OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE)
        selected = OccurrencePoint(occurrence.id, OccurrencePhase.EDGE, transfer.successor_index)
        target = OccurrencePoint(advance.id, OccurrencePhase.BEFORE)
        if (host_path(ctx, _port_point(ctx, source), before, budget=shared) is not None
                and host_path(ctx, selected, target, budget=shared) is not None):
            answers.append(transfer.successor_index == edge.successor_index)
    return answers[0] if len(answers) == 1 else None


def _required_choices(ctx, source, advance, choices, shared):
    """Project each required static edge in this exact source/caller context."""
    answers = []
    for edge in choices:
        if not shared.spend('await_required_choices', path='await.choices'):
            return None
        if edge == source['accepted_edge']:
            answers.append(_accepted_edge(ctx, source, advance, shared))
            continue
        owner_region = ctx.block_regions[ctx.operation_blocks[edge.operation].id]
        answer = None
        for anchor in (advance, source['occurrence']):
            region = ctx.activations[ctx.activation_of(anchor.id)].region
            if region != owner_region:
                continue
            if edge.operation == anchor.operation:
                transfer = ctx.outgoing.get(anchor.id)
                answer = None if transfer is None else transfer.successor_index == edge.successor_index
            else:
                answer = _guard(ctx, anchor, edge, shared)
            if answer is not None:
                break
        if answer is None:
            calls = (ctx.resolved_call_activations[identity] for identity in
                     ctx.call_activations_by_caller.get(source['occurrence'].id, ()))
            observed = []
            for call in calls:
                if call['activation'].region == owner_region and call['completion'] is not None:
                    observed.append(_guard(ctx, call['completion'], edge, shared))
            if len(observed) == 1:
                answer = observed[0]
        answers.append(answer)
    return False if any(answer is False for answer in answers) else (
        True if all(answer is True for answer in answers) else None)


def _copy_pair(ctx, expected, actual):
    return {'source_value': expected, 'formal': actual,
            'original_copy': (_root(ctx, expected) == _root(ctx, actual)
                              if _root(ctx, expected) is not None else None)}


def _wrapper_projection(ctx, source, advance, route, projection, gaps, shared):
    """Constructor W -> exact getter W/B -> this route's Drive instance.

    Expected B is read at the original constructor/lookup operand. It is never
    chosen from the drive or inferred from the only visible body activation.
    """
    from .host_order import host_path
    from .resumable_identity import compatible, distinct_objects
    ref = projection.constructor
    row = ctx.await_protocol_rows.get((ref.scope, ref.clause, ref.operation, ref.slot))
    constructors = []
    if row is not None:
        for occurrence in ctx.await_occurrences_by_site.get(ref.operation, ()):
            if not shared.spend('await_wrapper_constructors', path='await.wrapper.constructor'):
                break
            wrapper = _result(ctx, occurrence, row.contract.result)
            if _root(ctx, wrapper) is not None and _root(ctx, wrapper) == _root(ctx, source['value']):
                constructors.append((occurrence, wrapper))
    if len(constructors) != 1:
        gap(ctx, gaps, 'await_wrapper_constructor_occurrence_unproved', advance.id,
            'source W does not select exactly one original successful constructor occurrence')
        return {'projection': projection, 'constructors': tuple(constructors),
                'bindings': (), 'status': 'PARTIAL'}
    constructor, wrapper = constructors[0]
    bodies = []
    for occurrence in ctx.await_occurrences_by_site.get(projection.body.operation, ()):
        if not shared.spend('await_wrapper_body_operands', path='await.wrapper.body'):
            break
        actual = _use(ctx, occurrence, projection.body)
        if occurrence.id == constructor.id:
            bodies.append((occurrence, actual))
            continue
        # High-level zero-argument bound calls take B from the exact original
        # lookup receiver, not an invented call argument.
        if ctx.activation_of(occurrence.id) != ctx.activation_of(constructor.id):
            continue
        path = host_path(ctx, OccurrencePoint(occurrence.id, OccurrencePhase.AFTER),
                         OccurrencePoint(constructor.id, OccurrencePhase.BEFORE), budget=shared)
        if path is not None:
            bodies.append((occurrence, actual))
    if len(bodies) != 1:
        gap(ctx, gaps, 'await_wrapper_body_operand_unproved', constructor.id,
            'exact constructor/lookup B operand occurrence remains ambiguous or missing')
    if not shared.spend('await_wrapper_call_chain', len(route['call_chain']) + 1,
                        'await.wrapper.call_chain'):
        return {'projection': projection, 'bindings': (), 'status': 'NOT_CHECKED'}
    allowed = {ctx.activation_of(advance.id)}
    allowed.update(call['activation'].id for call in route['call_chain'])
    reads = []
    for occurrence in ctx.await_occurrences_by_site.get(projection.wrapper_read.operation, ()):
        if not shared.spend('await_wrapper_reads', path='await.wrapper.getter'):
            break
        if ctx.activation_of(occurrence.id) not in allowed:
            continue
        wrapper_use = _use(ctx, occurrence, projection.wrapper_read)
        wrapper_value = value_for_use(ctx, wrapper_use)
        body_result = _result(ctx, occurrence, projection.body_result)
        if _root(ctx, wrapper) is None or _root(ctx, wrapper) != _root(ctx, wrapper_value):
            continue
        drive = ctx.resolved_body_drives[route['drive_occurrence'].id]
        actual_body = drive['instance']['value']
        if (_root(ctx, body_result) is not None
                and _root(ctx, body_result) == _root(ctx, actual_body)):
            reads.append((occurrence, wrapper_value, body_result))
    if len(reads) != 1:
        gap(ctx, gaps, 'await_wrapper_read_occurrence_unproved', advance.id,
            'this exact call chain lacks one getter W/result B path to this Drive instance')
    bindings, distinctness = [], None
    if len(bodies) == len(reads) == 1:
        read, wrapper_value, body_result = reads[0]
        expected_body = value_for_use(ctx, bodies[0][1])
        drive = ctx.resolved_body_drives[route['drive_occurrence'].id]
        if shared.spend('await_wrapper_distinctness', path='await.wrapper.distinctness'):
            distinctness = distinct_objects(ctx, wrapper, expected_body, gaps,
                                           f'{advance.id}:native-wrapper-fresh-object')
        for left, right, role in ((wrapper, wrapper_value, 'wrapper_input'),
                (body_result, drive['instance']['value'], 'getter_to_drive'),
                (expected_body, body_result, 'native_held_body'),
                (expected_body, drive['instance']['creation_handle'], 'held_body_origin')):
            if not shared.spend('await_wrapper_comparisons', path='await.wrapper.compatibility'):
                break
            pair = _copy_pair(ctx, left, right)
            pair.update(role=role, compatibility=compatible(ctx, left, right, gaps,
                f'{advance.id}:{role}'))
            if role in ('native_held_body', 'held_body_origin'):
                pair['original_copy'] = None  # fixed native projection, not an ordinary copy
                pair['conditional_native_projection'] = True
            bindings.append(pair)
        expected_root = _root(ctx, expected_body)
        origin_root = _root(ctx, drive['instance']['creation_handle'])
        handles = ctx.body_known_create_handles
        if (expected_root in handles and origin_root in handles
                and expected_root != origin_root):
            ctx.issue('await_wrapper_body_source', advance.id,
                'native wrapper B operand belongs to another concrete Create handle')
    return {'projection': projection, 'constructor': constructor, 'wrapper': wrapper,
        'body_operands': tuple(bodies), 'reads': tuple(reads), 'bindings': tuple(bindings),
        'distinctness': distinctness,
        'status': 'DECLARED' if len(bodies) == len(reads) == 1 and not shared.truncated else 'PARTIAL'}


def await_identity_errors(ctx, shared):
    """Refresh conditional compatibility against this query's external snapshot."""
    from .resumable_identity import compatible
    from .host_order import host_path
    from scar.ir.program.protocol_await_records import WrapperHeldBody
    comparisons = 0
    for job in getattr(ctx, 'await_jobs', ()):
        for occurrence in job['occurrences']:
            gaps, bindings, candidates = [], [], []
            advance = occurrence['advance']
            if not shared.spend('await_binding_jobs', path='await.binding'):
                occurrence['derived_checked'] = False
                continue
            for route in occurrence['routes']:
                route['projections'] = ()
            if occurrence['advance_selected'] is False or occurrence['case_selected'] is False:
                occurrence.update(matched_sources=(), bindings=(), gaps=())
                continue
            if occurrence['case_selected'] is None and occurrence['case_guard'] is not None:
                gap(ctx, gaps, 'await_input_case_guard_unobserved', advance.id,
                    'this exact advance does not establish the original incoming case guard')
            target = OccurrencePoint(advance.id, OccurrencePhase.BEFORE)
            for source in occurrence['source_candidates']:
                if not shared.spend('await_source_candidates', path='await.source_candidates'):
                    break
                expected, actual = source['value'], occurrence['iterator_value']
                root = _root(ctx, expected)
                if root is None or root != _root(ctx, actual):
                    continue
                guard = _accepted_edge(ctx, source, advance, shared)
                choices = _required_choices(ctx, source, advance, job.get('choices', ()), shared)
                path = host_path(ctx, _port_point(ctx, source), target, budget=shared)
                if guard is False or choices is False or path is None:
                    continue
                candidates.append({**source, 'host_path': path, 'accepted': guard,
                                   'required_choices': choices})
            if not candidates:
                gap(ctx, gaps, 'await_source_occurrence_unproved', advance.id,
                    'no exact captured source port/copy/path supplies this iterator')
            if occurrence['advance_selected'] is None:
                gap(ctx, gaps, 'await_advance_completion_unobserved', advance.id,
                    'actual advance completion edge is not captured')
            elif len(candidates) != 1:
                gap(ctx, gaps, 'await_source_occurrence_ambiguous', advance.id,
                    'multiple source evaluations remain; static site or equal object does not select one')
            if len(candidates) == 1 and not shared.truncated:
                source = candidates[0]
                for code in source['body_source_gaps']:
                    gap(ctx, gaps, code, advance.id,
                        'independent source does not yet select this actual iterator body input')
                pair = _copy_pair(ctx, source['value'], occurrence['iterator_value'])
                pair['compatibility'] = compatible(ctx, pair['source_value'], pair['formal'],
                    gaps, f'{advance.id}:await-iterator')
                bindings.append(pair)
                comparisons += 1
                if source['accepted'] is not True:
                    gap(ctx, gaps, 'await_accepted_edge_unobserved', advance.id,
                        'boolean qualification accepted edge is not captured on this exact path')
                if source['required_choices'] is not True:
                    gap(ctx, gaps, 'await_required_choice_unobserved', advance.id,
                        'not every required edge is captured in this exact source/caller context')
                for route in occurrence['routes']:
                    projections = []
                    for link in job['links']:
                        if not shared.spend('await_projection_links', path='await.projection'):
                            break
                        selected = _guard(ctx, advance, link.guard, shared)
                        if selected is False:
                            continue
                        if selected is None:
                            gap(ctx, gaps, 'await_link_guard_unobserved', advance.id,
                                'original link guard is not captured on this exact call path')
                        if type(link.projection) is WrapperHeldBody:
                            view = _wrapper_projection(ctx, source, advance, route,
                                                       link.projection, gaps, shared)
                            projections.append(view)
                            comparisons += len(view['bindings'])
                        elif type(link.projection) is StaticProtocolGap:
                            gap(ctx, gaps, 'await_body_projection_unresolved', advance.id,
                                'supplied native/body relation remains an explicit static gap')
                        else:
                            drive = ctx.resolved_body_drives[route['drive_occurrence'].id]
                            expected = value_for_use(ctx, source['body_input'])
                            if expected is None:
                                expected = source['value']
                            pair = _copy_pair(ctx, expected, drive['instance']['creation_handle'])
                            pair['compatibility'] = compatible(ctx, expected,
                                drive['instance']['creation_handle'], gaps,
                                f'{advance.id}:await-body-origin')
                            expected_root = _root(ctx, expected)
                            actual_root = _root(ctx, drive['instance']['creation_handle'])
                            handles = ctx.body_known_create_handles
                            if (expected_root in handles and actual_root in handles
                                    and expected_root != actual_root):
                                ctx.issue('await_body_source', advance.id,
                                    'independent await operand belongs to another concrete Create')
                            projections.append({'projection': None, 'bindings': (pair,),
                                                'status': 'DECLARED'})
                            comparisons += 1
                    route['projections'] = tuple(projections)
            if not job['links']:
                gap(ctx, gaps, 'await_body_link_missing', advance.id,
                    'source-first obligation has no original AwaitBodyLink')
            if not occurrence['routes'] and job.get('drive') is not None:
                gap(ctx, gaps, 'await_drive_call_chain_missing', advance.id,
                    'exact advance has no captured call chain to this original Drive')
            occurrence.update(matched_sources=tuple(candidates), bindings=tuple(bindings),
                              gaps=tuple(gaps), derived_checked=not shared.truncated)
    ctx.await_identity_preparation = {'binding_comparisons': comparisons,
        'fresh_external_context': True, 'native_identity_proven': False}


def await_body_links(ctx, scope, *, shared):
    """Detached, bounded occurrence projection retaining every inventory job."""
    if type(scope) is not ProtocolScopeID:
        raise TypeError('await body links require an exact ProtocolScopeID')
    scope.__post_init__()
    if not any(row.id == scope for row in ctx.program.protocol_scopes):
        raise ValueError('await body links scope is not declared')
    project_await_links(ctx, scope, shared)
    await_identity_errors(ctx, shared)
    from .resumable_query import drive_execution
    jobs, cursor, checked, checked_jobs, all_gaps = [], None, 0, 0, []
    pending_copies = []
    originals = tuple(job for job in ctx.await_jobs if job['scope'] == scope)
    for number, original in enumerate(originals):
        job = {key: value for key, value in original.items()
               if key not in ('occurrences', 'source_occurrences', 'source_row')}
        allowed = shared.spend('await_jobs', path=f'await.jobs[{number}]')
        checked_jobs += int(allowed)
        if not original['occurrences']:
            job['gaps'] = (*job.get('gaps', ()), 'await_advance_occurrence_missing')
        occurrences = []
        for ordinal, prepared in enumerate(original['occurrences']):
            admitted = allowed and prepared['derived_checked'] and shared.spend('await_occurrences',
                path=f'await.jobs[{number}].occurrences[{ordinal}]')
            compatibility_cost = len(prepared['bindings']) + len(prepared.get('matched_sources', ()))
            compatibility_cost += sum(len(projection['bindings'])
                for route in prepared['routes'] for projection in route.get('projections', ()))
            compatibility_cost += sum(projection.get('distinctness') is not None
                for route in prepared['routes'] for projection in route.get('projections', ()))
            admitted = admitted and shared.spend('await_binding_projection', compatibility_cost + 1,
                path=f'await.jobs[{number}].occurrences[{ordinal}].bindings')
            row = {key: value for key, value in prepared.items() if key != 'routes'}
            routes = []
            for route in prepared['routes']:
                if not admitted or not shared.spend('await_call_chain',
                        len(route['call_chain']) + 1, 'await.call_chain'):
                    routes.append({'call_chain': route['call_chain'],
                        'drive_occurrence': route['drive_occurrence'], 'drive': None,
                        'status': 'NOT_CHECKED'})
                    continue
                drive = drive_execution(ctx, route['drive_occurrence'].id, shared=shared)
                routes.append({**route, 'drive': drive,
                    'status': 'PARTIAL' if drive['gaps'] or shared.truncated else 'DECLARED'})
            if not admitted:
                row.update(bindings=(), matched_sources=(), status='NOT_CHECKED')
            else:
                row['status'] = ('NOT_APPLICABLE' if prepared['advance_selected'] is False
                                 or prepared['case_selected'] is False else
                                 'PARTIAL' if row['gaps'] or shared.truncated else 'DECLARED')
                checked += 1
                for binding in row['bindings']:
                    pending_copies.extend((binding['source_value'], binding['formal']))
                for route in prepared['routes']:
                    for projection in route.get('projections', ()):
                        for binding in projection['bindings']:
                            pending_copies.extend((binding['source_value'], binding['formal']))
            row['routes'] = tuple(routes)
            occurrences.append(row)
            all_gaps.extend(row['gaps'])
            if shared.truncated and cursor is None:
                cursor = {'job': number, 'occurrence': ordinal, 'phase': 'await_occurrences'}
        job.update(occurrences=tuple(occurrences), occurrence_count=len(original['occurrences']),
            status='NOT_CHECKED' if not allowed else
                   'PARTIAL' if not occurrences or any(row['status'] not in ('DECLARED', 'NOT_APPLICABLE')
                       for row in occurrences) or job.get('gaps') else 'DECLARED')
        jobs.append(job)
        if shared.truncated and cursor is None:
            cursor = {'job': number, 'phase': 'await_jobs'}
    copies, seen = [], set()
    while pending_copies:
        value = pending_copies.pop()
        if value is None or type(value) is Unresolved or value.id in seen:
            continue
        seen.add(value.id)
        recipe = ctx.body_original_copy_recipes.get(value.id)
        if recipe is None:
            continue
        if not shared.spend('await_copy_edges', path='await.copy_support'):
            if cursor is None:
                cursor = {'phase': 'await_copy_support', 'target': value.id}
            break
        from .resumable_identity import compatible
        gaps = []
        comparison = compatible(ctx, ctx.values[recipe['source']], value, gaps,
                                f'await-copy:{value.id}')
        copies.append({**recipe, 'compatibility': comparison, 'gaps': tuple(gaps)})
        all_gaps.extend(gaps)
        pending_copies.append(ctx.values[recipe['source']])
    inventory = getattr(ctx, 'await_inventory_summary', {})
    incomplete = inventory.get('known_inventory_complete') is False
    if incomplete and cursor is None:
        cursor = inventory.get('cursor')
    return deepcopy({'scope': scope, 'jobs': tuple(jobs), 'job_count': len(originals),
        'checked_job_count': checked_jobs, 'checked_occurrence_count': checked,
        'inventory': inventory, 'copy_support': tuple(copies), 'gaps': tuple(all_gaps),
        'issues': tuple(ctx.issues),
        'status': 'CONTRADICTED' if ctx.issues else
                  'PARTIAL' if incomplete or shared.truncated or not jobs or
                  any(job['status'] != 'DECLARED' for job in jobs) else 'DECLARED',
        'budget': {'limit': shared.limit, 'used': shared.used, 'truncated': shared.truncated,
                   'costs': dict(shared.costs), 'gaps': tuple(shared.gaps)},
        'cursor': cursor, 'preparation_work': {'canonical': ctx.await_preparation,
            'external': ctx.external_preparation,
            'compatibility': getattr(ctx, 'await_identity_preparation', {})}, **_flags()})


__all__ = ['prepare_await_indexes', 'await_body_links']

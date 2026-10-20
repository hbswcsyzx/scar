"""Source-first async consumers over original CFG and canonical state ports.

The inventory is independent of SessionUpdate/AsyncSessionOutcome attachments.
Paths are temporary selected original edges, not another control or state IR.
All copies use the caller's existing flow and accounting.
"""
from .lifecycle import DriveOutcomeRef, LifecyclePostBinding, SessionPost
from .model import ExitKind, StateVersionValue, TerminatorKind
from .protocols import (DriverSubject, DriveResult, HostTerminal, OutcomeAdapter,
                        OutcomeAdapterRule, OwnedUse, ProtocolClause, ProtocolProfile)
from .resumption import SuspendTerminator, SuspensionFlavor
from .structured import ControlEdgeReference


def source_inventory(ctx):
    """Prepare only original rows, including sources with no supplied consumer."""
    cached = getattr(ctx, '_async_source_inventory', None)
    if cached is not None:
        return cached
    from .protocol_rules import PROFILE_FAMILY
    result = []
    for scope in ctx.graph.protocol_scopes:
        if type(scope.subject) is not DriverSubject or scope.profile not in PROFILE_FAMILY:
            continue
        for drive in ctx.drives_by_region.get(scope.subject.interface_region, ()):
            operation = ctx.operations[drive.operation]
            for number, edge in enumerate(operation.terminator.successors):
                body = ctx.operations[edge.source]
                terminator = body.terminator
                post = (SessionPost.HOLD if type(terminator) is SuspendTerminator
                        and terminator.flavor is SuspensionFlavor.AWAIT else
                        SessionPost.COMPLETE if terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                        or type(terminator) is SuspendTerminator
                        and terminator.flavor is SuspensionFlavor.ASYNC_YIELD else None)
                outcome = DriveOutcomeRef(drive.operation, edge.source)
                result.append({'scope': scope.id, 'drive': drive,
                    'source': outcome, 'body_source': body,
                    'edge': ControlEdgeReference(operation.id, number), 'successor': edge,
                    'expected_post': post,
                    'session_required': scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1})
    cached = ctx._async_source_inventory = tuple(result)
    ctx.preparation['async_original_outcome_sources'] = len(cached)
    return cached


def _truncated(ctx):
    return ctx.budget is not None and ctx.budget.truncated


def _states(ctx, block, previous=()):
    result = dict(previous)
    result.update((ctx.values[value].location, value) for value in block.arguments
                  if isinstance(ctx.values[value], StateVersionValue))
    return result


def _indexes(ctx):
    cached = getattr(ctx, '_async_source_indexes', None)
    if cached is None:
        from .protocol_connections import AsyncSessionOutcome
        updates = {row.operation: row for row in ctx.graph.session_updates}
        bindings = {(row.scope, row.update, row.source): row for row in ctx.graph.protocol_bindings
                    if type(row) is AsyncSessionOutcome}
        cached = ctx._async_source_indexes = updates, bindings
        ctx.preparation['async_session_update_rows'] = len(updates)
        ctx.preparation['async_session_source_binding_rows'] = len(bindings)
    return cached


def source_routes(ctx, source):
    """Follow each source only to this driver invocation's first host boundary.

    The first original update on a route is retained even if its attachment is
    absent or its owner is wrong. A later drive cannot repair that omission.
    Cycles retain a boundary instead of pretending an infinite walk is empty.
    """
    cache = getattr(ctx, '_async_source_routes', None)
    if cache is None:
        cache = ctx._async_source_routes = {}
    key = source['scope'], source['source']
    if key in cache:
        return cache[key]
    updates, _ = _indexes(ctx)
    initial = source['successor'].block
    pending = [(initial, (source['edge'],), (), (), None)]
    routes, boundaries, cursor = [], [], None
    while pending:
        if not ctx.spend('async_source_blocks'):
            cursor = {'phase': 'session_source_routes', 'source': source['source'],
                      'pending_paths': len(pending)}
            break
        block_id, choices, ancestors, old_states, first = pending.pop()
        block = ctx.blocks[block_id]
        if block_id in ancestors:
            boundaries.append({'code': 'async_session_source_cycle_unresolved',
                'operation': ctx.operations[block.operations[0]], 'choices': choices})
            routes.append({'choices': choices, 'target': first, 'terminal': None,
                           'boundary': boundaries[-1]})
            continue
        ancestors = (*ancestors, block_id)
        current = _states(ctx, block, old_states)
        stopped = False
        for identity in block.operations:
            if not ctx.spend('async_source_operations'):
                cursor = {'phase': 'session_source_routes', 'source': source['source'],
                          'operation': identity, 'pending_paths': len(pending) + 1}
                stopped = True
                break
            operation = ctx.operations[identity]
            if identity in ctx.drives:
                boundary = {'code': 'async_session_next_drive_before_host',
                            'operation': operation, 'choices': choices}
                boundaries.append(boundary)
                routes.append({'choices': choices, 'target': first, 'terminal': None,
                               'boundary': boundary})
                stopped = True
                break
            if first is None and identity in updates:
                first = {'update': updates[identity], 'operation': operation,
                         'state_snapshot': tuple(current.items()), 'choices': choices}
            for value in operation.results:
                if isinstance(ctx.values[value], StateVersionValue):
                    current[ctx.values[value].location] = value
        if stopped:
            if cursor is not None:
                break
            continue
        operation = ctx.operations[block.operations[-1]]
        terminator = operation.terminator
        if terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            routes.append({'choices': choices, 'target': first,
                           'terminal': HostTerminal(operation.id), 'boundary': None})
            continue
        if type(terminator) is SuspendTerminator:
            boundary = {'code': 'async_session_host_suspend_unresolved',
                        'operation': operation, 'choices': choices}
            boundaries.append(boundary)
            routes.append({'choices': choices, 'target': first, 'terminal': None,
                           'boundary': boundary})
            continue
        # Pending port feasibility comes from the independent token/port flow,
        # never from whether this expected payload happens to match a branch.
        possible = None
        if ctx.graph.pending_completions:
            from .pending_payload_flow import has_pending_region
            if has_pending_region(ctx, ctx.region_of[operation.id]):
                from .protocol_packet_routes import _possible_pending
                possible = _possible_pending(ctx, ctx.region_of[operation.id], choices)
                if possible is None:
                    boundary = {'code': 'async_session_pending_path_unresolved',
                                'operation': operation, 'choices': choices}
                    boundaries.append(boundary)
                    routes.append({'choices': choices, 'target': first, 'terminal': None,
                                   'boundary': boundary})
                    continue
        successors = []
        for number, edge in enumerate(terminator.successors):
            if not ctx.spend('async_source_edges'):
                cursor = {'phase': 'session_source_routes', 'source': source['source'],
                          'operation': operation.id, 'edge_ordinal': number,
                          'pending_paths': len(pending) + 1}
                break
            if possible is not None and possible.edges.get((operation.id, number)) is None:
                continue
            try:
                selected = ctx.selected_edges((*choices, ControlEdgeReference(operation.id, number)))
            except ValueError:
                selected = None
            if selected is None or ctx.selection_ambiguity(selected) is not None:
                boundary = {'code': 'async_session_source_context_unresolved',
                            'operation': operation, 'choices': choices}
                boundaries.append(boundary)
                routes.append({'choices': choices, 'target': first, 'terminal': None,
                               'boundary': boundary})
                continue
            successors.append((edge.block, selected, ancestors, tuple(current.items()), first))
        pending.extend(reversed(successors))
        if cursor is not None:
            break
        if not successors and not terminator.successors:
            boundary = {'code': 'async_session_host_boundary_unresolved',
                        'operation': operation, 'choices': choices}
            boundaries.append(boundary)
            routes.append({'choices': choices, 'target': first, 'terminal': None,
                           'boundary': boundary})
    result = {'routes': tuple(routes), 'boundaries': tuple(boundaries), 'cursor': cursor,
              'known_inventory_complete': cursor is None and not boundaries,
              'conditions': ('supplied static driver paths; dynamic occurrence and native applicability unproved',)}
    if not _truncated(ctx):
        cache[key] = result
    return result


def handoff_consumers(ctx):
    """Check AWAIT exports at their actual host RETURN Uses, path by path."""
    cached = getattr(ctx, '_async_handoff_consumers', None)
    if cached is not None:
        return cached
    results, issues = [], []
    for source in source_inventory(ctx):
        body = source['body_source']
        if (type(body.terminator) is not SuspendTerminator
                or body.terminator.flavor is not SuspensionFlavor.AWAIT):
            continue
        route_view = source_routes(ctx, source)
        consumers, gaps = [], []
        for route in route_view['routes']:
            terminal = route['terminal']
            if terminal is None or ctx.operations[terminal.operation].terminator.kind is not TerminatorKind.RETURN:
                continue
            for actual in ctx.terminal_uses(terminal):
                if not ctx.spend('async_handoff_consumers'):
                    break
                expected = DriveResult(source['source'], 0)
                match = ctx.forwards(expected, actual, guard=route['choices'])
                receipt = {'source': expected, 'actual': actual, 'choices': route['choices'],
                           'match': match, 'terminal': terminal}
                consumers.append(receipt)
                if match is False:
                    issues.append(('protocol_copy', str(terminal.operation),
                                   'host await handoff is not this exact AWAIT export'))
                elif match is None:
                    gaps.append({'code': 'async_await_handoff_unresolved', 'operation': terminal.operation})
        gaps.extend(route_view['boundaries'])
        if _truncated(ctx):
            gaps.append({'code': 'protocol_budget_exhausted', 'source': source['source']})
        cursor = route_view['cursor']
        if _truncated(ctx) and cursor is None:
            cursor = {'phase': 'await_handoff_consumers', 'source': source['source'],
                      'consumer_ordinal': len(consumers)}
        results.append({**source, 'consumers': tuple(consumers), 'gaps': tuple(gaps),
            'cursor': cursor,
            'known_inventory_complete': route_view['known_inventory_complete'] and not _truncated(ctx),
            'status': 'CONTRADICTED' if any(row['match'] is False for row in consumers) else
                      'PARTIAL' if gaps else 'DECLARED',
            'source_runtime_verified': False, 'transformation_authorized': False})
    result = {'handoffs': tuple(results), 'issues': tuple(issues)}
    if not _truncated(ctx):
        ctx._async_handoff_consumers = result
    return result


def session_consumers(analysis, scopes):
    """Associate the first post with each independent original async outcome."""
    ctx = analysis.ctx
    _, bindings = _indexes(ctx)
    enabled = {scope.id: scope for scope in scopes}
    result = []
    for source in source_inventory(ctx):
        if source['scope'] not in enabled:
            continue
        scope = enabled[source['scope']]
        path = f"async.session_source.{source['source'].drive}.{source['source'].source}"
        expected_post = source['expected_post']
        view = source_routes(ctx, source)
        targets, gaps = [], []
        missing = False
        for route in view['routes']:
            first = route['target']
            if first is None:
                if route['terminal'] is not None or route['boundary'] is not None and route['boundary']['code'] == 'async_session_next_drive_before_host':
                    missing = True
                    gaps.append(analysis.gap('async_session_update_missing', path,
                                            source=source['source'], route=route))
                continue
            if not analysis.spend('source_targets', path):
                break
            update = first['update']
            operation = first['operation']
            choices = route['choices']
            declaration = bindings.get((scope.id, update.operation, source['source']))
            if declaration is None:
                missing = True
                gaps.append(analysis.gap('async_session_outcome_missing', path,
                    source=source['source'], update=update))
            interface = ctx.interfaces[scope.subject.interface_region]
            actual_request = OwnedUse(update.operation, update.request)
            actual_body = OwnedUse(update.operation, update.body)
            request_source = analysis.formal(interface.region, interface.receiver)
            jobs = [('request', request_source, actual_request),
                    ('drive_request', request_source, OwnedUse(source['drive'].operation, source['drive'].session)),
                    ('body', OwnedUse(source['drive'].operation, source['drive'].instance), actual_body)]
            checks, state_support = {}, []
            for role, expected, actual in jobs:
                report = ctx.bind(expected, actual, choices=choices, path=path)
                checks[role] = analysis.check(report, 'async_session_' + role, path)
            actual_states = analysis.actual_states(operation)
            snapshots = dict(first['state_snapshot'])
            for location in interface.lifecycle:
                if not analysis.spend('source_states', path):
                    break
                actual = actual_states.get(location)
                value = snapshots.get(location)
                report = (ctx.bind(ctx.values[value].origin, actual, choices=choices, path=path)
                    if actual is not None and value is not None else
                    {'match': None, 'routes': (), 'gaps': ('async_session_current_state_unavailable',), 'cursor': None})
                analysis.check(report, 'async_session_state', path)
                state_support.append({'location': location, 'expected': value,
                                      'actual': actual, 'binding': report})
            reports = (*checks.values(), *(row['binding'] for row in state_support))
            joint = ctx.correlate(*reports)
            analysis.check(joint, 'async_session_tuple', path)
            if expected_post is not None and update.post is not expected_post:
                analysis.issue('async_session_post', path,
                               'first session post differs from this exact async outcome')
            selected = None
            if update.binding is LifecyclePostBinding.NORMAL_COMPLETION:
                selected = next((ControlEdgeReference(operation.id, number)
                    for number, edge in enumerate(operation.terminator.successors)
                    if edge.kind is ExitKind.NORMAL), None)
            target_gaps = (() if joint['match'] is True else ('async_session_tuple_unresolved',))
            gaps.extend({'code': code, 'path': path, 'update': update} for code in target_gaps)
            targets.append({'update': update, 'binding': declaration, 'operation': operation,
                'selected_edge': selected, 'choices': choices, 'request': checks['request'],
                'drive_request': checks['drive_request'], 'body': checks['body'],
                'state_support': tuple(state_support), 'source': source['source'],
                'source_binding': joint, 'terminal': route['terminal'],
                'post_applied': selected is None or selected in choices,
                'gaps': target_gaps,
                'status': 'CONTRADICTED' if joint['match'] is False or expected_post is not None
                          and update.post is not expected_post else
                          'MISSING' if declaration is None else
                          'PARTIAL' if joint['match'] is None or _truncated(ctx) else 'DECLARED'})
        for boundary in view['boundaries']:
            gaps.append(analysis.gap(boundary['code'], path, **{
                key: value for key, value in boundary.items() if key != 'code'}))
        if expected_post is None:
            gaps.append(analysis.gap('async_session_source_classification_unproved', path,
                                    source=source['source']))
        cursor = view['cursor']
        if _truncated(ctx):
            cursor = cursor or {'phase': 'session_source_consumers', 'source': source['source'],
                                'target_ordinal': len(targets)}
        complete = view['known_inventory_complete'] and cursor is None
        status = ('CONTRADICTED' if any(row['status'] == 'CONTRADICTED' for row in targets) else
                  'NOT_CHECKED' if cursor is not None and not targets else
                  'MISSING' if missing or complete and not targets else
                  'PARTIAL' if cursor is not None or not complete
                  or gaps or any(row['status'] != 'DECLARED' for row in targets) else 'DECLARED')
        row = {**source, 'targets': tuple(targets), 'target_count': len(targets),
            'status': status, 'gaps': tuple(gaps), 'cursor': cursor,
            'known_inventory_complete': complete,
            'source_inventory_complete': False,
            'conditions': ('session update source/native applicability and dynamic occurrence unproved',),
            'source_runtime_verified': False, 'transformation_authorized': False}
        result.append(row)
        analysis.obligations.append({'scope': scope.id, 'clause': ProtocolClause.ASYNC_ITEM_ADAPTER,
            'operation': source['drive'].operation, 'source': source['source'],
            'session_consumer': row, 'status': status})
        if cursor is not None and analysis.cursor is None:
            analysis.cursor = cursor
    return tuple(result)


__all__ = ['source_inventory', 'source_routes', 'handoff_consumers', 'session_consumers']

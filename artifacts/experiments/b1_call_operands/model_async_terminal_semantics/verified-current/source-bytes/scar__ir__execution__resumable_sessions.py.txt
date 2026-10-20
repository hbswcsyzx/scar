"""Async result consumers projected onto original occurrence routes.

These views add no execution, state, protocol or identity declarations.  Static
source obligations survive absent update rows/capture; an actual selected CFG
path, rather than a same-site candidate, determines this invocation's targets.
"""
from scar.ir.program.drivers import DriverReceiverKind
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.lifecycle import DriveOutcomeRef, LifecyclePostBinding, SessionPost
from scar.ir.program.model import (CompletionResult, ExitKind, InvokeLiteralResult,
                                   OperationResult, StateVersionValue, TerminatorKind)
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.protocols import (DriverSubject, DriveResult, OutcomeAdapter,
                                       OutcomeAdapterRule, ProtocolProfile)
from scar.ir.program.resumption import SuspendTerminator, SuspensionFlavor

from .common import Unresolved
from .coordinates import InitialEntry
from .resumable_flow import gap, value_for_use


def _pair(source, target):
    return {'source_value': source, 'target_value': target, 'compatibility': None}


def _use(ctx, occurrence, identity):
    return None if occurrence is None else ctx.uses.get((occurrence.id, identity))


def _path(ctx, drive, gaps):
    """Actual suffix of one segment, preserving missing original operations."""
    transfer = ctx.outgoing.get(drive.id)
    if transfer is None:
        gap(ctx, gaps, 'body_session_transfer_missing', drive.id,
            'no actual selected Drive successor locates the consumer suffix')
        return ()
    segment = ctx.visits[drive.visit].segment
    pending, seen, result = transfer.target, set(), []
    while pending not in seen:
        seen.add(pending)
        visit = ctx.visits[pending]
        if visit.segment != segment:
            ctx.issue('body_session_segment', drive.id, 'session consumer leaves this driver segment')
            break
        block = ctx.blocks[visit.block]
        for identity in block.operations:
            if identity in ctx.body_drives:
                gap(ctx, gaps, 'body_session_next_drive', drive.id,
                    'another Drive bounds the earlier result consumer suffix')
                return tuple(result)
            occurrence = ctx.session_occurrences_by_visit_site.get((visit.id, identity))
            result.append((ctx.core_operations[identity], occurrence, visit))
        terminal = result[-1][1]
        operation = ctx.core_operations[block.operations[-1]]
        if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            return tuple(result)
        next_edge = None if terminal is None else ctx.outgoing.get(terminal.id)
        if next_edge is None:
            gap(ctx, gaps, 'body_session_suffix_missing', drive.id,
                'captured suffix ends before a host completion')
            return tuple(result)
        pending = next_edge.target
    gap(ctx, gaps, 'body_session_suffix_cycle', drive.id,
        'actual suffix revisits one BlockVisit rather than naming a new occurrence')
    return tuple(result)


def _result(ctx, occurrence, port):
    if occurrence is None:
        return None
    if type(port) is OperationResult:
        operation = ctx.core_operations[occurrence.operation]
        return ctx.results.get((occurrence.id, operation.results[port.index]))
    if type(port) is InvokeLiteralResult:
        transfer = ctx.outgoing.get(occurrence.id)
        if transfer is None or transfer.successor_index != port.edge.successor_index:
            return None
        edge = ctx.core_operations[occurrence.operation].terminator.successors[transfer.successor_index]
        visit = ctx.visits[transfer.target]
        for actual, formal in zip(edge.arguments, ctx.blocks[visit.block].arguments):
            if type(actual) is CompletionResult and actual.index == port.result.index:
                return ctx.results.get((visit.id, formal))
    return None


def _post_failure(ctx, path):
    """The latest actual INVOKE RAISE owns its packet, even without metadata."""
    selected = None
    for helper, occurrence, _ in path:
        transfer = None if occurrence is None else ctx.outgoing.get(occurrence.id)
        if (transfer is None or helper.terminator is None
                or helper.terminator.kind is not TerminatorKind.INVOKE):
            continue
        edge = helper.terminator.successors[transfer.successor_index]
        if edge.kind is not ExitKind.RAISE:
            continue
        signature = next(row for row in helper.completions if row.kind is ExitKind.RAISE)
        packet_slot = next((index for index, value_type in enumerate(signature.types)
                           if getattr(value_type, 'protocol', None)
                           is ProtocolValueKind.EXCEPTION_PACKET), None)
        landing = ctx.visits[transfer.target]
        packet = None
        for actual, formal in zip(edge.arguments, ctx.blocks[landing.block].arguments):
            if type(actual) is CompletionResult and actual.index == packet_slot:
                packet = ctx.results.get((landing.id, formal))
        selected = (occurrence, packet)
    return selected


def _hosts(ctx, view, source, path, gaps):
    outcome = view['outcome']
    if outcome is None:
        return ()
    body = ctx.core_operations[outcome.operation]
    suspended = type(body.terminator) is SuspendTerminator
    terminal_return = not suspended and body.terminator.kind is TerminatorKind.RETURN
    terminal_raise = not suspended and body.terminator.kind is TerminatorKind.RAISE
    if not suspended and not terminal_return and not terminal_raise:
        gap(ctx, gaps, 'body_session_host_adapter_unproved', outcome.id,
            'terminal body outcome host adaptation is not yet projected by this bounded view')
        return ()
    flavor = body.terminator.flavor if suspended else None
    payload = (body.terminator.exported if suspended else next((identity
        for identity in body.terminator.values
        if not isinstance(ctx.core_values[next(use.value for use in body.uses
            if use.id == identity)], StateVersionValue)), None))
    exported = value_for_use(ctx, _use(ctx, outcome, payload))
    # A compiled body may already contain its complete exception conversion.
    # Its actual final RAISE packet then propagates unchanged. A declared
    # driver adapter, even when uncaptured, remains a separate obligation.
    declared_adapter = any(type(declaration.contract.input) is DriveResult
        and declaration.contract.input.outcome == source
        for operation, _, _ in path
        for declaration in ctx.session_adapters_by_site.get(operation.id, ()))
    post_failure = _post_failure(ctx, path)
    hosts = []
    for operation, occurrence, visit in path:
        if operation.terminator is None or operation.terminator.kind not in (
                TerminatorKind.RETURN, TerminatorKind.RAISE):
            continue
        payload = next((identity for identity in operation.terminator.values
                        if not isinstance(ctx.core_values[next(use.value for use in operation.uses
                            if use.id == identity)], StateVersionValue)), None)
        target = value_for_use(ctx, _use(ctx, occurrence, payload))
        row = {'operation': occurrence, 'definition': operation,
               'source_value': exported, 'target_value': target,
               'compatibility': None, 'adapter': None, 'bindings': ()}
        if occurrence is None:
            gap(ctx, gaps, 'body_session_host_missing', operation.id,
                'original host consumer has no captured occurrence on this actual visit')
        if operation.terminator.kind is TerminatorKind.RAISE and post_failure is not None:
            # A later helper may replace even a terminal body's exception.
            # Use its actual selected completion slot, never the earlier packet.
            row['kind'] = 'HOST_FAILURE'
            row['source_value'] = post_failure[1]
            row['bindings'] = (_pair(post_failure[1], target),)
        elif terminal_raise and not declared_adapter:
            if operation.terminator.kind is TerminatorKind.RAISE:
                row['kind'] = 'BODY_EXCEPTION_PROPAGATION'
                row['bindings'] = (_pair(exported, target),)
            else:
                gap(ctx, gaps, 'body_session_exception_host_unproved', operation.id,
                    'a terminal body exception has no original conversion to this normal host completion')
        elif flavor is SuspensionFlavor.AWAIT and operation.terminator.kind is TerminatorKind.RETURN:
            row['bindings'] = (_pair(exported, target),)
        elif flavor is SuspensionFlavor.AWAIT:
            row['source_value'] = None
            row['kind'] = 'HOST_FAILURE'
            gap(ctx, gaps, 'body_session_host_failure_unproved', operation.id,
                'non-handoff host failure has no captured selected helper packet source')
        else:
            # Item-to-StopIteration is a value-changing adapter, not a copy of
            # a ReferenceValue into an exception packet. Check its real input
            # and packet component separately; native implementation is unproved.
            selected = []
            for adapter_op, adapter_occ, _ in path:
                if adapter_occ is None:
                    continue
                transfer = ctx.outgoing.get(adapter_occ.id)
                for declaration in ctx.session_adapters_by_site.get(adapter_op.id, ()):
                    contract = declaration.contract
                    if terminal_return and (contract.rule is not
                            OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION
                            or type(contract.input) is not DriveResult or contract.input.index != 0):
                        continue
                    if (type(contract.input) is DriveResult and contract.input.outcome == source
                            and (transfer is None and declaration.slot == 0 or transfer is not None
                                 and transfer.successor_index == declaration.slot)):
                        selected.append((declaration, adapter_occ))
            if len(selected) == 1:
                declaration, adapter_occ = selected[0]
                contract = declaration.contract
                actual = value_for_use(ctx, _use(ctx, adapter_occ, contract.input_use))
                produced = _result(ctx, adapter_occ, contract.output)
                bindings = [_pair(exported, actual)]
                row['adapter'] = {'declaration': declaration, 'occurrence': adapter_occ,
                                  'input': actual, 'output': produced}
                # Original packet definition locates the exception component;
                # no association is inferred from equal types or operation names.
                component = None
                for packet_op, packet_occ, _ in path:
                    for packet in ctx.session_packets_by_site.get(packet_op.id, ()):
                        packet_value = ctx.results.get((packet_occ.id, packet.value)) if packet_occ else None
                        if target is not None and packet_value is not None and target.id == packet_value.id:
                            component = value_for_use(ctx, _use(ctx, packet_occ, packet.exception))
                if component is not None:
                    bindings.append(_pair(produced, component))
                elif produced is not None and target is not None:
                    if type(ctx.core_values[produced.value]) is type(ctx.core_values[target.value]):
                        bindings.append(_pair(produced, target))
                    else:
                        gap(ctx, gaps, 'body_session_packet_route_unproved', operation.id,
                            'adapter result to this actual host packet lacks a captured component route')
                else:
                    gap(ctx, gaps, 'body_session_adapter_result_missing', operation.id,
                        'selected original adapter result is not captured')
                row['bindings'] = tuple(bindings)
            else:
                gap(ctx, gaps, 'body_session_adapter_missing', operation.id,
                    'actual item host path lacks one exact selected original adapter')
        hosts.append(row)
    if not hosts:
        gap(ctx, gaps, 'body_session_host_missing', view['drive'].id,
            'no captured/original host completion is reached by this actual suffix')
    return tuple(hosts)


def prepare_body_sessions(ctx):
    ctx.resolved_body_sessions = {}
    interfaces = {row.region: row for row in ctx.program.driver_interfaces}
    ctx.session_occurrences_by_visit_site = {(row.visit, row.operation): row for row in ctx.occurrences.values()}
    updates = {row.operation: row for row in ctx.program.session_updates}
    ctx.session_updates_by_site = updates
    bindings = {(row.scope, row.update, row.source): row for row in ctx.program.protocol_bindings
                if type(row) is AsyncSessionOutcome}
    scopes_by_region = {}
    for scope in ctx.program.protocol_scopes:
        if type(scope.subject) is DriverSubject and scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1:
            scopes_by_region.setdefault(scope.subject.interface_region, []).append(scope)
    ctx.session_adapters_by_site, ctx.session_packets_by_site = {}, {}
    for row in ctx.program.protocol_operations:
        if type(row.contract) is OutcomeAdapter:
            ctx.session_adapters_by_site.setdefault(row.operation, []).append(row)
    for row in ctx.program.exception_packets:
        origin = ctx.core_values[row.value].origin
        if type(origin) is OperationResult:
            ctx.session_packets_by_site.setdefault(origin.operation, []).append(row)
    calls = {row['activation'].id: row for row in ctx.resolved_call_activations.values()}
    entries_by_activation = {}
    for visit in ctx.visits.values():
        segment = ctx.segments[visit.segment]
        if (type(segment.ingress) is InitialEntry and visit.id not in ctx.incoming
                and visit.block == ctx.regions[ctx.activations[segment.activation].region].entry):
            entries_by_activation.setdefault(segment.activation, []).append(visit)
    close_failures = {row.contract.input.outcome for row in ctx.program.protocol_operations
        if type(row.contract) is OutcomeAdapter and type(row.contract.input) is DriveResult
        and row.contract.rule is OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR}
    for identity, view in ctx.resolved_body_drives.items():
        activation = ctx.activation_of(identity)
        interface = interfaces.get(ctx.activations[activation].region)
        if interface is None or interface.receiver_kind is not DriverReceiverKind.ASYNC_REQUEST:
            continue
        gaps = []
        caller = calls.get(activation)
        entry = None if caller is None else caller['entry']
        if entry is None:
            # An entry is structural only when its segment ingress actually
            # declares it; never choose the sole visible repeated static site.
            entries = entries_by_activation.get(activation, ())
            entry = entries[0] if len(entries) == 1 else None
        request = None if entry is None else ctx.results.get((entry.id, interface.receiver))
        request_use = _use(ctx, view['drive'], view['declaration'].session)
        drive_request = value_for_use(ctx, request_use)
        scopes = tuple(scopes_by_region.get(interface.region, ()))
        body_use = _use(ctx, view['drive'], view['declaration'].instance)
        body_value = value_for_use(ctx, body_use)
        source = None if view['outcome'] is None else DriveOutcomeRef(view['drive'].operation, view['outcome'].operation)
        expected = None
        if source is not None:
            terminal = ctx.core_operations[source.source].terminator
            expected = (SessionPost.HOLD if type(terminal) is SuspendTerminator
                        and terminal.flavor is SuspensionFlavor.AWAIT else SessionPost.COMPLETE
                        if terminal.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                        or type(terminal) is SuspendTerminator and terminal.flavor is SuspensionFlavor.ASYNC_YIELD
                        else None)
            if source in close_failures:
                expected = None
            if expected is None:
                gap(ctx, gaps, 'body_session_source_classification_unproved', identity,
                    'this original outcome has no supported automatic session-post classification')
        else:
            gap(ctx, gaps, 'body_session_source_missing', identity,
                'actual body outcome is missing; static alternatives remain obligations')
        path = _path(ctx, view['drive'], gaps)
        targets = []
        for operation, occurrence, visit in path:
            update = updates.get(operation.id)
            if update is None:
                continue
            source_bindings = tuple({'scope': scope, 'source': source,
                'binding': bindings.get((scope.id, operation.id, source))} for scope in scopes)
            binding = source_bindings[0]['binding'] if len(source_bindings) == 1 else None
            request_value = value_for_use(ctx, _use(ctx, occurrence, update.request))
            target_body = value_for_use(ctx, _use(ctx, occurrence, update.body))
            transfer = None if occurrence is None else ctx.outgoing.get(occurrence.id)
            selected = None if transfer is None else operation.terminator.successors[transfer.successor_index]
            established = occurrence is not None and (update.binding is LifecyclePostBinding.AFTER_OPERATION
                or selected is not None and selected.kind is ExitKind.NORMAL)
            if occurrence is None:
                gap(ctx, gaps, 'body_session_update_occurrence_missing', operation.id,
                    'original update on the actual suffix has no captured occurrence')
            if not source_bindings or any(row['binding'] is None for row in source_bindings):
                gap(ctx, gaps, 'body_session_source_binding_missing', operation.id,
                    'original update has no attachment to this exact body result')
            if expected is not None and update.post is not expected:
                ctx.issue('body_session_post', identity, 'update post contradicts this actual source')
            before = {} if occurrence is None else ctx.before.get(occurrence.id, {})
            after = ({} if occurrence is None else ctx.after.get(occurrence.id, {}))
            if transfer is not None:
                after = ctx.edges.get((occurrence.id, transfer.successor_index), {})
            input_sites = (tuple(access.before for access in operation.accesses)
                if update.binding is LifecyclePostBinding.AFTER_OPERATION else operation.invoke_arguments)
            state_bindings = []
            for use in operation.uses:
                definition = ctx.core_values[use.value]
                if use.id not in input_sites or not isinstance(definition, StateVersionValue):
                    continue
                actual_use = _use(ctx, occurrence, use.id)
                actual_value = value_for_use(ctx, actual_use)
                state_bindings.append({'definition': use, 'use': actual_use,
                    'value': actual_value, 'location': definition.location,
                    'current': before.get(definition.location)})
                if actual_use is None or actual_value is None or type(actual_value) is Unresolved:
                    established = False
                    gap(ctx, gaps, 'body_session_input_state_missing', operation.id,
                        'original update state UseOccurrence is missing or unresolved')
            if any(before.get(location) is None for location in interface.lifecycle):
                gap(ctx, gaps, 'body_session_input_state_missing', operation.id,
                    'original update current-state inputs are not all captured')
            if established and any(after.get(location) is None for location in interface.lifecycle):
                established = False
                gap(ctx, gaps, 'body_session_output_state_missing', operation.id,
                    'declared post lacks captured current-state support')
            targets.append({'update': update, 'occurrence': occurrence, 'binding': binding,
                'source_bindings': source_bindings,
                'request': _pair(request, request_value), 'body': _pair(body_value, target_body),
                'state_inputs': dict(before), 'state_outputs': dict(after),
                'state_bindings': tuple(state_bindings),
                'selected_successor': transfer, 'post_established': established,
                'post_scope': 'conditional original update point; no survival across later calls is implied'})
            break  # The first post consumes this source; a later post cannot repair it.
        if not targets:
            gap(ctx, gaps, 'body_session_update_missing', identity,
                'original body result still requires a post consumer although no update is supplied')
        if request is None:
            gap(ctx, gaps, 'body_session_request_missing', identity,
                'this driver entry request value is not captured')
        hosts = _hosts(ctx, view, source, path, gaps)
        ctx.resolved_body_sessions[identity] = {'drive': view['drive'], 'source': source,
            'source_candidates': tuple(view['outcome_candidates']), 'expected_post': expected,
            'request': {'use': request_use, 'value': request},
            'request_binding': _pair(request, drive_request),
            'body': {'use': body_use, 'value': body_value}, 'scopes': scopes,
            'targets': tuple(targets), 'hosts': hosts, 'caller': caller,
            'expected_consumer_count': max(1, len(scopes)), 'target_count': len(targets), 'host_count': len(hosts),
            'canonical_gaps': tuple(gaps), 'gaps': tuple(gaps), 'cursor': None}
    ctx.body_preparation['async_session_sources'] = len(ctx.resolved_body_sessions)
    ctx.body_preparation['async_occurrence_index'] = len(ctx.session_occurrences_by_visit_site)


def session_endpoints(view):
    yield view['request_binding']['source_value']
    yield view['request_binding']['target_value']
    for row in view['targets']:
        for role in ('request', 'body'):
            for endpoint in ('source_value', 'target_value'):
                yield row[role][endpoint]
    for row in view['hosts']:
        for binding in row['bindings']:
            yield binding['source_value']
            yield binding['target_value']


def body_session_identity_errors(ctx):
    from .resumable_identity import compatible
    comparisons = 0

    def check(binding, gaps, path):
        nonlocal comparisons
        source, target = binding['source_value'], binding['target_value']
        binding['compatibility'] = compatible(ctx, source, target, gaps, path)
        comparisons += 1
        source_root = (None if source is None or type(source) is Unresolved
                       else ctx.body_value_roots.get(source.id))
        target_root = (None if target is None or type(target) is Unresolved
                       else ctx.body_value_roots.get(target.id))
        binding['copy_status'] = ('DECLARED_ORIGINAL_COPY' if source_root is not None
                                  and source_root == target_root else 'UNPROVED')
        if binding['copy_status'] == 'UNPROVED':
            gap(ctx, gaps, 'body_session_copy_unproved', path,
                'these endpoints lack one original captured CFG/CALL/body copy source')

    for identity, view in getattr(ctx, 'resolved_body_sessions', {}).items():
        gaps = list(view['canonical_gaps'])
        binding = view['request_binding']
        check(binding, gaps, f'{identity}:session-drive-request')
        for ordinal, row in enumerate(view['targets']):
            for role in ('request', 'body'):
                binding = row[role]
                check(binding, gaps, f'{identity}:session[{ordinal}]:{role}')
        for ordinal, host in enumerate(view['hosts']):
            for part, binding in enumerate(host['bindings']):
                check(binding, gaps, f'{identity}:host[{ordinal}]:{part}')
            host['compatibility'] = tuple(binding['compatibility'] for binding in host['bindings'])
        view['gaps'] = tuple(gaps)
    return comparisons


def session_view(ctx, identity, shared):
    source = getattr(ctx, 'resolved_body_sessions', {}).get(identity)
    if source is None:
        return None
    # The public body query detaches once at its final boundary. Copy only the
    # containers changed by budget masking here, without copying the model twice.
    result = {**source,
        'request_binding': dict(source['request_binding']),
        'targets': tuple({**row, 'request': dict(row['request']), 'body': dict(row['body'])}
                         for row in source['targets']),
        'hosts': tuple({**row, 'bindings': tuple(dict(item) for item in row['bindings'])}
                       for row in source['hosts'])}
    cursor = None
    if not shared.spend('body_session_request', path='body.session.request'):
        result['request_binding']['compatibility'] = None
        result['request_binding']['copy_status'] = None
        cursor = {'field': 'request', 'ordinal': 0, 'drive': identity}
    for field in ('targets', 'hosts'):
        for ordinal, row in enumerate(result[field]):
            checked = shared.spend('body_session_consumers', path=f'body.session.{field}[{ordinal}]')
            row['check_status'] = 'DECLARED' if checked else 'NOT_CHECKED'
            if not checked:
                cursor = cursor or {'field': field, 'ordinal': ordinal, 'drive': identity}
                if field == 'targets':
                    for role in ('request', 'body'):
                        row[role]['compatibility'] = None
                        row[role]['copy_status'] = None
                    row['post_established'] = False
                else:
                    row['compatibility'] = None
                    for binding in row['bindings']:
                        binding['compatibility'] = None
                        binding['copy_status'] = None
    if not result['targets'] and not shared.spend('body_session_missing_consumer', path='body.session.source'):
        cursor = cursor or {'field': 'source', 'ordinal': 0, 'drive': identity}
    result['cursor'] = cursor
    result['status'] = ('MISSING' if not result['targets'] else 'PARTIAL'
                        if result['gaps'] or cursor is not None else 'DECLARED')
    result.update(source_runtime_verified=False, runtime_identity_verified=False,
                  value_identity_verified=False, transformation_authorized=False)
    return result

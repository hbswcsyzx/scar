"""Source-first await obligations left joined to exact captured continuations.

Static definitions remain separate from occurrence evidence. Missing captures
do not remove obligations; declared associations do not authorize rewriting.
"""
from scar.ir.program.model import ExitKind, InvokeLiteralResult, TerminatorKind
from scar.ir.program.protocols import DriveResult, HostTerminal, OwnedUse

from .await_outcome_evidence import (append_gaps, choice, locate, pair, port_value,
                                    selected_choices, states, status, target)
from .resumable_flow import value_for_use


def _finish(row, *, selected=True, children=(), bindings=(), definition=None):
    local = list(row.get('gaps', ()))
    append_gaps(local, children)
    append_gaps(local, bindings)
    row.update(selected=selected, gaps=tuple(local), status=status(selected,
        gaps=local, children=children, bindings=bindings, definition=definition))
    return row


def _payload(ctx, outcome, ordinal=0):
    if outcome is None:
        return None
    term = ctx.core_operations[outcome.operation].terminator
    uses = (term.exported,) if term.kind is TerminatorKind.SUSPEND else term.values
    use = None if ordinal >= len(uses) else ctx.uses.get((outcome.id, uses[ordinal]))
    return value_for_use(ctx, use)


def _map(*occurrences):
    return {row.operation: row for row in occurrences if row is not None}


def _base_gaps(definition, children):
    """Keep direct static gaps; aggregate child gaps belong to chosen legs."""
    inherited = tuple(gap for child in children for gap in child.get('gaps', ()))
    return [gap for gap in definition.get('gaps', ()) if gap not in inherited]


def _final_legs(ctx, definitions, operation, shared):
    from .await_links import _result
    rows = []
    for definition in definitions:
        admitted = shared.spend('await_outcome_final_legs', path='await.outcome.final')
        selected = (None if operation is None or not admitted else
            True if definition['edge'] is None else choice(ctx, operation, definition['edge']))
        own = _result(ctx, operation, definition['own_result']) if selected is True else None
        targets, state_rows, local = (), (), list(definition.get('gaps', ()))
        if selected is True:
            targets = tuple(target(ctx, actual, operation, own, shared) for actual in definition['targets'])
            known = _map(operation, *(row['operation'] for row in targets))
            state_rows = states(ctx, definition['states'], known, shared)
            if own is None:
                local.append('await_final_own_result_unobserved')
        elif selected is None:
            local.append('await_final_choice_unobserved')
        rows.append(_finish({'definition': definition, 'own_value': own,
            'targets': targets, 'states': state_rows, 'gaps': tuple(local)}, selected=selected,
            children=(*targets, *state_rows), definition=definition))
    return tuple(rows)


def _consumer(ctx, definition, advance, known, anchors, shared, *, parent_port=None):
    from .await_links import _result, _use
    admitted = shared.spend('await_outcome_consumers', path='await.outcome.consumer')
    selected = selected_choices(ctx, definition.get('choices', ()), known, anchors, shared) if admitted else None
    actual = definition['actual']
    operation, reached = locate(ctx, advance, actual.operation, shared) if admitted else (None, None)
    if selected is not False and reached is False:
        selected = False
    own = _result(ctx, advance, definition.get('advance_result', parent_port))
    local = _base_gaps(definition, definition.get('legs', ()))
    use, final, bindings = None, (), ()
    if type(actual) is HostTerminal:
        projected = target(ctx, actual, advance, own, shared)
        use, binding = projected['use'], projected['binding']
        targets = (projected,)
    else:
        use = _use(ctx, operation, actual)
        binding = pair(ctx, own, value_for_use(ctx, use), shared)
        targets = ()
    if selected is not False:
        if operation is None:
            local.append('await_outcome_consumer_occurrence_missing')
        if use is None:
            local.append('await_outcome_consumer_use_missing')
        bindings = (binding,)
        final = _final_legs(ctx, definition.get('legs', ()), operation, shared)
    from .region_implementation import region_implementation
    implementation = region_implementation(ctx, definition.get('implementation'),
        operation, own, shared) if selected is not False else None
    return _finish({'definition': definition, 'operation': operation, 'use': use,
        'advance_value': own, 'binding': binding, 'legs': final, 'targets': targets,
        'implementation': implementation,
        'gaps': tuple(local)}, selected=selected, children=(*final, *targets),
        bindings=(*bindings, definition.get('binding', {})))


def _terminal(ctx, definition, anchor, advance, parent_port, known, shared,
              *, own=False, exact_completion=None, state_definitions=None,
              completion_required=False):
    from .await_links import _result, _use
    operation, reached = locate(ctx, anchor, definition['terminal'].operation, shared)
    local = list(definition.get('gaps', ()))
    if completion_required and exact_completion is None:
        local.append('await_failure_call_completion_unobserved')
    if exact_completion is not None and operation is not None and operation.id != exact_completion.id:
        local.append('await_outcome_call_completion_mismatch')
        ctx.issue('await_outcome_call_completion', operation.id,
            'terminal is not this exact source CallActivation completion')
    packet_use = _use(ctx, operation, definition.get('packet'))
    packet = value_for_use(ctx, packet_use)
    parent = _result(ctx, advance, parent_port)
    binding = pair(ctx, parent if own else packet, packet if own else parent, shared)
    if operation is None:
        local.append('await_outcome_terminal_unobserved')
    if packet_use is None:
        local.append('await_outcome_terminal_packet_unobserved')
    occurrences = {**known, **_map(anchor if hasattr(anchor, 'operation') else None, advance, operation)}
    current_value, current_binding = None, None
    if 'current_source' in definition:
        declared_source = definition['current_source']
        source_site = (declared_source.edge.operation if hasattr(declared_source, 'edge') else
                       declared_source.outcome.drive if type(declared_source) is DriveResult else
                       getattr(declared_source, 'operation', None))
        current_operation, _ = (locate(ctx, anchor, source_site, shared)
                                if source_site is not None else (None, None))
        from .await_outcome_evidence import port_value
        occurrences.update(_map(current_operation))
        current_value = port_value(ctx, declared_source, occurrences, shared)
        current_binding = pair(ctx, current_value, packet, shared)
        own_choice = selected_choices(ctx, definition.get('choices', ()), occurrences,
            (advance, anchor, operation), shared)
        reached = (False if reached is False or own_choice is False else
                   True if reached is True and own_choice is True else None)
    delivery_binding = binding
    if current_binding is not None:
        matches = binding['match'], current_binding['match']
        binding = {**binding, 'match': False if False in matches else None if None in matches else True,
            'current_binding': current_binding, 'delivery_binding': delivery_binding,
            'gaps': tuple(dict.fromkeys((*binding['gaps'], *current_binding['gaps'])))}
    state_rows = states(ctx, definition.get('states', ()) if state_definitions is None
                        else state_definitions, occurrences, shared)
    consumers = tuple(_consumer(ctx, receiver, advance, occurrences, (advance, operation), shared,
                               parent_port=parent_port) for receiver in definition.get('consumers', ()))
    if 'current_source' in definition and shared.truncated:
        local.append('await_completion_terminal_budget')
    return _finish({'definition': definition, 'operation': operation,
        'packet_use': packet_use, 'packet_value': packet, 'parent_value': parent,
        'binding': binding, 'current_value': current_value, 'current_binding': current_binding,
        'delivery_binding': delivery_binding,
        'states': state_rows, 'consumers': consumers, 'gaps': tuple(local)},
        selected=reached, children=(*state_rows, *consumers),
        bindings=(binding,) if current_binding is None else (binding, current_binding), definition=definition)


def _conversion(ctx, definition, advance, drive, body, shared, *, consumer_definitions=(), call_chain=()):
    from .await_links import _result, _use
    admitted = shared.spend('await_outcome_conversion_legs', path='await.outcome.conversion')
    operation, reached = locate(ctx, drive, definition['operation'], shared) if admitted else (None, None)
    selected = (False if reached is False else None if operation is None else
                True if definition['edge'] is None else choice(ctx, operation, definition['edge']))
    own = _result(ctx, operation, definition['own_result']) if selected is True else None
    packets, terminals, state_rows = [], [], ()
    local = _base_gaps(definition, consumer_definitions)
    input_value, input_binding = None, None
    if selected is True:
        rows = definition['rows']
        original_use = rows[0].contract.input_use if rows else None
        input_use = None if original_use is None else _use(ctx, operation, OwnedUse(operation.operation, original_use))
        input_value = value_for_use(ctx, input_use)
        input_binding = pair(ctx, _payload(ctx, body), input_value, shared)
        for packet in definition['packets']:
            if not shared.spend('await_outcome_packets', path='await.outcome.packet'):
                local.append('await_outcome_packet_budget')
                break
            declared = packet['definition']
            if declared is None:
                packet_occurrence, exception_use, exception, whole = operation, None, None, own
                binding = pair(ctx, own, whole, shared)
            else:
                origin = ctx.core_values[declared.value].origin
                packet_occurrence, packet_reached = locate(ctx, operation, origin.operation, shared)
                exception_use = _use(ctx, packet_occurrence, OwnedUse(origin.operation, declared.exception))
                exception = value_for_use(ctx, exception_use)
                whole = _result(ctx, packet_occurrence, origin)
                binding = pair(ctx, own, exception, shared)
            packet_local = list(binding['gaps'])
            packet_selected = True if declared is None else packet_reached
            if whole is None and packet_selected is not False:
                packet_local.append('await_outcome_whole_packet_unobserved')
            packets.append(_finish({'definition': declared, 'occurrence': packet_occurrence,
                'value': whole, 'exception_use': exception_use, 'exception_value': exception,
                'binding': binding, 'gaps': tuple(packet_local)},
                selected=packet_selected, bindings=(binding,)))
        for terminal in definition['terminals']:
            if not shared.spend('await_outcome_conversion_terminals', path='await.outcome.terminal'):
                local.append('await_outcome_terminal_budget')
                break
            structured = 'current_source' in terminal
            completions = ()
            if structured and shared.spend('await_structured_completion_context', len(call_chain) + 1):
                completions = tuple(call['completion'] for call in call_chain
                    if operation is not None and call['activation'].id == ctx.activation_of(operation.id))
            exact = completions[0] if len(completions) == 1 else None
            projected = _terminal(ctx, terminal, operation, advance,
                terminal.get('advance_result'), _map(drive, operation), shared,
                state_definitions=terminal.get('states', ()) if structured else definition['states'],
                exact_completion=exact, completion_required=structured)
            alternatives = tuple(pair(ctx, packet['value'], projected['packet_value'], shared)
                for packet in packets if packet['selected'] is not False)
            proven = next((binding for binding in alternatives if binding['match'] is True), None)
            if proven is not None:
                packet_binding = {**proven, 'alternatives': alternatives}
            elif alternatives:
                packet_binding = {**alternatives[0], 'match': False if all(
                    binding['match'] is False for binding in alternatives) else None,
                    'alternatives': alternatives,
                    'gaps': ('await_outcome_packet_delivery_unproved',)}
            else:
                packet_binding = {**pair(ctx, None, projected['packet_value'], shared),
                    'alternatives': (), 'gaps': ('await_outcome_packet_delivery_unproved',)}
            projected['root_binding'] = packet_binding
            projected['packet_binding'] = (projected['current_binding'] if structured else packet_binding)
            terminals.append(_finish(projected, selected=projected['selected'],
                children=(*projected['states'], *projected['consumers']),
                bindings=(projected['binding'], projected['packet_binding']), definition=terminal))
        state_rows = tuple(state for terminal in terminals for state in terminal['states'])
    elif selected is None:
        local.append('await_outcome_conversion_unobserved')
    return _finish({'definition': definition, 'occurrence': operation, 'own_value': own,
        'input_value': input_value, 'input_binding': input_binding, 'packets': tuple(packets),
        'terminals': tuple(terminals), 'states': state_rows, 'gaps': tuple(local)}, selected=selected,
        children=(*packets, *terminals, *state_rows),
        bindings=() if input_binding is None else (input_binding, definition['input_binding']))


def _prepared(ctx, definition, advance, shared):
    key = (definition['scope'], definition['source'], definition['advance_operation'],
           definition['input_guard'], definition['choices'], definition['drive_outcome'].drive, advance.id)
    candidates = ctx._await_outcome_prepared.get(key, ())
    if not shared.spend('await_outcome_prepared_candidates', len(candidates) + 1,
                        path='await.outcome.prepared_candidates'):
        return ()
    selected = tuple(row for row in candidates if row['advance_selected'] is True)
    return selected or tuple(row for row in candidates if row['advance_selected'] is None) or tuple(candidates)


def _raised_terminals(ctx, definitions, drive, advance, body, call_chain, shared):
    """A real body exception has no conversion operation to stand in for D."""
    rows = []
    for definition in definitions:
        if not shared.spend('await_body_raise_terminals', path='await.body_raise.terminal'):
            break
        exact = ()
        if drive is not None and shared.spend('await_body_raise_call_context', len(call_chain) + 1):
            exact = tuple(call['completion'] for call in call_chain
                          if call['activation'].id == ctx.activation_of(drive.id))
        projected = _terminal(ctx, definition, drive, advance,
            definition.get('advance_result'), _map(drive, advance), shared,
            exact_completion=exact[0] if len(exact) == 1 else None, completion_required=True)
        root_value = port_value(ctx, definition['root_source'], _map(drive), shared)
        body_binding = pair(ctx, _payload(ctx, body), root_value, shared)
        root = pair(ctx, root_value, projected['packet_value'], shared)
        projected['root_binding'] = root
        projected['body_binding'] = body_binding
        retained = definition['current_source'] == definition['root_source']
        if retained or root['match'] is None:
            projected['gaps'] = (*projected['gaps'], *root['gaps'])
        rows.append(_finish(projected, selected=projected['selected'],
            children=(*projected['states'], *projected['consumers']),
            bindings=(projected['binding'], body_binding, *((root,) if retained else ())), definition=definition))
    return tuple(rows)


def _outcome_occurrences(ctx, definition, advance, shared):
    from .await_links import _drive_routes
    admitted = shared.spend('await_outcome_parent_occurrences', path='await.outcome.parent')
    prepared = _prepared(ctx, definition, advance, shared) if admitted else ()
    admitted = admitted and shared.spend('await_outcome_source_supports',
        sum(len(row['source_candidates']) + len(row.get('matched_sources', ())) for row in prepared) + 1,
        path='await.outcome.source_supports')
    if not admitted:
        prepared = ()
    candidates = {source['occurrence'].id: source for row in prepared for source in row['source_candidates']}
    matched = {source['occurrence'].id: source for row in prepared for source in row.get('matched_sources', ())}
    routes = _drive_routes(ctx, advance, definition['drive_outcome'].drive, shared) if admitted else ()
    case = (False if prepared and all(row['case_selected'] is False for row in prepared) else
            True if any(row['case_selected'] is True for row in prepared) else None)
    rows = []
    for route in routes or ({'call_chain': (), 'drive_occurrence': None},):
        drive = route['drive_occurrence']
        view = None if drive is None else ctx.resolved_body_drives.get(drive.id)
        body = None if view is None else view['outcome']
        selected = (False if case is False else None if case is None or body is None else
                    body.operation == definition['drive_outcome'].source)
        local = _base_gaps(definition, (*definition['conversion_legs'],
                          *definition['advance_legs'], *definition['consumers']))
        conversions, consumers, raised_terminals = (), (), ()
        if selected is not False:
            if not matched:
                local.append('await_outcome_source_occurrence_unproved')
            if drive is None:
                local.append('await_outcome_drive_call_missing')
            if body is None:
                local.append('await_outcome_body_outcome_missing')
        if selected is True:
            conversions = tuple(_conversion(ctx, leg, advance, drive, body, shared,
                                consumer_definitions=definition['consumers'], call_chain=route['call_chain'])
                                for leg in definition['conversion_legs'])
            known = _map(advance, drive, body, *(source['occurrence'] for source in matched.values()),
                         *(leg['occurrence'] for leg in conversions))
            anchors = (advance, drive, *(leg['occurrence'] for leg in conversions))
            consumers = tuple(_consumer(ctx, consumer, advance, known, anchors, shared)
                              for consumer in definition['consumers'])
            raised_terminals = _raised_terminals(ctx, definition.get('terminals', ()), drive,
                advance, body, route['call_chain'], shared)
            if 'terminals' in definition and shared.truncated:
                local.append('await_body_raise_terminal_budget')
        row = _finish({'key': (definition['key'], advance.id, None if drive is None else drive.id),
            'advance': advance, 'source_candidates': tuple(candidates.values()),
            'matched_sources': tuple(matched.values()), 'call_chain': route['call_chain'],
            'drive': drive, 'body_outcome': body, 'conversion_legs': conversions,
            **({} if 'terminals' not in definition else {'terminals': raised_terminals}),
            'consumers': consumers, 'gaps': tuple(local)}, selected=selected,
            children=(*conversions, *consumers, *raised_terminals))
        if not admitted:
            row['status'] = 'NOT_CHECKED'
        rows.append(row)
    return tuple(rows)


def _failure_occurrence(ctx, definition, source, shared):
    admitted = shared.spend('await_failure_parent_occurrences', path='await.failure.parent')
    own = definition['stage_operation'] == definition['source_operation']
    calls = tuple(ctx.resolved_call_activations[identity]
                  for identity in ctx.call_activations_by_caller.get(source.id, ())) if admitted else ()
    call = calls[0] if len(calls) == 1 and not own else None
    entry = None if call is None else call['entry']
    stage, prefix, local = None, [], list(definition.get('gaps', ()))
    if call is not None and call['completion'] is None:
        local.append('await_failure_call_completion_unobserved')
    selected, terminals = None, []
    if admitted and own:
        stage, selected = source, choice(ctx, source, definition['edge'])
    elif admitted and call is not None and entry is not None:
        answers = []
        for edge in definition['choices']:
            occurrence, reached = locate(ctx, entry, edge.operation, shared, entry=True)
            actual = choice(ctx, occurrence, edge) if reached is not False else False
            prefix.append({'edge': edge, 'occurrence': occurrence, 'selected': actual,
                           'transfer': None if occurrence is None else ctx.outgoing.get(occurrence.id)})
            answers.append(actual)
        operation, reached = locate(ctx, entry, definition['stage_operation'], shared, entry=True)
        selected = (False if False in answers or reached is False else None if None in answers
                    else choice(ctx, operation, definition['edge']))
        if selected is True:
            stage = operation
    elif admitted:
        local.append('await_failure_call_activation_missing')
    if selected is True:
        known = _map(source, stage)
        for terminal in definition['terminals']:
            if not shared.spend('await_failure_occurrence_terminals', path='await.failure.terminal'):
                local.append('await_failure_terminal_budget')
                break
            # Payload ordinal zero is the original source R completion, not
            # the first State slot nor a landing-position assumption.
            from scar.ir.program.await_outcome_flow import result_legs
            parent_port = next((leg['own_result'] for leg in result_legs(ctx.await_flow,
                ctx.core_operations[source.operation]) if leg['kind'] is ExitKind.RAISE), None)
            terminals.append(_terminal(ctx, terminal, source if own else stage, source,
                parent_port, known, shared, own=own,
                exact_completion=None if own else call['completion'], completion_required=not own))
    elif selected is None:
        local.append('await_failure_path_unobserved')
    consumers = tuple(consumer for terminal in terminals for consumer in terminal['consumers'])
    row = _finish({'key': (definition['key'], source.id), 'source': source,
        'call_chain': () if call is None else (call,), 'stage': stage, 'prefix': tuple(prefix),
        'terminals': tuple(terminals), 'consumers': consumers, 'gaps': tuple(local)},
        selected=selected, children=tuple(terminals), definition=definition)
    if not admitted:
        row['status'] = 'NOT_CHECKED'
    return row


def project_outcomes(ctx, scope, shared):
    from scar.ir.program.await_failures import failure_paths
    from scar.ir.program.await_outcomes import outcome_connections
    if ctx.await_flow is None:
        from scar.ir.program.await_outcome_flow import inventory
        empty = {**inventory((), 0, True), 'occurrence_count': 0, 'observed_occurrence_count': 0,
            'checked_occurrence_count': 0, 'pending_occurrence_count': 0}
        return {'outcomes': (), 'outcome_inventory': {**empty, 'drive_successors_total': 0},
                'failure_paths': (), 'failure_path_inventory': empty, 'gaps': ()}
    ctx._await_outcome_prepared = {}
    has_captures = any(job['source_occurrence_count'] or job['occurrences'] for job in ctx.await_jobs)
    for job in ctx.await_jobs:
        if not job['occurrences']:
            continue
        if not shared.spend('await_outcome_prepared_jobs', path='await.outcome.prepared'):
            break
        for occurrence in job['occurrences']:
            if not shared.spend('await_outcome_prepared_occurrences', path='await.outcome.prepared'):
                break
            key = (job['scope'], job['source'], job['advance_operation'], job.get('input_guard'),
                   job['choices'], job.get('drive'), occurrence['advance'].id)
            ctx._await_outcome_prepared.setdefault(key, []).append(occurrence)
    # With no captured parent there is no dynamic pairing to search. Preserve
    # raw original keys, mark their detailed proof deliberately NOT_CHECKED,
    # and do not invent budget exhaustion for an empty occurrence inventory.
    static_outcomes = outcome_connections(ctx.await_flow, ctx.await_static_inventory, derive=has_captures)
    static_failures = failure_paths(ctx.await_flow, scope=scope, derive=has_captures)
    result, all_gaps = {}, []
    for field, inventory_field, original, parent_field in (
            ('outcomes', 'outcome_inventory', static_outcomes, 'advance_operation'),
            ('failure_paths', 'failure_path_inventory', static_failures, 'source_operation')):
        rows, checked_parents, observed, checked_jobs, cursor = [], 0, 0, 0, None
        for definition in original[field]:
            captures = ctx.await_occurrences_by_site.get(definition[parent_field], ())
            occurrences, checked = [], 0
            for parent in captures:
                derived = (_outcome_occurrences(ctx, definition, parent, shared) if field == 'outcomes'
                           else (_failure_occurrence(ctx, definition, parent, shared),))
                occurrences.extend(derived)
                checked += int(not shared.truncated and all(row['status'] != 'NOT_CHECKED' for row in derived))
            local = list(definition.get('gaps', ()))
            if not captures:
                local.append('await_outcome_capture_missing')
            if shared.truncated:
                local.append('await_outcome_projection_budget')
                cursor = cursor or {'phase': field, 'key': definition['key']}
            checked_jobs += int(checked == len(captures) and not shared.truncated
                                and definition['status'] != 'NOT_CHECKED')
            checked_parents += checked
            observed += len(captures)
            rows.append(_finish({'key': definition['key'], 'definition': definition,
                'occurrences': tuple(occurrences), 'occurrence_count': len(captures),
                'checked_occurrence_count': checked,
                'pending_occurrence_count': len(captures) - checked, 'gaps': tuple(local)},
                children=tuple(occurrences), definition=definition))
            append_gaps(all_gaps, (rows[-1],))
        inventory = original[inventory_field]
        complete = inventory['known_inventory_complete'] and not shared.truncated
        if cursor is None and (not complete or shared.truncated):
            cursor = inventory['cursor'] or {'phase': field, 'scope': scope, 'key': None}
        result[field] = tuple(rows)
        result[inventory_field] = {**inventory, 'checked_count': checked_jobs,
            'static_inventory_complete': inventory['known_inventory_complete'],
            'static_jobs_total': inventory['jobs_total'],
            'known_inventory_complete': complete,
            'jobs_total': len(rows) if complete else None,
            'pending_count': len(rows) - checked_jobs if complete else None,
            'occurrence_count': observed if complete else None,
            'observed_occurrence_count': observed, 'checked_occurrence_count': checked_parents,
            'pending_occurrence_count': observed - checked_parents if complete else None,
            'cursor': cursor or inventory['cursor']}
        for code, path, message in original['issues']:
            ctx.issue(code, path, message)
    result['gaps'] = tuple(all_gaps)
    result['outcome_preparation'] = {'static': dict(ctx.await_flow.preparation),
        'details_deferred_without_capture': not has_captures,
        'cost_scope': 'raw original-key/index enumeration is separate from bounded proof and occurrence search'}
    return result


__all__ = ['project_outcomes']

"""Original body outcomes connected to physical packets and caller consumers.

The original inventory precedes adapters. Declared semantic conversions stay
conditional, and never become copy/alias edges in the canonical graph.
"""
from .await_outcome_flow import (answer, bind_target, combine, consumers, flags,
    inventory, packet_use, prepare, required_choices, result_legs, selected,
    state_links, terminal_inventory)
from .lifecycle import DriveOutcomeRef
from .control import ProtocolValueKind
from .model import ExitKind, OperationResult, ProtocolValue, TerminatorKind
from .protocol_connections import ProtocolOperationRef
from .protocols import (ContractResult, DriveResult, HostTerminal, OutcomeAdapterRule,
                        OwnedUse, StaticProtocolGap)
from .structured import ControlEdgeReference
from .completion_adapter_routes import packets as _packets, structured_region


COMPLETION_RULES = (OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
                    OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION)


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _own_legs(ctx, operation, rows, choices, issues, *, required):
    """Raw N/R inventory first, then optional own contract/consumer receipts."""
    legs, gaps = [], []
    for original in result_legs(ctx, operation):
        if not ctx.spend('await_final_completion_legs'):
            legs.append({**original, 'targets': (), 'bindings': (), 'states': (),
                         'status': 'NOT_CHECKED', 'gaps': ()})
            continue
        own = original['own_result']
        local = []
        if own is None:
            legs.append({**original, 'targets': (), 'bindings': (), 'states': (),
                         'status': 'PARTIAL', 'gaps': ('await_final_payload_slot_unresolved',)})
            gaps.append('await_final_payload_slot_unresolved')
            continue
        conditions = selected(ctx, choices, original['edge'])
        ledger = consumers(ctx, own, conditions)
        targets = list(ledger['targets'])
        matching = tuple(row for row in rows if row.contract.output == own)
        if required and not matching:
            local.append('await_final_adapter_leg_missing')
        for row in matching:
            receipt = ctx.result_consumers.get(_ref(row))
            if receipt is None:
                local.append('protocol_result_consumers_missing')
                continue
            for target in receipt.targets:
                if not ctx.spend('await_final_receipt_targets'):
                    break
                if type(target) is StaticProtocolGap:
                    local.append('await_final_consumer_attachment_gap')
                elif target not in targets:
                    targets.append(target)
        bindings = tuple(bind_target(ctx, own, target, conditions) for target in targets)
        for binding in bindings:
            if binding['match'] is False:
                local.append('await_final_consumer_binding_contradicted')
                issues.append(('protocol_await_final_copy', str(operation.id),
                    'final consumer does not use this exact own completion payload'))
            elif binding['match'] is None:
                local.append('await_final_consumer_binding_unproved')
        if not targets:
            local.append('await_final_output_consumer_unresolved')
        states = []
        if original['edge'] is not None:
            for target in targets:
                if type(target) is HostTerminal:
                    states.extend(state_links(ctx, target, original['edge'], conditions, outward=True))
        for state in states:
            if state['binding']['match'] is False:
                local.append('await_final_state_contradicted')
                issues.append(('protocol_await_final_state', str(operation.id),
                               'final consumer uses another completion/state slot'))
            elif state['binding']['match'] is None:
                local.append('await_final_state_unproved')
        local.extend(ledger['gaps'])
        contradicted = any(binding['match'] is False for binding in bindings) or any(
                          state['binding']['match'] is False for state in states)
        legs.append({**original, 'targets': tuple(targets), 'bindings': bindings, 'states': tuple(states),
            'status': 'CONTRADICTED' if contradicted else 'PARTIAL' if local or ctx.budget.truncated else 'DECLARED',
            'gaps': tuple(dict.fromkeys(local))})
        gaps.extend(local)
    return tuple(legs), tuple(dict.fromkeys(gaps))


def _caller_consumers(ctx, advance, parent, choices, role, requires, issues):
    _, by_operation, _ = prepare(ctx)
    source = parent['own_result']
    if source is None:
        return (), ('await_advance_payload_unresolved',)
    ledger = consumers(ctx, source, choices)
    views, gaps = [], list(ledger['gaps'])
    for support in ledger['support']:
        if not ctx.spend('await_outcome_consumer_jobs'):
            break
        actual, binding = support['actual'], support['binding']
        local = []
        operation = ctx.operations[actual.operation]
        final_rows = tuple(row for row in by_operation.get(operation.id, ())
            if row.contract.rule is OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION
            and type(row.contract.input) is ContractResult
            and row.contract.input.operation == advance.id
            and row.contract.input.result_port == source
            and row.contract.input_use == getattr(actual, 'use', None))
        if requires and not final_rows:
            local.append('await_final_adapter_missing')
        legs, leg_gaps = ((), ()) if type(actual) is HostTerminal else _own_legs(
            ctx, operation, final_rows, choices, issues, required=bool(requires))
        local.extend(leg_gaps)
        if binding['match'] is not True:
            local.append('await_consumer_must_binding_unproved')
        from .region_implementation import region_implementation
        implementation = region_implementation(ctx, source, operation, choices,
            graph=ledger['consumer_graph'], parent_legs=legs)
        views.append({'actual': actual, 'advance_result': source, 'choices': choices,
            'consumer_graph': ledger['consumer_graph'],
            'implementation': implementation,
            'binding': binding, 'final_rows': final_rows, 'legs': legs, 'role': role,
            'requires_final_extraction': requires,
            'status': 'CONTRADICTED' if any(leg['status'] == 'CONTRADICTED' for leg in legs) else
                      'PARTIAL' if local or ctx.budget.truncated else 'DECLARED',
            'gaps': tuple(dict.fromkeys(local)), **flags()})
        gaps.extend(local)
    return tuple(views), tuple(dict.fromkeys(gaps))


def outcome_connections(ctx, original_inventory, *, derive=True):
    from .protocol_await import _result_copy
    by_input, _, successor_total = prepare(ctx)
    seeds, seen = [], set()
    enumeration_complete = original_inventory['known_inventory_complete']
    cursor = original_inventory['cursor']
    for job in original_inventory['jobs']:
        if job.get('drive') is None or job.get('advance_operation') is None:
            continue
        drive = ctx.operations[job['drive']]
        for number, edge in enumerate(drive.terminator.successors):
            if derive and not ctx.spend('await_original_outcome_edges'):
                enumeration_complete = False
                cursor = cursor or {'phase': 'await_outcome_inventory', 'drive': drive.id, 'successor': number}
                # Retain this and the raw declared suffix keys. Exhaustion
                # prevents detail proofs, never erases original anchors.
            body = ctx.operations[edge.source]
            outcome = DriveOutcomeRef(drive.id, edge.source)
            key = (job['scope'], job['source_operation'], job['advance_operation'],
                   job.get('input_guard'), job['choices'], outcome)
            if key in seen:
                continue
            seen.add(key)
            seeds.append((key, job, number, body, outcome))
    if not derive:
        ctx.preparation['await_deferred_original_outcome_keys'] = len(seeds)
    rows, issues, gaps, checked = [], [], [], 0
    for key, job, number, body, outcome in seeds:
        payload = DriveResult(outcome, 0)
        kind = ('RETURN_COMPLETION' if body.terminator.kind is TerminatorKind.RETURN else
                'EXCEPTION' if body.terminator.kind is TerminatorKind.RAISE else
                'HANDOFF' if body.terminator.kind is TerminatorKind.SUSPEND else 'UNRESOLVED')
        row = {'key': key, 'scope': job['scope'], 'source': job['source'],
            'source_operation': job['source_operation'], 'advance_operation': job['advance_operation'],
            'input_guard': job.get('input_guard'), 'choices': job['choices'],
            'drive_outcome': outcome, 'payload': payload, 'kind': kind}
        if not derive or ctx.budget.truncated or not ctx.spend('await_outcome_jobs'):
            rows.append({**row, 'conversion_legs': (), 'advance_legs': (), 'consumers': (), 'status': 'NOT_CHECKED',
                         'gaps': ('await_static_details_deferred_without_capture',) if not derive else
                                 ('await_outcome_budget',), **flags()})
            if derive:
                cursor = cursor or {'phase': 'await_outcome_jobs', 'key': key}
            continue
        local, converted, advance_legs, caller_views = list(job['gaps']), [], [], []
        required, complete = required_choices(ctx, payload)
        choices = selected(ctx, job['choices'], required, ControlEdgeReference(outcome.drive, number))
        if not complete:
            local.append('await_outcome_source_prefix_unresolved')
        advance = ctx.operations[job['advance_operation']]
        parents = tuple(result_legs(ctx, advance))
        conversion_rows = tuple(candidate for candidate in by_input.get(payload, ())
                                if candidate.contract.rule in COMPLETION_RULES)
        producer_ids = tuple(dict.fromkeys(candidate.operation for candidate in conversion_rows))
        if kind == 'RETURN_COMPLETION' and not producer_ids:
            local.append('await_completion_adapter_missing')
        for producer in producer_ids:
            operation = ctx.operations[producer]
            candidates = tuple(candidate for candidate in conversion_rows if candidate.operation == producer)
            input_binding = ctx.bind(payload, OwnedUse(producer, candidates[0].contract.input_use), guard=choices)
            for leg in result_legs(ctx, operation):
                if not ctx.spend('await_conversion_legs'):
                    break
                leg_choices = selected(ctx, choices, leg['edge'])
                own = leg['own_result']
                role = 'COMPLETION' if leg['kind'] is ExitKind.NORMAL else 'CONSTRUCTION_FAILURE'
                own_rows = tuple(candidate for candidate in candidates if candidate.contract.output == own)
                packets, packet_gaps = (_packets(ctx, own, leg_choices) if own is not None
                    and leg['kind'] is ExitKind.NORMAL else
                    (({'source': own, 'definition': None, 'exception_binding': None},), ()) if own is not None
                    else ((), ('await_conversion_payload_unresolved',)))
                if own is not None and structured_region(ctx, own):
                    from .await_structured_completion import structured_completion
                    joined = structured_completion(ctx, own, packets, leg_choices,
                        parents, advance, input_binding, own_rows, role, _caller_consumers, issues)
                    leg_gaps = [*packet_gaps, *joined['gaps']]
                    if not own_rows:
                        leg_gaps.append('await_completion_adapter_leg_missing')
                    if input_binding['match'] is not True:
                        leg_gaps.append('await_conversion_input_unproved')
                    converted.append({'operation': producer, **leg, 'role': role,
                        'choices': leg_choices, 'rows': own_rows, 'input_binding': input_binding,
                        'packets': packets, 'continuations': joined['continuations'],
                        'terminals': joined['terminals'], 'states': joined['states'],
                        'status': 'CONTRADICTED' if input_binding['match'] is False or any(
                            terminal['status'] == 'CONTRADICTED' for terminal in joined['terminals']) else
                            'PARTIAL' if leg_gaps or ctx.budget.truncated else 'DECLARED',
                        'gaps': tuple(dict.fromkeys(leg_gaps))})
                    caller_views.extend(joined['consumers'])
                    local.extend(leg_gaps)
                    continue
                terminals, terminal_gaps = (((), ('await_conversion_payload_unresolved',)) if own is None
                                           else terminal_inventory(ctx, own, leg_choices))
                terminal_views, states, leg_gaps = [], [], list((*packet_gaps, *terminal_gaps))
                if not own_rows:
                    leg_gaps.append('await_completion_adapter_leg_missing')
                for terminal in terminals:
                    if not ctx.spend('await_conversion_terminals'):
                        break
                    target = packet_use(ctx, terminal)
                    packet_reports = tuple(ctx.bind(packet['source'], target, guard=leg_choices)
                        for packet in packets if packet['source'] is not None and target is not None)
                    copied = (answer(True, bindings=packet_reports) if any(
                        report['match'] is True for report in packet_reports) else
                        answer(False, bindings=packet_reports,
                            gaps=('await_conversion_packet_terminal_contradicted',))
                        if packet_reports and all(report['match'] is False for report in packet_reports) else
                        answer(gaps=('await_conversion_packet_terminal_unproved',)))
                    if copied['match'] is not True:
                        leg_gaps.extend(copied['gaps'])
                    if copied['match'] is False:
                        issues.append(('protocol_await_conversion_packet', str(producer),
                            'driver terminal is not a packet of this own conversion result'))
                    terminal_views.append({'terminal': terminal, 'packet': target, 'binding': copied})
                    if leg['edge'] is not None:
                        states.extend(state_links(ctx, terminal, leg['edge'], leg_choices, outward=True))
                    for parent in parents:
                        if parent['kind'] is not ExitKind.RAISE or parent['own_result'] is None:
                            continue
                        conditions = selected(ctx, leg_choices, parent['edge'])
                        delivery = (answer(gaps=('await_conversion_terminal_packet_missing',)) if target is None
                                    else _result_copy(ctx, target, parent['own_result'], conditions))
                        requires = (role == 'COMPLETION' and copied['match'] is True
                                    and delivery['match'] is True and input_binding['match'] is True
                                    and bool(own_rows))
                        if delivery['match'] is not True:
                            leg_gaps.append('await_conversion_caller_delivery_unproved')
                        views, consumer_gaps = _caller_consumers(ctx, advance, parent, conditions,
                            role, requires if role != 'COMPLETION' or requires else None, issues)
                        if delivery['match'] is not True:
                            views = tuple({**view, 'delivery_binding': delivery, 'status': 'PARTIAL',
                                'gaps': (*view['gaps'], 'await_conversion_caller_delivery_unproved')}
                                for view in views)
                        else:
                            views = tuple({**view, 'delivery_binding': delivery} for view in views)
                        caller_views.extend(views)
                        leg_gaps.extend(consumer_gaps)
                        terminal_views[-1].update(advance_result=parent['own_result'], delivery_binding=delivery)
                for state in states:
                    if state['binding']['match'] is None:
                        leg_gaps.append('await_conversion_state_unproved')
                    elif state['binding']['match'] is False:
                        leg_gaps.append('await_conversion_state_contradicted')
                        issues.append(('protocol_await_conversion_state', str(producer),
                            'conversion terminal uses another state completion'))
                if input_binding['match'] is None:
                    leg_gaps.append('await_conversion_input_unproved')
                elif input_binding['match'] is False:
                    leg_gaps.append('await_conversion_input_contradicted')
                    issues.append(('protocol_await_conversion_input', str(producer),
                        'conversion input is not this exact body outcome payload'))
                converted.append({'operation': producer, **leg, 'role': role, 'choices': leg_choices,
                    'rows': own_rows, 'input_binding': input_binding, 'packets': packets,
                    'terminals': tuple(terminal_views),
                    'states': tuple(states), 'status': 'CONTRADICTED' if input_binding['match'] is False
                        or any(state['binding']['match'] is False for state in states)
                        or any(terminal['binding']['match'] is False for terminal in terminal_views) else
                        'PARTIAL' if leg_gaps or input_binding['match'] is None or ctx.budget.truncated else 'DECLARED',
                    'gaps': tuple(dict.fromkeys(leg_gaps))})
                local.extend(leg_gaps)
        if not producer_ids:
            # Even total deletion of semantic adapters cannot delete the
            # caller's actual consumers or the original BodyReturn obligation.
            for parent in parents:
                if parent['own_result'] is None:
                    continue
                conditions = selected(ctx, choices, parent['edge'])
                delivery = (_result_copy(ctx, payload, parent['own_result'], conditions)
                            if kind in ('HANDOFF', 'EXCEPTION') else
                            answer(gaps=('await_completion_conversion_unproved',)))
                if delivery['match'] is False:
                    advance_legs.append({**parent, 'delivery_binding': delivery, 'consumers': (),
                        'status': 'NOT_APPLICABLE', 'gaps': ()})
                    continue
                views, consumer_gaps = _caller_consumers(ctx, advance, parent, conditions,
                    'HANDOFF' if kind == 'HANDOFF' else 'EXCEPTION' if kind == 'EXCEPTION' else 'UNRESOLVED',
                    False if kind in ('HANDOFF', 'EXCEPTION') else None, issues)
                caller_views.extend(views)
                local.extend(consumer_gaps)
                if delivery['match'] is None:
                    local.append('await_outcome_caller_delivery_unproved')
                    views = tuple({**view, 'status': 'PARTIAL', 'delivery_binding': delivery,
                        'gaps': (*view['gaps'], 'await_outcome_caller_delivery_unproved')} for view in views)
                    # Replace the same original consumer projections, keeping
                    # the unresolved delivery visible at every child level.
                    if views:
                        caller_views[-len(views):] = views
                advance_legs.append({**parent, 'delivery_binding': delivery, 'consumers': views,
                    'status': 'PARTIAL' if delivery['match'] is None or consumer_gaps else 'DECLARED',
                    'gaps': consumer_gaps})
        if producer_ids:
            for parent in parents:
                alternatives = tuple(terminal for leg in converted for terminal in leg['terminals']
                    if terminal.get('advance_result') == parent['own_result'])
                checks = tuple(terminal['delivery_binding'] for terminal in alternatives)
                advance_legs.append({**parent, 'alternatives': alternatives,
                    'delivery_bindings': checks,
                    'status': 'PARTIAL' if not checks or any(check['match'] is None for check in checks)
                        else 'DECLARED' if all(check['match'] is True for check in checks) else 'CONTRADICTED',
                    'gaps': () if checks else ('await_advance_outcome_leg_unproved',)})
        local.extend(gap for leg in advance_legs for gap in leg['gaps'])
        if any(leg['status'] == 'PARTIAL' for leg in advance_legs):
            local.append('await_advance_outcome_leg_unproved')
        checked += int(not ctx.budget.truncated)
        rows.append({**row, 'conversion_legs': tuple(converted), 'advance_legs': tuple(advance_legs),
            'consumers': tuple(caller_views),
            'status': 'CONTRADICTED' if any(leg['status'] == 'CONTRADICTED' for leg in converted)
                or any(leg['status'] == 'CONTRADICTED' for leg in advance_legs)
                or any(consumer['status'] == 'CONTRADICTED' for consumer in caller_views) else
                'PARTIAL' if local or ctx.budget.truncated else 'DECLARED',
            'gaps': tuple(dict.fromkeys(local)), **flags()})
        gaps.extend(local)
        if ctx.budget.truncated:
            cursor = cursor or {'phase': 'await_outcome_connections', 'key': key}
    complete = enumeration_complete and not ctx.budget.truncated
    return {'outcomes': tuple(rows), 'outcome_inventory': inventory(rows, checked, complete,
        cursor=cursor, drive_successors_total=successor_total), 'issues': tuple(issues), 'gaps': tuple(gaps)}


__all__ = ['outcome_connections']

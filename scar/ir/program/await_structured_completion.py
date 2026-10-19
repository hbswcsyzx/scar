"""Connect typed same-region completion receipts to their exact caller ports."""
from .await_outcome_flow import selected, state_links
from .completion_adapter_routes import continuation_rows
from .model import ExitKind, TerminatorKind


def structured_completion(ctx, source, packets, choices, parents, advance,
                          input_binding, own_rows, role, consumers, issues):
    from .protocol_await import _result_copy
    rows, missing = continuation_rows(ctx, source, choices, candidates=packets)
    terminals, states, caller_views, gaps = [], [], [], list(missing)
    for row in rows:
        for receipt in row['continuation']['terminals']:
            if not ctx.spend('await_structured_terminals'):
                gaps.append('await_structured_budget')
                break
            terminal, actual = receipt['terminal'], receipt['actual']
            copied, root = receipt['binding'], receipt['root_binding']
            if copied['match'] is False:
                gaps.append('await_conversion_packet_terminal_contradicted')
                issues.append(('protocol_await_conversion_packet', str(terminal.operation),
                    'cleanup terminal is not its current completion source'))
            elif copied['match'] is None:
                gaps.append('await_conversion_packet_terminal_unproved')
            kind = (ExitKind.RAISE if ctx.operations[terminal.operation].terminator.kind
                    is TerminatorKind.RAISE else ExitKind.NORMAL)
            for parent in parents:
                if parent['kind'] is not kind or parent['own_result'] is None:
                    continue
                conditions = selected(ctx, receipt['choices'], parent['edge'])
                delivery = _result_copy(ctx, actual, parent['own_result'], conditions)
                current_states = state_links(ctx, terminal, parent['edge'], conditions)
                states.extend(current_states)
                for state in current_states:
                    if state['binding']['match'] is False:
                        gaps.append('await_conversion_state_contradicted')
                        issues.append(('protocol_await_conversion_state', str(terminal.operation),
                            'current cleanup terminal state does not reach its own caller result'))
                    elif state['binding']['match'] is None:
                        gaps.append('await_conversion_state_unproved')
                preserved = root['match'] is True and receipt['role'] == 'packet'
                overridden = (root['match'] is False and copied['match'] is True
                    and receipt['current_source'] != receipt['root_source'])
                receiver_role = 'OVERRIDE' if overridden else role
                requires = (False if overridden or role != 'COMPLETION' else
                    True if preserved and copied['match'] is True and delivery['match'] is True
                    and input_binding['match'] is True and own_rows else None)
                views, consumer_gaps = ((), ()) if delivery['match'] is False else consumers(
                    ctx, advance, parent, conditions, receiver_role, requires, issues)
                views = tuple({**view, 'delivery_binding': delivery,
                    **({'status': 'PARTIAL', 'gaps': tuple(dict.fromkeys((*view.get('gaps', ()),
                        'await_conversion_caller_delivery_unproved')))}
                       if delivery['match'] is None else {})} for view in views)
                caller_views.extend(views)
                gaps.extend(consumer_gaps)
                terminal_gaps = list(receipt['gaps'])
                if not preserved and not overridden and role == 'COMPLETION':
                    terminal_gaps.append('await_completion_preservation_unproved')
                if delivery['match'] is not True:
                    terminal_gaps.append('await_conversion_caller_delivery_contradicted'
                        if delivery['match'] is False else 'await_conversion_caller_delivery_unproved')
                terminal_gaps.extend(gap for state in current_states for gap in state.get('gaps', ()))
                terminal_gaps.extend('await_conversion_state_contradicted'
                    if state['binding']['match'] is False else 'await_conversion_state_unproved'
                    for state in current_states if state['binding']['match'] is not True)
                if ctx.budget.truncated:
                    terminal_gaps.append('await_completion_terminal_budget')
                gaps.extend(terminal_gaps)
                matches = (copied['match'], delivery['match'],
                           *(state['binding']['match'] for state in current_states))
                terminals.append({**receipt, 'packet': actual, 'choices': conditions,
                    'advance_result': parent['own_result'], 'delivery_binding': delivery,
                    'states': current_states, 'consumers': views,
                    'status': 'CONTRADICTED' if False in matches else
                        'PARTIAL' if None in matches or terminal_gaps else receipt['status'],
                    'gaps': tuple(dict.fromkeys(terminal_gaps))})
    return {'continuations': rows, 'terminals': tuple(terminals), 'states': tuple(states),
            'consumers': tuple(caller_views), 'gaps': tuple(dict.fromkeys(gaps))}

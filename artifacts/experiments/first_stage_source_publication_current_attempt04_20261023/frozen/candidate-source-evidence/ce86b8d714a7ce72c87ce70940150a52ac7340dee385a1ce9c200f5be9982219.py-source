"""Bounded original-port inventories shared by await outcome/failure views.

May-copy enumerates possible consumers. Only a later must binding establishes
an exact connection. No semantic projection is inserted into ordinary copies.
"""
from .control import ProtocolValueKind
from .model import (CompletionResult, ExitKind, InvokeLiteralResult, OperationResult,
                    ProtocolValue, StateVersionValue, TerminatorKind, ValueKind)
from .protocols import HostTerminal, OutcomeAdapter, OwnedUse
from .structured import ControlEdgeReference
from .copy_flow import flow, required_choices, selected
from .copy_flow import inventory_flow
from .operation_results import result_legs


def flags():
    return {'source_runtime_verified': False, 'runtime_identity_verified': False,
            'value_identity_verified': False, 'transformation_authorized': False}


def answer(match=None, *, gaps=(), **extra):
    return {'match': match, 'routes': (), 'gaps': tuple(gaps), **extra}


def combine(reports):
    checks = tuple(row['match'] for row in reports)
    return answer(False if False in checks else None if not checks or None in checks else True,
                  gaps=tuple(gap for row in reports for gap in row.get('gaps', ())),
                  bindings=tuple(reports))


def prepare(ctx):
    if hasattr(ctx, '_await_outcome_raw'):
        return ctx._await_outcome_raw
    by_input, by_operation = {}, {}
    for row in ctx.graph.protocol_operations:
        if type(row.contract) is OutcomeAdapter:
            by_input.setdefault(row.contract.input, []).append(row)
            by_operation.setdefault(row.operation, []).append(row)
    successor_total = sum(len(ctx.operations[row.operation].terminator.successors)
                          for row in ctx.graph.body_drives)
    ctx._await_outcome_raw = by_input, by_operation, successor_total
    ctx.preparation['await_outcome_raw_adapter_rows'] = sum(map(len, by_input.values()))
    ctx.preparation['await_original_drive_successors'] = successor_total
    ctx.preparation['await_prepared_value_use_index_reused'] = True
    return ctx._await_outcome_raw


def terminal_inventory(ctx, source, choices=()):
    """Original endpoints after this exact edge, not a semantic adapter search."""
    port = ctx.port(source)
    if port is None or port.operation is None or port.gap is not None:
        return (), ('await_terminal_source_unresolved',)
    operation = ctx.operations[port.operation]
    start = (operation.terminator.successors[port.edge].block if port.phase == 'edge'
             else ctx.block_of[port.operation])
    _, outgoing, _, _, _ = ctx._edges(ctx.region_of[port.operation])
    guards = ctx.selected_edges(choices, region=ctx.region_of[port.operation])
    own_choices = {edge.operation: edge.successor_index for edge in guards}
    incoming = {ctx.operations[edge.operation].terminator.successors[edge.successor_index].block:
                (edge.operation, edge.successor_index) for edge in guards}
    pending, seen, found, gaps = [start], set(), [], []
    while pending:
        if not ctx.spend('await_outcome_terminal_blocks'):
            gaps.append('await_outcome_terminal_budget')
            break
        block_id = pending.pop()
        if block_id in seen:
            continue
        seen.add(block_id)
        block = ctx.blocks[block_id]
        last = ctx.operations[block.operations[-1]]
        if last.id in ctx.drives:
            gaps.append('await_outcome_next_drive_boundary')
            continue
        kind = last.terminator.kind
        if kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            found.append(HostTerminal(last.id))
            continue
        if kind not in (TerminatorKind.INVOKE, TerminatorKind.JUMP, TerminatorKind.BRANCH):
            gaps.append('await_outcome_structured_continuation_unresolved')
            continue
        for identity, number, target, _ in reversed(outgoing[block_id]):
            if not ctx.spend('await_outcome_terminal_edges'):
                gaps.append('await_outcome_terminal_budget')
                break
            if identity in own_choices and own_choices[identity] != number:
                continue
            if target in incoming and incoming[target] != (identity, number):
                continue
            pending.append(target)
    if not found and not gaps:
        gaps.append('await_outcome_terminal_absent')
    return tuple(found), tuple(dict.fromkeys(gaps))


def terminal_payload(ctx, terminal):
    return tuple(OwnedUse(terminal.operation, identity)
        for identity in ctx.operations[terminal.operation].terminator.values
        if not isinstance(ctx.values[ctx.owned_use(terminal.operation, identity).value], StateVersionValue))


def packet_use(ctx, terminal):
    payloads = terminal_payload(ctx, terminal)
    return next((use for use in payloads if isinstance(
        value := ctx.values[ctx.owned_use(use.operation, use.use).value], ProtocolValue)
        and value.protocol is ProtocolValueKind.EXCEPTION_PACKET), None)


def bind_target(ctx, source, target, choices=()):
    if type(target) is HostTerminal:
        reports = tuple(case_binding(ctx, source, use, choices)
                        for use in terminal_payload(ctx, target))
        return {**combine(reports), 'target': target}
    return {**case_binding(ctx, source, target, choices), 'target': target}


def case_binding(ctx, source, actual, choices):
    """A possible multi-visit source is not a false payload-copy claim.

    Preserve the ordinary binding as evidence of its flat static context.
    Only a candidate in the conditional source-evaluated inventory may turn
    that context into an explicit unmet obligation, never a copy True.
    """
    binding = ctx.bind(source, actual, guard=choices or None)
    membership = inventory_flow(ctx, source, choices)
    before = membership['before']
    use = ctx.owned_use(actual.operation, actual.use)
    if (membership['conditional'] and (membership.get('pending', False)
            or before is not None and use.value in before.get(actual.operation, ()))):
        return {**answer(gaps=(*binding.get('gaps', ()), *membership['gaps'])),
                'guarded_binding': binding}
    return binding


def consumers(ctx, source, choices=()):
    """Indexed position-sensitive may inventory, with explicit call boundaries."""
    from .protocol_connection_validation import _consumer_role
    choices = ctx.selected_edges(choices)
    if not hasattr(ctx, '_await_outcome_consumers'):
        ctx._await_outcome_consumers = {}
    key = source, choices, ctx._returns.guards
    if key in ctx._await_outcome_consumers:
        return ctx._await_outcome_consumers[key]
    membership = inventory_flow(ctx, source, choices)
    before = membership['before']
    targets, support, gaps, seen = [], [], [], set()
    gaps.extend(membership['gaps'])
    if key in getattr(ctx, '_await_flow_choice_conflicts', ()):
        gaps.append('await_source_choice_conflict')
    if before is None:
        gaps.append('await_consumer_inventory_unresolved')
    else:
        for operation, values in before.items():
            if not ctx.spend('await_consumer_positions'):
                break
            if not ctx.spend('await_consumer_values', len(values)):
                break
            for value in sorted(values, key=lambda item: item.wire):
                for site in ctx.index._consumers[value]:
                    if not ctx.spend('await_consumer_indexed_uses'):
                        break
                    if site.operation != operation or site.use.id in seen:
                        continue
                    seen.add(site.use.id)
                    consumer = ctx.operations[site.operation]
                    if isinstance(ctx.values[site.use.value], StateVersionValue) or not _consumer_role(consumer, site.use.id):
                        continue
                    actual = OwnedUse(site.operation, site.use.id)
                    target = (HostTerminal(site.operation) if consumer.terminator is not None
                        and consumer.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE) else actual)
                    if target not in targets:
                        targets.append(target)
                        binding = bind_target(ctx, source, target, choices)
                        if membership['conditional']:
                            binding = {**answer(False if binding['match'] is False else None,
                                gaps=(*binding.get('gaps', ()), *membership['gaps'])),
                                'guarded_binding': binding}
                        support.append({'actual': target, 'binding': binding})
                    if consumer.callee is not None:
                        # Keep the actual call Use; a return-copy summary does
                        # not inventory that callee's internal consumers.
                        gaps.append('await_consumer_callee_expansion_pending')
    if ctx.budget.truncated:
        gaps.append('await_consumer_inventory_budget')
    from .copy_consumers import consumer_graph
    graph = consumer_graph(ctx, source, choices)
    if graph['inventory']['known_inventory_complete']:
        gaps = [gap for gap in gaps if gap != 'await_consumer_callee_expansion_pending']
    result = {'source': source, 'targets': tuple(targets), 'support': tuple(support),
        'consumer_graph': graph, 'inventory_membership': membership,
        'gaps': tuple(dict.fromkeys(gaps)), 'known_inventory_complete': before is not None
        and not membership['conditional'] and not ctx.budget.truncated
        and 'await_consumer_callee_expansion_pending' not in gaps}
    ctx._await_outcome_consumers[key] = result
    return result


def state_links(ctx, terminal, edge, choices=(), *, outward=False):
    """Exact signature ordinals and locations; never landing-formal positions."""
    from .protocol_await import _result_copy
    operation = ctx.operations[edge.operation]
    completion = operation.terminator.successors[edge.successor_index]
    signature = next(row for row in operation.completions if row.kind is completion.kind)
    actuals = tuple(OwnedUse(terminal.operation, identity)
                    for identity in ctx.operations[terminal.operation].terminator.values)
    rows = []
    for slot, value_type in enumerate(signature.types):
        if value_type.kind is not ValueKind.STATE:
            continue
        if not ctx.spend('await_outcome_state_slots'):
            break
        matches = tuple(use for use in actuals if isinstance(
            value := ctx.values[ctx.owned_use(use.operation, use.use).value], StateVersionValue)
            and value.location == value_type.location)
        post = InvokeLiteralResult(edge, CompletionResult(slot))
        actual = matches[0] if len(matches) == 1 else None
        report = (answer(gaps=('await_terminal_state_unresolved',)) if actual is None else
                  case_binding(ctx, post, actual, choices) if outward else
                  _result_copy(ctx, actual, post, choices))
        rows.append({'slot': slot, 'source': post if outward else actual,
                     'target': actual if outward else post, 'binding': report, 'forwarded': False})
    landing = ctx.blocks[completion.block]
    for position, (argument, formal) in enumerate(zip(completion.arguments, landing.arguments)):
        if type(argument) is CompletionResult:
            continue
        original = ctx.owned_use(operation.id, argument)
        value = ctx.values[original.value]
        if not isinstance(value, StateVersionValue):
            continue
        if not ctx.spend('await_outcome_forwarded_states'):
            break
        matches = tuple(use for use in actuals if isinstance(
            current := ctx.values[ctx.owned_use(use.operation, use.use).value], StateVersionValue)
            and current.location == value.location)
        target = matches[0] if len(matches) == 1 else None
        source = OwnedUse(operation.id, argument)
        binding = (answer(gaps=('await_forwarded_terminal_state_unresolved',)) if target is None else
                   case_binding(ctx, source, target, choices))
        rows.append({'slot': None, 'position': position, 'source': source, 'target': target,
                     'landing_formal': formal, 'binding': binding, 'forwarded': True})
    return tuple(rows)


def inventory(rows, checked, complete, *, cursor=None, **extra):
    total = len(rows) if complete else None
    return {'enumerated_count': len(rows), 'checked_count': checked,
            'pending_count': None if total is None else total - checked,
            'jobs_total': total, 'known_inventory_complete': complete,
            'cursor': cursor, **extra}

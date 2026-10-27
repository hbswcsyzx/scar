"""Original adapter packets and typed cleanup continuations, without aliases."""
from .control import ProtocolValueKind
from .model import OperationResult, ProtocolValue
from .protocols import OwnedUse


def structured_region(ctx, source):
    port = ctx.port(source)
    if port is None or port.operation is None or port.gap is not None:
        return False
    regions = getattr(ctx, '_completion_cleanup_regions', None)
    if regions is None:
        scopes = {interface.scope for interface in ctx.graph.cleanup_interfaces}
        regions = ctx._completion_cleanup_regions = {
            scope.region for scope in ctx.graph.control_scopes
            if scope.id in scopes}
    return ctx.region_of[port.operation] in regions


def packets(ctx, source, choices):
    """A Reference may be a packet component, never the whole packet alias."""
    port = ctx.port(source)
    if port is None:
        return (), ('await_completion_result_unresolved',)
    found, gaps = [], []
    if port.values and all(isinstance(ctx.values[value], ProtocolValue)
            and ctx.values[value].protocol is ProtocolValueKind.EXCEPTION_PACKET for value in port.values):
        return ({'source': source, 'definition': None, 'exception_binding': None},), ()
    for packet in ctx.packets.values():
        if not ctx.spend('await_completion_packet_candidates'):
            gaps.append('await_completion_packet_budget')
            break
        origin = ctx.values[packet.value].origin
        if type(origin) is not OperationResult or ctx.region_of[origin.operation] != ctx.region_of[port.operation]:
            continue
        component = ctx.bind(source, OwnedUse(origin.operation, packet.exception), guard=choices or None)
        if component['match'] is True:
            found.append({'source': origin, 'definition': packet, 'exception_binding': component})
        elif component['match'] is None:
            gaps.append('await_completion_packet_component_unproved')
    if not found:
        gaps.append('await_completion_whole_packet_unproved')
    return tuple(found), tuple(dict.fromkeys(gaps))


def continuation_rows(ctx, source, choices=(), *, candidates=None):
    """Demand-bound same-region receipts for the original known packets."""
    from .protocol_packet_routes import completion_continuations
    from .copy_flow import required_choices, selected
    required, complete = required_choices(ctx, source)
    choices = selected(ctx, ctx._returns.guards, choices, required)
    cache = getattr(ctx, '_completion_adapter_routes', None)
    if cache is None:
        cache = ctx._completion_adapter_routes = {}
    key = source, choices
    if not ctx.spend('completion_adapter_queries'):
        return (), ('completion_adapter_budget',)
    if key in cache:
        return cache[key]
    candidates, gaps = packets(ctx, source, choices) if candidates is None else (candidates, ())
    rows = []
    for candidate in candidates:
        if not ctx.spend('completion_adapter_packets'):
            gaps = (*gaps, 'completion_adapter_budget')
            break
        report = completion_continuations(ctx, candidate['source'], choices=choices,
                                          cross_resume=False)
        rows.append({'packet': candidate, 'start': report.get('start'),
                     'choices': choices, 'continuation': report})
        gaps = (*gaps, *report['gaps'])
    if not complete:
        gaps = (*gaps, 'completion_adapter_prefix_unresolved')
    result = tuple(rows), tuple(dict.fromkeys(gaps))
    if not ctx.budget.truncated:
        cache[key] = result
    return result


def terminal_relation(ctx, source, terminal):
    """Current completion versus original completion are separate obligations.

    None means the ordinary legacy path. An absent feasible terminal is not a
    bad copy. A missing continuation proof is unknown, never an override grant.
    """
    if not hasattr(ctx, 'index') or not structured_region(ctx, source):
        return None
    rows, gaps = continuation_rows(ctx, source)
    found = tuple(receipt for row in rows for receipt in row['continuation']['terminals']
                  if receipt['terminal'] == terminal)
    complete = bool(rows) and all(row['continuation']['known_inventory_complete'] for row in rows)
    if not found:
        return {'applicable': False if complete else None, 'match': None,
                'overridden': None, 'receipts': (), 'gaps': gaps}
    checks = tuple(receipt['binding']['match'] for receipt in found)
    return {'applicable': True, 'match': False if False in checks else
            None if None in checks else True,
            'overridden': all(receipt['current_source'] != receipt['root_source'] for receipt in found),
            'receipts': found, 'gaps': gaps}

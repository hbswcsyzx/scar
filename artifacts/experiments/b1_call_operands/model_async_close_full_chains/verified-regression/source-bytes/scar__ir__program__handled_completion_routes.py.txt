"""Conditional handler completions over original, separately selected routes.

An exception matcher controls a handler; it does not copy the old exception
into a newly constructed one.  This view retains those two obligations rather
than adding aliases or interpreting a constructor's name/native identity.
"""
from .control import ProtocolValueKind
from .copy_flow import required_choices
from .model import (CompletionResult, ExitKind, InvokeLiteralResult,
                    OperationResult, ProtocolValue, ReferenceValue,
                    TerminatorKind)
from .protocols import ContractResult, DriveResult, OutcomeAdapter, OwnedUse
from .structured import ControlEdgeReference


_FLAGS = {'source_runtime_verified': False, 'runtime_identity_verified': False,
          'value_identity_verified': False, 'native_applicability_verified': False,
          'transformation_authorized': False}


def _truncated(ctx):
    return ctx.budget is not None and ctx.budget.truncated


def _unknown(source, *, gaps=(), cursor=None):
    return {'source': source, 'applicable': None, 'match': None, 'receipts': (),
            'gaps': tuple(gaps), 'cursor': cursor, **_FLAGS}


def _indexes(ctx):
    cached = getattr(ctx, '_handled_completion_indexes', None)
    if cached is not None:
        return cached
    matchers, packets, origins = {}, {}, {}
    for row in ctx.graph.exception_matches:
        if not ctx.spend('handled_matcher_inventory'):
            return None
        matchers[row.operation] = row
    for row in ctx.graph.exception_packets:
        if not ctx.spend('handled_packet_inventory'):
            return None
        origin = ctx.values[row.value].origin
        if type(origin) is OperationResult:
            packets.setdefault(origin.operation, []).append(row)
    for row in ctx.graph.protocol_operations:
        if not ctx.spend('handled_adapter_inventory'):
            return None
        if type(row.contract) is OutcomeAdapter and type(row.contract.input) is DriveResult:
            origins.setdefault(row.contract.output, set()).add(row.contract.input.outcome)
    cached = matchers, packets, origins
    ctx._handled_completion_indexes = cached
    return cached


def _ordered(ctx, original, route):
    """Choices select edges; their canonical tuple order is not execution order."""
    cache = getattr(ctx, '_handled_completion_paths', None)
    if cache is None:
        cache = ctx._handled_completion_paths = {}
    key = original['source'], route['choices']
    if key in cache:
        return cache[key]
    if not ctx.spend('handled_route_choices', len(route['choices']) + 1):
        return None
    choices = {edge.operation: edge for edge in route['choices']}
    block_id, seen, rows = original['successor'].block, set(), []
    while block_id not in seen:
        block = ctx.blocks[block_id]
        if not ctx.spend('handled_route_operations', len(block.operations) + 1):
            return None
        seen.add(block_id)
        for identity in block.operations:
            operation = ctx.operations[identity]
            edge = choices.get(identity)
            rows.append((operation, edge))
        operation = rows[-1][0]
        if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            if route['terminal'] is None or operation.id != route['terminal'].operation:
                return None
            result = tuple(rows)
            cache[key] = result
            return result
        edge = choices.get(operation.id)
        if edge is None or not ctx.spend('handled_route_edges'):
            return None
        block_id = operation.terminator.successors[edge.successor_index].block
    return None


def _binding(ctx, source, target, choices, kind):
    if not ctx.spend('handled_bindings'):
        return {'kind': kind, 'source': source, 'target': target,
                'binding': {'match': None, 'routes': (), 'cursor': None,
                            'gaps': ('handled_completion_budget',)}}
    return {'kind': kind, 'source': source, 'target': target,
            'binding': ctx.bind(source, target, guard=choices)}


def _own_ports(ctx, operation, edge):
    successor = operation.terminator.successors[edge.successor_index]
    signature = next(row for row in operation.completions if row.kind is successor.kind)
    if not ctx.spend('handled_constructor_slots', len(signature.types) + len(successor.arguments) + 1):
        return None
    ports = []
    for index, value_type in enumerate(signature.types):
        if getattr(value_type, 'location', None) is not None:
            continue
        if (successor.kind is ExitKind.RAISE and getattr(value_type, 'protocol', None)
                is ProtocolValueKind.EXCEPTION_PACKET or successor.kind is ExitKind.NORMAL
                and getattr(value_type, 'protocol', None) is None):
            port = InvokeLiteralResult(edge, CompletionResult(index))
            info = ctx.port(port)
            if info is not None and info.gap is None and info.values and all(
                    isinstance(ctx.values[value], ReferenceValue) if successor.kind is ExitKind.NORMAL
                    else isinstance(ctx.values[value], ProtocolValue)
                    and ctx.values[value].protocol is ProtocolValueKind.EXCEPTION_PACKET
                    for value in info.values):
                ports.append(port)
    return tuple(ports)


def _route(ctx, source, port, original, route, ordered, indexes):
    matchers, packets, _ = indexes
    choices = route['choices']
    selected = {edge.operation: edge for edge in choices}
    if port.phase == 'edge' and selected.get(port.operation) != ControlEdgeReference(port.operation, port.edge):
        return None  # The other own completion did not produce this source.
    if port.operation == original['drive'].operation:
        start = 0
    else:
        positions = [index for index, (operation, _) in enumerate(ordered) if operation.id == port.operation]
        if len(positions) != 1:
            return None
        start = positions[0] + (port.phase != 'before')
    whole = bool(port.values) and all(isinstance(ctx.values[value], ProtocolValue)
        and ctx.values[value].protocol is ProtocolValueKind.EXCEPTION_PACKET for value in port.values)
    incoming, definition = (source if whole else None), None
    checks, matched, matcher_rows = [], False, []
    current, constructor, own_port, current_packet = None, None, None, None
    normal_candidates, established = (), []
    uncertain, saw_matcher = False, False
    for operation, edge in ordered[start:]:
        if not ctx.spend('handled_route_steps'):
            uncertain = True
            break
        for packet in packets.get(operation.id, ()):
            if not ctx.spend('handled_route_packet_candidates'):
                uncertain = True
                break
            actual = OwnedUse(operation.id, packet.exception)
            if incoming is None:
                binding = _binding(ctx, source, actual, choices, 'SOURCE_PACKET_EXCEPTION')
                if binding['binding']['match'] is True:
                    incoming, definition = ctx.values[packet.value].origin, packet
                    checks.append(binding)
                elif binding['binding']['match'] is None:
                    uncertain = True
            if matched and normal_candidates:
                candidates = []
                for producer, candidate in normal_candidates:
                    binding = _binding(ctx, candidate, actual, choices, 'CONSTRUCTOR_PACKET_EXCEPTION')
                    if binding['binding']['match'] is True:
                        candidates.append((producer, candidate, binding))
                    elif binding['binding']['match'] is None:
                        uncertain = True
                if len(candidates) == 1:
                    producer, candidate, binding = candidates[0]
                    established.append((producer, candidate, packet, binding))
                elif len(candidates) > 1:
                    uncertain = True
        matcher = matchers.get(operation.id)
        if matcher is not None:
            saw_matcher = True
            if matched and (current is not None or established):
                # A nested handler needs its own current-completion receipt;
                # do not compare its new packet to the superseded root.
                uncertain = True
                break
            if incoming is None or matcher.normal_result is None or matcher.branch is None:
                uncertain = True
                continue
            branch = ctx.operations[matcher.branch]
            actual_edge = selected.get(branch.id)
            if actual_edge is None:
                uncertain = True
                continue
            actual = OwnedUse(operation.id, matcher.input_use)
            bound = _binding(ctx, incoming, actual, choices, 'MATCHER_PACKET')
            declared = _binding(ctx, matcher.source, actual, choices, 'MATCHER_DECLARED_SOURCE')
            boolean = _binding(ctx, matcher.normal_result,
                OwnedUse(branch.id, branch.terminator.condition), choices, 'MATCHER_BOOL')
            checks.extend((bound, declared, boolean))
            matcher_rows.append({'matcher': matcher, 'input': actual,
                'source_binding': bound['binding'], 'declared_source_binding': declared['binding'],
                'bool': matcher.normal_result, 'branch': branch,
                'true_edge': ControlEdgeReference(branch.id, 0), 'selected_edge': actual_edge,
                'truth': actual_edge.successor_index == 0, 'bool_binding': boolean['binding']})
            # The original selected true edge must actually precede the new
            # producer. No claim is made about native category correctness.
        if matcher_rows and operation.id == matcher_rows[-1]['branch'].id:
            if matcher_rows[-1]['truth']:
                matched = True
                normal_candidates, established = (), []
            continue
        if matched and operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
            if edge is None:
                uncertain = True
                continue
            ports = _own_ports(ctx, operation, edge)
            if ports is None:
                uncertain = True
                break
            successor = operation.terminator.successors[edge.successor_index]
            if successor.kind is ExitKind.RAISE:
                if len(ports) == 1:
                    constructor, own_port, current_packet = operation, ports[0], None
                    current = own_port
                    normal_candidates, established = (), []
                else:
                    uncertain = True
            else:
                normal_candidates = (*normal_candidates, *((operation, candidate) for candidate in ports))
    if not saw_matcher:
        return None
    if established:
        # Multiple independently built packets are not an instruction to pick
        # whichever one happens to fit the terminal's actual operand.
        if len(established) == 1:
            constructor, own_port, current_packet, binding = established[0]
            current = ctx.values[current_packet.value].origin
            checks.append(binding)
        else:
            uncertain = True
    if not matched:
        current = incoming
    targets = tuple(ctx.terminal_uses(route['terminal']))
    host = None
    if current is not None and len(targets) == 1:
        host = _binding(ctx, current, targets[0], choices, 'HOST_PACKET')
        checks.append(host)
    else:
        uncertain = True
    values = tuple(row['binding']['match'] for row in checks)
    joint = None
    if checks and ctx.spend('handled_joint_bindings', len(checks) + 1):
        joint = ctx.correlate(*(row['binding'] for row in checks))
    joint_match = None if joint is None else joint['match']
    match = (False if False in values or joint_match is False else None
             if uncertain or not values or None in values or joint_match is None else True)
    if matched and constructor is None and match is not False:
        match = None
    return {'source': source, 'choices': choices, 'terminal': route['terminal'],
        'packet_source': incoming, 'packet_definition': definition, 'matchers': tuple(matcher_rows),
        'constructor': constructor, 'own_port': own_port, 'packet': current_packet,
        'current_source': current, 'bindings': tuple(checks),
        'host_binding': None if host is None else host['binding'], 'joint_binding': joint,
        'applicable': True,
        'overridden': matched and constructor is not None, 'match': match,
        'gaps': ('handled_completion_native_interpretation_unproved',
                 *(() if match is not None else ('handled_completion_support_unproved',))),
        'cursor': None, **_FLAGS}


def _analyze(ctx, source):
    from .async_session_sources import source_inventory, source_routes
    cache = getattr(ctx, '_handled_completion_sources', None)
    if cache is None:
        cache = ctx._handled_completion_sources = {}
    key = source, ctx._returns.guards
    if key in cache:
        return cache[key]
    port = ctx.port(source)
    if port is None or port.operation is None or port.gap is not None:
        return (), False, ()
    indexes = _indexes(ctx)
    if indexes is None:
        return (), False, ()
    required, complete = required_choices(ctx, source)
    required = (*ctx._returns.guards, *required)
    origins = indexes[2].get(port.source)
    receipts, inventory = [], []
    for original in source_inventory(ctx):
        if not ctx.spend('handled_original_sources'):
            complete = False
            break
        if ctx.region_of[original['drive'].operation] != ctx.region_of[port.operation]:
            continue
        if type(source) is DriveResult and original['source'] != source.outcome:
            continue
        if origins is not None and original['source'] not in origins:
            continue
        view = source_routes(ctx, original)
        complete &= view['known_inventory_complete']
        for route in view['routes']:
            if not ctx.spend('handled_original_routes'):
                complete = False
                break
            if route['terminal'] is None:
                continue
            try:
                ctx.selected_edges((*required, *route['choices']))
            except ValueError:
                continue  # Incompatible source/constructor N-R alternatives.
            ordered = _ordered(ctx, original, route)
            if ordered is None:
                complete = False
                continue
            if port.operation != original['drive'].operation and not any(
                    operation.id == port.operation for operation, _ in ordered):
                continue
            inventory.append(route['terminal'])
            receipt = _route(ctx, source, port, original, route, ordered, indexes)
            if receipt is not None:
                receipts.append(receipt)
        if _truncated(ctx):
            complete = False
            break
    result = tuple(receipts), bool(complete), tuple(inventory)
    if not _truncated(ctx):
        cache[key] = result
    return result


def handled_terminal_relation(ctx, source, terminal):
    """Return None for a legacy route, or an independently guarded receipt.

    False is a concrete wrong original packet/bool/own completion. Unknown
    native interpretation never becomes an issue, and a cut cannot grant a
    successful replacement. The cache belongs to this context/shared budget.
    """
    if not hasattr(ctx, 'index'):
        return None
    if not ctx.graph.exception_matches:
        return None
    regions = getattr(ctx, '_handled_completion_regions', None)
    if regions is None:
        regions = ctx._handled_completion_regions = frozenset(
            ctx.region_of[row.operation] for row in ctx.graph.exception_matches)
    original = source.result_port if type(source) is ContractResult else source
    operation = (original.outcome.drive if type(original) is DriveResult else
                 original.edge.operation if type(original) is InvokeLiteralResult else
                 original.operation if type(original) in (OperationResult, OwnedUse) else None)
    if operation is None or ctx.region_of.get(operation) not in regions:
        return None
    if not ctx.spend('handled_terminal_queries'):
        return _unknown(source, gaps=('handled_completion_budget',),
            cursor={'phase': 'handled_completion', 'source': source, 'terminal': terminal})
    receipts, complete, inventory = _analyze(ctx, source)
    found = tuple(row for row in receipts if row['terminal'] == terminal)
    if _truncated(ctx):
        if any(row['match'] is False for row in found):
            return {'source': source, 'applicable': True, 'match': False,
                'receipts': found,
                'gaps': tuple(dict.fromkeys(('handled_completion_budget',
                    *(gap for row in found for gap in row['gaps'])))),
                'cursor': {'phase': 'handled_completion', 'source': source,
                           'terminal': terminal, 'unchecked_routes': True}, **_FLAGS}
        return _unknown(source, gaps=('handled_completion_budget',),
            cursor={'phase': 'handled_completion', 'source': source, 'terminal': terminal})
    if not found:
        if terminal not in inventory and complete:
            return {'source': source, 'applicable': False, 'match': None, 'receipts': (),
                    'gaps': (), 'cursor': None, **_FLAGS}
        return None if complete else _unknown(source, gaps=('handled_completion_routes_unproved',))
    checks = tuple(row['match'] for row in found)
    matched_routes = sum(row['terminal'] == terminal for row in receipts)
    original_routes = sum(row == terminal for row in inventory)
    match = False if False in checks else None if not complete or None in checks or matched_routes != original_routes else True
    return {'source': source, 'applicable': True, 'match': match, 'receipts': found,
            'gaps': tuple(dict.fromkeys(gap for row in found for gap in row['gaps'])),
            'cursor': None, **_FLAGS}


def handled_completion(index, source, terminal, *, budget=4096):
    """Public detached view, with one shared budget for all derived work."""
    from copy import deepcopy
    from scar.ir.execution.validity_budget import ValidityBudget
    from .protocol_connection_flow import ConnectionContext
    from .protocols import HostTerminal
    if type(terminal) is not HostTerminal:
        raise TypeError('handled completion requires an exact original HostTerminal')
    terminal.__post_init__()
    accounting = ValidityBudget(budget)
    ctx = ConnectionContext(index.graph, index=index, budget=accounting)
    ctx.port(source)
    ctx.port(terminal)
    result = handled_terminal_relation(ctx, source, terminal)
    if result is None:
        result = _unknown(source, gaps=('handled_completion_receipt_absent',))
    return deepcopy({**result, 'terminal': terminal,
        'budget': {'limit': accounting.limit, 'used': accounting.used,
                   'costs': dict(accounting.costs), 'truncated': accounting.truncated},
        'preparation': dict(ctx.preparation)})


__all__ = ['handled_terminal_relation', 'handled_completion']

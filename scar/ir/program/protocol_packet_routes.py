"""Bounded packet frontiers on original CFG positions and owned operands.

This is a query, not another graph. A successful frontier is only a supplied
model copy relation; in particular C1 packaging is not proof of later dispatch.
"""
from .cleanup import CleanupEnter, CleanupReplace, CleanupResume
from .control import LanguageCompletionKind
from .driver_flow import body_drive_target
from .drivers import BodyResume
from .model import OperationResult, TerminatorKind
from .protocols import HostTerminal, OwnedUse
from .resumption import ResumeSlotKind, SuspendTerminator


def packet_frontiers(ctx, source, *, start, choices=(), cuts=()):
    """Check every reachable next frontier for this exact selected packet.

    ``start`` is an original (BlockID, operation index). Choices belong to one
    static visit only. Re-evaluation, loops and callbacks preserve explicit gaps.
    An inactive pending definition is neither a consumer nor a counterexample.
    """
    choices = ctx.selected_edges(choices)
    selected = {edge.operation: edge.successor_index for edge in choices}
    pending, seen, targets, checks, gaps = [start], set(), [], [], []
    overridden = []
    cursor = None
    origin = ctx.port(source)
    if origin is None or origin.gap is not None:
        gaps.append('packet_route_source_unresolved')
    cuts = set(cuts)
    if origin is not None and origin.phase != 'before':
        cuts.add(origin.operation)
    region = ctx.region_of[ctx.blocks[start[0]].operations[start[1]]]
    rank_cache = getattr(ctx, '_packet_route_ranks', None)
    if rank_cache is None:
        rank_cache = ctx._packet_route_ranks = {}
    if region not in rank_cache:
        _, _, _, _, order = ctx._edges(region)
        rank_cache[region] = {block: number for number, block in enumerate(order)}
    ranks = rank_cache[region]

    def check(target, kind):
        binding = ctx.bind(source, target, choices=choices)
        # May-copy support cannot be promoted to a must proof, or treated as
        # an exact wrong source when separate visits merge in a C1 boundary.
        if binding['match'] is False and ctx.may_forwards(source, target) is True:
            gaps.append('packet_route_guard_correlation_unresolved')
            binding = {**binding, 'match': None,
                       'gaps': (*binding['gaps'], 'packet_route_guard_correlation_unresolved')}
        checks.append({'target': target, 'binding': binding, 'kind': kind})
        targets.append(target)
        if binding['match'] is None:
            gaps.append('packet_route_source_unresolved')
        return binding

    while pending:
        if not ctx.spend('packet_route_positions'):
            cursor = {'phase': 'packet_route_positions', 'remaining_positions': len(pending)}
            gaps.append('packet_route_budget_exhausted')
            break
        block_id, position = pending.pop()
        if (block_id, position) in seen:
            continue
        seen.add((block_id, position))
        block = ctx.blocks[block_id]
        if position >= len(block.operations):
            gaps.append('packet_route_consumer_missing')
            continue
        identity = block.operations[position]
        operation = ctx.operations[identity]
        if identity in cuts:
            gaps.append('packet_route_source_reevaluated')
            continue
        drive = ctx.drives.get(identity)
        if drive is not None:
            if type(drive.target) is not BodyResume:
                gaps.append('packet_route_parent_ingress_unresolved')
                continue
            _, _, successor = body_drive_target(ctx.graph, drive)
            payloads = tuple(actual for actual in drive.resume_inputs
                             if successor.inputs[actual.slot].kind is not ResumeSlotKind.STATE)
            if not payloads:
                gaps.append('packet_route_parent_packet_missing')
            for actual in payloads:
                if successor.inputs[actual.slot].kind not in (
                        ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET):
                    checks.append({'target': OwnedUse(identity, actual.source), 'kind': 'BODY_PACKET',
                                   'binding': {'match': False, 'gaps': ()}})
                else:
                    check(OwnedUse(identity, actual.source), 'BODY_PACKET')
            continue
        action = ctx.index.cleanup_action(identity)
        if type(action) in (CleanupEnter, CleanupReplace, CleanupResume):
            actual = OwnedUse(identity, action.replacement if type(action) is CleanupReplace else action.pending)
            support = []
            uncertain = False
            for definition in ctx.graph.pending_completions:
                if not ctx.spend('packet_route_pending_sources'):
                    gaps.append('packet_route_budget_exhausted')
                    cursor = {'phase': 'packet_route_pending_sources', 'operation': identity}
                    break
                producer = ctx.values[definition.value].origin
                if type(producer) is not OperationResult or ctx.region_of[producer.operation] != region:
                    continue
                token = ctx.bind(producer, actual, choices=choices)
                if token['match'] is not True:
                    uncertain |= token['match'] is None or ctx.may_forwards(producer, actual) is True
                    continue
                port = ctx.index.pending_ports(definition.value)
                support.append({'definition': definition, 'token_binding': token, 'ports': port})
                # Core C1 validation establishes a fresh legal replacement.
                # Its new Return/Raise deliberately supersedes this packet.
                declared = next(item for item in ctx.graph.control_ports if item.id == definition.port)
                if type(action) is CleanupReplace and declared.kind in (
                        LanguageCompletionKind.RETURN, LanguageCompletionKind.RAISE):
                    overridden.append({'action': action, 'definition': definition,
                                       'token_binding': token, 'source_applicability_verified': False})
                    gaps.append('packet_route_override_applicability_unproved')
                elif declared.kind is not LanguageCompletionKind.RAISE or definition.payload is None:
                    checks.append({'target': actual, 'kind': 'C1_PENDING',
                                   'binding': {'match': False, 'gaps': ()}})
                else:
                    check(OwnedUse(producer.operation, definition.payload), 'C1_PENDING')
            targets.append({'action': action, 'actual': actual, 'sources': tuple(support)})
            if uncertain or not support:
                gaps.append('packet_route_pending_source_unresolved')
            # Exact PendingPayload projection / saved-context dispatch belongs
            # to the unchanged X25 closure, not to this frontier query.
            gaps.append('packet_route_pending_continuation_unproved')
            continue
        term = operation.terminator
        if type(term) is SuspendTerminator:
            gaps.append('packet_route_suspend_unresolved')
            continue
        if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            if term.kind is TerminatorKind.RETURN:
                gaps.append('packet_route_return_override_unproved')
            else:
                actuals = ctx.terminal_uses(HostTerminal(identity))
                if not actuals:
                    gaps.append('packet_route_host_packet_missing')
                for target in actuals:
                    check(target, 'HOST_RAISE')
            continue
        if (operation.callee is not None or term is not None and term.kind is TerminatorKind.INVOKE
                or not operation.effects_complete):
            gaps.append('packet_route_intervening_call_unresolved')
            continue
        if term is None:
            pending.append((block_id, position + 1))
        else:
            successors = getattr(term, 'successors', None)
            if successors is None:
                gaps.append('packet_route_structured_continuation_unproved')
                continue
            for number, successor in reversed(tuple(enumerate(successors))):
                if not ctx.spend('packet_route_edges'):
                    gaps.append('packet_route_budget_exhausted')
                    cursor = {'phase': 'packet_route_edges', 'operation': identity, 'edge': number}
                    break
                if identity in selected and selected[identity] != number:
                    continue
                if ranks.get(successor.block, 0) <= ranks.get(block_id, 0):
                    gaps.append('packet_route_cycle_unresolved')
                    if any(item in cuts for item in ctx.blocks[successor.block].operations):
                        gaps.append('packet_route_source_reevaluated')
                    continue
                pending.append((successor.block, 0))
    if not targets and not overridden:
        gaps.append('packet_route_consumer_missing')
    contradicted = any(row['binding']['match'] is False for row in checks)
    return {'status': 'CONTRADICTED' if contradicted else 'PARTIAL' if gaps else
                     'OVERRIDDEN' if overridden else 'DECLARED',
            'source': source, 'targets': tuple(targets), 'checks': tuple(checks),
            'gaps': tuple(dict.fromkeys(gaps)), 'cursor': cursor,
            'overrides': tuple(overridden), 'frontier_only': True,
            'source_runtime_verified': False, 'runtime_identity_verified': False,
            'transformation_authorized': False}


__all__ = ['packet_frontiers']


def _continuation_indexes(ctx):
    cached = getattr(ctx, '_packet_continuation_indexes', None)
    if cached is None:
        cached = ({row.value: row for row in ctx.graph.pending_completions},
                  {row.id: row for row in ctx.graph.control_ports})
        ctx._packet_continuation_indexes = cached
        ctx.preparation['packet_continuation_pending_definitions'] = len(cached[0])
        ctx.preparation['packet_continuation_control_ports'] = len(cached[1])
    return cached


def _continuation_ranks(ctx, region):
    cache = getattr(ctx, '_packet_route_ranks', None)
    if cache is None:
        cache = ctx._packet_route_ranks = {}
    if region not in cache:
        _, _, _, _, order = ctx._edges(region)
        cache[region] = {block: number for number, block in enumerate(order)}
    return cache[region]


def _possible_pending(ctx, region, choices):
    """Reuse the independent carrier/port fixed point, never source support."""
    from .pending_payload_flow import has_pending_region, prepare_pending_payload_flow

    guards = ctx.selected_edges(choices, region=region)
    cache = getattr(ctx, '_pending_payload_flows', {})
    if (region, guards) in cache:
        return cache[region, guards]
    if not has_pending_region(ctx, region) or ctx.selection_ambiguity(guards) is not None:
        return None
    declaration, outgoing, incoming, reached, order = ctx._edges(region)
    if guards:
        sources, targets = {}, {}
        for selected in guards:
            if not ctx.spend('packet_continuation_guard_choices'):
                return None
            operation = ctx.operations[selected.operation]
            target = operation.terminator.successors[selected.successor_index].block
            sources[operation.id] = selected.successor_index
            targets[target] = operation.id, selected.successor_index
        filtered = {}
        for block, edges in outgoing.items():
            kept = []
            for edge in edges:
                if not ctx.spend('packet_continuation_guard_edges'):
                    return None
                if ((edge[0] not in sources or sources[edge[0]] == edge[1])
                        and (edge[2] not in targets or targets[edge[2]] == (edge[0], edge[1]))):
                    kept.append(edge)
            filtered[block] = kept
        outgoing = filtered
        incoming = {block: [] for block in incoming}
        for block, edges in outgoing.items():
            for edge in edges:
                incoming[edge[2]].append((block, edge))
        pending, reachable = [declaration.entry], set()
        while pending:
            if not ctx.spend('packet_continuation_guard_reachability'):
                return None
            block = pending.pop()
            if block not in reachable:
                reachable.add(block)
                pending.extend(edge[2] for edge in outgoing[block])
        reached = frozenset(reachable)
        order = tuple(block for block in order if block in reached)
    return prepare_pending_payload_flow(ctx, region, outgoing, incoming, order, guards)


def _active_pending(ctx, action, choices, possible):
    """Inventory constructors of this actual token, including unresolved routes."""
    definitions, ports = _continuation_indexes(ctx)
    actual = OwnedUse(action.operation,
                      action.replacement if type(action) is CleanupReplace else action.pending)
    report = ctx.origins(actual, guard=choices or None)
    selected = ctx.owned_use(actual.operation, actual.use).value
    pairs = None if possible is None else possible.before.get(action.operation)
    sources, gaps = [], []
    complete = report['source_inventory_complete']
    if not complete:
        gaps.append('packet_continuation_pending_origin_inventory_unresolved')
    for recipe in report['recipes']:
        if not ctx.spend('packet_continuation_pending_sources'):
            complete = False
            break
        definition = definitions.get(recipe['leaf'].id)
        origin = recipe['leaf'].origin
        if (recipe['kind'] != 'OPERATION_RESULT' or definition is None
                or type(origin) is not OperationResult):
            complete = False
            gaps.append('packet_continuation_pending_source_unresolved')
            continue
        if pairs is not None and (selected, definition.port) not in pairs:
            continue
        payload = (None if definition.payload is None
                   else OwnedUse(origin.operation, definition.payload))
        local = list(choices)
        for step in recipe['path']:
            if not ctx.spend('packet_continuation_pending_context_steps'):
                complete = False
                break
            if step.get('kind') == 'CFG_COPY':
                from .structured import ControlEdgeReference
                local.append(ControlEdgeReference(step['operation'].id, step['successor_index']))
        try:
            local = ctx.selected_edges(tuple(local))
            if ctx.selection_ambiguity(local) is not None:
                raise ValueError('separate pending-token visits cannot be one selected context')
            token = ctx.bind(origin, actual, choices=local)
        except ValueError:
            local = choices
            token = {'match': None, 'gaps': ('packet_continuation_pending_context_unresolved',)}
        sources.append({'definition': definition, 'constructor': ctx.operations[origin.operation],
                        'payload': payload, 'port': ports[definition.port],
                        'token_binding': token, 'choices': local,
                        'token_path': recipe['path']})
    if not sources:
        complete = False
        gaps.append('packet_continuation_pending_source_unresolved')
    return actual, tuple(sources), complete, tuple(gaps)


def _callee_scope(ctx, callee, choices):
    """Bounded original reachable effects inventory, separate from copy proof."""
    from .cleanup import CleanupRouteTerminator
    from .control import PendingDispatchTerminator

    cache = getattr(ctx, '_packet_callee_scopes', None)
    if cache is None:
        cache = ctx._packet_callee_scopes = {}
    key = callee, choices
    if key in cache:
        return cache[key]
    if not ctx.spend('packet_continuation_callee_choices', len(choices) + 1):
        return {'known_inventory_complete': False, 'boundaries': (),
                'gaps': ('packet_continuation_budget_exhausted',), 'conditions': ()}
    selected = {edge.operation: edge.successor_index for edge in choices}
    targets = {ctx.operations[edge.operation].terminator.successors[edge.successor_index].block:
               (edge.operation, edge.successor_index) for edge in choices}
    pending = [(callee, ctx.regions[callee].entry, (callee,))]
    seen, boundaries, gaps, conditions = set(), [], [], []
    terminals = 0
    while pending:
        region, block_id, ancestors = pending.pop()
        if (region, block_id) in seen:
            continue
        seen.add((region, block_id))
        block = ctx.blocks[block_id]
        ranks = _continuation_ranks(ctx, region)
        stopped = False
        for identity in block.operations:
            if not ctx.spend('packet_continuation_callee_positions'):
                stopped = True
                break
            operation = ctx.operations[identity]
            term = operation.terminator
            kind = None
            if operation.callee is not None:
                if not ctx.spend('packet_continuation_callee_frames', len(ancestors) + 1):
                    stopped = True
                    break
                if operation.callee in ancestors:
                    kind = 'RECURSIVE_CALL'
                else:
                    pending.append((operation.callee, ctx.regions[operation.callee].entry,
                                    (*ancestors, operation.callee)))
            elif term is not None and term.kind is TerminatorKind.INVOKE:
                kind = 'UNKNOWN_CALL'
            elif identity in ctx.drives:
                kind = 'BODY_DRIVE'
            elif type(ctx.index.cleanup_action(identity)) in (CleanupEnter, CleanupReplace, CleanupResume):
                conditions.append('callee typed C1 preserves unknown callbacks and current state ports')
            elif type(term) is SuspendTerminator:
                conditions.append('callee resume successors are conditional declarations')
            elif (type(term) in (CleanupRouteTerminator, PendingDispatchTerminator)
                    or term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)):
                pass
            elif not operation.effects_complete:
                kind = 'OPAQUE_OPERATION'
            if kind is not None:
                boundaries.append({'operation': operation, 'kind': kind,
                                   'position': (block_id, ctx.positions[identity])})
                gaps.append('packet_continuation_callee_boundary_unresolved')
                stopped = True
                break
        if stopped or ctx.budget.truncated:
            if ctx.budget.truncated:
                break
            continue
        operation = ctx.operations[block.operations[-1]]
        term = operation.terminator
        if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            terminals += 1
            continue
        possible = (_possible_pending(ctx, region, choices)
                    if type(term) in (CleanupRouteTerminator, PendingDispatchTerminator) else None)
        if type(term) in (CleanupRouteTerminator, PendingDispatchTerminator) and possible is None:
            boundaries.append({'operation': operation, 'kind': 'PENDING_POSSIBILITY',
                               'position': (block_id, ctx.positions[operation.id])})
            gaps.append('packet_continuation_callee_pending_unresolved')
            continue
        for number, edge in enumerate(getattr(term, 'successors', ())):
            if not ctx.spend('packet_continuation_callee_edges'):
                break
            if ((operation.id in selected and selected[operation.id] != number)
                    or edge.block in targets and targets[edge.block] != (operation.id, number)):
                continue
            if possible is not None and possible.edges.get((operation.id, number)) is None:
                continue
            if ranks.get(edge.block, 0) <= ranks.get(block_id, 0):
                boundaries.append({'operation': operation, 'kind': 'CYCLE',
                                   'position': (block_id, ctx.positions[operation.id])})
                gaps.append('packet_continuation_callee_cycle_unresolved')
                continue
            pending.append((region, edge.block, ancestors))
    if not terminals:
        gaps.append('packet_continuation_callee_terminal_missing')
    result = {'known_inventory_complete': not gaps and not ctx.budget.truncated,
              'boundaries': tuple(boundaries), 'gaps': tuple(dict.fromkeys(gaps)),
              'conditions': tuple(dict.fromkeys(conditions))}
    cache[key] = result
    return result


def _known_call_outputs(ctx, source, operation, choices):
    """Try the existing exact known-callee must summary, without new aliases."""
    from .model import CompletionResult, ExitKind, ProtocolValue, ReferenceValue, StateVersionValue
    from .protocol_flow import ProtocolPort

    if operation.callee is None:
        return None
    invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
    actuals = operation.invoke_arguments if invoke else operation.call_arguments
    entry = ctx.blocks[ctx.regions[operation.callee].entry]
    seeds, inputs = [], []
    for actual, formal in zip(actuals, entry.arguments):
        if not ctx.spend('packet_continuation_call_inputs'):
            return None
        value = ctx.values[ctx.owned_use(operation.id, actual).value]
        if not isinstance(value, (ProtocolValue, ReferenceValue)):
            continue
        target = OwnedUse(operation.id, actual)
        binding = ctx.bind(source, target, choices=choices)
        inputs.append({'target': target, 'binding': binding})
        if binding['match'] is True:
            seeds.append(formal)
    if not seeds:
        return None
    source_port = ProtocolPort(None, entry.operations[0], tuple(seeds), 'before')
    local_guards = ctx.selected_edges(choices, region=operation.callee)
    if local_guards and len(ctx._returns.callers.get(operation.callee, ())) != 1:
        return None
    previous = ctx._returns.guards
    ctx._returns.guards = choices
    try:
        before = ctx._fresh_copies(source_port, guard=local_guards or None)
        summary = None if before is None else ctx._returns.project(operation.callee, before)
    finally:
        ctx._returns.guards = previous
    if summary is None:
        return None
    selected = {edge.operation: edge.successor_index for edge in choices}
    outputs = []
    if invoke:
        for number, edge in enumerate(operation.terminator.successors):
            if not ctx.spend('packet_continuation_call_outputs', len(edge.arguments) + 1):
                return None
            if operation.id in selected and selected[operation.id] != number:
                continue
            statuses = [summary.get((edge.kind, actual.index))
                for actual, formal in zip(edge.arguments, ctx.blocks[edge.block].arguments)
                if type(actual) is CompletionResult and not isinstance(ctx.values[formal], StateVersionValue)]
            outputs.append({'edge': number, 'copied': bool(statuses) and all(value is True for value in statuses)})
    else:
        if not ctx.spend('packet_continuation_call_outputs', len(operation.results) + 1):
            return None
        statuses = [summary.get((ExitKind.NORMAL, number)) for number, identity in enumerate(operation.results)
                    if not isinstance(ctx.values[identity], StateVersionValue)]
        outputs.append({'edge': None, 'copied': bool(statuses) and all(value is True for value in statuses)})
    scope = _callee_scope(ctx, operation.callee, choices)
    return {'operation': operation, 'inputs': tuple(inputs), 'summary': summary,
            'outputs': tuple(outputs), 'scope': scope}


def packet_continuations(ctx, source, *, start, choices=(), cuts=()):
    """Follow complete supplied-CFG packet obligations beyond a C1 frontier.

    Every expected source remains independent. Pending possibility filters only
    impossible control ports; must-copy is checked at actual consumers. A later
    explicit replacement is recorded separately from preservation of the first
    delivery. Conditional resume edges are not observed dynamic executions.
    """
    from .cleanup import CleanupRouteTerminator
    from .control import PendingDispatchTerminator, PendingPayload
    choices = ctx.selected_edges(choices)
    pending = [(start[0], start[1], source, 'packet', False, None, choices)]
    seen, targets, checks, actions, projections = set(), [], [], [], []
    suspensions, overrides, boundaries, helpers, gaps = [], [], [], [], []
    conditions = ['supplied canonical CFG and original state/context ports only',
                  'source/native applicability and dynamic execution remain unproved']
    complete, cursor = True, None
    cuts = set(cuts)
    origin = ctx.port(source)
    if origin is None or origin.gap is not None:
        gaps.append('packet_continuation_source_unresolved')
    elif origin.phase != 'before':
        cuts.add(origin.operation)
    region = ctx.region_of[ctx.blocks[start[0]].operations[start[1]]]
    ranks = _continuation_ranks(ctx, region)
    contexts = {}

    def boundary(operation, kind, expected, position):
        nonlocal complete
        complete = False
        boundaries.append({'operation': operation, 'kind': kind,
                           'source': expected, 'position': position})

    def check(expected, target, kind):
        binding = ctx.bind(expected, target, choices=route_choices)
        row = {'source': expected, 'target': target, 'kind': kind, 'binding': binding}
        checks.append(row)
        if binding['match'] is None:
            gaps.append('packet_continuation_source_unresolved')
        return binding

    def follow(operation, number, edge, expected, role, delivered, active_port):
        nonlocal complete
        if not ctx.spend('packet_continuation_edges'):
            return False
        if ((operation.id in selected and selected[operation.id] != number)
                or edge.block in guard_targets
                and guard_targets[edge.block] != (operation.id, number)):
            return True
        if ranks.get(edge.block, 0) <= ranks.get(ctx.block_of[operation.id], 0):
            gaps.append('packet_continuation_cycle_unresolved')
            if any(identity in cuts for identity in ctx.blocks[edge.block].operations):
                gaps.append('packet_continuation_source_reevaluated')
            boundary(operation, 'CYCLE', expected, (ctx.block_of[operation.id], ctx.positions[operation.id]))
            return True
        pending.append((edge.block, 0, expected, role, delivered, active_port, route_choices))
        return True

    while pending:
        if not ctx.spend('packet_continuation_positions'):
            break
        block_id, position, expected, role, delivered, active_port, route_choices = pending.pop()
        key = block_id, position, expected, role, delivered, active_port, route_choices
        if key in seen:
            continue
        seen.add(key)
        block = ctx.blocks[block_id]
        if position >= len(block.operations):
            complete = False
            gaps.append('packet_continuation_consumer_missing')
            continue
        identity = block.operations[position]
        operation = ctx.operations[identity]
        term = operation.terminator
        if route_choices not in contexts:
            if not ctx.spend('packet_continuation_context_choices', len(route_choices) + 1):
                break
            contexts[route_choices] = (
                {edge.operation: edge.successor_index for edge in route_choices},
                {ctx.operations[edge.operation].terminator.successors[edge.successor_index].block:
                 (edge.operation, edge.successor_index) for edge in route_choices})
        selected, guard_targets = contexts[route_choices]
        if identity in cuts:
            gaps.append('packet_continuation_source_reevaluated')
            boundary(operation, 'SOURCE_REEVALUATED', expected, (block_id, position))
            continue
        drive = ctx.drives.get(identity)
        if drive is not None:
            if type(drive.target) is not BodyResume:
                gaps.append('packet_continuation_parent_ingress_unresolved')
                boundary(operation, 'PARENT_START', expected, (block_id, position))
                continue
            _, _, successor = body_drive_target(ctx.graph, drive)
            actuals = tuple(actual for actual in drive.resume_inputs
                            if successor.inputs[actual.slot].kind is not ResumeSlotKind.STATE)
            if not actuals:
                gaps.append('packet_continuation_parent_packet_missing')
                complete = False
            for actual in actuals:
                target = OwnedUse(identity, actual.source)
                kind = successor.inputs[actual.slot].kind
                if role == 'packet' and kind not in (ResumeSlotKind.THROWN_PACKET, ResumeSlotKind.DELEGATE_PACKET):
                    checks.append({'source': expected, 'target': target, 'kind': 'BODY_PACKET',
                                   'binding': {'match': False, 'gaps': ()}})
                else:
                    check(expected, target, 'BODY_PACKET')
                targets.append(target)
            continue
        action = ctx.index.cleanup_action(identity)
        if type(action) in (CleanupEnter, CleanupReplace, CleanupResume):
            possible = _possible_pending(ctx, region, route_choices)
            actual, sources, known, missing = _active_pending(ctx, action, route_choices, possible)
            complete &= known
            gaps.extend(missing)
            conditions.append('typed C1 callbacks retain their original unknown effects and current post-state')
            record = {'action': action, 'actual': actual, 'sources': sources,
                      'active_port': active_port}
            actions.append(record)
            next_sources = []
            for candidate in sources:
                declared, payload = candidate['port'], candidate['payload']
                if (active_port is not None and type(action) is not CleanupReplace
                        and declared.id != active_port):
                    continue
                token_current = candidate['token_binding']['match'] is True
                if not token_current:
                    gaps.append('packet_continuation_pending_token_currentness_unresolved')
                    checks.append({'source': expected, 'target': payload or actual,
                                   'kind': 'C1_PENDING', 'binding': {
                                       'match': None, 'gaps': ('packet_continuation_pending_token_currentness_unresolved',)}})
                    boundary(operation, 'PENDING_TOKEN_CONTEXT', expected, (block_id, position))
                    continue
                candidate_choices = candidate['choices']
                packet = None
                if payload is not None and ((role == 'packet' and declared.kind is LanguageCompletionKind.RAISE)
                        or (role == 'reference' and declared.kind is LanguageCompletionKind.RETURN)):
                    packet = ctx.bind(expected, payload, choices=candidate_choices)
                match = None if packet is None else packet['match']
                candidate['packet_match'] = match
                if match is not True and delivered and type(action) is CleanupReplace:
                    if payload is not None and declared.kind in (LanguageCompletionKind.RETURN, LanguageCompletionKind.RAISE):
                        override = {'action': action, 'definition': candidate['definition'],
                                    'source': payload, 'previous_source': expected,
                                    'token_binding': candidate['token_binding'],
                                    'source_applicability_verified': False}
                        overrides.append(override)
                        gaps.append('packet_continuation_override_applicability_unproved')
                        next_sources.append((payload, 'packet' if declared.kind is LanguageCompletionKind.RAISE
                                             else 'reference', True, declared.id, candidate_choices))
                        continue
                if packet is None:
                    if declared.kind not in (LanguageCompletionKind.RETURN, LanguageCompletionKind.RAISE):
                        gaps.append('packet_continuation_control_override_unproved')
                        complete = False
                        continue
                    checks.append({'source': expected, 'target': payload or actual, 'kind': 'C1_PENDING',
                                   'binding': {'match': False, 'gaps': ()}})
                else:
                    checks.append({'source': expected, 'target': payload, 'kind': 'C1_PENDING',
                                   'binding': {**packet, 'match': match}})
                    if match is None:
                        gaps.append('packet_continuation_source_unresolved')
                next_sources.append((expected, role, delivered or match is True, declared.id, candidate_choices))
            for following in dict.fromkeys(next_sources):
                pending.append((block_id, position + 1, *following))
            continue
        if type(term) in (CleanupRouteTerminator, PendingDispatchTerminator):
            possible = _possible_pending(ctx, region, route_choices)
            if possible is None:
                gaps.append('packet_continuation_pending_possibility_unresolved')
                boundary(operation, 'PENDING_POSSIBILITY', expected, (block_id, position))
                continue
            followed = False
            for number, edge in enumerate(term.successors):
                if not ctx.spend('packet_continuation_port_cases'):
                    break
                if possible.edges.get((identity, number)) is None:
                    continue
                if active_port is not None and edge.port != active_port:
                    continue
                if identity in selected and selected[identity] != number:
                    continue
                followed = True
                for ordinal, (argument, formal) in enumerate(zip(edge.arguments, ctx.blocks[edge.block].arguments)):
                    if type(argument) is PendingPayload:
                        projections.append({'operation': operation, 'successor_index': number,
                            'argument_index': ordinal, 'selector': OwnedUse(identity, term.pending),
                            'port': edge.port, 'formal': ctx.values[formal]})
                following_port = None if type(term) is PendingDispatchTerminator else active_port
                if not follow(operation, number, edge, expected, role, delivered, following_port):
                    break
            if not followed and not ctx.budget.truncated:
                gaps.append('packet_continuation_selected_port_missing')
                complete = False
            continue
        if type(term) is SuspendTerminator:
            conditions.append('resume successors are declared conditional routes, not observed drives')
            suspensions.append({'operation': operation, 'saved': term.saved,
                                'handoff': term.handoff, 'successors': term.successors})
            if not term.successors:
                gaps.append('packet_continuation_resume_missing')
                complete = False
            for number, edge in enumerate(term.successors):
                if not follow(operation, number, edge, expected, role, delivered, active_port):
                    break
            continue
        if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            actuals = ctx.terminal_uses(HostTerminal(identity))
            required = TerminatorKind.RAISE if role == 'packet' else TerminatorKind.RETURN
            if not actuals:
                gaps.append('packet_continuation_host_payload_missing')
                complete = False
            for target in actuals:
                if term.kind is not required:
                    checks.append({'source': expected, 'target': target, 'kind': 'HOST_TERMINAL',
                                   'binding': {'match': False, 'gaps': ()}})
                else:
                    check(expected, target, 'HOST_RAISE' if role == 'packet' else 'HOST_RETURN')
                targets.append(target)
            continue
        if operation.callee is not None or term is not None and term.kind is TerminatorKind.INVOKE:
            summary = _known_call_outputs(ctx, expected, operation, route_choices)
            if summary is None:
                gaps.append('packet_continuation_intervening_call_unresolved')
                boundary(operation, 'UNKNOWN_CALL', expected, (block_id, position))
                continue
            helpers.append(summary)
            scope = summary['scope']
            conditions.extend(scope['conditions'])
            if not scope['known_inventory_complete']:
                gaps.extend(scope['gaps'])
                boundaries.extend({**item, 'source': expected} for item in scope['boundaries'])
                boundary(operation, 'UNKNOWN_CALL', expected, (block_id, position))
                continue
            for output in summary['outputs']:
                if not output['copied']:
                    gaps.append('packet_continuation_call_result_unresolved')
                    boundary(operation, 'CALL_RESULT', expected, (block_id, position))
                elif output['edge'] is None:
                    pending.append((block_id, position + 1, expected, role, delivered, active_port, route_choices))
                else:
                    number = output['edge']
                    follow(operation, number, term.successors[number], expected, role, delivered, active_port)
            continue
        if not operation.effects_complete:
            gaps.append('packet_continuation_intervening_effects_unresolved')
            boundary(operation, 'OPAQUE_OPERATION', expected, (block_id, position))
            continue
        if term is None:
            pending.append((block_id, position + 1, expected, role, delivered, active_port, route_choices))
        else:
            successors = getattr(term, 'successors', None)
            if successors is None:
                gaps.append('packet_continuation_structured_route_unresolved')
                boundary(operation, 'STRUCTURED_ROUTE', expected, (block_id, position))
                continue
            for number, edge in enumerate(successors):
                if not follow(operation, number, edge, expected, role, delivered, active_port):
                    break
    if ctx.budget.truncated:
        complete = False
        gaps.append('packet_continuation_budget_exhausted')
        cursor = {'phase': 'packet_continuation', 'remaining_positions': len(pending),
                  'operation': identity if 'identity' in locals() else None}
    if not targets:
        gaps.append('packet_continuation_consumer_missing')
        complete = False
    contradicted = any(row['binding']['match'] is False for row in checks)
    return {'status': 'CONTRADICTED' if contradicted else 'PARTIAL' if gaps or not complete else 'DECLARED',
            'source': source, 'targets': tuple(dict.fromkeys(targets)), 'checks': tuple(checks),
            'actions': tuple(actions), 'projections': tuple(projections),
            'suspensions': tuple(suspensions), 'overrides': tuple(overrides),
            'boundaries': tuple(boundaries), 'helpers': tuple(helpers),
            'gaps': tuple(dict.fromkeys(gaps)), 'cursor': cursor,
            'conditions': tuple(dict.fromkeys(conditions)), 'known_inventory_complete': complete,
            'source_inventory_complete': False, 'frontier_only': False,
            'source_runtime_verified': False, 'runtime_identity_verified': False,
            'native_applicability_verified': False,
            'transformation_authorized': False}

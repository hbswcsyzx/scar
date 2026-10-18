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

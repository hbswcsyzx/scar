"""Project a completion onto one captured activation's actual continuation.

The cursor follows original CFG positions and actual transfers, not a second
possible-path solver. Pending payloads and copy ancestry use the shared original
recipe query. No sibling activation or unobserved resume is a continuation.
"""
from copy import deepcopy

from scar.ir.program.control import PendingDispatchTerminator, PendingPayload, ProtocolValueKind
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.model import ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.protocols import HostTerminal, OwnedUse

from .await_links import _flags
from .await_outcome_evidence import pair, status
from .common import Unresolved
from .coordinates import ResumeIngress
from .pending_payloads import projection
from .resumable_flow import value_for_use


def _ownership(ctx, source, anchor, shared, parents):
    """Exact ordinary call ancestry to this anchor, never code/time matching."""
    if ctx.value_activation(source.id) == ctx.activation_of(anchor.id):
        # An INVOKE's selected result belongs to its caller activation. This
        # does not establish anything about an unobserved callee or its inputs.
        from scar.ir.program.model import CompletionResult, value_type
        operation = ctx.core_operations[anchor.operation]
        transfer = ctx.outgoing.get(anchor.id)
        if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE \
                or transfer is None or source.origin != transfer.target:
            return None
        edge = operation.terminator.successors[transfer.successor_index]
        landing = ctx.blocks[ctx.visits[transfer.target].block]
        if not shared.spend('completion_source_result_slots',
                            len(edge.arguments) + len(operation.completions) + 1):
            return None
        signature = next(row for row in operation.completions if row.kind is edge.kind)
        return True if any(type(actual) is CompletionResult and formal == source.value
            and signature.types[actual.index] == value_type(ctx.core_values[source.value])
            for actual, formal in zip(edge.arguments, landing.arguments)) else None
    links = ctx.call_activations_by_caller.get(anchor.id, ())
    if not shared.spend('completion_source_anchor_links', len(links) + 1):
        return None
    if len(links) != 1:
        return None
    link = ctx.resolved_call_activations[links[0]]
    if link['entry'] is None or link['completion'] is None:
        return None
    expected = link['activation'].id
    cursor, seen = ctx.value_activation(source.id), set()
    while cursor not in seen:
        if not shared.spend('completion_source_call_ancestry'):
            return None
        if cursor == expected:
            return True
        seen.add(cursor)
        ancestors = parents.get(cursor, ())
        if len(ancestors) != 1:
            return None
        parent = ancestors[0]
        if parent['entry'] is None or parent['completion'] is None:
            return None
        cursor = ctx.activation_of(parent['association'].caller)
    return None


def completion_continuations(ctx, source_id, anchor_id, *, cross_resume, shared):
    if type(cross_resume) is not bool:
        raise TypeError('cross_resume must be an exact bool')
    source, anchor = ctx.values[source_id], ctx.occurrences[anchor_id]
    activation = ctx.activation_of(anchor.id)
    # These are raw foreign-key indexes only. Every derived join is paid below.
    parents = {}
    for link in ctx.resolved_call_activations.values():
        if link['activation'] is not None:
            parents.setdefault(link['activation'].id, []).append(link)
    segment_drives = {}
    for drive in ctx.resolved_body_drives.values():
        if drive['entry'] is not None:
            segment_drives.setdefault(ctx.visits[drive['entry'].id].segment, []).append(drive)
    sites = ctx.session_occurrences_by_visit_site
    preparation = {'call_associations_indexed': len(ctx.resolved_call_activations),
                   'drive_associations_indexed': len(ctx.resolved_body_drives),
                   'occurrence_index_reused': len(sites), 'derived_paths_precomputed': 0}
    source_definition = ctx.core_values[source.value]
    supported = (isinstance(source_definition, ReferenceValue) or
        isinstance(source_definition, ProtocolValue)
        and source_definition.protocol is ProtocolValueKind.EXCEPTION_PACKET)
    owned = _ownership(ctx, source, anchor, shared, parents) if supported else None
    gaps = [] if owned is True else ['completion_source_anchor_association_unproved']
    boundaries, terminals, projections, segments, transfers, drives = [], [], [], [], [], []
    body = ctx.activations[activation].region in {row.region for row in ctx.program.resumable_bodies}
    current, crossed, cursor = source, False, None
    visit = ctx.visits[anchor.visit]
    position = ctx.blocks[visit.block].operations.index(anchor.operation) + 1
    seen, stopped = set(), not supported
    if not supported:
        boundaries.append({'kind': 'UNSUPPORTED_SOURCE', 'operation': anchor,
            'root_source': source, 'current_source': source, 'crossed_suspend': False})
        gaps.append('completion_actual_source_kind_unsupported')
    typed = {row.operation for name in ('cleanup_enters', 'cleanup_resumes',
        'cleanup_replacements', 'frame_context_initials', 'frame_context_attaches',
        'frame_context_detaches') for row in getattr(ctx.program, name)}
    typed.update(ctx.core_values[row.value].origin.operation for row in ctx.program.pending_completions)

    def boundary(kind, occurrence, gap):
        boundaries.append({'kind': kind, 'operation': occurrence, 'root_source': source,
            'current_source': current, 'crossed_suspend': crossed})
        gaps.append(gap)

    while not stopped and not shared.truncated:
        if not shared.spend('completion_actual_visits'):
            break
        state = visit.id, position
        if state in seen:
            boundary('CYCLE', None, 'completion_actual_cycle')
            break
        seen.add(state)
        segment = ctx.segments[visit.segment]
        if not segments or segments[-1].id != segment.id:
            segments.append(segment)
            candidates = segment_drives.get(segment.id, ()) if body else ()
            if body and (not shared.spend('completion_actual_segment_drives', len(candidates) + 1)
                    or len(candidates) != 1 or candidates[0]['association'] is None):
                boundary('MISSING_DRIVE', None, 'completion_actual_segment_drive_unproved')
                break
            segment_drive = candidates[0] if body else None
            if segment_drive is not None:
                drives.append(segment_drive['association'])
        block = ctx.blocks[visit.block]
        for site in block.operations[position:]:
            if not shared.spend('completion_actual_operations'):
                stopped = True
                break
            canonical, occurrence = ctx.core_operations[site], sites.get((visit.id, site))
            if occurrence is None:
                boundary('MISSING_OCCURRENCE', None, 'completion_actual_occurrence_missing')
                stopped = True
                break
            if site == anchor.operation:
                boundary('SOURCE_REEVALUATED', occurrence, 'completion_actual_source_reevaluated')
                stopped = True
                break
            term = canonical.terminator
            if (segment_drive is not None and term is not None and term.kind in (
                    TerminatorKind.RETURN, TerminatorKind.RAISE, TerminatorKind.SUSPEND)
                    and (segment_drive['outcome'] is None
                         or segment_drive['outcome'].id != occurrence.id)):
                boundary('MISSING_DRIVE_OUTCOME', occurrence, 'completion_actual_drive_outcome_unproved')
                stopped = True
                break
            if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                actuals = tuple(OwnedUse(site, use.id) for use in canonical.uses
                    if use.id in term.values and not isinstance(ctx.core_values[use.value], StateVersionValue))
                if not actuals:
                    boundary('MISSING_PAYLOAD', occurrence, 'completion_actual_terminal_payload_missing')
                for actual in actuals:
                    if not shared.spend('completion_actual_terminals'):
                        break
                    use = ctx.uses.get((occurrence.id, actual.use))
                    value = value_for_use(ctx, use)
                    binding, root = pair(ctx, current, value, shared), pair(ctx, source, value, shared)
                    definition = ctx.core_values[current.value]
                    role = ('reference' if isinstance(definition, ReferenceValue) else 'packet'
                        if isinstance(definition, ProtocolValue)
                        and definition.protocol is ProtocolValueKind.EXCEPTION_PACKET else 'unknown')
                    expected = TerminatorKind.RETURN if role == 'reference' else TerminatorKind.RAISE
                    local = [*binding['gaps']]
                    if role == 'unknown':
                        local.append('completion_actual_source_kind_unresolved')
                    elif term.kind is not expected:
                        binding = {**binding, 'match': False,
                            'gaps': (*binding['gaps'], 'completion_actual_terminal_kind_conflict')}
                        local.append('completion_actual_terminal_kind_conflict')
                    if owned is not True:
                        root = {**root, 'candidate_match': root['match'], 'match': None,
                            'gaps': (*root['gaps'], 'completion_source_anchor_association_unproved')}
                    local.extend(root['gaps'])
                    gaps.extend(local)
                    terminals.append({'terminal': HostTerminal(site), 'actual': actual,
                        'operation': occurrence, 'use': use, 'value': value, 'role': role,
                        'root_source': source, 'current_source': current, 'binding': binding,
                        'root_binding': root, 'root_preserved': root['match'],
                        'crossed_suspend': crossed, 'gaps': tuple(dict.fromkeys(local)),
                        'status': status(gaps=local, bindings=(binding,)), **_flags()})
                stopped = True
                break
            if term is not None and term.kind is TerminatorKind.SUSPEND and not cross_resume:
                boundary('SUSPENSION', occurrence, 'completion_actual_suspension_boundary')
                stopped = True
                break
            if site in ctx.body_drives:
                boundary('NEXT_DRIVE', occurrence, 'completion_actual_next_drive_boundary')
                stopped = True
                break
            if canonical.callee is not None or term is not None and term.kind is TerminatorKind.INVOKE:
                boundary('CALL_BOUNDARY', occurrence, 'completion_actual_intervening_call_unresolved')
                stopped = True
                break
            structural = site in typed or type(term) in (CleanupRouteTerminator, PendingDispatchTerminator)
            if not structural and not canonical.effects_complete:
                boundary('OPAQUE_OPERATION', occurrence, 'completion_actual_effects_unresolved')
                stopped = True
                break
        if stopped or shared.truncated:
            break
        last = sites.get((visit.id, block.operations[-1]))
        term = ctx.core_operations[block.operations[-1]].terminator
        transfer = None if last is None else ctx.outgoing.get(last.id)
        if transfer is None or not shared.spend('completion_actual_transfers'):
            boundary('MISSING_TRANSFER', last, 'completion_actual_transfer_missing')
            break
        following = ctx.visits[transfer.target]
        next_segment = ctx.segments[following.segment]
        if next_segment.activation != activation:
            boundary('ACTIVATION_BOUNDARY', last, 'completion_actual_activation_conflict')
            break
        if term is not None and term.kind is TerminatorKind.SUSPEND:
            ingress = next_segment.ingress
            if (next_segment.id == segment.id or type(ingress) is not ResumeIngress
                    or ingress.suspension != last.id
                    or ingress.successor_index != transfer.successor_index):
                boundary('MISSING_RESUME', last, 'completion_actual_resume_unproved')
                break
            crossed = True
        elif next_segment.id != segment.id:
            boundary('SEGMENT_BOUNDARY', last, 'completion_actual_unexpected_segment')
            break
        transfers.append(transfer)
        if type(term) is PendingDispatchTerminator:
            edge = term.successors[transfer.successor_index]
            landing = ctx.blocks[following.block]
            for argument, formal in zip(edge.arguments, landing.arguments):
                if type(argument) is not PendingPayload:
                    continue
                target = ctx.results.get((following.id, formal))
                receipt = projection(ctx, target, shared)
                if receipt is None:
                    boundary('MISSING_PROJECTION', last, 'completion_actual_projection_missing')
                    stopped = True
                    break
                projections.append(receipt)
                gaps.extend(receipt['gaps'])
                if receipt['binding']['match'] is not True:
                    boundary('UNPROVED_PROJECTION', last, 'completion_actual_projection_unproved')
                    stopped = True
                    break
                current = receipt['payload_value']
        visit, position = following, 0
    if shared.truncated:
        gaps.append('completion_actual_budget')
        cursor = {'phase': 'completion_actual', 'visit': visit.id, 'position': position}
    if not terminals:
        gaps.append('completion_actual_terminal_unobserved')
    return deepcopy({'source': source, 'anchor': anchor, 'segments': tuple(segments),
        'transfers': tuple(transfers), 'terminals': tuple(terminals),
        'drives': tuple(drives),
        'projections': tuple(projections), 'boundaries': tuple(boundaries),
        'gaps': tuple(dict.fromkeys(gaps)), 'status': status(gaps=gaps, children=terminals),
        'known_inventory_complete': not gaps and not shared.truncated,
        'cursor': cursor, 'budget': {'limit': shared.limit, 'used': shared.used,
            'truncated': shared.truncated, 'costs': dict(shared.costs)},
        'preparation': preparation, **_flags()})

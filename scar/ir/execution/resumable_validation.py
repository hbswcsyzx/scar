"""Check persistent-body associations against original ports and captured flow."""
from scar.ir.program.drivers import BodyStart

from .common import Unresolved
from .coordinates import CaptureIngress, InitialEntry, ResumeIngress, UnresolvedHostThread
from .ids import BlockVisitID, OperationOccurrenceID
from .resumable_flow import (
    check_unresolved, creation_view, gap, input_views, output_views,
    prepare_resumables, prepare_value_copies, value_for_use,
)


def _endpoint(ctx, row, kind, gaps):
    identity = getattr(row, kind)
    if type(identity) is Unresolved:
        check_unresolved(ctx, identity, row.activation, gaps)
        gap(ctx, gaps, 'body_' + kind + '_unobserved', row.drive, f'body {kind} is unresolved')
        return None
    registry = ctx.visits if kind == 'entry' else ctx.occurrences
    result = registry.get(identity)
    if result is None:
        ctx.issue('body_' + kind + '_endpoint', row.drive, f'known {kind} does not exist')
        return None
    visit = result if kind == 'entry' else ctx.visits[result.visit]
    if ctx.segments[visit.segment].activation != row.activation:
        ctx.issue('body_' + kind + '_activation', row.drive, f'known {kind} belongs to another body activation')
    return result


def _thread(ctx, caller, endpoint_segment, gaps):
    own = ctx.segments[ctx.visits[caller.visit].segment]
    if type(own.host_thread) is UnresolvedHostThread or type(endpoint_segment.host_thread) is UnresolvedHostThread:
        gap(ctx, gaps, 'body_thread_unresolved', caller.id, 'Drive/selected body segment thread is not fully captured')
        return False
    if own.host_thread != endpoint_segment.host_thread:
        ctx.issue('body_thread', caller.id, 'Drive and this selected execution segment have different known host threads')
        return False
    return True


def _ingress(ctx, caller, drive, entry, segment, gaps):
    if entry is None:
        return False
    region, target_block, _ = ctx.body_static_targets[caller.operation]
    if entry.block != target_block:
        ctx.issue('body_entry_block', caller.id, 'entry is not this Start/Resume original target block')
    ingress = segment.ingress
    if type(ingress) is CaptureIngress:
        gap(ctx, gaps, 'body_entry_ingress_unproved', caller.id, 'CaptureIngress does not establish InitialEntry or the exact resume ingress')
        return False
    if type(drive.target) is BodyStart:
        if type(ingress) is not InitialEntry:
            ctx.issue('body_start_ingress', caller.id, 'Start cannot select a resumed segment')
            return False
        if entry.id in ctx.incoming:
            ctx.issue('body_start_predecessor', caller.id, 'Start entry cannot be an ordinary loop revisit')
            return False
        return entry.block == region.entry
    if type(ingress) is not ResumeIngress:
        ctx.issue('body_resume_ingress', caller.id, 'Resume needs an exact previous Suspend occurrence')
        return False
    previous = ctx.occurrences.get(ingress.suspension)
    if previous is None or previous.operation != drive.target.suspend or ingress.successor_index != drive.target.successor:
        ctx.issue('body_resume_source', caller.id, 'Resume selected another static suspension or successor')
        return False
    if ctx.activation_of(previous.id) != segment.activation:
        ctx.issue('body_resume_activation', caller.id, 'Resume source belongs to a different persistent activation')
        return False
    old_segment = ctx.visits[previous.visit].segment
    if old_segment == segment.id:
        ctx.issue('body_resume_segment', caller.id, 'Resume must select a new execution segment')
        return False
    actual = ctx.outgoing.get(previous.id)
    if actual is None:
        gap(ctx, gaps, 'body_resume_transfer_unobserved', caller.id, 'exact previous suspension has no captured temporal transfer')
        return False
    if actual.target != entry.id or actual.successor_index != drive.target.successor:
        ctx.issue('body_resume_transfer', caller.id, 'Resume entry differs from the exact old Suspend temporal transfer')
        return False
    return entry.block == target_block


def _path(ctx, caller, entry, outcome, selected_source, gaps):
    """Respect captured branch choices before searching any missing suffix.

    Each linked segment is uniquely claimed. Captured visits are walked only
    within it; a missing suffix uses a cache of original static first frontiers.
    A known contrary prefix is a conflict, not merely an uncaptured-path gap.
    """
    desired = outcome.operation if outcome is not None else selected_source
    if entry is None or desired is None:
        gap(ctx, gaps, 'body_path_unobserved', caller.id, 'entry or actual/selected outcome is unresolved')
        return False
    cursor, seen = entry, set()
    while cursor.id not in seen:
        seen.add(cursor.id)
        if outcome is not None and cursor.id == outcome.visit:
            return True
        block = ctx.blocks[cursor.block]
        terminal = ctx.core_operations[block.operations[-1]]
        occurrence = ctx.body_occurrences_by_segment_site.get((cursor.segment, terminal.id), ())
        occurrence = next((row for row in occurrence if row.visit == cursor.id), None)
        if terminal.terminator.kind.value in ('SUSPEND', 'RETURN', 'RAISE'):
            if terminal.id != desired:
                ctx.issue('body_outcome_path', caller.id, 'captured prefix reaches a different first body outcome')
            else:
                gap(ctx, gaps, 'body_path_unobserved', caller.id, 'first outcome static site is compatible but exact outcome occurrence/path is missing')
            return False
        transfer = None if occurrence is None else ctx.outgoing.get(occurrence.id)
        if transfer is not None:
            following = ctx.visits[transfer.target]
            if following.segment != cursor.segment:
                ctx.issue('body_outcome_path', caller.id, 'first-outcome route cannot continue through a temporal resume')
                return False
            cursor = following
            continue
        key = ctx.block_regions[cursor.block], cursor.block
        if key not in ctx.body_missing_suffix_frontiers:
            from scar.ir.program.resumption_flow import first_body_outcome_operations
            ctx.body_missing_suffix_frontiers[key] = first_body_outcome_operations(
                ctx.regions[key[0]], ctx.core_operations, cursor.block)
        if desired not in ctx.body_missing_suffix_frontiers[key]:
            ctx.issue('body_outcome_path', caller.id, 'known captured prefix has no legal first-outcome continuation to the selected source')
        else:
            gap(ctx, gaps, 'body_path_unobserved', caller.id, 'missing transfer leaves a compatible but unproved suffix')
        return False
    ctx.issue('body_outcome_path', caller.id, 'actual first-outcome path cannot revisit the same visit identity')
    return False


def body_errors(ctx):
    prepare_resumables(ctx)
    ctx.body_missing_suffix_frontiers = {}
    claimed_entry, claimed_outcome, claimed_segment, claimed_creation = {}, {}, {}, {}
    for activation, row in ctx.body_activation_origins.items():
        owner = ctx.activations.get(activation)
        if owner is None or owner.region not in ctx.resumable_bodies:
            ctx.issue('body_origin_activation', activation, 'origin must name an existing resumable body activation')
            continue
        view = creation_view(ctx, activation)
        ctx.resolved_body_origins[activation] = view
        if type(row.creation) is not Unresolved:
            if row.creation in claimed_creation:
                ctx.issue('body_creation_reused', activation, 'one concrete Create cannot create two persistent body activations')
            claimed_creation[row.creation] = activation
    for identity, row in ctx.body_drive_executions.items():
        if identity not in ctx.body_drive_occurrences:
            ctx.issue('body_drive_kind', identity, 'association must name an actual canonical BodyDrive occurrence')
        if row.activation not in ctx.activations:
            ctx.issue('body_activation', identity, 'association references an absent body activation')
    for activation in ctx.activations.values():
        if activation.region in ctx.resumable_bodies and activation.id not in ctx.resolved_body_origins:
            ctx.resolved_body_origins[activation.id] = creation_view(ctx, activation.id)
    for identity, caller in ctx.body_drive_occurrences.items():
        drive, row, gaps = ctx.body_drives[caller.operation], ctx.body_drive_executions.get(identity), []
        region, target_block, edge = ctx.body_static_targets[caller.operation]
        activation = None if row is None else ctx.activations.get(row.activation)
        entry = outcome = segment = None
        entry_valid = path_complete = False
        entry_thread = outcome_thread = False
        if row is None:
            gap(ctx, gaps, 'body_drive_execution_missing', identity, 'captured BodyDrive has no explicit persistent-body association')
        else:
            # Known endpoint FK/kind and explicit unresolved scope are checked
            # independently; a missing activation must not hide those facts.
            entry, outcome = _endpoint(ctx, row, 'entry', gaps), _endpoint(ctx, row, 'outcome', gaps)
            if outcome is not None:
                op = ctx.core_operations[outcome.operation]
                if op.terminator is None or op.terminator.kind.value not in ('SUSPEND', 'RETURN', 'RAISE'):
                    ctx.issue('body_outcome_kind', identity, 'actual outcome must be an original Suspend/Return/Raise')
        if row is not None and activation is not None:
            if activation.region != region.id:
                ctx.issue('body_activation_region', identity, 'Drive target and body activation have different canonical regions')
            if activation.process != ctx.activations[ctx.activation_of(caller.id)].process:
                ctx.issue('body_process', identity, 'Drive and body activation belong to different process/run incarnations')
            segments = []
            for endpoint, visit in ((entry, entry), (outcome, None if outcome is None else ctx.visits[outcome.visit])):
                if endpoint is not None:
                    selected_segment = ctx.segments[visit.segment]
                    segments.append(selected_segment)
                    correct_thread = _thread(ctx, caller, selected_segment, gaps)
                    if endpoint is entry:
                        entry_thread = correct_thread
                    else:
                        outcome_thread = correct_thread
            if segments:
                segment = segments[0]
                if any(item.id != segment.id for item in segments):
                    ctx.issue('body_endpoint_segment', identity, 'entry and outcome select different execution segments')
                if segment.id in claimed_segment:
                    ctx.issue('body_segment_reused', identity, 'two Drives cannot claim the same body execution segment')
                claimed_segment[segment.id] = identity
                if len(ctx.body_outcomes_by_segment[segment.id]) > 1:
                    ctx.issue('body_multiple_outcome', identity, 'one selected body segment has multiple captured first outcomes')
            for endpoint, registry, code in ((entry, claimed_entry, 'body_entry_reused'), (outcome, claimed_outcome, 'body_outcome_reused')):
                if endpoint is not None:
                    if endpoint.id in registry:
                        ctx.issue(code, identity, 'two Drives cannot claim this exact body endpoint')
                    registry[endpoint.id] = identity
            if entry is not None:
                entry_valid = _ingress(ctx, caller, drive, entry, ctx.segments[entry.segment], gaps)
            ctx.body_drives_by_activation[row.activation].append(identity)
        origin = (ctx.resolved_body_origins.get(row.activation) if row is not None else None)
        if origin is None:
            origin = (creation_view(ctx, row.activation) if row is not None and activation is not None
                      else {'captures': {}, 'handle': None, 'creation': None, 'association': None, 'gaps': ()})
        if row is not None and activation is not None:
            ctx.resolved_body_origins.setdefault(row.activation, origin)
        gaps.extend(item for item in origin['gaps'] if item not in gaps)
        inputs = input_views(ctx, caller, row, entry, segment, origin, gaps)
        outputs, forwards, transfer = output_views(ctx, caller, outcome, gaps)
        selected = None if transfer is None else ctx.core_operations[caller.operation].terminator.successors[transfer.successor_index]
        if row is not None:
            path_complete = _path(ctx, caller, entry, outcome, None if selected is None else selected.source, gaps)
        instance_use = ctx.uses.get((caller.id, drive.instance))
        instance = {'use': instance_use, 'value': value_for_use(ctx, instance_use), 'creation_handle': origin['handle']}
        if instance_use is None:
            gap(ctx, gaps, 'body_instance_unobserved', identity, 'Drive instance Use is not captured')
        candidates = () if ctx.body_program_index is None else ctx.body_program_index.drive_outcomes(caller.operation)
        first = None
        if entry is not None:
            first = ctx.body_occurrences_by_segment_site.get((entry.segment, ctx.blocks[entry.block].operations[0]), ())
            first = next((item for item in first if item.visit == entry.id), None)
        if entry_valid and first is None:
            gap(ctx, gaps, 'body_entry_first_operation_unobserved', identity, 'entry first original operation is not captured')
        ctx.resolved_body_drives[identity] = {
            'drive': caller, 'operation': ctx.core_operations[caller.operation], 'declaration': drive,
            'association': row, 'activation': activation, 'entry': entry, 'outcome': outcome,
            'segment': segment, 'target': {'region': region, 'block': target_block, 'resume_edge': edge},
            'inputs': inputs, 'outputs': outputs, 'forwards': forwards, 'instance': instance,
            'outcome_candidates': candidates, 'transfer': transfer, 'origin': origin,
            'entry_first': first, 'entry_bridge': entry_valid and entry_thread and first is not None,
            'outcome_bridge': outcome is not None and outcome_thread and transfer is not None,
            'path_complete': path_complete, 'canonical_gaps': tuple(gaps), 'gaps': tuple(gaps)}
    from .resumable_sessions import prepare_body_sessions
    prepare_body_sessions(ctx)
    prepare_value_copies(ctx)
    for view in ctx.resolved_body_origins.values():
        view['canonical_gaps'] = view['gaps']


__all__ = ['body_errors']

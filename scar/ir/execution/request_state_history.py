"""Conditional post-to-read receipts over original captured program ports.

An established post, reference copy, state route and content preservation are
independent relations. Nothing here creates a state, a field address, a native
phase observation or permission to replace execution.
"""
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost
from scar.ir.program.model import AccessMode, ExitKind, OperationResult, TerminatorKind
from scar.ir.program.protocol_connections import RequestStateCondition, RequestStateRule
from scar.ir.program.protocols import AdmissionPredicate
from scar.ir.program.queries import ProgramIndex

from .await_outcome_evidence import pair
from .common import Unresolved
from .coordinates import OccurrencePhase, OccurrencePoint
from .resumable_flow import value_for_use
from .state_preservation import state_preservation


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                value_identity_verified=False, transformation_authorized=False)


def _empty_preservation():
    return {'preserved': None, 'reached': None, 'operations': (), 'calls': (),
            'transfers': (), 'state_bindings': (), 'blockers': (), 'gaps': (), 'cursor': None}


def _unknown_pair():
    return {'match': None, 'support': (), 'gaps': (), **_flags()}


class _History:
    def __init__(self, ctx, shared):
        self.ctx, self.shared = ctx, shared
        self.gaps, self.cursor = [], None
        self.sites = getattr(ctx, 'session_occurrences_by_visit_site', None)
        if self.sites is None:
            self.sites = {(row.visit, row.operation): row for row in ctx.occurrences.values()}

    def gap(self, code):
        if code not in self.gaps:
            self.gaps.append(code)

    def spend(self, kind, path):
        if self.shared.truncated or not self.shared.spend('state_history_' + kind, path=str(path)):
            self.gap('state_history_budget_exhausted')
            if self.cursor is None:
                self.cursor = {'phase': kind, 'path': str(path)}
            return False
        return True

    def use_value(self, occurrence, use):
        return value_for_use(self.ctx, self.ctx.uses.get((occurrence.id, use)))

    def observed_branch(self, read, row, boolean):
        """Follow this READ evaluation, never a later visit of the same site."""
        ctx = self.ctx
        visit = ctx.visits[read.visit]
        position = ctx.blocks[visit.block].operations.index(read.operation) + 1
        segment, seen = visit.segment, set()
        while visit.id not in seen:
            if not self.spend('branch_visits', visit.id):
                return None
            seen.add(visit.id)
            block = ctx.blocks[visit.block]
            for site in block.operations[position:]:
                if not self.spend('branch_operations', site):
                    return None
                occurrence = self.sites.get((visit.id, site))
                if occurrence is None:
                    self.gap('state_history_branch_occurrence_missing')
                    return None
                if site == read.operation:
                    self.gap('state_history_read_reevaluated_before_branch')
                    return None
                if site == row.contract.branch:
                    operation = ctx.core_operations[site]
                    condition = self.use_value(occurrence, operation.terminator.condition)
                    binding = pair(ctx, boolean, condition, self.shared)
                    transfer = ctx.outgoing.get(occurrence.id)
                    if binding['match'] is not True or transfer is None or self.shared.truncated:
                        self.gap('state_history_branch_binding_unproved')
                        return None
                    return transfer.successor_index == 0
            terminal = self.sites.get((visit.id, block.operations[-1]))
            operation = ctx.core_operations[block.operations[-1]]
            if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE,
                                             TerminatorKind.SUSPEND, TerminatorKind.BODY_DRIVE):
                return None
            transfer = None if terminal is None else ctx.outgoing.get(terminal.id)
            if transfer is None:
                self.gap('state_history_branch_transfer_missing')
                return None
            following = ctx.visits[transfer.target]
            if following.segment != segment:
                self.gap('state_history_branch_segment_unproved')
                return None
            visit, position = following, 0
        self.gap('state_history_branch_route_unproved')
        return None


def request_state_history(ctx, read_id, *, shared):
    analysis = _History(ctx, shared)
    read = ctx.occurrences[read_id]
    operation = ctx.core_operations[read.operation]
    declarations = tuple(row for row in ctx.program.protocol_operations
        if row.operation == read.operation and type(row.contract) is AdmissionPredicate
        and type(row.contract.subject) is RequestStateCondition)
    inventory = tuple(ctx.program.session_updates)
    occurrences = {}
    for occurrence in ctx.occurrences.values():
        occurrences.setdefault(occurrence.operation, []).append(occurrence)
    # Original declarations and actual occurrences survive even budget=1.
    candidates = [dict(update=update, source=source, post_established=None,
        subject_binding=_unknown_pair(), locations=(), support=(), source_point=None,
        state_input_inventory=(), state_inputs=(),
        preservation=_empty_preservation(), expected_bool=None, gaps=(), status='NOT_CHECKED')
        for update in inventory for source in occurrences.get(update.operation, ())]
    missing = tuple(update for update in inventory if not occurrences.get(update.operation))
    if missing:
        analysis.gap('state_history_post_sources_unobserved')
    if not inventory:
        analysis.gap('state_history_post_source_missing')
    publication_index = getattr(ctx, 'body_program_index', None)
    prepared = publication_index is not None
    if publication_index is None and inventory:
        publication_index = ProgramIndex(ctx.program)
    predicate = declarations[0] if len(declarations) == 1 else None
    # Dependency inventory is original input, not a successful proof prefix.
    read_locations = {access.location for access in operation.accesses}
    read_supported, read_subject, boolean = False, None, None
    observed = None
    if analysis.spend('read', read.id) and predicate is not None:
        read_supported = operation.effects_complete
        if not operation.effects_complete:
            analysis.gap('state_history_read_effects_incomplete')
        read_subject = analysis.use_value(read, predicate.contract.subject.request_use)
        current = ctx.current(OccurrencePoint(read.id, OccurrencePhase.BEFORE)) or {}
        for access in operation.accesses:
            if not analysis.spend('read_accesses', read.id):
                read_supported = False
                break
            value = analysis.use_value(read, access.before)
            if (access.mode is not AccessMode.READ or value is None or type(value) is Unresolved
                    or current.get(access.location) != value.id):
                read_supported = False
                analysis.gap('state_history_read_state_unproved')
        result = predicate.contract.result
        if (type(result) is OperationResult and result.operation == read.operation
                and result.index < len(operation.results)):
            boolean = ctx.results.get((read.id, operation.results[result.index]))
        if boolean is None:
            read_supported = False
            analysis.gap('state_history_read_bool_unobserved')
        if not read_locations:
            read_supported = False
            analysis.gap('state_history_read_dependencies_unresolved')
        observed = analysis.observed_branch(read, predicate, boolean)
    else:
        analysis.gap('state_history_predicate_unresolved')
    pending = []
    for ordinal, candidate in enumerate(candidates):
        source, update = candidate['source'], candidate['update']
        if not analysis.spend('sources', source.id):
            pending.extend(range(ordinal, len(candidates)))
            break
        gaps = []
        try:
            publication = publication_index.session_publication(update.operation)
        except (KeyError, ValueError, StopIteration, AttributeError):
            publication = None
        support = () if publication is None else tuple(publication.support)
        if not support:
            gaps.append('state_history_post_support_unresolved')
        locations = tuple(sorted({value.location for value in support} | read_locations,
                                 key=lambda value: value.wire))
        candidate.update(support=support, locations=locations)
        input_inventory = () if publication is None else publication.state_inputs
        candidate['state_input_inventory'] = input_inventory
        transfer = ctx.outgoing.get(source.id)
        source_operation = ctx.core_operations[source.operation]
        if update.binding is LifecyclePostBinding.AFTER_OPERATION:
            point, established = OccurrencePoint(source.id, OccurrencePhase.AFTER), True
        elif transfer is None:
            point, established = None, None
            gaps.append('state_history_post_transfer_missing')
        elif source_operation.terminator.successors[transfer.successor_index].kind is not ExitKind.NORMAL:
            point, established = None, False
            gaps.append('state_history_post_normal_not_selected')
        else:
            point = OccurrencePoint(source.id, OccurrencePhase.EDGE, transfer.successor_index)
            established = True
        states = {} if point is None else ctx.current(point) or {}
        source_request = analysis.use_value(source, update.request)
        source_body = analysis.use_value(source, update.body)
        if not support or any(states.get(value.location) is None for value in support):
            established = None if established is not False else False
            gaps.append('state_history_post_state_unobserved')
        if any(value is None or type(value) is Unresolved for value in (source_request, source_body)):
            established = None if established is not False else False
            gaps.append('state_history_post_subject_unobserved')
        # A captured output cannot fill an absent original input.  The generic
        # interval intentionally starts after the post, so this source boundary
        # must be checked here, using the original publication's entire inputs.
        before = ctx.before.get(source.id, {})
        input_bindings = []
        for site in input_inventory:
            if not analysis.spend('post_input_states', source.id):
                established = None if established is not False else False
                break
            definition = ctx.core_values[site.use.value]
            actual = ctx.uses.get((source.id, site.use.id))
            value = value_for_use(ctx, actual)
            current = before.get(definition.location)
            input_bindings.append({'definition': site, 'use': actual, 'value': value,
                'location': definition.location, 'current': current})
            if (value is None or type(value) is Unresolved or current != value.id):
                established = None if established is not False else False
                gaps.append('state_history_post_input_state_unobserved')
        candidate['state_inputs'] = tuple(input_bindings)
        for definition in support:
            if not analysis.spend('post_states', source.id):
                established = None if established is not False else False
                break
            value = ctx.values.get(states.get(definition.location))
            if value is None or value.value != definition.id:
                established = None if established is not False else False
                gaps.append('state_history_post_state_port_unproved')
        binding = pair(ctx, source_request, read_subject, shared)
        candidate.update(post_established=established, source_point=point, subject_binding=binding)
        if established is True and locations and not shared.truncated:
            preservation = state_preservation(ctx, point,
                OccurrencePoint(read.id, OccurrencePhase.BEFORE), locations, shared=shared)
            candidate['preservation'] = preservation
            if preservation['preserved'] is not True:
                gaps.append('state_history_post_preservation_unproved')
        else:
            gaps.append('state_history_post_not_established')
        if binding['match'] is not True:
            gaps.append('state_history_subject_unproved')
        supported_rule = (predicate is not None
            and predicate.contract.subject.rule is RequestStateRule.IS_COMPLETE
            and update.post is SessionPost.COMPLETE)
        if not supported_rule:
            gaps.append('state_history_post_implication_unresolved')
        if (supported_rule and read_supported and established is True
                and binding['match'] is True and candidate['preservation']['preserved'] is True
                and not shared.truncated):
            candidate['expected_bool'] = True
        candidate['gaps'] = tuple(dict.fromkeys(gaps))
        candidate['status'] = 'DECLARED' if candidate['expected_bool'] is True else 'PARTIAL'
    expected = (True if not shared.truncated and any(row['expected_bool'] is True
                                                    for row in candidates) else None)
    if shared.truncated:
        analysis.gap('state_history_budget_exhausted')
        if analysis.cursor is None:
            analysis.cursor = {'phase': 'state_history', 'read': read.id}
    return {'read': read, 'predicate': predicate, 'predicate_inventory': declarations,
        'source_inventory': inventory, 'missing_sources': missing,
        'candidates': tuple(candidates), 'locations': tuple(sorted(read_locations, key=lambda value: value.wire)),
        'expected_bool': expected, 'observed_branch': observed,
        'consistent': None if expected is None or observed is None else expected is observed,
        'status': 'NOT_CHECKED' if shared.truncated else 'DECLARED' if expected is True else 'PARTIAL',
        'gaps': tuple(analysis.gaps), 'pending_candidates': tuple(pending), 'cursor': analysis.cursor,
        'budget': {'limit': shared.limit, 'used': shared.used, 'costs': dict(shared.costs),
                   'truncated': shared.truncated},
        'preparation': {'source_rows': len(inventory), 'occurrence_rows': len(ctx.occurrences),
            'program_index_reused': prepared, 'new_program_indexes': int(not prepared and bool(inventory)),
            'derived_paths_precomputed': 0},
        'conditions': ('SessionUpdate implementation and source/native applicability remain conditional',
                       'location IDs and address labels do not establish isolation',
                       'expected truth is independent of the captured branch choice'), **_flags()}

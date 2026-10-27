"""Actual qualification choices over the original predicate and copy ports."""
from scar.ir.program.await_qualification import qualification_view
from scar.ir.program.model import ExitKind

from .common import Unresolved
from .coordinates import OccurrencePhase, OccurrencePoint
from .resumable_flow import gap, value_for_use


def qualification_occurrences(ctx, flow, shared, *, scope=None):
    from .await_links import _flags, _result, _root, _use
    from .host_order import host_path
    from scar.ir.program.protocols import OwnedUse

    sites = (tuple((row, ctx.await_occurrences_by_site.get(row.operation, ()))
                   for row in ctx.await_qualification_sites) if scope is None else
             getattr(ctx, 'await_qualifications_by_scope', {}).get(scope, ()))
    total = sum(len(occurrences) for _, occurrences in sites)
    rows, gaps, checked, cursor = [], [], 0, None
    for row, occurrences in sites:
        for occurrence in occurrences:
            local = []
            if not shared.spend('await_qualification_occurrences', path='await.qualification.occurrences'):
                rows.append({'record': row, 'occurrence': occurrence, 'feasibility': None,
                    'acceptance_selected': None, 'status': 'NOT_CHECKED', 'gaps': (), **_flags()})
                cursor = cursor or {'phase': 'qualification_occurrences', 'occurrence': occurrence.id}
                continue
            view = qualification_view(flow, row)
            contract = row.contract
            candidate = value_for_use(ctx, _use(ctx, occurrence, OwnedUse(row.operation, contract.input_use)))
            expected = None
            root = _root(ctx, candidate)
            creation = ctx.body_known_create_handles.get(root)
            if creation is not None and view['source']['binding']['match'] is True:
                declaration = ctx.body_creates[ctx.occurrences[creation].operation]
                cases = tuple(case for case in view['cases']
                              if case['source_case']['create'] is not None
                              and case['source_case']['create'].operation == declaration.operation
                              and case['source_case']['current'] is True)
                truths = {case['accepts'] for case in cases}
                if len(truths) == 1:
                    expected = next(iter(truths))
            elif candidate is not None and type(candidate) is not Unresolved and root is not None:
                original = ctx.core_values[ctx.values[root].value].origin
                cases = tuple(case for case in view['cases']
                              if case['source_case']['kind'] == 'NON_ITERATOR'
                              and case['source_case']['origin'] == original
                              and case['source_case']['current'] is True)
                if cases and view['source']['binding']['match'] is True:
                    expected = False
            selected, branches = None, []
            if contract.branch is None:
                transfer = ctx.outgoing.get(occurrence.id)
                if transfer is not None:
                    edge = ctx.core_operations[row.operation].terminator.successors[transfer.successor_index]
                    selected = edge.kind is ExitKind.NORMAL
            else:
                boolean = _result(ctx, occurrence, contract.result)
                boolean_root = _root(ctx, boolean)
                for branch in ctx.await_occurrences_by_site.get(contract.branch, ()):
                    if not shared.spend('await_qualification_branch_occurrences', path='await.qualification.branch'):
                        break
                    if ctx.activation_of(branch.id) != ctx.activation_of(occurrence.id):
                        continue
                    operation = ctx.core_operations[branch.operation]
                    actual = value_for_use(ctx, _use(ctx, branch,
                        OwnedUse(branch.operation, operation.terminator.condition)))
                    if boolean_root is None or boolean_root != _root(ctx, actual):
                        continue
                    path = host_path(ctx, OccurrencePoint(occurrence.id, OccurrencePhase.AFTER),
                                     OccurrencePoint(branch.id, OccurrencePhase.BEFORE), budget=shared)
                    transfer = ctx.outgoing.get(branch.id)
                    if path is not None and transfer is not None:
                        branches.append({'branch': branch, 'transfer': transfer, 'host_path': path})
                if len(branches) == 1:
                    selected = branches[0]['transfer'].successor_index == (0 if contract.accepts_true else 1)
            if expected is None:
                gap(ctx, local, 'await_qualification_input_kind_unproved', occurrence.id,
                    'this exact input lacks a complete independent declared source kind')
            if selected is None:
                gap(ctx, local, 'await_qualification_choice_unobserved', occurrence.id,
                    'this own predicate result lacks one exact captured accepting/rejecting choice')
            if expected is False and selected is True and not shared.truncated:
                ctx.issue('await_qualification_acceptance', occurrence.id,
                    'known unsuitable candidate selected the accepting leg of its exact qualification')
            if (contract.branch is not None and expected is True and selected is False
                    and not shared.truncated):
                ctx.issue('await_qualification_rejection', occurrence.id,
                    'declared iterator selected the rejecting leg of the fixed bool predicate')
            complete = not shared.truncated
            checked += int(complete)
            rows.append({'record': row, 'occurrence': occurrence, 'feasibility': view,
                'candidate': candidate, 'expected_acceptance': expected, 'acceptance_selected': selected,
                'branches': tuple(branches), 'status': 'PARTIAL' if local or not complete else 'DECLARED',
                'gaps': tuple(local), **_flags()})
            gaps.extend(local)
            if not complete:
                cursor = cursor or {'phase': 'qualification_occurrences', 'occurrence': occurrence.id}
    return {'records': len(sites), 'occurrence_count': total, 'checked_occurrence_count': checked,
        'pending_occurrence_count': total - checked, 'occurrences': tuple(rows), 'gaps': tuple(gaps),
        'cursor': cursor, 'known_inventory_complete': checked == total and not shared.truncated, **_flags()}


__all__ = ['qualification_occurrences']

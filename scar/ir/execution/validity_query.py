"""Conditional per-fragment support over independent production evidence.

Actual coverage and guarded future coverage are intentionally separate.  A
matched visibility alternative never closes source capture, stability or native
applicability. This module creates no operations, selectors or producers.
"""
from __future__ import annotations

from copy import deepcopy

from .common import Unresolved
from .content import VersionRef
from .content_validation import artifact_key
from .coverage import RegionRef, _ValueCatalog, _labeled_storage_coverage
from .ids import ContentReadID
from .production import RawRecordRef, WorkWrite
from .production_query import production_shared
from .validity_budget import ValidityBudget
from .validity_stability import production_interval, read_domain, read_interval, stability
from .validity_validation import resolve_support


def _empty_coverage(required, reason):
    return {'status': 'UNRESOLVED', 'required': required, 'offered': (), 'geometry': None,
            'intersections': (), 'portions': (), 'symbolic_whole': (), 'budget_used': 0,
            'gaps': ({'code': 'validity_selector_unresolved', 'message': reason},),
            'source_runtime_verified': False, 'transformation_authorized': False}


def _fragments(ctx, read, universe, budget):
    from .validity_validation import source_result_barrier

    by_write = {}
    for candidate in universe['candidates']:
        if not budget.spend('contribution_sources', path='validity.candidates'):
            break
        for resolved in candidate['write_associations']:
            if not budget.spend('association_joins', path='validity.source-write'):
                break
            identity = resolved['row'].id
            by_write.setdefault(identity, {})[candidate['id']] = None
    # A supplied support is not a new source writer. Retain detached/orphan
    # claims for diagnosis without admitting them to the source universe.
    for support in ctx.contribution_supports.values():
        if not budget.spend('association_joins', path='validity.orphan-support'):
            break
        if support.read == read['read'].id and support.write in ctx.resolved_writes:
            by_write.setdefault(support.write, {})

    result = []
    expected = universe['demand']['version']
    for identity, candidates in by_write.items():
        if not budget.spend('contribution_scan', path='validity.write'):
            break
        resolved = ctx.resolved_writes[identity]
        original = resolved['row']
        placement = resolved.get('placement')
        version = (None if placement is None or placement[0] is None or type(original.placement) is Unresolved
                   else VersionRef(original.placement.materialization.artifact, placement[0].value_version))
        requested = None if placement is None else placement[1]
        productions = []
        for registry in (ctx.resolved_produced, ctx.resolved_establishments):
            for actual in registry.values():
                if not budget.spend('association_joins', path='validity.write-result'):
                    break
                if actual['row'].write == identity:
                    productions.append(actual)
            if budget.truncated:
                break
        terminal = (ctx.work_outcomes.get(original.writer.ticket, ())
                    if type(original.writer) is WorkWrite else ())
        source_result = (source_result_barrier(ctx, original, budget=budget)
                         if not productions and type(original.writer) is WorkWrite
                         else {'blocked': False, 'source_result_present': False, 'conditions': ()})
        start, end = production_interval(ctx, original)
        for actual in productions or (None,):
            if not budget.spend('contribution_scan', path='validity.fragment'):
                break
            pending = (actual is None and not terminal and type(original.writer) is WorkWrite
                       and not source_result['blocked'])
            selected = actual['row'].actual if actual is not None else requested if pending else None
            same_version = (version is not None and expected is not None
                and artifact_key(version.artifact) == artifact_key(expected.artifact)
                and version.version == expected.version)
            placement_match = None if actual is None else actual.get('placement_match')
            conditions = []
            if actual is not None and placement_match is not True:
                conditions.append('exact actual-to-write materialization placement is unverified; byte coverage alone cannot establish this tuple')
            if not candidates:
                conditions.append('missing exact independent source-stage join')
            if not same_version:
                conditions.append('write does not establish the exact demanded scoped content version')
            if actual is None and terminal:
                conditions.append('terminal work has no exact actual production selector; request is not a fallback')
            if actual is None and source_result['blocked']:
                conditions.append('known source result is unjoined; deleting outcomes cannot enable future requested coverage')
                conditions.extend(source_result.get('conditions', ()))
            if pending:
                conditions.append('future support requires successful content production and valid error propagation')
            key = (original.stage, original.production, original.placement, original.writer,
                   None if actual is None else actual['row'].id)
            result.append({'label': 'fragment:' + str(len(result)), 'key': key,
                'write': original, 'resolved_write': resolved, 'production': actual,
                'actual': selected, 'requested': requested, 'version': version,
                'placement': original.placement, 'source_candidates': tuple(candidates),
                'source_universe': universe, 'production_start': start, 'production_end': end,
                'pending': pending, 'terminal_outcomes': tuple(terminal),
                'source_result': source_result, 'placement_match': placement_match,
                'content_match': same_version, 'conditions': tuple(conditions)})
    return result


def _coverage(ctx, required, fragments, budget):
    offers = []
    for fragment in fragments:
        if not budget.spend('coverage_offers', path='validity.coverage-offers'):
            break
        if type(fragment['actual']) is RegionRef:
            offers.append((fragment['label'], fragment['actual']))
    if type(required) is not RegionRef:
        return _empty_coverage(required, 'endpoint selector has no interpreted byte/extent coverage rule')
    return _labeled_storage_coverage(required, tuple(offers),
        catalog=_ValueCatalog.from_snapshots(ctx.snapshots), budget=budget)


def _same_production(support, fragment):
    actual = fragment['production']
    if actual is None:
        return support.production is None
    return support.production == actual['row'].id


def _physical_groups(fragments, budget):
    groups = []
    for fragment in fragments:
        if not budget.spend('association_joins', path='validity.physical-group'):
            break
        original = fragment['write']
        group = None
        if type(original.stage) is RawRecordRef:
            for existing in groups:
                if not budget.spend('association_joins', path='validity.physical-join'):
                    break
                first = existing['original_write']
                if (type(first.stage) is RawRecordRef and first.stage.source == original.stage.source
                        and first.stage.line == original.stage.line
                        and first.stage.sha256.lower() == original.stage.sha256.lower()
                        and first.production == original.production and first.placement == original.placement
                        and first.writer == original.writer):
                    group = existing
                    break
        if group is None:
            group = {'original_write': original, 'fragments': [],
                     'combination': 'OR evidence for one exact physical stage, not extra produced bytes'}
            groups.append(group)
        group['fragments'].append(fragment['label'])
    return tuple({**group, 'fragments': tuple(group['fragments'])} for group in groups)


def validity_shared(ctx, read_id, *, budget: ValidityBudget, include_context_gaps=False):
    """Internal undetached V view; charge the caller's shared derived budget."""
    if not isinstance(budget, ValidityBudget):
        raise TypeError('validity_shared requires a ValidityBudget')
    shared = budget
    used_before, costs_before, gaps_before = shared.used, dict(shared.costs), len(shared.gaps)
    if type(read_id) is not ContentReadID:
        raise TypeError('validity requires an exact ContentReadID')
    read = ctx.resolved_content_reads[read_id]
    universe = production_shared(ctx, read_id, budget=shared, include_context_gaps=include_context_gaps)
    if universe['truncated']:
        shared.mark_truncated('validity.production', 'independent source/lineage traversal was truncated')
    contributions = _fragments(ctx, read, universe, shared)
    actual_offers, conditional_offers, blocked_offers, invalidators, lifetime = [], [], [], [], []
    conditions = []
    for fragment in contributions:
        alternatives = []
        for support in ctx.resolved_supports.values():
            if not shared.spend('association_joins', path='validity.support'):
                break
            row = support['row']
            if row.read != read_id or row.write != fragment['write'].id or not _same_production(row, fragment):
                continue
            if not fragment['content_match']:
                alternative = {'row': row, 'status': 'CONTRADICTED', 'paths': (),
                    'domain': support.get('domain'), 'visibility': support['visibility'],
                    'conditions': ('wrong demanded scoped content version; order cannot repair this tuple',)}
            else:
                alternative = resolve_support(ctx, support, fragment, read, budget=shared)
            alternatives.append(alternative)
        fragment['alternatives'] = tuple(alternatives)
        if fragment['content_match']:
            fragment['stability'] = stability(ctx, read, fragment, budget=shared)
        else:
            # This writer still appears in every wanted fragment's independent
            # threat scan. It is not itself a candidate establishment of this
            # version, so do not repeat a whole read-validity check around it.
            fragment['stability'] = {'status': 'NOT_APPLICABLE', 'invalidators': (),
                'potential_invalidators': (), 'exclusions': (), 'lifetime': (),
                'conditions': ('other-version source retained in wanted-fragment invalidator scans',)}
        invalidators.extend({**item, 'fragment': fragment['label']} for item in fragment['stability']['invalidators'])
        lifetime.extend(fragment['stability']['lifetime'])
        conditions.extend(fragment['conditions'])
        conditions.extend(fragment['stability']['conditions'])
        for alternative in alternatives:
            conditions.extend(alternative.get('conditions', ()))
        matched = any(item['status'] == 'MATCHED' for item in alternatives)
        # Alternatives form an OR: a rejected alternative does not poison a
        # matching one. Stability, unlike one visibility alternative, applies
        # to this whole exact fragment/interval.
        conflict = fragment['stability']['status'] == 'CONTRADICTED'
        eligible = bool(fragment['content_match'] and fragment['source_candidates']
                        and (fragment['pending'] or fragment['placement_match'] is True))
        fragment['status'] = ('CONTRADICTED' if conflict and eligible else 'MATCHED'
            if matched and eligible else 'MISSING')
        if conflict and matched and eligible:
            blocked_offers.append(fragment)
        if eligible:
            if fragment['production'] is not None:
                actual_offers.append(fragment)
            if fragment['status'] == 'MATCHED':
                conditional_offers.append(fragment)

    selector = universe['demand']['selector']
    known = _coverage(ctx, selector, actual_offers, shared)
    conditional = _coverage(ctx, selector, conditional_offers, shared)
    blocked_portions = []
    if conditional['status'] != 'COVERED' and blocked_offers:
        # Keep good and blocked labels on the same exact selector partition.
        # A historical conflicting left-half leaf cannot explain a missing
        # right half when a different good leaf already covers the left.
        combined = _coverage(ctx, selector, (*conditional_offers, *blocked_offers), shared)
        good_labels, blocked_labels = set(), set()
        for offered, labels in ((conditional_offers, good_labels), (blocked_offers, blocked_labels)):
            for fragment in offered:
                if not shared.spend('support_formula', path='validity.blocked-labels'):
                    break
                labels.add(fragment['label'])
        for portion in combined.get('portions', ()):
            if not shared.spend('support_formula', len(portion['labels']) + 1,
                                path='validity.blocked-portions'):
                break
            if (not any(label in good_labels for label in portion['labels'])
                    and any(label in blocked_labels for label in portion['labels'])):
                blocked_portions.append(portion)
    groups = _physical_groups(contributions, shared)
    unmatched = []
    for candidate in universe['candidates']:
        if not shared.spend('source_reconciliation', path='validity.reconcile'):
            break
        if not candidate['write_associations']:
            unmatched.append(candidate['id'])
    by_label = {fragment['label']: fragment for fragment in contributions}
    formula = []
    for portion in conditional.get('portions', ()):
        if not shared.spend('support_formula', path='validity.formula.portion'):
            break
        alternatives = []
        for label in portion['labels']:
            if not shared.spend('support_formula', path='validity.formula.alternative'):
                break
            fragment = by_label[label]
            ids = []
            for item in fragment['alternatives']:
                if not shared.spend('support_formula', path='validity.formula.support'):
                    break
                if item['status'] == 'MATCHED':
                    ids.append(item['row'].id)
            alternatives.append({'fragment': label, 'pending': fragment['pending'],
                'support_ids': tuple(ids)})
        formula.append({'portion': portion, 'operator': 'OR', 'alternatives': tuple(alternatives)})
    # Reject only blocked necessary coverage. An unused historical/duplicate
    # candidate cannot veto a complete combination of valid fragment leaves.
    status = ('TRUNCATED' if shared.truncated else 'MATCHED'
              if conditional['status'] == 'COVERED' and contributions
              else 'CONTRADICTED' if blocked_portions else 'MISSING')
    conditions.extend(('source capture/write/alias/window completeness remains unverified',
                       'native content and visibility applicability remain unverified'))
    context_gaps = (tuple({'code': row.code, 'path': row.path, 'message': row.message}
                          for row in ctx.gaps) if include_context_gaps else ())
    return {'read': read['read'], 'demand': universe['demand'],
        'interval': read_interval(ctx, read), 'domain': read_domain(ctx, read),
        'source_universe': universe, 'lineage_prerequisites': universe['lineage_prerequisites'],
        'contributions': tuple(contributions), 'physical_groups': groups,
        'known_fragment_coverage': known, 'conditional_fragment_coverage': conditional,
        'conditional_support': {'status': status, 'operator': 'AND', 'portions': tuple(formula),
            'blocked_portions': tuple(blocked_portions),
            'meaning': 'exact known alternatives and guarded future production; not runtime readiness'},
        'source_reconciliation': {'status': 'OPEN', 'candidate_ids': tuple(item['id'] for item in universe['candidates']),
            'unmatched_candidates': tuple(unmatched), 'pending_sources': universe['pending_sources'],
            'known_joins': 'TRUNCATED' if shared.truncated else 'MISSING' if unmatched or universe['pending_sources'] else 'MATCHED',
            'conditions': ('supplied file projection is not full runtime writer/alias capture',)},
        'invalidators': tuple(invalidators), 'lifetime': tuple(lifetime),
        'validity_conditions': tuple(dict.fromkeys(conditions)),
        'gaps': context_gaps + tuple(shared.gaps[gaps_before:]),
        'budget_used': shared.used - used_before,
        'budget_costs': {key: value - costs_before.get(key, 0) for key, value in shared.costs.items()
                         if value != costs_before.get(key, 0)}, 'truncated': shared.truncated,
        'budget_scope': 'shared source, joins, formula, geometry, order and threat scans; record/FK validation, snapshot/replay and detached copying separate',
        'source_runtime_verified': False, 'runtime_visibility_verified': False,
        'transformation_authorized': False}


def validity(ctx, read_id, *, budget=4096):
    """Legacy detached single-read view with its own positive integer budget."""
    return deepcopy(validity_shared(ctx, read_id, budget=ValidityBudget(budget), include_context_gaps=True))


__all__ = ['validity', 'validity_shared']

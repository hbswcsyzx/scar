"""Bounded original-port evidence for one captured await continuation.

These helpers query existing occurrences and copy recipes.  They create no
identity, value, state or control facts, and never search sibling activations.
"""
from scar.ir.program.model import (InvokeLiteralResult,
    OperationResult, StateVersionValue, TerminatorKind)
from scar.ir.program.protocols import ContractResult, HostTerminal, OwnedUse

from .common import Unresolved
from .resumable_flow import value_for_use


def status(selected=True, *, gaps=(), children=(), bindings=(), definition=None):
    if selected is False:
        return 'NOT_APPLICABLE'
    relevant = tuple(child for child in children if child.get('status') != 'NOT_APPLICABLE')
    if (definition is not None and definition.get('status') == 'CONTRADICTED'
            or any(child.get('status') == 'CONTRADICTED' for child in relevant)
            or any(binding.get('match') is False for binding in bindings)):
        return 'CONTRADICTED'
    if (selected is None or gaps or any(binding.get('match') is None for binding in bindings)
            or any(child.get('status') in ('PARTIAL', 'NOT_CHECKED', 'MISSING') for child in relevant)
            or definition is not None and definition.get('status') in ('PARTIAL', 'NOT_CHECKED', 'MISSING')):
        return 'PARTIAL'
    return 'DECLARED'


def append_gaps(local, rows):
    for row in rows:
        if row.get('status') != 'NOT_APPLICABLE':
            for item in row.get('gaps', ()):
                if item not in local:
                    local.append(item)


def choice(ctx, occurrence, edge):
    if occurrence is None or occurrence.operation != edge.operation:
        return None
    transfer = ctx.outgoing.get(occurrence.id)
    return None if transfer is None else transfer.successor_index == edge.successor_index


def locate(ctx, anchor, site, shared, *, entry=False):
    """First original site on this captured same-segment suffix.

    A missing occurrence at the original position stays missing.  A fully
    captured different branch can establish nonselection; a truncated suffix
    cannot.  A second evaluation of the anchor bounds this evaluation's suffix.
    """
    if anchor is None:
        return None, None
    if not entry and anchor.operation == site:
        return anchor, True
    key = (anchor.id, site, entry)
    cache = getattr(ctx, '_await_outcome_locations', None)
    if cache is None:
        cache = ctx._await_outcome_locations = {}
    if not shared.spend('await_outcome_location_queries', path='await.outcome.location'):
        return None, None
    if key in cache:
        return cache[key]
    visit = anchor if entry else ctx.visits[anchor.visit]
    segment, seen = visit.segment, set()
    first = True
    while visit.id not in seen:
        if not shared.spend('await_outcome_suffix_visits', path='await.outcome.suffix'):
            return None, None
        seen.add(visit.id)
        block = ctx.blocks[visit.block]
        start = 0 if entry or not first else block.operations.index(anchor.operation) + 1
        for operation in block.operations[start:]:
            if not shared.spend('await_outcome_suffix_operations', path='await.outcome.suffix'):
                return None, None
            if operation == site:
                result = ctx.session_occurrences_by_visit_site.get((visit.id, operation)), True
                cache[key] = result
                return result
            if (not entry and operation == anchor.operation) or operation in ctx.body_drives:
                cache[key] = None, False
                return cache[key]
        last = ctx.core_operations[block.operations[-1]]
        occurrence = ctx.session_occurrences_by_visit_site.get((visit.id, last.id))
        if last.terminator is None or last.terminator.kind in (
                TerminatorKind.RETURN, TerminatorKind.RAISE, TerminatorKind.SUSPEND):
            # A missing terminal does not establish a captured completion.
            result = None, False if occurrence is not None else None
            cache[key] = result
            return result
        transfer = None if occurrence is None else ctx.outgoing.get(occurrence.id)
        if transfer is None or ctx.visits[transfer.target].segment != segment:
            cache[key] = None, None
            return cache[key]
        visit, first = ctx.visits[transfer.target], False
    return None, None


def pair(ctx, source, target, shared):
    """A common *original copy ancestor*, separately from denotation checks."""
    from .await_links import _flags
    from .resumable_identity import compatible
    from .pending_payloads import copy_recipe
    gaps, support, match, comparison = [], [], None, None
    present = all(value is not None and type(value) is not Unresolved for value in (source, target))
    if not shared.spend('await_outcome_copy_pairs', path='await.outcome.copy'):
        gaps.append('await_outcome_copy_budget')
    elif not present:
        gaps.append('await_outcome_value_unobserved')
    else:
        ancestors, cursor, seen, left, conflict = {}, source.id, set(), [], False
        while cursor not in seen:
            if not shared.spend('await_outcome_copy_ancestors', path='await.outcome.copy.source'):
                break
            seen.add(cursor)
            ancestors[cursor] = len(left)
            recipe, missing, contradicted = copy_recipe(ctx, cursor, shared)
            gaps.extend(missing)
            conflict |= contradicted
            if recipe is None:
                break
            left.append(recipe)
            cursor = recipe['source']
        cursor, seen, right = target.id, set(), []
        while not shared.truncated and cursor not in seen:
            if not shared.spend('await_outcome_copy_ancestors', path='await.outcome.copy.target'):
                break
            seen.add(cursor)
            if cursor in ancestors:
                count = ancestors[cursor] + len(right)
                if shared.spend('await_outcome_copy_support', count + 1, path='await.outcome.copy.support'):
                    support = [*left[:ancestors[cursor]], *right]
                    match = True
                break
            recipe, missing, contradicted = copy_recipe(ctx, cursor, shared)
            gaps.extend(missing)
            conflict |= contradicted
            if recipe is None:
                break
            right.append(recipe)
            cursor = recipe['source']
        if match is None:
            gaps.append('await_original_copy_unproved')
        if conflict:
            match = False
        if shared.spend('await_outcome_compatibility', path='await.outcome.compatibility'):
            comparison = compatible(ctx, source, target, gaps, 'await.outcome.copy')
            if comparison['status'] == 'CONFLICT':
                match = False
        else:
            match = None
            gaps.append('await_outcome_copy_budget')
        for recipe in support:
            if not shared.spend('await_outcome_recipe_compatibility', path='await.outcome.copy.recipe'):
                if match is not False:
                    match = None
                gaps.append('await_outcome_copy_budget')
                break
            evidence = compatible(ctx, ctx.values[recipe['source']], ctx.values[recipe['target']],
                                  gaps, 'await.outcome.recipe')
            if evidence['status'] == 'CONFLICT':
                match = False
    return {'source_value': source, 'target_value': target, 'match': match,
        'support': tuple(support), 'compatibility': comparison, 'gaps': tuple(gaps), **_flags()}


def port_value(ctx, port, occurrences, shared=None):
    from .await_links import _result, _use
    from scar.ir.program.protocols import DriveResult
    if type(port) is ContractResult:
        port = port.result_port
    if type(port) is OwnedUse:
        return value_for_use(ctx, _use(ctx, occurrences.get(port.operation), port))
    site = (port.operation if type(port) is OperationResult else
            port.edge.operation if type(port) is InvokeLiteralResult else
            port.outcome.drive if type(port) is DriveResult else None)
    return _result(ctx, occurrences.get(site), port, shared=shared)


def states(ctx, definitions, occurrences, shared):
    rows = []
    for definition in definitions:
        admitted = shared.spend('await_outcome_states', path='await.outcome.states')
        source = port_value(ctx, definition['source'], occurrences, shared) if admitted else None
        target = port_value(ctx, definition['target'], occurrences, shared) if admitted else None
        binding = pair(ctx, source, target, shared)
        local = list(binding['gaps'])
        rows.append({'definition': definition, 'source': source, 'target': target,
            'binding': binding, 'status': status(gaps=local, bindings=(binding,), definition=definition),
            'gaps': tuple(local)})
    return tuple(rows)


def target(ctx, definition, anchor, source, shared):
    """An original terminal/Use on this anchor's actual continuation."""
    from .await_links import _use
    operation, reached = locate(ctx, anchor, definition.operation, shared)
    local, use = [], None
    if type(definition) is OwnedUse:
        use = _use(ctx, operation, definition)
    elif type(definition) is HostTerminal and operation is not None:
        original = ctx.core_operations[operation.operation]
        payload = tuple(use for use in original.uses if use.id in original.terminator.values
                        and not isinstance(ctx.core_values[use.value], StateVersionValue))
        if len(payload) == 1:
            use = ctx.uses.get((operation.id, payload[0].id))
    value = value_for_use(ctx, use)
    binding = pair(ctx, source, value, shared) if reached is not False else {
        'source_value': source, 'target_value': None, 'match': None, 'support': (), 'gaps': ()}
    if reached is not False:
        if operation is None:
            local.append('await_outcome_consumer_occurrence_missing')
        if use is None:
            local.append('await_outcome_consumer_use_missing')
        local.extend(binding['gaps'])
    return {'definition': definition, 'operation': operation, 'use': use, 'value': value,
        'selected': reached, 'binding': binding,
        'status': status(reached, gaps=local, bindings=(binding,)), 'gaps': tuple(local)}


def selected_choices(ctx, choices, known, anchors, shared, *, input_guard=None):
    """Project a tuple in its exact original caller/child contexts."""
    from .await_links import _guard
    answers = []
    for edge in choices:
        if not shared.spend('await_outcome_choices', path='await.outcome.choices'):
            return None
        occurrence = known.get(edge.operation)
        if occurrence is not None and edge != input_guard:
            answers.append(choice(ctx, occurrence, edge))
            continue
        region = ctx.await_flow.region_of[edge.operation]
        candidates = tuple(anchor for anchor in anchors if anchor is not None
                           and ctx.activations[ctx.activation_of(anchor.id)].region == region)
        answers.append(_guard(ctx, candidates[-1], edge, shared,
            incoming=edge == input_guard) if candidates else None)
    return False if False in answers else None if None in answers else True


__all__ = ['append_gaps', 'choice', 'locate', 'pair', 'port_value', 'selected_choices',
           'states', 'status', 'target']

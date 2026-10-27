"""Query-local value-source proofs, separate from unconditional copy ancestry.

A stored edge means the supplied slot contract and the captured state interval
support that source. It never changes canonical copy recipes or object roots.
Parallel original-copy and stored-read edges are retained at the same value.
"""
from collections import deque

from .common import Unresolved
from .validity_budget import ValidityBudget


def source_pair(ctx, source, target, shared):
    """Find an actual common source, without equating unrelated candidates.

    Ordinary routes are tried first, so an independent copy proof does not
    require a recursive stored-read proof. If needed, a multiedge search adds
    conditional stored routes at *every* visited value, including values which
    already have an original copy predecessor. Only the chosen proof paths
    undergo endpoint compatibility checks.
    """
    from .pending_payloads import copy_recipe
    from .resumable_identity import compatible
    from .stored_value_projection import projection
    from .stored_values import _flags

    if type(shared) is not ValidityBudget:
        raise TypeError('value-source query requires exact shared ValidityBudget')
    gaps, search_gaps, projections, support = [], [], [], ()
    comparison, common, conflict = None, None, False
    paths, processed = ({}, {}), (set(), set())
    original, conditional = deque(), deque()

    def spend(kind, cost=1):
        return not shared.truncated and shared.spend('value_source_' + kind, cost,
                                                     path='value.source.' + kind)

    def add(side, identity, child=None, recipe=None):
        nonlocal common
        if identity not in paths[side]:
            paths[side][identity] = None if child is None else (child, recipe)
            original.append((side, identity))
            conditional.append((side, identity))
        if identity in paths[1 - side]:
            common = identity

    def append_original(side, identity):
        nonlocal conflict
        if (side, identity) in processed[0]:
            return
        if not spend('original_nodes'):
            return
        processed[0].add((side, identity))
        recipe, missing, contradicted = copy_recipe(ctx, identity, shared)
        search_gaps.extend(missing)
        conflict |= contradicted
        if recipe is not None:
            follow(side, identity, recipe)

    def follow(side, identity, recipe):
        nonlocal conflict
        if (recipe.get('target') != identity or recipe.get('source') not in ctx.values):
            # A broken supported route is a hard model contradiction, not a
            # reason to choose another candidate or install a guessed source.
            conflict = True
            gaps.append('value_source_recipe_endpoint_conflict')
            return
        add(side, recipe['source'], identity, recipe)

    admitted = spend('pairs')
    present = all(value is not None and type(value) is not Unresolved
                  and ctx.values.get(value.id) == value for value in (source, target))
    if not present:
        gaps.append('value_source_endpoint_unobserved')
    elif admitted:
        add(0, source.id)
        add(1, target.id)
        # First establish any independent original proof. No conditional
        # expansion is necessary for a reflexive or already connected pair.
        while original and common is None and not conflict and not shared.truncated:
            append_original(*original.popleft())
        # Each node can have BOTH predecessors. Newly discovered conditional
        # sources in turn get their original and conditional edges explored.
        while conditional and common is None and not conflict and not shared.truncated:
            while original and common is None and not conflict and not shared.truncated:
                append_original(*original.popleft())
            if common is not None or conflict or shared.truncated:
                break
            side, identity = conditional.popleft()
            if (side, identity) in processed[1]:
                continue
            if not spend('conditional_nodes'):
                break
            processed[1].add((side, identity))
            receipt = projection(ctx, ctx.values[identity], shared)
            if receipt is None:
                continue
            projections.append(receipt)
            search_gaps.extend(receipt['gaps'])
            # ACTIVE-dependent Unknown is only a missing edge. An independent
            # original route may still succeed; a cycle is never its own proof.
            recipe = receipt['recipe']
            if recipe is not None and not shared.truncated:
                follow(side, identity, recipe)

    match = None
    if common is not None and not shared.truncated and not conflict:
        selected = []
        for side in (0, 1):
            cursor = common
            while paths[side][cursor] is not None:
                if not spend('selected_support'):
                    break
                child, recipe = paths[side][cursor]
                selected.append(recipe)
                cursor = child
            if shared.truncated:
                break
        if spend('selected_support'):
            support = tuple(selected)
            comparison = compatible(ctx, source, target, gaps, 'value.source.selected')
            conflict = comparison['status'] == 'CONFLICT'
            for recipe in support:
                if not spend('selected_compatibility'):
                    break
                check = compatible(ctx, ctx.values[recipe['source']], ctx.values[recipe['target']],
                                   gaps, 'value.source.recipe')
                conflict |= check['status'] == 'CONFLICT'
            if not shared.truncated and not conflict and not ctx.issues:
                match = True
    if conflict:
        match = False
    if match is None:
        gaps.extend(search_gaps)
        gaps.append('value_source_unproved')
    if shared.truncated:
        gaps.append('value_source_budget_exhausted')
    stored = any(row['rule'] == 'DECLARED_STORED_VALUE' for row in support)
    return {'source_value': source, 'target_value': target, 'match': match,
        'conflict': conflict, 'common_source': common, 'support': support,
        'compatibility': comparison, 'projections': tuple(projections),
        'binding_kind': ('CONDITIONAL_STORED_VALUE_SOURCE' if stored else 'ORIGINAL_COPY')
                        if match is True else 'UNPROVED_VALUE_SOURCE',
        'conditional_stored_source': stored and match is True,
        'read_inventory': ctx.program.stored_value_reads,
        'write_inventory': ctx.program.stored_value_writes,
        'operation_inventory': ctx.model.operations,
        'gaps': tuple(gaps),
        'cursor': None if not shared.truncated else {
            'phase': 'value_source_search', 'original_pending': len(original),
            'conditional_pending': len(conditional), 'visited': tuple(len(rows) for rows in paths)},
        'budget': {'limit': shared.limit, 'used': shared.used, 'costs': dict(shared.costs),
                   'truncated': shared.truncated},
        'conditions': ('stored source routes depend on supplied direct-slot contracts and state intervals',
                       'source correspondence does not establish stable reference contents or native identity',
                       'original copy recipes and identity roots remain unchanged'),
        'preparation': {'original_operations': len(ctx.model.operations),
                        'original_reads': len(ctx.program.stored_value_reads),
                        'original_writes': len(ctx.program.stored_value_writes),
                        'scope': 'original indexing, fresh-context snapshot replay and detached output copying are separate'},
        **_flags()}


__all__ = ['source_pair']

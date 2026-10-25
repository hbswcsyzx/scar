"""Demand-bound stored-value edges, separate from original copy ancestry.

Only an exact own READ result can project. Receipts are private to one shared
query and its fresh context; neither roots nor canonical copy tables change.
"""
from scar.ir.program.model import (
    BlockArgument, CompletionResult, DataValue, ExitKind, InvokeLiteralResult,
    OperationResult, ReferenceValue, TerminatorKind,
)

from .common import Unresolved
from .coordinates import ValueOccurrence
from .ids import BlockVisitID, OperationOccurrenceID
from .validity_budget import ValidityBudget


_DEPTH_LIMIT = 32


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                native_identity_verified=False, value_identity_verified=False,
                transformation_authorized=False)


def _receipt(ctx, target, shared, *, declaration=None, operation=None,
             sources_report=None, recipe=None, gaps=(), cursor=None):
    match = True if recipe is not None and not shared.truncated else None
    if shared.truncated:
        recipe = None
        if 'stored_value_projection_budget' not in gaps:
            gaps = (*gaps, 'stored_value_projection_budget')
        if cursor is None:
            cursor = {'phase': 'shared_query', 'target': None if target is None else getattr(target, 'id', None)}
    return {'declaration': declaration,
            'site': None if declaration is None else declaration.result,
            'operation': operation, 'target_value': target,
            'read_inventory': ctx.program.stored_value_reads,
            'write_inventory': ctx.program.stored_value_writes,
            'operation_inventory': ctx.model.operations,
            'sources_report': sources_report, 'recipe': recipe,
            'binding': {'match': match, 'support': () if recipe is None else (recipe,),
                        'compatibility': None, 'gaps': tuple(gaps), **_flags()},
            'status': 'DECLARED' if match is True else 'PARTIAL',
            'gaps': tuple(gaps), 'cursor': cursor,
            'budget': {'limit': shared.limit, 'used': shared.used,
                       'costs': dict(shared.costs), 'truncated': shared.truncated},
            'conditions': ('original direct-slot contracts and interval effects remain conditional',
                           'this receipt adds no original copy edge or global identity union'),
            **_flags()}


def _spend(shared, phase, *, cost=1, target=None):
    path = 'stored_value_projection.' + phase
    if target is not None:
        path += '.' + str(target.id)
    return not shared.truncated and shared.spend('stored_value_projection_' + phase, cost, path)


def _read_index(ctx, shared):
    """Index original result definitions once, charging all inspected ports."""
    indexes = getattr(shared, '_stored_projection_indexes', None)
    if indexes is None:
        indexes = shared._stored_projection_indexes = {}
    if ctx in indexes:
        return indexes[ctx], (), None
    by_value = {}
    for index, declaration in enumerate(ctx.program.stored_value_reads):
        cursor = {'phase': 'read_index', 'read_index': index}
        if not _spend(shared, 'read_index'):
            return None, ('stored_value_projection_budget',), cursor
        site = declaration.result
        owner = site.operation if type(site) is OperationResult else site.edge.operation
        operation = ctx.core_operations.get(owner)
        if operation is None:
            return None, ('stored_value_projection_definition_unresolved',), cursor
        if type(site) is OperationResult:
            if site.index >= len(operation.results):
                return None, ('stored_value_projection_definition_unresolved',), cursor
            identity = operation.results[site.index]
            position = None
        else:
            term = operation.terminator
            if (term is None or term.kind is not TerminatorKind.INVOKE
                    or site.edge.successor_index >= len(term.successors)):
                return None, ('stored_value_projection_definition_unresolved',), cursor
            edge = term.successors[site.edge.successor_index]
            block = ctx.blocks.get(edge.block)
            if (edge.kind is not ExitKind.NORMAL or block is None
                    or len(edge.arguments) != len(block.arguments)):
                return None, ('stored_value_projection_definition_unresolved',), cursor
            produced = []
            for position, (argument, formal) in enumerate(zip(edge.arguments, block.arguments)):
                if not _spend(shared, 'index_landing_ports'):
                    return None, ('stored_value_projection_budget',), {
                        **cursor, 'landing_position': position}
                if type(argument) is CompletionResult and argument.index == site.result.index:
                    produced.append((position, formal))
            if len(produced) != 1:
                return None, ('stored_value_projection_definition_unresolved',), cursor
            position, identity = produced[0]
        by_value.setdefault(identity, []).append((declaration, position))
    completed = {identity: tuple(rows) for identity, rows in by_value.items()}
    indexes[ctx] = completed
    return completed, (), None


def _producer(ctx, target, declaration, position, shared):
    """Resolve this result incarnation, never a sibling static-site visit."""
    if not _spend(shared, 'producer', target=target):
        return None, ('stored_value_projection_budget',), {'phase': 'producer', 'target': target.id}
    definition = ctx.core_values[target.value]
    site = declaration.result
    if type(site) is OperationResult:
        operation = (ctx.occurrences.get(target.origin)
                     if type(target.origin) is OperationOccurrenceID else None)
        original = None if operation is None else ctx.core_operations.get(operation.operation)
        if (type(definition.origin) is not OperationResult or definition.origin != site
                or original is None or original.id != site.operation
                or site.index >= len(original.results) or original.results[site.index] != target.value
                or ctx.results.get((operation.id, target.value)) != target):
            return operation, ('stored_value_projection_producer_unobserved',), None
        return operation, (), None
    visit = ctx.visits.get(target.origin) if type(target.origin) is BlockVisitID else None
    origin = definition.origin
    if (visit is None or type(origin) is not BlockArgument
            or origin.block != visit.block or origin.index != position
            or ctx.results.get((target.origin, target.value)) != target):
        return None, ('stored_value_projection_landing_unobserved',), None
    transfer = ctx.incoming.get(target.origin)
    if transfer is None:
        return None, ('stored_value_projection_transfer_unobserved',), None
    operation = ctx.occurrences.get(transfer.operation)
    original = None if operation is None else ctx.core_operations.get(operation.operation)
    if (operation is None or original is None or original.id != site.edge.operation
            or transfer.target != target.origin or ctx.outgoing.get(operation.id) != transfer
            or transfer.successor_index != site.edge.successor_index):
        return operation, ('stored_value_projection_completion_unresolved',), None
    term = original.terminator
    if term is None or term.kind is not TerminatorKind.INVOKE:
        return operation, ('stored_value_projection_completion_unresolved',), None
    edge = term.successors[transfer.successor_index]
    block = ctx.blocks[visit.block]
    if not _spend(shared, 'selected_completion', target=target):
        return operation, ('stored_value_projection_budget',), {
            'phase': 'selected_completion', 'target': target.id}
    if (edge.kind is not ExitKind.NORMAL or edge.block != visit.block
            or position >= len(edge.arguments) or position >= len(block.arguments)
            or block.arguments[position] != target.value
            or type(edge.arguments[position]) is not CompletionResult
            or edge.arguments[position].index != site.result.index):
        return operation, ('stored_value_projection_own_result_unresolved',), None
    return operation, (), None


def projection(ctx, target, shared):
    """Return a completed conditional stored recipe, or None for a non-READ.

    ACTIVE keys are not partially published cache entries. A cycle increments
    a generation shared with the general source walker, so ancestors cannot
    cache failures dependent on an unfinished parent proof. Depth exhaustion
    truncates the shared analysis rather than granting a successful prefix.
    """
    if type(shared) is not ValidityBudget:
        raise TypeError('stored value projection requires exact shared ValidityBudget')
    if not ctx.program.stored_value_reads:
        return None
    if target is None or type(target) is Unresolved:
        _spend(shared, 'queries')
        return _receipt(ctx, target, shared, gaps=('stored_value_projection_target_unobserved',))
    if type(target) is not ValueOccurrence:
        raise TypeError('stored value projection requires an original ValueOccurrence')
    if ctx.values.get(target.id) != target:
        _spend(shared, 'queries', target=target)
        return _receipt(ctx, target, shared, gaps=('stored_value_projection_target_unobserved',))
    definition = ctx.core_values.get(target.value)
    if type(definition) not in (DataValue, ReferenceValue):
        return None
    if not _spend(shared, 'queries', target=target):
        return _receipt(ctx, target, shared, gaps=('stored_value_projection_budget',),
                        cursor={'phase': 'lookup', 'target': target.id})
    cache = getattr(shared, '_stored_projection_receipts', None)
    if cache is None:
        cache = shared._stored_projection_receipts = {}
    key = ctx, target.id
    if key in cache:
        cached = cache[key]
        if cached is not None and cached['recipe'] is not None and ctx.issues:
            return _receipt(ctx, target, shared, declaration=cached['declaration'],
                            operation=cached['operation'], sources_report=cached['sources_report'],
                            gaps=(*cached['gaps'], 'stored_value_projection_context_conflict'),
                            cursor=cached['cursor'])
        return cached
    index, gaps, cursor = _read_index(ctx, shared)
    if index is None:
        return _receipt(ctx, target, shared, gaps=gaps, cursor=cursor)
    declarations = index.get(target.value, ())
    if not declarations:
        cache[key] = None
        return None
    selected, unresolved = [], []
    for candidate_index, (declaration, position) in enumerate(declarations):
        if not _spend(shared, 'read_candidates', target=target):
            return _receipt(ctx, target, shared, gaps=('stored_value_projection_budget',),
                            cursor={'phase': 'read_candidates', 'target': target.id,
                                    'candidate_index': candidate_index})
        operation, gaps, cursor = _producer(ctx, target, declaration, position, shared)
        if shared.truncated:
            return _receipt(ctx, target, shared, declaration=declaration,
                            operation=operation, gaps=gaps, cursor=cursor)
        if gaps:
            unresolved.append((declaration, operation, gaps, cursor))
        else:
            selected.append((declaration, operation))
    if len(selected) != 1:
        gaps = ['stored_value_projection_read_ambiguous'] if len(declarations) > 1 else []
        for _, _, missing, _ in unresolved:
            gaps.extend(code for code in missing if code not in gaps)
        return _receipt(ctx, target, shared,
                        declaration=declarations[0][0] if len(declarations) == 1 else None,
                        operation=unresolved[0][1] if len(unresolved) == 1 else None,
                        gaps=tuple(gaps),
                        cursor=next((row[3] for row in unresolved if row[3] is not None), None))
    declaration, operation = selected[0]
    active = getattr(shared, '_stored_projection_active', None)
    if active is None:
        active = shared._stored_projection_active = set()
    if key in active:
        shared._stored_projection_cycle_generation = getattr(
            shared, '_stored_projection_cycle_generation', 0) + 1
        return _receipt(ctx, target, shared, declaration=declaration, operation=operation,
                        gaps=('stored_value_projection_cycle',),
                        cursor={'phase': 'active', 'target': target.id})
    if len(active) >= _DEPTH_LIMIT:
        shared.mark_truncated('stored_value_projection.depth',
                              'stored-value source analysis depth limit exceeded')
        return _receipt(ctx, target, shared, declaration=declaration, operation=operation,
                        gaps=('stored_value_projection_depth_limit',),
                        cursor={'phase': 'depth', 'target': target.id, 'limit': _DEPTH_LIMIT})
    generation = getattr(shared, '_stored_projection_cycle_generation', 0)
    active.add(key)
    try:
        from .stored_values import stored_value_sources
        report = stored_value_sources(ctx, declaration.result, operation.id, shared=shared)
    finally:
        active.remove(key)
    gaps = list(report['gaps'])
    recipe = report['recipe']
    source = report['source_value']
    if (report['match'] is not True or shared.truncated or recipe is None or ctx.issues):
        recipe = None
        if ctx.issues:
            gaps.append('stored_value_projection_context_conflict')
    elif (source is None or ctx.values.get(source.id) != source
          or recipe.get('source') != source.id or recipe.get('target') != target.id
          or recipe.get('rule') != 'DECLARED_STORED_VALUE'
          or report['read'] is None or report['read']['result'] != target):
        recipe = None
        gaps.append('stored_value_projection_recipe_unresolved')
    receipt = _receipt(ctx, target, shared, declaration=declaration, operation=operation,
                       sources_report=report, recipe=recipe, gaps=tuple(gaps),
                       cursor=report['cursor'])
    if (not shared.truncated
            and generation == getattr(shared, '_stored_projection_cycle_generation', 0)):
        cache[key] = receipt
    return receipt


__all__ = ['projection']

"""Bounded interpretation of original Reference evaluation sources.

This is a query-local reverse view of canonical ports, not an alias table.
Expected sources are supplied independently.  Known calls are opened at their
exact exit kind/slot and entry actual tuple; unknown or cyclic routes survive
in the denominator.  No result establishes a native type or object identity.
"""
from .model import (BlockArgument, CompletionResult, ExitKind, InvokeLiteralResult,
                    LiteralOrigin, OperationResult, ReferenceValue, TerminatorKind)
from .protocols import ContractResult, OwnedUse, StaticProtocolGap
from .structured import ControlEdgeReference


def _prepare(ctx):
    if hasattr(ctx, '_evaluated_source_indexes'):
        return ctx._evaluated_source_indexes
    creates = {row.operation: row for row in ctx.graph.resumable_creates}
    literals = {row.site: row for row in ctx.graph.literal_evaluations}
    result = creates, literals
    ctx._evaluated_source_indexes = result
    ctx._evaluated_source_cache = {}
    ctx.preparation['evaluated_source_creates'] = len(creates)
    ctx.preparation['evaluated_source_literals'] = len(literals)
    return result


def _local(ctx, choices, region):
    return ctx.selected_edges(choices, region=region)


def _case(*, origin=None, recipe=None, frames=(), choices=(), create=None,
          body=None, kind=None, current=None, gaps=(), complete=True):
    return {'origin': origin, 'recipe': recipe, 'caller_context': tuple(frames),
            'cfg_choices': tuple(choices), 'create': create, 'body': body,
            'kind': kind, 'current': current, 'gaps': tuple(gaps),
            'inventory_complete': complete,
            'source_runtime_verified': False, 'runtime_identity_verified': False}


def evaluated_sources(ctx, expected, actual, choices=(), *, role='DIRECT_INPUT'):
    """Resolve every original source case under one shared flow and budget.

    ``kind`` is a declared ResumableKind, ``NON_ITERATOR`` for an exact builtin
    literal, or None.  Kind classification and fresh expected-to-actual copy
    remain separate.  In particular, a mixed must-copy failure is never a
    license to omit another return/incoming source.
    """
    if type(actual) is not OwnedUse:
        raise TypeError('evaluated sources require an exact original OwnedUse')
    creates, literals = _prepare(ctx)
    guards = ctx.selected_edges(choices)
    key = expected, actual, guards, role
    if key in ctx._evaluated_source_cache:
        return ctx._evaluated_source_cache[key]
    binding = ctx.bind(expected, actual, guard=guards or None)
    original = ctx.origins(actual, guard=guards or None)
    rows = []

    def unknown(origin, frames, selected, code, *, recipe=None, complete=False):
        return [_case(origin=origin, recipe=recipe, frames=frames, choices=selected,
                      gaps=(code,), complete=complete)]

    def combine(selected, edge):
        try:
            merged = ctx.selected_edges((*selected, edge))
        except ValueError:
            return None
        return None if ctx.selection_ambiguity(merged) is not None else merged

    def walk_value(value_id, consumer, frames, selected, trail):
        if not ctx.spend('await_source_values'):
            return unknown(None, frames, selected, 'await_source_budget_exhausted')
        value = ctx.values[value_id]
        stamp = value_id, tuple(frame.id for frame in frames), selected
        if stamp in trail:
            return unknown(value.origin, frames, selected, 'await_source_cycle_unresolved')
        trail = trail | {stamp}
        origin = value.origin
        from .literal_sources import ExactLiteralOrigin
        if type(origin) in (LiteralOrigin, ExactLiteralOrigin):
            return [_case(origin=origin, frames=frames, choices=selected,
                          kind='NON_ITERATOR', current=True)]
        if type(origin) is OperationResult:
            return result_source(origin, consumer, frames, selected, trail)
        if type(origin) is not BlockArgument:
            return unknown(origin, frames, selected, 'await_source_origin_uninterpreted', complete=True)
        block = ctx.blocks[origin.block]
        region = value.region
        if origin.block == ctx.regions[region].entry:
            if frames and frames[-1].callee == region:
                call = frames[-1]
                actuals = (call.invoke_arguments if call.terminator is not None
                           and call.terminator.kind is TerminatorKind.INVOKE else call.call_arguments)
                if origin.index >= len(actuals):
                    return unknown(origin, frames, selected, 'await_source_entry_actual_missing')
                owned = OwnedUse(call.id, actuals[origin.index])
                return walk_value(ctx.owned_use(owned.operation, owned.use).value, owned,
                                  frames[:-1], selected, trail)
            return unknown(origin, frames, selected, 'await_source_external_formal', complete=True)
        _, _, incoming, reached, _ = ctx._edges(region)
        candidates = incoming[block.id]
        selected_by_op = {edge.operation: edge.successor_index for edge in _local(ctx, selected, region)}
        target_choices = {ctx.operations[edge.operation].terminator.successors[edge.successor_index].block:
                          (edge.operation, edge.successor_index) for edge in _local(ctx, selected, region)}
        found = []
        for parent, edge in candidates:
            if not ctx.spend('await_source_incoming'):
                found.extend(unknown(origin, frames, selected, 'await_source_budget_exhausted'))
                break
            op_id, ordinal, target, _ = edge
            if (parent not in reached or op_id in selected_by_op and selected_by_op[op_id] != ordinal
                    or target in target_choices and target_choices[target] != (op_id, ordinal)):
                continue
            operation = ctx.operations[op_id]
            chosen = combine(selected, ControlEdgeReference(op_id, ordinal))
            if chosen is None:
                found.extend(unknown(origin, frames, selected, 'await_source_visit_context_unresolved'))
                continue
            actual_port = operation.terminator.successors[ordinal].arguments[origin.index]
            if type(actual_port) is CompletionResult:
                found.extend(result_source(InvokeLiteralResult(ControlEdgeReference(op_id, ordinal), actual_port),
                                           consumer, frames, chosen, trail))
            else:
                from .ids import UseID
                if isinstance(actual_port, UseID):
                    owned = OwnedUse(op_id, actual_port)
                    found.extend(walk_value(ctx.owned_use(op_id, actual_port).value, owned,
                                            frames, chosen, trail))
                else:
                    # Saved/resume projections are interpreted by the existing
                    # origins solver at the outer anchor; never guessed here.
                    found.extend(unknown(origin, frames, chosen, 'await_source_saved_projection_unresolved'))
        return found or unknown(origin, frames, selected, 'await_source_incoming_missing')

    def result_source(origin, consumer, frames, selected, trail):
        operation = ctx.operations[origin.operation if type(origin) is OperationResult else origin.edge.operation]
        kind, slot = ExitKind.NORMAL, origin.index if type(origin) is OperationResult else origin.result.index
        if type(origin) is InvokeLiteralResult:
            kind = operation.terminator.successors[origin.edge.successor_index].kind
        create = creates.get(operation.id)
        if create is not None and kind is ExitKind.NORMAL and slot == create.handle_result.index:
            body = ctx.bodies.get(create.body)
            current = ctx.bind(origin, consumer, guard=_local(ctx, selected, ctx.region_of[consumer.operation]) or None)['match']
            return [_case(origin=origin, frames=frames, choices=selected, create=create,
                          body=body, kind=None if body is None else body.kind, current=current,
                          gaps=() if body is not None else ('await_source_body_missing',),
                          complete=body is not None)]
        literal = literals.get(origin)
        if literal is not None:
            from scar.ir.literals import PythonLiteral
            if type(literal.literal) is PythonLiteral:
                return [_case(origin=origin, frames=frames, choices=selected,
                              kind='NON_ITERATOR', current=True)]
        if operation.callee is None:
            return unknown(origin, frames, selected, 'await_source_opaque_result', complete=True)
        if any(frame.callee == operation.callee for frame in frames):
            return unknown(origin, frames, selected, 'await_source_recursive_call_unresolved')
        if not ctx.spend('await_source_call_frames'):
            return unknown(origin, frames, selected, 'await_source_budget_exhausted')
        region = ctx.regions[operation.callee]
        exits = tuple(exit_ for exit_ in region.exits if exit_.kind is kind and slot < len(exit_.types))
        result = []
        for exit_ in exits:
            sites = ctx.index._exit_ports[(region.id, exit_.name, slot)]
            # Prepared original inventory; no sort or fresh index per source.
            for site in sites:
                if not ctx.spend('await_source_terminal_uses'):
                    result.extend(unknown(origin, frames, selected, 'await_source_budget_exhausted'))
                    break
                entry = ctx.blocks[region.entry]
                from .protocol_flow import ProtocolPort
                reach = ctx._fresh_copies(ProtocolPort(None, entry.operations[0], (), 'before'),
                                         guard=_local(ctx, selected, region.id) or None)
                if reach is None:
                    result.extend(unknown(origin, frames, selected, 'await_source_call_path_unresolved'))
                    continue
                if site.operation not in reach:
                    continue
                owned = OwnedUse(site.operation, site.use.id)
                result.extend(walk_value(site.use.value, owned, (*frames, operation), selected, trail))
        return result or unknown(origin, frames, selected, 'await_source_terminal_missing')

    for recipe in original['recipes']:
        if not ctx.spend('await_source_recipes'):
            rows.extend(unknown(recipe.get('origin'), (), guards, 'await_source_budget_exhausted', recipe=recipe))
            break
        context = ctx.recipe_context(recipe)
        selected = guards
        conflict = False
        for (prefix, operation), ordinal in context['choices'].items():
            # Different visits to an identical static operation cannot be
            # flattened into one selected edge. Preserve the unresolved case.
            chosen = combine(selected, ControlEdgeReference(operation, ordinal))
            if chosen is None:
                conflict = True
                break
            selected = chosen
        if recipe['kind'] == 'STATIC_CYCLE' or conflict:
            rows.extend(unknown(recipe['origin'], (), selected, 'await_source_visit_context_unresolved', recipe=recipe))
            continue
        origin = recipe['origin']
        from .literal_sources import ExactLiteralOrigin
        if type(origin) in (OperationResult, InvokeLiteralResult):
            resolved = result_source(origin, actual, (), selected, frozenset())
        elif type(origin) in (LiteralOrigin, ExactLiteralOrigin):
            resolved = [_case(origin=origin, frames=(), choices=selected,
                              kind='NON_ITERATOR', current=True)]
        else:
            resolved = unknown(origin, (), selected, 'await_source_external_formal', complete=True)
        for item in resolved:
            item['recipe'] = recipe
            item['caller_recipe_context'] = context
            item['current'] = (False if binding['match'] is False or recipe.get('freshness') is False
                               else item['current'] if item['current'] is not None else binding['match'])
            rows.append(item)
    complete = (original['source_inventory_complete'] and bool(rows)
                and len(rows) > 0 and all(row['inventory_complete'] for row in rows)
                and not ctx.budget.truncated)
    gaps = [gap for row in rows for gap in row['gaps']]
    if not complete:
        gaps.append('await_source_inventory_unresolved')
    result = {'expected': expected, 'actual': actual, 'role': role, 'binding': binding,
              'cases': tuple(rows), 'inventory_complete': complete,
              'classification_complete': complete and all(row['kind'] is not None for row in rows),
              'gaps': tuple(dict.fromkeys(gaps)),
              'cursor': original['cursor'] or ({'phase': 'await_sources', 'actual': actual}
                                             if ctx.budget.truncated else None),
              'source_runtime_verified': False, 'runtime_identity_verified': False,
              'transformation_authorized': False}
    ctx._evaluated_source_cache[key] = result
    return result


__all__ = ['evaluated_sources']

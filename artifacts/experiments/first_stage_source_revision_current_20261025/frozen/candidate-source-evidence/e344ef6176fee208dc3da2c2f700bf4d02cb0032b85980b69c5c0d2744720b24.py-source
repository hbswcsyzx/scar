"""Demand-bound receipts for original PendingPayload dispatch projections.

A pending token is not its payload. This query follows this selector's actual
original copy ancestry to its constructor, then projects that occurrence's
original payload Use. No expected value, object name or sibling chooses it.
"""
from scar.ir.program.control import PendingDispatchTerminator, PendingPayload
from scar.ir.program.model import BlockArgument, OperationResult, value_type

from .common import Unresolved
from .ids import BlockVisitID, OperationOccurrenceID
from .resumable_flow import value_for_use


def prepare(ctx):
    """Original definitions only; no per-occurrence projection joins."""
    ctx.pending_payload_definitions = {
        row.value: row for row in ctx.program.pending_completions}
    ctx.pending_payload_preparation = {
        'original_definitions': len(ctx.pending_payload_definitions),
        'derived_projections_precomputed': 0,
        'scope': 'canonical original definition index; demand joins use shared query budget'}


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                value_identity_verified=False, transformation_authorized=False)


def _receipt(target, *, definition=None, constructor=None, selector=None,
             token_path=(), payload_use=None, payload_value=None, recipe=None,
             compatibility=None, conflict=False, gaps=()):
    match = False if conflict else True if recipe is not None else None
    return {'definition': definition, 'constructor': constructor,
        'selector': selector, 'token_path': tuple(token_path), 'payload_use': payload_use,
        'payload_value': payload_value, 'target_value': target,
        'binding': {'match': match, 'support': () if recipe is None else (recipe,),
                    'compatibility': compatibility,
                    'gaps': tuple(gaps), **_flags()},
        'recipe': recipe, 'status': 'CONTRADICTED' if conflict else
            'DECLARED' if match is True else 'PARTIAL', 'gaps': tuple(gaps), **_flags()}


def projection(ctx, target, shared):
    """Return None for a different original argument, not a missing projection.

    Successful receipts are query-local and charged before lookup. Cached
    support was paid in this exact shared budget, never a previous query.
    """
    if target is None or type(target) is Unresolved:
        paid = shared.spend('pending_payload_queries', path='pending.payload')
        return _receipt(target, gaps=('pending_payload_target_unobserved',)
                        if paid else ('pending_payload_budget',))
    if type(target.origin) is not BlockVisitID:
        return None
    definition = ctx.core_values[target.value]
    if type(definition.origin) is not BlockArgument:
        return None
    transfer = ctx.incoming.get(target.origin)
    occurrence = None if transfer is None else ctx.occurrences.get(transfer.operation)
    operation = None if occurrence is None else ctx.core_operations[occurrence.operation]
    if operation is None or type(operation.terminator) is not PendingDispatchTerminator:
        return None
    edge = operation.terminator.successors[transfer.successor_index]
    if type(edge.arguments[definition.origin.index]) is not PendingPayload:
        return None
    cache = getattr(shared, '_pending_payload_receipts', None)
    if cache is None:
        cache = shared._pending_payload_receipts = {}
    key = ctx, target.id
    admitted = shared.spend('pending_payload_queries', path='pending.payload')
    if admitted and key in cache:
        return cache[key]
    selected = constructor = pending_definition = payload_use = payload_value = None
    token_path, local, recipe, conflict = [], [], None, False
    compatibility = None
    if not admitted:
        local.append('pending_payload_budget')
    else:
        selected = ctx.uses.get((occurrence.id, operation.terminator.pending))
        token = value_for_use(ctx, selected)
        if token is None or type(token) is Unresolved:
            local.append('pending_payload_selector_unobserved')
        else:
            seen, cursor = set(), token.id
            while cursor not in seen:
                if not shared.spend('pending_payload_token_ancestors', path='pending.payload.token'):
                    local.append('pending_payload_budget')
                    break
                seen.add(cursor)
                previous = ctx.body_original_copy_recipes.get(cursor)
                if previous is None:
                    root = ctx.values.get(cursor)
                    original = None if root is None else ctx.core_values[root.value]
                    pending_definition = (None if root is None else
                        ctx.pending_payload_definitions.get(root.value))
                    if (pending_definition is None or type(original.origin) is not OperationResult
                            or type(root.origin) is not OperationOccurrenceID):
                        local.append('pending_payload_constructor_unobserved')
                        break
                    constructor = ctx.occurrences.get(root.origin)
                    if (constructor is None or constructor.operation != original.origin.operation):
                        local.append('pending_payload_constructor_unobserved')
                        break
                    if pending_definition.port != edge.port:
                        conflict = True
                        local.append('pending_payload_port_conflict')
                        break
                    if pending_definition.payload is None:
                        local.append('pending_payload_definition_without_payload')
                        break
                    if not shared.spend('pending_payload_constructor_use', path='pending.payload.use'):
                        local.append('pending_payload_budget')
                        break
                    payload_use = ctx.uses.get((constructor.id, pending_definition.payload))
                    payload_value = value_for_use(ctx, payload_use)
                    if payload_value is None or type(payload_value) is Unresolved:
                        local.append('pending_payload_use_unobserved')
                    elif value_type(ctx.core_values[payload_value.value]) != value_type(definition):
                        conflict = True
                        local.append('pending_payload_kind_conflict')
                    else:
                        if not shared.spend('pending_payload_compatibility',
                                            path='pending.payload.compatibility'):
                            local.append('pending_payload_budget')
                            break
                        from .resumable_identity import compatible
                        identity_gaps = []
                        compatibility = compatible(ctx, payload_value, target,
                            identity_gaps, 'pending.payload.compatibility')
                        local.extend(gap.code for gap in identity_gaps)
                        if compatibility['status'] == 'CONFLICT':
                            conflict = True
                            local.append('pending_payload_identity_conflict')
                        elif shared.spend('pending_payload_support', len(token_path) + 1,
                                          path='pending.payload.support'):
                            recipe = {'source': payload_value.id, 'target': target.id,
                                'rule': 'ORIGINAL_PENDING_PAYLOAD',
                                'support': (transfer, selected, *token_path,
                                            pending_definition, constructor, payload_use)}
                        else:
                            local.append('pending_payload_budget')
                    break
                token_path.append(previous)
                cursor = previous['source']
            else:
                local.append('pending_payload_token_cycle')
    result = _receipt(target, definition=pending_definition, constructor=constructor,
        selector=selected, token_path=token_path, payload_use=payload_use,
        payload_value=payload_value, recipe=recipe, compatibility=compatibility,
        conflict=conflict, gaps=local)
    if admitted:
        cache[key] = result
    return result


def copy_recipe(ctx, identity, shared):
    """A conditional original port recipe; token/payload are never equated."""
    original = ctx.body_original_copy_recipes.get(identity)
    if original is not None:
        return original, (), False
    receipt = projection(ctx, ctx.values.get(identity), shared)
    if receipt is None:
        return None, (), False
    return receipt['recipe'], receipt['gaps'], receipt['binding']['match'] is False

"""Bind declared state addresses to existing dynamic ports, without alias proof."""
from __future__ import annotations

from copy import deepcopy

from scar.ir.program.model import LiteralOrigin, ReferenceValue, is_literal_origin
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.ids import UseID
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand

from .common import Unresolved
from .coordinates import AccessRef
from .effects import effect_context, resolve_canonical_effect
from .validity_budget import ValidityBudget
from .work import InvokeBoundaryStateEffect


def state_address(ctx, effect, *, budget=4096):
    """Resolve one original effect and its declared address operand occurrences.

    Preparation, canonical graph validation, snapshot replay and final detached
    copying are separate from the budget for dynamic joins. Every original
    refinement remains in ``canonical`` even if an operand join is truncated.
    """
    traversal = ValidityBudget(budget)
    if type(effect) not in (AccessRef, InvokeBoundaryStateEffect):
        raise TypeError('state_address requires AccessRef or InvokeBoundaryStateEffect')
    effect.__post_init__()
    issues, gaps = [], []

    def issue(code, path, message):
        issues.append({'code': code, 'path': path, 'message': message})

    def gap(code, path, message):
        gaps.append({'code': code, 'path': str(path), 'message': message})

    dynamic = resolve_canonical_effect(effect_context(ctx, issue=issue, gap=gap),
                                       effect, 'state_address.effect')
    if issues or dynamic is None:
        raise ValueError('; '.join(row['code'] + ': ' + row['message'] for row in issues)
                         or 'effect does not resolve to an original state interface')
    occurrence = dynamic['operation']
    site = (ExistingAccess(occurrence.operation, effect.index) if type(effect) is AccessRef
            else InvokeStateOperand(occurrence.operation, effect.state_input.use))
    # This is a read-only view of the single canonical graph. It creates no
    # state version, object, producer, use, binding or native relation.
    canonical = ProgramIndex(ctx.program).state_address(site)
    declaration = canonical['refinement']
    sources = canonical['effects']
    items = []
    cursor = None

    def operand(site):
        path = site.use.id.wire
        if not traversal.spend('state_address_operands', path=path):
            return None
        use = ctx.uses.get((occurrence.id, site.use.id))
        value = None
        if use is None or type(use.value) is Unresolved:
            gap('state_address_operand_unobserved', path,
                'this exact operation occurrence has no captured operand value')
        else:
            value = ctx.values[use.value]
        definition = ctx.core_values[site.use.value]
        denotation = None if value is None else ctx.resolved_denotations.get(value.id)
        literal = definition.origin if is_literal_origin(definition.origin) else None
        if value is not None and type(definition) is ReferenceValue and denotation is None:
            gap('state_address_owner_identity_unresolved', path,
                'a captured reference occurrence does not establish an object identity')
        return {'site': site, 'use': use, 'value': value,
                'denotation': denotation, 'literal': literal}

    if traversal.spend('state_address_site', path='state_address'):
        for ordinal, source in enumerate(sources):
            if not traversal.spend('state_address_effects', path=str(ordinal)):
                cursor = {'effect_index': ordinal, 'phase': 'effect'}
                break
            item = {'index': source['index'], 'effect': source['effect'],
                    'owner_use': None, 'resource_use': source['resource_use'],
                    'resource_inventory': (), 'resource_matches': (), 'operands': ()}
            if source['owner_use'] is not None:
                item['owner_use'] = operand(source['owner_use'])
                if item['owner_use'] is None:
                    cursor = {'effect_index': ordinal, 'phase': 'owner'}
                    items.append(item)
                    break
            if source['resource_use'] is not None:
                item['resource_inventory'] = ctx.model.accesses
                matched = []
                for position, access in enumerate(ctx.model.accesses):
                    if not traversal.spend('state_address_resources', path=str(position)):
                        cursor = {'effect_index': ordinal, 'phase': 'resource',
                                  'resource_index': position}
                        break
                    binding = ctx.requirements[access.requirement]
                    if (access.operation == occurrence.id and
                            binding.requirement == source['resource_use'].requirement):
                        matched.append({'access': access, 'binding': binding})
                item['resource_matches'] = tuple(matched)
                if not matched and not traversal.truncated:
                    gap('state_address_resource_unobserved', str(ordinal),
                        'the declared resource Use has no matching captured access')
                if traversal.truncated:
                    items.append(item)
                    break
            operands = []
            for position, original in enumerate(source['operands']):
                bound = operand(original)
                if bound is None:
                    cursor = {'effect_index': ordinal, 'phase': 'operand',
                              'operand_index': position}
                    break
                operands.append(bound)
            item['operands'] = tuple(operands)
            items.append(item)
            if traversal.truncated:
                break
    else:
        cursor = {'effect_index': 0, 'phase': 'site'}
    if declaration is None:
        gap('state_address_refinement_missing', str(site),
            'the original coarse effect has no declared address refinement')
    elif declaration.coverage.value == 'PARTIAL':
        gap('state_address_partial_declaration', str(site),
            'unlisted address effects remain possible within the original state domain')
    before = dynamic.get('before') if type(effect) is AccessRef else dynamic.get('input')
    after = dynamic.get('after') if type(effect) is AccessRef else dynamic.get('post')
    completion = None
    if type(effect) is InvokeBoundaryStateEffect and not traversal.truncated:
        transfer = dynamic['actual_transfer']
        if transfer is not None:
            for position, port in enumerate(canonical['completions']):
                if not traversal.spend('state_address_completion', path=str(position)):
                    cursor = {'effect_index': len(sources), 'phase': 'completion',
                              'completion_index': position}
                    break
                if port['successor_index'] == transfer.successor_index:
                    formal = ctx.results.get((transfer.target, port['formal'].id))
                    forwarded = (ctx.uses.get((occurrence.id, port['argument']))
                                 if isinstance(port['argument'], UseID) else None)
                    completion = {'port': port, 'formal': formal, 'forwarded_use': forwarded}
                    if isinstance(port['argument'], UseID) and (
                            forwarded is None or type(forwarded.value) is Unresolved):
                        gap('state_address_forward_unobserved', str(site),
                            'the actual edge forwards an original Use whose value was not captured')
                    if formal is None:
                        gap('state_address_completion_unobserved', str(site),
                            'the actual landing state formal was not captured')
                    break
    next_effect = len(sources) if cursor is None else cursor['effect_index']
    return deepcopy({
        'status': 'TRUNCATED' if traversal.truncated else 'PARTIAL' if gaps else 'DECLARED',
        'site': site, 'canonical': canonical, 'dynamic': dynamic,
        'before': before, 'after': after, 'completion': completion,
        'activation': dynamic['activation'], 'run': dynamic['run'],
        'items': tuple(items), 'cursor': cursor,
        'pending': tuple(range(next_effect, len(sources))),
        'budget': {'limit': traversal.limit, 'used': traversal.used,
                   'remaining': traversal.remaining, 'costs': dict(traversal.costs),
                   'truncated': traversal.truncated,
                   'scope': 'dynamic effect/operand/resource joins; preparation and copying separate'},
        'gaps': tuple((*gaps, *traversal.gaps)),
        'validation_gaps': tuple(ctx.gaps),
        'coarse_dependencies_retained': True,
        'address_interpretation_verified': False,
        'source_runtime_verified': False, 'value_identity_verified': False,
        'transformation_authorized': False,
    })


__all__ = ['state_address']

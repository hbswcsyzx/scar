"""Attach literal declarations to exact existing producer occurrences.

Content and source declarations neither create values nor establish Python
object identity, native interpretation, purity or transformation permission.
"""
from __future__ import annotations

from copy import deepcopy

from scar.ir.program.model import InvokeLiteralResult, OperationResult, ReferenceValue
from scar.ir.program.queries import ProgramIndex

from .common import Unresolved
from .ids import OperationOccurrenceID
from .validity_budget import ValidityBudget


def validate_literal_request(site, occurrence, budget):
    """Reject malformed requests before fresh external snapshot preparation."""
    ValidityBudget(budget)
    if type(site) not in (OperationResult, InvokeLiteralResult):
        raise TypeError('literal evaluation requires an original result site')
    site.__post_init__()
    if type(occurrence) is not OperationOccurrenceID:
        raise TypeError('literal evaluation requires an exact operation occurrence ID')


def literal_evaluation(ctx, site, occurrence, *, budget=4096):
    """Bind a single declared result without changing its original producer.

    The budget measures operand and result joins. Canonical validation, fresh
    snapshots, static indexing and detached copying have separate costs.
    """
    validate_literal_request(site, occurrence, budget)
    traversal = ValidityBudget(budget)
    original = ctx.occurrences.get(occurrence)
    if original is None:
        raise ValueError('literal evaluation operation occurrence is not captured')
    canonical = ProgramIndex(ctx.program).literal_evaluation(site)
    if original.operation != canonical['operation'].id:
        raise ValueError('literal result site belongs to another operation')
    activation = ctx.activation_of(occurrence)
    transfer = ctx.outgoing.get(occurrence) if type(site) is InvokeLiteralResult else None
    inputs, gaps = [], []
    cursor = None
    result = None
    not_taken = (type(site) is InvokeLiteralResult and transfer is not None
                 and transfer.successor_index != canonical['successor_index'])

    def gap(code, path, message):
        gaps.append({'code': code, 'path': str(path), 'message': message})

    def bind_value(value):
        if value is None or type(value) is Unresolved:
            return None
        return {'occurrence': value,
                'definition': ctx.core_values[value.value],
                'denotation': ctx.resolved_denotations.get(value.id)}

    if traversal.spend('literal_site', path='literal_evaluation'):
        for position, use_site in enumerate(canonical['uses']):
            if not traversal.spend('literal_operands', path=use_site.use.id.wire):
                cursor = {'phase': 'operand', 'operand_index': position}
                break
            captured = ctx.uses.get((occurrence, use_site.use.id))
            value = None
            if captured is None or type(captured.value) is Unresolved:
                gap('literal_operand_unobserved', use_site.use.id.wire,
                    'this exact operation occurrence has no captured original operand')
            else:
                value = ctx.values[captured.value]
            inputs.append({'site': use_site, 'use': captured, 'value': bind_value(value)})
        if not traversal.truncated and not not_taken:
            if type(site) is InvokeLiteralResult and transfer is None:
                gap('literal_completion_unobserved', occurrence.wire,
                    'no actual completion selects this declared NORMAL result')
            elif traversal.spend('literal_result', path=canonical['result'].id.wire):
                owner = transfer.target if type(site) is InvokeLiteralResult else occurrence
                captured = ctx.results.get((owner, canonical['result'].id))
                result = bind_value(captured)
                if result is None:
                    gap('literal_result_unobserved', canonical['result'].id.wire,
                        'the original producer or actual landing result was not captured')
                elif (type(canonical['result']) is ReferenceValue
                      and result['denotation'] is None):
                    gap('literal_reference_identity_unresolved', canonical['result'].id.wire,
                        'literal content/source does not establish an object identity')
            else:
                cursor = {'phase': 'result'}
    else:
        cursor = {'phase': 'site'}
    if canonical['row'] is None:
        gap('literal_declaration_missing', str(site),
            'the original result has no literal content/source declaration')
    status = ('TRUNCATED' if traversal.truncated else 'NOT_TAKEN' if not_taken
              else 'PARTIAL' if gaps else 'DECLARED')
    next_operand = (cursor.get('operand_index', 0) if cursor is not None
                    and cursor['phase'] in ('site', 'operand') else len(canonical['uses']))
    return deepcopy({
        'status': status, 'canonical': canonical, 'operation': original,
        'activation': activation, 'actual_transfer': transfer,
        'inputs': tuple(inputs), 'result': result, 'cursor': cursor,
        'pending_operands': tuple(range(next_operand, len(canonical['uses']))),
        'budget': {'limit': traversal.limit, 'used': traversal.used,
                   'remaining': traversal.remaining, 'costs': dict(traversal.costs),
                   'truncated': traversal.truncated,
                   'scope': 'dynamic operand/result joins; preparation and copying separate'},
        'gaps': tuple((*gaps, *traversal.gaps)),
        'validation_gaps': tuple(ctx.gaps),
        'producer_and_effects_retained': True,
        'source_runtime_verified': False, 'value_identity_verified': False,
        'transformation_authorized': False,
    })


__all__ = ['literal_evaluation', 'validate_literal_request']

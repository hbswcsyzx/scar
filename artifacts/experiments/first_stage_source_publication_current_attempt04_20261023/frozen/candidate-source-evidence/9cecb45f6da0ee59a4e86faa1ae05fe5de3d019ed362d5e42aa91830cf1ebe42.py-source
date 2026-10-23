"""Detached views of explicitly declared dynamic call/activation links.

Routes come from the validated canonical interface.  This query neither picks
a callee by source/name/value nor creates another argument or producer table.
"""
from __future__ import annotations

from copy import deepcopy

from .coordinates import _identifier
from .ids import OperationOccurrenceID


def _view(resolved):
    return {**resolved, 'status': 'DECLARED',
            'source_runtime_verified': False,
            'runtime_identity_verified': False,
            'value_identity_verified': False,
            'transformation_authorized': False}


def call_activation(ctx, identity):
    """Return original ports for one association, including unresolved ends."""
    from .ids import CallActivationID

    _identifier(identity, CallActivationID, 'call activation query ID')
    return deepcopy(_view(ctx.resolved_call_activations[identity]))


def call_entries(ctx, caller_id):
    """List this caller's declared links without inferring a missing one."""
    from .validation import ExecutionIssue

    _identifier(caller_id, OperationOccurrenceID, 'call caller occurrence ID')
    caller = ctx.occurrences[caller_id]
    operation = ctx.core_operations[caller.operation]
    callee = None if operation.callee is None else ctx.regions[operation.callee]
    entries = tuple(_view(ctx.resolved_call_activations[identity])
                    for identity in ctx.call_activations_by_caller.get(caller_id, ()))
    status = 'DECLARED' if entries else 'MISSING' if callee is not None else 'NO_DECLARED_CALLEE'
    gaps = tuple(gap for entry in entries for gap in entry['gaps'])
    if status == 'MISSING':
        gaps = (*gaps, ExecutionIssue('call_activation_missing', str(caller_id),
            'static callee has no explicit association to a dynamic activation; source/name/value do not select one'))
    return deepcopy({'caller': caller, 'operation': operation, 'callee': callee,
        'entries': entries, 'status': status, 'gaps': gaps,
        'source_runtime_verified': False,
        'runtime_identity_verified': False,
        'value_identity_verified': False,
        'transformation_authorized': False})


__all__ = ['call_activation', 'call_entries']

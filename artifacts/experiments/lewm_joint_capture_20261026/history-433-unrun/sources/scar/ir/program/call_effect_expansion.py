"""Declared complete effect implementations of original synchronous calls.

The relation expands effects into the existing callee CFG. It asserts neither
purity nor state preservation and grants no source/runtime authority. Entry
and exit effects belong to that CFG as ordinary original operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .ids import OperationID, RegionID


@dataclass(frozen=True, slots=True)
class CallEffectExpansion:
    operation: OperationID
    callee: RegionID

    def __post_init__(self):
        if type(self.operation) is not OperationID:
            raise TypeError('call effect expansion operation requires exact OperationID')
        if type(self.callee) is not RegionID:
            raise TypeError('call effect expansion callee requires exact RegionID')
        self.operation.__post_init__()
        self.callee.__post_init__()


CALL_EFFECT_EXPANSION_RECORD_TAGS = MappingProxyType({
    CallEffectExpansion: ('kind', 'CALL_EFFECT_EXPANSION'),
})


def call_effect_expansion_errors(graph):
    """Check the new relation; canonical interfaces retain their core checks."""
    from .model import ProgramGraph, TerminatorKind

    if not isinstance(graph, ProgramGraph):
        raise TypeError('call effect expansion validation requires ProgramGraph')
    operations = {operation.id: operation for operation in graph.operations}
    regions = {region.id for region in graph.regions}
    issues, seen = [], set()
    for row in graph.call_effect_expansions:
        row.__post_init__()
        path = str(row.operation)
        if row.operation in seen:
            issues.append(('call_effect_expansion_duplicate', path,
                           'one original call has at most one complete effect expansion'))
        seen.add(row.operation)
        operation = operations.get(row.operation)
        if operation is None:
            issues.append(('call_effect_expansion_operation', path,
                           'effect expansion references a nonexistent original operation'))
        if row.callee not in regions:
            issues.append(('call_effect_expansion_region', path,
                           'effect expansion references a nonexistent original callee region'))
        if operation is None:
            continue
        if operation.callee is None:
            issues.append(('call_effect_expansion_callee', path,
                           'primitive operations have no declared callee effect implementation'))
        elif operation.callee != row.callee:
            issues.append(('call_effect_expansion_callee', path,
                           'effect expansion must reference this exact original callee'))
        if (operation.terminator is not None
                and operation.terminator.kind is not TerminatorKind.INVOKE):
            issues.append(('call_effect_expansion_call', path,
                           'effect expansion requires an ordinary CALL or synchronous INVOKE'))
    return tuple(issues)


__all__ = ['CallEffectExpansion', 'CALL_EFFECT_EXPANSION_RECORD_TAGS',
           'call_effect_expansion_errors']

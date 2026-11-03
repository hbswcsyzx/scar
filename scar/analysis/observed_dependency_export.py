"""Normalized observation DTOs; readback does not revalidate source or trace.

Original static points, conditions and edges use the common tables. Runtime
CALL scopes and interface points have separate tables and never become static
DependencyContexts or duplicated program graphs.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from scar.analysis.contextual_call_export import (
    _MAX_BYTES, _Reader, _TABLES, _array, _object, _preflight,
)
from scar.analysis.observed_call_bindings import ObservedCallBinding
from scar.analysis.observed_function_interfaces import ObservedFunctionInterface
from scar.analysis.program_dependency_export import _Tables
from scar.ir.program.call_edges import CallTraceFile
from scar.ir.program.observed_dependencies import (
    ObservedCallScope, ObservedDependencyEdge, ObservedDependencyFrontier,
    ObservedPortPhase, ObservedPortPoint,
)
from scar.ir.record_codec import decode, encode, loads


_OBSERVED_TABLES = ('observed_scopes', 'observed_points')
_FLAGS = {'observation_only': True, 'target_set_closed': False,
    'normal_landing_observed': False, 'whole_program_complete': False,
    'transformation_authorized': False}


@dataclass(frozen=True, slots=True)
class ObservedDependencySnapshot:
    run_scope: str
    scopes: tuple[ObservedCallScope, ...]
    bindings: tuple[ObservedCallBinding, ...]
    interfaces: tuple[ObservedFunctionInterface, ...]
    edges: tuple[ObservedDependencyEdge, ...]
    frontiers: tuple[ObservedDependencyFrontier, ...]
    capture_files: tuple[CallTraceFile, ...]

    def __post_init__(self):
        if type(self.run_scope) is not str or re.fullmatch(r'[0-9a-f]{64}', self.run_scope) is None:
            raise ValueError('observed snapshot needs its original run scope')
        for rows, kind in ((self.scopes, ObservedCallScope), (self.bindings, ObservedCallBinding),
                (self.interfaces, ObservedFunctionInterface), (self.edges, ObservedDependencyEdge),
                (self.frontiers, ObservedDependencyFrontier), (self.capture_files, CallTraceFile)):
            if type(rows) is not tuple:
                raise TypeError('observed snapshot rows must be immutable tuples')
            for row in rows:
                if type(row) is not kind:
                    raise TypeError('observed snapshot requires exact ' + kind.__name__)
                post = getattr(row, '__post_init__', None)
                if post is not None:
                    post()
        scopes = {}
        for scope in self.scopes:
            key = scope.caller, scope.attempt_index
            if scope.run_scope != self.run_scope or key in scopes:
                raise ValueError('observed snapshot mixed runs or duplicate CALL scopes')
            scopes[key] = scope
        binding_set = set(self.bindings)
        if len(binding_set) != len(self.bindings):
            raise ValueError('observed snapshot contains duplicate CALL bindings')
        for binding in self.bindings:
            scope = scopes.get((binding.target.caller, binding.target.attempt_index))
            if (binding.run_scope != self.run_scope or scope is None
                    or scope.attempt_anchor != binding.attempt_anchor
                    or scope.target_anchor != binding.target_anchor):
                raise ValueError('observed binding changed its declared run/CALL scope')
        if len(self.scopes) != len(self.bindings):
            raise ValueError('observed scope has no corresponding original CALL binding')
        for item in self.interfaces:
            if item.binding not in binding_set:
                raise ValueError('observed function interface lacks its original CALL binding')
            scope = scopes[item.entry.caller, item.entry.attempt_index]
            if (scope.callee != item.entry.callee or scope.entry_anchor != item.entry_anchor
                    or scope.frame_entry != item.frame_entry
                    or scope.exit_anchor != (None if item.observed_exit is None
                                             else item.observed_exit.anchor)):
                raise ValueError('observed function interface changed its activation/event scope')
        scope_set = set(self.scopes)
        if any(edge.source.scope not in scope_set for edge in self.edges) or any(
                frontier.point.scope not in scope_set for frontier in self.frontiers):
            raise ValueError('observed relation references an undeclared CALL scope')
        for item in self.capture_files:
            if (any(type(value) is not str or not value for value in (item.path, item.family))
                    or type(item.raw_sha256) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item.raw_sha256) is None
                    or type(item.process_id) is not int or item.process_id < 1
                    or any(type(value) is not int or value < 0
                           for value in (item.raw_bytes, item.lines))):
                raise ValueError('observed capture receipt has invalid typed fields')


class _ObservedTables(_Tables):
    def __init__(self):
        super().__init__()
        for name in _OBSERVED_TABLES:
            self.tables[name], self.indices[name] = [], {}

    def scope(self, value):
        return self.put('observed_scopes', value, lambda: encode(value))

    def observed_point(self, value):
        return self.put('observed_points', value, lambda: {
            'original': self.point(value.original), 'scope': self.scope(value.scope),
            'phase': value.phase.value})

    def pack(self, value):
        if type(value) is ObservedCallScope:
            return {'observed_scope': self.scope(value)}
        if type(value) is ObservedPortPoint:
            return {'observed_point': self.observed_point(value)}
        return super().pack(value)


class _ObservedReader(_Reader):
    def __init__(self, document):
        super().__init__(document)
        for name in _OBSERVED_TABLES:
            rows = _array(document[name], name)
            self.cache[name], self.states[name] = [None] * len(rows), [0] * len(rows)

    def row(self, name, row):
        if name == 'observed_scopes':
            return decode(ObservedCallScope, row)
        if name == 'observed_points':
            _object(row, ('original', 'scope', 'phase'), 'observed point')
            return ObservedPortPoint(self.ref('points', row['original']),
                self.ref('observed_scopes', row['scope']), decode(ObservedPortPhase, row['phase']))
        return super().row(name, row)

    def unpack(self, expected, wire, depth=0):
        if expected in (ObservedCallScope, ObservedPortPoint):
            tag, table = ('observed_scope', 'observed_scopes') if expected is ObservedCallScope \
                else ('observed_point', 'observed_points')
            _object(wire, (tag,), 'typed ' + tag + ' reference')
            return self.ref(table, wire[tag])
        return super().unpack(expected, wire, depth)

    def validate_tables(self):
        super().validate_tables()
        for name in _OBSERVED_TABLES:
            seen = set()
            for index in range(len(self.cache[name])):
                value = self.ref(name, index)
                if value in seen:
                    raise ValueError('duplicate normalized ' + name + ' table record')
                seen.add(value)


def export_observed_dependencies(provider):
    """Export an already checked provider; observations authorize no change."""
    provider.check()
    snapshot = ObservedDependencySnapshot(provider.run_scope, provider.scopes,
        provider.bindings, provider.interfaces, provider.edges, provider.frontiers,
        provider.capture_files)
    table = _ObservedTables()
    packed = table.pack(snapshot)
    return {'schema': 'scar.observed-dependencies', 'schema_version': 1,
        'snapshot': packed, **table.tables, **_FLAGS}


def read_observed_dependencies(document):
    """Strict DTO readback only: no original trace, source or receipt replay."""
    if type(document) in (str, bytes):
        if len(document.encode('utf-8') if type(document) is str else document) > _MAX_BYTES:
            raise ValueError('observed dependency document byte budget exceeded')
        document = loads(document)
    _preflight(document)
    _object(document, {'schema', 'schema_version', 'snapshot', *_FLAGS,
        *_TABLES, *_OBSERVED_TABLES}, 'observed dependencies')
    if (document['schema'] != 'scar.observed-dependencies'
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or any(document[name] is not value for name, value in _FLAGS.items())):
        raise ValueError('unsupported observed dependency schema/claims')
    reader = _ObservedReader(document)
    result = reader.unpack(ObservedDependencySnapshot, document['snapshot'])
    reader.validate_tables()
    return result


__all__ = ['ObservedDependencySnapshot', 'export_observed_dependencies',
           'read_observed_dependencies']

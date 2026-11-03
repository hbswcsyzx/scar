"""Normalized observation DTOs; readback does not revalidate source or trace.

Original static points, conditions and edges use the common tables. Runtime
CALL scopes and interface points have separate tables and never become static
DependencyContexts or duplicated program graphs.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import re

from scar.analysis.contextual_call_export import (
    _MAX_BYTES, _Reader, _TABLES, _array, _object, _preflight,
)
from scar.analysis.observed_call_bindings import ObservedCallBinding
from scar.analysis.observed_function_interfaces import ObservedFunctionInterface
from scar.analysis.program_dependency_export import _Tables
from scar.ir.program.call_edges import CallTraceFile
from scar.ir.program.native_callables import NativeCallableMetadata, NativeCarrier
from scar.ir.program.dependencies import GraphNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.observed_dependencies import (
    ObservedCallLayout, ObservedCallScope, ObservedDependencyEdge, ObservedDependencyFrontier,
    ObservedNativeCallable, ObservedNativeCallableFrontier, ObservedPortPhase, ObservedPortPoint,
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
    layouts: tuple[ObservedCallLayout, ...] | None = None
    native_callables: tuple[ObservedNativeCallable, ...] | None = None
    native_frontiers: tuple[ObservedNativeCallableFrontier, ...] | None = None
    native_metadata: tuple[NativeCallableMetadata, ...] | None = None
    native_protocols: tuple[GraphNamespace, ...] | None = None
    native_protocol_manifest: SourceArtifactLocator | None = None

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
        _validate_layouts(self.layouts, scope_set, self.bindings, self.edges)
        _validate_native(self, scopes)
        _validate_protocols(self)
        for item in self.capture_files:
            if (any(type(value) is not str or not value for value in (item.path, item.family))
                    or type(item.raw_sha256) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item.raw_sha256) is None
                    or type(item.process_id) is not int or item.process_id < 1
                    or any(type(value) is not int or value < 0
                           for value in (item.raw_bytes, item.lines))):
                raise ValueError('observed capture receipt has invalid typed fields')


_PROTOCOL_PHASES = frozenset((ObservedPortPhase.PROTOCOL_INPUT,
    ObservedPortPhase.DECLARED_NORMAL, ObservedPortPhase.DECLARED_RAISE))


def _validate_protocols(snapshot):
    protocol_edges = tuple(edge for edge in snapshot.edges
        if edge.source.phase in _PROTOCOL_PHASES or edge.target.phase in _PROTOCOL_PHASES)
    namespaces, manifest = snapshot.native_protocols, snapshot.native_protocol_manifest
    if namespaces is None and manifest is None:
        if protocol_edges:
            raise ValueError('declared protocol ports require their original template declarations')
        return
    if (type(namespaces) is not tuple or type(manifest) is not SourceArtifactLocator
            or snapshot.native_metadata is None):
        raise TypeError('declared protocols need their original namespaces, manifest and callable capture')
    manifest.__post_init__()
    known = set()
    for namespace in namespaces:
        if type(namespace) is not GraphNamespace or namespace.source_body is not None:
            raise TypeError('a protocol template is a canonical graph, not a Python source body')
        namespace.__post_init__()
        if namespace in known:
            raise ValueError('duplicate shared protocol template')
        known.add(namespace)
    bindings = {(item.target.caller, item.target.attempt_index): item for item in snapshot.bindings}
    native = {item.scope: item for item in snapshot.native_callables
              if item.fact.carrier is not NativeCarrier.UNKNOWN}
    for edge in protocol_edges:
        binding = bindings[edge.source.scope.caller, edge.source.scope.attempt_index]
        if edge.source.scope not in native or not any(
                condition.domain == 'SCAR_NATIVE_ABI' and condition.name == 'DECLARED_CALL_PROTOCOL'
                and condition.subject == binding.call
                for condition in edge.template.conditions):
            raise ValueError('a protocol route needs its supported callable fact and declaration condition')
        for port in (edge.source, edge.target):
            if port.phase is ObservedPortPhase.PROTOCOL_INPUT and port.original.namespace not in known:
                raise ValueError('protocol input belongs to an undeclared shared template')
            if port.phase in (ObservedPortPhase.DECLARED_NORMAL, ObservedPortPhase.DECLARED_RAISE) \
                    and port.original.namespace not in known | {binding.call.namespace}:
                raise ValueError('declared completion changed its original caller/template namespace')


def _validate_native(snapshot, scopes):
    rows = (snapshot.native_callables, snapshot.native_frontiers, snapshot.native_metadata)
    if all(value is None for value in rows):
        return  # Legacy NOT_RECORDED, not an empty capture or a native ABI choice.
    if any(type(value) is not tuple for value in rows):
        raise TypeError('recorded native companion needs all immutable fact/frontier/metadata collections')
    bindings = {(binding.target.caller, binding.target.attempt_index): binding
                for binding in snapshot.bindings}
    seen = set()
    for item in snapshot.native_callables:
        if type(item) is not ObservedNativeCallable:
            raise TypeError('observed snapshot requires exact ObservedNativeCallable')
        item.__post_init__()
        key = item.fact.caller, item.fact.attempt_index
        binding = bindings.get(key)
        if (key in seen or scopes.get(key) != item.scope or binding is None
                or item.call.original != binding.call or item.callable.original != binding.callable
                or item.fact.callable_reference != binding.target.callable_reference):
            raise ValueError('native callable fact changed its original static binding/target token')
        seen.add(key)
    for item in snapshot.native_frontiers:
        if type(item) is not ObservedNativeCallableFrontier:
            raise TypeError('observed snapshot requires exact ObservedNativeCallableFrontier')
        item.__post_init__()
        key = item.fact.caller, item.fact.attempt_index
        if item.run_scope != snapshot.run_scope or key in seen or key in scopes:
            raise ValueError('unbound native fact changed its original run or discarded a retained CALL binding')
        seen.add(key)
    metadata_by_process = {}
    for metadata in snapshot.native_metadata:
        if type(metadata) is not NativeCallableMetadata:
            raise TypeError('observed native metadata must retain its exact typed receipt record')
        metadata.__post_init__()
        if (metadata.process_id in metadata_by_process
                or metadata.counts.rows != metadata.file.rows):
            raise ValueError('native callable metadata changed its original process/row denominator')
        metadata_by_process[metadata.process_id] = metadata
    if not metadata_by_process:
        raise ValueError('a recorded native companion needs its original process metadata')
    counts = dict.fromkeys(metadata_by_process, 0)
    for item in (*snapshot.native_callables, *snapshot.native_frontiers):
        process = item.fact.caller.process_id
        metadata = metadata_by_process.get(process)
        if (metadata is None or item.anchor.path != metadata.file.path
                or item.anchor.line_number != item.fact.event_index):
            raise ValueError('native callable fact changed its original process/file/line namespace')
        counts[process] += 1
    if any(counts[process] != metadata.counts.rows
           for process, metadata in metadata_by_process.items()):
        raise ValueError('native callable snapshot omitted an original fact without a frontier')


def _validate_layouts(layouts, scopes, bindings, edges):
    # None means legacy NOT_RECORDED, never an empty or implicit ABI choice.
    if layouts is not None and type(layouts) is not tuple:
        raise TypeError('observed CALL layouts must be an immutable tuple or legacy None')
    calls = {(binding.target.caller, binding.target.attempt_index): binding.call
             for binding in bindings}
    declared = {}
    for layout in layouts or ():
        if type(layout) is not ObservedCallLayout:
            raise TypeError('observed snapshot requires exact ObservedCallLayout')
        layout.__post_init__()
        if layout.scope not in scopes:
            raise ValueError('observed CALL layout references an undeclared scope')
        alternatives = declared.setdefault(layout.scope, {})
        if layout.implicit_prefix in alternatives:
            raise ValueError('duplicate implicit-prefix alternative in observed CALL scope')
        condition = layout.condition
        call = calls.get((layout.scope.caller, layout.scope.attempt_index))
        if call is None or condition is not None and condition.subject != call:
            raise ValueError('observed CALL layout predicate names another original CALL')
        alternatives[layout.implicit_prefix] = layout
    for alternatives in declared.values():
        if len(alternatives) == 2 and any(layout.condition is None
                                        for layout in alternatives.values()):
            raise ValueError('ambiguous observed CALL prefixes need both explicit predicates')
    for edge in edges:
        admitted = {layout.condition for layout in declared.get(edge.source.scope, {}).values()
                    if layout.condition is not None}
        for condition in edge.template.conditions:
            if (condition.domain == 'SCAR_CALL_ABI'
                    and condition.name == 'IMPLICIT_POSITIONAL_PREFIX'
                    and condition not in admitted):
                raise ValueError('observed edge uses an undeclared CALL-prefix predicate')


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
        provider.capture_files, provider.layouts, provider.native_callables,
        provider.native_frontiers, provider.native_metadata,
        provider.native_protocols, provider.native_protocol_manifest)
    if snapshot.layouts is None:
        raise ValueError('observed dependency export requires explicit CALL layouts')
    table = _ObservedTables()
    packed = table.pack(snapshot)
    version = 4 if snapshot.native_protocols is not None else 3
    if version == 3:
        for name in ('native_protocols', 'native_protocol_manifest'):
            packed.pop(name)
    return {'schema': 'scar.observed-dependencies', 'schema_version': version,
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
            or type(document['schema_version']) is not int or document['schema_version'] not in (1, 2, 3, 4)
            or any(document[name] is not value for name, value in _FLAGS.items())):
        raise ValueError('unsupported observed dependency schema/claims')
    wire = document['snapshot']
    missing = {'native_protocols', 'native_protocol_manifest'}
    if document['schema_version'] in (1, 2):
        missing.update(('native_callables', 'native_frontiers', 'native_metadata'))
    if document['schema_version'] == 1:
        missing.add('layouts')
    if document['schema_version'] in (1, 2, 3):
        _object(wire, {'record_type', *(field.name for field in fields(ObservedDependencySnapshot)
                                      if field.name not in missing)}, 'legacy observed snapshot')
        wire = {**wire, **dict.fromkeys(missing)}
    reader = _ObservedReader(document)
    result = reader.unpack(ObservedDependencySnapshot, wire)
    if document['schema_version'] in (2, 3, 4) and result.layouts is None:
        raise ValueError('observed dependency snapshot cannot omit recorded CALL layouts')
    if document['schema_version'] == 4 and result.native_protocols is None:
        raise ValueError('protocol-capable snapshot must retain its template manifest')
    reader.validate_tables()
    return result


__all__ = ['ObservedDependencySnapshot', 'export_observed_dependencies',
           'read_observed_dependencies']

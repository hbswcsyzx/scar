"""Normalized, strictly typed codecs for derived contextual-call queries.

Storage coordinates in the local tables never become program identities.  The
expected Python schema selects every record class; wire record names cannot
import or select constructors.  No original artifact is read or executed here.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from scar.analysis.contextual_call_resolution import ContextualCallResolution
from scar.analysis.program_dependency_export import _Tables
from scar.ir.literals import PythonLiteral
from scar.ir.program.dependencies import (NODE_TYPES, GraphNamespace,
    DependencyFrame, DependencyPoint, DependencyCondition, DependencyEvidence,
    DependencyEdge, DependencyFrontier, DependencyKind, DependencyMeaning,
    DependencyStrength, OpenDependencyContext)
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, loads
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import Identifier, OperationDefinitionID


_TABLES = tuple(_Tables().tables)
_TOP = {'schema', 'schema_version', 'resolution', 'interface_edges',
        'target_executed', 'target_resolution_complete'}
_MAX_BYTES = 256 * 1024 * 1024
_MAX_DEPTH = 192
_MAX_ITEMS = 2_000_000
_POINT_NODE_TYPES = {kind.__name__: kind for kind in NODE_TYPES}
_REFERENCES = {GraphNamespace: ('namespace', 'namespaces'),
    DependencyFrame: ('frame', 'frames'), OpenDependencyContext: ('context', 'contexts'),
    DependencyPoint: ('point', 'points'), DependencyCondition: ('condition', 'conditions'),
    DependencyEvidence: ('evidence', 'evidence'), DependencyEdge: ('edge', 'edges'),
    SourceArtifactLocator: ('locator', 'locators')}


def _object(value, names, detail):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(detail + ' fields mismatch')
    return value


def _array(value, detail):
    if type(value) is not list:
        raise ValueError(detail + ' must be an array')
    return value


def _wire_id(kind, value):
    if type(value) is not str or not value.startswith(kind.prefix + ':'):
        raise ValueError('original typed ID namespace mismatch')
    payload = value[len(kind.prefix) + 1:]
    return decode(kind, {'kind': kind.prefix, 'value': payload, 'wire': value})


def _preflight(document):
    """Reject host-object cycles and non-JSON values before either codec."""
    pending = [(document, 0, False)]
    active, count = set(), 0
    while pending:
        value, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(value)); continue
        count += 1
        if count > _MAX_ITEMS or depth > _MAX_DEPTH:
            raise ValueError('contextual query structural budget exhausted')
        if type(value) in (dict, list):
            if id(value) in active:
                raise ValueError('cyclic contextual query wire object')
            active.add(id(value)); pending.append((value, depth, True))
            if type(value) is dict:
                if any(type(key) is not str for key in value):
                    raise ValueError('contextual query object keys must be strings')
                pending.extend((item, depth + 1, False) for item in value.values())
            else:
                pending.extend((item, depth + 1, False) for item in value)
        elif value is None or type(value) in (str, int, bool):
            pass
        elif type(value) is float and math.isfinite(value):
            pass
        else:
            raise ValueError('contextual query wire contains a non-JSON value')


def _resolution(value):
    if type(value) is not ContextualCallResolution:
        raise TypeError('expected ContextualCallResolution')
    if type(value.call) is not DependencyPoint or type(value.call.node) is not OperationID:
        raise ValueError('contextual resolution needs its original CALL operation point')
    if type(value.targets) is not tuple or type(value.frontiers) is not tuple or type(value.enumerated) is not bool:
        raise ValueError('contextual resolution has invalid typed rows/scope')
    from scar.ir.program.contextual_calls import ContextualCallTarget
    if any(type(target) is not ContextualCallTarget or target.call != value.call for target in value.targets):
        raise ValueError('contextual target belongs to another original CALL')
    if any(type(frontier) is not DependencyFrontier for frontier in value.frontiers):
        raise ValueError('contextual resolution has an untyped frontier')
    value.call.__post_init__()
    for target in value.targets:
        target.__post_init__()
    for frontier in value.frontiers:
        frontier.__post_init__()


def _interface_edges(resolution):
    return tuple(edge for target in resolution.targets for edge in target.dependency_edges())


def export_contextual_call(resolution):
    """Pack each original endpoint, condition and evidence record once."""
    _resolution(resolution)
    table = _Tables()
    packed = table.pack(resolution)
    edges = table.pack(_interface_edges(resolution))
    return {'schema': 'scar.contextual-calls', 'schema_version': 2,
        **table.tables, 'resolution': packed, 'interface_edges': edges,
        'target_executed': False, 'target_resolution_complete': False}


class _Reader:
    def __init__(self, document):
        self.document = document
        self.cache, self.states = {}, {}
        self.schemas = {}
        self.depth = 0
        for name in _TABLES:
            rows = _array(document[name], name)
            self.cache[name] = [None] * len(rows)
            self.states[name] = [0] * len(rows)

    def ref(self, name, index):
        if type(index) is not int or not 0 <= index < len(self.cache[name]):
            raise ValueError('invalid ' + name + ' table reference')
        state = self.states[name][index]
        if state == 1:
            raise ValueError('cyclic contextual query table reference')
        if state == 2:
            return self.cache[name][index]
        if self.depth >= _MAX_DEPTH:
            raise ValueError('contextual query reference depth exhausted')
        self.states[name][index] = 1; self.depth += 1
        try:
            result = self.row(name, self.document[name][index])
        except BaseException:
            self.states[name][index] = 0
            raise
        finally:
            self.depth -= 1
        self.cache[name][index] = result; self.states[name][index] = 2
        return result

    def row(self, name, row):
        if name == 'locators':
            return decode(SourceArtifactLocator, row)
        if name == 'namespaces':
            _object(row, ('graph', 'representation', 'root', 'source_body'), 'namespace')
            graph = self.ref('locators', row['graph'])
            root = _wire_id(RegionID, row['root'])
            if type(row['representation']) is not str:
                raise ValueError('namespace representation must be a string')
            body = row['source_body']
            if body is not None:
                _object(body, ('definition', 'entry', 'source'), 'namespace source body')
                definition = _wire_id(OperationDefinitionID, body['definition'])
                source = decode(SourceReference | None, body['source'])
                body = SourceBodyNamespace(graph, row['representation'], definition,
                    source, decode(str, body['entry']), root)
            return GraphNamespace(graph, row['representation'], root, body)
        if name == 'frames':
            _object(row, ('caller', 'operation', 'callee_use', 'callee_value', 'target', 'definition', 'entry'), 'frame')
            return DependencyFrame(self.ref('namespaces', row['caller']),
                _wire_id(OperationID, row['operation']),
                None if row['callee_use'] is None else _wire_id(UseID, row['callee_use']),
                None if row['callee_value'] is None else _wire_id(ValueID, row['callee_value']),
                self.ref('namespaces', row['target']),
                None if row['definition'] is None else _wire_id(OperationDefinitionID, row['definition']),
                None if row['entry'] is None else _wire_id(RegionID, row['entry']))
        if name == 'contexts':
            _object(row, ('frames', 'unknown_prefix'), 'context')
            if type(row['unknown_prefix']) is not bool:
                raise ValueError('context unknown_prefix must be an exact bool')
            frames = tuple(self.ref('frames', index) for index in _array(row['frames'], 'context frames'))
            if row['unknown_prefix']:
                return OpenDependencyContext(frames)
            # The original helper validates a closed frame chain without
            # converting an unknown prefix into an empty root selection.
            from scar.ir.program.dependencies import context_frames
            context_frames(frames)
            return frames
        if name == 'points':
            _object(row, ('namespace', 'node', 'node_type', 'context', 'visited'), 'point')
            kind = _POINT_NODE_TYPES.get(row['node_type']) if type(row['node_type']) is str else None
            if kind is None:
                raise ValueError('unknown original point ID type')
            # Contextual resolution is not a traversal. _Tables is created
            # without a visited set, so accepting True would discard data.
            if row['visited'] is not False:
                raise ValueError('contextual-call point cannot declare traversal visitation')
            context = None if row['context'] is None else self.ref('contexts', row['context'])
            return DependencyPoint(self.ref('namespaces', row['namespace']), _wire_id(kind, row['node']), context)
        if name == 'conditions':
            _object(row, ('domain', 'name', 'subject', 'index', 'operands'), 'condition')
            return DependencyCondition(decode(str, row['domain']), decode(str, row['name']),
                None if row['subject'] is None else self.ref('points', row['subject']),
                decode(int | None, row['index']),
                tuple(self.ref('points', index) for index in _array(row['operands'], 'condition operands')))
        if name == 'evidence':
            _object(row, ('rule', 'sources', 'anchors'), 'evidence')
            return DependencyEvidence(decode(str, row['rule']),
                tuple(self.ref('locators', index) for index in _array(row['sources'], 'evidence sources')),
                tuple(self.ref('points', index) for index in _array(row['anchors'], 'evidence anchors')))
        if name == 'edges':
            _object(row, ('source', 'target', 'kind', 'meaning', 'strength', 'evidence', 'conditions'), 'edge')
            return DependencyEdge(self.ref('points', row['source']), self.ref('points', row['target']),
                decode(DependencyKind, row['kind']), decode(DependencyMeaning, row['meaning']),
                tuple(self.ref('evidence', index) for index in _array(row['evidence'], 'edge evidence')),
                tuple(self.ref('conditions', index) for index in _array(row['conditions'], 'edge conditions')),
                decode(DependencyStrength, row['strength']))
        if name == 'frontier_reasons':
            _object(row, ('kind', 'detail'), 'frontier reason')
            kind, detail = decode(str, row['kind']), decode(str, row['detail'])
            if not kind or not detail:
                raise ValueError('frontier reason cannot be empty')
            return kind, detail
        raise ValueError('unknown contextual query table')

    def unpack(self, expected, wire, depth=0):
        if depth > _MAX_DEPTH:
            raise ValueError('contextual record depth exhausted')
        origin, args = get_origin(expected), get_args(expected)
        if expected is Any:
            raise TypeError('contextual query schema must not expose Any')
        if origin in (Union, UnionType):
            for choice in args:
                try:
                    return self.unpack(choice, wire, depth + 1)
                except (TypeError, ValueError):
                    pass
            raise ValueError('contextual value does not match its expected union')
        if origin in (tuple, list):
            rows = _array(wire, 'typed sequence')
            if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
                if len(rows) != len(args):
                    raise ValueError('incorrect fixed contextual tuple length')
                return tuple(self.unpack(kind, item, depth + 1) for kind, item in zip(args, rows))
            if len(args) != (2 if origin is tuple else 1):
                raise TypeError('unsupported untyped contextual sequence')
            result = [self.unpack(args[0], item, depth + 1) for item in rows]
            return tuple(result) if origin is tuple else result
        if origin is dict:
            if type(wire) is not dict or len(args) != 2:
                raise ValueError('typed contextual mapping fields mismatch')
            return {self.unpack(args[0], key, depth + 1): self.unpack(args[1], value, depth + 1)
                    for key, value in wire.items()}
        reference = _REFERENCES.get(expected)
        if reference is not None:
            tag, table = reference
            _object(wire, (tag,), 'typed ' + tag + ' reference')
            result = self.ref(table, wire[tag])
            if type(result) is not expected:
                raise ValueError('contextual reference points to another expected type')
            return result
        if expected is DependencyFrontier:
            _object(wire, ('point', 'reason'), 'frontier')
            kind, detail = self.ref('frontier_reasons', wire['reason'])
            return DependencyFrontier(self.ref('points', wire['point']), kind, detail)
        if expected is PythonLiteral:
            _object(wire, ('literal',), 'immutable literal')
            return decode(PythonLiteral, wire['literal'])
        if isinstance(expected, type) and issubclass(expected, Identifier):
            _object(wire, ('original_id',), 'original typed ID')
            return _wire_id(expected, wire['original_id'])
        if isinstance(expected, type) and issubclass(expected, Enum):
            return decode(expected, wire)
        if isinstance(expected, type) and is_dataclass(expected):
            schema = self.schemas.get(expected)
            if schema is None:
                schema = fields(expected), get_type_hints(expected)
                self.schemas[expected] = schema
            members, hints = schema
            _object(wire, ('record_type', *(field.name for field in members)), expected.__name__)
            if type(wire['record_type']) is not str or wire['record_type'] != expected.__name__:
                raise ValueError('contextual record discriminator differs from expected class')
            return expected(**{field.name: self.unpack(hints[field.name], wire[field.name], depth + 1)
                               for field in members})
        return decode(expected, wire)

    def validate_tables(self):
        # Unreferenced malformed rows must not hide behind an unused index.
        for name in _TABLES:
            seen = set()
            for index in range(len(self.cache[name])):
                value = self.ref(name, index)
                if value in seen:
                    raise ValueError('duplicate normalized ' + name + ' table record')
                seen.add(value)


def read_contextual_call(document):
    """Read strict raw v1 or normalized v2 into original strong Python types.

    All source declarations, open prefixes, ordered condition operands and
    caller/factory contexts survive.  Local indices never escape this reader.
    """
    if type(document) in (str, bytes):
        if len(document.encode('utf-8') if type(document) is str else document) > _MAX_BYTES:
            raise ValueError('contextual query byte budget exhausted')
        document = loads(document)
    _preflight(document)
    if (type(document) is not dict or document.get('schema') != 'scar.contextual-calls'
            or type(document.get('schema_version')) is not int):
        raise ValueError('unsupported contextual-call query schema')
    version = document['schema_version']
    _object(document, _TOP | set(_TABLES) if version == 2 else _TOP, 'contextual-call query')
    if document['target_executed'] is not False or document['target_resolution_complete'] is not False:
        raise ValueError('contextual query cannot assert execution or target-set closure')
    if version == 1:
        resolution = decode(ContextualCallResolution, document['resolution'])
        edges = decode(tuple[DependencyEdge, ...], document['interface_edges'])
    elif version == 2:
        reader = _Reader(document)
        resolution = reader.unpack(ContextualCallResolution, document['resolution'])
        edges = reader.unpack(tuple[DependencyEdge, ...], document['interface_edges'])
        reader.validate_tables()
    else:
        raise ValueError('unsupported contextual-call query version')
    _resolution(resolution)
    if edges != _interface_edges(resolution):
        raise ValueError('stored contextual interface edges differ from their original typed target ports')
    return resolution, edges


__all__ = ['export_contextual_call', 'read_contextual_call']

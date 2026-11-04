"""F4-A target type grammar and exact nominal shape checking.

This is the declared structure of the existing canonical IR, not a second IR.
It deliberately does not infer operator semantics from labels, certify effects,
or replay source lowering. Recursive type definitions use named references;
cyclic Python value objects are rejected separately.
"""
from collections import Counter, deque
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from scar.ir.program.model import ProgramGraph
from scar.ir.v2.ids import Identifier


_VERSION = 'F4A_CANONICAL_TYPE_GRAMMAR_V1'
_ATOMS = {type(None): 'NoneType', bool: 'bool', int: 'int', float: 'float', str: 'str', bytes: 'bytes'}


class ProgramTypeError(ValueError):
    def __init__(self, code, path, detail):
        self.code, self.path = code, path
        super().__init__(code + ' at ' + path + ': ' + detail)


def _key(cls):
    return cls.__module__ + '.' + cls.__qualname__


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _digest(value):
    return sha256(_json(value)).hexdigest()


def _record_children(members, value, path):
    for field in members:
        yield field['type'], getattr(value, field['name']), path + '.' + field['name']


def _tuple_children(expressions, values, path, *, variadic):
    for index, value in enumerate(values):
        yield expressions[0] if variadic else expressions[index], value, path + '[' + str(index) + ']'


def _build_types(root, *, max_types=1_000, max_fields=10_000, max_expressions=30_000):
    """Total over the reviewed type-expression grammar, with explicit errors."""
    pending, registry, rows, unions = deque(), {}, {}, set()
    expressions, field_count = 0, 0

    def reference(cls):
        key = _key(cls)
        if key in registry and registry[key] is not cls:
            raise ProgramTypeError('TYPE_KEY_COLLISION', key, 'distinct classes share a nominal key')
        if key not in registry:
            if len(registry) >= max_types:
                raise ProgramTypeError('BUDGET_FRONTIER', key, 'type declaration limit')
            registry[key] = cls
            pending.append(cls)
        return dict(kind='REF', name=key, args=[])

    def expression(hint, path):
        nonlocal expressions
        expressions += 1
        if expressions > max_expressions:
            raise ProgramTypeError('BUDGET_FRONTIER', path, 'type expression limit')
        if hint in _ATOMS:
            return dict(kind='ATOM', name=_ATOMS[hint], args=[])
        if hint is Any or hint is object:
            raise ProgramTypeError('OPEN_TYPE_DOMAIN', path, 'Any/object has no closed shape rule')
        origin, arguments = get_origin(hint), get_args(hint)
        if origin in (Union, UnionType):
            args = [expression(arg, path) for arg in arguments]
            result = dict(kind='UNION', name=None, args=args)
            unions.add(_json(result))
            return result
        if origin is tuple:
            variadic = len(arguments) == 2 and arguments[1] is Ellipsis
            args = [expression(arg, path) for arg in (arguments[:1] if variadic else arguments)]
            return dict(kind='TUPLE' if variadic else 'FIXED_TUPLE', name=None, args=args)
        if isinstance(hint, type) and (issubclass(hint, (Identifier, Enum)) or is_dataclass(hint)):
            return reference(hint)
        raise ProgramTypeError('UNSUPPORTED_TYPE_EXPRESSION', path, 'no declared type grammar production')

    root_expression = expression(root, 'root')
    while pending:
        cls = pending.popleft()
        key = _key(cls)
        if issubclass(cls, Identifier):
            if type(cls.prefix) is not str or not cls.prefix:
                raise ProgramTypeError('OPEN_IDENTIFIER_DOMAIN', key, 'identifier needs a nonempty nominal prefix')
            row = dict(key=key, kind='IDENTIFIER', prefix=cls.prefix)
        elif issubclass(cls, Enum):
            members = []
            for name, value in cls.__members__.items():
                if type(value.value) is not str:
                    raise ProgramTypeError('UNSUPPORTED_ENUM_PAYLOAD', key, 'canonical enums require exact strings')
                members.append(dict(name=name, value=value.value, canonical=value.name == name))
            row = dict(key=key, kind='ENUM', members=members)
        else:
            try:
                hints = get_type_hints(cls, include_extras=True)
            except (NameError, TypeError) as error:
                raise ProgramTypeError('UNRESOLVED_TYPE', key, type(error).__name__) from error
            members = []
            for field in fields(cls):
                field_count += 1
                path = key + '.' + field.name
                if field_count > max_fields:
                    raise ProgramTypeError('BUDGET_FRONTIER', path, 'record field limit')
                if field.name not in hints:
                    raise ProgramTypeError('UNRESOLVED_TYPE', path, 'missing field annotation')
                default = ('VALUE' if field.default is not MISSING else
                    'FACTORY' if field.default_factory is not MISSING else 'REQUIRED')
                members.append(dict(name=field.name, type=expression(hints[field.name], path), default=default))
            row = dict(key=key, kind='RECORD', fields=members,
                frozen=cls.__dataclass_params__.frozen)
        rows[key] = row
    ordered = [rows[key] for key in sorted(rows)]
    counts = dict(records=sum(r['kind'] == 'RECORD' for r in ordered), fields=field_count,
        identifiers=sum(r['kind'] == 'IDENTIFIER' for r in ordered),
        enums=sum(r['kind'] == 'ENUM' for r in ordered),
        enum_members=sum(sum(m['canonical'] for m in r['members']) for r in ordered if r['kind'] == 'ENUM'),
        unions=len(unions))
    return root_expression, ordered, registry, counts


def program_type_catalog():
    root, rows, registry, counts = _build_types(ProgramGraph)
    modules = {}
    for cls in registry.values():
        module = sys.modules[cls.__module__]
        path = getattr(module, '__file__', None)
        if path is None:
            raise ProgramTypeError('MISSING_DECLARATION_SOURCE', cls.__module__, 'source pin is required')
        modules[cls.__module__] = sha256(Path(path).read_bytes()).hexdigest()
    payload = dict(schema='scar.program-type-catalog', schema_version=1, grammar_version=_VERSION,
        root=root, types=rows, counts=counts,
        profile=dict(implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            source_modules=dict(sorted(modules.items()))),
        scalar_policy='EXACT_BUILTINS;FLOAT_ACCEPTS_EXACT_INT;FINITE_FLOATS',
        nominal_policy='EXACT_REGISTERED_RECORD_ENUM_IDENTIFIER',
        recursion_policy='NAMED_TYPE_REFERENCES;ACYCLIC_VALUE_OBJECTS',
        claims=dict(structural_signature_closed=True, operation_semantics_closed=False, graph_realized=False),
        semantic_obligations=[
            'Operation.label has mixed legacy display/dispatch consumers; no operator kind is inferred from it.',
            'Nominal type names and identity strings are data, not resolved runtime class/object identities.',
            'Operator families, signatures, source productions, effects and cross-record constraints require their own checks.',
        ])
    return {**payload, 'content_sha256': _digest(payload)}


def read_program_type_catalog(document):
    expected = program_type_catalog()
    if _json(document) != _json(expected):
        raise ProgramTypeError('CATALOG_MISMATCH', 'catalog', 'declarations, grammar or source pins differ')
    return expected


def validate_program_shape(graph, *, max_visits=10_000_000):
    """Check exact registered shapes and constructors, not CFG or semantics.

    A closed iterative walk rejects extensions/cycles before the existing
    constructor validator can inspect them. Shared immutable records are valid.
    """
    if type(max_visits) is not int or max_visits < 0:
        raise ProgramTypeError('QUERY_ARGUMENT', 'max_visits', 'expected an exact nonnegative integer')
    root, declarations, registry, _ = _build_types(ProgramGraph)
    rows = {row['key']: row for row in declarations}
    active, visited, records = set(), 0, 0
    pending = [('ENTER', root, graph, 'graph')]

    def accepts(expr, value, *, promote_float=True):
        kind = expr['kind']
        if kind == 'REF':
            return type(value) is registry[expr['name']]
        if kind == 'ATOM':
            cls = next(cls for cls, name in _ATOMS.items() if name == expr['name'])
            return type(value) in (float, int) if cls is float and promote_float else type(value) is cls
        if kind in ('TUPLE', 'FIXED_TUPLE'):
            return type(value) is tuple
        if kind == 'UNION':
            return any(accepts(arg, value, promote_float=promote_float) for arg in expr['args'])
        return False

    while pending:
        action, expr, value, path = pending.pop()
        if action == 'LEAVE':
            active.remove(id(value))
            continue
        if action == 'CHILDREN':
            child = next(value, None)
            if child is not None:
                pending.append(('CHILDREN', None, value, path))
                pending.append(('ENTER', *child))
            continue
        if visited >= max_visits:
            raise ProgramTypeError('BUDGET_FRONTIER', path, 'value traversal limit')
        visited += 1
        if expr['kind'] == 'UNION':
            # int|float chooses the exact int case; only a float-only
            # annotation uses the numeric promotion admitted by typing.
            choices = [arg for arg in expr['args'] if accepts(arg, value, promote_float=False)]
            if not choices:
                choices = [arg for arg in expr['args'] if accepts(arg, value)]
            if len(choices) != 1:
                raise ProgramTypeError('TYPE_MISMATCH', path, 'expected one exact registered union variant')
            expr = choices[0]
        kind = expr['kind']
        if not accepts(expr, value):
            code = 'UNREGISTERED_VARIANT' if kind == 'REF' else 'TYPE_MISMATCH'
            raise ProgramTypeError(code, path, 'value is outside its declared exact type')
        if kind == 'ATOM':
            if type(value) is float and not math.isfinite(value):
                raise ProgramTypeError('TYPE_MISMATCH', path, 'non-finite scalar')
            continue
        if kind == 'REF':
            row = rows[expr['name']]
            if row['kind'] == 'ENUM':
                if not any(value is member for member in registry[expr['name']].__members__.values()):
                    raise ProgramTypeError('UNREGISTERED_VARIANT', path, 'enum object is not a declared member')
                continue
            if row['kind'] == 'IDENTIFIER':
                if (type(value.value) is not str or not value.value
                        or type(value.prefix) is not str or value.prefix != row['prefix']):
                    raise ProgramTypeError('TYPE_MISMATCH', path, 'identifier payload/prefix differs from its declaration')
                continue
            records += 1
            children = _record_children(row['fields'], value, path)
        elif kind == 'TUPLE':
            children = _tuple_children(expr['args'], value, path, variadic=True)
        else:
            if len(value) != len(expr['args']):
                raise ProgramTypeError('TYPE_MISMATCH', path, 'fixed tuple arity differs')
            children = _tuple_children(expr['args'], value, path, variadic=False)
        if id(value) in active:
            raise ProgramTypeError('VALUE_CYCLE', path, 'cyclic value object is not a graph ID reference')
        active.add(id(value))
        pending.append(('LEAVE', None, value, path))
        pending.append(('CHILDREN', None, children, path))
    from scar.ir.v2._validation import record_errors
    try:
        errors = record_errors(graph, ProgramGraph, 'graph')
    except (RecursionError, MemoryError) as error:
        raise ProgramTypeError('BUDGET_FRONTIER', 'graph', 'constructor validation resource limit') from error
    if errors:
        raise ProgramTypeError('CONSTRUCTOR_INVARIANT', 'graph', errors[0])
    return dict(complete=True, visits=visited, records=records, constructor_invariants_checked=True,
        cross_record_invariants_checked=False, operation_semantics_checked=False)


__all__ = ['ProgramTypeError', 'program_type_catalog', 'read_program_type_catalog', 'validate_program_shape']

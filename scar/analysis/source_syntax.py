"""F2: fixed official ONLY_AST parsing and lossless flat occurrence records.

This stage does not resolve names, construct execution IR or run target code.
Warning isolation has the same process-worker requirement as F1.
"""
from __future__ import annotations

import ast
import _ast
import builtins
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import UnionType
from typing import get_args, get_origin
import warnings

from scar.analysis.source_bytes import decoded_source_bytes
from scar.analysis.source_tokens import read_source_tokens, _error, _implementation
from scar.ir import literals
from scar.ir.literals import PythonLiteral
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_syntax import (
    AstClassSchema, AstFieldSchema, AstOccurrence, AstTypeSchema, AstValue,
    SourceSyntaxInput, SourceSyntaxMaterial, SourceSyntaxProfile, SyntaxFrontier,
)
from scar.ir.program.source_tokens import SourceTokenWarning
from scar.ir.record_codec import decode, encode


@lru_cache(maxsize=1)
def _registry():
    classes = {name: cls for name, cls in vars(_ast).items()
        if isinstance(cls, type) and issubclass(cls, ast.AST)}
    abstract = {cls for cls in classes.values()
        if any(cls in child.__bases__ for child in classes.values())}
    constructors = {name: cls for name, cls in classes.items() if cls not in abstract}
    return classes, constructors


def _type_schema(kind):
    origin = get_origin(kind)
    if origin is list:
        return AstTypeSchema('LIST', None, tuple(_type_schema(x) for x in get_args(kind)))
    if origin is UnionType:
        return AstTypeSchema('UNION', None, tuple(_type_schema(x) for x in get_args(kind)))
    if isinstance(kind, type) and issubclass(kind, ast.AST):
        return AstTypeSchema('AST_CLASS', kind.__name__, ())
    if kind in (str, int, object, type(None)):
        return AstTypeSchema('BUILTIN', kind.__name__, ())
    raise ValueError('unrecorded official AST field type')


@lru_cache(maxsize=1)
def _schema_and_digests():
    classes, constructors = _registry()
    schema = tuple(AstClassSchema(name, tuple(base.__name__ for base in cls.__bases__),
        name not in constructors, tuple(cls._fields), tuple(cls._attributes),
        tuple(AstFieldSchema(field, _type_schema(kind)) for field, kind in getattr(cls, '_field_types', {}).items()))
        for name, cls in classes.items())
    return schema, sha256(Path(ast.__file__).read_bytes()).hexdigest(), sha256(Path(literals.__file__).read_bytes()).hexdigest()


def _profile(f0):
    schema, ast_sha, literal_sha = _schema_and_digests()
    _, _, origin, binary, binary_sha = _implementation()
    # This supported CPython build places both native lexer and parser in the
    # static interpreter. An extension-only lexer is not a parser receipt.
    if origin != 'built-in' or _ast.__spec__.origin != 'built-in':
        raise ValueError('F2 needs the actual loaded native parser implementation receipt')
    return SourceSyntaxProfile(decode(SourceBytesProfile, f0['profile']),
        'builtins.compile.PyCF_ONLY_AST', ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS,
        True, 0, sys.version_info.minor, sys.get_int_max_str_digits(), sys.getrecursionlimit(),
        'AST_LINES_1_BASED_UTF8_BYTE_COLUMNS_0_BASED', 'RECORD_ALL_ALWAYS_ISOLATED_V1',
        ast_sha, 'builtins.compile/_ast:built-in', binary, binary_sha, schema,
        'PythonLiteral.from_python(exact=True);FIXED_BUDGET_V1', literal_sha,
        literals.MAX_LITERAL_DEPTH, literals.MAX_LITERAL_NODES, literals.MAX_LITERAL_PAYLOAD_BYTES,
        literals.MAX_INT_DECIMAL_DIGITS, literals.MAX_INT_BIT_LENGTH)


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


class SyntaxBudgetExceeded(ValueError):
    def __init__(self, code, path, detail):
        self.frontier = SyntaxFrontier(code, path, detail)
        super().__init__(detail)


def _flatten_ast(root, *, max_nodes=1_000_000):
    """Encode official node occurrences, also usable for synthetic codec cases.

    Parser singleton object sharing is deliberately not program identity:
    every parent/field/list occurrence gets its own local integer reference.
    """
    if type(max_nodes) is not int or max_nodes < 0:
        raise ValueError('max_nodes must be an exact nonnegative integer')
    constructors = _registry()[1]
    rows, tasks, active = [], [], set()

    def value(item, path):
        if isinstance(item, ast.AST):
            if type(item).__name__ not in constructors or constructors[type(item).__name__] is not type(item):
                raise ValueError('only exact official concrete AST constructors are recorded')
            if len(rows) >= max_nodes:
                raise SyntaxBudgetExceeded('AST_NODE_BUDGET', path, 'maximum AST occurrence count reached')
            index = len(rows)
            rows.append(None)
            tasks.append((item, index, path))
            return AstValue('NODE', index, (), None)
        if type(item) is list:
            return AstValue('LIST', None, tuple(value(child, path + '[' + str(i) + ']') for i, child in enumerate(item)), None)
        try:
            literal = PythonLiteral.from_python(item, exact=True)
        except ValueError as error:
            raise SyntaxBudgetExceeded('SCALAR_BUDGET', path, str(error)) from error
        return AstValue('SCALAR', None, (), literal)

    root_value = value(root, '$')
    if root_value.kind != 'NODE':
        raise TypeError('F2 root must be an official AST node')
    while tasks:
        node, index, path = tasks.pop()
        if node is None:
            active.remove(index)
            continue
        identity = id(node)
        if identity in active:
            raise ValueError('cyclic AST object graph')
        active.add(identity)
        tasks.append((None, identity, path))
        cls, present = type(node), vars(node)
        if set(present) - set(cls._fields) - set(cls._attributes):
            raise ValueError('undeclared attributes are not official AST material')
        groups = []
        for names in (cls._fields, cls._attributes):
            groups.append(tuple(value(present[name], path + '.' + name) if name in present
                else AstValue('ABSENT', None, (), None) for name in names))
        rows[index] = AstOccurrence(cls.__name__, groups[0], groups[1])
    return root_value.reference, tuple(rows)


def _references(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if item.kind == 'NODE':
            yield item.reference
        elif item.kind == 'LIST':
            stack.extend(item.items)


def _require_value(value, expected, rows, *, nullable_list=False):
    if value.kind == 'ABSENT':
        raise ValueError('ABSENT is allowed only in a declared field/attribute slot')
    origin = get_origin(expected)
    if origin is UnionType:
        for kind in get_args(expected):
            try:
                _require_value(value, kind, rows)
                return
            except ValueError:
                pass
        raise ValueError('AST value does not match its official union field type')
    if origin is list:
        if value.kind != 'LIST':
            raise ValueError('official AST list field requires LIST')
        for item in value.items:
            if nullable_list and item.kind == 'SCALAR' and item.scalar.to_python() is None:
                continue
            _require_value(item, get_args(expected)[0], rows)
        return
    if isinstance(expected, type) and issubclass(expected, ast.AST):
        if value.kind != 'NODE' or not issubclass(_registry()[1][rows[value.reference].constructor], expected):
            raise ValueError('AST reference does not match its official node family')
        return
    if value.kind != 'SCALAR':
        raise ValueError('official AST scalar field requires SCALAR')
    actual = value.scalar.to_python()
    if expected is not object and type(actual) is not expected:
        raise ValueError('AST scalar differs from its official field type')


def _restore_ast(root_index, nodes):
    """Restore the stored occurrences without constructor defaults or hooks."""
    if type(nodes) is not tuple or type(root_index) is not int or not 0 <= root_index < len(nodes):
        raise ValueError('invalid AST occurrence table/root')
    constructors, parents, links = _registry()[1], [0] * len(nodes), []
    for row in nodes:
        if type(row) is not AstOccurrence or row.constructor not in constructors:
            raise ValueError('unknown official AST constructor')
        cls = constructors[row.constructor]
        if len(row.fields) != len(cls._fields) or len(row.attributes) != len(cls._attributes):
            raise ValueError('AST field/attribute arity differs from its official schema')
        refs = tuple(ref for item in (*row.fields, *row.attributes) for ref in _references(item))
        if any(type(ref) is not int or not 0 <= ref < len(nodes) for ref in refs):
            raise ValueError('AST reference is outside the occurrence table')
        for ref in refs:
            parents[ref] += 1
        links.append(refs)
    if parents[root_index] != 0 or any(count != 1 for i, count in enumerate(parents) if i != root_index):
        raise ValueError('each non-root AST occurrence must have exactly one parent')
    reached, pending = set(), [root_index]
    while pending:
        index = pending.pop()
        if index in reached:
            raise ValueError('cyclic or shared AST occurrence references')
        reached.add(index)
        pending.extend(links[index])
    if len(reached) != len(nodes):
        raise ValueError('unreachable AST occurrence rows')
    for row in nodes:
        cls = constructors[row.constructor]
        for name, value in zip(cls._fields, row.fields):
            if value.kind != 'ABSENT':
                _require_value(value, cls._field_types[name], nodes,
                    nullable_list=(row.constructor, name) in (('Dict', 'keys'), ('arguments', 'kw_defaults')))
        for name, value in zip(cls._attributes, row.attributes):
            if value.kind == 'ABSENT':
                continue
            _require_value(value, int | None if name.startswith('end_') else int, nodes)
    objects = tuple(ast.AST.__new__(constructors[row.constructor]) for row in nodes)

    def restore(value):
        if value.kind == 'NODE':
            return objects[value.reference]
        if value.kind == 'LIST':
            return [restore(item) for item in value.items]
        if value.kind == 'SCALAR':
            return value.scalar.to_python()
        raise ValueError('ABSENT cannot occur inside an AST value')

    for node, row in zip(objects, nodes):
        cls = type(node)
        for names, values in ((cls._fields, row.fields), (cls._attributes, row.attributes)):
            for name, value in zip(names, values):
                if value.kind != 'ABSENT':
                    vars(node)[name] = restore(value)
    return objects[root_index]


def _produce(f0, f1, mode, max_nodes):
    if type(mode) is not str or mode not in ('exec', 'eval', 'single', 'func_type'):
        raise ValueError('mode must be exec/eval/single/func_type')
    if type(max_nodes) is not int or max_nodes < 0:
        raise ValueError('max_nodes must be an exact nonnegative integer')
    read_source_tokens(f1, f0)
    original = decoded_source_bytes(f0)
    profile = _profile(f0)
    inputs = SourceSyntaxInput(_digest(f0), _digest(f1), f0['path'], f0['raw']['sha256'],
        f1['view']['sha256'] if f1['view'] is not None else None, f1['status'])
    if f1['status'] != 'TOKENIZED' or not f1['actual_eof']:
        return SourceSyntaxMaterial(inputs, profile, mode, max_nodes, 'UPSTREAM_NOT_TOKENIZED',
            None, (), (), None, ())
    text = original.replace('\r\n', '\n').replace('\r', '\n')
    root, rows, frontiers, failure, status = None, (), (), None, 'PARSED'
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        try:
            tree = builtins.compile(text, f0['path'], mode, flags=profile.flags,
                dont_inherit=True, optimize=0, _feature_version=profile.feature_version)
        except SyntaxError as error:
            failure, status = replace(_error(error),
                coordinate_basis='NATIVE_PARSER_EXCEPTION_DIAGNOSTIC_NOT_AST_COORDINATES'), 'PARSER_ERROR'
        except (MemoryError, RecursionError, OverflowError) as error:
            failure, status = replace(_error(error),
                coordinate_basis='NATIVE_PARSER_EXCEPTION_DIAGNOSTIC_NOT_AST_COORDINATES'), 'PARSER_RESOURCE_ERROR'
        else:
            try:
                root, rows = _flatten_ast(tree, max_nodes=max_nodes)
            except SyntaxBudgetExceeded as error:
                frontiers, status = (error.frontier,), 'BUDGET_STOPPED'
    warning_rows = tuple(SourceTokenWarning(item.category.__module__, item.category.__qualname__,
        str(item.message), item.filename, item.lineno, item.line, item.source is not None) for item in captured)
    return SourceSyntaxMaterial(inputs, profile, mode, max_nodes, status, root, rows, frontiers, failure, warning_rows)


def source_syntax_document(f0_document, f1_document, *, mode='exec', max_nodes=1_000_000) -> dict:
    return encode(_produce(f0_document, f1_document, mode, max_nodes))


def read_source_syntax(document, f0, f1) -> ast.AST | None:
    material = decode(SourceSyntaxMaterial, document)
    fresh = _produce(f0, f1, material.mode, material.max_nodes)
    if material != fresh:
        raise ValueError('F2 document differs from its F0/F1/profile/fresh official parser')
    if material.status != 'PARSED':
        return None
    root = _restore_ast(material.root, material.nodes)
    if _flatten_ast(root, max_nodes=material.max_nodes) != (fresh.root, fresh.nodes):
        raise ValueError('restored AST differs in an occurrence/field/presence/exact scalar')
    return root


__all__ = ['source_syntax_document', 'read_source_syntax']

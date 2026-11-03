"""F2 structural schema tests; synthetic ASTs are never parser evidence.

Only the official ONLY_AST parser is invoked. No bytecode, symbol table,
target execution, name resolution, or execution-IR construction is required.
"""
import _ast
import ast
import builtins
from copy import deepcopy
import json
import struct
import sys
from types import UnionType
from typing import get_args, get_origin
import warnings

import pytest

from scar.analysis.source_bytes import decoded_source_bytes, source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.ir.literals import MAX_INT_BIT_LENGTH, MAX_LITERAL_PAYLOAD_BYTES, PythonLiteral
from scar.ir.record_codec import decode, encode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='this AST schema is pinned to the CPython 3.14.7 grammar')


def _inputs(text, *, max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/material.py', namespace_root='/source')
    return f0, source_tokens_document(f0, max_tokens=max_tokens)


def _scalar_equal(actual, expected):
    assert type(actual) is type(expected)
    if type(expected) is float:
        assert struct.pack('>d', actual) == struct.pack('>d', expected)
    elif type(expected) is complex:
        assert struct.pack('>dd', actual.real, actual.imag) == struct.pack('>dd', expected.real, expected.imag)
    elif type(expected) is tuple:
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            _scalar_equal(a, b)
    else:
        assert actual == expected


def _compare_trees(actual, expected):
    pending = [(actual, expected)]
    while pending:
        actual, expected = pending.pop()
        assert type(actual) is type(expected)
        if isinstance(expected, ast.AST):
            assert set(vars(actual)) == set(vars(expected))
            for name in (*type(expected)._fields, *type(expected)._attributes):
                assert (name in vars(actual)) == (name in vars(expected))
                if name in vars(expected):
                    pending.append((vars(actual)[name], vars(expected)[name]))
        elif type(expected) is list:
            assert len(actual) == len(expected)
            pending.extend(zip(actual, expected))
        else:
            _scalar_equal(actual, expected)


def _check_flat(root, rows, expected):
    """Inspect stored records directly, independently of F2's fresh reader."""
    pending, seen = [(root, expected)], set()

    def value(stored, actual):
        if isinstance(actual, ast.AST):
            assert stored['kind'] == 'NODE' and stored['items'] == [] and stored['scalar'] is None
            assert type(stored['reference']) is int
            pending.append((stored['reference'], actual))
        elif type(actual) is list:
            assert stored['kind'] == 'LIST' and stored['reference'] is stored['scalar'] is None
            assert len(stored['items']) == len(actual)
            for item, original in zip(stored['items'], actual):
                value(item, original)
        else:
            assert stored['kind'] == 'SCALAR' and stored['reference'] is None and stored['items'] == []
            _scalar_equal(PythonLiteral.from_dict(stored['scalar']).to_python(), actual)

    while pending:
        index, node = pending.pop()
        assert type(index) is int and 0 <= index < len(rows) and index not in seen
        seen.add(index)
        row, cls = rows[index], type(node)
        assert row['constructor'] == cls.__name__
        for key, names in (('fields', cls._fields), ('attributes', cls._attributes)):
            assert len(row[key]) == len(names)
            for name, stored in zip(names, row[key]):
                if name not in vars(node):
                    assert stored == {'kind': 'ABSENT', 'reference': None, 'items': [], 'scalar': None}
                else:
                    value(stored, vars(node)[name])
    assert seen == set(range(len(rows)))


def _constructors():
    return {name: cls for name, cls in vars(_ast).items()
            if isinstance(cls, type) and issubclass(cls, ast.AST) and '_field_types' in vars(cls)}


def _synthetic(cls, variant):
    """Produce schema-shaped records, explicitly not grammar-valid programs."""
    node = ast.AST.__new__(cls)
    if variant == 'absent':
        return node

    def sample(kind, populated):
        origin = get_origin(kind)
        if origin is UnionType:
            choices = get_args(kind)
            if type(None) in choices and not populated:
                return None
            return sample(next(item for item in choices if item is not type(None)), populated)
        if origin is list:
            return [sample(get_args(kind)[0], False)] if populated else []
        if isinstance(kind, type) and issubclass(kind, ast.AST):
            concrete = next(candidate for candidate in _constructors().values() if issubclass(candidate, kind))
            return _synthetic(concrete, 'empty')
        return {str: 'name', int: 1, object: None, type(None): None}[kind]

    for name, kind in cls._field_types.items():
        vars(node)[name] = sample(kind, variant == 'populated')
    for name in cls._attributes:
        vars(node)[name] = None if name.startswith('end_') and variant == 'empty' else (0 if name.endswith('offset') else 1)
    if variant == 'populated' and cls is ast.Dict:
        node.keys = [None, ast.Constant(value='key', kind=None)]
        node.values = [ast.Constant(value=1, kind=None), ast.Constant(value=2, kind=None)]
    if variant == 'populated' and cls is ast.arguments:
        node.kwonlyargs = [ast.arg(arg='required'), ast.arg(arg='optional')]
        node.kw_defaults = [None, ast.Constant(value=None, kind=None)]
    return node


def _oracle(f0, mode):
    text = decoded_source_bytes(f0).replace('\r\n', '\n').replace('\r', '\n')
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        tree, failure = None, None
        try:
            tree = builtins.compile(text, f0['path'], mode,
                flags=ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS,
                dont_inherit=True, optimize=0, _feature_version=sys.version_info.minor)
        except SyntaxError as error:
            failure = error
    return tree, failure, captured


def _parser_corpus():
    yield 'exec', ''
    yield 'exec', r'''@decorate
def f(first: T=1, /, second=2, *args, required, optional=None, **kwargs) -> T:
    global shared
    local: T = first
    local += second
    del args[0]
    result = {**kwargs, "key": local}
    return result
numbers = [1e999, 2j, ..., b"\x00\xff", u"text", "\ud800"]
x = 1 # type: int
y = 2 # type: ignore[tag]
α = f"{{α}} {value!r:>{width}}"
template = t"text {value!r}"
'''
    yield 'exec', '''def control(manager, items, error):
    with manager as resource:
        try:
            for item in items:
                if item:
                    continue
                else:
                    break
            else:
                assert items, "empty"
            while items:
                raise error() from resource
        except error as caught:
            raise
        else:
            pass
        finally:
            resource.close()
    try:
        consume(items)
    except* error:
        handle(items)
    return items
'''
    yield 'exec', '''async def asynchronous(source, manager):
    async with manager:
        async for item in source:
            await consume(item)
    return [piece async for piece in source if piece]
def generator(items):
    yield from items
    yield 1
'''
    yield 'exec', '''match value:
    case [first, *rest]: pass
    case {"key": found, **rest}: pass
    case Some(attr=field) | Other(attr=field) if field: pass
    case 1 | 2: pass
    case None: pass
'''
    yield 'exec', '''type Vector[T: int = int, *Ts, **P] = tuple[T, *Ts]
class Holder[T](Base, option=True):
    def method(self): return self.value
'''
    yield 'exec', 'a+b+c\r\nx = "\\q"\r\n'
    yield 'eval', '(value := obj.attr[1:]), lambda x: x, {x: x for x in items}, {x for x in items}, (x for x in items)'
    yield 'single', 'x = 1\n'
    yield 'func_type', '(int, str) -> bool'
    yield 'exec', 'x = if :\n'
    # ONLY_AST success is not a proof that a scope/control statement is legal.
    yield 'exec', 'return 1\n'


@pytest.mark.parametrize('family', ('synthetic_schema', 'parser', 'gates'))
def test_f2_official_ast_schema_and_parser(family, monkeypatch):
    from scar.analysis.source_syntax import (
        SyntaxBudgetExceeded, _flatten_ast, _restore_ast,
        read_source_syntax, source_syntax_document,
    )
    from scar.ir.program.source_syntax import AstOccurrence

    if family == 'synthetic_schema':
        constructors = _constructors()
        assert len(constructors) == 113 and sum(len(cls._fields) for cls in constructors.values()) == 196
        fields, attributes = set(), set()
        for name, cls in constructors.items():
            for variant in ('absent', 'empty', 'populated'):
                synthetic = _synthetic(cls, variant)
                root, rows = _flatten_ast(synthetic)
                wire = json.loads(json.dumps(encode(rows)))
                _check_flat(root, wire, synthetic)
                restored = _restore_ast(root, decode(tuple[AstOccurrence, ...], wire))
                _compare_trees(restored, synthetic)
                if variant == 'populated':
                    fields.update((name, field) for field in cls._fields)
                    attributes.update((name, attribute) for attribute in cls._attributes)
        assert len(fields) == 196 and len(attributes) == 288
        nan = struct.unpack('>d', bytes.fromhex('7ff8000000000042'))[0]
        for scalar in (None, False, True, -1, 1 << 1024, -0.0, float('inf'), nan,
                       complex(-0.0, nan), '\ud800', b'\x00\xff', Ellipsis, (None, False, -0.0)):
            synthetic = ast.Constant(value=scalar, kind=None)
            root, rows = _flatten_ast(synthetic)
            _check_flat(root, encode(rows), synthetic)
            _compare_trees(_restore_ast(root, rows), synthetic)
        synthetic = ast.Constant(value='a' * (MAX_LITERAL_PAYLOAD_BYTES + 1), kind=None)
        with pytest.raises(SyntaxBudgetExceeded) as stopped:
            _flatten_ast(synthetic)
        assert stopped.value.frontier.code == 'SCALAR_BUDGET'
        return

    if family == 'parser':
        modes = set()
        for mode, text in _parser_corpus():
            f0, f1 = _inputs(text)
            expected, failure, warning_rows = _oracle(f0, mode)
            assert f1['status'] == 'TOKENIZED'
            document = source_syntax_document(f0, f1, mode=mode)
            actual = read_source_syntax(json.loads(json.dumps(document)), f0, f1)
            profile = document['profile']
            assert profile['flags'] == ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS
            assert profile['dont_inherit'] is True and profile['optimize'] == 0
            assert profile['feature_version'] == sys.version_info.minor
            schema = {row['name']: row for row in profile['ast_schema']}
            for name, cls in _constructors().items():
                assert schema[name]['abstract'] is False
                assert schema[name]['fields'] == list(cls._fields)
                assert schema[name]['attributes'] == list(cls._attributes)
                assert [item['name'] for item in schema[name]['field_types']] == list(cls._field_types)
            assert document['warnings'] == [dict(
                category_module=item.category.__module__, category_name=item.category.__qualname__,
                message=str(item.message), filename=item.filename, lineno=item.lineno,
                line=item.line, source_present=item.source is not None) for item in warning_rows]
            if failure is not None:
                assert actual is None and document['status'] == 'PARSER_ERROR'
                assert document['error']['exception_type'] == type(failure).__name__
                assert document['error']['message'] == str(failure)
            else:
                assert document['status'] == 'PARSED'
                _check_flat(document['root'], document['nodes'], expected)
                _compare_trees(actual, expected)
                assert len(document['nodes']) == sum(1 for _ in ast.walk(expected))
                # Shared official singleton objects still have separate occurrences.
                additions = [node for node in ast.walk(expected) if type(node) is ast.Add]
                if len(additions) > 1:
                    assert len({id(node) for node in additions}) == 1
                    assert sum(row['constructor'] == 'Add' for row in document['nodes']) == len(additions)
                modes.add(mode)
        assert modes == {'exec', 'eval', 'single', 'func_type'}
        return

    f0, f1 = _inputs('x=1\n')
    document = source_syntax_document(f0, f1)
    expected, _, _ = _oracle(f0, 'exec')
    read_source_syntax(document, f0, f1)  # Warm the normal typed reader before the compile prohibition.
    count = sum(1 for _ in ast.walk(expected))
    for limit in (0, count - 1, count):
        bounded = source_syntax_document(f0, f1, max_nodes=limit)
        actual = read_source_syntax(bounded, f0, f1)
        assert bounded['status'] == ('PARSED' if limit == count else 'BUDGET_STOPPED')
        if limit != count:
            assert actual is None and bounded['root'] is None and bounded['nodes'] == []
            assert bounded['frontiers'][0]['code'] == 'AST_NODE_BUDGET'
    huge, huge_tokens = _inputs('x=0x' + 'f' * (MAX_INT_BIT_LENGTH // 4 + 1) + '\n')
    stopped = source_syntax_document(huge, huge_tokens)
    assert stopped['status'] == 'BUDGET_STOPPED' and stopped['frontiers'][0]['code'] == 'SCALAR_BUDGET'
    assert read_source_syntax(stopped, huge, huge_tokens) is None

    upstream = [_inputs('x=(\n'), _inputs('x=1\n', max_tokens=0)]
    invalid = source_bytes_document(b'# coding: missing_scar_codec\n', path='/source/material.py', namespace_root='/source')
    upstream.append((invalid, source_tokens_document(invalid)))
    def forbidden(*args, **kwargs):
        raise AssertionError('F2 must not invoke the parser for incomplete F1')
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'compile', forbidden)
        for a, b in upstream:
            result = source_syntax_document(a, b)
            assert result['status'] == 'UPSTREAM_NOT_TOKENIZED'
            assert read_source_syntax(result, a, b) is None

    for route, replacement in (
        (('max_nodes',), True), (('root',), True), (('nodes', 0, 'constructor'), 'UnknownConstructor'),
        (('profile', 'flags'), 0), (('nodes', 0, 'extra'), None), (('extra',), [])):
        changed = deepcopy(document)
        target = changed
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            read_source_syntax(changed, f0, f1)
    changed = deepcopy(document)
    del changed['schema_version']
    with pytest.raises((TypeError, ValueError)):
        read_source_syntax(changed, f0, f1)
    different, different_tokens = _inputs('x=2\n')
    with pytest.raises((TypeError, ValueError)):
        read_source_syntax(document, different, different_tokens)

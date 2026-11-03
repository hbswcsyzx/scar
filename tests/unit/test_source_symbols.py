"""F3-A official symbol-table facts, without AST joins or target execution."""
import _symtable
import builtins
from copy import deepcopy
import json
import os
import subprocess
import sys
import warnings

import pytest

from scar.analysis.source_bytes import decoded_source_bytes, source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the official symbol-table schema is pinned to CPython 3.14.7')


def _inputs(text, *, mode='exec', max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/symbols.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    return f0, f1, source_syntax_document(f0, f1, mode=mode)


def _native_oracle(f0, mode):
    """Independently copy public raw tables in two passes, excluding C addresses."""
    text = decoded_source_bytes(f0).replace('\r\n', '\n').replace('\r', '\n')
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        root = _symtable.symtable(text, f0['path'], mode)
    pending, objects, local = [root], [], {}
    while pending:
        table = pending.pop()
        if id(table) in local:
            continue
        local[id(table)] = len(objects)
        objects.append(table)
        pending.extend(reversed(table.children))
    rows = tuple(dict(name=table.name, type=table.type, nested=table.nested,
        lineno=table.lineno, varnames=tuple(table.varnames),
        symbols=tuple(table.symbols.items()),
        children=tuple(local[id(child)] for child in table.children)) for table in objects)
    return local[id(root)], rows, captured


def _corpus():
    yield '''module_global=1
import imported
def outer(seed):
    captured=seed
    def inner(param):
        nonlocal captured
        global module_global
        local=param
        captured+=local
        return captured,module_global,missing
    return inner
left=lambda: 1; right=lambda: 1
type Same = int; type Same = int
'''
    yield '''first: First
second: Second
class __Owner[__T: __Bound = __Default]:
    __slot: __T
    def __method(__self, __arg: __T):
        return __arg, __external
type Alias[T: Bound = Default] = list[T]
'''
    yield '''def outer():
    owned=1
    class C:
        owned=2
        def method(self): return owned
    return C
rows=[lambda: item for item in data]
gen=(lambda: item for item in data)
class C:
    rows: [lambda: item for item in data]
'''


def _tree(root, rows):
    """Compare graph topology without requiring the producer's ID ordering."""
    def visit(index):
        row = rows[index]
        return (row['name'], row['type'], row['nested'], row['lineno'],
                row['varnames'], row['symbols'], tuple(visit(i) for i in row['children']))
    return visit(root)


def _stored_rows(material):
    return tuple(dict(name=row.name, type=row.type, nested=row.nested,
        lineno=row.lineno, varnames=row.varnames,
        symbols=tuple((symbol.name, symbol.flags) for symbol in row.symbols),
        children=row.children) for row in material.scopes)


@pytest.mark.parametrize('family', ('oracle', 'gates', 'warnings_and_reader'))
def test_f3_official_public_symbol_graph(family, monkeypatch):
    import scar.analysis.source_symbols as symbols_api
    from scar.analysis.source_symbols import read_source_symbols, source_symbols_document

    if family == 'oracle':
        kinds, scope_codes, seen_flags = set(), set(), 0
        for text in _corpus():
            inputs = _inputs(text)
            expected_root, expected_rows, warning_rows = _native_oracle(inputs[0], 'exec')
            document = source_symbols_document(*inputs)
            material = read_source_symbols(json.loads(json.dumps(document)), *inputs)
            assert material.status == 'CAPTURED'
            assert material.authority == 'PUBLIC_COMPILER_VIEW'
            assert material.ast_join == 'UNJOINED' and material.complete_lexical_scopes is False
            assert _tree(material.root, _stored_rows(material)) == _tree(expected_root, expected_rows)
            assert len(material.scopes) == len(expected_rows)
            assert document['warnings'] == [dict(
                category_module=item.category.__module__, category_name=item.category.__qualname__,
                message=str(item.message), filename=item.filename, lineno=item.lineno,
                line=item.line, source_present=item.source is not None) for item in warning_rows]
            assert document['profile']['warning_policy'] == 'RECORD_ALL_ALWAYS_ISOLATED_V1'
            constants = {item['name']: item['value'] for item in document['profile']['constants']}
            assert constants == {name: value for name, value in vars(_symtable).items() if name.isupper()}
            assert len(constants) == 26
            assert len([name for name in constants if name.startswith('TYPE_')]) == 7
            assert len([name for name in constants if name in ('LOCAL', 'GLOBAL_EXPLICIT', 'GLOBAL_IMPLICIT', 'FREE', 'CELL')]) == 5
            flags = {name: value for name, value in constants.items()
                     if name == 'USE' or name.startswith('DEF_') and name != 'DEF_BOUND'}
            assert len(flags) == 11
            members = document['profile']['raw_members']
            assert {row['name'] for row in members} == {
                'id', 'name', 'symbols', 'varnames', 'children', 'nested', 'type', 'lineno'}
            assert len(members) == 8
            for row in document['scopes']:
                assert set(row) == {'type', 'name', 'lineno', 'nested', 'varnames', 'symbols', 'children'}
            for row in material.scopes:
                assert all(type(value) is int for value in (row.type, row.nested, row.lineno))
                kinds.add(row.type)
                for symbol in row.symbols:
                    assert type(symbol.flags) is int
                    seen_flags |= symbol.flags
                    scope_codes.add((symbol.flags >> _symtable.SCOPE_OFF) & _symtable.SCOPE_MASK)
            if 'left=lambda' in text:
                children = [material.scopes[index] for index in material.scopes[material.root].children]
                for name in ('lambda', 'Same'):
                    twins = [row for row in children if row.name == name]
                    assert len(twins) == 2 and twins[0] == twins[1]
            if 'class __Owner' in text:
                owner = next(row for row in material.scopes if row.type == _symtable.TYPE_CLASS)
                assert '_Owner__method' in {item.name for item in owner.symbols}
                assert any(material.scopes[index].name == '__method' for index in owner.children)
                # Public namespace lookup is name-based and misses private methods.
                import symtable
                wrapped = symtable.symtable(text, inputs[0]['path'], 'exec')
                pending = [wrapped]
                while pending:
                    current = pending.pop()
                    if current.get_type() == 'class' and current.get_name() == '__Owner':
                        assert not current.lookup('_Owner__method').get_namespaces()
                        break
                    pending.extend(current.get_children())
                else:
                    pytest.fail('original private class scope disappeared')
        assert kinds == {getattr(_symtable, name) for name in constants if name.startswith('TYPE_')}
        assert {_symtable.LOCAL, _symtable.GLOBAL_EXPLICIT, _symtable.GLOBAL_IMPLICIT,
                _symtable.FREE, _symtable.CELL} <= scope_codes
        assert all(seen_flags & value for value in flags.values())
        for mode, text in (('eval', 'lambda x: x'), ('single', 'value=1\n')):
            inputs = _inputs(text, mode=mode)
            root, rows, _ = _native_oracle(inputs[0], mode)
            material = read_source_symbols(source_symbols_document(*inputs), *inputs)
            assert _tree(material.root, _stored_rows(material)) == _tree(root, rows)
        # Synthetic raw-graph alias probe, not a source/AST correspondence proof.
        raw = _symtable.symtable('def f(): pass\n', '/source/alias.py', 'exec')
        raw.children.append(raw.children[-1])
        aliases = symbols_api.capture_raw_view(raw)
        assert aliases[0].children[-1] == aliases[0].children[-2]
        assert len(aliases) == 1 + len({id(child) for child in raw.children})
        return

    inputs = _inputs('value=1\ndef f(x):\n    return x\n')
    document = source_symbols_document(*inputs)
    material = read_source_symbols(document, *inputs)

    if family == 'gates':
        context = symbols_api.compiler_hash_context()
        assert document['profile']['hash_context_sha256'] == context
        assert document['profile']['hash_randomization'] == sys.flags.hash_randomization
        with monkeypatch.context() as patch:
            patch.setenv('PYTHONHASHSEED', 'changed-after-startup')
            assert symbols_api.compiler_hash_context() == context
            assert read_source_symbols(document, *inputs) == material
        with monkeypatch.context() as patch:
            patch.setattr(symbols_api, 'compiler_hash_context', lambda: '0' * 64 if context != '0' * 64 else '1' * 64)
            def no_native(*args, **kwargs):
                raise AssertionError('changed hash context must reject before native replay')
            patch.setattr(symbols_api, '_native_symtable', no_native)
            with pytest.raises(ValueError, match='profile|hash context'):
                read_source_symbols(document, *inputs)
        # Official free-variable insertion order depends on the actual hash seed.
        source = ('def outer():\n    a=1;b=2;c=3;d=4;e=5\n'
                  '    def middle():\n        def inner(): return a,b,c,d,e\n'
                  '        return inner\n    return middle\n')
        script = ('import _symtable,json\nroot=_symtable.symtable(' + repr(source) +
                  ',"/hash-order.py","exec")\n'
                  'outer=next(c for c in root.children if c.name=="outer")\n'
                  'middle=next(c for c in outer.children if c.name=="middle")\n'
                  'print(json.dumps(list(middle.symbols.items())))\n')
        orders = [json.loads(subprocess.run([sys.executable, '-B', '-c', script],
            env={**os.environ, 'PYTHONHASHSEED': seed, 'PYTHONDONTWRITEBYTECODE': '1'},
            check=True, capture_output=True, text=True).stdout) for seed in ('0', '1')]
        assert orders[0] != orders[1] and dict(orders[0]) == dict(orders[1])
        # F2 fresh replay may parse ONLY_AST; this stage must not produce bytecode.
        original_compile = builtins.compile
        def ast_only(source, filename, mode, flags=0, **kwargs):
            import ast
            assert flags & ast.PyCF_ONLY_AST
            return original_compile(source, filename, mode, flags=flags, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(builtins, 'compile', ast_only)
            assert read_source_symbols(source_symbols_document(*inputs), *inputs) == material
        for limits in (dict(max_scopes=0), dict(max_symbols=0)):
            stopped = source_symbols_document(*inputs, **limits)
            assert stopped['status'] == 'BUDGET_STOPPED'
            assert stopped['frontiers'][0]['code'] == ('SCOPE_BUDGET' if 'max_scopes' in limits else 'SYMBOL_BUDGET')
            assert stopped['root'] is None and stopped['scopes'] == [] and stopped['frontiers']
            assert read_source_symbols(stopped, *inputs).status == 'BUDGET_STOPPED'
        upstream = [_inputs('x=(\n'), _inputs('x=1\n', max_tokens=0), _inputs('x = if :\n')]
        function_type = _inputs('(int) -> int', mode='func_type')
        def forbidden(*args, **kwargs):
            raise AssertionError('upstream or unsupported mode must not invoke native symtable')
        with monkeypatch.context() as patch:
            patch.setattr(symbols_api, '_native_symtable', forbidden)
            for a, b, c in upstream:
                rejected = source_symbols_document(a, b, c)
                assert rejected['root'] is None and rejected['scopes'] == []
                assert read_source_symbols(rejected, a, b, c).status == rejected['status']
            unsupported = source_symbols_document(*function_type)
            assert unsupported['status'] == 'UNSUPPORTED_SYMTABLE_MODE'
            assert read_source_symbols(unsupported, *function_type).status == unsupported['status']
        # Adapter validation failures are not official compiler diagnostics.
        with monkeypatch.context() as patch:
            patch.setattr(symbols_api, '_native_symtable', lambda *args: object())
            with pytest.raises((TypeError, ValueError)):
                source_symbols_document(*inputs)
        # This passes ONLY_AST and fails the official symbol analysis itself.
        invalid = _inputs('def f(a,a): pass\n')
        assert invalid[2]['status'] == 'PARSED'
        failure = source_symbols_document(*invalid)
        assert failure['status'] == 'SYMBOL_TABLE_ERROR'
        assert failure['error']['exception_type'] == 'SyntaxError'
        assert failure['scopes'] == [] and failure['root'] is None
        assert read_source_symbols(failure, *invalid).error is not None
        return

    warning_inputs = _inputs('value="\\q"\n')
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        ambient = list(warnings.filters)
        warned = source_symbols_document(*warning_inputs)
        assert warned['warnings'] and warned['warnings'][0]['category_name'] == 'SyntaxWarning'
        assert read_source_symbols(warned, *warning_inputs).warnings
        assert warnings.filters == ambient
    for route, replacement in (
        (('ast_join',), 'VERIFIED'), (('complete_lexical_scopes',), True),
        (('profile', 'constants', 0, 'value'), -1),
        (('profile', 'raw_members', 0, 'extra'), None),
        (('root',), True), (('scopes', 0, 'children'), [0]),
        (('scopes', 0, 'extra'), None), (('extra',), [])):
        changed = deepcopy(document)
        target = changed
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            read_source_symbols(changed, *inputs)
    different = _inputs('value=2\ndef f(x):\n    return x\n')
    with pytest.raises((TypeError, ValueError)):
        read_source_symbols(document, *different)

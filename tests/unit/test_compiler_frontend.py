"""Focused source-only tests for the guarded array-region adapter."""
from hashlib import sha256
from types import CodeType, SimpleNamespace

import pytest

from scar.compiler.frontend import discover_regions
from scar.trace.code_snapshot import code_key


def _source(tmp_path, text):
    path = tmp_path / 'source.py'
    path.write_text(text)
    return path


def _compiled_functions(path):
    pending = [compile(path.read_bytes(), str(path), 'exec', dont_inherit=True, optimize=0)]
    result = {}
    while pending:
        code = pending.pop()
        result[code.co_qualname] = code
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    return result


def test_generic_static_expression_aliases_provenance_and_no_execution(tmp_path):
    path = _source(tmp_path, '''target_must_never_execute()
class Arbitrary:
    @staticmethod
    def random(parameter):
        """A pure body is accepted regardless of names."""
        interior = parameter[1:-1, 1:-1]
        other = parameter[2:, 1:-1]
        alias = interior
        return -(alias - other * 2) / 4.0 + 0.25
''')
    regions, rejected = discover_regions(path)
    assert rejected == []
    assert len(regions) == 1
    region = regions[0]
    assert region.parameters == ('parameter',)
    assert region.source.qualname == 'Arbitrary.random'
    assert region.source.path == str(path)
    assert region.source.sha256 == sha256(path.read_bytes()).hexdigest()
    assert region.source.code_key == code_key(_compiled_functions(path)['Arbitrary.random'])
    assert region.source.line == 4 and region.source.column == 4
    assert region.source.origins[0]['span']['end_line'] == 9
    assert {node.op for node in region.nodes} == {'input', 'const', 'slice', 'sub', 'mul', 'neg', 'div', 'add'}
    assert [node.attrs['bounds'] for node in region.nodes if node.op == 'slice'] == [
        [[1, -1], [1, -1]], [[2, None], [1, -1]]]
    assert discover_regions(path) == (regions, [])


def test_scans_all_nested_functions_and_signature_orders(tmp_path):
    path = _source(tmp_path, '''def outer():
    def inner(a, /, b, *, c):
        return a + b * c
    return inner
class Container:
    def method(self, x):
        return x - 1
''')
    regions, rejected = discover_regions(path)
    assert [region.source.qualname for region in regions] == ['outer.<locals>.inner', 'Container.method']
    assert regions[0].parameters == ('a', 'b', 'c')
    # The frontend treats even an instance receiver as an array parameter;
    # runtime installation owns the exact ndarray rejection.
    assert regions[1].parameters == ('self', 'x')
    assert rejected[0]['qualname'] == 'outer'
    for region in regions:
        assert region.source.code_key == code_key(_compiled_functions(path)[region.source.qualname])


@pytest.mark.parametrize(('body', 'reason'), [
    ('return a', 'ALIASED_OUTPUT'),
    ('return a[1:, :]', 'ALIASED_OUTPUT'),
    ('return 2', 'SCALAR_OUTPUT'),
    ('return a + external', 'UNBOUND_NAME'),
    ('return a.attribute + 1', 'UNSUPPORTED_STATE_READ'),
    ('return rng.random(a)', 'UNSUPPORTED_CALL'),
    ('a[:, :] = 1\nreturn a + 1', 'UNSUPPORTED_WRITE'),
    ('a += 1\nreturn a + 1', 'UNSUPPORTED_WRITE'),
    ('if a:\n    return a + 1\nreturn a + 2', 'UNSUPPORTED_STATEMENT'),
    ('for x in a:\n    pass\nreturn a + 1', 'UNSUPPORTED_STATEMENT'),
    ('return a ** 2', 'UNSUPPORTED_OPERATOR'),
    ('return a + True', 'UNSUPPORTED_EXPRESSION'),
    ('return a + 1e999', 'UNSUPPORTED_CONSTANT'),
    ('return a + 9007199254740993', 'UNSUPPORTED_CONSTANT'),
    ('return a + (1 / 0)', 'SCALAR_ARITHMETIC'),
    ('return a[::2, :] + 1', 'UNSUPPORTED_SLICE_STEP'),
    ('return a[a:, :] + 1', 'NONCONSTANT_SLICE_BOUND'),
    ('return a[0, :] + 1', 'UNSUPPORTED_SLICE'),
    ('return a[:] + 1', 'UNSUPPORTED_SLICE'),
    ('return (a + 1)[:, :] + 2', 'UNSUPPORTED_SLICE_BASE'),
    ('unused = a / 0\nreturn a + 1', 'UNUSED_ARITHMETIC'),
    ('return a + 1\na = a + 2', 'NONFINAL_RETURN'),
    ('pass', 'UNSUPPORTED_STATEMENT'),
])
def test_explicit_rejection_frontiers(tmp_path, body, reason):
    path = _source(tmp_path, 'def candidate(a):\n' + ''.join('    ' + line + '\n' for line in body.splitlines()))
    regions, rejected = discover_regions(path)
    assert regions == []
    assert len(rejected) == 1
    assert rejected[0]['code'] == rejected[0]['reason'] == reason
    assert rejected[0]['path'] == str(path)
    assert rejected[0]['qualname'] == 'candidate'
    assert rejected[0]['detail']
    assert rejected[0]['line'] >= 1


@pytest.mark.parametrize('prefix', ['@custom\n', '@staticmethod()\n', '@owner.staticmethod\n', '@classmethod\n'])
def test_rejects_other_decorators(tmp_path, prefix):
    path = _source(tmp_path, prefix + 'def candidate(a):\n    return a + 1\n')
    regions, rejected = discover_regions(path)
    assert regions == []
    assert rejected[0]['code'] == 'UNSUPPORTED_DECORATOR'


def test_signed_constants_unit_slices_and_parameter_rebinding(tmp_path):
    path = _source(tmp_path, '''def candidate(a):
    a = a[None:-1:+1, ::None]
    result = a + -0.0
    return result - -2
''')
    regions, rejected = discover_regions(path)
    assert rejected == []
    assert regions[0].nodes[1].attrs['bounds'] == [[None, -1], [None, None]]
    assert [node.attrs['value'] for node in regions[0].nodes if node.op == 'const'] == [-0.0, -2]


def test_attaches_original_catalog_unit_and_f2_occurrences(tmp_path, monkeypatch):
    from scar.analysis import source_declared_catalog
    from scar.analysis.source_bytes import source_bytes_document
    from scar.analysis.source_tokens import source_tokens_document
    from scar.analysis.source_syntax import source_syntax_document
    from scar.analysis.static_program import _write

    path = _source(tmp_path, 'def candidate(a):\n    alias = a[1:, :]\n    return alias * 3\n')
    original_unit = 'source:original-identity-preserved'
    root = tmp_path / 'materials'
    root.mkdir()
    f0 = source_bytes_document(path.read_bytes(), path=str(path), namespace_root=str(tmp_path))
    f1 = source_tokens_document(f0, max_tokens=1000)
    f2 = source_syntax_document(f0, f1, max_nodes=1000)
    source = dict(schema='scar.static-source-text', schema_version=1,
        path=str(path), namespace_root=str(tmp_path),
        raw_sha256=sha256(path.read_bytes()).hexdigest(),
        decoded_sha256=sha256(path.read_bytes()).hexdigest(), encoding='utf-8', text=path.read_text())
    # Use the existing source-envelope shape instead of compiling an entire
    # program model just to test this per-file F2 projection.
    artifacts = {name: _write(root, name + '.json.gz', document)
        for name, document in [('source', source), ('source_bytes', f0), ('source_tokens', f1), ('source_syntax', f2)]}
    unit = dict(key=original_unit, path=str(path), namespace_root=str(tmp_path),
        raw_sha256=sha256(path.read_bytes()).hexdigest(), decoded_sha256=sha256(path.read_bytes()).hexdigest(),
        encoding='utf-8', size_bytes=len(path.read_bytes()), source_bytes=len(path.read_bytes()), artifacts=artifacts)
    facts = SimpleNamespace(model_units={original_unit: unit}, model_for=lambda identity: root)
    catalog = SimpleNamespace(fact_store=facts, units_for_source=lambda selected: {original_unit})
    calls = []

    def read_catalog(value):
        calls.append(value)
        return catalog

    monkeypatch.setattr(source_declared_catalog, 'read_source_catalog', read_catalog)
    regions, rejected = discover_regions(path, catalog='existing-catalog')
    assert calls == ['existing-catalog']
    assert rejected == []
    origins = [origin for origin in regions[0].source.origins if 'unit' in origin]
    assert origins
    assert {origin['unit'] for origin in origins} == {original_unit}
    for origin in origins:
        assert f2['nodes'][origin['occurrence']]['constructor'] == origin['constructor']
        assert origin['f2_sha256'] == artifacts['source_syntax']['decoded_sha256']
    assert any(origin['constructor'] == 'FunctionDef' for origin in origins)
    assert any(origin['constructor'] == 'BinOp' for origin in origins)
    path.write_text('def candidate(a):\n    return a + 4\n')
    regions, rejected = discover_regions(path, catalog='existing-catalog')
    assert regions == []
    assert rejected[0]['code'] == 'CATALOG_SOURCE_MISMATCH'


def test_invalid_source_is_a_rejection_record(tmp_path):
    path = _source(tmp_path, 'def broken(:\n')
    assert discover_regions(path)[1][0]['code'] == 'SOURCE_COMPILATION_FAILED'

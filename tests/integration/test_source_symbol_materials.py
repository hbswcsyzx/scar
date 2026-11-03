"""F3-A material stores and canonical append preserve existing endpoints."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import ast
import builtins
import json
import shutil
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.static_program import _json, _write


def _snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def test_f3_material_store_is_independent_fresh_and_append_only(tmp_path, monkeypatch):
    from scar.analysis.source_symbol_materials import _symbol_unit, main, model_source_symbols
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir()
    model.mkdir()
    units = []
    for number, raw in enumerate((
        b'def ordinary(second,first):\n return first\nraise RuntimeError("never execute")\n',
        b'nonlocal missing\n',
        b'class Holder:\n value=1\n def method(self): return self.value\n')):
        path, key = source / f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = {'schema': 'scar.static-source-text', 'schema_version': 1,
            'path': str(path), 'namespace_root': str(source), 'raw_sha256': sha256(raw).hexdigest(),
            'decoded_sha256': sha256(text.encode()).hexdigest(), 'encoding': encoding, 'text': text}
        # An opaque pre-existing artifact exercises byte/endpoint preservation;
        # F3 does not interpret it or claim that this fixture validates old IR.
        old = _write(model, 'units/' + key + '/old_core.json.gz', {'endpoint': 'preserved:' + key})
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | {'key': key, 'source_bytes': len(raw), 'bodies': [{'entry_key': 'prior:' + key, 'artifact': old}],
               'artifacts': {'source': _write(model, 'units/' + key + '/source.json.gz', envelope)}})
    (model / 'manifest.json').write_bytes(_json({'schema': 'scar.static-program',
        'schema_version': 1, 'units': units, 'remaining': [], 'source_issues': []}))
    original_compile = builtins.compile
    def only_ast(text, filename, mode, flags=0, *args, **kwargs):
        if str(filename).startswith(str(source)):
            assert flags & ast.PyCF_ONLY_AST
        return original_compile(text, filename, mode, flags, *args, **kwargs)
    monkeypatch.setattr(builtins, 'compile', only_ast)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    parsed = model_source_syntax(model, tmp_path / 'f2', jobs=1)
    assert parsed['status_counts'] == {'PARSED': 3}
    before = _snapshot(model)

    import scar.analysis.source_symbols as symbols
    def forbidden_native(*args, **kwargs):
        raise AssertionError('mismatched worker context must be rejected before producing native facts')
    with monkeypatch.context() as patch:
        patch.setattr(symbols, 'source_symbols_document', forbidden_native)
        limits = dict(max_scopes=100_000, max_symbols=1_000_000, max_nodes=1_000_000, max_tokens=2_000_000)
        with pytest.raises(ValueError, match='fixed PYTHONHASHSEED'):
            _symbol_unit((model, None, units[0], limits, None, None, False, 'not-the-parent-context'))

    for limit in ({'max_scopes': 0}, {'max_symbols': 0}):
        report = model_source_symbols(model, tmp_path / ('budget-' + next(iter(limit))), jobs=1, **limit)
        assert not report['complete_for_declared_units'] and not report['canonical_model_published']
        assert _snapshot(model) == before

    store = tmp_path / 'materials'
    def no_clone(*args, **kwargs):
        raise AssertionError('collect-only must not clone or write the model')
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil, 'copytree', no_clone)
            collected = model_source_symbols(model, store, jobs=1, collect_only=True)
    finally:
        model.chmod(0o755)
    assert collected['status_counts'] == {'CAPTURED': 2, 'SYMBOL_TABLE_ERROR': 1}
    assert collected['complete_for_declared_units'] and not collected['all_declared_tables_captured']
    assert collected['manifest_unchanged'] and not collected['canonical_model_published']
    assert collected['authority'] == 'PUBLIC_COMPILER_VIEW' and collected['ast_join'] == 'UNJOINED'
    assert collected['complete_lexical_scopes'] is collected['whole_program_complete'] is False
    assert _snapshot(model) == before

    # Current model metadata may change without changing any source prerequisite.
    # A full manifest SHA is an observation, not the store's dependency basis.
    current = json.loads((model / 'manifest.json').read_bytes())
    current['unrelated_note'] = 'new model metadata'
    (model / 'manifest.json').write_bytes(_json(current))
    readonly = _snapshot(model)
    checked = model_source_symbols(model, tmp_path / 'store-check', jobs=1, verify=True, materials=store)
    assert checked['complete_for_declared_units'] and checked['material_source_basis_unchanged']
    assert checked['observed_manifest_sha256'] != collected['observed_manifest_sha256']
    assert _snapshot(model) == readonly
    for limits in ({'max_scopes': 0}, {'max_symbols': 0}, {'max_nodes': 0}, {'max_tokens': 0}):
        with pytest.raises(ValueError, match='budget'):
            model_source_symbols(model, tmp_path / ('check-' + next(iter(limits))),
                jobs=1, verify=True, materials=store, **limits)

    first = store / collected['results'][0]['artifact']['path']
    payload = first.read_bytes()
    first.write_bytes(payload + b'changed')
    try:
        with pytest.raises(ValueError, match='receipt'):
            model_source_symbols(model, tmp_path / 'changed-payload', jobs=1, verify=True, materials=store)
    finally:
        first.write_bytes(payload)
    result = store / 'result.json'
    original = result.read_bytes()
    malformed = deepcopy(json.loads(original))
    malformed['basis'][0]['raw_sha256'] = '0' * 64
    result.write_bytes(_json(malformed))
    try:
        with pytest.raises(ValueError, match='basis'):
            model_source_symbols(model, tmp_path / 'changed-basis', jobs=1, verify=True, materials=store)
    finally:
        result.write_bytes(original)
    for key, replacement in (
        ('scopes', collected['scopes'] + 1), ('symbols', collected['symbols'] + 1),
        ('status_counts', {'CAPTURED': 3}), ('complete_for_declared_units', False),
        ('units', True), ('covered_units', False), ('jobs', 0), ('seconds', -1)):
        malformed = deepcopy(json.loads(original))
        malformed[key] = replacement
        result.write_bytes(_json(malformed))
        try:
            with pytest.raises(ValueError):
                model_source_symbols(model, tmp_path / ('changed-summary-' + key), jobs=1,
                    verify=True, materials=store)
        finally:
            result.write_bytes(original)
    note = store / 'unowned.txt'
    note.write_text('keep me')
    try:
        with pytest.raises(ValueError, match='unowned'):
            model_source_symbols(model, tmp_path / 'unowned-store', jobs=1, verify=True, materials=store)
        assert note.read_text() == 'keep me'
    finally:
        note.unlink()

    published = model_source_symbols(model, tmp_path / 'canonical', jobs=1)
    assert published['complete_for_declared_units'] and published['canonical_model_published']
    after = json.loads((model / 'manifest.json').read_bytes())
    for old, new in zip(current['units'], after['units']):
        assert {**new, 'artifacts': {k: v for k, v in new['artifacts'].items() if k != 'source_symbols'}} == old
    assert all((model / name).read_bytes() == data for name, data in readonly.items() if name != 'manifest.json')
    canonical = model_source_symbols(model, tmp_path / 'canonical-check', jobs=2, verify=True)
    assert canonical['complete_for_declared_units'] and canonical['manifest_unchanged']
    # The external store remains reusable after the new canonical sidecar appears.
    assert model_source_symbols(model, tmp_path / 'store-after-append', jobs=1,
        verify=True, materials=store)['complete_for_declared_units']

    file_store, file_report = tmp_path / 'file-store', tmp_path / 'file-check'
    assert main(['--file', str(source / '0.py'), '--out', str(file_store)]) == 0
    file_receipt = file_store / 'result.json'
    original_file_receipt = file_receipt.read_bytes()
    malformed = json.loads(original_file_receipt)
    malformed['scopes'] += 1
    file_receipt.write_bytes(_json(malformed))
    try:
        with pytest.raises(ValueError, match='summary'):
            main(['--file', str(source / '0.py'), '--materials', str(file_store),
                '--out', str(tmp_path / 'file-summary-rejected'), '--verify'])
    finally:
        file_receipt.write_bytes(original_file_receipt)
    assert main(['--file', str(source / '0.py'), '--materials', str(file_store),
        '--out', str(file_report), '--verify']) == 0
    assert json.loads((file_report / 'result.json').read_bytes())['authority'] == 'PUBLIC_COMPILER_VIEW'

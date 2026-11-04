"""A real saved frontend chain is checked without publishing or executing it."""
from hashlib import sha256
from io import BytesIO
import json
import shutil
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.source_role_materials import model_source_roles
from scar.analysis.source_context_materials import model_source_contexts
from scar.analysis.source_declaration_materials import model_source_declarations
from scar.analysis.source_binding_materials import model_source_bindings
from scar.analysis.source_symbol_materials import model_source_symbols
from scar.analysis.compiler_topology_materials import model_compiler_topology
from scar.analysis.compiler_symbol_materials import model_compiler_symbols
from scar.analysis.static_program import _json, _write


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_read_only_frontend_check_preserves_inputs_and_all_units(tmp_path, monkeypatch):
    from scar.analysis.frontend_check import check_frontend, main
    source, model = tmp_path/'source', tmp_path/'model'
    source.mkdir(); model.mkdir(); units = []
    for number, raw in enumerate((
        b'from __future__ import annotations\nclass Owner:\n    value: Later\n'
        b'    def method(self, item): return super().method(item)\n'
        b'def outer(data):\n    base=1\n    return [base+x for x in data]\n'
        b'raise RuntimeError("the target must never execute")\n',
        b'def invalid(item, item): pass\n')):
        path, key = source/f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = dict(schema='scar.static-source-text', schema_version=1, path=str(path), namespace_root=str(source),
            raw_sha256=sha256(raw).hexdigest(), decoded_sha256=sha256(text.encode()).hexdigest(), encoding=encoding, text=text)
        old = _write(model, 'units/'+key+'/old_core.json.gz', {'original_endpoint': key})
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | dict(key=key, source_bytes=len(raw), bodies=[dict(entry_key='old:'+key, artifact=old)],
                   artifacts={'source': _write(model, 'units/'+key+'/source.json.gz', envelope)}))
    (model/'manifest.json').write_bytes(_json(dict(schema='scar.static-program', schema_version=1,
                                                units=units, remaining=[], source_issues=[])))
    archive_model_source_bytes(model, tmp_path/'f0', jobs=1)
    model_source_tokens(model, tmp_path/'f1', jobs=1)
    model_source_syntax(model, tmp_path/'f2', jobs=1)
    b, c, d, q, a, t, s = [tmp_path/name for name in ('roles', 'contexts', 'declarations', 'bindings', 'symbols', 'topology', 'compiler-symbols')]
    model_source_roles(model, b, jobs=1, collect_only=True)
    model_source_contexts(model, c, roles_materials=b, jobs=1, collect_only=True)
    model_source_declarations(model, d, roles_materials=b, contexts_materials=c, jobs=1, collect_only=True)
    model_source_bindings(model, q, roles_materials=b, contexts_materials=c, declarations_materials=d, jobs=1, collect_only=True)
    model_source_symbols(model, a, jobs=1, collect_only=True)
    model_compiler_topology(model, t, roles_materials=b, contexts_materials=c, symbols_materials=a, jobs=1, collect_only=True)
    model_compiler_symbols(model, s, roles_materials=b, contexts_materials=c, declarations_materials=d,
                          symbols_materials=a, topology_materials=t, jobs=1, collect_only=True)
    stores = (b, c, d, q, a, t, s)
    before = [_snapshot(root) for root in (model, *stores)]
    external = dict(zip(('roles_materials', 'contexts_materials', 'declarations_materials', 'bindings_materials',
                         'symbols_materials', 'topology_materials', 'compiler_symbols_materials'), stores))
    output = tmp_path/'checked'
    argv = ['--model', str(model), '--out', str(output), '--jobs', '2']
    for name, path in external.items():
        argv.extend(('--'+name.replace('_', '-'), str(path)))
    def no_clone(*args, **kwargs):
        raise AssertionError('read-only frontend check must not clone or publish the model')
    with monkeypatch.context() as patch:
        patch.setattr(shutil, 'copytree', no_clone)
        assert main(argv) == 1  # The invalid scope remains an explicit original unit.
    result = json.loads((output/'result.json').read_bytes())
    assert result['units'] == 2 and [row['unit'] for row in result['results']] == ['0', '1']
    assert result['status_counts'] == {'VERIFIED': 1, 'UPSTREAM_NOT_READY': 1}
    assert not result['complete_for_declared_units']
    valid, unavailable = result['results']
    assert valid['ports'] and valid['raw_events'] and valid['implicit_omissions']
    assert unavailable['statuses']['source_symbols'] == 'SYMBOL_TABLE_ERROR'
    assert unavailable['input_counts']['ports'] > 0 and unavailable['error']['code'] == 'UPSTREAM_NOT_ACCEPTED'
    assert result['input_stores_unchanged'] and result['original_model_artifacts_unchanged']
    assert result['manifest_unchanged'] and not result['canonical_model_published']
    assert not result['new_materials_written'] and not result['target_executed'] and not result['bytecode_generated']
    assert result['runtime_binding'] == 'NOT_OBSERVED' and not result['whole_program_complete']
    assert set(_snapshot(output)) == {'result.json'}
    assert set(result['input_stores']) == {'source_roles', 'source_contexts', 'source_declarations',
        'source_bindings', 'source_symbols', 'compiler_topology', 'compiler_symbols'}
    owned_stores = dict(zip(('source_roles', 'source_contexts', 'source_declarations', 'source_bindings',
                            'source_symbols', 'compiler_topology', 'compiler_symbols'), stores))
    for name, receipt in result['input_stores'].items():
        owner = owned_stores[name]
        assert receipt['root'] == str(owner) and receipt['receipt_kind'] == 'RESULT_JSON'
        assert receipt['receipt_sha256'] == sha256((owner/'result.json').read_bytes()).hexdigest()
        assert receipt['units'] == 2
        assert receipt['catalog_sha256'] is not None or name == 'source_symbols'
    from pathlib import Path
    assert set(result['implementation']) == {'query', 'driver'}
    for receipt in result['implementation'].values():
        assert receipt['sha256'] == sha256(Path(receipt['path']).read_bytes()).hexdigest()
    assert result['frontend_binding_contract']['rule_version'] == 'F3D_ORIGINAL_REFERENCE_COMPOSITION_V1'
    assert result['frontend_binding_contract_sha256'] == sha256(_json(result['frontend_binding_contract'])).hexdigest()
    assert [_snapshot(root) for root in (model, *stores)] == before
    with pytest.raises(ValueError, match='fresh'):
        check_frontend(model, output, **external)
    with pytest.raises(ValueError, match='budget'):
        check_frontend(model, tmp_path/'limited', max_tokens=0, **external)
    # Re-signed source-store summaries cannot bypass their original owner checker.
    manifest = q/'result.json'; original = manifest.read_bytes()
    changed = json.loads(original); changed['implicit'] += 1
    manifest.write_bytes(_json(changed))
    try:
        with pytest.raises(ValueError):
            check_frontend(model, tmp_path/'false-summary', **external)
    finally:
        manifest.write_bytes(original)
    note = s/'unowned.txt'; note.write_text('preserve this input')
    try:
        with pytest.raises(ValueError, match='unowned'):
            check_frontend(model, tmp_path/'unowned', **external)
        assert note.read_text() == 'preserve this input'
    finally:
        note.unlink()
    assert [_snapshot(root) for root in (model, *stores)] == before

"""F3-B owns sparse slot-role materials; no scope compiler is consulted."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import shutil
import symtable
import _symtable
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_f3b_sparse_roles_share_catalog_and_preserve_material_basis(tmp_path, monkeypatch):
    from scar.analysis.source_role_materials import main, model_source_roles
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir()
    model.mkdir()
    units = []
    for number, raw in enumerate((
        b'import unavailable as alias\nvalue=[0,1,2,3,4,5,6,7,8,9]\n'
        b'obj.attribute = call(value, keyword=None)\nraise RuntimeError("never execute")\n',
        b'nonlocal missing\n', b'value = if\n')):
        path, key = source / f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = {'schema': 'scar.static-source-text', 'schema_version': 1,
            'path': str(path), 'namespace_root': str(source), 'raw_sha256': sha256(raw).hexdigest(),
            'decoded_sha256': sha256(text.encode()).hexdigest(), 'encoding': encoding, 'text': text}
        old = _write(model, 'units/' + key + '/old_core.json.gz', {'opaque_prior_endpoint': key})
        units.append({key: value for key, value in envelope.items() if key not in ('schema', 'schema_version', 'text')}
            | {'key': key, 'source_bytes': len(raw), 'bodies': [{'entry_key': 'prior:' + key, 'artifact': old}],
               'artifacts': {'source': _write(model, 'units/' + key + '/source.json.gz', envelope)}})
    (model / 'manifest.json').write_bytes(_json({'schema': 'scar.static-program', 'schema_version': 1,
        'units': units, 'remaining': [], 'source_issues': []}))
    def forbidden(*args, **kwargs):
        raise AssertionError('F3-B must not invoke a symbol-table API')
    monkeypatch.setattr(symtable, 'symtable', forbidden)
    monkeypatch.setattr(_symtable, 'symtable', forbidden)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    parsed = model_source_syntax(model, tmp_path / 'f2', jobs=1)
    assert parsed['status_counts'] == {'PARSED': 2, 'PARSER_ERROR': 1}
    before = _snapshot(model)
    for limit in ({'max_ports': 0}, {'max_slots': 0}):
        report = model_source_roles(model, tmp_path / ('budget-' + next(iter(limit))), jobs=1, **limit)
        assert not report['complete_for_declared_units'] and not report['canonical_model_published']
        assert _snapshot(model) == before

    store = tmp_path / 'materials'
    def no_clone(*args, **kwargs):
        raise AssertionError('collect-only must not clone the read-only model')
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil, 'copytree', no_clone)
            captured = model_source_roles(model, store, jobs=1, collect_only=True)
    finally:
        model.chmod(0o755)
    assert captured['status_counts'] == {'CLASSIFIED': 2, 'UPSTREAM_NOT_PARSED': 1}
    assert captured['complete_for_declared_units'] and not captured['all_declared_units_classified']
    assert captured['authority'] == 'SYNTAX_FIELD_ROLES' and not captured['symtable_executed']
    assert captured['manifest_unchanged'] and not captured['canonical_model_published']
    assert _snapshot(model) == before
    assert len(list(store.rglob('catalog.json.gz'))) == 1
    catalog = _Fragments(store).read(captured['catalog'])
    assert len(catalog['constructors']) == 113 and len(catalog['rules']) == 484
    assert len(captured['rule_counts']) == 484
    for row, unit in zip(captured['results'], json.loads(before['manifest.json'])['units']):
        document = _Fragments(store).read(row['artifact'])
        assert 'catalog' not in document and document['profile']['catalog_sha256'] == catalog['content_sha256']
        if row['status'] == 'CLASSIFIED':
            syntax = _Fragments(model).read(unit['artifacts']['source_syntax'])
            assert row['slots'] == sum(len(n['fields']) + len(n['attributes']) for n in syntax['nodes'])
            assert row['ports'] < row['slots']

    current = json.loads((model / 'manifest.json').read_bytes())
    current['unrelated_note'] = 'new metadata, same source receipts'
    (model / 'manifest.json').write_bytes(_json(current))
    readonly = _snapshot(model)
    verified = model_source_roles(model, tmp_path / 'store-check', jobs=1, verify=True, materials=store)
    assert verified['material_source_basis_unchanged'] and verified['complete_for_declared_units']
    assert verified['observed_manifest_sha256'] != captured['observed_manifest_sha256']
    assert _snapshot(model) == readonly
    for limits in ({'max_ports': 0}, {'max_slots': 0}, {'max_nodes': 0}, {'max_tokens': 0}):
        with pytest.raises(ValueError, match='budget'):
            model_source_roles(model, tmp_path / ('replay-' + next(iter(limits))),
                jobs=1, verify=True, materials=store, **limits)

    result = store / 'result.json'
    original = result.read_bytes()
    changes = [('ports', captured['ports'] + 1), ('complete_for_declared_units', False),
        ('status_counts', {'CLASSIFIED': 3}), ('jobs', True)]
    for key, replacement in changes:
        changed = deepcopy(json.loads(original))
        changed[key] = replacement
        result.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):
                model_source_roles(model, tmp_path / ('changed-' + key), jobs=1, verify=True, materials=store)
        finally:
            result.write_bytes(original)
    catalog_path = store / captured['catalog']['path']
    content = catalog_path.read_bytes()
    catalog_path.write_bytes(content + b'changed')
    try:
        with pytest.raises(ValueError, match='receipt'):
            model_source_roles(model, tmp_path / 'changed-catalog', jobs=1, verify=True, materials=store)
    finally:
        catalog_path.write_bytes(content)
    note = store / 'unowned.txt'
    note.write_text('retain me')
    try:
        with pytest.raises(ValueError, match='unowned'):
            model_source_roles(model, tmp_path / 'unowned', jobs=1, verify=True, materials=store)
        assert note.read_text() == 'retain me'
    finally:
        note.unlink()

    published = model_source_roles(model, tmp_path / 'canonical', jobs=1)
    assert published['canonical_model_published'] and published['complete_for_declared_units']
    after = json.loads((model / 'manifest.json').read_bytes())
    for old, new in zip(current['units'], after['units']):
        assert {**new, 'artifacts': {key: value for key, value in new['artifacts'].items() if key != 'source_roles'}} == old
    assert all((model / name).read_bytes() == data for name, data in readonly.items() if name != 'manifest.json')
    assert after['source_roles']['artifacts'] == [published['catalog']]
    checked = model_source_roles(model, tmp_path / 'canonical-check', jobs=2, verify=True)
    assert checked['complete_for_declared_units'] and checked['manifest_unchanged']
    assert main(['--model', str(model), '--out', str(tmp_path / 'cli-check'), '--verify', '--jobs', '1']) == 0

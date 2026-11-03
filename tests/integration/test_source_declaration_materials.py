"""One C2a IO transaction over detached B/C1 stores, without lookup or execution."""
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
from scar.analysis.source_role_materials import model_source_roles
from scar.analysis.source_context_materials import model_source_contexts
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_c2a_declarations_preserve_detached_inputs_and_old_model_endpoints(tmp_path, monkeypatch):
    from scar.analysis.source_declaration_materials import main, model_source_declarations
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir();model.mkdir()
    units = []
    for number, raw in enumerate((
        b'root = 1\ndef enclosing(values):\n    global shared\n    local = values\n'
        b'    local += 1\n    del local\n    return [shadow for shadow in values]\n'
        b'class Owner[__A: __B, __B]:\n    __private = 1\n'
        b'raise RuntimeError("never execute")\n',
        b'def conflict(item):\n    global item\n', b'value = if\n')):
        path, key = source / f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = dict(schema='scar.static-source-text', schema_version=1, path=str(path), namespace_root=str(source),
            raw_sha256=sha256(raw).hexdigest(), decoded_sha256=sha256(text.encode()).hexdigest(), encoding=encoding, text=text)
        old = _write(model, 'units/' + key + '/old_core.json.gz', {'opaque_prior_endpoint': key})
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | dict(key=key, source_bytes=len(raw), bodies=[dict(entry_key='old:' + key, artifact=old)],
                artifacts={'source': _write(model, 'units/' + key + '/source.json.gz', envelope)}))
    (model / 'manifest.json').write_bytes(_json(dict(schema='scar.static-program', schema_version=1,
        units=units, remaining=[], source_issues=[])))
    def forbidden(*args, **kwargs):
        raise AssertionError('C2a must not use official symbol tables or execute this source')
    monkeypatch.setattr(symtable, 'symtable', forbidden)
    monkeypatch.setattr(_symtable, 'symtable', forbidden)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    model_source_syntax(model, tmp_path / 'f2', jobs=1)
    b, c = tmp_path / 'roles', tmp_path / 'contexts'
    b_report = model_source_roles(model, b, jobs=1, collect_only=True)
    c_report = model_source_contexts(model, c, roles_materials=b, jobs=1, collect_only=True)
    before, b_before, c_before = _snapshot(model), _snapshot(b), _snapshot(c)
    external = dict(roles_materials=b, contexts_materials=c, jobs=1)
    with pytest.raises(ValueError, match='external.*collect-only'):
        model_source_declarations(model, tmp_path / 'bad-canonical', **external)
    with pytest.raises(ValueError, match='requires canonical'):
        model_source_declarations(model, tmp_path / 'missing-inputs', jobs=1, collect_only=True)
    for key in ('max_names', 'max_contributions'):
        report = model_source_declarations(model, tmp_path / ('budget-' + key), collect_only=True,
            **external, **{key: 0})
        assert not report['complete_for_declared_units'] and not report['canonical_model_published']
        assert _snapshot(model) == before
    store = tmp_path / 'declarations'
    def no_clone(*args, **kwargs):
        raise AssertionError('detached declaration capture must not clone the read-only model')
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil, 'copytree', no_clone)
            captured = model_source_declarations(model, store, collect_only=True, **external)
    finally:
        model.chmod(0o755)
    assert captured['status_counts'] == {'DECLARED': 2, 'UPSTREAM_NOT_CONTEXTUALIZED': 1}
    assert captured['complete_for_declared_units'] and captured['conflicts'] > 0
    assert captured['authority'] == 'SOURCE_NAME_DECLARATIONS' and captured['lookup_resolution'] == 'NOT_COMPUTED_IN_C2A'
    assert not captured['symtable_executed'] and not captured['canonical_model_published']
    assert captured['manifest_unchanged'] and len(list(store.rglob('catalog.json.gz'))) == 1
    assert _snapshot(model) == before and _snapshot(b) == b_before and _snapshot(c) == c_before
    for row, b_row, c_row, basis in zip(captured['results'], b_report['results'], c_report['results'], captured['basis']):
        assert basis['artifacts']['source_roles'] == b_row['artifact']
        assert basis['artifacts']['source_contexts'] == c_row['artifact']
        document = _Fragments(store).read(row['artifact'])
        assert 'nodes' not in document and 'catalog' not in document
        assert document['profile']['declaration_catalog_sha256'] == captured['catalog_sha256']
    verified = model_source_declarations(model, tmp_path / 'fresh', verify=True, materials=store, **external)
    assert verified['complete_for_declared_units'] and verified['material_source_basis_unchanged']
    assert _snapshot(model) == before and _snapshot(b) == b_before and _snapshot(c) == c_before
    for key in ('max_names', 'max_nodes', 'max_scopes'):
        with pytest.raises(ValueError, match='budget'):
            model_source_declarations(model, tmp_path / ('limit-' + key), verify=True,
                materials=store, **external, **{key: 0})
    for owner, counter in ((store, 'names'), (b, 'ports'), (c, 'scopes')):
        result, original = owner / 'result.json', (owner / 'result.json').read_bytes()
        changed = deepcopy(json.loads(original));changed[counter] += 1
        result.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):
                model_source_declarations(model, tmp_path / ('tamper-' + counter), verify=True, materials=store, **external)
        finally:
            result.write_bytes(original)
    for owner, report in ((b, b_report), (c, c_report), (store, captured)):
        catalog = owner / report['catalog']['path']
        original = catalog.read_bytes();catalog.write_bytes(original + b'changed')
        try:
            with pytest.raises(ValueError, match='receipt'):
                model_source_declarations(model, tmp_path / ('catalog-' + owner.name), verify=True, materials=store, **external)
        finally:
            catalog.write_bytes(original)
    note = c / 'unowned.txt';note.write_text('keep me')
    try:
        with pytest.raises(ValueError, match='unowned'):
            model_source_declarations(model, tmp_path / 'unowned', verify=True, materials=store, **external)
        assert note.read_text() == 'keep me'
    finally:
        note.unlink()
    model_source_roles(model, tmp_path / 'b-publish', jobs=1)
    model_source_contexts(model, tmp_path / 'c-publish', jobs=1)
    prior_publish = _snapshot(model)
    published = model_source_declarations(model, tmp_path / 'publish', jobs=1)
    assert published['canonical_model_published'] and published['complete_for_declared_units']
    assert all((model / key).read_bytes() == raw for key, raw in prior_publish.items() if key != 'manifest.json')
    after = json.loads((model / 'manifest.json').read_bytes())
    assert after['source_declarations']['artifacts'] == [published['catalog']]
    for old, new in zip(json.loads(prior_publish['manifest.json'])['units'], after['units']):
        assert {**new, 'artifacts': {key: value for key, value in new['artifacts'].items() if key != 'source_declarations'}} == old
    checked = model_source_declarations(model, tmp_path / 'canonical-check', jobs=2, verify=True)
    assert checked['complete_for_declared_units'] and checked['manifest_unchanged']
    assert main(['--model', str(model), '--out', str(tmp_path / 'cli'), '--verify', '--jobs', '1']) == 0

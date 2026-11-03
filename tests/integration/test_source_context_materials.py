"""One context-stage transaction over canonical F2 and detached F3-B materials."""
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
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_c1_contexts_use_detached_roles_without_publishing_external_references(tmp_path, monkeypatch):
    from scar.analysis.source_context_materials import main, model_source_contexts
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir()
    model.mkdir()
    units = []
    for number, raw in enumerate((
        b'global_value = 1\ndef outer(value: Annotation = default_value):\n'
        b'    return [lambda: item for item in value]\n'
        b'class Owner[T: Bound = Default]:\n    field: T\n'
        b'    def method(self, value: T = global_value): return value\n'
        b'raise RuntimeError("never execute")\n',
        b'nonlocal missing\n', b'value = if\n')):
        path, key = source / f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = dict(schema='scar.static-source-text', schema_version=1, path=str(path),
            namespace_root=str(source), raw_sha256=sha256(raw).hexdigest(),
            decoded_sha256=sha256(text.encode()).hexdigest(), encoding=encoding, text=text)
        prior = _write(model, 'units/' + key + '/old_core.json.gz', {'opaque_prior_endpoint': key})
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | dict(key=key, source_bytes=len(raw), bodies=[dict(entry_key='prior:' + key, artifact=prior)],
                artifacts={'source': _write(model, 'units/' + key + '/source.json.gz', envelope)}))
    (model / 'manifest.json').write_bytes(_json(dict(schema='scar.static-program', schema_version=1,
        units=units, remaining=[], source_issues=[])))
    def forbidden(*args, **kwargs):
        raise AssertionError('C1 must not request compiler symbol tables')
    monkeypatch.setattr(symtable, 'symtable', forbidden)
    monkeypatch.setattr(_symtable, 'symtable', forbidden)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    model_source_syntax(model, tmp_path / 'f2', jobs=1)
    roles = tmp_path / 'roles'
    roles_report = model_source_roles(model, roles, jobs=1, collect_only=True)
    before, before_roles = _snapshot(model), _snapshot(roles)
    assert all('source_roles' not in unit['artifacts'] for unit in json.loads(before['manifest.json'])['units'])
    with pytest.raises(ValueError, match='external.*collect-only'):
        model_source_contexts(model, tmp_path / 'bad-canonical', roles_materials=roles, jobs=1)
    with pytest.raises(ValueError, match='canonical F3-B|roles-materials'):
        model_source_contexts(model, tmp_path / 'missing-roles', jobs=1, collect_only=True)
    budget = model_source_contexts(model, tmp_path / 'budget', roles_materials=roles,
        jobs=1, collect_only=True, max_scopes=0)
    assert not budget['complete_for_declared_units'] and not budget['canonical_model_published']
    assert _snapshot(model) == before
    def no_clone(*args, **kwargs):
        raise AssertionError('collect-only must not clone the model')
    store = tmp_path / 'contexts'
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil, 'copytree', no_clone)
            captured = model_source_contexts(model, store, roles_materials=roles, jobs=1, collect_only=True)
    finally:
        model.chmod(0o755)
    assert captured['status_counts'] == {'CONTEXTUALIZED': 2, 'UPSTREAM_NOT_CLASSIFIED': 1}
    assert captured['complete_for_declared_units'] and not captured['all_declared_units_routed']
    assert not captured['symtable_executed'] and not captured['canonical_model_published']
    assert captured['manifest_unchanged'] and len(list(store.rglob('catalog.json.gz'))) == 1
    assert _snapshot(model) == before and _snapshot(roles) == before_roles
    for row, role_row, basis in zip(captured['results'], roles_report['results'], captured['basis']):
        assert basis['artifacts']['source_roles'] == role_row['artifact']
        document = _Fragments(store).read(row['artifact'])
        assert 'nodes' not in document and 'catalog' not in document
        assert document['profile']['context_catalog_sha256'] == captured['catalog_sha256']
        if row['status'] == 'CONTEXTUALIZED':
            assert row['boundaries'] < row['slots']
    fresh = model_source_contexts(model, tmp_path / 'fresh', roles_materials=roles,
        materials=store, jobs=1, verify=True)
    assert fresh['material_source_basis_unchanged'] and fresh['complete_for_declared_units']
    assert _snapshot(model) == before and _snapshot(roles) == before_roles
    for limits in ({'max_scopes': 0}, {'max_nodes': 0}, {'max_ports': 0}):
        with pytest.raises(ValueError, match='budget'):
            model_source_contexts(model, tmp_path / ('limit-' + next(iter(limits))), roles_materials=roles,
                materials=store, jobs=1, verify=True, **limits)
    result = store / 'result.json'
    original = result.read_bytes()
    for key, replacement in (('scopes', captured['scopes'] + 1),
            ('status_counts', {'CONTEXTUALIZED': 3}), ('complete_for_declared_units', False), ('jobs', True)):
        altered = deepcopy(json.loads(original))
        altered[key] = replacement
        result.write_bytes(_json(altered))
        try:
            with pytest.raises(ValueError):
                model_source_contexts(model, tmp_path / ('changed-' + key), roles_materials=roles,
                    materials=store, jobs=1, verify=True)
        finally:
            result.write_bytes(original)
    role_result = roles / 'result.json'
    original_roles = role_result.read_bytes()
    altered = json.loads(original_roles)
    altered['ports'] += 1
    role_result.write_bytes(_json(altered))
    try:
        with pytest.raises(ValueError):
            model_source_contexts(model, tmp_path / 'changed-role-summary', roles_materials=roles,
                materials=store, jobs=1, verify=True)
    finally:
        role_result.write_bytes(original_roles)
    catalog_path = roles / roles_report['catalog']['path']
    original_catalog = catalog_path.read_bytes()
    catalog_path.write_bytes(original_catalog + b'changed')
    try:
        with pytest.raises(ValueError, match='receipt'):
            model_source_contexts(model, tmp_path / 'changed-role-catalog', roles_materials=roles,
                materials=store, jobs=1, verify=True)
    finally:
        catalog_path.write_bytes(original_catalog)
    note = store / 'unowned.txt'
    note.write_text('retain me')
    try:
        with pytest.raises(ValueError, match='unowned'):
            model_source_contexts(model, tmp_path / 'unowned', roles_materials=roles,
                materials=store, jobs=1, verify=True)
        assert note.read_text() == 'retain me'
    finally:
        note.unlink()
    model_source_roles(model, tmp_path / 'roles-publish', jobs=1)
    prior_publish = _snapshot(model)
    published = model_source_contexts(model, tmp_path / 'publish', jobs=1)
    assert published['canonical_model_published'] and published['complete_for_declared_units']
    assert all((model / name).read_bytes() == value for name, value in prior_publish.items() if name != 'manifest.json')
    current = json.loads((model / 'manifest.json').read_bytes())
    assert current['source_contexts']['artifacts'] == [published['catalog']]
    for old, new in zip(json.loads(prior_publish['manifest.json'])['units'], current['units']):
        assert {**new, 'artifacts': {k: v for k, v in new['artifacts'].items() if k != 'source_contexts'}} == old
    verified = model_source_contexts(model, tmp_path / 'canonical-check', jobs=2, verify=True)
    assert verified['complete_for_declared_units'] and verified['manifest_unchanged']
    assert main(['--model', str(model), '--out', str(tmp_path / 'cli-check'), '--verify', '--jobs', '1']) == 0

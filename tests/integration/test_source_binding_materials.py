"""One C2b store transaction; namespace templates never identify runtime objects."""
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
from scar.analysis.source_declaration_materials import model_source_declarations
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_c2b_namespace_materials_preserve_detached_inputs_and_canonical_endpoints(tmp_path, monkeypatch):
    from scar.analysis.source_binding_materials import main, model_source_bindings
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir();model.mkdir()
    units = []
    for number, raw in enumerate((
        b'outer = 0\ndef enclosing(values):\n    captured = values\n    class Owner:\n'
        b'        captured = 5\n        field: captured\n'
        b'        def method(self): return captured, __class__, global_missing\n'
        b'    return [lambda: item for item in values], Owner\n'
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
        raise AssertionError('C2b must not request native symbol tables or execute the fixture')
    monkeypatch.setattr(symtable, 'symtable', forbidden);monkeypatch.setattr(_symtable, 'symtable', forbidden)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    model_source_syntax(model, tmp_path / 'f2', jobs=1)
    b, c, d = tmp_path / 'roles', tmp_path / 'contexts', tmp_path / 'declarations'
    b_report = model_source_roles(model, b, jobs=1, collect_only=True)
    c_report = model_source_contexts(model, c, roles_materials=b, jobs=1, collect_only=True)
    d_report = model_source_declarations(model, d, roles_materials=b, contexts_materials=c, jobs=1, collect_only=True)
    before = _snapshot(model)
    upstream = [(b, b_report, 'ports'), (c, c_report, 'scopes'), (d, d_report, 'names')]
    snapshots = [_snapshot(root) for root, _, _ in upstream]
    external = dict(roles_materials=b, contexts_materials=c, declarations_materials=d, jobs=1)
    with pytest.raises(ValueError, match='external.*collect-only'):
        model_source_bindings(model, tmp_path / 'bad-canonical', **external)
    with pytest.raises(ValueError, match='canonical'):
        model_source_bindings(model, tmp_path / 'missing-inputs', jobs=1, collect_only=True)
    for key in ('max_bindings', 'max_plan_steps'):
        report = model_source_bindings(model, tmp_path / ('budget-' + key), collect_only=True, **external, **{key: 0})
        assert not report['complete_for_declared_units'] and not report['canonical_model_published']
        assert _snapshot(model) == before
    store = tmp_path / 'bindings'
    def no_clone(*args, **kwargs):raise AssertionError('collect-only must not clone a read-only model')
    model.chmod(0o555)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(shutil, 'copytree', no_clone)
            captured = model_source_bindings(model, store, collect_only=True, **external)
    finally:
        model.chmod(0o755)
    assert captured['status_counts'] == {'RESOLVED': 1, 'RESOLVED_WITH_CONFLICTS': 1, 'UPSTREAM_NOT_DECLARED': 1}
    assert captured['complete_for_declared_units'] and captured['captures'] > 0 and captured['conflicts'] > 0
    assert captured['runtime_binding'] == 'NOT_OBSERVED' and captured['compiler_projection'] == 'NOT_COMPUTED_IN_C2B'
    assert not captured['symtable_executed'] and not captured['canonical_model_published']
    assert captured['manifest_unchanged'] and len(list(store.rglob('catalog.json.gz'))) == 1
    assert _snapshot(model) == before
    assert all(_snapshot(root) == saved for (root, _, _), saved in zip(upstream, snapshots))
    for i, row in enumerate(captured['results']):
        for name, report in (('source_roles', b_report), ('source_contexts', c_report), ('source_declarations', d_report)):
            assert captured['basis'][i]['artifacts'][name] == report['results'][i]['artifact']
        document = _Fragments(store).read(row['artifact'])
        assert 'nodes' not in document and 'catalog' not in document
        assert document['profile']['binding_catalog_sha256'] == captured['catalog_sha256']
        assert row['steps'] == sum(len(plan['steps']) for plan in document['plans'])
    verified = model_source_bindings(model, tmp_path / 'fresh', verify=True, materials=store, **external)
    assert verified['complete_for_declared_units'] and verified['material_source_basis_unchanged']
    assert _snapshot(model) == before
    for key in ('max_bindings', 'max_nodes', 'max_names'):
        with pytest.raises(ValueError, match='budget'):
            model_source_bindings(model, tmp_path / ('limit-' + key), verify=True, materials=store, **external, **{key: 0})
    for owner, counter in [(store, 'bindings'), *((root, counter) for root, _, counter in upstream)]:
        result = owner / 'result.json';original = result.read_bytes()
        changed = deepcopy(json.loads(original));changed[counter] += 1
        result.write_bytes(_json(changed))
        try:
            with pytest.raises(ValueError):
                model_source_bindings(model, tmp_path / ('tamper-' + owner.name), verify=True, materials=store, **external)
        finally:
            result.write_bytes(original)
    for owner, report in [(store, captured), *((root, report) for root, report, _ in upstream)]:
        catalog = owner / report['catalog']['path'];original = catalog.read_bytes()
        catalog.write_bytes(original + b'changed')
        try:
            with pytest.raises(ValueError, match='receipt'):
                model_source_bindings(model, tmp_path / ('catalog-' + owner.name), verify=True, materials=store, **external)
        finally:
            catalog.write_bytes(original)
    note = d / 'unowned.txt';note.write_text('keep me')
    try:
        with pytest.raises(ValueError, match='unowned'):
            model_source_bindings(model, tmp_path / 'unowned', verify=True, materials=store, **external)
        assert note.read_text() == 'keep me'
    finally:
        note.unlink()
    model_source_roles(model, tmp_path / 'b-publish', jobs=1)
    model_source_contexts(model, tmp_path / 'c-publish', jobs=1)
    model_source_declarations(model, tmp_path / 'd-publish', jobs=1)
    prior_publish = _snapshot(model)
    published = model_source_bindings(model, tmp_path / 'publish', jobs=1)
    assert published['canonical_model_published'] and published['complete_for_declared_units']
    assert all((model / key).read_bytes() == raw for key, raw in prior_publish.items() if key != 'manifest.json')
    after = json.loads((model / 'manifest.json').read_bytes())
    assert after['source_bindings']['artifacts'] == [published['catalog']]
    for old, new in zip(json.loads(prior_publish['manifest.json'])['units'], after['units']):
        assert {**new, 'artifacts': {key: value for key, value in new['artifacts'].items() if key != 'source_bindings'}} == old
    checked = model_source_bindings(model, tmp_path / 'canonical-check', jobs=2, verify=True)
    assert checked['complete_for_declared_units'] and checked['manifest_unchanged']
    assert main(['--model', str(model), '--out', str(tmp_path / 'cli'), '--verify', '--jobs', '1']) == 0

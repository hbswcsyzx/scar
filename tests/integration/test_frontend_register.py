"""Register an attested small frontend chain without replay or store paths."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.source_symbol_materials import model_source_symbols
from scar.analysis.source_role_materials import model_source_roles
from scar.analysis.source_context_materials import model_source_contexts
from scar.analysis.source_declaration_materials import model_source_declarations
from scar.analysis.source_binding_materials import model_source_bindings
from scar.analysis.compiler_topology_materials import model_compiler_topology
from scar.analysis.compiler_symbol_materials import model_compiler_symbols
from scar.analysis.frontend_check import check_frontend
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


_ARGUMENTS = dict(source_symbols='symbols_materials', source_roles='roles_materials',
    source_contexts='contexts_materials', source_declarations='declarations_materials',
    source_bindings='bindings_materials', compiler_topology='topology_materials',
    compiler_symbols='compiler_symbols_materials')


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob('*') if p.is_file()}


@contextmanager
def _changed(path, data):
    original = path.read_bytes()
    path.write_bytes(data)
    try:
        yield
    finally:
        path.write_bytes(original)


def _fixture(tmp_path):
    source, model = tmp_path/'program', tmp_path/'model'
    source.mkdir(); model.mkdir()
    path, key = source/'program.py', 'unit'
    raw = (b'from __future__ import annotations\n'
        b'class Owner:\n    value: Later\n'
        b'    def project(self, item): return super().project(item)\n'
        b'def outer(seed):\n'
        b'    def inner(item): return seed + item\n'
        b'    return [inner(x) for x in range(2)]\n'
        b'raise RuntimeError("the target must never execute")\n')
    path.write_bytes(raw)
    encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    text = raw.decode(encoding)
    envelope = dict(schema='scar.static-source-text', schema_version=1,
        path=str(path), namespace_root=str(source), raw_sha256=sha256(raw).hexdigest(),
        decoded_sha256=sha256(text.encode()).hexdigest(), encoding=encoding, text=text)
    old_core = _write(model, 'units/unit/core.json.gz', dict(original_endpoint='core:sentinel'))
    unit = {k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
    unit.update(key=key, source_bytes=len(raw),
        bodies=[dict(entry_key='entry:sentinel', artifact=old_core)],
        artifacts={'source': _write(model, 'units/unit/source.json.gz', envelope)})
    (model/'manifest.json').write_bytes(_json(dict(schema='scar.static-program', schema_version=1,
        units=[unit], remaining=[], source_issues=[])))
    archive_model_source_bytes(model, tmp_path/'f0', jobs=1)
    model_source_tokens(model, tmp_path/'f1', jobs=1)
    model_source_syntax(model, tmp_path/'f2', jobs=1)
    stores = {name: tmp_path/'stores'/name for name in _ARGUMENTS}
    jobs = [(model_source_symbols, 'source_symbols', {}),
        (model_source_roles, 'source_roles', {}),
        (model_source_contexts, 'source_contexts', dict(roles_materials=stores['source_roles'])),
        (model_source_declarations, 'source_declarations', dict(
            roles_materials=stores['source_roles'], contexts_materials=stores['source_contexts'])),
        (model_source_bindings, 'source_bindings', dict(roles_materials=stores['source_roles'],
            contexts_materials=stores['source_contexts'], declarations_materials=stores['source_declarations'])),
        (model_compiler_topology, 'compiler_topology', dict(roles_materials=stores['source_roles'],
            contexts_materials=stores['source_contexts'], symbols_materials=stores['source_symbols'])),
        (model_compiler_symbols, 'compiler_symbols', dict(roles_materials=stores['source_roles'],
            contexts_materials=stores['source_contexts'], declarations_materials=stores['source_declarations'],
            symbols_materials=stores['source_symbols'], topology_materials=stores['compiler_topology']))]
    for capture, name, inputs in jobs:
        report = capture(model, stores[name], collect_only=True, jobs=1, **inputs)
        assert report['complete_for_declared_units']
    verifications = {}
    for capture, name, inputs in jobs:
        output = tmp_path/'verified'/name
        report = capture(model, output, materials=stores[name], verify=True, jobs=1, **inputs)
        assert report['complete_for_declared_units']
        verifications[name] = output/'result.json'
    acceptance = tmp_path/'accepted'/'result.json'
    report = check_frontend(model, acceptance.parent, jobs=1,
        **{_ARGUMENTS[name]: store for name, store in stores.items()})
    assert report['status_counts'] == {'VERIFIED': 1}
    assert report['complete_for_declared_units'] and not report['target_executed']
    return model, stores, verifications, acceptance


def test_register_attested_chain_preserves_bytes_and_queries_without_external_stores(tmp_path, monkeypatch):
    from scar.analysis import frontend_register as registration
    from scar.analysis import (source_symbols, source_roles, source_contexts, source_declarations,
        source_bindings, compiler_topology, compiler_symbols)
    model, stores, verifications, acceptance = _fixture(tmp_path)
    accepted_sha = sha256(acceptance.read_bytes()).hexdigest()
    original_model = _snapshot(model)
    original_stores = {name: _snapshot(store) for name, store in stores.items()}
    kwargs = dict(acceptance=acceptance, acceptance_sha256=accepted_sha,
                  verifications=verifications, jobs=1)

    def reject(label, **overrides):
        with pytest.raises((ValueError, FileExistsError)):
            registration.register_frontend(model, tmp_path/label, **(kwargs | overrides))
        assert _snapshot(model) == original_model

    reject('wrong-pin', acceptance_sha256='0'*64)
    # The trusted acceptance SHA remains fixed: re-signing a changed store
    # cannot upgrade that historical authorization into a different input.
    result = stores['source_roles']/'result.json'
    summary = json.loads(result.read_bytes())
    changed = deepcopy(summary)
    changed['complete_for_declared_units'] = True
    changed['results'][0]['status'] = 'BUDGET_STOPPED'
    with _changed(result, _json(changed)):
        reject('false-complete')
    leaf = verifications['source_roles']
    changed_leaf = json.loads(leaf.read_bytes())
    changed_leaf['results'][0]['ports'] += 1
    with _changed(leaf, _json(changed_leaf)):
        reject('wrong-leaf-facts')
    original_manifest = (model/'manifest.json').read_bytes()
    source_descriptor = json.loads(original_manifest)['units'][0]['artifacts']['source']
    source_blob = model/source_descriptor['path']
    original_source = source_blob.read_bytes()
    damaged = bytes([original_source[0] ^ 1]) + original_source[1:]
    with _changed(source_blob, damaged):
        damaged_model = _snapshot(model)
        with pytest.raises(ValueError):
            registration.register_frontend(model, tmp_path/'bad-source-payload', **kwargs)
        assert _snapshot(model) == damaged_model
    parent = stores['compiler_symbols']/'result.json'
    parent_summary = json.loads(parent.read_bytes())
    descriptor = parent_summary['results'][0]['artifact']
    body_path = stores['compiler_symbols']/descriptor['path']
    body = _Fragments(stores['compiler_symbols']).read(descriptor)
    for label, section, field in (
            ('changed-parent', 'input', 'topology_document_sha256'),
            ('changed-implementation', 'profile', 'implementation_sha256')):
        changed_body = deepcopy(body)
        changed_body[section][field] = '0'*64
        original_blob = body_path.read_bytes()
        changed_receipt = _write(stores['compiler_symbols'], descriptor['path'], changed_body)
        changed_summary = deepcopy(parent_summary)
        changed_summary['results'][0]['artifact'] = changed_receipt
        try:
            with _changed(parent, _json(changed_summary)):
                reject(label)
        finally:
            body_path.write_bytes(original_blob)
    catalog = summary['catalog']
    catalog_path = stores['source_roles']/catalog['path']
    catalog_body = _Fragments(stores['source_roles']).read(catalog)
    changed_catalog = deepcopy(catalog_body)
    changed_catalog['rule_version'] = 'UNACCEPTED_CATALOG_VERSION'
    original_catalog = catalog_path.read_bytes()
    changed_catalog_receipt = _write(stores['source_roles'], catalog['path'], changed_catalog)
    changed_summary = deepcopy(summary)
    changed_summary['catalog'] = changed_catalog_receipt
    try:
        with _changed(result, _json(changed_summary)):
            reject('changed-catalog')
    finally:
        catalog_path.write_bytes(original_catalog)

    # A concurrent input file must survive rejection; no old model is published.
    note = stores['compiler_symbols']/'concurrent-note.txt'
    copier = registration._copy_artifact
    def changed_store(*args, **kw):
        copied = copier(*args, **kw)
        note.write_text('keep this concurrent input')
        return copied
    with monkeypatch.context() as patch:
        patch.setattr(registration, '_copy_artifact', changed_store)
        reject('concurrent-store')
    assert note.read_text() == 'keep this concurrent input'
    note.unlink()
    assert {name: _snapshot(store) for name, store in stores.items()} == original_stores

    # This catalog path belongs to an existing unrelated core artifact.
    occupied = _write(model, 'source_roles/catalog.json.gz', dict(original_endpoint='occupied:catalog'))
    current = json.loads(original_manifest)
    current['artifacts'] = {'owned-core-catalog': occupied}
    (model/'manifest.json').write_bytes(_json(current))
    conflict_model = _snapshot(model)
    with pytest.raises((ValueError, FileExistsError)):
        registration.register_frontend(model, tmp_path/'owned-target', **kwargs)
    assert _snapshot(model) == conflict_model
    (model/occupied['path']).unlink()
    (model/'manifest.json').write_bytes(original_manifest)

    def no_replay(*args, **kw):
        raise AssertionError('registration must consume the accepted receipts without semantic replay')
    with monkeypatch.context() as patch:
        for module, function in ((source_symbols, 'read_source_symbols'),
                (source_roles, 'read_source_roles'), (source_contexts, 'read_source_contexts'),
                (source_declarations, 'read_source_declarations'), (source_bindings, 'read_source_bindings'),
                (compiler_topology, 'read_compiler_topology'), (compiler_symbols, 'read_compiler_symbols')):
            patch.setattr(module, function, no_replay)
        registered = registration.register_frontend(model, tmp_path/'registered', **kwargs)
    assert registered['all_seven_registered'] and registered['registered_stages'] == 7
    assert not registered['semantic_replay_executed']
    after = json.loads((model/'manifest.json').read_bytes())
    old = json.loads(original_manifest)
    restored_unit = deepcopy(after['units'][0])
    for name, store in stores.items():
        receipt = json.loads((store/'result.json').read_bytes())
        imported = after['units'][0]['artifacts'][name]
        assert imported == receipt['results'][0]['artifact']
        assert (model/imported['path']).read_bytes() == (store/imported['path']).read_bytes()
        restored_unit['artifacts'].pop(name)
        if 'catalog' in receipt:
            assert (model/receipt['catalog']['path']).read_bytes() == (store/receipt['catalog']['path']).read_bytes()
    assert restored_unit == old['units'][0]
    for relative, data in original_model.items():
        if relative != 'manifest.json':
            assert (model/relative).read_bytes() == data
    assert {name: _snapshot(store) for name, store in stores.items()} == original_stores
    registered_model = _snapshot(model)
    def no_copy(*args, **kw):
        raise AssertionError('identical canonical artifacts must be reused without copying')
    with monkeypatch.context() as patch:
        patch.setattr(registration, '_copy_artifact', no_copy)
        reused = registration.register_frontend(model, tmp_path/'reused', **kwargs)
    assert reused['all_seven_registered'] and reused['manifest_unchanged']
    assert all(stage['transport'] == 'ALREADY_REGISTERED' for stage in reused['stages'])
    assert _snapshot(model) == registered_model

    hidden = []
    try:
        for store in stores.values():
            target = store.with_name(store.name+'-hidden')
            store.rename(target)
            hidden.append((store, target))
        canonical = check_frontend(model, tmp_path/'canonical-check', jobs=1)
        assert canonical['status_counts'] == {'VERIFIED': 1}
        assert canonical['complete_for_declared_units'] and not canonical['target_executed']
        assert all(receipt['root'] == str(model) and receipt['receipt_kind'] == 'CANONICAL_MANIFEST'
            for receipt in canonical['input_stores'].values())
    finally:
        for store, target in reversed(hidden):
            target.rename(store)

"""A saved source domain may contain both old graphs and source-only inputs."""
from hashlib import sha256
import json

import pytest

from scar.analysis.source_anchor_materials import collect_source_anchors, _write
from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.ir.frontend_v2 import build_semantic_source_texts


def test_collect_and_fresh_verify_preserve_source_only_domains(tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    units = []
    for key, text, suffix in (('runtime', 'answer = 42\n', '.py'),
                               ('interface', 'answer: int\n', '.pyi')):
        path = '/source/' + key + suffix
        digest = sha256(text.encode()).hexdigest()
        source = dict(schema='scar.static-source-text', schema_version=1,
            path=path, namespace_root='/source', raw_sha256=digest,
            decoded_sha256=digest, encoding='utf-8', text=text)
        f0 = source_bytes_document(text.encode(), path=path, namespace_root='/source')
        f1 = source_tokens_document(f0)
        f2 = source_syntax_document(f0, f1)
        documents = dict(source=source, source_bytes=f0, source_tokens=f1, source_syntax=f2)
        if key == 'runtime':
            documents['semantic'] = build_semantic_source_texts([path], '/source',
                sources={path: text}, root_is_package=False).graph.to_dict()
        artifacts = {name: _write(model, 'units/' + key + '/' + name + '.json.gz', doc)
                     for name, doc in documents.items()}
        units.append(dict(key=key, path=path, namespace_root='/source',
            raw_sha256=digest, decoded_sha256=digest, encoding='utf-8',
            source_bytes=len(text.encode()), artifacts=artifacts))
    original = json.dumps(dict(schema='scar.static-program', schema_version=1, units=units)).encode()
    (model / 'manifest.json').write_bytes(original)
    materials = tmp_path / 'materials'
    captured = collect_source_anchors(model, materials)
    fresh = collect_source_anchors(model, tmp_path / 'fresh', materials=materials)
    assert captured['status'] == fresh['status'] == 'VERIFIED_DECLARED_SOURCE_DOMAIN'
    assert captured['counts'] == fresh['counts'] == dict(
        units=2, verified=1, source_only=1, failed=0, occurrences=11, atoms=3)
    interface = next(row for row in fresh['units'] if row['unit'] == 'interface')
    assert interface['status'] == 'NO_SAVED_LEGACY_DOMAIN'
    assert 'artifact' not in interface and interface['source_input']['semantic_artifact'] is None
    assert (model / 'manifest.json').read_bytes() == original
    assert all(fresh[name] is False for name in ('target_executed', 'canonical_model_modified',
        'source_productions_verified', 'first_stage_complete'))
    forged = json.loads((materials / 'result.json').read_text())
    next(row for row in forged['units'] if row['unit'] == 'interface')['source_input']['f2_sha256'] = '0' * 64
    (materials / 'result.json').write_text(json.dumps(forged))
    with pytest.raises(ValueError, match='source-only disposition'):
        collect_source_anchors(model, tmp_path / 'forged', materials=materials)

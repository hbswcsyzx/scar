"""F1 appends only lexical materials, after F0, without running later layers."""
from hashlib import sha256
import ast
import json
import symtable
import pytest
from io import BytesIO
import tokenize

from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments
from scar.analysis.source_tokens import read_source_tokens


def test_f1_publication_is_metadata_only_and_freshly_verifiable(tmp_path, monkeypatch):
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir()
    model.mkdir()
    units = []
    for number, raw in enumerate((b'raise RuntimeError("never execute")\r',
            'text=f"{{α}} {x!r}"\r\n'.encode(), b'def unfinished(\n')):
        path, key = source / f'{number}.py', str(number)
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        envelope = {'schema': 'scar.static-source-text', 'schema_version': 1,
            'path': str(path), 'namespace_root': str(source), 'raw_sha256': sha256(raw).hexdigest(),
            'decoded_sha256': sha256(text.encode()).hexdigest(), 'encoding': encoding, 'text': text}
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | {'key': key, 'source_bytes': len(raw), 'bodies': [],
               'artifacts': {'source': _write(model, 'units/' + key + '/source.json.gz', envelope)}})
    (model / 'manifest.json').write_bytes(_json({'schema': 'scar.static-program',
        'schema_version': 1, 'units': units, 'remaining': [], 'source_issues': []}))
    def forbidden(*args, **kwargs):
        raise AssertionError('F1 called a later frontend stage')
    monkeypatch.setattr(ast, 'parse', forbidden)
    monkeypatch.setattr(symtable, 'symtable', forbidden)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    before = (model / 'manifest.json').read_bytes()
    malformed = json.loads(before)
    malformed['units'][0]['key'] = '../escape'
    (model / 'manifest.json').write_bytes(_json(malformed))
    with pytest.raises(ValueError, match='safe source-unit'):
        model_source_tokens(model, tmp_path / 'invalid-key', jobs=1)
    (model / 'manifest.json').write_bytes(before)
    budget = model_source_tokens(model, tmp_path / 'prefix', jobs=1, max_tokens=1)
    assert not budget['complete_for_declared_units']
    assert (model / 'manifest.json').read_bytes() == before
    report = model_source_tokens(model, tmp_path / 'f1', jobs=1)
    assert report['complete_for_declared_units']
    assert report['status_counts'] == {'TOKENIZED': 2, 'TOKENIZER_ERROR': 1}
    after = json.loads((model / 'manifest.json').read_bytes())
    for old, new in zip(json.loads(before)['units'], after['units']):
        restored = {**new, 'artifacts': {k: v for k, v in new['artifacts'].items() if k != 'source_tokens'}}
        assert restored == old
        reader = _Fragments(model)
        read_source_tokens(reader.read(new['artifacts']['source_tokens']),
            reader.read(new['artifacts']['source_bytes']))
    before_verify = (model / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='replay budget'):
        model_source_tokens(model, tmp_path / 'verify-budget', jobs=1, verify=True, max_tokens=0)
    assert (model / 'manifest.json').read_bytes() == before_verify
    verified = model_source_tokens(model, tmp_path / 'check', jobs=2, verify=True)
    assert verified['complete_for_declared_units'] and verified['units'] == 3
    assert verified['manifest_unchanged'] and verified['consumed_artifacts_unchanged']
    assert (model / 'manifest.json').read_bytes() == before_verify
    assert verified['parser_executed'] is verified['target_executed'] is verified['later_stages_verified'] is False

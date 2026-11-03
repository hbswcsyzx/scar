"""F2 adds syntax materials without changing old graph identities or bodies."""
from hashlib import sha256
import ast
import builtins
from io import BytesIO
import json
import symtable
import tokenize

import pytest

from scar.analysis.source_materials import archive_model_source_bytes
from scar.analysis.source_lexing import model_source_tokens
from scar.analysis.source_parsing import model_source_syntax
from scar.analysis.static_program import _json, _write


def test_f2_publication_keeps_old_model_and_never_enters_binding(tmp_path, monkeypatch):
    source, model = tmp_path / 'source', tmp_path / 'model'
    source.mkdir()
    model.mkdir()
    units = []
    for number, raw in enumerate((b'# type: ignore[tag]\nx={**data}\r\ndef f(*,required):return "\\ud800"\r\n'
            b'raise RuntimeError("never execute")\n', b'value = if\n', b'')):
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
        raise AssertionError('F2 called the binding layer')
    monkeypatch.setattr(symtable, 'symtable', forbidden)
    original_compile = builtins.compile
    def ast_only(text, filename, mode, flags=0, *args, **kwargs):
        if str(filename).startswith(str(source)):
            assert flags & ast.PyCF_ONLY_AST
        return original_compile(text, filename, mode, flags, *args, **kwargs)
    monkeypatch.setattr(builtins, 'compile', ast_only)
    archive_model_source_bytes(model, tmp_path / 'f0', jobs=1)
    model_source_tokens(model, tmp_path / 'f1', jobs=1)
    before = (model / 'manifest.json').read_bytes()
    budget = model_source_syntax(model, tmp_path / 'prefix', max_nodes=1, jobs=1)
    assert not budget['complete_for_declared_units']
    assert (model / 'manifest.json').read_bytes() == before

    import scar.analysis.static_program as storage
    writer, note = storage._write, model / 'unowned-note.txt'
    def concurrent_file(*args, **kwargs):
        result = writer(*args, **kwargs)
        note.write_text('retain this file')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_write', concurrent_file)
        with pytest.raises(ValueError, match='unowned'):
            model_source_syntax(model, tmp_path / 'concurrent', jobs=1)
    assert note.read_text() == 'retain this file' and (model / 'manifest.json').read_bytes() == before
    note.unlink()

    report = model_source_syntax(model, tmp_path / 'f2', jobs=1)
    assert report['complete_for_declared_units'] and report['status_counts'] == {'PARSED': 2, 'PARSER_ERROR': 1}
    after = json.loads((model / 'manifest.json').read_bytes())
    for old, new in zip(json.loads(before)['units'], after['units']):
        assert {**new, 'artifacts': {k: d for k, d in new['artifacts'].items() if k != 'source_syntax'}} == old
    before_verify = (model / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='budget'):
        model_source_syntax(model, tmp_path / 'verify-budget', jobs=1, verify=True, max_nodes=0)
    verified = model_source_syntax(model, tmp_path / 'check', jobs=2, verify=True)
    assert verified['complete_for_declared_units'] and verified['units'] == 3
    assert verified['manifest_unchanged'] and verified['consumed_artifacts_unchanged']
    assert (model / 'manifest.json').read_bytes() == before_verify
    assert verified['symtable_executed'] is verified['target_executed'] is verified['later_stages_verified'] is False

"""F0 preserves bytes before any lexical, syntax or semantic processing."""
from hashlib import sha256
from pathlib import Path
import ast
import json
import symtable
import pytest

from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_materials import archive_model_source_bytes, verify_model_source_bytes, main
from scar.analysis.static_calls import input_basis_unit
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def test_f0_material_gate_keeps_all_bytes_and_never_requires_parser(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    model = tmp_path / 'model'
    model.mkdir()
    content = {'program.py': b'raise RuntimeError("the program must never execute")\r\n',
        'syntax_error.py': b'def unfinished(\n',
        'cp932.py': b'# coding: cp932\r\nvalue = "\x87\x90"\r\n'}
    units = []
    import tokenize
    from io import BytesIO
    for index, (name, raw) in enumerate(content.items()):
        path = source / name
        path.write_bytes(raw)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        text = raw.decode(encoding)
        key = str(index)
        envelope = {'schema': 'scar.static-source-text', 'schema_version': 1,
            'path': str(path), 'namespace_root': str(source), 'raw_sha256': sha256(raw).hexdigest(),
            'decoded_sha256': sha256(text.encode()).hexdigest(), 'encoding': encoding, 'text': text}
        descriptor = _write(model, 'units/' + key + '/source.json.gz', envelope)
        units.append({k: v for k, v in envelope.items() if k not in ('schema', 'schema_version', 'text')}
            | {'key': key, 'source_bytes': len(raw), 'module_names': [], 'module_mappings': [],
                'artifacts': {'source': descriptor}, 'bodies': []})
    manifest = {'schema': 'scar.static-program', 'schema_version': 1, 'units': units,
        'remaining': [], 'source_issues': [], 'project_root': str(source)}
    (model / 'manifest.json').write_bytes(_json(manifest))
    original = (model / 'manifest.json').read_bytes()
    original_basis = [input_basis_unit(unit) for unit in units]
    def forbidden(*args, **kwargs):
        raise AssertionError('a later frontend layer was invoked during F0')
    monkeypatch.setattr(ast, 'parse', forbidden)
    monkeypatch.setattr(symtable, 'symtable', forbidden)

    # A non-invertible encoding cannot be reconstructed from retained text.
    (source / 'cp932.py').unlink()
    missing = archive_model_source_bytes(model, tmp_path / 'missing', jobs=2)
    assert missing['covered_units'] == 2 and not missing['complete_for_declared_units']
    assert (model / 'manifest.json').read_bytes() == original
    (source / 'cp932.py').write_bytes(content['cp932.py'])
    budget = archive_model_source_bytes(model, tmp_path / 'budget', max_bytes=1)
    assert not budget['complete_for_declared_units'] and len(budget['frontier']) == 3
    assert (model / 'manifest.json').read_bytes() == original

    # A new unowned file must abort publication and remain untouched.
    import scar.analysis.static_program as storage
    writer = storage._write
    note = model / 'unowned-note.txt'
    def concurrent_file(*args, **kwargs):
        result = writer(*args, **kwargs)
        note.write_text('preserve this file')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_write', concurrent_file)
        with pytest.raises(ValueError, match='unowned'):
            archive_model_source_bytes(model, tmp_path / 'concurrent', jobs=2)
    assert note.read_text() == 'preserve this file'
    assert (model / 'manifest.json').read_bytes() == original
    note.unlink()

    result = archive_model_source_bytes(model, tmp_path / 'published', jobs=2)
    assert result['complete_for_declared_units'] and result['covered_units'] == 3
    after = json.loads((model / 'manifest.json').read_bytes())
    assert [input_basis_unit(unit) for unit in after['units']] == original_basis
    for unit in after['units']:
        document = _Fragments(model).read(unit['artifacts']['source_bytes'])
        assert read_source_bytes(document) == content[Path(unit['path']).name]
    before_verify = (model / 'manifest.json').read_bytes()
    verified = verify_model_source_bytes(model, tmp_path / 'verified')
    assert verified['verified_units'] == 3 and verified['complete_for_declared_units']
    assert (model / 'manifest.json').read_bytes() == before_verify
    assert verified['parser_executed'] is verified['lexer_executed'] is verified['later_stages_verified'] is False

    # Invalid encoding also yields a complete raw material, not a lost file.
    bad = source / 'bad_encoding.py'
    bad_raw = b'# coding: not_a_codec\nvalue=1\n'
    bad.write_bytes(bad_raw)
    out = tmp_path / 'standalone'
    assert main(['--file', str(bad), '--out', str(out)]) == 0
    doc = _Fragments(out).read(json.loads((out / 'result.json').read_bytes())['artifact'])
    assert doc['decoding']['status'] == 'ENCODING_ERROR' and read_source_bytes(doc) == bad_raw
    absent_out = tmp_path / 'absent'
    assert main(['--file', str(source / 'absent.py'), '--out', str(absent_out)]) == 1
    assert json.loads((absent_out / 'result.json').read_bytes())['material_complete'] is False

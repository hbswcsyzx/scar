"""F0 retains bytes through encoding failures without parsing the source."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest


def test_source_bytes_lossless_material_and_strict_replay():
    from scar.analysis.source_bytes import source_bytes_document, read_source_bytes, decoded_source_bytes

    def document(raw):
        return source_bytes_document(raw, path='/source/material.py', namespace_root='/source')

    unicode_text = 'α = "λ"\r\n# 注释\r\n'
    latin_text = '# coding: latin-1\r\nx = "é"\r\n'
    cp932 = b'# coding: cp932\ns="\x87\x90"\n'
    positives = ((b'', ''), (b'\xef\xbb\xbfx = 1\r\n', 'x = 1\r\n'),
        (unicode_text.encode(), unicode_text), (latin_text.encode('latin-1'), latin_text),
        (cp932, cp932.decode('cp932')), (b'x = if :\n', 'x = if :\n'))
    for raw, expected in positives:
        item = document(raw)
        assert item['schema'] == 'scar.source-bytes' and item['schema_version'] == 1
        assert item['decoding']['status'] == 'DECODED'
        assert item['decoding']['decoded_utf8_sha256'] == sha256(expected.encode()).hexdigest()
        assert item['decoding']['characters'] == len(expected)
        assert item['raw']['size_bytes'] == len(raw) and item['raw']['sha256'] == sha256(raw).hexdigest()
        assert read_source_bytes(json.loads(json.dumps(item))) == raw
        assert decoded_source_bytes(item) == expected
        assert 'text' not in item and 'text' not in item['decoding']
    # A successful decode/re-encode is not a raw-byte receipt.
    assert cp932.decode('cp932').encode('cp932') != cp932
    failures = ((b'\xef\xbb\xbf# coding: latin-1\n', 'ENCODING_ERROR', 'ENCODING', 'SyntaxError'),
        (b'# coding: missing_scar_codec\n', 'ENCODING_ERROR', 'ENCODING', 'SyntaxError'),
        (b'# coding: utf-8\n# prefix\nx="\xff"\n', 'DECODE_ERROR', 'DECODING', 'UnicodeDecodeError'),
        (b'# coding: base64_codec\nx=1\n', 'ENCODING_ERROR', 'ENCODING', 'LookupError'),
        (b'\0not Python syntax', 'ENCODING_ERROR', 'ENCODING', 'SyntaxError'),
        (b'# coding: unicode_escape\ns="\\ud800"\n', 'DECODED_TEXT_ENCODING_ERROR', 'DECODED_TEXT_ENCODING', 'UnicodeEncodeError'))
    for raw, status, stage, exception in failures:
        item = document(raw)
        assert read_source_bytes(json.loads(json.dumps(item))) == raw
        assert item['decoding']['status'] == status
        error = item['decoding']['error']
        assert error['stage'] == stage and error['exception_type'] == exception
        assert 'object' not in error and 'text' not in error
        if status == 'DECODED_TEXT_ENCODING_ERROR':
            assert decoded_source_bytes(item) == raw.decode('unicode_escape')
            assert error['index_basis'] == 'DECODED_TEXT'
            assert item['decoding']['decoded_utf8_sha256'] is None
        else:
            assert decoded_source_bytes(item) is None
        if exception == 'UnicodeDecodeError':
            assert error['index_basis'] == 'RAW_INPUT' and error['start'] == raw.index(b'\xff')
    original = document(b'a')
    mutations = ((('schema_version',), True), (('raw', 'base64'), '@@@'),
        (('raw', 'base64'), 'YR=='), (('raw', 'sha256'), '0' * 64), (('raw', 'size_bytes'), True),
        (('decoding', 'characters'), 20), (('decoding', 'encoding'), 'latin-1'),
        (('profile', 'cache_tag'), 'unrecorded'), (('profile', 'version'), [True, 14, 7, 'final', 0]))
    for path, replacement in mutations:
        changed = deepcopy(original)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        with pytest.raises((ValueError, TypeError)):
            read_source_bytes(changed)
    changed = deepcopy(original)
    changed['tokens'] = []
    with pytest.raises(ValueError):
        read_source_bytes(changed)
    with pytest.raises(TypeError):
        source_bytes_document(bytearray(b'a'), path='/source/material.py', namespace_root='/source')

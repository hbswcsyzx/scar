"""Finite F1 schema families, compared with the pinned stdlib tokenizer only.

This corpus exercises serialization and lexical boundaries. It does not prove
syntax validity, all possible error messages, or whole-program coverage.
"""
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import base64
import json
import re
import sys
import token
import tokenize
import warnings

import pytest

from scar.analysis.source_bytes import decoded_source_bytes, source_bytes_document


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='this lexical corpus records the CPython 3.14.7 public tokenizer profile')


def _material(raw):
    return source_bytes_document(raw, path='/source/material.py', namespace_root='/source')


def _oracle(material):
    text = decoded_source_bytes(material)
    assert material['decoding']['status'] == 'DECODED'
    view = text.replace('\r\n', '\n').replace('\r', '\n')
    rows, error = [], None
    stream = tokenize.generate_tokens(StringIO(view).readline)
    try:
        for row in stream:
            rows.append(row)
    except (tokenize.TokenError, IndentationError, TabError) as caught:
        error = caught
    return tuple(rows), error


def _native_parameter(row):
    if row['kind'] == 'TUPLE':
        assert row['value'] is None
        return tuple(_native_parameter(item) for item in row['items'])
    assert row['items'] == []
    if row['kind'] == 'BYTES_BASE64':
        return base64.b64decode(row['value'], validate=True)
    expected_type = {'NONE': type(None), 'STR': str, 'INT': int, 'FLOAT': float, 'BOOL': bool}[row['kind']]
    assert type(row['value']) is expected_type
    return row['value']


def _check_source_geometry(document, material, official):
    """Check stored references independently of the production fresh reader.

    Prefix normalization and character sets are deliberately simple oracles
    for this tiny corpus, not algorithms for processing large source files.
    """
    original = decoded_source_bytes(material)
    normalize = lambda text: text.replace('\r\n', '\n').replace('\r', '\n')
    view = normalize(original)
    assert document['view']['characters'] == len(view)
    assert document['view']['utf8_bytes'] == len(view.encode('utf-8'))
    assert document['view']['sha256'] == sha256(view.encode('utf-8')).hexdigest()
    assert document['view']['newline_rewrites'] == [
        {'original_chars': {'start': match.start(), 'end': match.end()},
         'view_chars': {'start': len(normalize(original[:match.start()])),
                        'end': len(normalize(original[:match.start()])) + 1}}
        for match in re.finditer(r'\r\n?', original)]

    # At a CRLF boundary choose the end of the complete original newline.
    original_boundary = {len(normalize(original[:i])): i for i in range(len(original) + 1)}
    starts = [0] + [match.end() for match in re.finditer('\n', view)]

    def position(pair):
        row, column = pair
        if not 1 <= row <= len(starts):
            return None
        start = starts[row - 1]
        end = starts[row] if row < len(starts) else len(view)
        return start + column if 0 <= column <= end - start else None

    def resolve(reference):
        if reference['kind'] == 'VIEW_RANGE':
            a, b = reference['start'], reference['end']
            assert type(a) is type(b) is int and 0 <= a <= b <= len(view)
            assert reference['literal_index'] is None
            return view[a:b]
        assert reference['kind'] == 'INTERNED_LITERAL'
        assert reference['start'] is reference['end'] is None
        return document['text_pool'][reference['literal_index']]

    token_coverage = set()
    assert len(document['tokens']) == len(official)
    for stored, expected in zip(document['tokens'], official):
        assert resolve(stored['string']) == expected.string
        assert resolve(stored['line']) == expected.line
        assert tuple(stored['start']) == expected.start
        assert tuple(stored['end']) == expected.end
        assert stored['type'] == expected.type and stored['exact_type'] == expected.exact_type
        a, b = position(expected.start), position(expected.end)
        extent = stored['source_extent']
        if a is None or b is None or a > b:
            # Virtual/synthetic native coordinates need no invented source span.
            assert extent is None
            continue
        assert extent is not None
        assert extent['view_chars'] == {'start': a, 'end': b}
        oa, ob = original_boundary[a], original_boundary[b]
        assert extent['original_chars'] == {'start': oa, 'end': ob}
        assert normalize(original[oa:ob]) == view[a:b]
        assert extent['view_utf8_bytes'] == {
            'start': len(view[:a].encode('utf-8')), 'end': len(view[:b].encode('utf-8'))}
        token_coverage.update(range(a, b))

    coverage = document['source_coverage']
    covered = {i for span in coverage['covered'] for i in range(span['start'], span['end'])}
    assert covered == token_coverage
    cursor = 0
    for span in sorted(coverage['covered'] + coverage['gaps'], key=lambda item: item['start']):
        assert span['start'] == cursor and cursor < span['end'] <= len(view)
        cursor = span['end']
    assert cursor == len(view)


def _corpus(family):
    if family == 'operators':
        yield 'all-exact-operators', (' '.join(token.EXACT_TOKEN_TYPES) + '\n').encode()
        yield 'numbers-and-names', (
            'α = 0 123_456 0xF_F 0o7 0b10 1. .1 1e+2 1j\n'
            'match case type async await € $ ? `\n').encode()
    elif family == 'strings':
        for prefix in sorted(tokenize._all_string_prefixes()):
            for quote in ("'", '"', "'''", '"""'):
                body = 'one\ntwo' if len(quote) == 3 else 'piece'
                yield prefix + quote, (prefix + quote + body + quote + '\n').encode()
        for prefix in ('f', 't'):
            yield prefix + '-braces', (prefix + '"{{α}} {value!r:>{width}}"\n').encode()
            yield prefix + '-multiline', (prefix + '"""α\n{value}\n{{b}}"""\n').encode()
        yield 'multiline-token-line', b'x="""a\nb"""; z=2\n'
    elif family == 'layout':
        layouts = ('', '# only a comment', '# comment\n\n', 'x=1',
            'if x:\n\tpass\npass\n', 'if x:\n\f    x=1\n',
            'x=(1 # first\n  # second\n +2)\n', 'x=1\\\n +2\n')
        for index, source in enumerate(layouts):
            for newline in ('\n', '\r\n', '\r'):
                yield f'layout-{index}-{newline!r}', source.replace('\n', newline).encode()
        yield 'utf8-bom', b'\xef\xbb\xbf' + 'α = "λ"\r\n'.encode()
        yield 'latin1', '# coding: latin-1\r\nx="é"\r\n'.encode('latin-1')
        yield 'cp932', b'# coding: cp932\ns="\x87\x90"\r\n'
        yield 'never-execute', b'raise RuntimeError("F1 must not execute this")\n'
    elif family == 'errors':
        for name, source in (
            ('single-quote', 'x="abc\n'), ('triple-quote', 'x="""abc\n'),
            ('f-brace', 'f"{value"\n'), ('t-brace', 't"{value"\n'),
            ('open-bracket', 'x=(\n'), ('continuation', 'x=1\\'),
            ('late-null', '# first\n# second\n\0\n'),
            ('dedent', 'if x:\n  y=1\n z=2\n'),
            ('tab', 'if x:\n\tpass\n        pass\n')):
            yield name, source.encode()


@pytest.mark.parametrize('family', ('operators', 'strings', 'layout', 'errors', 'guards', 'warnings'))
def test_f1_schema_families_match_official_tokenizer(family):
    from scar.analysis.source_tokens import source_tokens_document, read_source_tokens

    if family == 'warnings':
        with warnings.catch_warnings(record=True) as leaked:
            warnings.simplefilter('error')
            external_filters = list(warnings.filters)
            for prefix in ('f', 't'):
                material = _material((prefix + '"\\{value}"\n').encode())
                with warnings.catch_warnings(record=True) as official:
                    warnings.simplefilter('always')
                    expected, failure = _oracle(material)
                assert failure is None and len(official) == 1
                document = source_tokens_document(material)
                assert read_source_tokens(document, material) == expected
                _check_source_geometry(document, material, expected)
                assert document['warnings'] == [dict(
                    category_module=item.category.__module__, category_name=item.category.__qualname__,
                    message=str(item.message), filename=item.filename, lineno=item.lineno,
                    line=item.line, source_present=item.source is not None) for item in official]
                assert warnings.filters == external_filters
            # This warning comes from the unicode_escape codec during F0.
            # It must not be promoted into the ordinary STRING token stream.
            material = _material(b'# coding: unicode_escape\ns="\\q"\n')
            document = source_tokens_document(material)
            assert document['status'] == 'TOKENIZED' and document['warnings'] == []
            expected = _oracle(material)[0]
            assert read_source_tokens(document, material) == expected
            _check_source_geometry(document, material, expected)
            assert warnings.filters == external_filters and leaked == []
        return

    if family == 'guards':
        material = _material(b'x=1\n')
        expected, failure = _oracle(material)
        assert failure is None
        for limit in (0, 2, len(expected), len(expected) + 1):
            document = source_tokens_document(material, max_tokens=limit)
            actual = read_source_tokens(json.loads(json.dumps(document)), material)
            assert actual == expected[:limit]
            _check_source_geometry(document, material, expected[:limit])
            assert document['actual_eof'] is any(row.type == token.ENDMARKER for row in actual)
            assert document['status'] == ('TOKENIZED' if limit >= len(expected) else 'BUDGET_STOPPED')
        document = source_tokens_document(material)
        for route, replacement in (
            (('max_tokens',), True), (('tokens', 0, 'type'), True),
            (('tokens', 0, 'exact_type'), token.ENDMARKER),
            (('tokens', 0, 'unexpected'), None), (('unexpected',), [])):
            changed = deepcopy(document)
            target = changed
            for part in route[:-1]:
                target = target[part]
            target[route[-1]] = replacement
            with pytest.raises((TypeError, ValueError)):
                read_source_tokens(changed, material)
        changed = deepcopy(document)
        del changed['schema_version']
        with pytest.raises((TypeError, ValueError)):
            read_source_tokens(changed, material)
        with pytest.raises((TypeError, ValueError)):
            read_source_tokens(document, _material(b'x=2\n'))
        for raw in (b'# coding: missing_scar_codec\n',
                    b'# first\n# second\nx="\xff"\n',
                    b'# coding: unicode_escape\ns="\\ud800"\n'):
            upstream = _material(raw)
            assert upstream['decoding']['status'] != 'DECODED'
            result = source_tokens_document(upstream)
            assert read_source_tokens(result, upstream) == ()
            assert result['status'] == 'UPSTREAM_DECODING_ERROR' and result['actual_eof'] is False
            assert result['view'] is result['source_coverage'] is None
        return

    exact_kinds, error_kinds = set(), set()
    for label, raw in _corpus(family):
        material = _material(raw)
        unchanged = deepcopy(material)
        expected, failure = _oracle(material)
        document = source_tokens_document(material)
        actual = read_source_tokens(json.loads(json.dumps(document)), material)
        _check_source_geometry(document, material, expected)
        assert material == unchanged
        assert tuple(tuple(row) for row in actual) == tuple(tuple(row) for row in expected), label
        assert tuple(row.exact_type for row in actual) == tuple(row.exact_type for row in expected), label
        assert document['actual_eof'] is any(row.type == token.ENDMARKER for row in expected)
        exact_kinds.update(row.exact_type for row in actual)
        if failure is None:
            assert document['status'] == 'TOKENIZED' and document['error'] is None, label
        else:
            assert document['status'] == 'TOKENIZER_ERROR', label
            assert document['error']['exception_type'] == type(failure).__name__, label
            assert document['error']['message'] == str(failure), label
            assert _native_parameter(document['error']['parameters']) == failure.args, label
            error_kinds.add(type(failure).__name__)
    if family == 'operators':
        assert set(token.EXACT_TOKEN_TYPES.values()) <= exact_kinds
        assert document['profile']['token_types'] == [
            {'code': code, 'name': token.tok_name[code]} for code in range(token.N_TOKENS)]
        assert document['profile']['exact_operators'] == [
            {'text': text, 'code': code} for text, code in sorted(token.EXACT_TOKEN_TYPES.items())]
    elif family == 'strings':
        assert {token.STRING, token.FSTRING_START, token.FSTRING_MIDDLE, token.FSTRING_END,
                token.TSTRING_START, token.TSTRING_MIDDLE, token.TSTRING_END} <= exact_kinds
    elif family == 'errors':
        assert error_kinds == {'TokenError', 'IndentationError', 'TabError'}

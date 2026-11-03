"""Pure F1 lexing, with a reversible newline view and strict fresh replay.

Warning isolation temporarily changes process warning filters on CPython builds
without context-aware warnings. Run this API in separate worker processes, not
concurrent threads. No AST, parsing, compilation or target execution occurs.
"""
from __future__ import annotations

import base64
import _tokenize
from bisect import bisect_left, bisect_right
from functools import lru_cache
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sys
import sysconfig
import token
import tokenize
import warnings

from scar.analysis.source_bytes import decoded_source_bytes
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_tokens import (
    ExactOperator, NativeTokenAttribute, NativeTokenParameter, NewlineRewrite,
    SourceToken, SourceTokenError, SourceTokensInput, SourceTokensMaterial,
    SourceTokensProfile, SourceTokenWarning, TokenCoverage, TokenExtent,
    TokenSpan, TokenTextRef, TokenType, TokenView,
)
from scar.ir.record_codec import decode, encode


@lru_cache(maxsize=1)
def _implementation():
    origin = _tokenize.__spec__.origin
    if origin == 'built-in':
        if sysconfig.get_config_var('Py_ENABLE_SHARED'):
            raise ValueError('a built-in tokenizer in a shared runtime needs its loaded-library receipt')
        binary = str(Path(sys.executable).resolve())
    elif type(origin) is str and Path(origin).is_file():
        binary = str(Path(origin).resolve())
    else:
        raise ValueError('native tokenizer implementation binary is unavailable')
    return (sha256(Path(tokenize.__file__).read_bytes()).hexdigest(),
        sha256(Path(token.__file__).read_bytes()).hexdigest(), origin, binary,
        sha256(Path(binary).read_bytes()).hexdigest())


def _profile(f0):
    tokenizer_sha, token_sha, native_origin, native_binary, native_sha = _implementation()
    return SourceTokensProfile(decode(SourceBytesProfile, f0['profile']),
        'stdlib.tokenize.generate_tokens.extra_tokens', 'CRLF_AND_CR_TO_LF_NO_FINAL_NEWLINE_V1',
        'RECORD_ALL_ALWAYS_ISOLATED_V1', tokenizer_sha, token_sha, native_origin, native_binary, native_sha,
        tuple(TokenType(i, token.tok_name[i]) for i in range(token.N_TOKENS)),
        tuple(ExactOperator(text, code) for text, code in sorted(token.EXACT_TOKEN_TYPES.items())))


def _input(f0):
    digest = sha256(json.dumps(f0, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
    return SourceTokensInput(digest, f0['path'], f0['namespace_root'], f0['raw']['sha256'],
        f0['decoding']['decoded_utf8_sha256'], f0['decoding']['status'])


def _view(original):
    parts, rewrites, cursor, length = [], [], 0, 0
    for match in re.finditer(r'\r\n?', original):
        fragment = original[cursor:match.start()]
        parts.extend((fragment, '\n'))
        length += len(fragment)
        rewrites.append(NewlineRewrite(TokenSpan(match.start(), match.end()), TokenSpan(length, length + 1)))
        length += 1
        cursor = match.end()
    parts.append(original[cursor:])
    text = ''.join(parts)
    raw = text.encode('utf-8')
    return text, TokenView(sha256(raw).hexdigest(), len(text), len(raw), tuple(rewrites))


def _parameter(value):
    if type(value) is tuple:
        return NativeTokenParameter('TUPLE', None, tuple(_parameter(x) for x in value))
    if type(value) is bytes:
        return NativeTokenParameter('BYTES_BASE64', base64.b64encode(value).decode('ascii'), ())
    kinds = {type(None): 'NONE', str: 'STR', int: 'INT', float: 'FLOAT', bool: 'BOOL'}
    if type(value) not in kinds:
        raise TypeError('unsupported native tokenizer diagnostic parameter')
    return NativeTokenParameter(kinds[type(value)], value, ())


def _error(error):
    names = ('msg', 'filename', 'lineno', 'offset', 'end_lineno', 'end_offset', 'text',
        'encoding', 'reason', 'start', 'end', 'object')
    return SourceTokenError(type(error).__module__, type(error).__qualname__, str(error),
        _parameter(error.args), tuple(NativeTokenAttribute(name, _parameter(getattr(error, name)))
            for name in names if hasattr(error, name)))


class _References:
    def __init__(self, text, view):
        self.text, self.view = text, view
        self.lines = [0] + [i + 1 for i, char in enumerate(text) if char == '\n']
        self.pool, self.intern = [], {}
        self.line_refs = {}
        self.line_objects = {}
        self.crlf_ends = [item.view_chars.end for item in view.newline_rewrites
            if item.original_chars.end - item.original_chars.start == 2]
        self.non_ascii, self.utf8_extra = [], []
        extra = 0
        for i, char in enumerate(text):
            if ord(char) >= 128:
                extra += len(char.encode('utf-8')) - 1
                self.non_ascii.append(i)
                self.utf8_extra.append(extra)

    def offset(self, position):
        row, column = position
        if not 1 <= row <= len(self.lines):
            return None
        start = self.lines[row - 1]
        end = self.lines[row] if row < len(self.lines) else len(self.text)
        return start + column if 0 <= column <= end - start else None

    def ref(self, value, span=None):
        if span is not None and self.text[span.start:span.end] == value:
            return TokenTextRef('VIEW_RANGE', span.start, span.end, None)
        if value not in self.intern:
            self.intern[value] = len(self.pool)
            self.pool.append(value)
        return TokenTextRef('INTERNED_LITERAL', None, None, self.intern[value])

    def utf8(self, offset):
        index = bisect_left(self.non_ascii, offset)
        return offset + (self.utf8_extra[index - 1] if index else 0)

    def source_token(self, item):
        a, b = self.offset(item.start), self.offset(item.end)
        span = TokenSpan(a, b) if a is not None and b is not None and a <= b else None
        if span is not None:
            extent = TokenExtent(span, TokenSpan(a + bisect_right(self.crlf_ends, a),
                b + bisect_right(self.crlf_ends, b)), TokenSpan(self.utf8(a), self.utf8(b)))
            kind = 'ZERO_WIDTH' if a == b else 'SOURCE'
        else:
            extent = None
            if item.type in (token.NEWLINE, token.NL) and item.string == '' and a == len(self.text):
                kind = 'SYNTHETIC_NEWLINE'
            elif item.type == token.ENDMARKER:
                kind = 'VIRTUAL_ENDMARKER'
            else:
                kind = 'VIRTUAL_COORDINATES'
        line_key = id(item.line)
        if line_key not in self.line_objects:
            if item.line not in self.line_refs:
                line_span = None
                if 1 <= item.start[0] <= len(self.lines) and 1 <= item.end[0] <= len(self.lines):
                    start = self.lines[item.start[0] - 1]
                    end = self.lines[item.end[0]] if item.end[0] < len(self.lines) else len(self.text)
                    line_span = TokenSpan(start, end)
                self.line_refs[item.line] = (item.line, self.ref(item.line, line_span))
            canonical, reference = self.line_refs[item.line]
            # The first field strongly retains this exact native string, so
            # its id cannot be recycled during this local replay.
            self.line_objects[line_key] = (item.line, canonical, reference)
        return SourceToken(item.type, item.exact_type, self.ref(item.string, span),
            self.line_objects[line_key][2], tuple(item.start), tuple(item.end), extent, kind)


def _coverage(rows, size):
    intervals = sorted((row.source_extent.view_chars.start, row.source_extent.view_chars.end)
        for row in rows if row.source_extent is not None and row.source_extent.view_chars.start < row.source_extent.view_chars.end)
    covered = []
    for start, end in intervals:
        if covered and start <= covered[-1].end:
            covered[-1] = TokenSpan(covered[-1].start, max(end, covered[-1].end))
        else:
            covered.append(TokenSpan(start, end))
    gaps, cursor = [], 0
    for span in covered:
        if cursor < span.start:
            gaps.append(TokenSpan(cursor, span.start))
        cursor = span.end
    if cursor < size:
        gaps.append(TokenSpan(cursor, size))
    return TokenCoverage(tuple(covered), tuple(gaps))


def _produce(f0, max_tokens, *, retain_items=False):
    if type(max_tokens) is not int or max_tokens < 0:
        raise ValueError('max_tokens must be an exact nonnegative integer')
    original = decoded_source_bytes(f0)
    upstream, profile = _input(f0), _profile(f0)
    if f0['decoding']['status'] != 'DECODED':
        return SourceTokensMaterial(upstream, profile, max_tokens, 'UPSTREAM_DECODING_ERROR',
            False, None, (), (), None, None, ()), ()
    text, view = _view(original)
    refs, items, rows, failure = _References(text, view), [], [], None
    actual_eof = False
    status = 'BUDGET_STOPPED'
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        stream = tokenize.generate_tokens(StringIO(text).readline)
        while len(rows) < max_tokens:
            try:
                item = next(stream)
            except StopIteration:
                status = 'TOKENIZED'
                break
            except (tokenize.TokenError, SyntaxError, UnicodeError, LookupError) as error:
                failure, status = _error(error), 'TOKENIZER_ERROR'
                break
            if not 0 <= item.type < token.N_TOKENS or not 0 <= item.exact_type < token.N_TOKENS:
                raise ValueError('tokenizer emitted a nonterminal sentinel token')
            rows.append(refs.source_token(item))
            if retain_items:
                items.append(tokenize.TokenInfo(item.type, item.string, item.start, item.end,
                    refs.line_objects[id(item.line)][1]))
            if item.type == token.ENDMARKER:
                actual_eof = True
                try:
                    next(stream)
                except StopIteration:
                    status = 'TOKENIZED'
                else:
                    raise ValueError('tokenizer emitted an item after ENDMARKER')
                break
        stream.close()
    warning_rows = tuple(SourceTokenWarning(item.category.__module__, item.category.__qualname__,
        str(item.message), item.filename, item.lineno, item.line, item.source is not None) for item in captured)
    if status == 'TOKENIZED' and not actual_eof:
        raise ValueError('tokenizer exhausted without an actual ENDMARKER')
    return SourceTokensMaterial(upstream, profile, max_tokens, status, actual_eof, view,
        tuple(refs.pool), tuple(rows), _coverage(rows, len(text)), failure, warning_rows), tuple(items)


def source_tokens_document(f0_document, *, max_tokens=2_000_000) -> dict:
    """Lex a strict F0 document; no implicit downstream compiler stage runs."""
    return encode(_produce(f0_document, max_tokens)[0])


def read_source_tokens(document, f0_document) -> tuple[tokenize.TokenInfo, ...]:
    """Rebuild and compare every typed lexical field against its original F0."""
    material = decode(SourceTokensMaterial, document)
    fresh, items = _produce(f0_document, material.max_tokens, retain_items=True)
    if material != fresh:
        raise ValueError('F1 document differs from its original F0/profile/fresh tokenizer stream')
    return items


__all__ = ['source_tokens_document', 'read_source_tokens']

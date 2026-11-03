"""Pure F0 bytes/encoding API, independent of tokens, parsing and execution."""
from __future__ import annotations

import base64
import binascii
from dataclasses import fields
from hashlib import sha256
from io import BytesIO
import sys
import tokenize

from scar.ir.program.source_bytes import (
    SourceBytesDecoding, SourceBytesError, SourceBytesMaterial, SourceBytesProfile, SourceRawBytes,
)
from scar.ir.record_codec import decode, encode


def _profile():
    return SourceBytesProfile(sys.implementation.name, tuple(sys.implementation.version),
        tuple(sys.version_info), sys.version, sys.hexversion, sys.implementation.cache_tag)


def _error(stage, error, original):
    obj = getattr(error, 'object', None)
    basis = None
    if type(obj) in (bytes, str):
        basis = ('RAW_INPUT' if type(original) is bytes else 'DECODED_TEXT') if obj == original else 'EXCEPTION_OBJECT'
    return SourceBytesError(stage, type(error).__name__, str(error), getattr(error, 'reason', None),
        getattr(error, 'encoding', None), getattr(error, 'start', None), getattr(error, 'end', None), basis,
        getattr(error, 'lineno', None), getattr(error, 'offset', None),
        getattr(error, 'end_lineno', None), getattr(error, 'end_offset', None))


def _interpret(raw):
    try:
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    except (SyntaxError, UnicodeError, LookupError) as error:
        return SourceBytesDecoding('ENCODING_ERROR', None, None, None, _error('ENCODING', error, raw)), None
    try:
        text = raw.decode(encoding)
    except (UnicodeError, LookupError) as error:
        return SourceBytesDecoding('DECODE_ERROR', encoding, None, None, _error('DECODING', error, raw)), None
    try:
        digest = sha256(text.encode('utf-8', errors='strict')).hexdigest()
    except UnicodeEncodeError as error:
        return SourceBytesDecoding('DECODED_TEXT_ENCODING_ERROR', encoding, None, len(text),
            _error('DECODED_TEXT_ENCODING', error, text)), text
    return SourceBytesDecoding('DECODED', encoding, digest, len(text), None), text


def source_bytes_document(raw: bytes, *, path: str, namespace_root: str) -> dict:
    """Retain exactly one raw payload, including encoding/decoding failures.

    Paths are labels checked lexically, never opened or resolved. Decoding
    preserves original newline characters. No source is parsed or executed.
    """
    if type(raw) is not bytes:
        raise TypeError('F0 source material requires exact immutable bytes')
    decoding, _ = _interpret(raw)
    return encode(SourceBytesMaterial(path, namespace_root, _profile(),
        SourceRawBytes(base64.b64encode(raw).decode('ascii'), sha256(raw).hexdigest(), len(raw)), decoding))


def _record(document, kind):
    if type(document) is not dict or set(document) != {field.name for field in fields(kind)}:
        raise ValueError('closed exact F0 ' + kind.__name__ + ' fields required')


def _read(document):
    _record(document, SourceBytesMaterial)
    for name, kind in (('profile', SourceBytesProfile), ('raw', SourceRawBytes), ('decoding', SourceBytesDecoding)):
        _record(document[name], kind)
    if document['decoding']['error'] is not None:
        _record(document['decoding']['error'], SourceBytesError)
    material = decode(SourceBytesMaterial, document)
    if material.profile != _profile():
        raise ValueError('F0 encoding interpretation requires its exact current runtime profile')
    try:
        raw = base64.b64decode(material.raw.base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('invalid F0 base64 payload') from error
    if (base64.b64encode(raw).decode('ascii') != material.raw.base64
            or len(raw) != material.raw.size_bytes or sha256(raw).hexdigest() != material.raw.sha256):
        raise ValueError('F0 canonical base64/raw size/SHA differ')
    decoding, text = _interpret(raw)
    if decoding != material.decoding:
        raise ValueError('F0 decoding metadata differs from its original bytes/profile')
    return raw, text


def read_source_bytes(document) -> bytes:
    """Strictly replay F0 only, rejecting changed payload or interpretation."""
    return _read(document)[0]


def decoded_source_bytes(document) -> str | None:
    """Return actual decoded text, even if its strict UTF-8 digest failed.

    Encoding/detection failure returns None. A decoded-text encoding error is
    recorded separately and never upgraded to a successful decoding summary.
    """
    return _read(document)[1]


__all__ = ['source_bytes_document', 'read_source_bytes', 'decoded_source_bytes']

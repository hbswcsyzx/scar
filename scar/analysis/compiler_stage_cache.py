"""Bounded reuse of pure analyzer documents within an explicit compilation.

This is immutable-input reuse by the analyzer, unrelated to Tensor caches or
runtime values. A session assumes fixed analyzer implementations and schemas;
hot schema changes require invalidation or a new session. Public stage APIs
remain uncached outside an explicitly owned session. Readers still perform
their ordinary decoding and comparisons on every call.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import fields
from hashlib import sha256
import json
import math

from scar.ir.record_codec import encode
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_compiled_values import EffectiveCompileContext


_ACTIVE = ContextVar('scar_compiler_stage_cache', default=None)
_RECORDS = (EffectiveCompileContext, SourceBytesProfile)


def _nominal(cls):
    return cls.__module__ + '.' + cls.__qualname__


def _key_value(value):
    """Canonical exact input types, without Python repr or object addresses.

    The wire codec intentionally merges list/tuple and dataclass/dict shapes.
    Cache keys retain those distinctions so a malformed lookalike cannot hit
    an earlier valid request. Unsupported or cyclic inputs bypass reuse and
    receive the original producer's diagnostics instead.
    """
    kind = type(value)
    if value is None:
        return ['none']
    if kind is bool:
        return ['bool', value]
    if kind is int:
        # Hex preserves exact integers without CPython's decimal digit limit.
        return ['int', format(value, 'x')]
    if kind is float:
        if not math.isfinite(value):
            raise ValueError('non-finite compiler cache input')
        return ['float', value.hex()]
    if kind is str:
        return ['str', value]
    if kind is bytes:
        return ['bytes', value.hex()]
    if kind is tuple or kind is list:
        return ['tuple' if kind is tuple else 'list', [_key_value(item) for item in value]]
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise TypeError('compiler cache mappings need exact string keys')
        # Python mappings retain insertion order; a pure producer can observe
        # it even when JSON object equality ignores that distinction.
        return ['dict', [[key, _key_value(value[key])] for key in value]]
    if any(kind is cls for cls in _RECORDS):
        # Only reviewed exact analyzer classes are admitted. Reject custom
        # records/subclasses before getattr/codec can invoke their methods;
        # same-named foreign classes never share these identities.
        members = [[item.name, _key_value(getattr(value, item.name))] for item in fields(kind)]
        # Keep canonical codec preflight after rejecting unsupported nested
        # objects; exact literal payloads in source documents stay wire data.
        encode(value)
        return ['record', _nominal(kind), members]
    raise TypeError('unsupported compiler cache input type')


def _request_digest(args, kwargs):
    tree = _key_value((args, kwargs))
    raw = json.dumps(tree, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True, allow_nan=False).encode('ascii')
    return sha256(raw).hexdigest()


class _CompilerStageSession:
    def __init__(self, max_entries):
        self.max_entries = max_entries
        self._documents = OrderedDict()
        self._generation = 0
        self._closed = False

    def clear(self):
        """Invalidate retained documents, including any in-flight generation."""
        self._documents.clear()
        self._generation += 1

    invalidate = clear


@contextmanager
def compiler_stage_session(*, max_entries=16):
    """Own a fresh bounded cache; nested sessions restore their outer owner.

    No documents survive exit, including in copied contexts that retain this
    session object. Schema/implementation mutation within a session is not a
    supported incremental-schema protocol; call clear/invalidate explicitly.
    """
    if type(max_entries) is not int or max_entries < 1:
        raise ValueError('compiler stage max_entries must be an exact positive integer')
    session = _CompilerStageSession(max_entries)
    token = _ACTIVE.set(session)
    try:
        yield session
    finally:
        session.clear()
        session._closed = True
        _ACTIVE.reset(token)


def clear_compiler_stage_cache():
    """Invalidate the current session; outside a session this is a no-op."""
    session = _ACTIVE.get()
    if session is not None:
        session.clear()


invalidate_compiler_stage_cache = clear_compiler_stage_cache


def reuse_document(stage, producer, *args, **kwargs):
    """Reuse only successful pure documents, copying into and out of storage.

    Every effective producer argument belongs in args/kwargs, including its
    budgets. The caller must not supply workers or cache native observations
    or validation conclusions. Producer identity partitions stage namespaces;
    it does not claim to detect hot edits to its implementation or schema.
    """
    session = _ACTIVE.get()
    if session is None or session._closed:
        return producer(*args, **kwargs)
    try:
        key = stage, producer, _request_digest(args, kwargs)
    except (TypeError, ValueError, RecursionError, AttributeError):
        return producer(*args, **kwargs)
    if key in session._documents:
        session._documents.move_to_end(key)
        return deepcopy(session._documents[key])
    generation = session._generation
    result = producer(*args, **kwargs)
    if not session._closed and session._generation == generation:
        session._documents[key] = deepcopy(result)
        session._documents.move_to_end(key)
        while len(session._documents) > session.max_entries:
            session._documents.popitem(last=False)
    return deepcopy(result)

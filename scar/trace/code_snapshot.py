"""Bounded structural code identities and exact bytecode positions.

Only exact builtin constant types are inspected.  No application repr, hash,
equality, descriptor, or target execution is used.  The v2 encoding is a
length-delimited binary tree, independent of marshal reference flags and of
adaptive bytecode.  These identities describe code, not callable environments.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import dis
import hashlib
import inspect
from itertools import islice
import struct
import threading
from types import CodeType
import weakref


_MAX_BYTES = 16 * 1024 * 1024
_MAX_NODES = 100_000
_MAX_DEPTH = 128
_MAX_CODE_UNITS = 100_000
_MAX_CACHE_ENTRIES = 128
_MAX_CACHE_TEXT_BYTES = 512 * 1024
_MAX_KEY_CACHE_ENTRIES = 2048
_MAX_PARAMETER_CACHE_BYTES = 512 * 1024
_MAX_CACHED_SITES = 128

_CODE_FIELDS = (
    "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
    "co_stacksize", "co_flags", "co_code", "co_consts", "co_names",
    "co_varnames", "co_freevars", "co_cellvars", "co_filename", "co_name",
    "co_qualname", "co_firstlineno", "co_linetable", "co_exceptiontable",
)
_DOMAIN = b"scar-code-structural-v2\0"


class _Encoder:
    def __init__(self):
        self.bytes = self.nodes = 0

    def write(self, output, data):
        if len(data) > _MAX_BYTES - self.bytes:
            raise ValueError("code snapshot encoded-byte budget exceeded")
        self.bytes += len(data)
        output.extend(data)

    def length(self, output, value):
        self.write(output, struct.pack(">Q", value))

    def encode(self, value, output, depth=0):
        if depth > _MAX_DEPTH:
            raise ValueError("code snapshot nesting budget exceeded")
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            raise ValueError("code snapshot node budget exceeded")
        kind = type(value)
        if value is None:
            self.write(output, b"N")
        elif value is Ellipsis:
            self.write(output, b"E")
        elif kind is bool:
            self.write(output, b"B\x01" if value else b"B\x00")
        elif kind is int:
            size = (value.bit_length() + 7) // 8
            self.write(output, b"I-" if value < 0 else b"I+")
            self.length(output, size)
            if size > _MAX_BYTES - self.bytes:
                raise ValueError("code snapshot encoded-byte budget exceeded")
            self.write(output, abs(value).to_bytes(size, "big"))
        elif kind is float:
            self.write(output, b"F" + struct.pack(">d", value))
        elif kind is complex:
            self.write(output, b"C" + struct.pack(">dd", value.real, value.imag))
        elif kind is str:
            # UTF-8 needs at least one byte per character.  Check before encoding
            # so even a rejected adversarial string has bounded temporary size.
            if len(value) > _MAX_BYTES - self.bytes:
                raise ValueError("code snapshot encoded-byte budget exceeded")
            data = value.encode("utf-8", "surrogatepass")
            self.write(output, b"S")
            self.length(output, len(data))
            self.write(output, data)
        elif kind is bytes:
            self.write(output, b"Y")
            self.length(output, len(value))
            self.write(output, value)
        elif kind is tuple:
            self.write(output, b"T")
            self.length(output, len(value))
            for item in value:
                self.encode(item, output, depth + 1)
        elif kind is slice:
            self.write(output, b"L")
            for item in (value.start, value.stop, value.step):
                self.encode(item, output, depth + 1)
        elif kind is frozenset:
            self.write(output, b"R")
            self.length(output, len(value))
            members = []
            for item in value:
                encoded = bytearray()
                self.encode(item, encoded, depth + 1)
                members.append(bytes(encoded))
            # Sorting only encoded bytes never compares or hashes constants.
            for encoded in sorted(members):
                output.extend(encoded)  # Already charged by recursive encoding.
        elif kind is CodeType:
            self.write(output, b"K")
            self.length(output, len(_CODE_FIELDS))
            for name in _CODE_FIELDS:
                self.encode(name, output, depth + 1)
                self.encode(getattr(value, name), output, depth + 1)
        else:
            raise ValueError("unsupported exact code constant type")


@dataclass(slots=True)
class _CachedCode:
    reference: weakref.ReferenceType
    key: str
    filename: str
    qualname: str
    first_line: int
    flags: int
    parameters: tuple[str, ...]
    text_bytes: int
    limits: tuple[int, int, int]


@dataclass(slots=True)
class _CachedKey:
    reference: weakref.ReferenceType
    key: str
    limits: tuple[int, int, int]
    sites: OrderedDict = field(default_factory=OrderedDict)
    calls: OrderedDict = field(default_factory=OrderedDict)
    parameters: tuple[str, ...] | None = None
    parameter_bytes: int = 0


_CACHE: OrderedDict[int, _CachedCode] = OrderedDict()
_KEY_CACHE: OrderedDict[int, _CachedKey] = OrderedDict()
_CACHE_TEXT_BYTES = 0
_PARAMETER_CACHE_BYTES = 0
_CACHE_LOCK = threading.RLock()


def _forget(identity, reference):
    global _CACHE_TEXT_BYTES
    with _CACHE_LOCK:
        record = _CACHE.get(identity)
        if record is not None and record.reference is reference:
            _CACHE_TEXT_BYTES -= record.text_bytes
            del _CACHE[identity]


def _forget_key(identity, reference):
    global _PARAMETER_CACHE_BYTES
    with _CACHE_LOCK:
        record = _KEY_CACHE.get(identity)
        if record is not None and record.reference is reference:
            _PARAMETER_CACHE_BYTES -= record.parameter_bytes
            del _KEY_CACHE[identity]


def _key_record(code):
    global _PARAMETER_CACHE_BYTES
    if type(code) is not CodeType:
        raise ValueError("code snapshot requires an exact CodeType")
    identity = id(code)
    limits = (_MAX_BYTES, _MAX_NODES, _MAX_DEPTH)
    with _CACHE_LOCK:
        cached = _KEY_CACHE.get(identity)
        if cached is not None and cached.reference() is code and cached.limits == limits:
            _KEY_CACHE.move_to_end(identity)
            return cached
    encoded = bytearray()
    encoder = _Encoder()
    try:
        encoder.write(encoded, _DOMAIN)
        encoder.encode(code, encoded)
    except RecursionError as error:
        raise ValueError("code snapshot nesting budget exceeded") from error
    key = "pycode-v2:" + hashlib.sha256(encoded).hexdigest()
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS)
    count += bool(code.co_flags & inspect.CO_VARKEYWORDS)
    if count > len(code.co_varnames):
        raise ValueError("code snapshot parameter layout is inconsistent")
    reference = weakref.ref(code, lambda ref: _forget_key(identity, ref))
    record = _CachedKey(reference, key, limits)
    with _CACHE_LOCK:
        previous = _KEY_CACHE.get(identity)
        if previous is not None and previous.reference() is code and previous.limits == limits:
            _KEY_CACHE.move_to_end(identity)
            return previous
        if previous is not None:
            _PARAMETER_CACHE_BYTES -= previous.parameter_bytes
            del _KEY_CACHE[identity]
        if _MAX_KEY_CACHE_ENTRIES > 0:
            _KEY_CACHE[identity] = record
            while len(_KEY_CACHE) > _MAX_KEY_CACHE_ENTRIES:
                _, evicted = _KEY_CACHE.popitem(last=False)
                _PARAMETER_CACHE_BYTES -= evicted.parameter_bytes
    return record


def code_key(code: CodeType) -> str:
    """Return the structural code key without allocating a descriptor mapping.

    Only fully encoded, supported CodeType trees enter the bounded cache. Cache
    identity is guarded by a weak reference so recycled object addresses cannot
    inherit a prior code object's key.
    """
    return _key_record(code).key


def code_parameters(code: CodeType) -> tuple[str, ...]:
    """Immutable formal names, cached only for the validated live CodeType."""
    global _PARAMETER_CACHE_BYTES
    record = _key_record(code)
    with _CACHE_LOCK:
        if record.parameters is not None:
            return record.parameters
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS) + bool(code.co_flags & inspect.CO_VARKEYWORDS)
    if count > len(code.co_varnames):
        raise ValueError('code snapshot parameter layout is inconsistent')
    parameters = code.co_varnames[:count]
    size = 64 + 8*len(parameters) + 4*sum(map(len,parameters))
    with _CACHE_LOCK:
        if (_KEY_CACHE.get(id(code)) is record and record.parameters is None
                and _PARAMETER_CACHE_BYTES + size <= _MAX_PARAMETER_CACHE_BYTES):
            record.parameters, record.parameter_bytes = parameters, size
            _PARAMETER_CACHE_BYTES += size
    return parameters


def call_instruction(code: CodeType, offset: int) -> tuple[str, int | None] | None:
    """Exact static instruction at a CALL site, without retaining argval/repr.

    Reuse the pinned dis decoder on a cold site so EXTENDED_ARG and inline
    CACHE boundaries retain their old interpretation. Only opcode name/oparg
    survive; no Instruction, code constant, frame or callable is cached.
    """
    if type(offset) is not int:
        raise ValueError('instruction offset must be an exact integer')
    record = _key_record(code)
    if len(code.co_code) // 2 > _MAX_CODE_UNITS:
        raise ValueError('code snapshot instruction budget exceeded')
    with _CACHE_LOCK:
        if offset in record.calls:
            record.calls.move_to_end(offset)
            return record.calls[offset]
    instruction = next((i for i in dis.get_instructions(code) if i.offset == offset), None)
    value = None if instruction is None else (instruction.opname, instruction.arg)
    with _CACHE_LOCK:
        if _MAX_CACHED_SITES > 0:
            record.calls[offset] = value
            while len(record.calls) > _MAX_CACHED_SITES:
                record.calls.popitem(last=False)
    return value


def _record(code):
    global _CACHE_TEXT_BYTES
    if type(code) is not CodeType:
        raise ValueError("code snapshot requires an exact CodeType")
    identity = id(code)
    limits = (_MAX_BYTES, _MAX_NODES, _MAX_DEPTH)
    with _CACHE_LOCK:
        cached = _CACHE.get(identity)
        if cached is not None and cached.reference() is code and cached.limits == limits:
            _CACHE.move_to_end(identity)
            return cached
    key = _key_record(code).key
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS)
    count += bool(code.co_flags & inspect.CO_VARKEYWORDS)
    if count > len(code.co_varnames):
        raise ValueError("code snapshot parameter layout is inconsistent")
    parameters = code.co_varnames[:count]
    text_bytes = 4 * sum(len(value) for value in (code.co_filename, code.co_qualname, *parameters)) + len(key)
    reference = weakref.ref(code, lambda ref: _forget(identity, ref))
    record = _CachedCode(reference, key, code.co_filename, code.co_qualname,
                         code.co_firstlineno, code.co_flags, parameters, text_bytes, limits)
    with _CACHE_LOCK:
        previous = _CACHE.pop(identity, None)
        if previous is not None:
            _CACHE_TEXT_BYTES -= previous.text_bytes
        if _MAX_CACHE_ENTRIES > 0 and text_bytes <= _MAX_CACHE_TEXT_BYTES:
            _CACHE[identity] = record
            _CACHE_TEXT_BYTES += text_bytes
            while len(_CACHE) > _MAX_CACHE_ENTRIES or _CACHE_TEXT_BYTES > _MAX_CACHE_TEXT_BYTES:
                _, evicted = _CACHE.popitem(last=False)
                _CACHE_TEXT_BYTES -= evicted.text_bytes
    return record


def describe_code(code: CodeType) -> dict:
    """Describe canonical loaded code without retaining the code or constants.

    Raises ValueError for unsupported constants or finite encoding limits.
    Parameters follow the code layout: positional, keyword-only, *args, **kwargs.
    Returned containers are fresh and may be modified by callers.
    """
    record = _record(code)
    return {"key": record.key, "filename": record.filename, "qualname": record.qualname,
            "first_line": record.first_line, "flags": record.flags,
            "parameters": list(record.parameters)}


def site(code: CodeType, offset: int) -> dict:
    """Describe one exact CPython wordcode offset, including non-CALL opcodes.

    Offsets outside the code or inside a two-byte code unit have no opcode or
    position.  CACHE units remain CACHE; they are never reassigned to a CALL.
    This reports bytecode provenance, not a proven source ast.Call mapping.
    """
    if type(offset) is not int:
        raise ValueError("instruction offset must be an exact integer")
    record = _key_record(code)
    raw = code.co_code  # Canonical, unquickened bytes, even after specialization.
    if len(raw) // 2 > _MAX_CODE_UNITS:
        raise ValueError("code snapshot instruction budget exceeded")
    if offset < 0 or offset >= len(raw) or offset % 2:
        return {"code": record.key, "offset": offset, "opname": None, "position": None}
    with _CACHE_LOCK:
        known = record.sites.get(offset)
        if known is not None:
            record.sites.move_to_end(offset)
    if known is None:
        # Do not ask dis to resolve arguments: it renders constants with repr.
        # co_positions has one record per two-byte code unit, including caches.
        position = next(islice(code.co_positions(), offset // 2, None), None)
        if position is not None and any(value is None for value in position):
            position = None
        known = (dis.opname[raw[offset]], position)
        with _CACHE_LOCK:
            if _MAX_CACHED_SITES > 0:
                record.sites[offset] = known
                while len(record.sites) > _MAX_CACHED_SITES:
                    record.sites.popitem(last=False)
    opname, position = known
    return {"code": record.key, "offset": offset, "opname": opname,
            "position": list(position) if position is not None else None}


__all__ = ["code_key", "code_parameters", "call_instruction", "describe_code", "site"]

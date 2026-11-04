"""F3-A: preserve official public symbol/scope material without AST joins.

Only the compiler's symbol-table entry point is invoked. No target bytecode is
generated or executed. As in F1/F2, warning isolation requires process workers
instead of concurrent threads on builds without context-aware warnings.
"""
from __future__ import annotations

import _symtable
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import struct
import symtable
import sys
import sysconfig
from types import MemberDescriptorType
import warnings

from scar.analysis.source_bytes import decoded_source_bytes
from scar.analysis.source_syntax import read_source_syntax
from scar.analysis.source_tokens import _error
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_symbols import (
    RawScopeMember, SourceScope, SourceSymbol, SourceSymbolsInput,
    SourceSymbolsMaterial, SourceSymbolsProfile, SymbolConstant, SymbolFrontier,
)
from scar.ir.program.source_tokens import SourceTokenWarning
from scar.ir.record_codec import decode, encode


_RAW_MEMBERS = tuple(RawScopeMember(*row) for row in (
    ('id', 'int', 'VOLATILE_NATIVE_AST_ADDRESS_KEY_OMITTED'),
    ('name', 'str', 'PERSISTED'), ('symbols', 'dict[str,int]', 'ORDERED_ITEMS'),
    ('varnames', 'list[str]', 'ORDERED_VALUES'),
    ('children', 'list[symtable entry]', 'ORDERED_LOCAL_REFERENCES'),
    ('nested', 'int', 'PERSISTED'), ('type', 'int', 'PERSISTED'), ('lineno', 'int', 'PERSISTED')))


def compiler_hash_context() -> str:
    """Fingerprint effective native string hashing, independent of environ.

    Closure analysis can insert synthetic free names in set iteration order.
    Preserve that original order and bind its replay to this process context.
    """
    probes = ('SCAR/F3-A/compiler-hash-context/v1', 'scope:outer/middle/inner',
        'binding/alpha-beta-gamma/0:1:2', 'symbol/α/目标/🙂/\x00')
    payload = ['CPYTHON_STR_HASH_PROBES_V1', *[hash(text) for text in probes]]
    return sha256(json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


@lru_cache(maxsize=1)
def _implementation():
    origin = _symtable.__spec__.origin
    if origin == 'built-in':
        if sysconfig.get_config_var('Py_ENABLE_SHARED'):
            raise ValueError('a built-in symtable in a shared runtime needs its loaded-library receipt')
        binary = str(Path(sys.executable).resolve())
    elif type(origin) is str and Path(origin).is_file():
        binary = str(Path(origin).resolve())
    else:
        raise ValueError('native symtable implementation binary is unavailable')
    return origin, binary, sha256(Path(binary).read_bytes()).hexdigest(), sha256(Path(symtable.__file__).read_bytes()).hexdigest()


def _profile(f0):
    origin, binary, binary_sha, wrapper_sha = _implementation()
    return SourceSymbolsProfile(decode(SourceBytesProfile, f0['profile']),
        '_symtable.symtable(str, filename, compile_type)', sysconfig.get_config_var('SOABI'),
        sys.abiflags, struct.calcsize('P') * 8, sys.byteorder, origin, binary, binary_sha, wrapper_sha,
        tuple(SymbolConstant(name, value) for name, value in vars(_symtable).items() if type(value) is int),
        _RAW_MEMBERS, sys.get_int_max_str_digits(), sys.getrecursionlimit(),
        sys.flags.hash_randomization, compiler_hash_context(),
        'RECORD_ALL_ALWAYS_ISOLATED_V1', 'F1_CRLF_AND_CR_TO_LF_NO_FINAL_NEWLINE_V1',
        'NO_CALLER_FUTURE_INHERITANCE', 'OFFICIAL_FUTURE_FROM_THIS_SOURCE',
        'SAME_NORMALIZED_SOURCE_DIFFERENT_COMPILER_ENTRY_NOT_SHARED_AST',
        'RAW_ENTRY_OBJECT_ALIAS_NORMALIZATION_NO_NATIVE_ADDRESS_PERSISTED',
        'BREADTH_FIRST_FIRST_DISCOVERY_ORIGINAL_CHILD_ORDER_V1', 'RETAIN_RAW_WORD_AND_EXPLICIT_INTERPRETATION_FRONTIER')


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


class SymbolBudgetExceeded(ValueError):
    def __init__(self, code, path, detail, symbol=None):
        self.frontier = SymbolFrontier(code, None, path, symbol, None, detail)
        super().__init__(detail)


def _validate_graph(scopes):
    if not scopes:
        raise ValueError('a public scope graph needs its module root')
    for row in scopes:
        row.__post_init__()
        if any(ref >= len(scopes) for ref in row.children):
            raise ValueError('public scope reference is outside its table')
    # Three colors reject cycles while allowing repeated references/aliases.
    colors, stack = [0] * len(scopes), [(0, False)]
    while stack:
        index, leaving = stack.pop()
        if leaving:
            colors[index] = 2
        elif colors[index] == 1:
            raise ValueError('cyclic public compiler scope graph')
        elif colors[index] == 0:
            colors[index] = 1
            stack.append((index, True))
            stack.extend((ref, False) for ref in reversed(scopes[index].children))
    if any(color != 2 for color in colors):
        raise ValueError('unreachable public compiler scope row')


def capture_raw_view(raw, *, max_scopes=100_000, max_symbols=1_000_000):
    """Normalize one raw result; aliases use local ordinals, not native .id.

    The raw objects remain strongly held until capture ends, so the temporary
    Python object identity keys cannot be recycled. Only local references are
    persisted. This helper also admits controlled native-object codec probes.
    """
    if any(type(n) is not int or n < 0 for n in (max_scopes, max_symbols)):
        raise ValueError('scope/symbol budgets must be exact nonnegative integers')
    raw_type = type(raw)
    members = tuple(name for name, value in vars(raw_type).items() if type(value) is MemberDescriptorType)
    if raw_type.__name__ != 'symtable entry' or members != tuple(row.name for row in _RAW_MEMBERS):
        raise ValueError('native public symtable entry schema differs')
    if max_scopes == 0:
        raise SymbolBudgetExceeded('SCOPE_BUDGET', (), 'maximum public scope count reached')
    objects, paths, ids, rows, symbol_count, cursor = [raw], [()], {id(raw): 0}, [], 0, 0
    while cursor < len(objects):
        table, path = objects[cursor], paths[cursor]
        if (type(table) is not raw_type or type(table.symbols) is not dict
                or type(table.varnames) is not list or type(table.children) is not list):
            raise ValueError('native public scope member/container types differ')
        symbols = []
        for name, flags in table.symbols.items():
            if symbol_count >= max_symbols:
                raise SymbolBudgetExceeded('SYMBOL_BUDGET', path, 'maximum compiler symbol count reached', name)
            symbols.append(SourceSymbol(name, flags))
            symbol_count += 1
        children = []
        for i, child in enumerate(table.children):
            if type(child) is not raw_type:
                raise ValueError('native child is not an exact public scope entry')
            identity = id(child)
            if identity not in ids:
                if len(objects) >= max_scopes:
                    raise SymbolBudgetExceeded('SCOPE_BUDGET', path + (i,), 'maximum public scope count reached')
                ids[identity] = len(objects)
                objects.append(child)
                paths.append(path + (i,))
            children.append(ids[identity])
        rows.append(SourceScope(table.type, table.name, table.lineno, table.nested,
            tuple(table.varnames), tuple(symbols), tuple(children)))
        cursor += 1
    result = tuple(rows)
    _validate_graph(result)
    return result


def _interpretation_frontiers(scopes, profile):
    constants = {item.name: item.value for item in profile.constants}
    known_bits = constants['SCOPE_MASK'] << constants['SCOPE_OFF']
    for name, value in constants.items():
        if name == 'USE' or name.startswith('DEF_'):
            known_bits |= value
    types = {value for name, value in constants.items() if name.startswith('TYPE_')}
    codes = {constants[name] for name in ('LOCAL', 'GLOBAL_EXPLICIT', 'GLOBAL_IMPLICIT', 'FREE', 'CELL')}
    paths, queue, cursor, found = {0: ()}, [0], 0, []
    while cursor < len(queue):
        index = queue[cursor]
        row, path = scopes[index], paths[index]
        if row.type not in types:
            found.append(SymbolFrontier('UNINTERPRETED_SCOPE_TYPE', index, path, None, row.type, 'raw scope type has no recorded official constant'))
        for symbol in row.symbols:
            unknown = symbol.flags & ~known_bits
            if unknown:
                found.append(SymbolFrontier('UNINTERPRETED_SYMBOL_FLAGS', index, path, symbol.name, unknown, 'unrecognized raw flag bits retained unchanged'))
            code = (symbol.flags >> constants['SCOPE_OFF']) & constants['SCOPE_MASK']
            if code not in codes:
                found.append(SymbolFrontier('UNINTERPRETED_SYMBOL_SCOPE', index, path, symbol.name, code, 'raw symbol scope code has no recorded official meaning'))
        for i, ref in enumerate(row.children):
            if ref not in paths:
                paths[ref] = path + (i,)
                queue.append(ref)
        cursor += 1
    return tuple(found)


def _native_symtable(text, path, mode):
    return _symtable.symtable(text, path, mode)


def _produce(f0, f1, f2, max_scopes, max_symbols):
    if any(type(n) is not int or n < 0 for n in (max_scopes, max_symbols)):
        raise ValueError('scope/symbol budgets must be exact nonnegative integers')
    read_source_syntax(f2, f0, f1)
    profile, mode = _profile(f0), f2['mode']
    inputs = SourceSymbolsInput(_digest(f0), _digest(f1), _digest(f2), f0['path'], f2['input']['view_sha256'], f2['status'])
    if f2['status'] != 'PARSED':
        return SourceSymbolsMaterial(inputs, profile, mode, max_scopes, max_symbols,
            'UPSTREAM_NOT_PARSED', None, (), (), None, ())
    if mode == 'func_type':
        return SourceSymbolsMaterial(inputs, profile, mode, max_scopes, max_symbols,
            'UNSUPPORTED_SYMTABLE_MODE', None, (), (), None, ())
    original = decoded_source_bytes(f0)
    text = original.replace('\r\n', '\n').replace('\r', '\n')
    status, scopes, frontiers, failure = 'CAPTURED', (), (), None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            raw = _native_symtable(text, f0['path'], mode)
        except (SyntaxError, ValueError, TypeError) as error:
            status, failure = 'SYMBOL_TABLE_ERROR', replace(_error(error),
                coordinate_basis='NATIVE_SYMBOL_TABLE_DIAGNOSTIC_NOT_AST_COORDINATES')
        except (MemoryError, RecursionError, OverflowError) as error:
            status, failure = 'RESOURCE_ERROR', replace(_error(error),
                coordinate_basis='NATIVE_SYMBOL_TABLE_DIAGNOSTIC_NOT_AST_COORDINATES')
        else:
            try:
                scopes = capture_raw_view(raw, max_scopes=max_scopes, max_symbols=max_symbols)
                frontiers = _interpretation_frontiers(scopes, profile)
            except SymbolBudgetExceeded as error:
                status, frontiers = 'BUDGET_STOPPED', (error.frontier,)
            except (MemoryError, RecursionError, OverflowError) as error:
                status, failure = 'RESOURCE_ERROR', replace(_error(error),
                    coordinate_basis='SOURCE_SYMBOL_MATERIAL_RESOURCE_ERROR')
    warning_rows = tuple(SourceTokenWarning(item.category.__module__, item.category.__qualname__,
        str(item.message), item.filename, item.lineno, item.line, item.source is not None) for item in caught)
    if status != 'CAPTURED':
        scopes = ()
    return SourceSymbolsMaterial(inputs, profile, mode, max_scopes, max_symbols, status,
        0 if status == 'CAPTURED' else None, scopes, frontiers, failure, warning_rows)


def source_symbols_document(f0, f1, f2, *, max_scopes=100_000, max_symbols=1_000_000) -> dict:
    return encode(_produce(f0, f1, f2, max_scopes, max_symbols))


def read_source_symbols(document, f0, f1, f2) -> SourceSymbolsMaterial:
    material = decode(SourceSymbolsMaterial, document)
    if material.profile != _profile(f0):
        raise ValueError('F3-A compiler profile mismatch (including effective hash context)')
    if material.status == 'CAPTURED':
        _validate_graph(material.scopes)
    fresh = _produce(f0, f1, f2, material.max_scopes, material.max_symbols)
    if material != fresh:
        raise ValueError('F3-A material differs from its F0/F1/F2/profile/fresh official compiler view')
    return material


__all__ = ['source_symbols_document', 'read_source_symbols', 'compiler_hash_context']

"""Event-local callable carrier facts, independent of Python target v2.

UNKNOWN means the probe did not establish a field. ABSENT is an explicit
inapplicability/null fact. Addresses are observations, never callable IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import re

from .call_edges import CallRecordAnchor, CallTraceFile, InvocationKey
from .call_operands import _reference


class NativeCarrier(str, Enum):
    METHOD_DEF = 'METHOD_DEF'
    WRAPPER_SLOT = 'WRAPPER_SLOT'
    UNKNOWN = 'UNKNOWN'


class NativeFieldState(str, Enum):
    OBSERVED = 'OBSERVED'
    ABSENT = 'ABSENT'
    UNKNOWN = 'UNKNOWN'


REFERENCE_FIELDS = frozenset(('exact_type', 'bound_self', 'defining_class', 'descriptor_owner'))
TEXT_FIELDS = frozenset(('exact_type_name', 'descriptor_owner_name', 'method_name', 'wrapper_name'))
FLAG_FIELDS = frozenset(('method_flags', 'wrapper_flags'))
ADDRESS_FIELDS = frozenset(('methoddef_address', 'entrypoint_address',
    'wrapper_adapter_address', 'wrapped_slot_address', 'dispatcher_vectorcall_address',
    'dispatcher_tp_call_address'))
METHOD_FIELDS = frozenset(('method_name', 'method_flags', 'methoddef_address',
    'entrypoint_address', 'bound_self', 'defining_class', 'descriptor_owner', 'descriptor_owner_name'))
WRAPPER_FIELDS = frozenset(('bound_self', 'descriptor_owner', 'descriptor_owner_name', 'wrapper_name',
    'wrapper_flags', 'wrapper_adapter_address', 'wrapped_slot_address'))
DISPATCH_FIELDS = ADDRESS_FIELDS - {'methoddef_address', 'entrypoint_address',
    'wrapper_adapter_address', 'wrapped_slot_address'}


def _text(value):
    return type(value) is str and bool(value) and '\0' not in value


def _sha(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


@dataclass(frozen=True, slots=True)
class NativeCallableField:
    state: NativeFieldState
    value: str | int | None
    reason: str | None

    def __post_init__(self):
        if type(self.state) is not NativeFieldState:
            raise TypeError('native field requires a typed observation state')
        if self.state is NativeFieldState.OBSERVED:
            if (type(self.value) not in (str, int) or self.reason is not None
                    or type(self.value) is str and not _text(self.value)):
                raise ValueError('observed native field requires a scalar value and no gap')
        elif self.value is not None or (self.state is NativeFieldState.UNKNOWN
                and not _text(self.reason)) or (self.state is NativeFieldState.ABSENT
                and self.reason is not None):
            raise ValueError('unknown and absent native fields must remain distinct')


@dataclass(frozen=True, slots=True)
class NativeCallableFields:
    exact_type: NativeCallableField
    exact_type_name: NativeCallableField
    method_name: NativeCallableField
    method_flags: NativeCallableField
    methoddef_address: NativeCallableField
    entrypoint_address: NativeCallableField
    bound_self: NativeCallableField
    defining_class: NativeCallableField
    descriptor_owner: NativeCallableField
    descriptor_owner_name: NativeCallableField
    wrapper_name: NativeCallableField
    wrapper_flags: NativeCallableField
    wrapper_adapter_address: NativeCallableField
    wrapped_slot_address: NativeCallableField
    dispatcher_vectorcall_address: NativeCallableField
    dispatcher_tp_call_address: NativeCallableField

    def __post_init__(self):
        for member in fields(self):
            item = getattr(self, member.name)
            if type(item) is not NativeCallableField:
                raise TypeError('native fields require exact NativeCallableField records')
            item.__post_init__()
            if item.state is not NativeFieldState.OBSERVED:
                continue
            if member.name in REFERENCE_FIELDS:
                _reference(item.value)
            elif member.name in TEXT_FIELDS:
                if not _text(item.value):
                    raise ValueError('native method/wrapper names must be text')
            elif not _integer(item.value, 1 if member.name in ADDRESS_FIELDS else 0):
                raise ValueError('native flags/addresses need exact nonnegative/positive integers')
        if any(getattr(self, key).state is not NativeFieldState.OBSERVED
               for key in ('exact_type', 'exact_type_name')):
            raise ValueError('the actual callable type must always be observed')


@dataclass(frozen=True, slots=True)
class NativeCallableFact:
    event_index: int
    caller: InvocationKey
    attempt_index: int
    callable_reference: str
    carrier: NativeCarrier
    fields: NativeCallableFields

    def __post_init__(self):
        if (not _integer(self.event_index, 1) or not _integer(self.attempt_index, 1)
                or type(self.caller) is not InvocationKey or type(self.carrier) is not NativeCarrier
                or type(self.fields) is not NativeCallableFields):
            raise ValueError('native callable facts need an original CALL and exact typed fields')
        self.caller.__post_init__()
        self.fields.__post_init__()
        _reference(self.callable_reference)
        references = (self.callable_reference, *(getattr(self.fields, key).value
            for key in REFERENCE_FIELDS
            if getattr(self.fields, key).state is NativeFieldState.OBSERVED))
        if any(int(reference.split(':')[1]) != self.caller.process_id for reference in references):
            raise ValueError('native reference token belongs to another process')
        if self.carrier is NativeCarrier.UNKNOWN:
            if any(getattr(self.fields, key).state is not NativeFieldState.UNKNOWN
                   for key in METHOD_FIELDS | WRAPPER_FIELDS):
                raise ValueError('unsupported callable carriers cannot assert exclusive native fields')
        else:
            inapplicable = (WRAPPER_FIELDS - METHOD_FIELDS if self.carrier is NativeCarrier.METHOD_DEF
                            else METHOD_FIELDS - WRAPPER_FIELDS)
            if any(getattr(self.fields, key).state is not NativeFieldState.ABSENT
                   for key in inapplicable):
                raise ValueError('method-definition and wrapper-slot fields cannot be conflated')


@dataclass(frozen=True, slots=True)
class NativeFileReceipt:
    path: str
    bytes: int
    sha256: str

    def __post_init__(self):
        if not _text(self.path) or not _integer(self.bytes) or not _sha(self.sha256):
            raise ValueError('invalid native callable input receipt')


@dataclass(frozen=True, slots=True)
class NativeCallableOutput:
    path: str
    bytes: int
    sha256: str
    rows: int

    def __post_init__(self):
        NativeFileReceipt(self.path, self.bytes, self.sha256)
        if not _integer(self.rows):
            raise ValueError('native output rows must be nonnegative')


@dataclass(frozen=True, slots=True)
class NativeCallableABI:
    implementation: str
    version: tuple[int, int, int]
    cache_tag: str
    pointer_bits: int

    def __post_init__(self):
        if (self.implementation != 'cpython' or type(self.implementation) is not str
                or type(self.version) is not tuple or self.version != (3, 14, 7)
                or any(type(value) is not int for value in self.version)
                or self.cache_tag != 'cpython-314' or type(self.cache_tag) is not str
                or type(self.pointer_bits) is not int or self.pointer_bits != 64):
            raise ValueError('unsupported exact native callable probe ABI')


@dataclass(frozen=True, slots=True)
class NativeCallableBudget:
    max_records: int = 100_000
    max_bytes: int = 32_000_000
    max_line_bytes: int = 2_000_000

    def __post_init__(self):
        if any(not _integer(getattr(self, member.name), 1) for member in fields(self)):
            raise ValueError('native callable budgets must be positive exact integers')


@dataclass(frozen=True, slots=True)
class NativeCallableCounts:
    rows: int
    attempts: int

    def __post_init__(self):
        if not _integer(self.rows) or not _integer(self.attempts):
            raise ValueError('native counts must be nonnegative exact integers')


@dataclass(frozen=True, slots=True)
class NativeCallableMetadata:
    schema: str
    schema_version: int
    capabilities: tuple[str, ...]
    process_id: int
    project_root: str
    abi: NativeCallableABI
    probe_source: NativeFileReceipt
    probe_binary: NativeFileReceipt
    legacy_inputs: tuple[CallTraceFile, ...]
    target_meta: NativeFileReceipt
    scope_policy: str
    budget: NativeCallableBudget
    counts: NativeCallableCounts
    stopped: bool
    errors: tuple[str, ...]
    io_failed: bool
    file: NativeCallableOutput

    def __post_init__(self):
        if (type(self.schema) is not str or self.schema != 'scar.native-callable-collection'
                or type(self.schema_version) is not int or self.schema_version != 1
                or type(self.capabilities) is not tuple
                or self.capabilities != ('NATIVE_CALLABLE_FACTS_V1',)
                or not _integer(self.process_id, 1) or not _text(self.project_root)
                or self.scope_policy != 'ALL_CALL_ATTEMPTS_V1' or type(self.scope_policy) is not str
                or type(self.stopped) is not bool or type(self.io_failed) is not bool
                or type(self.errors) is not tuple or any(not _text(error) for error in self.errors)):
            raise ValueError('invalid native callable capability, scope or completion declaration')
        for value, kind in ((self.abi, NativeCallableABI), (self.probe_source, NativeFileReceipt),
                (self.probe_binary, NativeFileReceipt), (self.target_meta, NativeFileReceipt),
                (self.budget, NativeCallableBudget), (self.counts, NativeCallableCounts),
                (self.file, NativeCallableOutput)):
            if type(value) is not kind:
                raise TypeError('native metadata requires exact ' + kind.__name__)
            value.__post_init__()
        if (type(self.legacy_inputs) is not tuple or len(self.legacy_inputs) != 5
                or any(type(row) is not CallTraceFile for row in self.legacy_inputs)):
            raise ValueError('native metadata must retain its five original CALL stream receipts')


@dataclass(frozen=True, slots=True)
class NativeCallableCapture:
    directory: str
    run_scope: str
    facts: tuple[NativeCallableFact, ...]
    anchors: tuple[CallRecordAnchor, ...]
    metadata: tuple[NativeCallableMetadata, ...]
    files: tuple[CallTraceFile, ...]

    def __post_init__(self):
        if not _text(self.directory) or not _sha(self.run_scope):
            raise ValueError('native callable capture needs its original directory and run')
        for rows, kind in ((self.facts, NativeCallableFact), (self.anchors, CallRecordAnchor),
                (self.metadata, NativeCallableMetadata), (self.files, CallTraceFile)):
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError('native capture requires immutable exact ' + kind.__name__ + ' rows')
        if len(self.facts) != len(self.anchors) or any(f.event_index != a.index
                for f, a in zip(self.facts, self.anchors)):
            raise ValueError('native facts must retain each original event anchor')


def build_fields(raw_probe_dict, reference):
    """Convert probe fields to fresh wire dictionaries without creating DTOs.

    Present Py_None is a real object. Missing applicable fields are UNKNOWN
    because the probe does not distinguish NULL from an unavailable field.
    """
    names = tuple(member.name for member in fields(NativeCallableFields))
    if (type(raw_probe_dict) is not dict
            or any(type(key) is not str for key in raw_probe_dict)
            or set(raw_probe_dict) - {'kind', *names}
            or type(raw_probe_dict.get('kind')) is not str
            or raw_probe_dict['kind'] not in ('METHOD_DEF', 'WRAPPER_SLOT', 'UNKNOWN')
            or 'exact_type' not in raw_probe_dict or 'exact_type_name' not in raw_probe_dict
            or not callable(reference)):
        raise ValueError('unsupported raw native probe fields/carrier')
    carrier = raw_probe_dict['kind']
    applicable = (METHOD_FIELDS if carrier == 'METHOD_DEF' else WRAPPER_FIELDS
                  if carrier == 'WRAPPER_SLOT' else frozenset())
    exclusive = METHOD_FIELDS | WRAPPER_FIELDS
    result = {}
    for name in names:
        if name in exclusive and name not in applicable:
            if name in raw_probe_dict:
                raise ValueError('probe exposed a field outside its native carrier contract')
            state = 'UNKNOWN' if carrier == 'UNKNOWN' else 'ABSENT'
            result[name] = {'state': state, 'value': None,
                'reason': 'UNSUPPORTED_CALLABLE_CARRIER' if state == 'UNKNOWN' else None}
            continue
        if name not in raw_probe_dict:
            result[name] = {'state': 'UNKNOWN', 'value': None,
                            'reason': 'PROBE_DID_NOT_EXPOSE_FIELD'}
            continue
        value = raw_probe_dict[name]
        if name in REFERENCE_FIELDS:
            value = reference(value)
            _reference(value)
        elif name in TEXT_FIELDS:
            if not _text(value):
                raise ValueError('native probe text must be nonempty exact text')
        elif name in ADDRESS_FIELDS | FLAG_FIELDS:
            if not _integer(value):
                raise ValueError('native probe flags/addresses must be nonnegative exact integers')
            if name in ADDRESS_FIELDS and value == 0:
                result[name] = {'state': 'ABSENT', 'value': None, 'reason': None}
                continue
        result[name] = {'state': 'OBSERVED', 'value': value, 'reason': None}
    return result


__all__ = ['NativeCarrier', 'NativeFieldState', 'NativeCallableField', 'NativeCallableFields',
    'NativeCallableFact', 'NativeFileReceipt', 'NativeCallableOutput', 'NativeCallableABI',
    'NativeCallableBudget', 'NativeCallableCounts', 'NativeCallableMetadata', 'NativeCallableCapture',
    'build_fields']

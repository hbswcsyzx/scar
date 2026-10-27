"""Strict operand observations; no observation is an unconditional binding proof."""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import re

from scar.ir.program.call_edges import CallRecordAnchor, CallTraceFile, CapturedSite, InvocationKey


LOAD_OCCURRENCES_RULE = "CPYTHON_LOAD_OCCURRENCES_V1"
CALL_WINDOWS_RULE = "CPYTHON_CALL_WINDOWS_V1"
LEAN_PORTS_RULE = "SCAR_LEAN_PORTS_V1"
PROGRAM_PORTS_RULE = "SCAR_PROGRAM_PORTS_V1"
PROCESS_PORTS_RULE = "SCAR_PROGRAM_PORTS_V2"
OPERAND_CAPTURE_RULES = frozenset((LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE, LEAN_PORTS_RULE, PROGRAM_PORTS_RULE, PROCESS_PORTS_RULE))


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _integer(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, name + " must be an exact integer >= " + str(minimum))


def _text(value, name):
    _require(type(value) is str and bool(value), name + " must be nonempty text")


def _code(value):
    _require(type(value) is str and re.fullmatch(r"pycode-v2:[0-9a-f]{64}", value) is not None,
             "operand code must be a canonical pycode-v2 fingerprint")


def _reference(value):
    _require(type(value) is str and re.fullmatch(
        r"(?:weak:[1-9][0-9]*:[1-9][0-9]*|operand-snapshot:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*)", value,
    ) is not None, "operand reference is outside the capture protocol")


def _tuple(value, kind, name):
    _require(type(value) is tuple and all(type(item) is kind for item in value), name + " must be a typed tuple")


def _site(value):
    _require(type(value) is CapturedSite, "operand site must be typed")
    _code(value.code)
    _integer(value.offset, "operand offset")
    _text(value.opname, "operand opcode")
    if value.position is not None:
        _require(type(value.position) is tuple, "operand position must be a tuple")
    value.__post_init__()


@dataclass(frozen=True, slots=True)
class CallOperandBudget:
    max_raw_bytes: int = 128_000_000
    max_lines: int = 1_000_000
    max_line_bytes: int = 2_000_000
    max_processes: int = 128
    max_events: int = 1_000_000
    max_loads: int = 1_000_000
    max_references: int = 2_000_000
    max_metadata_bytes: int = 2_000_000

    def __post_init__(self):
        for field in fields(self):
            _integer(getattr(self, field.name), field.name, 1)


class CallableKind(str, Enum):
    EXACT_FUNCTION = "EXACT_FUNCTION"
    EXACT_METHOD = "EXACT_METHOD"
    OTHER = "OTHER"
    UNAVAILABLE = "UNAVAILABLE"


class LoadNamespace(str, Enum):
    FAST_LOCAL = "FAST_LOCAL"
    GLOBAL = "GLOBAL"
    BUILTIN = "BUILTIN"


class OperandEventKind(str, Enum):
    INSTRUCTION = "INSTRUCTION"
    CALL_ATTEMPT = "CALL_ATTEMPT"
    ENTRY_HANDSHAKE = "ENTRY_HANDSHAKE"
    GAP = "GAP"
    SCOPED_GAP = "SCOPED_GAP"


@dataclass(frozen=True, slots=True)
class FunctionLayout:
    argcount: int
    posonlyargcount: int
    kwonlyargcount: int
    flags: int
    parameters: tuple[str, ...]

    def __post_init__(self):
        for name in ("argcount", "posonlyargcount", "kwonlyargcount", "flags"):
            _integer(getattr(self, name), name)
        _require(self.posonlyargcount <= self.argcount, "positional-only count exceeds positional count")
        _tuple(self.parameters, str, "parameters")
        _require(all(self.parameters) and len(set(self.parameters)) == len(self.parameters),
                 "parameter names must be unique nonempty strings")
        expected = self.argcount + self.kwonlyargcount + bool(self.flags & 4) + bool(self.flags & 8)
        _require(len(self.parameters) == expected, "function layout parameter count disagrees with flags/counts")


@dataclass(frozen=True, slots=True)
class CallableShape:
    kind: CallableKind
    reference: str | None
    code: str | None
    layout: FunctionLayout | None

    def __post_init__(self):
        _require(type(self.kind) is CallableKind, "callable kind must be typed")
        if self.reference is not None:
            _reference(self.reference)
        if self.kind is CallableKind.EXACT_FUNCTION:
            _require(self.reference is not None and type(self.layout) is FunctionLayout,
                     "exact function needs a reference and typed layout")
            _code(self.code)
            self.layout.__post_init__()
        else:
            _require(self.code is None and self.layout is None, "non-function shape cannot claim code/layout")
            if self.kind is CallableKind.UNAVAILABLE:
                _require(self.reference is None, "unavailable shape cannot claim a reference")
            else:
                _require(self.reference is not None, "observed shape needs its reference")


@dataclass(frozen=True, slots=True)
class LoadObservation:
    suboperand: int
    namespace: LoadNamespace
    slot: str
    slot_index: int | None
    reference: str | None
    callable_shape: CallableShape

    def __post_init__(self):
        _integer(self.suboperand, "suboperand")
        _require(type(self.namespace) is LoadNamespace, "load namespace must be typed")
        _text(self.slot, "load slot")
        if self.namespace is LoadNamespace.FAST_LOCAL:
            _integer(self.slot_index, "fast-local slot index")
        else:
            _require(self.slot_index is None, "global/builtin loads have no fast-local slot index")
        if self.reference is not None:
            _reference(self.reference)
        _require(type(self.callable_shape) is CallableShape, "load callable shape must be typed")
        self.callable_shape.__post_init__()
        _require(self.reference == self.callable_shape.reference, "load and callable shape references disagree")


class _OperandEvent:
    __slots__ = ()

    @property
    def invocation(self):
        if self.invocation_id is None:
            return None
        return InvocationKey(self.process_id, self.thread_id, self.invocation_id)

    @property
    def key(self):
        return self.process_id, self.index

    def _common(self, expected):
        _require(type(self.kind) is OperandEventKind and self.kind is expected, "operand event kind mismatch")
        for name, minimum in (("index", 1), ("process_id", 1), ("thread_id", 0),
                              ("frame_index", 0), ("hook_epoch", 1)):
            _integer(getattr(self, name), name, minimum)
        if self.invocation_id is None:
            _require(expected in (OperandEventKind.GAP, OperandEventKind.SCOPED_GAP), "only gaps may have no invocation")
        else:
            _integer(self.invocation_id, "invocation_id", 1)
        _require(type(self.anchor) is CallRecordAnchor, "operand event needs its own raw anchor")
        _text(self.anchor.path, "operand anchor path")
        _integer(self.anchor.line_number, "operand anchor line", 1)
        _require(type(self.anchor.line_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", self.anchor.line_sha256),
                 "operand anchor needs a canonical SHA256")
        _require(type(self.anchor.index) is int and self.anchor.index == self.index,
                 "operand anchor index differs from event index")


@dataclass(frozen=True, slots=True)
class OperandInstruction(_OperandEvent):
    anchor: CallRecordAnchor
    index: int
    kind: OperandEventKind
    process_id: int
    thread_id: int
    invocation_id: int
    frame_index: int
    hook_epoch: int
    site: CapturedSite
    loads: tuple[LoadObservation, ...]

    def __post_init__(self):
        self._common(OperandEventKind.INSTRUCTION)
        _site(self.site)
        _tuple(self.loads, LoadObservation, "instruction loads")
        _require(tuple(item.suboperand for item in self.loads) == tuple(range(len(self.loads))),
                 "load suboperands must be contiguous and ordered")
        for item in self.loads:
            item.__post_init__()


@dataclass(frozen=True, slots=True)
class OperandCallAttempt(_OperandEvent):
    anchor: CallRecordAnchor
    index: int
    kind: OperandEventKind
    process_id: int
    thread_id: int
    invocation_id: int
    frame_index: int
    hook_epoch: int
    site: CapturedSite
    dispatch: CallableShape
    arg0: str | None
    arg0_missing: bool

    def __post_init__(self):
        self._common(OperandEventKind.CALL_ATTEMPT)
        _site(self.site)
        _require(type(self.dispatch) is CallableShape, "dispatch shape must be typed")
        self.dispatch.__post_init__()
        _require(type(self.arg0_missing) is bool, "arg0_missing must be an exact boolean")
        _require((self.arg0 is None) is self.arg0_missing, "arg0 presence disagrees with MISSING flag")
        if self.arg0 is not None:
            _reference(self.arg0)


@dataclass(frozen=True, slots=True)
class OperandEntryHandshake(_OperandEvent):
    anchor: CallRecordAnchor
    index: int
    kind: OperandEventKind
    process_id: int
    thread_id: int
    invocation_id: int
    frame_index: int
    hook_epoch: int
    attempt_index: int
    entry_index: int

    def __post_init__(self):
        self._common(OperandEventKind.ENTRY_HANDSHAKE)
        _integer(self.attempt_index, "attempt_index", 1)
        _integer(self.entry_index, "entry_index", 1)
        _require(self.attempt_index < self.index, "handshake must follow its attempt")
        _require(self.entry_index == self.frame_index, "handshake watermark must identify its original entry")


@dataclass(frozen=True, slots=True)
class OperandGap(_OperandEvent):
    anchor: CallRecordAnchor
    index: int
    kind: OperandEventKind
    process_id: int
    thread_id: int
    invocation_id: int | None
    frame_index: int
    hook_epoch: int
    reason: str

    def __post_init__(self):
        self._common(OperandEventKind.GAP)
        _text(self.reason, "operand gap reason")


@dataclass(frozen=True, slots=True)
class OperandScopedGap(_OperandEvent):
    anchor: CallRecordAnchor
    index: int
    kind: OperandEventKind
    process_id: int
    thread_id: int
    invocation_id: int | None
    frame_index: int
    hook_epoch: int
    reason: str
    code: str

    def __post_init__(self):
        self._common(OperandEventKind.SCOPED_GAP)
        _text(self.reason, "scoped operand gap reason")
        _code(self.code)


OperandEvent = OperandInstruction | OperandCallAttempt | OperandEntryHandshake | OperandGap | OperandScopedGap


@dataclass(frozen=True, slots=True)
class OperandCollectionLimits:
    max_events: int
    max_bytes: int
    max_loads: int
    max_namespace_items: int
    max_references: int

    def __post_init__(self):
        for field in fields(self):
            _integer(getattr(self, field.name), field.name, 1)


@dataclass(frozen=True, slots=True)
class OperandCollectionMetadata:
    schema: str
    schema_version: int
    process_id: int
    project_root: str
    python: str
    implementation: str
    rule: str
    limits: OperandCollectionLimits
    events: int
    event_attempts: int
    instructions: int
    call_attempts: int
    handshakes: int
    gaps: int
    loads: int
    references: int
    bytes: int
    dropped_events: int
    errors: tuple[str, ...]
    io_failed: bool
    previous_profile: bool
    base_manifest: tuple[CallTraceFile, ...]
    reference_contents_observed: bool
    callable_environment_established: bool
    transformation_authorized: bool

    def __post_init__(self):
        _require(self.schema == "scar.call-operands-trace" and type(self.schema) is str,
                 "operand metadata schema mismatch")
        _require(type(self.schema_version) is int and self.schema_version == 1,
                 "operand metadata version mismatch")
        _integer(self.process_id, "metadata process", 1)
        for name in ("project_root", "python", "implementation", "rule"):
            _text(getattr(self, name), name)
        _require(self.implementation == "cpython" and self.rule in OPERAND_CAPTURE_RULES,
                 "operand interpreter/rule is unsupported")
        _require(type(self.limits) is OperandCollectionLimits, "operand collection limits must be typed")
        self.limits.__post_init__()
        for name in ("events", "event_attempts", "instructions", "call_attempts", "handshakes", "gaps",
                     "loads", "references", "bytes", "dropped_events"):
            _integer(getattr(self, name), name)
        _require(self.events == self.instructions + self.call_attempts + self.handshakes + self.gaps,
                 "operand event counters disagree")
        _require(self.events <= self.event_attempts <= self.limits.max_events,
                 "operand event attempts exceed collection limit")
        _require(self.event_attempts - self.events <= self.dropped_events,
                 "operand unwritten attempts lack declared drops")
        _require(self.bytes <= self.limits.max_bytes, "operand bytes exceed collection limit")
        _tuple(self.errors, str, "operand errors")
        _require(len(self.errors) <= 16 and all(self.errors), "operand errors must be at most 16 nonempty strings")
        for name in ("io_failed", "previous_profile"):
            _require(type(getattr(self, name)) is bool, name + " must be an exact boolean")
        for name in ("reference_contents_observed", "callable_environment_established", "transformation_authorized"):
            _require(getattr(self, name) is False, "operand observations cannot grant " + name)
        _tuple(self.base_manifest, CallTraceFile, "base manifest")
        _require(len(self.base_manifest) == 3 and {item.family for item in self.base_manifest} == {"codes", "events", "meta"},
                 "operand metadata must bind all three original frame files")
        _require(len({item.path for item in self.base_manifest}) == 3, "base manifest paths must be unique")
        for item in self.base_manifest:
            _text(item.path, "base manifest path")
            _require(type(item.process_id) is int and item.process_id == self.process_id,
                     "base manifest process mismatch")
            _require(type(item.raw_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", item.raw_sha256),
                     "base manifest needs a canonical SHA256")
            _integer(item.raw_bytes, "base manifest bytes")
            _integer(item.lines, "base manifest lines")


def operand_references(event):
    """Count every serialized reference field; repeated tokens still cost space."""
    if type(event) is OperandInstruction:
        return tuple(reference for load in event.loads
                     for reference in (load.reference, load.callable_shape.reference) if reference is not None)
    if type(event) is OperandCallAttempt:
        return tuple(reference for reference in (event.dispatch.reference, event.arg0) if reference is not None)
    return ()


__all__ = ["LOAD_OCCURRENCES_RULE", "CALL_WINDOWS_RULE", "PROGRAM_PORTS_RULE", "PROCESS_PORTS_RULE", "OPERAND_CAPTURE_RULES",
           "CallOperandBudget", "CallableKind", "FunctionLayout", "CallableShape", "LoadNamespace",
           "LoadObservation", "OperandEventKind", "OperandInstruction", "OperandCallAttempt",
           "OperandEntryHandshake", "OperandGap", "OperandEvent", "OperandCollectionLimits",
           "OperandCollectionMetadata", "operand_references"]

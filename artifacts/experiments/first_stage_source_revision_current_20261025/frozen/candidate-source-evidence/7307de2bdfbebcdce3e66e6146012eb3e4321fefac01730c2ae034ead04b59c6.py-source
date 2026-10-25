"""Inventory v6 demand records, without raw/source or execution authority.

These records distinguish analysis work from program facts. The coordinator
must replay their seed membership, source identities, queue order and final
body links. Decoding a record performs only structural validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import re

from scar.ir.program.expansion import ContextStoreBudget, ContextUnavailable
from scar.ir.program.ids import RegionID
from scar.ir.program.inventory import BodyStatus
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2._validation import record_errors
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, name, minimum=0):
    _require(type(value) is int and value >= minimum,
             name + " must be an exact integer >= " + str(minimum))


def _text(value, name):
    _require(type(value) is str and bool(value), name + " must be nonempty text")


def _path(value, name):
    _text(value, name)
    _require(os.path.isabs(value) and os.path.normpath(value) == value,
             name + " must be an absolute normalized path")


def _hash(value, name, prefix):
    _require(type(value) is str and re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value) is not None,
             name + " must be a canonical SHA256")


def _record(value, expected, name):
    _require(type(value) is expected, name + " has the wrong record type")
    errors = record_errors(value, expected, name)
    if errors:
        raise ValueError("; ".join(errors))


def _snapshot(value):
    _record(value, SourceSnapshot, "snapshot")
    _path(value.path, "snapshot.path")
    _hash(value.fingerprint, "snapshot.fingerprint", "sha256:")


def _source(value):
    _record(value, SourceReference, "source")
    _path(value.path, "source.path")
    _hash(value.fingerprint, "source.fingerprint", "sha256:")


class _WireRecord:
    def to_dict(self):
        self.__post_init__()
        return encode(self)

    @classmethod
    def from_dict(cls, document):
        """Decode structure only; independent raw/source replay is external."""
        return decode(cls, document)


class DemandOriginKind(str, Enum):
    LEGACY_OBSERVATION = "LEGACY_OBSERVATION"
    ENTERED_CALL_CODE = "ENTERED_CALL_CODE"
    SOURCE_CALL_CANDIDATE = "SOURCE_CALL_CANDIDATE"
    REMAINDER = "REMAINDER"


@dataclass(frozen=True, slots=True)
class LegacyObservation(_WireRecord):
    index: int
    kind: DemandOriginKind = DemandOriginKind.LEGACY_OBSERVATION

    def __post_init__(self):
        _integer(self.index, "legacy observation index")
        _require(self.kind is DemandOriginKind.LEGACY_OBSERVATION, "incorrect legacy observation kind")


@dataclass(frozen=True, slots=True)
class EnteredCallCode(_WireRecord):
    process_id: int
    code: str
    kind: DemandOriginKind = DemandOriginKind.ENTERED_CALL_CODE

    def __post_init__(self):
        _integer(self.process_id, "process_id", 1)
        _hash(self.code, "code", "pycode-v2:")
        _require(self.kind is DemandOriginKind.ENTERED_CALL_CODE, "incorrect entered-code kind")


@dataclass(frozen=True, slots=True)
class SourceCallCandidate(_WireRecord):
    call: OperationDefinitionID
    kind: DemandOriginKind = DemandOriginKind.SOURCE_CALL_CANDIDATE

    def __post_init__(self):
        _record(self.call, OperationDefinitionID, "source call")
        _require(self.kind is DemandOriginKind.SOURCE_CALL_CANDIDATE, "incorrect source-call kind")


@dataclass(frozen=True, slots=True)
class Remainder(_WireRecord):
    kind: DemandOriginKind = DemandOriginKind.REMAINDER

    def __post_init__(self):
        _require(self.kind is DemandOriginKind.REMAINDER, "incorrect remainder kind")


DemandOrigin = LegacyObservation | EnteredCallCode | SourceCallCandidate | Remainder
_ORIGIN_TYPES = (LegacyObservation, EnteredCallCode, SourceCallCandidate, Remainder)


@dataclass(frozen=True, slots=True)
class BodyExpansionV6(_WireRecord):
    definition: OperationDefinitionID
    source: SourceReference
    origins: tuple[DemandOrigin, ...]
    attempted: bool = False
    construction_operations: int = 0
    status: BodyStatus = BodyStatus.NOT_ATTEMPTED
    operation_budget_charged: int = 0
    construction_cost_known: bool = True

    def __post_init__(self):
        _record(self.definition, OperationDefinitionID, "definition")
        _source(self.source)
        _require(type(self.origins) is tuple and bool(self.origins), "body needs a nonempty tuple of origins")
        for origin in self.origins:
            _require(type(origin) in _ORIGIN_TYPES, "body origin must be a typed demand origin")
            origin.__post_init__()
        _require(len(set(self.origins)) == len(self.origins), "duplicate body demand origin")
        _require(type(self.attempted) is bool and type(self.construction_cost_known) is bool,
                 "expansion flags must be exact booleans")
        _require(type(self.status) is BodyStatus, "body status must be typed")
        for name in ("construction_operations", "operation_budget_charged"):
            _integer(getattr(self, name), name)
        _require(self.operation_budget_charged >= self.construction_operations,
                 "constructed operations cannot be refunded")
        if not self.attempted:
            _require(self.status is BodyStatus.NOT_ATTEMPTED and not self.construction_operations
                     and not self.operation_budget_charged and self.construction_cost_known,
                     "unattempted task cannot claim construction work")
        else:
            _require(self.status is not BodyStatus.NOT_ATTEMPTED, "attempted task needs an explicit result")


@dataclass(frozen=True, slots=True)
class EntryRoot(_WireRecord):
    """The entry module's source scope; this is not a lowered function body."""
    snapshot: SourceSnapshot
    initializer: OperationDefinitionID

    def __post_init__(self):
        _snapshot(self.snapshot)
        _record(self.initializer, OperationDefinitionID, "module initializer")


@dataclass(frozen=True, slots=True)
class ExpansionScheduleV6(_WireRecord):
    budget: ContextStoreBudget
    entries: tuple[BodyExpansionV6, ...]
    entry_roots: tuple[EntryRoot, ...]
    unavailable_contexts: tuple[ContextUnavailable, ...] = ()

    def __post_init__(self):
        _record(self.budget, ContextStoreBudget, "context budget")
        for name, expected in (("entries", BodyExpansionV6), ("entry_roots", EntryRoot),
                               ("unavailable_contexts", ContextUnavailable)):
            values = getattr(self, name)
            _require(type(values) is tuple, name + " must be a tuple")
            for value in values:
                _record(value, expected, name)
        _require(len({entry.definition for entry in self.entries}) == len(self.entries),
                 "a body definition can be scheduled only once")
        _require(len({root.initializer for root in self.entry_roots}) == len(self.entry_roots)
                 and len({root.snapshot.path for root in self.entry_roots}) == len(self.entry_roots),
                 "duplicate entry source scope")
        for entry in self.unavailable_contexts:
            _path(entry.path, "unavailable context path")
            _text(entry.reason, "unavailable context reason")
        _require(len({entry.path for entry in self.unavailable_contexts}) == len(self.unavailable_contexts),
                 "duplicate unavailable context")


class CallSourceAdmissionStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    INDEXED_WITHOUT_BODY = "INDEXED_WITHOUT_BODY"
    CORE_LINKED = "CORE_LINKED"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class CallSourceAdmission(_WireRecord):
    origin: EnteredCallCode
    status: CallSourceAdmissionStatus
    snapshot: SourceSnapshot | None = None
    definition: OperationDefinitionID | None = None
    source: SourceReference | None = None
    core_region: RegionID | None = None
    reason: str = ""

    def __post_init__(self):
        _record(self.origin, EnteredCallCode, "admission origin")
        _require(type(self.status) is CallSourceAdmissionStatus, "admission status must be typed")
        _require(type(self.reason) is str, "admission reason must be text")
        if self.status in (CallSourceAdmissionStatus.UNAVAILABLE, CallSourceAdmissionStatus.MISMATCH):
            _require(all(value is None for value in (self.snapshot, self.definition, self.source, self.core_region)),
                     "unavailable/mismatched admission cannot retain a successful source/core link")
            _text(self.reason, "admission boundary reason")
            return
        _snapshot(self.snapshot)
        _record(self.definition, OperationDefinitionID, "indexed definition")
        _source(self.source)
        _require(self.snapshot.path == self.source.path and self.snapshot.fingerprint == self.source.fingerprint,
                 "indexed source differs from its snapshot")
        if self.status is CallSourceAdmissionStatus.CORE_LINKED:
            _record(self.core_region, RegionID, "core region")
        else:
            _require(self.core_region is None, "indexed-only admission cannot claim a core region")
            _text(self.reason, "no-body boundary reason")


@dataclass(frozen=True, slots=True)
class CallSourceScope(_WireRecord):
    """Group outcomes; the enclosing inventory stores the seed report once."""
    admissions: tuple[CallSourceAdmission, ...]

    def __post_init__(self):
        _require(type(self.admissions) is tuple, "admissions must be a tuple")
        for admission in self.admissions:
            _record(admission, CallSourceAdmission, "admission")
        _require(len({(item.origin.process_id, item.origin.code) for item in self.admissions}) == len(self.admissions),
                 "duplicate entered-code admission")


__all__ = [
    "BodyExpansionV6", "CallSourceAdmission", "CallSourceAdmissionStatus", "CallSourceScope",
    "DemandOrigin", "DemandOriginKind", "EnteredCallCode", "EntryRoot", "ExpansionScheduleV6",
    "LegacyObservation", "Remainder", "SourceCallCandidate",
]

"""Observed frame entries and source/core correspondences, without effect proofs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + " must be an exact integer >= " + str(minimum))


def _text(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be nonempty text")


@dataclass(frozen=True, slots=True)
class CallEdgeBudget:
    max_raw_bytes: int = 128_000_000
    max_lines: int = 200_000
    max_line_bytes: int = 2_000_000
    max_processes: int = 128
    max_codes: int = 8192
    max_events: int = 100_000
    max_source_files: int = 256
    max_source_bytes: int = 16_000_000
    max_references: int = 1_000_000
    max_path: int = 128

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            _integer(getattr(self, name), name, 1)


@dataclass(frozen=True, slots=True)
class InvocationKey:
    process_id: int
    thread_id: int
    invocation_id: int

    def __post_init__(self):
        _integer(self.process_id, "process_id", 1)
        _integer(self.thread_id, "thread_id")
        _integer(self.invocation_id, "invocation_id", 1)


@dataclass(frozen=True, slots=True)
class CallRecordAnchor:
    path: str
    line_number: int
    line_sha256: str
    index: int | None = None

    def __post_init__(self):
        _text(self.path, "anchor path")
        _integer(self.line_number, "anchor line", 1)
        if re.fullmatch(r"[0-9a-f]{64}", self.line_sha256) is None:
            raise ValueError("anchor needs a canonical SHA256")
        if self.index is not None:
            _integer(self.index, "event index")


@dataclass(frozen=True, slots=True)
class CallTraceFile:
    path: str
    family: str
    process_id: int
    raw_sha256: str
    raw_bytes: int
    lines: int


@dataclass(frozen=True, slots=True)
class CapturedCode:
    key: str
    filename: str
    qualname: str
    first_line: int
    flags: int
    parameters: tuple[str, ...]

    def __post_init__(self):
        if re.fullmatch(r"pycode-v2:[0-9a-f]{64}", self.key) is None:
            raise ValueError("captured code needs the stable v2 fingerprint")
        _text(self.filename, "code filename")
        _text(self.qualname, "code qualname")
        _integer(self.first_line, "code first line")
        _integer(self.flags, "code flags")
        if len(set(self.parameters)) != len(self.parameters) or any(type(name) is not str or not name for name in self.parameters):
            raise ValueError("captured formal names must be unique nonempty strings")


@dataclass(frozen=True, slots=True)
class CodeCapture:
    code: CapturedCode
    anchor: CallRecordAnchor
    process_id: int


@dataclass(frozen=True, slots=True)
class CapturedSite:
    code: str
    offset: int
    opname: str | None
    position: tuple[int, int, int, int] | None

    def __post_init__(self):
        _text(self.code, "site code")
        _integer(self.offset, "site offset", -1)
        if self.opname is not None:
            _text(self.opname, "site opcode")
        if self.position is not None:
            if len(self.position) != 4 or any(type(item) is not int for item in self.position):
                raise ValueError("site position needs four exact coordinates")
            first, last, start, end = self.position
            if first < 0 or last < first or start < 0 or end < 0 or first == last and end < start:
                raise ValueError("site position span is invalid")


@dataclass(frozen=True, slots=True)
class NamedReference:
    name: str
    ref: str

    def __post_init__(self):
        _text(self.name, "reference name")
        if re.fullmatch(r"(?:weak:[0-9]+:[0-9]+|snapshot:[0-9]+:[0-9]+:[0-9]+)", self.ref) is None:
            raise ValueError("reference token is outside the capture protocol")


@dataclass(frozen=True, slots=True)
class FrameEntry:
    anchor: CallRecordAnchor
    invocation: InvocationKey
    code: str
    parameters: tuple[NamedReference, ...]
    parameters_complete: bool
    caller: CapturedSite | None
    caller_invocation: InvocationKey | None
    ancestor_invocation: InvocationKey | None
    path: tuple[CapturedSite, ...]
    path_complete: bool
    caller_locals: tuple[NamedReference, ...]
    caller_locals_complete: bool
    suspended: bool


class FrameCompletion(str, Enum):
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"
    SUSPENDED = "SUSPENDED"


@dataclass(frozen=True, slots=True)
class FrameExit:
    anchor: CallRecordAnchor
    invocation: InvocationKey
    code: str
    return_site: CapturedSite
    completion: FrameCompletion
    return_ref: str
    locals: tuple[NamedReference, ...]
    locals_complete: bool


class CallLinkStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INCOMPLETE = "INCOMPLETE"
    MISMATCH = "MISMATCH"


class CallEdgeIssueKind(str, Enum):
    MISSING_CODE = "MISSING_CODE"
    SOURCE_BOUNDARY = "SOURCE_BOUNDARY"
    CODE_MISMATCH = "CODE_MISMATCH"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    NO_SOURCE_CALL = "NO_SOURCE_CALL"
    NO_CALLER = "NO_CALLER"
    UNTRACKED_CALLER = "UNTRACKED_CALLER"
    INCOMPLETE_PATH = "INCOMPLETE_PATH"
    SUSPENDED_FRAME = "SUSPENDED_FRAME"
    CORE_CALL_MISSING = "CORE_CALL_MISSING"
    TARGET_DEFINITION_MISSING = "TARGET_DEFINITION_MISSING"
    TARGET_BODY_MISSING = "TARGET_BODY_MISSING"
    TRACE_COLLECTION_GAP = "TRACE_COLLECTION_GAP"
    INVOCATION_MISSING = "INVOCATION_MISSING"
    INVOCATION_MISMATCH = "INVOCATION_MISMATCH"
    REFERENCE_FLOW_GAP = "REFERENCE_FLOW_GAP"
    ARGUMENT_ROUTING_UNVERIFIED = "ARGUMENT_ROUTING_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class CallEdgeIssue:
    kind: CallEdgeIssueKind
    detail: str
    anchor: CallRecordAnchor | None = None

    def __post_init__(self):
        _text(self.detail, "call edge issue")


@dataclass(frozen=True, slots=True)
class CodeSourceLink:
    code: str
    status: CallLinkStatus
    snapshot: SourceSnapshot | None = None
    definition: OperationDefinitionID | None = None
    source: SourceReference | None = None
    optimize_levels: tuple[int, ...] = ()
    issues: tuple[CallEdgeIssue, ...] = ()

    def __post_init__(self):
        if self.status is not CallLinkStatus.VERIFIED and (self.definition is not None or self.source is not None):
            raise ValueError("unverified code cannot claim a source definition")
        if self.status is CallLinkStatus.VERIFIED and self.snapshot is None:
            raise ValueError("verified code needs its source snapshot")


@dataclass(frozen=True, slots=True)
class CallSiteLink:
    site: CapturedSite
    status: CallLinkStatus
    source: SourceReference | None = None
    call: OperationDefinitionID | None = None
    execution_owner: OperationDefinitionID | None = None
    core_region: RegionID | None = None
    core_operation: OperationID | None = None
    callee_use: UseID | None = None
    callee_value: ValueID | None = None
    issues: tuple[CallEdgeIssue, ...] = ()

    def __post_init__(self):
        core = (self.core_region, self.core_operation, self.callee_use, self.callee_value)
        if any(value is not None for value in core) and any(value is None for value in core):
            raise ValueError("core call needs region, operation and callee use/value together")
        if self.status is not CallLinkStatus.VERIFIED and any(value is not None for value in (*core, self.source, self.call, self.execution_owner)):
            raise ValueError("unverified call site cannot retain source/core routes")
        if self.status is CallLinkStatus.VERIFIED and (self.source is None or self.call is None):
            raise ValueError("verified call site needs one source call")


class CallEdgeCondition(str, Enum):
    TRACE_PRODUCER_AND_CAPTURE_TRUSTED = "TRACE_PRODUCER_AND_CAPTURE_TRUSTED"
    FUNCTION_OBJECT_AND_ENVIRONMENT_UNVERIFIED = "FUNCTION_OBJECT_AND_ENVIRONMENT_UNVERIFIED"
    ACTUAL_FORMAL_ROUTING_UNVERIFIED = "ACTUAL_FORMAL_ROUTING_UNVERIFIED"
    EFFECTS_AND_COMPLETION_MAPPING_UNVERIFIED = "EFFECTS_AND_COMPLETION_MAPPING_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class FrameCallEdge:
    entry: FrameEntry
    target: CodeSourceLink
    path: tuple[CallSiteLink, ...]
    target_body: RegionID | None = None
    caller_identity_verified: bool = False
    ancestor_identity_verified: bool = False
    exit: FrameExit | None = None
    exit_verified: bool = False
    issues: tuple[CallEdgeIssue, ...] = ()
    conditions: tuple[CallEdgeCondition, ...] = tuple(CallEdgeCondition)

    def __post_init__(self):
        if self.conditions != tuple(CallEdgeCondition):
            raise ValueError("frame observations must retain all unverified runtime requirements")
        if tuple(link.site for link in self.path) != self.entry.path:
            raise ValueError("a frame edge must preserve every captured wrapper path site in order")
        if self.exit is not None and self.exit.invocation != self.entry.invocation:
            raise ValueError("frame completion belongs to another invocation")


@dataclass(frozen=True, slots=True)
class CoreCallObservation:
    invocation: InvocationKey
    anchor: CallRecordAnchor
    site_index: int
    site: CallSiteLink
    target: CodeSourceLink
    target_body: RegionID | None
    through_untracked_frames: bool
    conditions: tuple[CallEdgeCondition, ...] = tuple(CallEdgeCondition)


class ReferenceRole(str, Enum):
    PARAMETER = "PARAMETER"
    CALLER_LOCAL = "CALLER_LOCAL"
    RETURN = "RETURN"
    EXIT_LOCAL = "EXIT_LOCAL"
    CALL_RESULT = "CALL_RESULT"


@dataclass(frozen=True, slots=True)
class ReferenceOccurrence:
    anchor: CallRecordAnchor
    observed_in: InvocationKey
    owner: InvocationKey | None
    role: ReferenceRole
    name: str
    ref: str
    source_reference: SourceReference | None = None
    core_use: UseID | None = None
    core_value: ValueID | None = None


class ReferenceRouteKind(str, Enum):
    SOURCE_ARGUMENT_LOCAL = "SOURCE_ARGUMENT_LOCAL"
    SAME_FRAME_PARAMETER = "SAME_FRAME_PARAMETER"
    SOURCE_RETURN_LOCAL = "SOURCE_RETURN_LOCAL"
    CORE_CALL_RESULT = "CORE_CALL_RESULT"
    OBSERVED_CALL_RETURN = "OBSERVED_CALL_RETURN"
    RETURN_CALL = "RETURN_CALL"


@dataclass(frozen=True, slots=True)
class ReferenceIdentityRoute:
    destination: ReferenceOccurrence
    source: ReferenceOccurrence
    kind: ReferenceRouteKind
    source_reference: SourceReference | None = None
    core_use: UseID | None = None
    identity_only: bool = True
    function_environment_established: bool = False
    contents_or_effects_established: bool = False

    def __post_init__(self):
        if self.source.ref != self.destination.ref:
            raise ValueError("identity routes require identical captured reference tokens")
        if self.source.observed_in.process_id != self.destination.observed_in.process_id:
            raise ValueError("identity routes cannot transfer identities across processes")
        if self.source.anchor != self.destination.anchor and not self.source.ref.startswith("weak:"):
            raise ValueError("snapshot identity cannot cross event boundaries")
        if not self.identity_only or self.function_environment_established or self.contents_or_effects_established:
            raise ValueError("reference routes do not establish contents, effects or function environments")


@dataclass(frozen=True, slots=True)
class ReferenceIdentityGroup:
    ref: str
    occurrences: tuple[ReferenceOccurrence, ...]
    across_events: bool
    contents_established: bool = False
    function_environment_established: bool = False

    def __post_init__(self):
        if any(occurrence.ref != self.ref for occurrence in self.occurrences):
            raise ValueError("reference group contains a different identity token")
        if self.ref.startswith("snapshot:") and self.across_events:
            raise ValueError("snapshot references cannot establish identity across events")
        if self.contents_established or self.function_environment_established:
            raise ValueError("captured reference identity does not prove contents or function environment")


@dataclass(frozen=True, slots=True)
class ReferenceTrace:
    invocation: InvocationKey
    groups: tuple[ReferenceIdentityGroup, ...]
    routes: tuple[ReferenceIdentityRoute, ...] = ()
    issues: tuple[CallEdgeIssue, ...] = ()
    identity_only: bool = True
    content_or_effect_equivalence_established: bool = False


@dataclass(frozen=True, slots=True)
class CallEdgeModel:
    trace: str
    project_root: str
    budget: CallEdgeBudget
    files: tuple[CallTraceFile, ...]
    codes: tuple[CodeCapture, ...]
    edges: tuple[FrameCallEdge, ...]
    exits: tuple[FrameExit, ...]
    code_links: tuple[CodeSourceLink, ...]
    references: tuple[ReferenceOccurrence, ...]
    reference_routes: tuple[ReferenceIdentityRoute, ...]
    issues: tuple[CallEdgeIssue, ...]
    collection_metadata: tuple[dict[str, Any], ...]
    inventory_sha256: str | None

    def __post_init__(self):
        identities = [edge.entry.invocation for edge in self.edges]
        if len(set(identities)) != len(identities):
            raise ValueError("frame entries need unique process/thread/invocation identities")
        if len({link.code for link in self.code_links}) != len(self.code_links):
            raise ValueError("code source links must be unique")


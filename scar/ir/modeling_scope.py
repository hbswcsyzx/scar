"""Acceptance records over original artifacts; never another program graph.

The initial producer checks retained source/call membership. Semantic, content,
state and readiness requirements remain OPEN. Unsupported subject refinements
and semantic proof reuse are rejected rather than interpreted as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from functools import lru_cache
import hashlib
import json
import re
from types import UnionType
from typing import TypeAlias, Union, get_args, get_origin, get_type_hints

from scar.ir.program.providers import ProviderArtifact
from scar.ir.execution.ids import RunID


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    from scar.ir.record_codec import encode
    return hashlib.sha256(json.dumps(encode(value), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "invalid SHA256")


def _id(value, prefix):
    require(type(value) is str and re.fullmatch(prefix + r":[0-9a-f]{64}", value) is not None,
            "invalid " + prefix + " identity")


@lru_cache(maxsize=None)
def _hints(cls):
    return get_type_hints(cls)


def _type(value, expected):
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        return any(_type(value, kind) for kind in args)
    if origin is tuple:
        return (type(value) is tuple and (all(_type(v, args[0]) for v in value)
            if len(args) == 2 and args[1] is Ellipsis else
            len(value) == len(args) and all(_type(v, k) for v, k in zip(value, args))))
    return type(value) is expected


class _Record:
    def __post_init__(self):
        require(all(_type(getattr(self, f.name), _hints(type(self))[f.name])
                    for f in fields(self)), type(self).__name__ + " requires exact typed fields")
        self._check()

    def _check(self):
        pass


class Encoding(str, Enum):
    JSON = "JSON"
    GZIP_JSON = "GZIP_JSON"
    JSONL = "JSONL"
    GZIP_JSONL = "GZIP_JSONL"
    TEXT = "TEXT"


@dataclass(frozen=True, slots=True)
class RetainedArtifact(_Record):
    original: ProviderArtifact
    decoded_sha256: str
    decoded_bytes: int
    encoding: Encoding

    def _check(self):
        self.original.__post_init__()
        _hash(self.decoded_sha256)
        require(self.decoded_bytes >= 0, "negative decoded size")
        if self.encoding in (Encoding.JSON, Encoding.JSONL, Encoding.TEXT):
            require((self.original.sha256, self.original.size_bytes) ==
                    (self.decoded_sha256, self.decoded_bytes), "plain artifact receipts disagree")


@dataclass(frozen=True, slots=True)
class RecordLocator(_Record):
    artifact: RetainedArtifact
    pointer: str
    line: int | None = None
    line_sha256: str | None = None

    def _check(self):
        require((self.pointer == "#" or self.pointer.startswith("#/"))
                and re.search(r"~(?![01])", self.pointer) is None, "invalid fragment pointer")
        if self.artifact.encoding in (Encoding.JSONL, Encoding.GZIP_JSONL):
            require(type(self.line) is int and self.line > 0 and self.line_sha256 is not None,
                    "JSONL requires actual one-based line and SHA")
            _hash(self.line_sha256)
        else:
            require(self.line is None and self.line_sha256 is None, "non-JSONL cannot carry line fields")
        if self.artifact.encoding is Encoding.TEXT:
            require(self.pointer == "#", "text only supports the actual whole artifact")


class Domain(str, Enum):
    SOURCE_DEFINITIONS = "SOURCE_DEFINITIONS"
    SOURCE_CONSTRUCTS = "SOURCE_CONSTRUCTS"
    OBSERVED_PYTHON_CALLS = "OBSERVED_PYTHON_CALLS"
    DISPATCH_ATTEMPTS = "DISPATCH_ATTEMPTS"
    NATIVE_ACTIVITIES = "NATIVE_ACTIVITIES"
    OS_INTERFACES = "OS_INTERFACES"
    OS_RESOURCES = "OS_RESOURCES"
    PHYSICAL_OBJECTS_AND_RESOURCES = "PHYSICAL_OBJECTS_AND_RESOURCES"


class CollectionProfile(str, Enum):
    SOURCE_DEFINITIONS_V1_V2 = "SOURCE_DEFINITIONS_V1_V2"
    SOURCE_CONSTRUCTS_V1_V2 = "SOURCE_CONSTRUCTS_V1_V2"
    SOURCE_INVOCATIONS_V1_V3 = "SOURCE_INVOCATIONS_V1_V3"
    CAPTURE_MEMBERSHIP_V1 = "CAPTURE_MEMBERSHIP_V1"
    DECLARED_COLLECTION = "DECLARED_COLLECTION"


@dataclass(frozen=True, slots=True)
class CollectionLocator(_Record):
    record: RecordLocator
    profile: CollectionProfile

    def _check(self):
        require(self.record.line is None, "collection must reference actual JSON declaration")
        require(self.record.artifact.encoding in (Encoding.JSON, Encoding.GZIP_JSON),
                "collection declaration must be JSON")


class SubjectKind(str, Enum):
    SOURCE_DEFINITION = "SOURCE_DEFINITION"
    INVOCATION = "INVOCATION"
    COLLECTION = "COLLECTION"


@dataclass(frozen=True, slots=True)
class CoverageSubject(_Record):
    scope_id: str
    kind: SubjectKind
    record: RecordLocator

    def _check(self):
        _id(self.scope_id, "scope")
        require(self.record.artifact.encoding is not Encoding.TEXT,
                "program subjects need exact original JSON/JSONL records")


@dataclass(frozen=True, slots=True)
class CoverageGap(_Record):
    code: str
    requirement_key: str
    source: RecordLocator
    reason: str
    missing_count: int | None = None

    def _check(self):
        require(bool(self.code and self.requirement_key and self.reason), "gap needs precise code/key/reason")
        require(self.missing_count is None or self.missing_count >= 0, "negative missing count")


class ScopeFieldKind(str, Enum):
    ARGV = "ARGV"
    CWD = "CWD"
    CODE_VERSIONS = "CODE_VERSIONS"
    ENVIRONMENT = "ENVIRONMENT"
    CONFIGURATION = "CONFIGURATION"
    INPUT_IDENTITIES = "INPUT_IDENTITIES"
    RUN_MODE = "RUN_MODE"
    PROCESS_TREE = "PROCESS_TREE"
    CAPTURE_INTERVAL = "CAPTURE_INTERVAL"
    SOFTWARE_INTERFACES = "SOFTWARE_INTERFACES"
    HARDWARE_LAYERS = "HARDWARE_LAYERS"


@dataclass(frozen=True, slots=True)
class ScopeField(_Record):
    kind: ScopeFieldKind
    sources: tuple[RecordLocator, ...]
    gaps: tuple[CoverageGap, ...]

    def _check(self):
        require(bool(self.sources or self.gaps), "scope field cannot silently be empty")


class Coverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Observability(_Record):
    domain: Domain
    sources: tuple[RecordLocator, ...]
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]

    def _check(self):
        require(bool(self.sources or self.gaps), "observability needs source or precise gap")
        require(self.coverage is Coverage.COMPLETE or bool(self.gaps), "unknown observation needs gap")


@dataclass(frozen=True, slots=True)
class AnalysisScope(_Record):
    id: str
    revision: str
    parent: str | None
    contract: RecordLocator
    policy: RecordLocator
    source: RecordLocator
    run: RunID
    fields: tuple[ScopeField, ...]
    observability: tuple[Observability, ...]
    denominators: tuple[Domain, ...]
    policy_sources: tuple[RecordLocator, ...]

    def _check(self):
        _id(self.id, "scope"); _id(self.revision, "scope_revision")
        if self.parent is not None:
            _id(self.parent, "scope_revision")
        require(tuple(sorted(self.denominators, key=lambda x: x.value)) == tuple(sorted(Domain, key=lambda x: x.value)),
                "scope must preserve every contract domain exactly once")
        require(len(self.fields) == len(ScopeFieldKind) and {x.kind for x in self.fields} == set(ScopeFieldKind),
                "scope must preserve every original field requirement")
        require(len(self.observability) == len(Domain) and {x.domain for x in self.observability} == set(Domain),
                "scope must preserve per-domain observability")
        require(len(self.policy_sources) == 4
                and len({r.artifact.original.uri for r in self.policy_sources}) == 4
                and self.policy in self.policy_sources
                and all(r.artifact.encoding is Encoding.TEXT and r.pointer == "#" for r in self.policy_sources),
                "scope policy must bind the four distinct producer source artifacts")
        require(self.revision == scope_revision_id(self), "scope revision does not match all typed scope fields")


def scope_revision_id(scope):
    """Hash every typed scope field except the revision itself."""
    return "scope_revision:" + digest({f.name: getattr(scope, f.name)
                                      for f in fields(scope) if f.name != "revision"})


class Expansion(str, Enum):
    SOURCE_BODY = "SOURCE_BODY"
    PROVIDER_GRAPH = "PROVIDER_GRAPH"
    PROTOCOL_INTERFACE = "PROTOCOL_INTERFACE"
    PHYSICAL_DETAIL = "PHYSICAL_DETAIL"


class RelationKind(str, Enum):
    SOURCE_BINDING = "SOURCE_BINDING"
    ORDERED_INPUTS = "ORDERED_INPUTS"
    ORDERED_RESULTS = "ORDERED_RESULTS"
    STATE_PRE_POST = "STATE_PRE_POST"
    CONTROL_COMPLETION = "CONTROL_COMPLETION"
    CALL_ACTUAL_FORMAL = "CALL_ACTUAL_FORMAL"
    CALL_RETURN_EXCEPTION = "CALL_RETURN_EXCEPTION"
    ENVIRONMENT_IDENTITY = "ENVIRONMENT_IDENTITY"
    OWNER_SELECTOR = "OWNER_SELECTOR"
    ALIAS_ESCAPE = "ALIAS_ESCAPE"
    VALUE_PROVENANCE = "VALUE_PROVENANCE"
    LOGICAL_MATERIALIZATION = "LOGICAL_MATERIALIZATION"
    RESOURCE_BINDING = "RESOURCE_BINDING"
    RESOURCE_WORK = "RESOURCE_WORK"
    READY_ORDER = "READY_ORDER"
    LIFETIME = "LIFETIME"


@dataclass(frozen=True, slots=True)
class RelationRequirement(_Record):
    key: str
    kind: RelationKind
    source: RecordLocator

    def _check(self):
        require(self.key == self.kind.value, "initial policy keys are exact relation names")


@dataclass(frozen=True, slots=True)
class ObligationSource(_Record):
    rule: RecordLocator
    origin: RecordLocator


@dataclass(frozen=True, slots=True)
class CoverageObligation(_Record):
    id: str
    scope_revision: str
    rule_key: str
    source: ObligationSource
    subject: CoverageSubject
    required_relations: tuple[RelationRequirement, ...]
    required_expansion: Expansion
    mandatory: bool

    def _check(self):
        _id(self.id, "obligation"); _id(self.scope_revision, "scope_revision")
        require(bool(self.rule_key and self.required_relations), "obligation needs rule and requirements")
        require(len({r.key for r in self.required_relations}) == len(self.required_relations), "duplicate relation")
        require(self.id == obligation_id(self.subject, self.rule_key), "obligation identity mismatch")


def obligation_id(subject, rule_key):
    # Scope ID and actual qualified original record are already in subject.
    return "obligation:" + digest((subject_key(subject), rule_key))


def locator_key(locator):
    """Original namespace and decoded record, never content equality alone.

    No retention relocation mapping: original.uri is the fixed original
    logical path. Equal bytes at distinct original URIs remain distinct.
    """
    return (locator.artifact.original.uri, locator.artifact.original.schema, locator.artifact.decoded_sha256,
            locator.artifact.decoded_bytes, locator.pointer, locator.line, locator.line_sha256)


def subject_key(subject):
    return subject.scope_id, subject.kind, locator_key(subject.record)


@dataclass(frozen=True, slots=True)
class EnumerationCursor(_Record):
    collection: CollectionLocator
    next_partition: int
    next_ordinal: int
    reason: str

    def _check(self):
        require(self.next_partition >= 0 and self.next_ordinal >= 0 and bool(self.reason), "invalid cursor")


class Enumeration(str, Enum):
    DECLARED = "DECLARED"
    PARTIAL = "PARTIAL"
    ENUMERATED = "ENUMERATED"


@dataclass(frozen=True, slots=True)
class DenominatorInventory(_Record):
    id: str
    scope_revision: str
    domain: Domain
    collection: CollectionLocator
    source: RecordLocator
    declared_count: int | None
    enumerated_count: int
    membership_sha256: str | None
    enumeration: Enumeration
    observation_coverage: Coverage
    cursor: EnumerationCursor | None
    gaps: tuple[CoverageGap, ...]

    def _check(self):
        _id(self.id, "denominator"); _id(self.scope_revision, "scope_revision")
        require(self.enumerated_count >= 0 and (self.declared_count is None or self.declared_count >= 0), "negative count")
        if self.membership_sha256 is not None:
            _hash(self.membership_sha256)
        if self.enumeration is Enumeration.ENUMERATED:
            require(self.cursor is None and self.declared_count == self.enumerated_count
                    and self.membership_sha256 is not None, "enumerated requires exact full membership/count")
        else:
            require(self.cursor is not None and bool(self.gaps), "unfinished denominator requires cursor and debt")
        require(self.observation_coverage is Coverage.COMPLETE or bool(self.gaps), "observation uncertainty needs debt")


@dataclass(frozen=True, slots=True)
class DenominatorMember(_Record):
    denominator: str
    subject: CoverageSubject
    obligation: str
    source: RecordLocator

    def _check(self):
        _id(self.denominator, "denominator"); _id(self.obligation, "obligation")


class Axis(str, Enum):
    STRUCTURAL_ATTRIBUTION = "STRUCTURAL_ATTRIBUTION"
    DEPENDENCY_CONNECTION = "DEPENDENCY_CONNECTION"
    INTERNAL_EXPANSION = "INTERNAL_EXPANSION"
    RUNTIME_EVIDENCE = "RUNTIME_EVIDENCE"


class RequirementStatus(str, Enum):
    SATISFIED = "SATISFIED"
    OPEN = "OPEN"
    CONTRADICTED = "CONTRADICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class RequirementResult(_Record):
    key: str
    status: RequirementStatus
    evidence: tuple[RecordLocator, ...]
    conditions: tuple[RecordLocator, ...]
    gaps: tuple[CoverageGap, ...]

    def _check(self):
        require(bool(self.key), "result key required")
        if self.status in (RequirementStatus.OPEN, RequirementStatus.CONTRADICTED):
            require(bool(self.gaps), "unmet requirement needs specific gap")
        else:
            require(bool(self.evidence) and not self.gaps, "satisfied/excluded result needs evidence and no gaps")


@dataclass(frozen=True, slots=True)
class AxisResult(_Record):
    axis: Axis
    results: tuple[RequirementResult, ...]

    def _check(self):
        require(bool(self.results) and len({r.key for r in self.results}) == len(self.results), "invalid axis result keys")


@dataclass(frozen=True, slots=True)
class CoverageAssessment(_Record):
    obligation: str
    scope_revision: str
    axes: tuple[AxisResult, ...]
    checker: ProviderArtifact
    source: RecordLocator
    retained_gaps: tuple[CoverageGap, ...] = ()

    def _check(self):
        _id(self.obligation, "obligation"); _id(self.scope_revision, "scope_revision")
        require(len(self.axes) == 4 and {x.axis for x in self.axes} == set(Axis), "four independent axes required")


@dataclass(frozen=True, slots=True)
class LedgerEntry(_Record):
    obligation: CoverageObligation
    member: DenominatorMember | None
    assessment: CoverageAssessment

    def _check(self):
        require(self.assessment.obligation == self.obligation.id and
                self.assessment.scope_revision == self.obligation.scope_revision, "assessment scope/subject mismatch")
        if self.member is not None:
            require(self.member.subject == self.obligation.subject and self.member.obligation == self.obligation.id,
                    "member/obligation mismatch")
        expected = {
            Axis.STRUCTURAL_ATTRIBUTION: {"ORIGINAL_RECORD_MEMBERSHIP"},
            Axis.DEPENDENCY_CONNECTION: {r.key for r in self.obligation.required_relations},
            Axis.INTERNAL_EXPANSION: {self.obligation.required_expansion.value},
            Axis.RUNTIME_EVIDENCE: {"ORIGINAL_SEMANTIC_EVIDENCE"},
        }
        for axis in self.assessment.axes:
            require({r.key for r in axis.results} == expected[axis.axis], "assessment omitted/added required key")
            if axis.axis is not Axis.STRUCTURAL_ATTRIBUTION:
                require(all(r.status is RequirementStatus.OPEN for r in axis.results),
                        "semantic acceptance reuse is not implemented in this initial policy")


LedgerRow: TypeAlias = LedgerEntry | DenominatorInventory


__all__ = [name for name, value in tuple(globals().items())
           if isinstance(value, type) and value.__module__ == __name__ and not name.startswith("_")] + [
    "LedgerRow", "digest", "obligation_id", "locator_key", "subject_key", "scope_revision_id", "require"]

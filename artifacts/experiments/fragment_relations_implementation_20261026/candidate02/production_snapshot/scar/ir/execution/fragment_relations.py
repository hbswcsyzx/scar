"""Qualified cross-fragment associations, never replacement program facts.

Static definitions and dynamic occurrences have separate endpoints.  Every
endpoint keeps its original artifact namespace; constructors perform no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re

from scar.ir.program.call_edges import CapturedCode, InvocationKey
from scar.ir.program.ids import LocationID, OperationID, RegionID, UseID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.record_codec import encode
from scar.ir.v2.ids import OperationInstanceID
from .ids import OperationOccurrenceID, ProcessInstanceID, RunID, WorkTicketID
from .model import LegacyOperationRef, OccurrenceEvidenceBinding


def need(condition, message):
    if not condition:
        raise ValueError("fragment relation: " + message)


def exact(value, kind, label):
    need(type(value) is kind, label + " requires exact " + kind.__name__)
    if hasattr(value, "__post_init__"):
        value.__post_init__()


def canonical(value):
    import json
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def stable_key(value):
    """Namespace, version and typed IDs participate; assessments do not."""
    return hashlib.sha256(canonical(encode(value))).hexdigest()


class Encoding(str, Enum):
    JSON = "JSON"
    JSONL = "JSONL"
    GZIP_JSON = "GZIP_JSON"
    GZIP_JSONL = "GZIP_JSONL"


@dataclass(frozen=True, slots=True)
class FragmentLocator:
    artifact: ProviderArtifact
    decoded_sha256: str
    decoded_bytes: int
    encoding: Encoding
    line: int | None
    pointer: str
    declaration: ProviderFactReference

    def __post_init__(self):
        exact(self.artifact, ProviderArtifact, "original artifact")
        exact(self.declaration, ProviderFactReference, "original declaration")
        exact(self.encoding, Encoding, "encoding")
        need(type(self.decoded_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", self.decoded_sha256), "decoded SHA")
        need(type(self.decoded_bytes) is int and self.decoded_bytes > 0, "decoded bytes")
        lines = self.encoding in (Encoding.JSONL, Encoding.GZIP_JSONL)
        need((type(self.line) is int and self.line > 0) if lines else self.line is None, "line/encoding mismatch")
        need(type(self.pointer) is str and (self.pointer == "#" or self.pointer.startswith("#/"))
             and re.search(r"~(?![01])", self.pointer) is None, "record pointer")
        if self.encoding in (Encoding.JSON, Encoding.JSONL):
            need((self.artifact.sha256, self.artifact.size_bytes) == (self.decoded_sha256, self.decoded_bytes), "plain stored/decoded receipt differs")


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    run: RunID
    process: ProcessInstanceID
    coordinates: ProviderArtifact

    def __post_init__(self):
        exact(self.run, RunID, "Run")
        exact(self.process, ProcessInstanceID, "process incarnation")
        exact(self.coordinates, ProviderArtifact, "coordinates")
        need(self.coordinates.schema == "scar.capture-coordinates", "coordinate schema")


@dataclass(frozen=True, slots=True)
class QualifiedOccurrenceRef:
    """The original source/native public endpoint, re-exported there."""
    execution: ProviderArtifact
    occurrence: OperationOccurrenceID
    binding: OccurrenceEvidenceBinding

    def __post_init__(self):
        need(type(self.execution) is ProviderArtifact and type(self.occurrence) is OperationOccurrenceID
             and type(self.binding) is OccurrenceEvidenceBinding and self.binding.operation == self.occurrence,
             "invalid qualified occurrence/binding")


@dataclass(frozen=True, slots=True)
class WorkTicketRef:
    locator: FragmentLocator
    ticket: WorkTicketID

    def __post_init__(self):
        exact(self.locator, FragmentLocator, "work record")
        exact(self.ticket, WorkTicketID, "work ticket")
        need(self.locator.pointer.endswith("/submission"), "work endpoint must locate its original submission")


@dataclass(frozen=True, slots=True)
class EvidenceInstanceRef:
    locator: FragmentLocator
    instance: OperationInstanceID

    def __post_init__(self):
        exact(self.locator, FragmentLocator, "EEG instance locator")
        exact(self.instance, OperationInstanceID, "EEG instance")


class HostRelationKind(str, Enum):
    SUBMITTED_BY_RUNTIME = "SUBMITTED_BY_RUNTIME"
    PROVIDER_SCOPE_CONTEXT = "PROVIDER_SCOPE_CONTEXT"


@dataclass(frozen=True, slots=True)
class EvidenceEdgeRef:
    locator: FragmentLocator
    edge_id: str
    relation: str
    source: OperationInstanceID
    target: OperationInstanceID

    def __post_init__(self):
        exact(self.locator, FragmentLocator, "EEG edge locator")
        exact(self.source, OperationInstanceID, "EEG edge source")
        exact(self.target, OperationInstanceID, "EEG edge target")
        need(type(self.edge_id) is str and bool(self.edge_id), "original EEG edge ID")
        need(self.relation in ("submits_work", "provider_scope_association"), "unsupported provider edge")


@dataclass(frozen=True, slots=True)
class WorkActivityProjectionLink:
    scope: RuntimeScope
    work: WorkTicketRef
    binding: FragmentLocator
    projection: LegacyOperationRef
    original: EvidenceInstanceRef
    receipt: FragmentLocator

    def __post_init__(self):
        for field, kind in (("scope", RuntimeScope), ("work", WorkTicketRef), ("binding", FragmentLocator),
                            ("projection", LegacyOperationRef), ("original", EvidenceInstanceRef), ("receipt", FragmentLocator)):
            exact(getattr(self, field), kind, field)
        need(self.projection.instance == self.original.instance, "projection changes original entity ID")
        need(self.binding.artifact == self.work.locator.artifact and self.binding.line == self.work.locator.line
             and self.binding.pointer == "#/binding", "binding is not in the original work row")

    @property
    def id(self):
        return "fragment_relation:" + stable_key(("WORK_ACTIVITY_PROJECTION", self.scope, self.work, self.original, self.receipt))


@dataclass(frozen=True, slots=True)
class WorkHostRelation:
    work: WorkTicketRef
    kind: HostRelationKind
    host: EvidenceInstanceRef
    activity: EvidenceInstanceRef
    evidence_path: tuple[EvidenceEdgeRef, ...]
    native: QualifiedOccurrenceRef | None

    def __post_init__(self):
        exact(self.work, WorkTicketRef, "work ticket")
        exact(self.kind, HostRelationKind, "host relation kind")
        exact(self.host, EvidenceInstanceRef, "host")
        exact(self.activity, EvidenceInstanceRef, "activity")
        need(type(self.evidence_path) is tuple and 1 <= len(self.evidence_path) <= 2, "bounded original edge path required")
        for edge in self.evidence_path:
            exact(edge, EvidenceEdgeRef, "original edge")
        edges = self.evidence_path
        need(edges[0].source == self.host.instance and edges[-1].target == self.activity.instance
             and all(a.target == b.source for a, b in zip(edges, edges[1:])), "edge path direction/endpoints differ")
        relations = tuple(e.relation for e in edges)
        expected = (("submits_work",),) if self.kind is HostRelationKind.SUBMITTED_BY_RUNTIME else (
            ("provider_scope_association",), ("provider_scope_association", "submits_work"))
        need(relations in expected, "provider scope and submission relations are not interchangeable")
        if self.native is not None:
            exact(self.native, QualifiedOccurrenceRef, "native occurrence")
            need(self.native.binding.legacy.instance == self.host.instance, "native binding changes host identity")

    @property
    def id(self):
        return "fragment_relation:" + stable_key((self.kind, self.work, self.host, self.activity, self.evidence_path, self.native))


@dataclass(frozen=True, slots=True)
class InvocationRef:
    scope: RuntimeScope
    invocation: InvocationKey
    fact: ProviderFactReference

    def __post_init__(self):
        exact(self.scope, RuntimeScope, "invocation scope")
        exact(self.invocation, InvocationKey, "invocation")
        exact(self.fact, ProviderFactReference, "original invocation fact")


@dataclass(frozen=True, slots=True)
class StaticEntityRef:
    """Existing static member; no dynamic occurrence or activity is implied."""
    graph: SourceArtifactLocator | FragmentLocator
    identity: RegionID | OperationID | UseID | LocationID
    definition: SourceDefinitionReference
    namespace: ProviderFactReference | None = None

    def __post_init__(self):
        need(type(self.graph) in (SourceArtifactLocator, FragmentLocator), "exact original static graph locator")
        self.graph.__post_init__()
        exact(self.definition, SourceDefinitionReference, "static definition")
        need(type(self.identity) in (RegionID, OperationID, UseID, LocationID), "unsupported static member")
        self.identity.__post_init__()
        if self.namespace is not None:
            exact(self.namespace, ProviderFactReference, "original namespace field")


@dataclass(frozen=True, slots=True)
class InvocationStaticBinding:
    invocation: InvocationRef
    captured_code: CapturedCode
    definition: SourceDefinitionReference
    code_capture: ProviderFactReference
    code_source_link: SourceArtifactLocator | FragmentLocator
    witness: tuple[SourceArtifactLocator | FragmentLocator, ...]
    body: StaticEntityRef | None

    def __post_init__(self):
        for name, kind in (("invocation", InvocationRef), ("captured_code", CapturedCode),
                           ("definition", SourceDefinitionReference), ("code_capture", ProviderFactReference)):
            exact(getattr(self, name), kind, name)
        need(type(self.code_source_link) in (SourceArtifactLocator, FragmentLocator), "exact original code/source locator")
        self.code_source_link.__post_init__()
        need(type(self.witness) is tuple and bool(self.witness), "exact code/source witness locators required")
        for item in self.witness:
            need(type(item) in (SourceArtifactLocator, FragmentLocator), "exact witness locator")
            item.__post_init__()
        if self.body is not None:
            exact(self.body, StaticEntityRef, "static body")
            need(self.body.definition == self.definition, "body belongs to another definition version")

    @property
    def id(self):
        return "fragment_relation:" + stable_key(("INVOCATION_STATIC", self.invocation,
            self.captured_code.key, self.definition, self.code_source_link))


@dataclass(frozen=True, slots=True)
class NativeSourceContextRelation:
    native: QualifiedOccurrenceRef
    invocation: InvocationRef
    association: FragmentLocator
    source_binding: ProviderFactReference | None
    definition: SourceDefinitionReference | None
    kind: str = "RETAINED_SOURCE_CONTEXT"

    def __post_init__(self):
        exact(self.native, QualifiedOccurrenceRef, "native occurrence")
        exact(self.invocation, InvocationRef, "invocation")
        exact(self.association, FragmentLocator, "retained source association")
        need(self.kind == "RETAINED_SOURCE_CONTEXT", "retained context cannot become direct call")
        if self.source_binding is not None:
            exact(self.source_binding, ProviderFactReference, "source binding fact")
        if self.definition is not None:
            exact(self.definition, SourceDefinitionReference, "source definition")

    @property
    def id(self):
        return "fragment_relation:" + stable_key((self.kind, self.native, self.invocation, self.association))


@dataclass(frozen=True, slots=True)
class RelationGap:
    code: str
    source: ProviderFactReference
    detail: str
    candidates: int | None

    def __post_init__(self):
        exact(self.source, ProviderFactReference, "gap provenance")
        need(type(self.code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]+", self.code), "gap code")
        need(type(self.detail) is str and bool(self.detail), "gap detail")
        need(self.candidates is None or type(self.candidates) is int and self.candidates >= 0, "candidate count")


@dataclass(frozen=True, slots=True)
class WorkRelations:
    projection: WorkActivityProjectionLink
    hosts: tuple[WorkHostRelation, ...]
    source_contexts: tuple[NativeSourceContextRelation, ...]
    static_bindings: tuple[InvocationStaticBinding, ...]
    gaps: tuple[RelationGap, ...]

    def __post_init__(self):
        exact(self.projection, WorkActivityProjectionLink, "work projection")
        for name, kind in (("hosts", WorkHostRelation), ("source_contexts", NativeSourceContextRelation),
                           ("static_bindings", InvocationStaticBinding), ("gaps", RelationGap)):
            rows = getattr(self, name)
            need(type(rows) is tuple, name + " must be a tuple")
            for row in rows:
                exact(row, kind, name)
        need(bool(self.hosts) or any(g.code == "HOST_RELATION_UNRESOLVED" for g in self.gaps), "missing host must remain explicit debt")
        native = {stable_key(h.native) for h in self.hosts if h.native is not None}
        need(all(h.work == self.projection.work and h.activity == self.projection.original for h in self.hosts), "host relation belongs to another work/activity")
        for row in self.source_contexts:
            need(stable_key(row.native) in native and row.invocation.scope == self.projection.scope, "context/native/Run scope differs")
        for row in self.static_bindings:
            need(any(row.invocation == context.invocation and row.definition == context.definition
                     for context in self.source_contexts), "static binding is not from the retained invocation")

    @property
    def id(self):
        return "work_relation:" + stable_key((self.projection.scope, self.projection.work))


RECORD_TYPES = (FragmentLocator, RuntimeScope, QualifiedOccurrenceRef, WorkTicketRef,
    EvidenceInstanceRef, EvidenceEdgeRef, WorkActivityProjectionLink, WorkHostRelation,
    InvocationRef, StaticEntityRef, InvocationStaticBinding, NativeSourceContextRelation,
    RelationGap, WorkRelations)

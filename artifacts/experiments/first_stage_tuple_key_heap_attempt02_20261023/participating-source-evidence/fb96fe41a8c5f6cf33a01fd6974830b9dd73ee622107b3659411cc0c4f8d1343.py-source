"""Strict provider declarations and references into the canonical program graph.

These records preserve provenance and provider-scoped claims, not runtime/source
identity or transformation authority. A coverage declaration is not SCAR proof;
canonical def/use, state and call interfaces remain the sole dependency graph.
Artifact availability, graph ownership and mapped value variants require separate
validation. No constructor reads an artifact or executes a provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from scar.ir.program.ids import OperationID, ProviderID, RegionID, UseID, ValueID
from scar.ir.v2.common import Completeness, SourceVersion


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _text(value, name):
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _nonnegative(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _records(value, expected, name):
    _exact(value, tuple, name)
    for item in value:
        _record(item, expected, name + " item")


@dataclass(frozen=True, slots=True)
class ProviderArtifact:
    uri: str
    sha256: str
    size_bytes: int
    schema: str

    def __post_init__(self):
        _text(self.uri, "provider artifact URI")
        _exact(self.sha256, str, "provider artifact SHA256")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("provider artifact SHA256 must be 64 lowercase hexadecimal characters")
        _nonnegative(self.size_bytes, "provider artifact byte size")
        _text(self.schema, "provider artifact schema")


@dataclass(frozen=True, slots=True)
class ProviderFactReference:
    artifact: ProviderArtifact
    locator: str

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "provider fact artifact")
        _text(self.locator, "provider fact locator")


class ProviderArtifactKind(str, Enum):
    DEFINITION_GRAPH = "DEFINITION_GRAPH"
    EXECUTION_EVIDENCE = "EXECUTION_EVIDENCE"


class ProviderCaptureMode(str, Enum):
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    SYMBOLIC_CAPTURE = "SYMBOLIC_CAPTURE"
    REAL_EXECUTION = "REAL_EXECUTION"
    REPLAY = "REPLAY"


@dataclass(frozen=True, slots=True)
class ProviderRunScope:
    run: str
    process_id: int
    window: str
    clock: str
    thread_id: int | None = None

    def __post_init__(self):
        _text(self.run, "provider run")
        _nonnegative(self.process_id, "provider process id")
        _text(self.window, "provider window")
        _text(self.clock, "provider clock")
        if self.thread_id is not None:
            _nonnegative(self.thread_id, "provider thread id")


@dataclass(frozen=True, slots=True)
class ProviderStage:
    name: str
    evidence: ProviderFactReference

    def __post_init__(self):
        _text(self.name, "provider stage name")
        _record(self.evidence, ProviderFactReference, "provider stage evidence")


class ProviderConditionDomain(str, Enum):
    SHAPE = "SHAPE"
    VALUE = "VALUE"
    MODE = "MODE"
    ENVIRONMENT = "ENVIRONMENT"
    SCHEMA = "SCHEMA"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class ProviderCondition:
    domain: ProviderConditionDomain
    evidence: ProviderFactReference

    def __post_init__(self):
        _exact(self.domain, ProviderConditionDomain, "provider condition domain")
        _record(self.evidence, ProviderFactReference, "provider condition evidence")


class ProviderCoverageDomain(str, Enum):
    SOURCE = "SOURCE"
    STRUCTURE = "STRUCTURE"
    DATAFLOW = "DATAFLOW"
    STATE_EFFECTS = "STATE_EFFECTS"
    ALIAS_IDENTITY = "ALIAS_IDENTITY"
    CONTROL_COMPLETION = "CONTROL_COMPLETION"
    RESOURCE_ORDERING = "RESOURCE_ORDERING"
    CONDITIONS = "CONDITIONS"


@dataclass(frozen=True, slots=True)
class ProviderCoverage:
    """A provider-scoped coverage declaration, never a legality certificate."""

    domain: ProviderCoverageDomain
    completeness: Completeness
    evidence: ProviderFactReference | None
    reason: str

    def __post_init__(self):
        _exact(self.domain, ProviderCoverageDomain, "provider coverage domain")
        _exact(self.completeness, Completeness, "provider coverage completeness")
        if self.evidence is not None:
            _record(self.evidence, ProviderFactReference, "provider coverage evidence")
        _text(self.reason, "provider coverage reason")
        if self.completeness is not Completeness.UNKNOWN and self.evidence is None:
            raise ValueError("non-UNKNOWN provider coverage requires evidence")


class ProviderCollectionDomain(str, Enum):
    CAPTURE_EFFECTS = "CAPTURE_EFFECTS"
    COST = "COST"


@dataclass(frozen=True, slots=True)
class ProviderCollectionObservation:
    """Missing evidence denotes a named gap, not zero cost or no effects."""

    domain: ProviderCollectionDomain
    evidence: ProviderFactReference | None
    reason: str

    def __post_init__(self):
        _exact(self.domain, ProviderCollectionDomain, "provider collection domain")
        if self.evidence is not None:
            _record(self.evidence, ProviderFactReference, "provider collection evidence")
        _text(self.reason, "provider collection reason")


@dataclass(frozen=True, slots=True)
class ProviderEnvelope:
    id: ProviderID
    provider: str
    provider_version: str | None
    source_revision: str | None
    artifact: ProviderArtifact
    kind: ProviderArtifactKind
    capture_mode: ProviderCaptureMode
    capture_scope: ProviderRunScope | None
    sources: tuple[SourceVersion, ...]
    stages: tuple[ProviderStage, ...]
    conditions: tuple[ProviderCondition, ...]
    coverage: tuple[ProviderCoverage, ...]
    collection: tuple[ProviderCollectionObservation, ...]

    def __post_init__(self):
        _exact(self.id, ProviderID, "provider id")
        _text(self.provider, "provider name")
        for name in ("provider_version", "source_revision"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        if self.provider_version is None and self.source_revision is None:
            raise ValueError("provider needs a version or source revision")
        _record(self.artifact, ProviderArtifact, "provider artifact")
        _exact(self.kind, ProviderArtifactKind, "provider artifact kind")
        _exact(self.capture_mode, ProviderCaptureMode, "provider capture mode")
        if self.capture_scope is not None:
            _record(self.capture_scope, ProviderRunScope, "provider capture scope")
        if self.capture_mode is ProviderCaptureMode.STATIC_ANALYSIS and self.capture_scope is not None:
            raise ValueError("static analysis must not have a capture scope")
        execution_modes = (ProviderCaptureMode.REAL_EXECUTION, ProviderCaptureMode.REPLAY)
        if self.kind is ProviderArtifactKind.EXECUTION_EVIDENCE and self.capture_mode not in execution_modes:
            raise ValueError("execution evidence requires REAL_EXECUTION or REPLAY capture mode")
        if (self.kind is ProviderArtifactKind.EXECUTION_EVIDENCE or self.capture_mode in execution_modes) and self.capture_scope is None:
            raise ValueError("execution/replay capture requires a run scope")
        _exact(self.sources, tuple, "provider sources")
        for source in self.sources:
            _exact(source, SourceVersion, "provider source version")
            _text(source.path, "provider source path")
            _exact(source.fingerprint, str, "provider source fingerprint")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", source.fingerprint) is None:
                raise ValueError("provider source needs a canonical sha256 fingerprint")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("provider sources must not repeat")
        _records(self.stages, ProviderStage, "provider stages")
        if not self.stages:
            raise ValueError("provider needs nonempty stages")
        _records(self.conditions, ProviderCondition, "provider conditions")
        _records(self.coverage, ProviderCoverage, "provider coverage")
        if (len(self.coverage) != len(ProviderCoverageDomain)
                or {item.domain for item in self.coverage} != set(ProviderCoverageDomain)):
            raise ValueError("provider coverage needs exactly one record for every domain")
        _records(self.collection, ProviderCollectionObservation, "provider collection")
        if (len(self.collection) != len(ProviderCollectionDomain)
                or {item.domain for item in self.collection} != set(ProviderCollectionDomain)):
            raise ValueError("provider collection needs exactly one record for every domain")


class ProviderRegionRelation(str, Enum):
    DEFINES_REPRESENTATION = "DEFINES_REPRESENTATION"
    OBSERVATION_SCOPE = "OBSERVATION_SCOPE"


@dataclass(frozen=True, slots=True)
class ProviderRegion:
    provider: ProviderID
    external_region: str
    region: RegionID
    relation: ProviderRegionRelation

    def __post_init__(self):
        _exact(self.provider, ProviderID, "provider region provider id")
        _text(self.external_region, "provider external region")
        _exact(self.region, RegionID, "provider canonical region")
        _exact(self.relation, ProviderRegionRelation, "provider region relation")


@dataclass(frozen=True, slots=True)
class ProviderPathIndex:
    index: int

    def __post_init__(self):
        _nonnegative(self.index, "provider path index")


@dataclass(frozen=True, slots=True)
class ProviderPathKey:
    key: str

    def __post_init__(self):
        _text(self.key, "provider path key")


class ProviderElementKind(str, Enum):
    OPERATION = "OPERATION"
    DATA_VALUE = "DATA_VALUE"
    REFERENCE_VALUE = "REFERENCE_VALUE"
    STATE_VALUE = "STATE_VALUE"
    BINDING_VALUE = "BINDING_VALUE"
    PROTOCOL_VALUE = "PROTOCOL_VALUE"
    USE = "USE"


@dataclass(frozen=True, slots=True)
class ProviderElement:
    kind: ProviderElementKind
    key: str
    path: tuple[ProviderPathIndex | ProviderPathKey, ...] = ()

    def __post_init__(self):
        _exact(self.kind, ProviderElementKind, "provider element kind")
        _text(self.key, "provider element key")
        _exact(self.path, tuple, "provider element path")
        for item in self.path:
            if type(item) not in (ProviderPathIndex, ProviderPathKey):
                raise TypeError("provider path needs exact ProviderPathIndex or ProviderPathKey items")
            item.__post_init__()
        if self.kind is ProviderElementKind.OPERATION and self.path:
            raise ValueError("provider operation element path must be empty")
        if self.kind is ProviderElementKind.USE and not self.path:
            raise ValueError("provider use element needs a nonempty operand path")


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """One provenance mapping; actual dependency endpoints stay in the core."""

    provider: ProviderID
    region: RegionID
    external: ProviderElement
    target: OperationID | ValueID | UseID

    def __post_init__(self):
        _exact(self.provider, ProviderID, "provider binding provider id")
        _exact(self.region, RegionID, "provider binding region")
        _record(self.external, ProviderElement, "provider binding external element")
        expected = {ProviderElementKind.OPERATION: OperationID,
                    ProviderElementKind.USE: UseID}.get(self.external.kind, ValueID)
        _exact(self.target, expected, "provider binding target")


__all__ = [
    "ProviderArtifact", "ProviderArtifactKind", "ProviderBinding", "ProviderCaptureMode",
    "ProviderCollectionDomain", "ProviderCollectionObservation", "ProviderCondition",
    "ProviderConditionDomain", "ProviderCoverage", "ProviderCoverageDomain", "ProviderElement",
    "ProviderElementKind", "ProviderEnvelope", "ProviderFactReference", "ProviderPathIndex",
    "ProviderPathKey", "ProviderRegion", "ProviderRegionRelation", "ProviderRunScope", "ProviderStage",
]

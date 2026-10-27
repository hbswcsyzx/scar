"""Typed effect, contract, resource and measurement records for IR v2."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .common import Completeness, EvidenceClaim, ProofStatus
from .ids import (
    ContractID,
    EffectSummaryID,
    MeasurementID,
    ResourceID,
    ValueSlotID,
)


class EffectPresence(str, Enum):
    NONE = "NONE"
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"


class EffectTargetKind(str, Enum):
    VALUE_SLOT = "value_slot"
    VALUE_VERSION = "value_version"
    OBJECT = "object"
    STORAGE = "storage"
    RNG = "rng"
    ENVIRONMENT = "environment"
    FILE = "file"
    LOG = "log"
    EXTERNAL = "external"
    ORDERING = "ordering"
    OPAQUE = "opaque"


@dataclass(frozen=True, slots=True)
class EffectTarget:
    kind: EffectTargetKind
    reference: str

    def __post_init__(self) -> None:
        if not self.reference:
            raise ValueError("effect target reference is required")

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "reference": self.reference}


@dataclass(frozen=True, slots=True)
class EffectSet:
    members: tuple[EffectTarget, ...] = ()
    completeness: Completeness = Completeness.UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return {
            "members": [item.as_dict() for item in sorted(
                self.members, key=lambda item: (item.kind.value, item.reference))],
            "completeness": self.completeness.value,
        }


@dataclass(slots=True)
class EffectSummary:
    id: EffectSummaryID
    reads: EffectSet = field(default_factory=EffectSet)
    writes: EffectSet = field(default_factory=EffectSet)
    allocates: EffectSet = field(default_factory=EffectSet)
    frees: EffectSet = field(default_factory=EffectSet)
    aliases: EffectSet = field(default_factory=EffectSet)
    escapes: EffectSet = field(default_factory=EffectSet)
    rng: EffectPresence = EffectPresence.UNKNOWN
    may_raise: EffectPresence = EffectPresence.UNKNOWN
    external: EffectPresence = EffectPresence.UNKNOWN
    ordering: EffectPresence = EffectPresence.UNKNOWN
    evidence: tuple[EvidenceClaim, ...] = ()

    @property
    def is_complete(self) -> bool:
        collections = (
            self.reads, self.writes, self.allocates, self.frees,
            self.aliases, self.escapes,
        )
        scalars = (self.rng, self.may_raise, self.external, self.ordering)
        return (
            all(item.completeness is Completeness.COMPLETE for item in collections)
            and all(item is not EffectPresence.UNKNOWN for item in scalars)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "reads": self.reads.as_dict(),
            "writes": self.writes.as_dict(),
            "allocates": self.allocates.as_dict(),
            "frees": self.frees.as_dict(),
            "aliases": self.aliases.as_dict(),
            "escapes": self.escapes.as_dict(),
            "rng": self.rng.value,
            "may_raise": self.may_raise.value,
            "external": self.external.value,
            "ordering": self.ordering.value,
            "evidence": [item.as_dict() for item in self.evidence],
        }


class ContractFacet(str, Enum):
    OUTPUT = "output"
    STATE = "state"
    RNG = "rng"
    EXCEPTION = "exception"
    EXTERNAL = "external"
    ORDERING = "ordering"
    NUMERICAL = "numerical"
    RESOURCE = "resource"


@dataclass(frozen=True, slots=True)
class FacetRequirement:
    facet: ContractFacet
    required: bool
    tolerance: dict[str, float] = field(default_factory=dict)
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "facet": self.facet.value,
            "required": self.required,
            "tolerance": dict(sorted(self.tolerance.items())),
            "description": self.description,
        }


@dataclass(slots=True)
class ContractDefinition:
    id: ContractID
    name: str
    required_outputs: tuple[ValueSlotID, ...] = ()
    facets: tuple[FacetRequirement, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence: tuple[EvidenceClaim, ...] = ()

    def __post_init__(self) -> None:
        duplicates = [facet.facet for facet in self.facets]
        if len(duplicates) != len(set(duplicates)):
            raise ValueError("contract facets must be unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "name": self.name,
            "required_outputs": [item.as_dict() for item in sorted(
                self.required_outputs, key=lambda item: item.wire)],
            "facets": [item.as_dict() for item in sorted(
                self.facets, key=lambda item: item.facet.value)],
            "assumptions": sorted(self.assumptions),
            "evidence": [item.as_dict() for item in self.evidence],
        }


class ResourceKind(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    MEMORY = "memory"
    STORAGE = "storage"
    STREAM = "stream"
    THREAD = "thread"
    PROCESS = "process"
    FILE = "file"
    DEVICE = "device"
    OTHER = "other"


@dataclass(slots=True)
class ResourceRequirement:
    id: ResourceID
    kind: ResourceKind
    selector: str
    capacity: dict[str, float] = field(default_factory=dict)
    exclusive: bool = False
    evidence: tuple[EvidenceClaim, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "kind": self.kind.value,
            "selector": self.selector,
            "capacity": dict(sorted(self.capacity.items())),
            "exclusive": self.exclusive,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class MeasurementRecord:
    id: MeasurementID
    metric: str
    value: float
    unit: str
    scope: str
    samples: int = 1
    minimum: float | None = None
    maximum: float | None = None
    variance: float | None = None
    instrumented: bool = True
    evidence: tuple[EvidenceClaim, ...] = ()

    def __post_init__(self) -> None:
        if self.samples < 1:
            raise ValueError("measurement samples must be positive")
        if self.variance is not None and self.variance < 0:
            raise ValueError("measurement variance cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "scope": self.scope,
            "samples": self.samples,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "variance": self.variance,
            "instrumented": self.instrumented,
            "evidence": [item.as_dict() for item in self.evidence],
        }


__all__ = [
    "ContractDefinition", "ContractFacet", "EffectPresence", "EffectSet",
    "EffectSummary", "EffectTarget", "EffectTargetKind", "FacetRequirement",
    "MeasurementRecord", "ResourceKind", "ResourceRequirement",
]

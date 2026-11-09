"""Source-to-core identity projections, not a second instruction language.

Ports remain ports: a transport endpoint is not a new computation or an object
identity. Original instructions and normal edges are retained by their owner.
"""
from dataclasses import dataclass
from enum import Enum

from .dependencies import (DependencyPoint, DependencyEdge, NodeID, DependencyKind,
    DependencyMeaning, DependencyStrength)
from .providers import ProviderArtifact
from .normal_graph import Port, Edge
from .source_productions import ProductionRegionID, ProductionStepID
from .source_template_links import SourceTemplateKey
from .signature_patterns import GroundType
from .ids import LocationID


class ProgramEntityKind(str, Enum):
    OPERATION = 'OPERATION'
    VALUE = 'VALUE'
    STATE_LOCATION = 'STATE_LOCATION'
    REGION = 'REGION'
    RESOURCE = 'RESOURCE'


class ProgramNodeRole(str, Enum):
    OPERATION = 'OPERATION'
    REGION = 'REGION'
    STATE_LOCATION = 'STATE_LOCATION'
    RESOURCE = 'RESOURCE'
    ABSTRACT_STATE_DOMAIN = 'ABSTRACT_STATE_DOMAIN'
    PARAMETER = 'PARAMETER'
    ARGUMENT = 'ARGUMENT'
    RESULT = 'RESULT'
    ENTER = 'ENTER'
    EXIT = 'EXIT'
    CALL_RESULT = 'CALL_RESULT'
    CALL_RETURN = 'CALL_RETURN'
    CORE_VALUE = 'CORE_VALUE'
    CORE_USE = 'CORE_USE'
    CORE_CONTROL_PORT = 'CORE_CONTROL_PORT'
    BLOCK = 'BLOCK'
    RESOURCE_REQUIREMENT = 'RESOURCE_REQUIREMENT'
    ENVIRONMENT_INTERFACE = 'ENVIRONMENT_INTERFACE'
    PROVIDER = 'PROVIDER'
    NATIVE_BOUNDARY = 'NATIVE_BOUNDARY'


@dataclass(frozen=True, slots=True)
class ProgramNode:
    """Common metadata; kind=None marks an auxiliary port/interface, not UNKNOWN."""
    point: DependencyPoint
    kind: ProgramEntityKind | None
    role: ProgramNodeRole
    owner: DependencyPoint | None
    value_type: GroundType | None


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    unit: str
    template: SourceTemplateKey | None
    original: ProductionRegionID | ProductionStepID | Port | LocationID


@dataclass(frozen=True, slots=True)
class SourceNodeProjection:
    point: DependencyPoint
    anchor: SourceAnchor
    kind: ProgramEntityKind | None
    role: ProgramNodeRole
    owner: DependencyPoint | None
    value_type: GroundType | None
    material: ProviderArtifact


@dataclass(frozen=True, slots=True)
class SourceEdgeProjection:
    relation: DependencyEdge
    template: SourceTemplateKey
    ordinal: int
    original: Edge | None
    rule: str


@dataclass(frozen=True, slots=True)
class StoredSourceNode:
    """Unit/namespace/material are supplied once by the owning shard header."""
    node: NodeID
    template: SourceTemplateKey | None
    original: ProductionRegionID | ProductionStepID | Port | LocationID
    kind: ProgramEntityKind | None
    role: ProgramNodeRole
    owner: NodeID | None
    value_type: GroundType | None


@dataclass(frozen=True, slots=True)
class StoredDependencyCondition:
    domain: str
    name: str
    subject: NodeID | None
    index: int | None
    operands: tuple[NodeID, ...]


@dataclass(frozen=True, slots=True)
class StoredSourceEdge:
    """original=True references the header's sealed F4 template/edge ordinal.

    Helper relations use rule plus the same template/ordinal coordinates.
    Neither form duplicates the original G.Edge or an executable instruction.
    """
    source: NodeID
    target: NodeID
    kind: DependencyKind
    meaning: DependencyMeaning
    strength: DependencyStrength
    template: SourceTemplateKey
    ordinal: int
    rule: str
    original: bool
    conditions: tuple[StoredDependencyCondition, ...]

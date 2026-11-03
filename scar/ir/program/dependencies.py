"""Qualified endpoints and relations for the shared program-dependency view.

These are references to existing records, not a second set of program IDs.
Context frames are static interface selections, never runtime invocations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from scar.ir.program.ids import (BlockID, ControlPortID, EnvironmentInterfaceID,
    LocationID, NativeBoundaryID, OperationID, ProviderID, RegionID,
    ResourceDefinitionID, ResourceRequirementID, UseID, ValueID)
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.v2.ids import OperationDefinitionID


NODE_TYPES = (OperationID, ValueID, UseID, BlockID, RegionID, LocationID,
    ResourceDefinitionID, ResourceRequirementID, EnvironmentInterfaceID,
    ControlPortID, ProviderID, NativeBoundaryID)
NodeID: TypeAlias = (OperationID | ValueID | UseID | BlockID | RegionID | LocationID
    | ResourceDefinitionID | ResourceRequirementID | EnvironmentInterfaceID
    | ControlPortID | ProviderID | NativeBoundaryID)


@dataclass(frozen=True, slots=True, eq=False)
class GraphNamespace:
    graph: SourceArtifactLocator = field(compare=False, hash=False)
    representation: str
    root: RegionID
    source_body: SourceBodyNamespace | None = field(default=None, compare=False, hash=False)

    def __post_init__(self):
        if type(self.graph) is not SourceArtifactLocator or type(self.root) is not RegionID:
            raise TypeError("graph namespace needs an original locator and RegionID")
        self.graph.__post_init__()
        if type(self.representation) is not str or not self.representation:
            raise ValueError("graph namespace needs its actual representation")
        # A receipt declaring the same immutable original fragment is evidence,
        # not a second namespace. Each supplied declaration is still checked
        # independently by the shared loader, even on a graph cache hit.
        if self.source_body is not None:
            if type(self.source_body) is not SourceBodyNamespace:
                raise TypeError("source body metadata must be SourceBodyNamespace")
            original = self.source_body
            if (self.graph, self.representation, self.root) != (
                    original.graph, original.graph_representation, original.region):
                raise ValueError("graph namespace changed its original source body")

    @classmethod
    def from_source(cls, body):
        if type(body) is not SourceBodyNamespace:
            raise TypeError("expected original SourceBodyNamespace")
        return cls(body.graph, body.graph_representation, body.region, body)

    @property
    def identity(self):
        return (self.graph.artifact.uri, self.graph.decoded_sha256, self.graph.pointer,
                self.representation, self.root)

    def __eq__(self, other):
        return type(other) is GraphNamespace and self.identity == other.identity

    def __hash__(self):
        return hash(self.identity)


@dataclass(frozen=True, slots=True)
class DependencyFrame:
    caller: GraphNamespace
    operation: OperationID
    callee_use: UseID | None
    callee_value: ValueID | None
    target: GraphNamespace
    definition: OperationDefinitionID | None = None
    entry: RegionID | None = None

    def __post_init__(self):
        if (type(self.caller) is not GraphNamespace or type(self.target) is not GraphNamespace
                or type(self.operation) is not OperationID):
            raise TypeError("context frame must retain original call/target endpoints")
        if ((self.callee_use is None) != (self.callee_value is None)
                or self.callee_use is not None and (type(self.callee_use) is not UseID
                    or type(self.callee_value) is not ValueID)):
            raise TypeError("callable Use/value must both be original or both be inapplicable")
        if self.entry is not None and type(self.entry) is not RegionID:
            raise TypeError("internal region entry must be an original RegionID")
        if self.callee_use is None and self.entry is None:
            raise ValueError("direct region calls need their original target entry")
        if self.definition is not None and type(self.definition) is not OperationDefinitionID:
            raise TypeError("selected source definition must be OperationDefinitionID")
        if (self.entry in (None, self.target.root) and self.target.source_body is not None
                and self.definition != self.target.source_body.definition):
            raise ValueError("context frame differs from its selected source definition")


def _context_chain(frames):
    if type(frames) is not tuple or any(type(frame) is not DependencyFrame for frame in frames):
        raise TypeError("dependency context needs an immutable tuple of original frames")
    if any(left.target != right.caller for left, right in zip(frames, frames[1:])):
        raise ValueError("dependency context frames do not form a call chain")
    return frames


@dataclass(frozen=True, slots=True)
class OpenDependencyContext:
    """An unknown, possibly empty outer prefix plus a known nonempty suffix.

    This is an abstract family of interface selections, never a runtime stack.
    It intentionally has no tuple iteration/indexing interface: dropping its
    prefix marker must be an explicit loss of knowledge, not an implicit slice.
    """
    frames: tuple[DependencyFrame, ...]

    def __post_init__(self):
        if not _context_chain(self.frames):
            raise ValueError("open dependency context needs a nonempty known suffix")


DependencyContext: TypeAlias = tuple[DependencyFrame, ...] | OpenDependencyContext | None


def context_frames(context: DependencyContext) -> tuple[DependencyFrame, ...]:
    """Inspect known frames; an empty result does not prove a closed root."""
    if context is None:
        return ()
    if type(context) is OpenDependencyContext:
        context.__post_init__()
        return context.frames
    return _context_chain(context)


def context_is_closed(context: DependencyContext) -> bool:
    return type(context) is tuple


def context_push(context: DependencyContext, *frames: DependencyFrame) -> DependencyContext:
    known = context_frames(context)
    appended = _context_chain((*known, *frames))
    if not frames:
        return context
    return appended if context_is_closed(context) else OpenDependencyContext(appended)


@dataclass(frozen=True, slots=True)
class ContextPopResult:
    matched: bool
    remaining: DependencyContext

    def __post_init__(self):
        if type(self.matched) is not bool:
            raise TypeError("context pop needs an explicit match result")
        context_frames(self.remaining)


def context_pop(context: DependencyContext, expected_frames: tuple[DependencyFrame, ...]) -> ContextPopResult:
    """Pop an exact known suffix without guessing any unknown outer frame."""
    known = context_frames(context)
    expected = _context_chain(expected_frames)
    if len(expected) > len(known) or expected and known[-len(expected):] != expected:
        return ContextPopResult(False, context)
    remaining = known[:-len(expected)] if expected else known
    if context_is_closed(context):
        result = remaining
    else:
        result = OpenDependencyContext(remaining) if remaining else None
    return ContextPopResult(True, result)


@dataclass(frozen=True, slots=True)
class DependencyPoint:
    namespace: GraphNamespace
    node: NodeID
    context: DependencyContext = ()

    def __post_init__(self):
        if type(self.namespace) is not GraphNamespace or type(self.node) not in NODE_TYPES:
            raise TypeError("dependency endpoint needs a qualified original typed ID")
        known = context_frames(self.context)
        if known and known[-1].target != self.namespace:
            raise ValueError("dependency context does not end at the original endpoint namespace")


class DependencyKind(str, Enum):
    VALUE_USE = "VALUE_USE"
    OPERAND = "OPERAND"
    RESULT = "RESULT"
    BLOCK_ARGUMENT = "BLOCK_ARGUMENT"
    BINDING_PAYLOAD = "BINDING_PAYLOAD"
    BINDING_READ = "BINDING_READ"
    CONTROL = "CONTROL"
    CONTROL_FLOW = "CONTROL_FLOW"
    CONTROL_CONDITION = "CONTROL_CONDITION"
    SEQUENCE = "SEQUENCE"
    ORDER = "ORDER"
    CALL_TARGET = "CALL_TARGET"
    ARGUMENT = "ARGUMENT"
    COMPLETION = "COMPLETION"
    STATE_INPUT = "STATE_INPUT"
    STATE_OUTPUT = "STATE_OUTPUT"
    STATE_INTERFACE = "STATE_INTERFACE"
    STATE_LOCATION = "STATE_LOCATION"
    STATE_VALUE = "STATE_VALUE"
    ENVIRONMENT = "ENVIRONMENT"
    FIELD_INITIALIZER = "FIELD_INITIALIZER"
    ALIAS = "ALIAS"
    RESOURCE = "RESOURCE"
    IMPLEMENTATION = "IMPLEMENTATION"
    CONTAINS = "CONTAINS"


class DependencyMeaning(str, Enum):
    DEPENDENCE = "DEPENDENCE"
    VALUE = "VALUE"
    REFERENCE = "REFERENCE"
    STATE_INTERFACE = "STATE_INTERFACE"
    ORDER = "ORDER"
    STRUCTURE = "STRUCTURE"
    BINDING = "BINDING"


class DependencyStrength(str, Enum):
    EXACT = "EXACT"
    MAY = "MAY"


@dataclass(frozen=True, slots=True)
class DependencyCondition:
    """A predicate signature over original endpoints, never a proof.

    ``subject`` is its primary endpoint; ordered ``operands`` bind the other
    participants.  Evidence is not part of a predicate's truth identity.
    Empty operands preserve existing unary signatures, not an implicit
    permission to ignore arguments supplied by a newer predicate rule.
    """
    domain: str
    name: str
    subject: DependencyPoint | None = None
    index: int | None = None
    operands: tuple[DependencyPoint, ...] = ()

    def __post_init__(self):
        if any(type(value) is not str or not value for value in (self.domain, self.name)):
            raise ValueError("condition needs its original domain and name")
        if self.subject is not None and type(self.subject) is not DependencyPoint:
            raise TypeError("condition subject must be a qualified original endpoint")
        if self.index is not None and (type(self.index) is not int or self.index < 0):
            raise ValueError("condition index must be an original nonnegative ordinal")
        if (type(self.operands) is not tuple
                or any(type(operand) is not DependencyPoint for operand in self.operands)):
            raise TypeError("condition operands must be ordered qualified original endpoints")

    @classmethod
    def from_enum(cls, value):
        if not isinstance(value, Enum):
            raise TypeError("original condition must be an Enum member")
        return cls(type(value).__module__ + "." + type(value).__qualname__, value.name)


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    rule: str
    sources: tuple[SourceArtifactLocator, ...]
    anchors: tuple[DependencyPoint, ...] = ()

    def __post_init__(self):
        if type(self.rule) is not str or not self.rule:
            raise ValueError("dependency evidence needs a versioned rule name")
        if (type(self.sources) is not tuple or not self.sources
                or any(type(source) is not SourceArtifactLocator for source in self.sources)):
            raise TypeError("dependency evidence needs original source/relationship locators")
        if type(self.anchors) is not tuple or any(type(point) is not DependencyPoint for point in self.anchors):
            raise TypeError("dependency evidence anchors must be original endpoints")


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source: DependencyPoint
    target: DependencyPoint
    kind: DependencyKind
    meaning: DependencyMeaning
    evidence: tuple[DependencyEvidence, ...]
    conditions: tuple[DependencyCondition, ...] = ()
    strength: DependencyStrength = DependencyStrength.EXACT

    def __post_init__(self):
        if type(self.source) is not DependencyPoint or type(self.target) is not DependencyPoint:
            raise TypeError("dependency edge endpoints must be qualified points")
        if type(self.kind) is not DependencyKind or type(self.meaning) is not DependencyMeaning:
            raise TypeError("dependency edge kind and meaning must be typed")
        if type(self.strength) is not DependencyStrength:
            raise TypeError("dependency relation precision must be typed")
        if (type(self.evidence) is not tuple or not self.evidence
                or any(type(item) is not DependencyEvidence for item in self.evidence)):
            raise TypeError("dependency edge needs its original evidence")
        if type(self.conditions) is not tuple or any(type(item) is not DependencyCondition for item in self.conditions):
            raise TypeError("dependency edge conditions must be immutable typed predicates")


@dataclass(frozen=True, slots=True)
class DependencyFrontier:
    point: DependencyPoint
    kind: str
    detail: str

    def __post_init__(self):
        if type(self.point) is not DependencyPoint or any(
                type(value) is not str or not value for value in (self.kind, self.detail)):
            raise ValueError("dependency frontier needs an original point and explicit reason")


@dataclass(frozen=True, slots=True)
class DependencyNeighborhood:
    edges: tuple[DependencyEdge, ...] = ()
    frontiers: tuple[DependencyFrontier, ...] = ()
    enumerated: bool = True

    def __post_init__(self):
        if type(self.edges) is not tuple or any(type(edge) is not DependencyEdge for edge in self.edges):
            raise TypeError("neighborhood edges must be immutable typed relations")
        if type(self.frontiers) is not tuple or any(type(item) is not DependencyFrontier for item in self.frontiers):
            raise TypeError("neighborhood frontiers must be immutable typed diagnostics")
        if type(self.enumerated) is not bool:
            raise TypeError("neighborhood enumeration marker must be Boolean")

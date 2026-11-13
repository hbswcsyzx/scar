"""Static binding addresses/versions, distinct from objects and tensor data.

A location is a source interface template. Its actual frame, mapping or cell
must still be supplied. A version is indexed by an execution occurrence;
one write site in a loop does not denote a single immutable runtime value.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.effects import Knowledge

from .ids import LocationID, OperationID, ValueID
from .normal_targets import GlobalPort
from .normal_links import CodeScopeRef, Namespace
from .source_bindings import EnvironmentInterface
from .source_effects import FamilyRule
from .source_name_definitions import NameDefinitionKind
from .source_name_definitions import (NameDefinition, NameDefinitionState,
    NameDefinitionTransition, NameDefinitionRead, NameDefinitionFrontier)
from .dependencies import NodeID, DependencyKind, DependencyMeaning, DependencyStrength
from .view import StoredDependencyCondition


class BindingAccessKind(str, Enum):
    READ = 'READ'
    WRITE = 'WRITE'
    DELETE = 'DELETE'
    HANDLE = 'HANDLE'


class BindingBoundness(str, Enum):
    BOUND = 'BOUND'
    UNBOUND = 'UNBOUND'
    UNKNOWN = 'UNKNOWN'


class StateInstanceParameter(str, Enum):
    ACTIVATION_OR_CAPTURED_ENVIRONMENT = 'ACTIVATION_OR_CAPTURED_ENVIRONMENT'
    SITE_EXECUTION_OCCURRENCE = 'SITE_EXECUTION_OCCURRENCE'


@dataclass(frozen=True, slots=True)
class BindingLocationTemplate:
    id: LocationID
    unit: str
    interface: EnvironmentInterface
    key: str
    instance_parameters: tuple[StateInstanceParameter, ...] = (
        StateInstanceParameter.ACTIVATION_OR_CAPTURED_ENVIRONMENT,)


@dataclass(frozen=True, slots=True)
class BindingAccessAlternative:
    """An ordered lookup branch, not an unconditional read of every mapping."""
    location: LocationID
    interface: int | None
    lookup_ordinal: int | None
    on_hit: str | None = None
    on_miss: str | None = None
    on_exception: str | None = None


@dataclass(frozen=True, slots=True)
class BindingAccessTemplate:
    operation: OperationID
    site: GlobalPort
    scope: CodeScopeRef
    kind: BindingAccessKind
    binding_port: int | None
    alternatives: tuple[BindingAccessAlternative, ...]
    payload: GlobalPort | None
    world_in: GlobalPort
    world_out: GlobalPort
    missing_outcome: str | None = None


@dataclass(frozen=True, slots=True)
class SourceEffectRequest:
    """Identification is total; resolved effect membership need not be total.

    Original instructions/ports remain in the sealed source unit. A request
    stores their identity and a closed dispatch rule, never a tensor snapshot.
    """
    operation: OperationID
    rule: FamilyRule
    accesses: tuple[int, ...]
    missing_rules: tuple[str, ...]
    pending: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceEffectSet:
    """Known source access members and independent completeness knowledge.

    Ordinals refer to the owning unit's binding/content access tables. A
    protocol request is not an observed physical read or write. An empty
    UNKNOWN set never means that no effect exists.
    """
    knowledge: Knowledge = Knowledge.UNKNOWN
    binding_accesses: tuple[int, ...] = ()
    content_accesses: tuple[int, ...] = ()

    def __post_init__(self):
        if (type(self.knowledge) is not Knowledge
                or any(type(n) is not int or n < 0 for n in (*self.binding_accesses, *self.content_accesses))
                or self.knowledge is Knowledge.NONE and (self.binding_accesses or self.content_accesses)):
            raise ValueError('effect members require original nonnegative access ordinals and consistent knowledge')


@dataclass(frozen=True, slots=True)
class SourceEffectSummary:
    operation: OperationID
    rule: FamilyRule
    world_inputs: tuple[GlobalPort, ...]
    world_outputs: tuple[GlobalPort, ...]
    reads: SourceEffectSet
    writes: SourceEffectSet
    allocates: SourceEffectSet
    frees: SourceEffectSet
    aliases: SourceEffectSet
    escapes: SourceEffectSet
    rng_effect: Knowledge
    may_raise: Knowledge
    external_effect: Knowledge
    ordering_effect: Knowledge
    unresolved_fields: tuple[str, ...]
    missing_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BindingVersionTemplate:
    id: ValueID
    location: LocationID
    source_function: GlobalPort
    namespace: Namespace
    definition: int
    kind: NameDefinitionKind
    boundness: BindingBoundness
    payload: GlobalPort | None
    instance_parameters: tuple[StateInstanceParameter, ...] = (
        StateInstanceParameter.ACTIVATION_OR_CAPTURED_ENVIRONMENT,
        StateInstanceParameter.SITE_EXECUTION_OCCURRENCE)


@dataclass(frozen=True, slots=True)
class BindingReadSelection:
    """Indices retain the original matched recipe stack and source guards."""
    track: int
    read: int
    access: int
    state: int
    versions: tuple[ValueID, ...]


@dataclass(frozen=True, slots=True)
class StoredBindingTrack:
    """Operation/edge indices refer to the pinned original body projection.

    Body instructions, world ports and control edges are not copied. The
    reader rederives their original order before accepting these indices.
    """
    source_function: GlobalPort
    namespace: Namespace
    max_states: int
    max_stack: int
    max_updates: int
    definitions: tuple[NameDefinition, ...]
    states: tuple[NameDefinitionState, ...]
    transitions: tuple[NameDefinitionTransition, ...]
    reads: tuple[NameDefinitionRead, ...]
    frontiers: tuple[NameDefinitionFrontier, ...]
    traversal_complete: bool
    dataflow_complete: bool


@dataclass(frozen=True, slots=True)
class StoredBindingEdge:
    """Source namespace and rule materials are factored into the shard header."""
    source: NodeID
    target: NodeID
    kind: DependencyKind
    meaning: DependencyMeaning
    strength: DependencyStrength
    rule: str
    conditions: tuple[StoredDependencyCondition, ...]

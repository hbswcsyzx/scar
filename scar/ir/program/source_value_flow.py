"""Source operations and value transport, without object/content equivalence.

Operation interfaces reference the original F4 instruction language. Lexical
locations factor possible writes/reads instead of materializing their product.
All identifiers are qualified by the body's versioned source material.
"""
from dataclasses import dataclass

from . import source_productions as P, normal_graph as G, normal_links as F
from .normal_targets import GlobalPort, Body
from .providers import ProviderArtifact, ProviderFactReference
from .signature_patterns import GroundType


@dataclass(frozen=True, slots=True)
class TypedValuePort:
    port: G.Port
    value_type: GroundType


@dataclass(frozen=True, slots=True)
class SourceOperation:
    entry: G.Port
    instruction: P.ProductionInstruction
    inputs: tuple[TypedValuePort, ...]
    outputs: tuple[TypedValuePort, ...]


@dataclass(frozen=True, slots=True)
class LocationAccess:
    value: G.Port
    fact: ProviderFactReference


@dataclass(frozen=True, slots=True)
class LexicalLocation:
    scope: F.CodeScopeRef
    namespace: F.Namespace
    writes: tuple[LocationAccess, ...]
    reads: tuple[LocationAccess, ...]


@dataclass(frozen=True, slots=True)
class NameBoundary:
    scope: F.CodeScopeRef
    namespace: F.Namespace
    access: LocationAccess
    write: bool
    reason: str


@dataclass(frozen=True, slots=True)
class SourceBodyCall:
    fact: ProviderFactReference
    call: F.Call


@dataclass(frozen=True, slots=True)
class SourceBodyValueFlow:
    source_function: GlobalPort
    body: Body
    source_templates: ProviderArtifact
    edges: tuple[G.Edge, ...]
    operations: tuple[SourceOperation, ...]
    locations: tuple[LexicalLocation, ...]
    calls: tuple[SourceBodyCall, ...]
    name_boundaries: tuple[NameBoundary, ...] = ()


@dataclass(frozen=True, slots=True)
class DependentCallInput:
    call: ProviderFactReference
    role: str
    ordinal: int
    keyword: str | None
    actual: GlobalPort


@dataclass(frozen=True, slots=True)
class SourceDataReach:
    entry: int
    body: int
    formal: GlobalPort
    reached_ports: int
    reached_operations: tuple[int, ...]
    call_inputs: tuple[DependentCallInput, ...]
    conditions: tuple[str, ...] = (
        'PARENT_ARGUMENT_AND_DECLARED_BODY_CONTEXT_SELECTED',
        'FLOW_INSENSITIVE_SYNTACTIC_MAY_DEPENDENCY',
        'BRANCH_AND_CALL_RETURN_LABELS_RETAINED_NOT_SOLVED_BY_THIS_QUERY',
        'LEXICAL_LOCATION_IS_NOT_A_SELECTED_REACHING_VERSION',
        'OPERATION_OUTPUT_CAN_DEPEND_ON_ANY_DATA_INPUT',
        'WORLD_IS_NOT_PROPAGATED_AS_DATA_DEPENDENCY',
        'NO_ALIAS_CONTENT_IDENTITY_PURITY_OR_RUNTIME_DISPATCH_PROOF',
    )

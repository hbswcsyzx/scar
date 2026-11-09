"""Original name facts anchored to source operations, never current versions."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef, CodeScopeWitness, NameAccess, Namespace
from .normal_targets import GlobalPort
from .providers import ProviderArtifact, ProviderFactReference
from .source_namespaces import NamespaceAccess, NamespaceInterfaceRef


@dataclass(frozen=True, slots=True)
class NameAccessAnchor:
    """access indexes graph.accesses; lookup ordinal selects its read branch."""
    fact: ProviderFactReference
    record: NameAccess
    scope: CodeScopeRef
    access: int
    namespace: Namespace
    lookup_ordinal: int | None
    target: NamespaceInterfaceRef | None


@dataclass(frozen=True, slots=True)
class NameDeleteAnchor:
    """DELETE has an F4 operation but no legacy NameAccess row."""
    access: int
    namespace: Namespace
    target: NamespaceInterfaceRef


@dataclass(frozen=True, slots=True)
class FormalNameAdmission:
    """A logical formal admission at a declared body entry, not a store step.

    parameter is the original environment.parameters ordinal. The formal's
    original body PARAMETER ordinal includes the separate environment prefix.
    """
    fact: ProviderFactReference
    record: NameAccess
    function: ProviderFactReference
    source_function: GlobalPort
    owner: CodeScopeWitness
    parameter: int
    binding_port: int
    formal: GlobalPort
    entry: GlobalPort


@dataclass(frozen=True, slots=True)
class NameAccessAnchorFrontier:
    fact: ProviderFactReference | None
    access: int | None
    scope: CodeScopeRef | None
    reason: str
    candidate_accesses: tuple[int, ...] = ()
    candidate_functions: tuple[ProviderFactReference, ...] = ()


@dataclass(frozen=True, slots=True)
class NameAccessAnchorGraph:
    unit: str
    scopes: tuple[CodeScopeRef, ...]
    materials: tuple[ProviderArtifact, ...]
    accesses: tuple[NamespaceAccess, ...]
    anchors: tuple[NameAccessAnchor, ...]
    formals: tuple[FormalNameAdmission, ...]
    deletes: tuple[NameDeleteAnchor, ...]
    frontiers: tuple[NameAccessAnchorFrontier, ...]
    conditions: tuple[str, ...] = (
        'SOURCE_SCOPE_SELECTION_IS_QUERY_NOT_ACTIVATION',
        'ORIGINAL_OPERATION_AND_LOOKUP_BRANCH_REQUIRE_SELECTED_EXECUTION_CONTEXT',
        'OPERATION_WORLD_PORTS_NOT_CURRENT_NAMESPACE_SLOT_VERSION_PROOF',
        'NO_REACHING_DEFINITION_OR_REFERENCE_IDENTITY_ESTABLISHED',
    )
    semantics: str = 'SOURCE_NAME_FACT_OPERATION_ANCHORS_NOT_NAME_VERSIONS'

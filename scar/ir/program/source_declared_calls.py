"""Original source call declarations and conditional namespace requests."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .source_namespace_references import NamespaceReferenceSlice, NamespaceSelector


@dataclass(frozen=True, slots=True)
class DeclaredCallQuery:
    unit: str
    call: ProviderFactReference
    callee: GlobalPort
    owners: tuple[CodeScopeRef, ...]
    reference: NamespaceReferenceSlice
    formal_frontiers: tuple[int, ...] = ()
    call_result_frontiers: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DeclaredCallSymbolRequest:
    """query indexes this unit's queries table, preserving calls ordinals."""
    query: int
    state: int
    imported: ProviderFactReference
    returned_module: str
    requested_module: str | None
    selectors: tuple[NamespaceSelector, ...]
    conditions: tuple[str, ...] = (
        'STANDARD_IMPORT_RETURN_AND_RECORDED_ATTRIBUTE_PATH_SELECTED',
        'CURRENT_NAMESPACE_EXPORT_OR_IMPORT_FROM_BRANCH_NOT_SELECTED',
        'SYMBOL_PATH_IS_INTERFACE_REQUEST_NOT_CALLABLE_OR_NATIVE_BINDING_PROOF',
        'SOURCE_CALL_DECLARATION_DOES_NOT_ESTABLISH_OWNING_SCOPE_ENTRY',
    )


@dataclass(frozen=True, slots=True)
class DeclaredCallUnit:
    unit: str
    queries: tuple[DeclaredCallQuery, ...]
    symbols: tuple[DeclaredCallSymbolRequest, ...]
    semantics: str = 'DECLARED_SOURCE_CALLS_NOT_ENTERED_FRAMES_OR_RUNTIME_DISPATCH'

"""Namespace source templates attached to selected caller reference states."""
from dataclasses import dataclass

from .normal_targets import GlobalPort, FunctionConnection
from .providers import ProviderFactReference
from .source_namespace_references import NamespaceReferenceSlice, NamespaceSelector


@dataclass(frozen=True, slots=True)
class CalleeNamespaceLookup:
    port: GlobalPort
    reference: NamespaceReferenceSlice


@dataclass(frozen=True, slots=True)
class CalleeNamespaceAnchor:
    query: int
    state: int
    lookup: int


@dataclass(frozen=True, slots=True)
class NamespaceFunctionConnection:
    anchor: int
    origin: int
    connection: FunctionConnection


@dataclass(frozen=True, slots=True)
class NamespaceCallFrontier:
    anchor: int
    origin: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class NamespaceSymbolRequest:
    lookup: int
    state: int
    imported: ProviderFactReference
    returned_module: str
    requested_module: str | None
    selectors: tuple[NamespaceSelector, ...]
    conditions: tuple[str, ...] = (
        'STANDARD_IMPORT_RETURN_AND_RECORDED_ATTRIBUTE_PATH_SELECTED',
        'CURRENT_NAMESPACE_EXPORT_OR_IMPORT_FROM_BRANCH_NOT_SELECTED',
        'SYMBOL_PATH_IS_INTERFACE_REQUEST_NOT_CALLABLE_OR_NATIVE_BINDING_PROOF',
    )

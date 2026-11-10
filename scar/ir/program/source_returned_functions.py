"""Returned callable provenance; creation and invocation contexts are separate."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .source_call_contexts import CallInterfaceRecord, ContextReferenceSlice
from .source_function_creations import SourceFunctionCreation


@dataclass(frozen=True, slots=True)
class ReturnedCallableProvenance:
    query: int
    cut: int
    declared: ProviderFactReference
    seed_interface: CallInterfaceRecord
    return_source: GlobalPort
    reference: ContextReferenceSlice
    origin: int
    creation: SourceFunctionCreation
    creator_interfaces: tuple[CallInterfaceRecord, ...]
    base_scopes: tuple[CodeScopeRef, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReturnedCallableFrontier:
    query: int
    cut: int
    declared: ProviderFactReference
    seed_interface: CallInterfaceRecord | None
    return_source: GlobalPort | None
    reference: ContextReferenceSlice | None
    reason: str

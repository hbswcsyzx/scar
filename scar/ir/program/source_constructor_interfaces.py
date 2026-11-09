"""Original constructor stages and guarded source-body entry interfaces."""
from dataclasses import dataclass

from .normal_targets import ConstructionLink, FunctionConnection
from .providers import ProviderFactReference
from .source_value_flow import SourceBodyCall


@dataclass(frozen=True, slots=True)
class ConstructorInterfaceSite:
    unit: str
    record: SourceBodyCall


@dataclass(frozen=True, slots=True)
class ConstructorInterfaceStep:
    site: int
    evidence: ProviderFactReference
    link: ConstructionLink


@dataclass(frozen=True, slots=True)
class ConstructorBodyEntry:
    step: int
    connection: FunctionConnection


@dataclass(frozen=True, slots=True)
class ConstructorInterfaceFrontier:
    step: int
    reason: str


@dataclass(frozen=True, slots=True)
class ConstructorInterfaceGraph:
    sites: tuple[ConstructorInterfaceSite, ...]
    steps: tuple[ConstructorInterfaceStep, ...]
    entries: tuple[ConstructorBodyEntry, ...]
    frontiers: tuple[ConstructorInterfaceFrontier, ...]
    semantics: str = 'GUARDED_CONSTRUCTOR_PROTOCOL_NOT_ALLOCATION_OR_RUNTIME_DISPATCH_PROOF'

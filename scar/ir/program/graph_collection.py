"""A small, typed directory of immutable source graph shards."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.v2.ids import Identifier
from .providers import ProviderArtifact


class NormalGraphStoreID(Identifier):
    prefix='normal_graph_store'


class SourceUnitRole(str,Enum):
    PYTHON_SOURCE='PYTHON_SOURCE'
    TYPE_DECLARATION='TYPE_DECLARATION'


@dataclass(frozen=True,slots=True)
class NormalGraphStore:
    id: NormalGraphStoreID
    result: ProviderArtifact


@dataclass(frozen=True,slots=True)
class NormalGraphUnit:
    unit: str
    store: NormalGraphStoreID
    role: SourceUnitRole


@dataclass(frozen=True,slots=True)
class NormalGraphDirectory:
    source_interfaces: ProviderArtifact
    stores: tuple[NormalGraphStore,...]
    units: tuple[NormalGraphUnit,...]

"""Catalog-qualified locations of immutable source fact material."""
from dataclasses import dataclass

from .providers import ProviderArtifact


@dataclass(frozen=True, slots=True)
class FactMaterialRoute:
    unit: str
    logical: ProviderArtifact
    physical: ProviderArtifact
    catalogs: tuple[ProviderArtifact, ...]
    format: str

"""Ordered configuration operations over shared, versioned data materials.

This is a conditional library-protocol graph, not a dictionary snapshot or an
execution trace. A merge result is a version; it is never a Python object ID.
"""
from dataclasses import dataclass
from enum import Enum

from .providers import ProviderArtifact


@dataclass(frozen=True,slots=True)
class ConfigurationProtocolSource:
    source: ProviderArtifact
    qualified_function: str
    function_ast_sha256: str


@dataclass(frozen=True,slots=True)
class ConfigurationMaterial:
    id: str
    store: ProviderArtifact
    source: ProviderArtifact
    root_reference: int | None
    package_header: str | None


class ConfigurationDependencyKind(str,Enum):
    SELF = 'SELF'
    CONFIG = 'CONFIG'
    GROUP = 'GROUP'
    OVERRIDE = 'OVERRIDE'
    NULL_CHOICE = 'NULL_CHOICE'
    UNRESOLVED = 'UNRESOLVED'


@dataclass(frozen=True,slots=True)
class ConfigurationDependency:
    ordinal: int
    instance: str
    material: str
    reference: int | None
    kind: ConfigurationDependencyKind
    config_path: str | None
    group: str | None
    choice: str | None
    package_override: str | None
    package: str | None
    child_instance: str | None
    optional: bool
    implicit: bool
    conditions: tuple[str,...]


class ConfigurationStepKind(str,Enum):
    EMPTY = 'EMPTY'
    MERGE_MATERIAL = 'MERGE_MATERIAL'
    OPEN_PROVIDER = 'OPEN_PROVIDER'


@dataclass(frozen=True,slots=True)
class ConfigurationStep:
    """One SSA-like root version, retaining source payloads instead of copies."""
    ordinal: int
    kind: ConfigurationStepKind
    previous: int | None
    instance: str | None
    dependency: int | None
    material: str | None
    root_reference: int | None
    package: tuple[str,...]
    exclude_root_keys: tuple[str,...]
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class ConfigurationCompositionObligation:
    code: str
    dependency: int | None
    material: str | None
    detail: str


@dataclass(frozen=True,slots=True)
class ConfigurationComposition:
    request: str
    source_candidate: int
    file_root: str
    main_resource: str
    profiles: tuple[ConfigurationProtocolSource,...]
    materials: tuple[ConfigurationMaterial,...]
    dependencies: tuple[ConfigurationDependency,...]
    steps: tuple[ConfigurationStep,...]
    obligations: tuple[ConfigurationCompositionObligation,...]
    root_version: int
    conditions: tuple[str,...]
    semantics: str = 'CONDITIONAL_ORDERED_COMPOSITION_NOT_RESOLVED_CFG_OR_RUNTIME_VALUE'

"""Representation graphs for external data; not executed program actions."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from .providers import ProviderArtifact


class DataNodeKind(str,Enum):
    SCALAR='SCALAR'
    SEQUENCE='SEQUENCE'
    MAPPING='MAPPING'


@dataclass(frozen=True,slots=True)
class DataSpan:
    """Raw UTF-8 byte bounds and zero-based parser-view line/columns."""
    byte_start: int
    byte_end: int
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True,slots=True)
class DataReference:
    ordinal: int
    target: int
    span: DataSpan
    alias: bool
    anchor: str | None


@dataclass(frozen=True,slots=True)
class DataMappingEntry:
    key: int
    value: int


@dataclass(frozen=True,slots=True)
class DataNode:
    ordinal: int
    kind: DataNodeKind
    tag: str
    span: DataSpan
    anchor: str | None
    scalar_text: str | None
    scalar_style: str | None
    flow_style: bool | None
    representation_literal: PythonLiteral | None
    items: tuple[int,...]
    entries: tuple[DataMappingEntry,...]


@dataclass(frozen=True,slots=True)
class DataObligation:
    code: str
    node: int | None
    reference: int | None
    detail: str


@dataclass(frozen=True,slots=True)
class DataParserProfile:
    rule: str
    tools: tuple[ProviderArtifact,...]
    loader_source: ProviderArtifact | None
    loader_function_ast_sha256: str | None
    float_pattern: str | None
    float_flags: int
    float_initial_characters: str
    removed_implicit_tags: tuple[str,...]
    scalar_tags: tuple[str,...]
    text_view: str = 'UTF8_UNIVERSAL_NEWLINES'
    construction_scope: str = 'SCALARS_ONLY_NO_CONTAINER_OR_CUSTOM_CONSTRUCTORS'


@dataclass(frozen=True,slots=True)
class DataMaterial:
    source: ProviderArtifact
    profile: DataParserProfile
    normalized_text_sha256: str
    root: int | None
    nodes: tuple[DataNode,...]
    references: tuple[DataReference,...]
    obligations: tuple[DataObligation,...]
    semantics: str = 'PARSED_REPRESENTATION_NOT_COMPOSED_CONFIGURATION_OR_RUNTIME_VALUE'

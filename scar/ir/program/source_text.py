"""Conditional path expressions and text reads of captured source artifacts."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from . import normal_links as F, normal_targets as T, source_productions as P
from .python_bindings import SourceCallSite
from .source_references import SourceArtifactLocator


class SourcePathOperation(str, Enum):
    CONSTRUCT = 'CONSTRUCT'
    RESOLVE = 'RESOLVE'
    PARENT = 'PARENT'
    JOIN = 'JOIN'


@dataclass(frozen=True, slots=True)
class SourcePathExpression:
    id: str
    result: T.GlobalPort
    owner: F.CodeScopeRef
    operation: SourcePathOperation
    operands: tuple[T.GlobalPort, ...]
    provider: SourceArtifactLocator
    export: str
    source_table: str
    source_ordinal: int
    call: SourceCallSite | None = None
    attribute: T.AttributeSite | None = None
    language: T.LanguageOperationSite | None = None
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourcePathCandidate:
    expression: str
    result: T.GlobalPort
    lexical_path: str
    conditions: tuple[str, ...]
    semantics: str = 'CONDITIONAL_LEXICAL_PATH_NOT_FILESYSTEM_IDENTITY'


@dataclass(frozen=True, slots=True)
class TextReadParameter:
    name: str
    source: T.GlobalPort | None
    literal: PythonLiteral | None
    defaulted: bool
    literal_occurrence: P.ProductionOccurrence | None = None


@dataclass(frozen=True, slots=True)
class SourceTextRead:
    site: SourceCallSite
    owner: F.CodeScopeRef
    receiver: T.GlobalPort
    path_expression: str
    parameters: tuple[TextReadParameter, ...]
    conditions: tuple[str, ...]
    obligations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TextOpenInterpretation:
    encoding: str | None
    errors: str | None
    newline: str | None
    newline_resolved: bool
    default_encoding: bool
    rule: str = 'TEXT_OPEN_CAPTURED_RAW_BYTES_V1'
    conditions: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceTextCandidate:
    read_result: T.GlobalPort
    path_expression: str
    source_unit: str
    source_path: str
    source: SourceArtifactLocator
    f0_document_sha256: str
    raw_sha256: str
    raw_bytes: int
    interpretation: TextOpenInterpretation
    text_utf8_sha256: str | None
    characters: int | None
    conditions: tuple[str, ...]
    obligations: tuple[str, ...] = ()
    semantics: str = 'CONDITIONAL_CAPTURED_SOURCE_TEXT_NOT_RUNTIME_IO'


@dataclass(frozen=True, slots=True)
class SourceTextObligation:
    port: T.GlobalPort
    reason: str


@dataclass(frozen=True, slots=True)
class SourceTextOverlay:
    unit: str
    paths: tuple[SourcePathExpression, ...]
    path_values: tuple[SourcePathCandidate, ...]
    reads: tuple[SourceTextRead, ...]
    candidates: tuple[SourceTextCandidate, ...]
    obligations: tuple[SourceTextObligation, ...]

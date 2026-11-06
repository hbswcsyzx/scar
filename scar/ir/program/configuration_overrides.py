"""Input expressions and ordered configuration writes, not runtime objects."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from .configuration_composition import ConfigurationProtocolSource
from .providers import ProviderArtifact
from .source_frame_bindings import StaticInputPort


class OverrideExpressionKind(str,Enum):
    SCALAR = 'SCALAR'
    SEQUENCE = 'SEQUENCE'
    MAPPING = 'MAPPING'
    CALL = 'CALL'
    SWEEP = 'SWEEP'


@dataclass(frozen=True,slots=True)
class OverrideExpression:
    ordinal: int
    argument_index: int
    character_start: int
    character_end: int
    kind: OverrideExpressionKind
    literal: PythonLiteral | None
    quote: str | None
    children: tuple[int,...]
    entries: tuple[tuple[int,int],...]
    function: str | None
    argument_names: tuple[str | None,...]


class OverrideAction(str,Enum):
    CHANGE = 'CHANGE'
    ADD = 'ADD'
    FORCE_ADD = 'FORCE_ADD'
    DELETE = 'DELETE'


@dataclass(frozen=True,slots=True)
class ConfigurationOverride:
    ordinal: int
    source: StaticInputPort
    token: str
    action: OverrideAction
    key_or_group: str
    package: str | None
    field_path_candidate: tuple[str,...] | None
    value: int | None
    input_version: int
    output_version: int
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class ConfigurationOverrideObligation:
    code: str
    override: int | None
    expression: int | None
    detail: str


@dataclass(frozen=True,slots=True)
class ConfigurationOverrides:
    composition: ProviderArtifact
    composition_version: int
    entry: ProviderArtifact
    protocol_sources: tuple[ConfigurationProtocolSource,...]
    parser_tools: tuple[ProviderArtifact,...]
    overrides: tuple[ConfigurationOverride,...]
    expressions: tuple[OverrideExpression,...]
    obligations: tuple[ConfigurationOverrideObligation,...]
    root_version: int
    conditions: tuple[str,...]
    semantics: str = 'INITIAL_ARGV_CONDITIONAL_WRITES_NOT_CURRENT_OR_RESOLVED_CFG'

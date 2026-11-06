"""Versioned configuration algebra and read dependencies over shared inputs.

Ordinals are scoped to their graph artifact. They are neither storage addresses
nor Python identities; input references retain the original material/argv graph.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from .configuration_composition import ConfigurationProtocolSource
from .providers import ProviderArtifact


@dataclass(frozen=True,slots=True)
class ConfigurationInput:
    table: str
    owner: str
    ordinal: int


class ConfigurationExpressionKind(str,Enum):
    EMPTY = 'EMPTY'
    INPUT = 'INPUT'
    OPEN_PROVIDER = 'OPEN_PROVIDER'
    EMBED = 'EMBED'
    MERGE = 'MERGE'
    ASSIGN = 'ASSIGN'
    UPDATE = 'UPDATE'
    DELETE = 'DELETE'


@dataclass(frozen=True,slots=True)
class ConfigurationExpression:
    ordinal: int
    kind: ConfigurationExpressionKind
    inputs: tuple[int,...]
    source: ConfigurationInput | None
    path: tuple[str,...]
    exclude_root_keys: tuple[str,...]
    parent_stage: str
    parent_ordinal: int | None
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class ConfigurationRoot:
    stage: str
    version: int
    expression: int


class ConfigurationValueKind(str,Enum):
    SCALAR = 'SCALAR'
    MAPPING = 'MAPPING'
    SEQUENCE = 'SEQUENCE'
    MISSING = 'MISSING'
    ABSENT = 'ABSENT'
    OPEN = 'OPEN'
    INTERPOLATION = 'INTERPOLATION'
    CYCLE = 'CYCLE'
    NONCONTAINER = 'NONCONTAINER'
    TYPE_CONFLICT = 'TYPE_CONFLICT'


@dataclass(frozen=True,slots=True)
class ConfigurationProjection:
    ordinal: int
    root: int
    path: tuple[str,...]
    kind: ConfigurationValueKind
    literal: PythonLiteral | None
    members_complete: bool | None
    origins: tuple[ConfigurationInput,...]
    dependencies: tuple[int,...]
    evidence: tuple[int,...]
    value_path: tuple[str,...] | None
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class ConfigurationInterpolation:
    ordinal: int
    projection: int
    character_start: int
    character_end: int
    syntax: str
    kind: str
    target_path: tuple[str,...] | None
    dependencies: tuple[int,...]
    phase: str = 'LAZY_SELECTED_ROOT'


@dataclass(frozen=True,slots=True)
class ConfigurationReadDemand:
    ordinal: int
    operation: int
    snapshot: int | None
    path: tuple[str,...]
    phase: str
    source: ConfigurationInput | None
    projection: int | None


@dataclass(frozen=True,slots=True)
class ConfigurationValueObligation:
    code: str
    expression: int | None
    projection: int | None
    detail: str


@dataclass(frozen=True,slots=True)
class ConfigurationValues:
    overrides: ProviderArtifact
    profiles: tuple[ConfigurationProtocolSource,...]
    parser_tools: tuple[ProviderArtifact,...]
    expressions: tuple[ConfigurationExpression,...]
    roots: tuple[ConfigurationRoot,...]
    projections: tuple[ConfigurationProjection,...]
    interpolations: tuple[ConfigurationInterpolation,...]
    read_demands: tuple[ConfigurationReadDemand,...]
    obligations: tuple[ConfigurationValueObligation,...]
    selected_root: int
    conditions: tuple[str,...]
    semantics: str = 'CONDITIONAL_STATIC_INPUT_PROJECTIONS_NOT_CURRENT_TASK_CFG_OR_OBJECT_IDENTITY'

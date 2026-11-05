"""Conditional software/target relationships; never evidence of actual use."""
from dataclasses import dataclass
from enum import Enum

from .ids import NativeBoundaryID
from .native import EntryPortRef
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .python_bindings import PythonBindingID
from .target_hardware import TargetResourceRef,ResourceCandidateKind


@dataclass(frozen=True,slots=True)
class OperandTargetCandidate:
    boundary: NativeBoundaryID
    port: EntryPortRef
    declaration: ProviderFactReference
    target: TargetResourceRef
    relation: ResourceCandidateKind
    conditions: tuple[str,...]
    selected: bool=False


class OperandSourceKind(str,Enum):
    KEYWORD='KEYWORD'
    POSITIONAL='POSITIONAL'
    DEFAULT_EXPRESSION='DEFAULT_EXPRESSION'
    PACK_DEPENDENCY='PACK_DEPENDENCY'
    RECEIVER_OPEN='RECEIVER_OPEN'
    RECEIVER='RECEIVER'
    CONVERSION_OPEN='CONVERSION_OPEN'


@dataclass(frozen=True,slots=True)
class OperandSource:
    call: GlobalPort
    binding: PythonBindingID
    boundary: NativeBoundaryID
    native_port: EntryPortRef
    parser_parameter: str | None
    actuals: tuple[GlobalPort,...]
    kind: OperandSourceKind
    default_expression: str | None
    conditions: tuple[str,...]
    semantics: str='DECLARED_NORMALIZATION_DEPENDENCY'


@dataclass(frozen=True,slots=True)
class SoftwareArtifactLocation:
    unit: str
    source_path: str
    resolved_path: str
    endpoint: TargetResourceRef | None
    evidence: ProviderFactReference
    conditions: tuple[str,...]=('PATH_LOCATION_SNAPSHOT_ONLY','NO_RUNTIME_IO_OR_SOURCE_CONTENT_EQUALITY_CLAIM')

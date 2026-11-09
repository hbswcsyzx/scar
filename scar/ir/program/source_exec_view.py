"""Conditional exec interfaces; auxiliary handles are not source F4 ports."""
from dataclasses import dataclass
from enum import Enum

from .dependencies import DependencyPoint, DependencyFrame, DependencyKind, DependencyMeaning
from .ids import ValueID, ControlPortID, OperationID, ProviderID
from .providers import ProviderFactReference
from .signature_patterns import GroundType
from .source_exec_roots import ExecProtocolValue, ExecProtocolAction, ExecPredicate
from .source_frame_bindings import FrameGlobalsBinding, RootNamespaceBinding
from .source_launch import ScriptEntryContract
from .normal_graph import Transition
from scar.ir.literals import PythonLiteral


class ExecValueKind(str, Enum):
    REFERENCE = 'REFERENCE'
    STATE = 'STATE'
    CONTROL = 'CONTROL'


class ExecFlow(str, Enum):
    ENTER = 'ENTER'
    RETURN = 'RETURN'


@dataclass(frozen=True, slots=True)
class ExecInterfaceValue:
    id: ValueID | ControlPortID
    original: ExecProtocolValue
    kind: ExecValueKind
    value_type: GroundType | None
    instance_parameters: tuple[str, ...] = ('CALLER_FRAME', 'EXEC_OCCURRENCE', 'SELECTED_NAMESPACE_BRANCH')


@dataclass(frozen=True, slots=True)
class ExecActionOperation:
    id: OperationID
    connection: ProviderFactReference
    ordinal: int
    original: ExecProtocolAction


@dataclass(frozen=True, slots=True)
class ExecNormalResult:
    id: ValueID
    connection: ProviderFactReference
    literal: PythonLiteral


@dataclass(frozen=True, slots=True)
class ExecFrameGlobalsValue:
    id: ValueID
    connection: ProviderFactReference
    evidence: ProviderFactReference
    original: FrameGlobalsBinding
    instance_parameters: tuple[str, ...] = ('CALLER_FRAME', 'SELECTED_FUNCTION_CREATION', 'EXEC_OCCURRENCE')


@dataclass(frozen=True, slots=True)
class ExecEntryDeclaration:
    id: ProviderID
    contract: ScriptEntryContract
    binding: RootNamespaceBinding


@dataclass(frozen=True, slots=True)
class ExecBodyInterface:
    connection: int
    evidence: ProviderFactReference
    frame: DependencyFrame


@dataclass(frozen=True, slots=True)
class ExecRelation:
    source: DependencyPoint
    target: DependencyPoint
    connection: int
    rule: str
    ordinal: int
    kind: DependencyKind
    meaning: DependencyMeaning
    transition: Transition
    flow: ExecFlow | None
    guards: tuple[str, ...]
    predicates: tuple[ExecPredicate, ...]

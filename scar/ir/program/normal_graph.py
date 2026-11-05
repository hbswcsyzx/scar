"""Normal-success dependency edges over the existing shared source IR.

Nodes remain SourceProductionPlan regions/steps. Ports qualify their original
IDs by source template; the store header qualifies templates by source version.
Call-site labels pair entry/return edges without cloning functions or loops.
"""
from dataclasses import dataclass
from enum import Enum

from . import source_productions as P
from .control import LanguageCompletionKind
from .model import ValueKind, ValueType
from .signature_patterns import GroundType
from .source_template_links import SourceTemplateKey


class PortKind(str, Enum):
    PARAMETER = 'PARAMETER'
    ARGUMENT = 'ARGUMENT'
    RESULT = 'RESULT'
    ENTER = 'ENTER'
    EXIT = 'EXIT'
    CALL_RESULT = 'CALL_RESULT'
    CALL_RETURN = 'CALL_RETURN'


class EdgeKind(str, Enum):
    DATA = 'DATA'
    STATE = 'STATE'
    CONTROL = 'CONTROL'
    DECLARE = 'DECLARE'


class Transition(str, Enum):
    DIRECT = 'DIRECT'
    CALL = 'CALL'
    RETURN = 'RETURN'
    BACKEDGE = 'BACKEDGE'
    RESUME = 'RESUME'


@dataclass(frozen=True, slots=True)
class Port:
    template: SourceTemplateKey
    owner: P.ProductionRegionID | P.ProductionStepID
    kind: PortKind
    ordinal: int = 0
    completion: LanguageCompletionKind | P.PatternCompletionKind | None = None
    target: P.ProductionControlTarget | None = None
    path: tuple[P.CompilationPathPart, ...] = ()

    def __post_init__(self):
        if type(self.template) is not SourceTemplateKey or type(self.owner) not in (P.ProductionRegionID, P.ProductionStepID):
            raise ValueError('graph port needs original qualified identities')
        if type(self.kind) is not PortKind or type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError('graph port needs an exact kind and nonnegative ordinal')
        completed = self.kind in (PortKind.RESULT, PortKind.EXIT, PortKind.CALL_RESULT, PortKind.CALL_RETURN)
        if completed != (self.completion is not None):
            raise ValueError('only result/exit ports carry a completion')


@dataclass(frozen=True, slots=True)
class CallSite:
    template: SourceTemplateKey
    step: P.ProductionStepID
    path: tuple[P.CompilationPathPart, ...] = ()


@dataclass(frozen=True, slots=True)
class Edge:
    source: Port
    target: Port
    kind: EdgeKind
    value_type: GroundType | None = None
    site: CallSite | None = None
    transition: Transition = Transition.DIRECT
    condition: Port | None = None
    when: bool | None = None

    def __post_init__(self):
        if type(self.source) is not Port or type(self.target) is not Port or type(self.kind) is not EdgeKind:
            raise ValueError('edge requires typed endpoints and kind')
        if (self.kind in (EdgeKind.DATA, EdgeKind.STATE)) != (self.value_type is not None):
            raise ValueError('data/state edges require a value type')
        state = type(self.value_type) is ValueType and self.value_type.kind is ValueKind.STATE
        if (self.kind is EdgeKind.STATE) != state:
            raise ValueError('state edges must carry an actual state domain')
        if (self.condition is None) != (self.when is None) or self.when is not None and type(self.when) is not bool:
            raise ValueError('a guarded edge needs a condition port and boolean choice')

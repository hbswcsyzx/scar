"""Observed entries of shared source bodies with conditional source anchors.

IDs and ports refer to original evidence. Multiple anchors remain alternatives;
these records assert neither parameter aliases nor concrete namespace instances.
"""
from dataclasses import dataclass

from . import normal_graph as G, source_productions as P
from .ids import ProviderID
from .normal_targets import GlobalPort
from .normal_links import CodeScopeWitness, CodeScopeRef
from .call_edges import CapturedCode, CapturedSite, FrameEntry, FrameExit, CallRecordAnchor, InvocationKey
from .signature_patterns import GroundType
from .source_body_interfaces import SourceBodyCompletion, _port, _types


def _tuple(values, kind, label):
    if type(values) is not tuple or any(type(value) is not kind for value in values):
        raise ValueError(label + ' requires exact typed records in a tuple')


def _anchor(value):
    if type(value) is not CallRecordAnchor:
        raise ValueError('activation requires an original call-record anchor')
    value.__post_init__()
    if type(value.index) is not int or value.index < 1:
        raise ValueError('activation evidence requires a real positive frame-event index')


@dataclass(frozen=True, slots=True)
class SourceActivationAnchor:
    site: CapturedSite
    operation: GlobalPort
    scope: CodeScopeWitness
    arguments: tuple[GlobalPort, ...]
    types: tuple[GroundType, ...]
    completions: tuple[SourceBodyCompletion, ...]

    def __post_init__(self):
        if type(self.site) is not CapturedSite:
            raise ValueError('activation source anchor requires its captured caller site')
        self.site.__post_init__()
        p = _port(self.operation,G.PortKind.ENTER,ordinal=0)
        if (type(p.owner) is not P.ProductionStepID or type(self.scope) is not CodeScopeWitness
                or type(self.scope.owner) is not CodeScopeRef or type(self.scope.region) is not P.ProductionRegionID
                or self.scope.owner.unit != self.operation.unit or self.scope.template != p.template
                or type(self.scope.source_scope) is not int or self.scope.source_scope < 0):
            raise ValueError('activation anchor needs its original step and source code scope')
        self.scope.owner.__post_init__(); _types(self.types)
        _tuple(self.arguments,GlobalPort,'activation arguments')
        if len(self.arguments) != len(self.types):
            raise ValueError('activation argument count differs from original source types')
        for argument in self.arguments:
            a = _port(argument)
            if ((argument.unit,a.template) != (self.operation.unit,p.template)
                    or a.kind not in (G.PortKind.PARAMETER,G.PortKind.ARGUMENT,G.PortKind.RESULT,G.PortKind.CALL_RESULT)):
                raise ValueError('activation input must retain its original value port in the same unit/template')
        _tuple(self.completions,SourceBodyCompletion,'activation completions')
        labels = set()
        for completion in self.completions:
            completion.__post_init__()
            if (completion.exit.unit != self.operation.unit or completion.exit.port.template != p.template
                    or completion.exit.port.owner != p.owner):
                raise ValueError('activation completion must retain its original step output')
            label = completion.kind,completion.target
            if label in labels:raise ValueError('duplicate source-step completion kind/target')
            labels.add(label)


@dataclass(frozen=True, slots=True)
class SourceBodyActivation:
    id: ProviderID
    code_link: ProviderID
    interface: ProviderID
    code: CapturedCode
    path: tuple[CapturedSite, ...]
    suspended: bool
    caller_links: tuple[ProviderID, ...]
    path_index: int | None
    anchors: tuple[SourceActivationAnchor, ...]

    def __post_init__(self):
        if (any(type(value) is not ProviderID for value in (self.id,self.code_link,self.interface))
                or type(self.code) is not CapturedCode or type(self.suspended) is not bool):
            raise ValueError('body activation requires typed shared evidence/interface identities')
        self.code.__post_init__()
        if self.suspended != bool(self.code.flags & (0x20|0x80|0x200)):
            raise ValueError('activation suspension capability differs from the captured code flags')
        _tuple(self.path,CapturedSite,'activation path')
        for site in self.path:site.__post_init__()
        _tuple(self.caller_links,ProviderID,'activation caller links')
        _tuple(self.anchors,SourceActivationAnchor,'activation source anchors')
        if len(set(self.caller_links)) != len(self.caller_links):
            raise ValueError('activation repeats an original caller correspondence')
        if self.path_index is None:
            if self.caller_links or self.anchors:
                raise ValueError('unselected path cannot claim source caller links or anchors')
        elif (type(self.path_index) is not int or not 0 <= self.path_index < len(self.path)
                or not self.caller_links):
            raise ValueError('selected source path needs an in-range site and retained caller alternatives')
        for anchor in self.anchors:
            anchor.__post_init__()
            if anchor.site != self.path[self.path_index]:
                raise ValueError('activation source anchor differs from its original selected path site')


@dataclass(frozen=True, slots=True)
class SourceBodyActivationObservation:
    activation: ProviderID
    entry: FrameEntry
    exit: FrameExit | None

    def __post_init__(self):
        if (type(self.activation) is not ProviderID or type(self.entry) is not FrameEntry
                or type(self.entry.invocation) is not InvocationKey):
            raise ValueError('body activation observation requires its actual frame entry')
        self.entry.invocation.__post_init__(); _anchor(self.entry.anchor)
        if type(self.entry.code) is not str or not self.entry.code:
            raise ValueError('activation frame entry must retain its captured code identity')
        if self.exit is not None:
            if (type(self.exit) is not FrameExit or type(self.exit.invocation) is not InvocationKey
                    or type(self.exit.return_site) is not CapturedSite):
                raise ValueError('body activation exit must be an original frame record')
            self.exit.invocation.__post_init__(); _anchor(self.exit.anchor); self.exit.return_site.__post_init__()
            if (self.entry.invocation != self.exit.invocation or self.entry.code != self.exit.code
                    or self.exit.return_site.code != self.exit.code
                    or self.exit.anchor.index <= self.entry.anchor.index):
                raise ValueError('activation exit differs in invocation, code or temporal order')


@dataclass(frozen=True, slots=True)
class SourceBodyActivationParent:
    parent: ProviderID
    child: ProviderID
    observation: CallRecordAnchor
    direct: bool

    def __post_init__(self):
        if (type(self.parent) is not ProviderID or type(self.child) is not ProviderID
                or type(self.direct) is not bool):
            raise ValueError('activation parent relation needs typed identities and explicit directness')
        _anchor(self.observation)


@dataclass(frozen=True, slots=True)
class SourceBodyActivationFrontier:
    entry: FrameEntry
    reason: str

    def __post_init__(self):
        if type(self.entry) is not FrameEntry or type(self.reason) is not str or not self.reason:
            raise ValueError('activation frontier needs its original frame and a specific reason')
        _anchor(self.entry.anchor)

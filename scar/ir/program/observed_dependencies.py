"""Run-scoped interface occurrences referencing the shared static graph.

These ports bind original interfaces to one CALL occurrence. They are not
Tensor value samples, loop iteration coordinates, or a second execution IR.
In particular NORMAL_INTERFACE is a declared caller landing for an observed
callee return, not an independently captured caller instruction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .call_edges import CallRecordAnchor, InvocationKey
from .dependencies import DependencyCondition, DependencyEdge, DependencyPoint
from .ids import OperationID, RegionID, UseID, ValueID


@dataclass(frozen=True, slots=True)
class ObservedCallScope:
    run_scope: str
    caller: InvocationKey
    attempt_index: int
    attempt_anchor: CallRecordAnchor
    target_anchor: CallRecordAnchor
    callee: InvocationKey | None = None
    entry_anchor: CallRecordAnchor | None = None
    frame_entry: CallRecordAnchor | None = None
    exit_anchor: CallRecordAnchor | None = None

    def __post_init__(self):
        if (type(self.run_scope) is not str or re.fullmatch(r'[0-9a-f]{64}', self.run_scope) is None
                or type(self.caller) is not InvocationKey or type(self.attempt_index) is not int
                or self.attempt_index < 1):
            raise ValueError('observed scope needs original run, caller and exact attempt')
        self.caller.__post_init__()
        for anchor in (self.attempt_anchor, self.target_anchor):
            if type(anchor) is not CallRecordAnchor:
                raise TypeError('observed scope needs original event anchors')
            anchor.__post_init__()
        if self.callee is None:
            if any(item is not None for item in (self.entry_anchor, self.frame_entry, self.exit_anchor)):
                raise ValueError('missing direct callee cannot supply invented entry/exit anchors')
        else:
            if (type(self.callee) is not InvocationKey or self.callee == self.caller
                    or (self.callee.process_id, self.callee.thread_id)
                    != (self.caller.process_id, self.caller.thread_id)):
                raise ValueError('direct observed callee changed original activation/process/thread')
            self.callee.__post_init__()
            for anchor in (self.entry_anchor, self.frame_entry):
                if type(anchor) is not CallRecordAnchor:
                    raise TypeError('direct observed callee requires both retained entry anchors')
                anchor.__post_init__()
            if self.exit_anchor is not None:
                if type(self.exit_anchor) is not CallRecordAnchor:
                    raise TypeError('observed exit needs its original event anchor')
                self.exit_anchor.__post_init__()


class ObservedPortPhase(str, Enum):
    CALL_SITE = 'CALL_SITE'
    ENTRY_INTERFACE = 'ENTRY_INTERFACE'
    RETURN_SITE = 'RETURN_SITE'
    NORMAL_INTERFACE = 'NORMAL_INTERFACE'


@dataclass(frozen=True, slots=True)
class ObservedPortPoint:
    original: DependencyPoint
    scope: ObservedCallScope
    phase: ObservedPortPhase

    def __post_init__(self):
        if (type(self.original) is not DependencyPoint or type(self.scope) is not ObservedCallScope
                or type(self.phase) is not ObservedPortPhase):
            raise TypeError('observed port needs original static point, scope and typed phase')
        self.original.__post_init__()
        self.scope.__post_init__()
        if self.original.context is not None:
            raise ValueError('observed port uses a static anchor, never an invented runtime context')
        types = {
            ObservedPortPhase.CALL_SITE: (OperationID, UseID),
            ObservedPortPhase.ENTRY_INTERFACE: (RegionID, ValueID),
            ObservedPortPhase.RETURN_SITE: (UseID,),
            ObservedPortPhase.NORMAL_INTERFACE: (ValueID,),
        }
        if type(self.original.node) not in types[self.phase]:
            raise ValueError('observed interface phase has an incompatible original endpoint')
        if self.phase is not ObservedPortPhase.CALL_SITE and self.scope.callee is None:
            raise ValueError('no direct callee was captured for this interface')
        if self.phase in (ObservedPortPhase.RETURN_SITE, ObservedPortPhase.NORMAL_INTERFACE) \
                and self.scope.exit_anchor is None:
            raise ValueError('normal return interface needs its original exit witness')

    @property
    def invocation(self):
        return (self.scope.caller if self.phase in (ObservedPortPhase.CALL_SITE,
            ObservedPortPhase.NORMAL_INTERFACE) else self.scope.callee)

    @property
    def witness(self):
        if self.phase is ObservedPortPhase.CALL_SITE:
            return self.scope.attempt_anchor
        if self.phase is ObservedPortPhase.ENTRY_INTERFACE:
            return self.scope.frame_entry
        return self.scope.exit_anchor


@dataclass(frozen=True, slots=True)
class ObservedDependencyEdge:
    template: DependencyEdge
    source: ObservedPortPoint
    target: ObservedPortPoint

    def __post_init__(self):
        if (type(self.template) is not DependencyEdge or type(self.source) is not ObservedPortPoint
                or type(self.target) is not ObservedPortPoint):
            raise TypeError('observed relation requires typed original and scoped endpoints')
        self.template.__post_init__()
        self.source.__post_init__()
        self.target.__post_init__()
        if (self.source.scope != self.target.scope or self.source.original != self.template.source
                or self.target.original != self.template.target):
            raise ValueError('observed relation mixed CALL occurrences or changed its original ports')

    @property
    def kind(self):
        return self.template.kind

    @property
    def meaning(self):
        return self.template.meaning


@dataclass(frozen=True, slots=True)
class ObservedCallLayout:
    """One admitted CALL ABI alternative, not an observed branch choice.

    Source parameter ports are unchanged. Missing defaults and implicit or
    packed inputs remain explicit obligations under this layout's condition.
    """
    scope: ObservedCallScope
    implicit_prefix: int
    condition: DependencyCondition | None
    default_formals: tuple[ObservedPortPoint, ...]
    implicit_formals: tuple[ObservedPortPoint, ...]
    packed_formals: tuple[ObservedPortPoint, ...]

    def __post_init__(self):
        if (type(self.scope) is not ObservedCallScope or type(self.implicit_prefix) is not int
                or self.implicit_prefix not in (0, 1)):
            raise ValueError('observed CALL layout needs its original scope and finite prefix')
        self.scope.__post_init__()
        if self.condition is not None:
            if type(self.condition) is not DependencyCondition:
                raise TypeError('CALL layout condition must be a typed original predicate')
            self.condition.__post_init__()
            if (self.condition.domain != 'SCAR_CALL_ABI'
                    or self.condition.name != 'IMPLICIT_POSITIONAL_PREFIX'
                    or self.condition.index != self.implicit_prefix
                    or self.condition.subject is None
                    or type(self.condition.subject.node) is not OperationID):
                raise ValueError('CALL layout condition changed its original protocol variable')
        for rows in (self.default_formals, self.implicit_formals, self.packed_formals):
            if type(rows) is not tuple or len(set(rows)) != len(rows):
                raise TypeError('CALL layout ports must be immutable and unique')
            for port in rows:
                if (type(port) is not ObservedPortPoint or port.scope != self.scope
                        or port.phase is not ObservedPortPhase.ENTRY_INTERFACE
                        or type(port.original.node) is not ValueID):
                    raise ValueError('CALL layout obligation changed its original callee parameter')


@dataclass(frozen=True, slots=True)
class ObservedDependencyFrontier:
    point: ObservedPortPoint
    kind: str
    detail: str

    def __post_init__(self):
        if (type(self.point) is not ObservedPortPoint or any(type(value) is not str or not value
                for value in (self.kind, self.detail))):
            raise ValueError('observed frontier needs its original scoped port and explicit reason')


@dataclass(frozen=True, slots=True)
class ObservedDependencyNeighborhood:
    """Recorded interface edges; enumeration does not close runtime effects."""
    edges: tuple[ObservedDependencyEdge, ...] = ()
    frontiers: tuple[ObservedDependencyFrontier, ...] = ()
    enumerated: bool = True

    def __post_init__(self):
        if (type(self.edges) is not tuple or any(type(row) is not ObservedDependencyEdge for row in self.edges)
                or type(self.frontiers) is not tuple
                or any(type(row) is not ObservedDependencyFrontier for row in self.frontiers)
                or type(self.enumerated) is not bool):
            raise TypeError('observed neighborhoods require immutable typed edges/frontiers')

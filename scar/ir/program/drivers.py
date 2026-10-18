"""Typed declarations for resumable object creation and body driving.

These records reference canonical operation Uses, completion ports, CFG blocks,
and resumable-body slots. They are structural declarations only: they do not
establish source correspondence, runtime object identity, guard execution, or
transformation authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.providers import ProviderFactReference


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _tuple(value, name):
    _exact(value, tuple, name)


def _unique(values, name):
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")


def _index(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


class DriverRuleProfile(str, Enum):
    PYTHON_RESUMPTION_V1 = "PYTHON_RESUMPTION_V1"


@dataclass(frozen=True, slots=True)
class DriverRule:
    profile: DriverRuleProfile
    implementation: ProviderFactReference

    def __post_init__(self):
        _exact(self.profile, DriverRuleProfile, "driver rule profile")
        _record(self.implementation, ProviderFactReference, "driver rule implementation")


@dataclass(frozen=True, slots=True)
class NormalResultPort:
    """Index of a NORMAL signature result on the owning INVOKE record."""

    index: int

    def __post_init__(self):
        _index(self.index, "normal result port index")


class RawRequestKind(str, Enum):
    NEXT = "NEXT"
    SEND = "SEND"
    THROW = "THROW"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class RawRequestDefinition:
    value: ValueID
    kind: RawRequestKind
    operands: tuple[UseID, ...]

    def __post_init__(self):
        _exact(self.value, ValueID, "raw request value")
        _exact(self.kind, RawRequestKind, "raw request kind")
        _tuple(self.operands, "raw request operands")
        for use in self.operands:
            _exact(use, UseID, "raw request operand")
        _unique(self.operands, "raw request operand UseIDs")
        count = len(self.operands)
        if self.kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE) and count != 0:
            raise ValueError(f"{self.kind.value} raw request takes no operands")
        if self.kind is RawRequestKind.SEND and count != 1:
            raise ValueError("SEND raw request takes exactly one operand")
        if self.kind is RawRequestKind.THROW and not 1 <= count <= 3:
            raise ValueError("THROW raw request takes one to three operands")


@dataclass(frozen=True, slots=True)
class CreationCapture:
    formal: ValueID
    source: UseID

    def __post_init__(self):
        _exact(self.formal, ValueID, "creation capture formal")
        _exact(self.source, UseID, "creation capture source")


@dataclass(frozen=True, slots=True)
class ResumableCreate:
    operation: OperationID
    body: RegionID
    function_object: UseID
    captures: tuple[CreationCapture, ...]
    handle_result: NormalResultPort
    rule: DriverRule

    def __post_init__(self):
        _exact(self.operation, OperationID, "resumable create operation")
        _exact(self.body, RegionID, "resumable create body")
        _exact(self.function_object, UseID, "resumable create function object")
        _tuple(self.captures, "resumable create captures")
        for capture in self.captures:
            _record(capture, CreationCapture, "resumable create capture")
        _unique(tuple(capture.formal for capture in self.captures),
                "resumable create capture formals")
        _unique(tuple(capture.source for capture in self.captures),
                "resumable create capture source Uses")
        _record(self.handle_result, NormalResultPort, "resumable create handle result")
        _record(self.rule, DriverRule, "resumable create rule")


@dataclass(frozen=True, slots=True)
class AsyncRequestCreate:
    operation: OperationID
    body: UseID
    latent: UseID
    request_result: NormalResultPort
    rule: DriverRule

    def __post_init__(self):
        _exact(self.operation, OperationID, "async request create operation")
        _exact(self.body, UseID, "async request body operand")
        _exact(self.latent, UseID, "async request latent operand")
        if self.body == self.latent:
            raise ValueError("async request body and latent Uses must be distinct")
        _record(self.request_result, NormalResultPort, "async request result")
        _record(self.rule, DriverRule, "async request create rule")


@dataclass(frozen=True, slots=True)
class RequestAssociationRead:
    operation: OperationID
    request: UseID
    body_result: NormalResultPort
    latent_result: NormalResultPort
    rule: DriverRule

    def __post_init__(self):
        _exact(self.operation, OperationID, "request association operation")
        _exact(self.request, UseID, "request association request operand")
        _record(self.body_result, NormalResultPort, "request association body result")
        _record(self.latent_result, NormalResultPort, "request association latent result")
        if self.body_result.index == self.latent_result.index:
            raise ValueError("association body and latent results need distinct ports")
        _record(self.rule, DriverRule, "request association rule")


class DriverReceiverKind(str, Enum):
    BODY = "BODY"
    ASYNC_REQUEST = "ASYNC_REQUEST"


@dataclass(frozen=True, slots=True)
class DriverInterface:
    region: RegionID
    body: RegionID
    receiver_kind: DriverReceiverKind
    receiver: ValueID
    scheduler_request: ValueID
    lifecycle: tuple[LocationID, ...]
    rule: DriverRule

    def __post_init__(self):
        _exact(self.region, RegionID, "driver interface region")
        _exact(self.body, RegionID, "driver interface body")
        _exact(self.receiver_kind, DriverReceiverKind, "driver receiver kind")
        _exact(self.receiver, ValueID, "driver receiver value")
        _exact(self.scheduler_request, ValueID, "driver scheduler request value")
        _tuple(self.lifecycle, "driver lifecycle locations")
        if not self.lifecycle:
            raise ValueError("driver lifecycle locations must be nonempty")
        for location in self.lifecycle:
            _exact(location, LocationID, "driver lifecycle location")
        _unique(self.lifecycle, "driver lifecycle locations")
        _record(self.rule, DriverRule, "driver interface rule")


@dataclass(frozen=True, slots=True)
class BodyStart:
    body: RegionID

    def __post_init__(self):
        _exact(self.body, RegionID, "body start region")


@dataclass(frozen=True, slots=True)
class BodyResume:
    suspend: OperationID
    successor: int

    def __post_init__(self):
        _exact(self.suspend, OperationID, "body resume suspension")
        _index(self.successor, "body resume successor")


@dataclass(frozen=True, slots=True)
class BodyStateInput:
    location: LocationID
    source: UseID

    def __post_init__(self):
        _exact(self.location, LocationID, "body state input location")
        _exact(self.source, UseID, "body state input source")


@dataclass(frozen=True, slots=True)
class BodyResumeInput:
    slot: int
    source: UseID

    def __post_init__(self):
        _index(self.slot, "body resume input slot")
        _exact(self.source, UseID, "body resume input source")


@dataclass(frozen=True, slots=True)
class FinalBodyGate:
    operation: OperationID
    drive: OperationID
    body_argument: int
    scheduler_argument: int
    session_argument: int | None
    delivery_arguments: tuple[int, ...]

    def __post_init__(self):
        _exact(self.operation, OperationID, "final body gate operation")
        _exact(self.drive, OperationID, "final body gate drive")
        for name in ("body_argument", "scheduler_argument"):
            _index(getattr(self, name), "final body gate " + name)
        if self.session_argument is not None:
            _index(self.session_argument, "final body gate session argument")
        _tuple(self.delivery_arguments, "final body gate delivery arguments")
        for index in self.delivery_arguments:
            _index(index, "final body gate delivery argument")
        roles = [self.body_argument, self.scheduler_argument, *self.delivery_arguments]
        if self.session_argument is not None:
            roles.append(self.session_argument)
        _unique(tuple(roles), "final body gate argument roles")


# Public target union is represented directly by BodyStart | BodyResume.
BodyDriveTarget = BodyStart | BodyResume


@dataclass(frozen=True, slots=True)
class BodyDrive:
    operation: OperationID
    instance: UseID
    scheduler_request: UseID
    session: UseID | None
    target: BodyDriveTarget
    state_inputs: tuple[BodyStateInput, ...]
    resume_inputs: tuple[BodyResumeInput, ...]

    def __post_init__(self):
        _exact(self.operation, OperationID, "body drive operation")
        _exact(self.instance, UseID, "body drive instance")
        _exact(self.scheduler_request, UseID, "body drive scheduler request")
        if self.session is not None:
            _exact(self.session, UseID, "body drive session")
        if type(self.target) not in (BodyStart, BodyResume):
            raise TypeError("body drive target must be exact BodyStart or BodyResume")
        self.target.__post_init__()
        _tuple(self.state_inputs, "body drive state inputs")
        for item in self.state_inputs:
            _record(item, BodyStateInput, "body drive state input")
        _unique(tuple(item.location for item in self.state_inputs),
                "body drive state input locations")
        _tuple(self.resume_inputs, "body drive resume inputs")
        for item in self.resume_inputs:
            _record(item, BodyResumeInput, "body drive resume input")
        _unique(tuple(item.slot for item in self.resume_inputs),
                "body drive resume input slots")
        _unique(self.actual_uses, "body drive actual Uses")

    @property
    def actual_uses(self) -> tuple[UseID, ...]:
        return (
            self.instance, self.scheduler_request,
            *((self.session,) if self.session is not None else ()),
            *(item.source for item in self.state_inputs),
            *(item.source for item in self.resume_inputs),
        )


@dataclass(frozen=True, slots=True)
class BodyDriveResult:
    index: int

    def __post_init__(self):
        _index(self.index, "body drive result index")


@dataclass(frozen=True, slots=True)
class BodyDriveSuccessor:
    source: OperationID
    block: BlockID
    arguments: tuple[UseID | BodyDriveResult, ...]

    def __post_init__(self):
        _exact(self.source, OperationID, "body drive outcome source")
        _exact(self.block, BlockID, "body drive successor block")
        _tuple(self.arguments, "body drive successor arguments")
        for argument in self.arguments:
            if type(argument) is UseID:
                continue
            if type(argument) is BodyDriveResult:
                argument.__post_init__()
                continue
            raise TypeError("body drive successor arguments must be exact UseID or BodyDriveResult")


@dataclass(frozen=True, slots=True)
class BodyDriveTerminator:
    successors: tuple[BodyDriveSuccessor, ...]

    def __post_init__(self):
        _tuple(self.successors, "body drive successors")
        for item in self.successors:
            _record(item, BodyDriveSuccessor, "body drive successor")
        _unique(tuple(item.source for item in self.successors), "body drive outcome sources")
        _unique(tuple(item.block for item in self.successors), "body drive landing blocks")

    @property
    def kind(self):
        from scar.ir.program.model import TerminatorKind
        return TerminatorKind.BODY_DRIVE

    @property
    def values(self):
        return ()

    @property
    def condition(self):
        return None

    @property
    def exit(self):
        return None


__all__ = [
    "AsyncRequestCreate", "BodyDrive", "BodyDriveResult", "BodyDriveSuccessor",
    "BodyDriveTarget", "BodyDriveTerminator", "BodyResume", "BodyResumeInput",
    "BodyStart", "BodyStateInput", "CreationCapture", "DriverInterface",
    "DriverReceiverKind", "DriverRule", "DriverRuleProfile", "FinalBodyGate",
    "NormalResultPort", "RawRequestDefinition", "RawRequestKind",
    "RequestAssociationRead", "ResumableCreate",
]

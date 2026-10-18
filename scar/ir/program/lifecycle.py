"""Typed lifecycle declarations for resumable body outcome publication.

These records point to existing driver operations, values, and uses. They are
static declarations only; they do not establish source/runtime correspondence
or transformation authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.structured import ControlEdgeReference


def _exact(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be exact {expected.__name__}")


def _record(value: object, expected: type, name: str) -> None:
    _exact(value, expected, name)
    value.__post_init__()


@dataclass(frozen=True, slots=True)
class DriverLifecycle:
    """Enables lifecycle declarations for one existing driver interface region."""

    region: RegionID

    def __post_init__(self) -> None:
        _exact(self.region, RegionID, "driver lifecycle region")


@dataclass(frozen=True, slots=True)
class DriveOutcomeRef:
    """Names one body drive and one actual source successor operation."""

    drive: OperationID
    source: OperationID

    def __post_init__(self) -> None:
        _exact(self.drive, OperationID, "outcome driver operation")
        _exact(self.source, OperationID, "outcome source operation")


@dataclass(frozen=True, slots=True)
class BodyOutcomeCommit:
    """Declares the first publication operation for one drive source."""

    operation: OperationID
    outcome: DriveOutcomeRef
    instance: UseID

    def __post_init__(self) -> None:
        _exact(self.operation, OperationID, "body outcome commit operation")
        _record(self.outcome, DriveOutcomeRef, "body outcome reference")
        _exact(self.instance, UseID, "body outcome commit instance")


@dataclass(frozen=True, slots=True)
class CreatedCloseTest:
    """Declares a typed test for a created body and close request.

    The graph validator joins each role Use to its exact driver input/source;
    this record does not prove predicate behavior or purity.
    """

    operation: OperationID
    instance: UseID
    scheduler_request: UseID
    effective_request: UseID
    session: UseID | None
    result: ValueID

    def __post_init__(self) -> None:
        _exact(self.operation, OperationID, "created-close test operation")
        role_uses = [self.instance, self.scheduler_request, self.effective_request]
        for name in ("instance", "scheduler_request", "effective_request"):
            _exact(getattr(self, name), UseID, "created-close test " + name)
        if self.session is not None:
            _exact(self.session, UseID, "created-close test session")
            role_uses.append(self.session)
        if len(set(role_uses)) != len(role_uses):
            raise ValueError("created-close role UseIDs must be distinct")
        _exact(self.result, ValueID, "created-close test result")


@dataclass(frozen=True, slots=True)
class NoBodyFinish:
    """Declares a body-only terminal mark on a created-close true edge."""

    operation: OperationID
    precondition: ControlEdgeReference
    instance: UseID

    def __post_init__(self) -> None:
        _exact(self.operation, OperationID, "no-body finish operation")
        _record(self.precondition, ControlEdgeReference, "no-body finish precondition")
        _exact(self.instance, UseID, "no-body finish instance")


__all__ = [
    "DriverLifecycle", "DriveOutcomeRef", "BodyOutcomeCommit",
    "CreatedCloseTest", "NoBodyFinish",
]

"""Typed lifecycle declarations for resumable body outcome publication.

These records point to existing driver operations, values, and uses. They are
static declarations only; they do not establish source/runtime correspondence
or transformation authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.ids import OperationID, RegionID, UseID


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


__all__ = ["DriverLifecycle", "DriveOutcomeRef", "BodyOutcomeCommit"]

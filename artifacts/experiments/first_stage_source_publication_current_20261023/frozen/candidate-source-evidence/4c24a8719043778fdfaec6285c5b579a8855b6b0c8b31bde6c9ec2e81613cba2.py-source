"""Conditional source rules for frame lifetime, without a second dependency graph.

All dependency endpoints live in the program core. These records identify the
source rule applied to an operation; they never certify its runtime conditions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from scar.ir.program.ids import OperationID, RegionID, UseID
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors
from scar.ir.v2.common import Completeness, ProofStatus, SourceReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


class FrameRuleVersion(str, Enum):
    PYTHON_FRAME_V1 = "PYTHON_FRAME_V1"


class FrameCondition(str, Enum):
    # Excludes external mutation of active locals/control and unmodeled
    # trace/profile/asynchronous replacement of a frame transition's completion.
    # Ordinary finalizer mutations of objects or external state remain possible.
    NO_FRAME_INTERPOSITION = "NO_FRAME_INTERPOSITION"


class FrameCompletionRule(str, Enum):
    PRESERVE_PENDING_IF_COMPLETED = "PRESERVE_PENDING_IF_COMPLETED"


class FrameTermination(str, Enum):
    MAY_NOT_COMPLETE = "MAY_NOT_COMPLETE"


class FrameFinalizerErrors(str, Enum):
    UNRAISABLE = "UNRAISABLE"


class FrameRelease(str, Enum):
    NOT_GUARANTEED = "NOT_GUARANTEED"


@dataclass(frozen=True, slots=True)
class FrameRules:
    """Fixed rule semantics, explicitly separate from its unproved condition.

    There is deliberately no writable authority/termination/free boolean.
    The rule is completion-preserving *if applicable and completed*; UNKNOWN
    applicability and effects cannot be promoted by decoding a report.
    """

    version: FrameRuleVersion = FrameRuleVersion.PYTHON_FRAME_V1
    condition: FrameCondition = FrameCondition.NO_FRAME_INTERPOSITION
    condition_status: ProofStatus = ProofStatus.UNKNOWN
    completion: FrameCompletionRule = FrameCompletionRule.PRESERVE_PENDING_IF_COMPLETED
    effects: Completeness = Completeness.UNKNOWN
    termination: FrameTermination = FrameTermination.MAY_NOT_COMPLETE
    finalizer_errors: FrameFinalizerErrors = FrameFinalizerErrors.UNRAISABLE
    release: FrameRelease = FrameRelease.NOT_GUARANTEED

    def __post_init__(self):
        fixed = (
            ("version", FrameRuleVersion.PYTHON_FRAME_V1),
            ("condition", FrameCondition.NO_FRAME_INTERPOSITION),
            ("condition_status", ProofStatus.UNKNOWN),
            ("completion", FrameCompletionRule.PRESERVE_PENDING_IF_COMPLETED),
            ("effects", Completeness.UNKNOWN),
            ("termination", FrameTermination.MAY_NOT_COMPLETE),
            ("finalizer_errors", FrameFinalizerErrors.UNRAISABLE),
            ("release", FrameRelease.NOT_GUARANTEED),
        )
        for name, expected in fixed:
            if getattr(self, name) is not expected:
                raise ValueError(f"FrameRules.{name} must remain {expected.value}")


class FrameTransitionKind(str, Enum):
    ENTER = "ENTER"
    BIND = "BIND"
    DISCARD = "DISCARD"
    EXIT = "EXIT"


def _typed(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _source(value):
    _typed(value, SourceReference, "source")
    errors = record_errors(value, SourceReference, "source")
    if errors:
        raise ValueError("; ".join(errors))


def _operation_source(operation, source):
    _typed(operation, OperationID, "operation")
    _source(source)


@dataclass(frozen=True, slots=True)
class FrameFormal:
    slot: ValueSlotID
    use: UseID

    def __post_init__(self):
        _typed(self.slot, ValueSlotID, "slot")
        _typed(self.use, UseID, "use")


@dataclass(frozen=True, slots=True)
class FrameEnter:
    operation: OperationID
    source: SourceReference
    formals: tuple[FrameFormal, ...]

    def __post_init__(self):
        _operation_source(self.operation, self.source)
        _typed(self.formals, tuple, "formals")
        for formal in self.formals:
            _typed(formal, FrameFormal, "formal")
            formal.__post_init__()
        if (len({formal.slot for formal in self.formals}) != len(self.formals)
                or len({formal.use for formal in self.formals}) != len(self.formals)):
            raise ValueError("frame formals need distinct slots and use sites")

    @property
    def kind(self):
        return FrameTransitionKind.ENTER


@dataclass(frozen=True, slots=True)
class FrameBind:
    operation: OperationID
    source: SourceReference
    slot: ValueSlotID
    assigned: UseID

    def __post_init__(self):
        _operation_source(self.operation, self.source)
        _typed(self.slot, ValueSlotID, "slot")
        _typed(self.assigned, UseID, "assigned")

    @property
    def kind(self):
        return FrameTransitionKind.BIND


@dataclass(frozen=True, slots=True)
class FrameDiscard:
    operation: OperationID
    source: SourceReference
    reference: UseID

    def __post_init__(self):
        _operation_source(self.operation, self.source)
        _typed(self.reference, UseID, "reference")

    @property
    def kind(self):
        return FrameTransitionKind.DISCARD


@dataclass(frozen=True, slots=True)
class FrameExit:
    operation: OperationID
    source: SourceReference
    completion: OperationID
    payload: UseID

    def __post_init__(self):
        _operation_source(self.operation, self.source)
        _typed(self.completion, OperationID, "completion")
        _typed(self.payload, UseID, "payload")
        if self.completion == self.operation:
            raise ValueError("frame transition and completion are distinct operations")

    @property
    def kind(self):
        return FrameTransitionKind.EXIT


# Distinct exact field sets disambiguate this union in the strict record codec.
# No label, duplicated pending kind, or duplicated before/after world is stored.
FrameTransition: TypeAlias = FrameEnter | FrameBind | FrameDiscard | FrameExit


@dataclass(frozen=True, slots=True)
class FrameModel:
    definition: OperationDefinitionID
    region: RegionID
    source: SourceReference
    transitions: tuple[FrameTransition, ...]
    rules: FrameRules = FrameRules()

    def __post_init__(self):
        _typed(self.definition, OperationDefinitionID, "definition")
        _typed(self.region, RegionID, "region")
        _source(self.source)
        _typed(self.transitions, tuple, "transitions")
        for transition in self.transitions:
            if type(transition) not in (FrameEnter, FrameBind, FrameDiscard, FrameExit):
                raise TypeError("transitions must contain typed frame transitions")
            transition.__post_init__()
        _typed(self.rules, FrameRules, "rules")
        self.rules.__post_init__()
        if sum(type(item) is FrameEnter for item in self.transitions) != 1:
            raise ValueError("one frame ENTER is required")
        operations = [item.operation for item in self.transitions]
        if len(set(operations)) != len(operations):
            raise ValueError("one transition per frame operation is required")
        completions = [item.completion for item in self.transitions if type(item) is FrameExit]
        if len(set(completions)) != len(completions):
            raise ValueError("one frame EXIT per completion is required")

    def to_dict(self):
        errors = record_errors(self, FrameModel, "frame")
        if errors:
            raise ValueError("; ".join(errors))
        return encode(self)

    @classmethod
    def from_dict(cls, document):
        """Decode records only; graph/source correspondence needs the validator."""
        return decode(cls, document)


__all__ = [
    "FrameRuleVersion", "FrameCondition", "FrameCompletionRule", "FrameTermination",
    "FrameFinalizerErrors", "FrameRelease", "FrameRules", "FrameTransitionKind",
    "FrameFormal", "FrameEnter", "FrameBind", "FrameDiscard", "FrameExit",
    "FrameTransition", "FrameModel",
]

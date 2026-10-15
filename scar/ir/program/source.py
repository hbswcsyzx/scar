"""Typed source correspondence for automatic program construction.

These records describe source provenance and outstanding conditions, not
runtime identity, resolved dispatch, or permission to transform a program.
Cross-record checks and deterministic source replay belong to the lowerer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import ExitKind
from scar.ir.semantics_v2 import Opcode, SourceExecutionPrecondition, SourceSnapshot
from scar.ir.v2.common import EvidenceKind, SourceReference
from scar.ir.v2.ids import BindingUseID, OperationDefinitionID, StaticValueID, ValueSlotID


class SourceRole(str, Enum):
    PARAMETER = "PARAMETER"
    EXPRESSION = "EXPRESSION"
    LOCAL_BINDING = "LOCAL_BINDING"
    MERGE = "MERGE"
    CONTROL = "CONTROL"
    TRUTH = "TRUTH"
    RETURN = "RETURN"
    FUNCTION_OBJECT = "FUNCTION_OBJECT"
    STATE = "STATE"
    EXCEPTION = "EXCEPTION"


class GapKind(str, Enum):
    UNSUPPORTED_SYNTAX = "UNSUPPORTED_SYNTAX"
    UNBOUND_LOCAL = "UNBOUND_LOCAL"
    DYNAMIC_TARGET = "DYNAMIC_TARGET"
    EFFECT_SUMMARY = "EFFECT_SUMMARY"
    CODE_VERSION = "CODE_VERSION"
    IMPLICIT_COMPLETION = "IMPLICIT_COMPLETION"
    UNSUPPORTED_SIGNATURE = "UNSUPPORTED_SIGNATURE"
    SOURCE_MAPPING = "SOURCE_MAPPING"
    CONTROL_FLOW = "CONTROL_FLOW"
    SOURCE_COVERAGE = "SOURCE_COVERAGE"
    DYNAMIC_DISPATCH = "DYNAMIC_DISPATCH"
    FRAME_EFFECT = "FRAME_EFFECT"
    BUDGET = "BUDGET"


@dataclass(frozen=True, slots=True)
class OperationSource:
    operation: OperationID
    source: SourceReference
    role: SourceRole
    semantic_operation: OperationDefinitionID | None = None
    opcode: Opcode | None = None


@dataclass(frozen=True, slots=True)
class ValueSource:
    value: ValueID
    source: SourceReference
    role: SourceRole
    slot: ValueSlotID | None = None
    semantic_value: StaticValueID | None = None


@dataclass(frozen=True, slots=True)
class UseSource:
    operation: OperationID
    use: UseID
    source: SourceReference
    role: str
    index: int
    semantic_value: StaticValueID | None = None

    def __post_init__(self) -> None:
        if type(self.role) is not str or not self.role:
            raise ValueError("UseSource.role must be non-empty text")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("UseSource.index must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CandidateArgument:
    """One caller operand's conditional correspondence to a body parameter."""

    use: UseID
    parameter: ValueID


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """A caller completion value corresponding to a candidate exit port."""

    kind: ExitKind
    index: int
    value: ValueID

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("CandidateResult.index must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CallTarget:
    operation: OperationID
    callee_reference: ValueID
    candidate: RegionID | None = None
    source_definition: OperationDefinitionID | None = None
    status: EvidenceKind = EvidenceKind.INFERRED
    conditions: tuple[SourceExecutionPrecondition, ...] = ()
    arguments: tuple[CandidateArgument, ...] = ()
    results: tuple[CandidateResult, ...] = ()
    binding_use: BindingUseID | None = None


@dataclass(frozen=True, slots=True)
class LoweringGap:
    kind: GapKind
    source: SourceReference
    detail: str

    def __post_init__(self) -> None:
        if type(self.detail) is not str or not self.detail.strip():
            raise ValueError("LoweringGap.detail must be non-empty text")


@dataclass(frozen=True, slots=True)
class LoweringMetadata:
    entry: str
    source: SourceSnapshot
    operation_links: tuple[OperationSource, ...] = ()
    value_links: tuple[ValueSource, ...] = ()
    call_targets: tuple[CallTarget, ...] = ()
    gaps: tuple[LoweringGap, ...] = ()
    assumptions: tuple[SourceExecutionPrecondition, ...] = ()
    use_links: tuple[UseSource, ...] = ()

    def __post_init__(self) -> None:
        if type(self.entry) is not str or not self.entry.strip():
            raise ValueError("LoweringMetadata.entry must be non-empty text")
        for name in ("operation_links", "value_links", "call_targets", "use_links"):
            records = getattr(self, name)
            if len(set(records)) != len(records):
                raise ValueError(f"LoweringMetadata.{name} contains duplicate records")


__all__ = [
    "SourceRole", "GapKind", "OperationSource", "ValueSource", "UseSource", "CallTarget",
    "CandidateArgument", "CandidateResult", "LoweringGap", "LoweringMetadata",
]

"""Conditional standard class-call protocol over an ordinary canonical graph.

These interfaces describe the CPython construction protocol, not a proof that
an original callable selects it. In particular a logical argument view is not
a materialized Python tuple/dict, and a tp_new result need not be newly allocated
or have the requested class as its exact type. Source callbacks remain open.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import ProgramGraph, ValueKind, ValueType
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.structured import ControlEdgeReference


RULE = "CPYTHON_TYPE_CALL_3147_V1"


def _need(condition, message):
    if not condition:
        raise ValueError("type call provider: " + message)


class TypeCallGuard(str, Enum):
    CALLEE_IS_NON_BUILTIN_TYPE = "CALLEE_CURRENTLY_IS_A_NON_BUILTIN_TYPE_OBJECT"
    STANDARD_CONSTRUCTOR_SELECTED = "SELECTED_METACLASS_CALL_HAS_CPYTHON_3147_STANDARD_CONSTRUCTOR_SEMANTICS"
    OPERAND_LAYOUT_MATCHES = "ORIGINAL_CALL_OPERAND_LAYOUT_MATCHES_LOGICAL_ARGUMENT_VIEW"
    SLOT_ABI_VALID = "CURRENT_NATIVE_NEW_AND_INIT_SLOT_ABI_IS_VALID"
    PROFILE_MATCHES_TARGET = "TARGET_HAS_DECLARED_CPYTHON_3147_TYPE_CALL_PROFILE"


class TypeCallStageKind(str, Enum):
    ARGUMENT_VIEW = "FORM_LOGICAL_CALL_ARGUMENT_VIEW"
    READ_TP_NEW = "READ_CURRENT_CLASS_TP_NEW"
    NEW_PRESENT = "TEST_NATIVE_NEW_SLOT_PRESENT"
    BRANCH_NEW = "BRANCH_ON_NATIVE_NEW_SLOT_PRESENCE"
    RAISE_MISSING_NEW = "RAISE_CANNOT_CREATE_INSTANCE_TYPE_ERROR"
    INVOKE_TP_NEW = "INVOKE_TP_NEW_AND_CHECK_NATIVE_RESULT"
    IS_REQUESTED_INSTANCE = "INTERNAL_RETURNED_OBJECT_SUBTYPE_TEST"
    BRANCH_INSTANCE = "BRANCH_ON_RETURNED_OBJECT_SUBTYPE"
    READ_TP_INIT = "READ_ACTUAL_RETURNED_OBJECT_TYPE_TP_INIT"
    INIT_PRESENT = "TEST_NATIVE_INIT_SLOT_PRESENT"
    BRANCH_INIT = "BRANCH_ON_NATIVE_INIT_SLOT_PRESENCE"
    INVOKE_TP_INIT = "INVOKE_TP_INIT_AND_CHECK_NATIVE_STATUS"
    RELEASE_FAILED_INIT = "RELEASE_OWNED_OBJECT_PRESERVING_PENDING_EXCEPTION"
    RETURN_OBJECT = "RETURN_ORIGINAL_TP_NEW_OBJECT"
    PROPAGATE_RAISE = "PROPAGATE_PENDING_EXCEPTION"


@dataclass(frozen=True, slots=True)
class TypeCallOperand:
    """The original ordered operand's declared role, not a fabricated actual."""
    role: str
    index: int | None = None
    keyword: str | None = None

    def __post_init__(self):
        _need(type(self.role) is str and bool(self.role), "operand role must be nonempty text")
        _need(self.index is None or type(self.index) is int and self.index >= 0,
              "operand index must be absent or a nonnegative integer")
        _need(self.keyword is None or type(self.keyword) is str and bool(self.keyword),
              "operand keyword must be absent or nonempty text")


def validate_type_call_layout(input_types, layout, exception_arity):
    """Check only declared typed layout; it does not verify an original CALL."""
    _need(type(input_types) is tuple and bool(input_types)
          and all(type(item) is ValueType for item in input_types),
          "input types must be a nonempty exact tuple of core ValueTypes")
    for item in input_types:
        item.__post_init__()
    _need(input_types[0] == ValueType(ValueKind.REFERENCE)
          and all(item.kind in (ValueKind.REFERENCE, ValueKind.DATA) for item in input_types),
          "the first input is the callee reference; other inputs are non-world data/references")
    _need(type(layout) is tuple and len(layout) == len(input_types)
          and all(type(item) is TypeCallOperand for item in layout),
          "operand layout must retain one typed entry per original non-world operand")
    for item in layout:
        item.__post_init__()
    _need(layout[0] == TypeCallOperand("callee")
          and all(item.role != "callee" for item in layout[1:]),
          "the first and only callee layout entry must have no argument index/keyword")
    _need(type(exception_arity) is int and exception_arity in (1, 2),
          "exception arity must retain either exception or exception/traceback ports")


@dataclass(frozen=True, slots=True)
class TypeCallCompletion:
    edge: ControlEdgeReference
    payloads: tuple[ValueID, ...]
    world: ValueID

    def __post_init__(self):
        _need(type(self.edge) is ControlEdgeReference, "completion must name its original provider edge")
        self.edge.__post_init__()
        _need(type(self.payloads) is tuple and all(type(value) is ValueID for value in self.payloads)
              and type(self.world) is ValueID and self.world not in self.payloads,
              "completion must retain ordered payloads and a separate world")


@dataclass(frozen=True, slots=True)
class TypeCallStage:
    kind: TypeCallStageKind
    operation: OperationID
    inputs: tuple[UseID, ...]
    results: tuple[ValueID, ...]
    world: UseID | None = None
    normal: TypeCallCompletion | None = None
    raised: TypeCallCompletion | None = None

    def __post_init__(self):
        _need(type(self.kind) is TypeCallStageKind and type(self.operation) is OperationID,
              "stage must name a typed original provider operation")
        _need(type(self.inputs) is tuple and all(type(value) is UseID for value in self.inputs)
              and len(set(self.inputs)) == len(self.inputs), "stage inputs must be distinct operand occurrences")
        _need(type(self.results) is tuple and all(type(value) is ValueID for value in self.results),
              "stage results must retain their original values")
        _need(self.world is None or type(self.world) is UseID and self.world not in self.inputs,
              "stage world must be separate from its non-world operands")
        for completion in (self.normal, self.raised):
            _need(completion is None or type(completion) is TypeCallCompletion,
                  "stage completions must be typed original ports")
            if completion is not None:
                completion.__post_init__()
                _need(completion.edge.operation == self.operation,
                      "completion edge must belong to this stage's operation")


@dataclass(frozen=True, slots=True)
class TypeCallProvider:
    implementation: ProviderArtifact
    rule: str
    input_types: tuple[ValueType, ...]
    layout: tuple[TypeCallOperand, ...]
    exception_arity: int
    graph: ProgramGraph
    inputs: tuple[ValueID, ...]
    world: ValueID
    argument_view: ValueID
    new_object: ValueID
    stages: tuple[TypeCallStage, ...]
    cleanup_operations: tuple[OperationID, ...]
    guards: tuple[TypeCallGuard, ...] = tuple(TypeCallGuard)
    physical_abi_mapping_complete: bool = False
    python_callbacks_connected: bool = False
    effects_complete: bool = False

    def __post_init__(self):
        validate_type_call_layout(self.input_types, self.layout, self.exception_arity)
        _need(type(self.implementation) is ProviderArtifact and type(self.graph) is ProgramGraph,
              "provider needs producer provenance and the canonical graph")
        self.implementation.__post_init__()
        _need(self.rule == RULE and self.guards == tuple(TypeCallGuard),
              "the standard profile and all applicability premises must remain explicit")
        _need(type(self.inputs) is tuple and len(self.inputs) == len(self.input_types)
              and all(type(value) is ValueID for value in self.inputs)
              and len(set(self.inputs)) == len(self.inputs), "provider formals differ from original typed layout")
        _need(all(type(value) is ValueID for value in (self.world, self.argument_view, self.new_object)),
              "provider needs original world, logical view and new-object ports")
        _need(type(self.stages) is tuple and all(type(stage) is TypeCallStage for stage in self.stages)
              and len({stage.operation for stage in self.stages}) == len(self.stages),
              "provider stages must be distinct typed original operations")
        _need(type(self.cleanup_operations) is tuple
              and all(type(operation) is OperationID for operation in self.cleanup_operations)
              and len(set(self.cleanup_operations)) == len(self.cleanup_operations),
              "cleanup must retain its original operations")
        _need(self.physical_abi_mapping_complete is False and self.python_callbacks_connected is False
              and self.effects_complete is False,
              "logical argument transport does not close physical ABI, callbacks or effects")


__all__ = ["RULE", "TypeCallCompletion", "TypeCallGuard", "TypeCallOperand", "TypeCallProvider",
           "TypeCallStage", "TypeCallStageKind", "validate_type_call_layout"]

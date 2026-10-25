"""Conditional operand provenance, separate from observed reference identity."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.call_edges import CallRecordAnchor, InvocationKey
from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceExecutionPrecondition
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _positive(value, name):
    _require(type(value) is int and value > 0, name + " must be an exact positive integer")


class _Record:
    def to_dict(self):
        return encode(self)

    @classmethod
    def from_dict(cls, value):
        return decode(cls, value)


@dataclass(frozen=True, slots=True)
class OperandRouteBudget(_Record):
    max_routes: int = 100_000
    max_template_values: int = 100_000

    def __post_init__(self):
        _positive(self.max_routes, "max_routes")
        _positive(self.max_template_values, "max_template_values")


class OperandRouteCondition(str, Enum):
    CAPTURE_PRODUCER_TRUSTED = "CAPTURE_PRODUCER_TRUSTED"
    NO_FRAME_INTERPOSITION = "NO_FRAME_INTERPOSITION"
    NO_NAMESPACE_MUTATION_BETWEEN_OBSERVATION_AND_LOAD = "NO_NAMESPACE_MUTATION_BETWEEN_OBSERVATION_AND_LOAD"
    OBSERVER_AND_AUDIT_NONINTERFERENCE = "OBSERVER_AND_AUDIT_NONINTERFERENCE"
    MONITORING_DELIVERY_CONTINUITY_UNVERIFIED = "MONITORING_DELIVERY_CONTINUITY_UNVERIFIED"
    SOURCE_CORE_EXECUTION_PRECONDITIONS = "SOURCE_CORE_EXECUTION_PRECONDITIONS"
    FUNCTION_ENVIRONMENT_UNVERIFIED = "FUNCTION_ENVIRONMENT_UNVERIFIED"
    CONTENTS_EFFECTS_AND_WORLD_EQUIVALENCE_UNVERIFIED = "CONTENTS_EFFECTS_AND_WORLD_EQUIVALENCE_UNVERIFIED"


def _conditions(value):
    _require(type(value) is tuple and all(type(item) is OperandRouteCondition for item in value)
             and value == tuple(OperandRouteCondition), "all conditional routing requirements must remain typed")


class ReferenceConsistency(str, Enum):
    AGREES = "AGREES"
    UNKNOWN = "UNKNOWN"


class OperandRouteIssueKind(str, Enum):
    CAPTURE_GAP = "CAPTURE_GAP"
    INSTRUCTION_WINDOW = "INSTRUCTION_WINDOW"
    SOURCE_CORE_BOUNDARY = "SOURCE_CORE_BOUNDARY"
    DISPATCH_BOUNDARY = "DISPATCH_BOUNDARY"
    HANDSHAKE_BOUNDARY = "HANDSHAKE_BOUNDARY"
    REFERENCE_CONTRADICTION = "REFERENCE_CONTRADICTION"
    ARGUMENT_ROUTING_UNVERIFIED = "ARGUMENT_ROUTING_UNVERIFIED"
    COMPLETION_BOUNDARY = "COMPLETION_BOUNDARY"
    CONTROL_SELECTION_UNVERIFIED = "CONTROL_SELECTION_UNVERIFIED"
    OPAQUE_REFERENCE = "OPAQUE_REFERENCE"
    QUERY_BUDGET = "QUERY_BUDGET"
    ROUTE_BUDGET = "ROUTE_BUDGET"
    CYCLE_BOUNDARY = "CYCLE_BOUNDARY"


@dataclass(frozen=True, slots=True)
class OperandRouteIssue(_Record):
    kind: OperandRouteIssueKind
    detail: str
    invocation: InvocationKey | None = None
    anchor: CallRecordAnchor | None = None

    def __post_init__(self):
        _require(type(self.detail) is str and bool(self.detail), "route issue needs detail")


@dataclass(frozen=True, slots=True)
class ArgumentRoute(_Record):
    attempt: CallRecordAnchor
    caller: InvocationKey
    callee: InvocationKey
    actual_index: int
    load_anchor: CallRecordAnchor
    load_suboperand: int
    call: OperationDefinitionID
    call_source: SourceReference
    caller_definition: OperationDefinitionID
    caller_region: RegionID
    operation: OperationID
    actual_source: SourceReference
    actual_use: UseID
    actual_value: ValueID
    callee_definition: OperationDefinitionID
    callee_region: RegionID
    formal_slot: ValueSlotID
    formal_value: ValueID
    formal_name: str
    reference_consistency: ReferenceConsistency
    rule: str = "RAW_FUNCTION_ALL_POSITIONAL_V1"
    conditions: tuple[OperandRouteCondition, ...] = tuple(OperandRouteCondition)

    def __post_init__(self):
        _require(type(self.actual_index) is int and self.actual_index >= 0, "actual index must be nonnegative")
        _require(type(self.load_suboperand) is int and self.load_suboperand >= 0, "load suboperand must be nonnegative")
        _require((self.caller.process_id, self.caller.thread_id) ==
                 (self.callee.process_id, self.callee.thread_id), "argument routes cannot cross process/thread")
        _require(self.caller != self.callee, "argument route needs different frame invocations")
        _require(type(self.formal_name) is str and bool(self.formal_name), "formal name is required")
        _require(self.rule == "RAW_FUNCTION_ALL_POSITIONAL_V1", "unknown argument route rule")
        _require(type(self.reference_consistency) is ReferenceConsistency, "reference consistency must be typed")
        _conditions(self.conditions)


@dataclass(frozen=True, slots=True)
class CompletionRoute(_Record):
    attempt: CallRecordAnchor
    caller: InvocationKey
    callee: InvocationKey
    call: OperationDefinitionID
    call_source: SourceReference
    caller_definition: OperationDefinitionID
    caller_region: RegionID
    operation: OperationID
    normal_result: ValueID
    callee_definition: OperationDefinitionID
    callee_region: RegionID
    exit_anchor: CallRecordAnchor
    payload_use: UseID
    payload_value: ValueID
    post_world: ValueID
    rule: str = "DIRECT_NORMAL_COMPLETION_V1"
    conditions: tuple[OperandRouteCondition, ...] = tuple(OperandRouteCondition)

    def __post_init__(self):
        _require((self.caller.process_id, self.caller.thread_id) ==
                 (self.callee.process_id, self.callee.thread_id), "completion routes cannot cross process/thread")
        _require(self.caller != self.callee, "completion needs different frame invocations")
        _require(self.rule == "DIRECT_NORMAL_COMPLETION_V1", "unknown completion route rule")
        _conditions(self.conditions)


class CoreReferenceKind(str, Enum):
    FORMAL = "FORMAL"
    BLOCK_ARGUMENT = "BLOCK_ARGUMENT"
    CALL_RESULT = "CALL_RESULT"
    LITERAL = "LITERAL"
    OPAQUE_OPERATION = "OPAQUE_OPERATION"


@dataclass(frozen=True, slots=True)
class CoreReferenceValue(_Record):
    value: ValueID
    kind: CoreReferenceKind
    source: SourceReference | None = None
    formal_slot: ValueSlotID | None = None
    formal_name: str | None = None

    def __post_init__(self):
        _require((self.formal_slot is not None and self.formal_name is not None) ==
                 (self.kind is CoreReferenceKind.FORMAL), "only formal values carry a named slot")


@dataclass(frozen=True, slots=True)
class CoreReferenceRoute(_Record):
    destination: ValueID
    source: ValueID
    operation: OperationID
    use: UseID
    successor: int
    port: int

    def __post_init__(self):
        _require(type(self.successor) is int and self.successor >= 0, "successor must be nonnegative")
        _require(type(self.port) is int and self.port >= 0, "port must be nonnegative")


@dataclass(frozen=True, slots=True)
class CoreReferenceTemplate(_Record):
    definition: OperationDefinitionID
    region: RegionID
    values: tuple[CoreReferenceValue, ...]
    routes: tuple[CoreReferenceRoute, ...]

    def __post_init__(self):
        values = {value.value for value in self.values}
        _require(len(values) == len(self.values), "template values must be unique")
        _require(all(route.destination in values and route.source in values for route in self.routes),
                 "core routes must stay within their thin reference template")


@dataclass(frozen=True, slots=True)
class InvocationReturn(_Record):
    invocation: InvocationKey
    definition: OperationDefinitionID
    region: RegionID
    exit_anchor: CallRecordAnchor
    source: SourceReference
    operation: OperationID
    payload_use: UseID
    payload_value: ValueID
    post_world: ValueID


@dataclass(frozen=True, slots=True)
class FrameRouteObligations(_Record):
    definition: OperationDefinitionID
    region: RegionID
    frame_rules: FrameRules
    source_conditions: tuple[SourceExecutionPrecondition, ...]
    incomplete_effect_operations: tuple[OperationID, ...]


@dataclass(frozen=True, slots=True)
class OperandRouteModel(_Record):
    budget: OperandRouteBudget
    argument_routes: tuple[ArgumentRoute, ...]
    completion_routes: tuple[CompletionRoute, ...]
    templates: tuple[CoreReferenceTemplate, ...]
    returns: tuple[InvocationReturn, ...]
    obligations: tuple[FrameRouteObligations, ...]
    issues: tuple[OperandRouteIssue, ...]

    def __post_init__(self):
        _require(type(self.budget) is OperandRouteBudget, "routes require a typed independent budget")
        _require(sum(len(template.values) for template in self.templates) <= self.budget.max_template_values,
                 "route template value budget exceeded")
        count = len(self.argument_routes) + len(self.completion_routes) + len(self.returns)
        count += sum(len(template.routes) for template in self.templates)
        _require(count <= self.budget.max_routes, "route record budget exceeded")
        _require(len({template.definition for template in self.templates}) == len(self.templates), "duplicate template")
        _require(len({value.invocation for value in self.returns}) == len(self.returns), "duplicate invocation return")
        keys = [(route.callee, route.formal_slot) for route in self.argument_routes]
        _require(len(keys) == len(set(keys)), "formal must have a unique occurrence-based binding")
        keys = [(route.caller, route.operation, route.attempt) for route in self.completion_routes]
        _require(len(keys) == len(set(keys)), "duplicate attempt completion")

    def summary(self):
        return {"argument_routes": len(self.argument_routes), "completion_routes": len(self.completion_routes),
                "template_values": sum(len(template.values) for template in self.templates),
                "invocation_returns": len(self.returns), "issues": len(self.issues),
                "conditional_only": True, "function_environment_established": False,
                "contents_or_effects_established": False, "world_equivalence_established": False,
                "transformation_authorized": False}


@dataclass(frozen=True, slots=True)
class OperandReferenceNode(_Record):
    invocation: InvocationKey
    definition: OperationDefinitionID
    region: RegionID
    value: ValueID
    kind: CoreReferenceKind
    source: SourceReference | None = None
    formal_slot: ValueSlotID | None = None
    formal_name: str | None = None


class OperandQueryRouteKind(str, Enum):
    ARGUMENT = "ARGUMENT"
    COMPLETION = "COMPLETION"
    CORE_REFERENCE = "CORE_REFERENCE"


@dataclass(frozen=True, slots=True)
class OperandQueryStep(_Record):
    destination: OperandReferenceNode
    source: OperandReferenceNode
    kind: OperandQueryRouteKind
    argument: ArgumentRoute | None = None
    completion: CompletionRoute | None = None
    core: CoreReferenceRoute | None = None

    def __post_init__(self):
        _require(sum(value is not None for value in (self.argument, self.completion, self.core)) == 1,
                 "query step needs exactly one typed route")
        expected = {OperandQueryRouteKind.ARGUMENT: self.argument,
                    OperandQueryRouteKind.COMPLETION: self.completion,
                    OperandQueryRouteKind.CORE_REFERENCE: self.core}
        _require(expected[self.kind] is not None, "query step kind differs from its route")


@dataclass(frozen=True, slots=True)
class OperandReferenceTrace(_Record):
    invocation: InvocationKey
    roots: tuple[OperandReferenceNode, ...]
    nodes: tuple[OperandReferenceNode, ...]
    routes: tuple[OperandQueryStep, ...]
    endpoints: tuple[OperandReferenceNode, ...]
    issues: tuple[OperandRouteIssue, ...]
    obligations: tuple[FrameRouteObligations, ...]
    reference_steps: int
    max_reference_steps: int
    conditions: tuple[OperandRouteCondition, ...] = tuple(OperandRouteCondition)
    conditional_only: bool = True
    function_environment_established: bool = False
    contents_or_effects_established: bool = False
    world_equivalence_established: bool = False
    transformation_authorized: bool = False

    def __post_init__(self):
        _conditions(self.conditions)
        _require(self.conditional_only is True and all(value is False for value in (self.function_environment_established,
                 self.contents_or_effects_established, self.world_equivalence_established,
                 self.transformation_authorized)), "conditional reference routes grant no environment/effect authority")
        _require(type(self.max_reference_steps) is int and 1 <= self.max_reference_steps <= 100_000,
                 "query step ceiling must be an exact integer in [1, 100000]")
        _require(type(self.reference_steps) is int and 0 <= self.reference_steps <= self.max_reference_steps,
                 "query step count exceeds its independent ceiling")


__all__ = [name for name in globals() if name.startswith(("Operand", "ArgumentRoute", "CompletionRoute", "CoreReference", "InvocationReturn", "FrameRouteObligations", "ReferenceConsistency"))]

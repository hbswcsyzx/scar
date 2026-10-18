"""Typed protocol connections over canonical program ports.

These records name expected source/consumer relationships. Actual Uses,
definitions, result ports, control edges and state remain in the program graph.
They are static declarations, not source/runtime authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias, Union

from scar.ir.program.ids import OperationID, ProtocolScopeID, RegionID, UseID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference

from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, ContractResult, HostTerminal, NativeExit,
    OperationSiteSubject, OwnedUse, ProtocolCall, ProtocolCallRule, ProtocolClause,
    ProtocolProfile, ProtocolScope, ProtocolSourcePort, ReferenceIsNoneCondition, RequestProcessing,
    RequestProcessingRule, StaticProtocolGap,
    _protocol_result_port, _protocol_source_port,
)


def _exact(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be exact {expected.__name__}")


def _identifier(value: object, expected: type, name: str) -> None:
    _exact(value, expected, name)
    if type(getattr(value, "value", None)) is not str or not value.value:
        raise ValueError(f"{name} requires an exact nonempty string value")
    value.__post_init__()


def _index(value: object, name: str) -> None:
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _record(value: object, expected: type, name: str) -> None:
    _exact(value, expected, name)
    value.__post_init__()


def _tuple(value: object, name: str) -> tuple:
    _exact(value, tuple, name)
    return value


def _state_sites(value: object, name: str, *, read_only: bool = False) -> None:
    _tuple(value, name)
    accepted = (ExistingAccess,) if read_only else (ExistingAccess, InvokeStateOperand)
    for item in value:
        if type(item) not in accepted:
            kinds = "ExistingAccess" if read_only else "ExistingAccess or InvokeStateOperand"
            raise TypeError(f"{name} must contain exact {kinds} records")
        item.__post_init__()
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicate sites")


# Model-owned ports are bound by program.model only after their classes exist.
# The public package imports ProgramGraph before exposing these aliases.
ExpectedSourcePort: TypeAlias = Any
AssociationPort: TypeAlias = Any
ExactResultPort: TypeAlias = Any
_MODEL_PORT_CLASSES: tuple[type, type, type] | None = None


@dataclass(frozen=True, slots=True)
class ProtocolOperationRef:
    """The complete natural key of one existing ProtocolOperation."""

    scope: ProtocolScopeID
    clause: ProtocolClause
    operation: OperationID
    slot: int

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "protocol operation reference scope")
        _exact(self.clause, ProtocolClause, "protocol operation reference clause")
        _identifier(self.operation, OperationID, "protocol operation reference operation")
        _index(self.slot, "protocol operation reference slot")


@dataclass(frozen=True, slots=True)
class RawOperandSource:
    """Expected projection from an original raw pack, never a callee operand."""

    raw: OwnedUse
    ordinal: int

    def __post_init__(self) -> None:
        _record(self.raw, OwnedUse, "raw operand source")
        _index(self.ordinal, "raw operand source ordinal")


@dataclass(frozen=True, slots=True)
class RawRequestTrigger:
    raw: OwnedUse

    def __post_init__(self) -> None:
        _record(self.raw, OwnedUse, "raw request trigger")


@dataclass(frozen=True, slots=True)
class InjectedPacketTrigger:
    packet: ExpectedSourcePort

    def __post_init__(self) -> None:
        _expected_source(self.packet, "injected packet trigger")


@dataclass(frozen=True, slots=True)
class InitialAdvance:
    iterator: ContractResult

    def __post_init__(self) -> None:
        _record(self.iterator, ContractResult, "initial advance iterator result")


CallTrigger: TypeAlias = RawRequestTrigger | InjectedPacketTrigger | InitialAdvance | StaticProtocolGap


@dataclass(frozen=True, slots=True)
class ProtocolCallInputCase:
    guard: ControlEdgeReference | None
    receiver: ExpectedSourcePort
    arguments: tuple[ExpectedSourcePort | RawOperandSource, ...]
    trigger: CallTrigger | None

    def __post_init__(self) -> None:
        if self.guard is not None:
            _record(self.guard, ControlEdgeReference, "protocol call input guard")
            _identifier(self.guard.operation, OperationID, "protocol call input guard operation")
            _index(self.guard.successor_index, "protocol call input guard successor")
        _expected_source(self.receiver, "protocol call input expected receiver")
        _tuple(self.arguments, "protocol call input expected arguments")
        for item in self.arguments:
            if type(item) is RawOperandSource:
                item.__post_init__()
            else:
                _expected_source(item, "protocol call input expected argument")
        if self.trigger is not None:
            _call_trigger(self.trigger, "protocol call input trigger")


@dataclass(frozen=True, slots=True)
class ProtocolCallInputs:
    site: ProtocolOperationRef
    cases: tuple[ProtocolCallInputCase, ...]

    def __post_init__(self) -> None:
        _record(self.site, ProtocolOperationRef, "protocol call input site")
        _tuple(self.cases, "protocol call input cases")
        if not self.cases:
            raise ValueError("protocol call input cases must be nonempty")
        for case in self.cases:
            _record(case, ProtocolCallInputCase, "protocol call input case")
        guards = tuple(case.guard for case in self.cases)
        if len(self.cases) > 1 and any(guard is None for guard in guards):
            raise ValueError("multiple protocol call input cases require exact edge guards")
        if len(set(guards)) != len(guards):
            raise ValueError("protocol call input case guards must be unique")


@dataclass(frozen=True, slots=True)
class ResumeSourceBinding:
    """Expected source for one original BODY_INGRESS resume slot."""

    source: ExpectedSourcePort

    def __post_init__(self) -> None:
        _expected_source(self.source, "resume source binding")


@dataclass(frozen=True, slots=True)
class ProtocolResultConsumers:
    site: ProtocolOperationRef
    targets: tuple[OwnedUse | HostTerminal | NativeExit | StaticProtocolGap, ...]

    def __post_init__(self) -> None:
        _record(self.site, ProtocolOperationRef, "protocol result consumers site")
        _tuple(self.targets, "protocol result consumers targets")
        accepted = (OwnedUse, HostTerminal, NativeExit, StaticProtocolGap)
        for target in self.targets:
            if type(target) not in accepted:
                raise TypeError("protocol result consumer target has unsupported exact type")
            target.__post_init__()
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("protocol result consumer targets must be unique")


@dataclass(frozen=True, slots=True)
class RequestAssociation:
    request_use: UseID
    body: AssociationPort
    latent: AssociationPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]

    def __post_init__(self) -> None:
        _identifier(self.request_use, UseID, "request association request Use")
        _association_port(self.body, "request association body port")
        _association_port(self.latent, "request association latent port")
        _state_sites(self.state_sites, "request association state sites")


class RequestStateRule(str, Enum):
    IS_INITIAL_STEP = "IS_INITIAL_STEP"
    IS_COMPLETE = "IS_COMPLETE"


@dataclass(frozen=True, slots=True)
class RequestStateCondition:
    request_use: UseID
    state_sites: tuple[ExistingAccess, ...]
    rule: RequestStateRule

    def __post_init__(self) -> None:
        _identifier(self.request_use, UseID, "request state condition request Use")
        _state_sites(self.state_sites, "request state condition state sites", read_only=True)
        if not self.state_sites:
            raise ValueError("request state condition needs at least one original READ site")
        _exact(self.rule, RequestStateRule, "request state condition rule")


@dataclass(frozen=True, slots=True)
class AsyncSessionOutcome:
    scope: ProtocolScopeID
    update: OperationID
    source: DriveOutcomeRef | ContractResult

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "async session outcome scope")
        _identifier(self.update, OperationID, "async session outcome update")
        if type(self.source) not in (DriveOutcomeRef, ContractResult):
            raise TypeError("async session outcome source must be DriveOutcomeRef or ContractResult")
        self.source.__post_init__()


class TaskTargetRole(str, Enum):
    OWN_CONTINUATION = "OWN_CONTINUATION"
    CURRENT_AWAITED = "CURRENT_AWAITED"


@dataclass(frozen=True, slots=True)
class TaskCreatedTarget:
    task_result: ExactResultPort
    body_use: OwnedUse
    interface: ProviderFactReference | StaticProtocolGap

    def __post_init__(self) -> None:
        _exact_result(self.task_result, "created task result")
        _record(self.body_use, OwnedUse, "created task body Use")
        _interface(self.interface, "created task interface")


@dataclass(frozen=True, slots=True)
class TaskTargetRead:
    task: OwnedUse
    target: ExactResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    role: TaskTargetRole
    interface: ProviderFactReference | StaticProtocolGap

    def __post_init__(self) -> None:
        _record(self.task, OwnedUse, "task target read task Use")
        _exact_result(self.target, "task target read result")
        _state_sites(self.state_sites, "task target read state sites")
        if not self.state_sites:
            raise ValueError("task target read requires current-state sites")
        _exact(self.role, TaskTargetRole, "task target read role")
        _interface(self.interface, "task target read interface")


TaskTargetSource: TypeAlias = TaskCreatedTarget | TaskTargetRead | StaticProtocolGap


@dataclass(frozen=True, slots=True)
class CancelDelivery:
    scope: ProtocolScopeID
    expected_target: TaskTargetSource
    packet_source: ExpectedSourcePort
    consumer: OwnedUse

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "cancel delivery scope")
        _task_target_source(self.expected_target, "cancel delivery expected target")
        _expected_source(self.packet_source, "cancel delivery packet source")
        _record(self.consumer, OwnedUse, "cancel delivery consumer")


@dataclass(frozen=True, slots=True)
class CancelDeliveryRef:
    scope: ProtocolScopeID
    expected_target: TaskTargetSource
    packet_source: ExpectedSourcePort
    consumer: OwnedUse

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "cancel delivery reference scope")
        _task_target_source(self.expected_target, "cancel delivery reference expected target")
        _expected_source(self.packet_source, "cancel delivery reference packet source")
        _record(self.consumer, OwnedUse, "cancel delivery reference consumer")

    @classmethod
    def from_delivery(cls, delivery: CancelDelivery) -> CancelDeliveryRef:
        _record(delivery, CancelDelivery, "cancel delivery reference source")
        return cls(delivery.scope, delivery.expected_target, delivery.packet_source, delivery.consumer)


@dataclass(frozen=True, slots=True)
class CancelHandling:
    delivery: CancelDeliveryRef
    handler_packet: OwnedUse
    context_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    continuation: ControlEdgeReference | StaticProtocolGap

    def __post_init__(self) -> None:
        _record(self.delivery, CancelDeliveryRef, "cancel handling delivery reference")
        _record(self.handler_packet, OwnedUse, "cancel handling packet Use")
        _state_sites(self.context_sites, "cancel handling context sites")
        if type(self.continuation) is ControlEdgeReference:
            self.continuation.__post_init__()
        elif type(self.continuation) is StaticProtocolGap:
            self.continuation.__post_init__()
        else:
            raise TypeError("cancel handling continuation must be ControlEdgeReference or gap")


class TaskStatusRule(str, Enum):
    IS_DONE = "IS_DONE"
    IS_CANCELLED = "IS_CANCELLED"


@dataclass(frozen=True, slots=True)
class TaskStatusRead:
    scope: ProtocolScopeID
    task: OwnedUse
    result: ExactResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    rule: TaskStatusRule
    consumer: OwnedUse | StaticProtocolGap

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "task status scope")
        _record(self.task, OwnedUse, "task status task Use")
        _exact_result(self.result, "task status result")
        _state_sites(self.state_sites, "task status state sites")
        if not self.state_sites:
            raise ValueError("task status requires original READ sites")
        _exact(self.rule, TaskStatusRule, "task status rule")
        if type(self.consumer) not in (OwnedUse, StaticProtocolGap):
            raise TypeError("task status consumer must be OwnedUse or StaticProtocolGap")
        self.consumer.__post_init__()


@dataclass(frozen=True, slots=True)
class NormalizedThrowSource:
    """Independent raw and whole-packet anchors, not a normalization proof."""

    raw: OwnedUse
    packet: ExpectedSourcePort

    def __post_init__(self) -> None:
        _record(self.raw, OwnedUse, 'normalized throw raw source')
        _expected_source(self.packet, 'normalized throw packet source')


@dataclass(frozen=True, slots=True)
class DelegateLookupFallback:
    lookup: ProtocolOperationRef
    matcher: OperationID
    request: NormalizedThrowSource | InjectedPacketTrigger | StaticProtocolGap
    guard: ControlEdgeReference | None = None

    def __post_init__(self) -> None:
        _record(self.lookup, ProtocolOperationRef, 'fallback exact lookup site')
        _identifier(self.matcher, OperationID, 'fallback original matcher operation')
        if type(self.request) not in (NormalizedThrowSource, InjectedPacketTrigger, StaticProtocolGap):
            raise TypeError('lookup fallback requires an exact independent request source or gap')
        self.request.__post_init__()
        if self.guard is not None:
            _record(self.guard, ControlEdgeReference, 'fallback original guard')


ProtocolBinding: TypeAlias = AsyncSessionOutcome | CancelDelivery | CancelHandling | TaskStatusRead | DelegateLookupFallback
PROTOCOL_BINDING_TYPES = (AsyncSessionOutcome, CancelDelivery, CancelHandling, TaskStatusRead, DelegateLookupFallback)

LOOKUP_FALLBACK_RECORD_TAGS = MappingProxyType({
    NormalizedThrowSource: ('kind', 'NORMALIZED_THROW_SOURCE'),
    DelegateLookupFallback: ('kind', 'DELEGATE_LOOKUP_FALLBACK'),
})


def has_lookup_fallback_capability(graph: object) -> bool:
    return any(type(row) is DelegateLookupFallback for row in getattr(graph, 'protocol_bindings', ()))


def _call_trigger(value: object, name: str) -> None:
    if type(value) is RawRequestTrigger:
        value.__post_init__()
    elif type(value) is InjectedPacketTrigger:
        value.__post_init__()
    elif type(value) is InitialAdvance:
        value.__post_init__()
    elif type(value) is StaticProtocolGap:
        value.__post_init__()
    else:
        raise TypeError(f"{name} has unsupported exact type")


def _expected_source(value: object, name: str) -> None:
    from scar.ir.program.model import BlockArgument
    if type(value) is BlockArgument:
        value.__post_init__()
    else:
        _protocol_source_port(value, name)


def _association_port(value: object, name: str) -> None:
    operation_result, invoke_result, _ = _model_classes()
    if type(value) in (operation_result, invoke_result, OwnedUse, StaticProtocolGap):
        if type(value) is StaticProtocolGap:
            value.__post_init__()
        elif type(value) is OwnedUse:
            value.__post_init__()
        else:
            _protocol_result_port(value, name)
        return
    raise TypeError(f"{name} has unsupported exact type")


def _exact_result(value: object, name: str) -> None:
    operation_result, invoke_result, _ = _model_classes()
    if type(value) not in (operation_result, invoke_result):
        raise TypeError(f"{name} must be exact OperationResult or InvokeLiteralResult")
    _protocol_result_port(value, name)


def _interface(value: object, name: str) -> None:
    if type(value) is ProviderFactReference:
        value.__post_init__()
    elif type(value) is StaticProtocolGap:
        value.__post_init__()
    else:
        raise TypeError(f"{name} must be ProviderFactReference or StaticProtocolGap")


def _task_target_source(value: object, name: str) -> None:
    if type(value) in (TaskCreatedTarget, TaskTargetRead, StaticProtocolGap):
        value.__post_init__()
        return
    raise TypeError(f"{name} has unsupported exact type")


def _model_classes() -> tuple[type, type, type]:
    from scar.ir.program.model import BlockArgument, InvokeLiteralResult, OperationResult
    return OperationResult, InvokeLiteralResult, BlockArgument


def _bind_connection_model_ports(
        operation_result: type, invoke_literal_result: type, block_argument: type) -> None:
    """Bind annotations to the exact model-owned ports after model definitions."""
    global ExpectedSourcePort, AssociationPort, ExactResultPort, _MODEL_PORT_CLASSES
    from scar.ir.program import model
    from scar.ir.program.protocols import ProtocolSourcePort, _MODEL_PORT_CLASSES as protocol_ports
    expected = (model.OperationResult, model.InvokeLiteralResult, model.BlockArgument)
    actual = (operation_result, invoke_literal_result, block_argument)
    if actual != expected:
        raise TypeError("protocol connection ports bind only canonical model classes")
    if protocol_ports != expected[:2]:
        raise RuntimeError("base protocol result ports must bind before connection ports")
    if _MODEL_PORT_CLASSES is not None:
        if _MODEL_PORT_CLASSES != actual:
            raise RuntimeError("protocol connection ports cannot be rebound")
        return
    ExpectedSourcePort = Union[ProtocolSourcePort, block_argument]
    AssociationPort = Union[operation_result, invoke_literal_result, OwnedUse, StaticProtocolGap]
    ExactResultPort = Union[operation_result, invoke_literal_result]
    _MODEL_PORT_CLASSES = actual


PROTOCOL_CONNECTION_RECORD_TAGS = MappingProxyType({
    ProtocolOperationRef: ("kind", "PROTOCOL_OPERATION_REF"),
    RawOperandSource: ("kind", "RAW_OPERAND_SOURCE"),
    RawRequestTrigger: ("kind", "RAW_REQUEST_TRIGGER"),
    InjectedPacketTrigger: ("kind", "INJECTED_PACKET_TRIGGER"),
    InitialAdvance: ("kind", "INITIAL_ADVANCE"),
    ProtocolCallInputCase: ("kind", "PROTOCOL_CALL_INPUT_CASE"),
    ProtocolCallInputs: ("kind", "PROTOCOL_CALL_INPUTS"),
    ResumeSourceBinding: ("kind", "RESUME_SOURCE_BINDING"),
    ProtocolResultConsumers: ("kind", "PROTOCOL_RESULT_CONSUMERS"),
    RequestAssociation: ("kind", "PROTOCOL_REQUEST_ASSOCIATION"),
    RequestStateCondition: ("kind", "PROTOCOL_REQUEST_STATE_CONDITION"),
    AsyncSessionOutcome: ("kind", "ASYNC_SESSION_OUTCOME"),
    TaskCreatedTarget: ("kind", "TASK_CREATED_TARGET"),
    TaskTargetRead: ("kind", "TASK_TARGET_READ"),
    CancelDelivery: ("kind", "CANCEL_DELIVERY"),
    CancelDeliveryRef: ("kind", "CANCEL_DELIVERY_REF"),
    CancelHandling: ("kind", "CANCEL_HANDLING"),
    TaskStatusRead: ("kind", "TASK_STATUS_READ"),
})


PROTOCOL_CONNECTION_CONTRACTS = (ResumeSourceBinding, RequestAssociation)
PROTOCOL_CONNECTION_ADMISSION_SUBJECTS = (RequestStateCondition,)
_DELEGATED_METHOD_LOOKUP_RULES = frozenset({
    ProtocolCallRule.DELEGATE_NEXT_LOOKUP,
    ProtocolCallRule.DELEGATE_SEND_LOOKUP,
    ProtocolCallRule.DELEGATE_THROW_LOOKUP,
    ProtocolCallRule.DELEGATE_CLOSE_LOOKUP,
})


def _bind_protocol_records() -> None:
    from scar.ir.program.protocols import _bind_protocol_connection_types
    _bind_protocol_connection_types(
        ResumeSourceBinding, RequestAssociation, RequestStateCondition)


def has_protocol_connection_capability(graph: object) -> bool:
    """Return whether a graph uses a Program19 connection record or contract.

    Keep this predicate independent of the codec so graph validation and
    indexed queries can apply the expensive P4 stage only for this capability.
    An older protocol scope by itself does not select the new capability.
    """
    if any(getattr(graph, name, ()) for name in (
            "protocol_call_inputs", "protocol_result_consumers", "protocol_bindings")):
        return True
    if has_delegated_method_lookup_capability(graph):
        return True
    scope_profiles = {
        row.id: row.profile for row in getattr(graph, "protocol_scopes", ())
        if type(row) is ProtocolScope
    }
    for row in getattr(graph, "protocol_operations", ()):
        contract = getattr(row, "contract", None)
        if type(contract) in PROTOCOL_CONNECTION_CONTRACTS:
            return True
        if (type(contract) is RequestProcessing
                and row.clause is ProtocolClause.ASYNC_REQUEST_DELIVERY
                and scope_profiles.get(row.scope) is ProtocolProfile.ASYNC_GENERATOR_BODY_V1
                and contract.rule is RequestProcessingRule.NORMALIZE_GENERATOR_EXIT):
            # P19 clarifies that async-generator CLOSE delivery reuses the
            # established CLOSE -> GeneratorExit normalizer. This is an old
            # record shape under a newly applicable profile/rule, so the
            # semantic profile use itself must select the newer capability.
            return True
        if type(contract) is AdmissionPredicate:
            subject_type = type(contract.subject)
            if subject_type in PROTOCOL_CONNECTION_ADMISSION_SUBJECTS:
                return True
            # Program19 changes where the already-known body/reference
            # admission predicates are applicable. Their records are old
            # shapes, so detect this exact new profile/clause combination as
            # a capability without upgrading legacy generator predicates.
            if (row.clause is ProtocolClause.RAW_ADMISSION
                    and scope_profiles.get(row.scope) in (
                        ProtocolProfile.COROUTINE_BODY_V1,
                        ProtocolProfile.GENERATOR_COROUTINE_BODY_V1,
                    )
                    and subject_type in (BodyStateCondition, ReferenceIsNoneCondition)):
                return True
    return False


def has_delegated_method_lookup_capability(graph: object) -> bool:
    """Return whether a graph declares one of the Program20 method lookups.

    This is deliberately a closed rule check over canonical ProtocolCall rows.
    Program19 knows the same record shape, but must not reinterpret these new
    rules under its frozen wire capability.
    """
    return any(
        type(getattr(row, "contract", None)) is ProtocolCall
        and row.contract.rule in _DELEGATED_METHOD_LOOKUP_RULES
        for row in getattr(graph, "protocol_operations", ())
    )


__all__ = [
    'DelegateLookupFallback', 'NormalizedThrowSource', 'LOOKUP_FALLBACK_RECORD_TAGS',
    'has_lookup_fallback_capability',
    "AssociationPort", "AsyncSessionOutcome", "CallTrigger", "CancelDelivery",
    "CancelDeliveryRef", "CancelHandling", "ExactResultPort", "ExpectedSourcePort",
    "InitialAdvance", "InjectedPacketTrigger", "PROTOCOL_CONNECTION_RECORD_TAGS",
    "PROTOCOL_CONNECTION_ADMISSION_SUBJECTS", "PROTOCOL_CONNECTION_CONTRACTS",
    "PROTOCOL_BINDING_TYPES", "ProtocolBinding", "ProtocolCallInputCase", "ProtocolCallInputs",
    "ProtocolOperationRef", "ProtocolResultConsumers", "RawOperandSource",
    "RawRequestTrigger", "RequestAssociation", "RequestStateCondition",
    "RequestStateRule", "ResumeSourceBinding", "TaskCreatedTarget", "TaskStatusRead",
    "TaskStatusRule", "TaskTargetRead", "TaskTargetRole", "TaskTargetSource",
    "_bind_connection_model_ports", "_bind_protocol_records",
    "has_delegated_method_lookup_capability", "has_protocol_connection_capability",
]

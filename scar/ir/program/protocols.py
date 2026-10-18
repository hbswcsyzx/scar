"""Fixed static protocol declarations over canonical program ports.

These records name source-level protocol claims and point to existing core
operations, Uses, results, state sites and control edges. They do not add a
second producer/use/state graph and do not prove source applicability, runtime
behavior or transformation permission.

The ordinary and INVOKE result classes are owned by ``program.model``. They
are late-bound by that module after both canonical classes exist, avoiding a
module cycle while leaving the wire/API fields typed as their exact union.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, TYPE_CHECKING, TypeAlias, Union

from scar.ir.program.ids import (
    NativeBoundaryID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.native import ExitPortRef
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference

if TYPE_CHECKING:
    from scar.ir.program.model import InvokeLiteralResult, OperationResult


def _exact(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be exact {expected.__name__}")


def _identifier(value: object, expected: type, name: str) -> None:
    _exact(value, expected, name)
    # Identifier.__post_init__ accepts str subclasses; this interface does not.
    _exact(getattr(value, "value", None), str, name + " value")
    if not value.value:
        raise ValueError(f"{name} value must be nonempty")
    value.__post_init__()


def _text(value: object, name: str) -> None:
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _index(value: object, name: str) -> None:
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _record(value: object, expected: type, name: str) -> None:
    _exact(value, expected, name)
    value.__post_init__()


def _records(values: object, expected: type, name: str) -> None:
    _exact(values, tuple, name)
    for value in values:
        _record(value, expected, name + " item")


class ProtocolProfile(str, Enum):
    GENERATOR_BODY_V1 = "GENERATOR_BODY_V1"
    COROUTINE_BODY_V1 = "COROUTINE_BODY_V1"
    GENERATOR_COROUTINE_BODY_V1 = "GENERATOR_COROUTINE_BODY_V1"
    ASYNC_GENERATOR_BODY_V1 = "ASYNC_GENERATOR_BODY_V1"
    AWAIT_SITE_V1 = "AWAIT_SITE_V1"
    DELEGATION_SITE_V1 = "DELEGATION_SITE_V1"
    COROUTINE_AWAIT_WRAPPER_V1 = "COROUTINE_AWAIT_WRAPPER_V1"
    CREATED_THROW_V1 = "CREATED_THROW_V1"
    CREATED_CLOSE_V1 = "CREATED_CLOSE_V1"
    SUSPENDED_CLOSE_V1 = "SUSPENDED_CLOSE_V1"
    TASK_CANCEL_EXTERNAL_V1 = "TASK_CANCEL_EXTERNAL_V1"


class ProtocolClause(str, Enum):
    RAW_ADMISSION = "RAW_ADMISSION"
    REQUEST_PROCESSING = "REQUEST_PROCESSING"
    BODY_INGRESS = "BODY_INGRESS"
    BODY_SUSPENSION = "BODY_SUSPENSION"
    BODY_TERMINAL = "BODY_TERMINAL"
    HOST_ADAPTER = "HOST_ADAPTER"
    AWAIT_COMPLETION_ADAPTER = "AWAIT_COMPLETION_ADAPTER"
    DIRECT_HOST_ADAPTER = "DIRECT_HOST_ADAPTER"
    CLOSE_ROUTE = "CLOSE_ROUTE"
    ASYNC_REQUEST_SOURCE = "ASYNC_REQUEST_SOURCE"
    ASYNC_REQUEST_ASSOCIATE = "ASYNC_REQUEST_ASSOCIATE"
    ASYNC_REQUEST_DELIVERY = "ASYNC_REQUEST_DELIVERY"
    ASYNC_ITEM_ADAPTER = "ASYNC_ITEM_ADAPTER"
    AWAIT_LOOKUP = "AWAIT_LOOKUP"
    AWAIT_CALL = "AWAIT_CALL"
    AWAIT_RESULT_ADAPTER = "AWAIT_RESULT_ADAPTER"
    DELEGATE_ITER_LOOKUP = "DELEGATE_ITER_LOOKUP"
    DELEGATE_ADVANCE = "DELEGATE_ADVANCE"
    DELEGATE_THROW = "DELEGATE_THROW"
    DELEGATE_CLOSE = "DELEGATE_CLOSE"
    DELEGATE_PARENT_OR_HOST_RESULT = "DELEGATE_PARENT_OR_HOST_RESULT"
    WRAPPER_LOOKUP = "WRAPPER_LOOKUP"
    WRAPPER_CALL = "WRAPPER_CALL"
    WRAPPER_RESULT_ROUTE = "WRAPPER_RESULT_ROUTE"
    THROW_NORMALIZATION = "THROW_NORMALIZATION"
    PREENTRY_REJECT = "PREENTRY_REJECT"
    INITIAL_THROW_DELIVERED = "INITIAL_THROW_DELIVERED"
    INITIAL_THROW_CONSTRUCTOR_FAILURE = "INITIAL_THROW_CONSTRUCTOR_FAILURE"
    HOST_TERMINAL = "HOST_TERMINAL"
    CREATED_CLOSE_BRANCH = "CREATED_CLOSE_BRANCH"
    CLOSE_INJECTION = "CLOSE_INJECTION"
    CLOSE_HOST_ADAPTER = "CLOSE_HOST_ADAPTER"
    TASK_CANCEL_REQUEST = "TASK_CANCEL_REQUEST"
    CANCEL_DELIVERY = "CANCEL_DELIVERY"
    CANCEL_HANDLER_OR_TERMINAL = "CANCEL_HANDLER_OR_TERMINAL"
    TASK_STATUS_ROUTE = "TASK_STATUS_ROUTE"


class StaticGapReason(str, Enum):
    SOURCE_SCOPE_INVENTORY_UNRESOLVED = "SOURCE_SCOPE_INVENTORY_UNRESOLVED"
    SITE_INVENTORY_UNRESOLVED = "SITE_INVENTORY_UNRESOLVED"
    EXTERNAL_RAW_UNAVAILABLE = "EXTERNAL_RAW_UNAVAILABLE"
    RAW_OPERAND_PROJECTION_UNRESOLVED = "RAW_OPERAND_PROJECTION_UNRESOLVED"
    PORT_UNCAPTURED = "PORT_UNCAPTURED"
    STATE_POST_UNCAPTURED = "STATE_POST_UNCAPTURED"
    CALLBACK_BEHAVIOR_UNPROVEN = "CALLBACK_BEHAVIOR_UNPROVEN"
    NATIVE_APPLICABILITY_UNPROVEN = "NATIVE_APPLICABILITY_UNPROVEN"
    TASK_IDENTITY_UNMODELED = "TASK_IDENTITY_UNMODELED"
    TERMINAL_ROUTE_UNRESOLVED = "TERMINAL_ROUTE_UNRESOLVED"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"


class RequestProcessingRule(str, Enum):
    CHECK_NEXT = "CHECK_NEXT"
    CHECK_SEND = "CHECK_SEND"
    CHECK_THROW = "CHECK_THROW"
    CHECK_CLOSE = "CHECK_CLOSE"
    CHECK_ASYNC_REQUEST = "CHECK_ASYNC_REQUEST"
    CHECK_INITIAL_ASEND = "CHECK_INITIAL_ASEND"
    NORMALIZE_THROW_INSTANCE = "NORMALIZE_THROW_INSTANCE"
    NORMALIZE_THROW_CLASS = "NORMALIZE_THROW_CLASS"
    NORMALIZE_GENERATOR_EXIT = "NORMALIZE_GENERATOR_EXIT"
    NORMALIZE_ASYNC_THROW = "NORMALIZE_ASYNC_THROW"


class BodyStatePredicateRule(str, Enum):
    IS_CREATED = "IS_CREATED"
    IS_RUNNING = "IS_RUNNING"
    IS_SUSPENDED = "IS_SUSPENDED"
    IS_CLOSED = "IS_CLOSED"


class ProtocolCallRule(str, Enum):
    AWAIT_LOOKUP = "AWAIT_LOOKUP"
    AWAIT_CALL = "AWAIT_CALL"
    DELEGATE_ITER = "DELEGATE_ITER"
    DELEGATE_NEXT = "DELEGATE_NEXT"
    DELEGATE_SEND = "DELEGATE_SEND"
    DELEGATE_THROW = "DELEGATE_THROW"
    DELEGATE_CLOSE = "DELEGATE_CLOSE"
    ASYNC_REQUEST_AWAIT = "ASYNC_REQUEST_AWAIT"
    TASK_CANCEL_CALL = "TASK_CANCEL_CALL"
    EXCEPTION_CONSTRUCTOR = "EXCEPTION_CONSTRUCTOR"


class PacketRule(str, Enum):
    THROW_PACKET_FROM_NORMALIZED = "THROW_PACKET_FROM_NORMALIZED"
    GENERATOR_EXIT_PACKET = "GENERATOR_EXIT_PACKET"
    CANCEL_PACKET_FROM_DELIVERY = "CANCEL_PACKET_FROM_DELIVERY"
    FORWARD_EXISTING_PACKET = "FORWARD_EXISTING_PACKET"


class OutcomeAdapterRule(str, Enum):
    GENERATOR_RETURN_TO_STOP_ITERATION = "GENERATOR_RETURN_TO_STOP_ITERATION"
    GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR = "GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR"
    COROUTINE_RETURN_TO_STOP_ITERATION = "COROUTINE_RETURN_TO_STOP_ITERATION"
    AWAIT_STOPITER_TO_EXPRESSION = "AWAIT_STOPITER_TO_EXPRESSION"
    ASYNCGEN_YIELD_TO_REQUEST_ITEM = "ASYNCGEN_YIELD_TO_REQUEST_ITEM"
    ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION = "ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION"
    DELEGATE_ITEM_TO_PARENT_YIELD = "DELEGATE_ITEM_TO_PARENT_YIELD"
    DELEGATE_STOPITER_TO_PARENT_VALUE = "DELEGATE_STOPITER_TO_PARENT_VALUE"
    DELEGATE_ONLY_HOST_ITEM = "DELEGATE_ONLY_HOST_ITEM"
    DELEGATE_ONLY_HOST_EXCEPTION = "DELEGATE_ONLY_HOST_EXCEPTION"
    CLOSE_RETURN_VALUE = "CLOSE_RETURN_VALUE"
    CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR = "CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR"
    ASYNCGEN_CLOSE_YIELD_ERROR = "ASYNCGEN_CLOSE_YIELD_ERROR"


@dataclass(frozen=True, slots=True)
class StaticProtocolGap:
    reason: StaticGapReason

    def __post_init__(self) -> None:
        _exact(self.reason, StaticGapReason, "static protocol gap reason")


@dataclass(frozen=True, slots=True)
class DriverSubject:
    interface_region: RegionID

    def __post_init__(self) -> None:
        _identifier(self.interface_region, RegionID, "protocol driver interface region")


@dataclass(frozen=True, slots=True)
class OperationSiteSubject:
    region: RegionID
    operation: OperationID

    def __post_init__(self) -> None:
        _identifier(self.region, RegionID, "protocol operation site region")
        _identifier(self.operation, OperationID, "protocol operation site operation")


@dataclass(frozen=True, slots=True)
class ProtocolScope:
    id: ProtocolScopeID
    profile: ProtocolProfile
    subject: DriverSubject | OperationSiteSubject
    source: ProviderFactReference | StaticProtocolGap

    def __post_init__(self) -> None:
        _identifier(self.id, ProtocolScopeID, "protocol scope id")
        _exact(self.profile, ProtocolProfile, "protocol scope profile")
        if type(self.subject) not in (DriverSubject, OperationSiteSubject):
            raise TypeError("protocol scope subject must be an exact typed subject")
        self.subject.__post_init__()
        if type(self.source) is ProviderFactReference:
            self.source.__post_init__()
        elif type(self.source) is StaticProtocolGap:
            self.source.__post_init__()
        else:
            raise TypeError("protocol scope source must be ProviderFactReference or StaticProtocolGap")


@dataclass(frozen=True, slots=True)
class OwnedUse:
    """One exact UseID owned by an operation, even when its Value is aliased."""

    operation: OperationID
    use: UseID

    def __post_init__(self) -> None:
        _identifier(self.operation, OperationID, "protocol owned-use operation")
        _identifier(self.use, UseID, "protocol owned-use UseID")


@dataclass(frozen=True, slots=True)
class RequestOperandBinding:
    request_ordinal: int
    operation_use: UseID

    def __post_init__(self) -> None:
        _index(self.request_ordinal, "request operand ordinal")
        _identifier(self.operation_use, UseID, "request operand operation Use")


@dataclass(frozen=True, slots=True)
class DriveResult:
    outcome: DriveOutcomeRef
    index: int

    def __post_init__(self) -> None:
        _record(self.outcome, DriveOutcomeRef, "protocol DriveOutcomeRef")
        _identifier(self.outcome.drive, OperationID, "protocol outcome drive")
        _identifier(self.outcome.source, OperationID, "protocol outcome source")
        _index(self.index, "protocol drive result index")


@dataclass(frozen=True, slots=True)
class ContractResult:
    scope: ProtocolScopeID
    clause: ProtocolClause
    operation: OperationID
    slot: int
    result_port: ProtocolResultPort

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "contract result scope")
        _exact(self.clause, ProtocolClause, "contract result clause")
        _identifier(self.operation, OperationID, "contract result operation")
        _index(self.slot, "contract result slot")
        _protocol_result_port(self.result_port, "contract result port")


@dataclass(frozen=True, slots=True)
class HostTerminal:
    operation: OperationID

    def __post_init__(self) -> None:
        _identifier(self.operation, OperationID, "protocol host terminal operation")


@dataclass(frozen=True, slots=True)
class NativeExit:
    boundary: NativeBoundaryID
    port: ExitPortRef

    def __post_init__(self) -> None:
        _identifier(self.boundary, NativeBoundaryID, "protocol native exit boundary")
        _record(self.port, ExitPortRef, "protocol native exit port")
        _identifier(self.port.region, RegionID, "protocol native exit region")
        _text(self.port.exit_name, "protocol native exit name")
        _index(self.port.index, "protocol native exit index")


@dataclass(frozen=True, slots=True)
class RequestProcessing:
    raw_use: UseID
    operand_bindings: tuple[RequestOperandBinding, ...]
    result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    rule: RequestProcessingRule

    def __post_init__(self) -> None:
        _identifier(self.raw_use, UseID, "request processing raw Use")
        _records(self.operand_bindings, RequestOperandBinding, "request operand bindings")
        _protocol_result_port(self.result, "request processing result")
        _state_sites(self.state_sites, "request processing state sites")
        _exact(self.rule, RequestProcessingRule, "request processing rule")
        ordinals = tuple(binding.request_ordinal for binding in self.operand_bindings)
        uses = tuple(binding.operation_use for binding in self.operand_bindings)
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("request operand ordinals must be unique")
        if len(set(uses)) != len(uses) or self.raw_use in uses:
            raise ValueError("request processing role UseIDs must be independent")


@dataclass(frozen=True, slots=True)
class ProtocolCall:
    receiver_use: UseID
    argument_uses: tuple[UseID, ...]
    result: ProtocolResultPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    rule: ProtocolCallRule

    def __post_init__(self) -> None:
        _identifier(self.receiver_use, UseID, "protocol call receiver Use")
        _exact(self.argument_uses, tuple, "protocol call argument Uses")
        for use in self.argument_uses:
            _identifier(use, UseID, "protocol call argument Use")
        if self.receiver_use in self.argument_uses or len(set(self.argument_uses)) != len(self.argument_uses):
            raise ValueError("protocol call role UseIDs must be independent")
        _protocol_result_port(self.result, "protocol call result")
        _state_sites(self.state_sites, "protocol call state sites")
        _exact(self.rule, ProtocolCallRule, "protocol call rule")


@dataclass(frozen=True, slots=True)
class PacketConstruction:
    packet: ValueID
    exception_source: ProtocolSourcePort
    traceback_source: ProtocolSourcePort
    rule: PacketRule

    def __post_init__(self) -> None:
        _identifier(self.packet, ValueID, "protocol packet Value")
        _protocol_source_port(self.exception_source, "packet exception source")
        _protocol_source_port(self.traceback_source, "packet traceback source")
        _exact(self.rule, PacketRule, "packet rule")


@dataclass(frozen=True, slots=True)
class OutcomeAdapter:
    input: AdapterInputPort
    input_use: UseID
    output: ProtocolResultPort | HostTerminal | NativeExit
    rule: OutcomeAdapterRule

    def __post_init__(self) -> None:
        if type(self.input) not in (DriveResult, ContractResult):
            raise TypeError("outcome adapter input must be DriveResult or ContractResult")
        self.input.__post_init__()
        _identifier(self.input_use, UseID, "outcome adapter input Use")
        _adapter_output(self.output, "outcome adapter output")
        _exact(self.rule, OutcomeAdapterRule, "outcome adapter rule")


@dataclass(frozen=True, slots=True)
class NoEntryOutcome:
    instance_use: UseID
    effective_request_use: UseID
    selected_input: NoEntryInputPort
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...]
    selected_edge: ControlEdgeReference | None
    terminal: HostTerminal | NativeExit

    def __post_init__(self) -> None:
        _identifier(self.instance_use, UseID, "no-entry instance Use")
        _identifier(self.effective_request_use, UseID, "no-entry effective request Use")
        if self.instance_use == self.effective_request_use:
            raise ValueError("no-entry instance and request need independent Uses")
        _no_entry_input(self.selected_input, "no-entry selected input")
        _state_sites(self.state_sites, "no-entry state sites")
        if self.selected_edge is not None:
            _record(self.selected_edge, ControlEdgeReference, "no-entry selected edge")
            _identifier(self.selected_edge.operation, OperationID, "no-entry selected-edge operation")
            _index(self.selected_edge.successor_index, "no-entry selected-edge index")
        _terminal(self.terminal, "no-entry terminal")


@dataclass(frozen=True, slots=True)
class BodyStateCondition:
    """Only the owner and READ sites actually consumed by the predicate."""

    instance_use: UseID
    state_sites: tuple[ExistingAccess, ...]
    rule: BodyStatePredicateRule

    def __post_init__(self) -> None:
        _identifier(self.instance_use, UseID, "body-state predicate instance Use")
        _exact(self.state_sites, tuple, "body-state predicate state sites")
        if not self.state_sites:
            raise ValueError("body-state predicate state sites must be nonempty")
        for site in self.state_sites:
            _record(site, ExistingAccess, "body-state predicate state site")
            _identifier(site.operation, OperationID, "body-state predicate access operation")
            _index(site.index, "body-state predicate access index")
        if len(set(self.state_sites)) != len(self.state_sites):
            raise ValueError("body-state predicate state sites must be distinct")
        _exact(self.rule, BodyStatePredicateRule, "body-state predicate rule")


@dataclass(frozen=True, slots=True)
class ReferenceIsNoneCondition:
    """The real reference operand; neither a body nor a raw pack is added."""

    input_use: UseID

    def __post_init__(self) -> None:
        _identifier(self.input_use, UseID, "reference-is-None predicate input Use")


@dataclass(frozen=True, slots=True)
class AdmissionPredicate:
    """Original bool production and intended branch, without a phase state."""

    subject: BodyStateCondition | ReferenceIsNoneCondition
    result: OperationResult
    branch: OperationID

    def __post_init__(self) -> None:
        if type(self.subject) not in (BodyStateCondition, ReferenceIsNoneCondition):
            raise TypeError("admission predicate subject must be an exact typed condition")
        self.subject.__post_init__()
        operation_result, _ = _model_port_types()
        _record(self.result, operation_result, "admission predicate result")
        _identifier(self.result.operation, OperationID, "admission predicate result operation")
        _index(self.result.index, "admission predicate result index")
        _identifier(self.branch, OperationID, "admission predicate branch")

    @property
    def state_sites(self) -> tuple[ExistingAccess, ...]:
        return self.subject.state_sites if type(self.subject) is BodyStateCondition else ()


@dataclass(frozen=True, slots=True)
class ProtocolOperation:
    scope: ProtocolScopeID
    clause: ProtocolClause
    operation: OperationID
    slot: int
    contract: RequestProcessing | ProtocolCall | PacketConstruction | OutcomeAdapter | NoEntryOutcome | AdmissionPredicate
    source: ProviderFactReference | StaticProtocolGap

    def __post_init__(self) -> None:
        _identifier(self.scope, ProtocolScopeID, "protocol operation scope")
        _exact(self.clause, ProtocolClause, "protocol operation clause")
        _identifier(self.operation, OperationID, "protocol operation operation")
        _index(self.slot, "protocol operation slot")
        if type(self.contract) not in (
                RequestProcessing, ProtocolCall, PacketConstruction, OutcomeAdapter, NoEntryOutcome,
                AdmissionPredicate):
            raise TypeError("protocol operation contract must be one exact protocol contract record")
        self.contract.__post_init__()
        if type(self.source) is ProviderFactReference:
            self.source.__post_init__()
        elif type(self.source) is StaticProtocolGap:
            self.source.__post_init__()
        else:
            raise TypeError("protocol operation source must be ProviderFactReference or StaticProtocolGap")


def _state_sites(value: object, name: str) -> None:
    _exact(value, tuple, name)
    for item in value:
        if type(item) not in (ExistingAccess, InvokeStateOperand):
            raise TypeError(f"{name} must contain ExistingAccess or InvokeStateOperand")
        item.__post_init__()


def _model_port_types() -> tuple[type, type]:
    # Import only when constructing/validating a port, after model.py has loaded.
    from scar.ir.program.model import InvokeLiteralResult, OperationResult
    return OperationResult, InvokeLiteralResult


def _protocol_result_port(value: object, name: str) -> None:
    operation_result, invoke_result = _model_port_types()
    if type(value) is operation_result:
        value.__post_init__()
        _identifier(value.operation, OperationID, name + " operation")
        _index(value.index, name + " index")
        return
    if type(value) is invoke_result:
        value.__post_init__()
        _record(value.edge, ControlEdgeReference, name + " INVOKE edge")
        _identifier(value.edge.operation, OperationID, name + " INVOKE operation")
        _index(value.edge.successor_index, name + " INVOKE successor")
        _record(value.result, _completion_result_type(), name + " completion result")
        _index(value.result.index, name + " completion result index")
        return
    if type(value) is StaticProtocolGap:
        value.__post_init__()
        return
    raise TypeError(f"{name} must be an exact ordinary result, INVOKE result, or StaticProtocolGap")


def _completion_result_type() -> type:
    from scar.ir.program.model import CompletionResult
    return CompletionResult


def _protocol_source_port(value: object, name: str) -> None:
    if type(value) is OwnedUse:
        value.__post_init__()
    elif type(value) in _model_port_types():
        _protocol_result_port(value, name)
    elif type(value) in (DriveResult, ContractResult):
        value.__post_init__()
    elif type(value) is StaticProtocolGap:
        value.__post_init__()
    else:
        raise TypeError("protocol source port has an unsupported exact type")


def _adapter_output(value: object, name: str) -> None:
    if type(value) in _model_port_types() or type(value) is StaticProtocolGap:
        _protocol_result_port(value, name)
    elif type(value) in (HostTerminal, NativeExit):
        value.__post_init__()
    else:
        raise TypeError(f"{name} must be a result port, HostTerminal or NativeExit")


def _no_entry_input(value: object, name: str) -> None:
    # Deliberately excludes DriveResult: a no-entry route has no body Drive.
    if type(value) is ContractResult:
        value.__post_init__()
    else:
        _protocol_result_port(value, name)


def _terminal(value: object, name: str) -> None:
    if type(value) in (HostTerminal, NativeExit):
        value.__post_init__()
    else:
        raise TypeError(f"{name} must be HostTerminal or NativeExit")


# These aliases are rebound by model.py after the two canonical result classes
# have been defined. The placeholder keeps protocols.py independently importable.
ProtocolResultPort: TypeAlias = Any
ProtocolSourcePort: TypeAlias = Any
AdapterInputPort: TypeAlias = Any
NoEntryInputPort: TypeAlias = Any
_MODEL_PORT_CLASSES: tuple[type, type] | None = None


def _bind_model_ports(operation_result: type, invoke_literal_result: type) -> None:
    """Bind exact model-owned result classes after their definitions exist."""
    global ProtocolResultPort, ProtocolSourcePort, AdapterInputPort, NoEntryInputPort
    global _MODEL_PORT_CLASSES
    global OperationResult
    from scar.ir.program import model
    if operation_result is not model.OperationResult or invoke_literal_result is not model.InvokeLiteralResult:
        raise TypeError("protocol ports can bind only the canonical model result classes")
    if _MODEL_PORT_CLASSES is not None:
        if _MODEL_PORT_CLASSES != (operation_result, invoke_literal_result):
            raise RuntimeError("protocol model ports cannot be rebound")
        return
    ProtocolResultPort = Union[operation_result, invoke_literal_result, StaticProtocolGap]
    AdapterInputPort = Union[DriveResult, ContractResult]
    NoEntryInputPort = Union[ProtocolResultPort, ContractResult]
    ProtocolSourcePort = Union[
        OwnedUse, operation_result, invoke_literal_result, DriveResult, ContractResult,
        StaticProtocolGap,
    ]
    _MODEL_PORT_CLASSES = operation_result, invoke_literal_result
    # The new predicate result is the one ordinary canonical port, not the
    # broader protocol result union. Resolve its postponed annotation here.
    OperationResult = operation_result


ADMISSION_RECORD_TAGS = MappingProxyType({
    BodyStateCondition: ("kind", "PROTOCOL_BODY_STATE_CONDITION"),
    ReferenceIsNoneCondition: ("kind", "PROTOCOL_REFERENCE_IS_NONE_CONDITION"),
    AdmissionPredicate: ("kind", "PROTOCOL_ADMISSION_PREDICATE"),
})


PROTOCOL_RECORD_TAGS = MappingProxyType({
    StaticProtocolGap: ("kind", "STATIC_PROTOCOL_GAP"),
    DriverSubject: ("kind", "PROTOCOL_DRIVER_SUBJECT"),
    OperationSiteSubject: ("kind", "PROTOCOL_OPERATION_SITE_SUBJECT"),
    ProtocolScope: ("kind", "PROTOCOL_SCOPE"),
    OwnedUse: ("kind", "PROTOCOL_OWNED_USE"),
    RequestOperandBinding: ("kind", "REQUEST_OPERAND_BINDING"),
    DriveResult: ("kind", "PROTOCOL_DRIVE_RESULT"),
    ContractResult: ("kind", "PROTOCOL_CONTRACT_RESULT"),
    HostTerminal: ("kind", "PROTOCOL_HOST_TERMINAL"),
    NativeExit: ("kind", "PROTOCOL_NATIVE_EXIT"),
    RequestProcessing: ("kind", "PROTOCOL_REQUEST_PROCESSING"),
    ProtocolCall: ("kind", "PROTOCOL_CALL"),
    PacketConstruction: ("kind", "PROTOCOL_PACKET_CONSTRUCTION"),
    OutcomeAdapter: ("kind", "PROTOCOL_OUTCOME_ADAPTER"),
    NoEntryOutcome: ("kind", "PROTOCOL_NO_ENTRY_OUTCOME"),
    ProtocolOperation: ("kind", "PROTOCOL_OPERATION"),
    **ADMISSION_RECORD_TAGS,
})

__all__ = [
    "ADMISSION_RECORD_TAGS", "AdmissionPredicate", "BodyStateCondition",
    "BodyStatePredicateRule", "ReferenceIsNoneCondition",
    "AdapterInputPort", "ContractResult", "DriveResult", "DriverSubject",
    "HostTerminal", "NativeExit", "NoEntryInputPort", "NoEntryOutcome",
    "OperationSiteSubject", "OutcomeAdapter", "OutcomeAdapterRule", "OwnedUse",
    "PacketConstruction", "PacketRule", "PROTOCOL_RECORD_TAGS", "ProtocolCall",
    "ProtocolCallRule", "ProtocolClause", "ProtocolOperation", "ProtocolProfile",
    "ProtocolResultPort", "ProtocolScope", "ProtocolSourcePort", "RequestOperandBinding",
    "RequestProcessing", "RequestProcessingRule", "StaticGapReason", "StaticProtocolGap",
    "_bind_model_ports",
]

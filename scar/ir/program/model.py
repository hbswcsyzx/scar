"""Typed immutable records for the N1 canonical program graph.

These constructors enforce only facts available within one record (or one
owned tuple). Cross-record ownership, dominance, state flow, calls, and exits
belong to ``program.validation``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TypeAlias

from scar.ir.program.bindings import BindingDefinition, BindingRead
from scar.ir.program.control import (
    ControlPort, ControlScope, ExceptionPacketDefinition, PendingCompletionDefinition,
    PendingDispatchTerminator, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.source_subjects import FrameRoot, SourceCompilationFrameRoot
from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteTerminator, HandledContextDomain, HandledContextRead,
)
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    SuspendTerminator,
)
from scar.ir.program.drivers import (
    AsyncRequestCreate, BodyDrive, BodyDriveTerminator, DriverInterface,
    FinalBodyGate, RawRequestDefinition, RequestAssociationRead, ResumableCreate,
)
from scar.ir.program.lifecycle import (
    BodyOutcomeCommit, CreatedCloseTest, DriveOutcomeRef, DriverLifecycle, NoBodyFinish,
    SessionUpdate, TerminalFrameRelease,
)
from scar.ir.program.environments import EnvironmentInterface, FunctionEntryLayout
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.resources import (
    ResourceDefinition, ResourceLocation, ResourceRequirement, ResourceUse,
)
from scar.ir.program.providers import ProviderBinding, ProviderEnvelope, ProviderRegion
from scar.ir.program.native import BoundaryRelation, NativeBoundary
from scar.ir.program.call_effect_expansion import CallEffectExpansion
from scar.ir.program.state_modes import AccessMode
from scar.ir.program.state_addresses import StateAddressRefinement
from scar.ir.program.literal_sources import (ExactLiteralOrigin, LiteralDefinition,
    UninterpretedConstant, UnlocatedLiteral, require_definition)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.literals import PythonLiteral
from scar.ir.v2.ids import ValueSlotID


def _nonempty_text(value: object, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _exact_nonnegative_int(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _tuple(value: object, name: str) -> tuple:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    return value


def _unique(values: tuple, name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


class ValueKind(str, Enum):
    DATA = "DATA"
    REFERENCE = "REFERENCE"
    STATE = "STATE"


@dataclass(frozen=True, slots=True)
class ValueType:
    kind: ValueKind
    data_type: str | None = None
    location: LocationID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ValueKind):
            raise TypeError("ValueType.kind must be ValueKind")
        if self.data_type is not None:
            _nonempty_text(self.data_type, "ValueType.data_type")
        if self.location is not None and not isinstance(self.location, LocationID):
            raise TypeError("ValueType.location must be LocationID or None")
        if self.kind is ValueKind.DATA:
            if self.data_type is None or self.location is not None:
                raise ValueError("DATA type requires data_type and forbids location")
        elif self.kind is ValueKind.STATE:
            if self.location is None or self.data_type is not None:
                raise ValueError("STATE type requires location and forbids data_type")
        elif self.kind is ValueKind.REFERENCE:
            if self.data_type is not None or self.location is not None:
                raise ValueError("REFERENCE type carries neither data_type nor location")


@dataclass(frozen=True, slots=True)
class LocalBindingType:
    """The type of a local-name binding token, distinct from object values."""

    slot: ValueSlotID

    def __post_init__(self) -> None:
        if not isinstance(self.slot, ValueSlotID):
            raise TypeError("LocalBindingType.slot must be ValueSlotID")


class FootprintKind(str, Enum):
    WHOLE = "WHOLE"
    INTERVAL = "INTERVAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Footprint:
    kind: FootprintKind = FootprintKind.UNKNOWN
    start: int | None = None
    stop: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FootprintKind):
            raise TypeError("Footprint.kind must be FootprintKind")
        if self.kind is FootprintKind.INTERVAL:
            _exact_nonnegative_int(self.start, "Footprint.start")
            _exact_nonnegative_int(self.stop, "Footprint.stop")
            if self.stop < self.start:
                raise ValueError("INTERVAL footprint stop must not precede start")
        elif self.start is not None or self.stop is not None:
            raise ValueError("WHOLE and UNKNOWN footprints cannot carry interval bounds")


class Stability(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StateLocation:
    id: LocationID
    label: str
    extent: int | None = None
    stability: Stability = Stability.UNKNOWN

    def __post_init__(self) -> None:
        if not isinstance(self.id, LocationID):
            raise TypeError("StateLocation.id must be LocationID")
        _nonempty_text(self.label, "StateLocation.label")
        if self.extent is not None:
            _exact_nonnegative_int(self.extent, "StateLocation.extent")
        if not isinstance(self.stability, Stability):
            raise TypeError("StateLocation.stability must be Stability")


@dataclass(frozen=True, slots=True)
class LiteralOrigin:
    value: bool | int | float | str | None

    def __post_init__(self) -> None:
        if self.value is None or type(self.value) in (bool, int, str):
            return
        if type(self.value) is float and math.isfinite(self.value):
            return
        raise TypeError("literal origin must be an exact builtin scalar or None")


@dataclass(frozen=True, slots=True)
class BlockArgument:
    block: BlockID
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.block, BlockID):
            raise TypeError("BlockArgument.block must be BlockID")
        _exact_nonnegative_int(self.index, "BlockArgument.index")


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation: OperationID
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.operation, OperationID):
            raise TypeError("OperationResult.operation must be OperationID")
        _exact_nonnegative_int(self.index, "OperationResult.index")


def is_literal_origin(origin: object) -> bool:
    """Activation-local content origins; producer attachments are excluded."""
    return isinstance(origin, (LiteralOrigin, ExactLiteralOrigin))


Origin: TypeAlias = LiteralOrigin | ExactLiteralOrigin | BlockArgument | OperationResult


@dataclass(frozen=True, slots=True)
class DataValue:
    id: ValueID
    region: RegionID
    origin: Origin
    data_type: str

    def __post_init__(self) -> None:
        _value_fields(self.id, self.region, self.origin, allow_literal=True, allow_exact=True)
        _nonempty_text(self.data_type, "DataValue.data_type")
        if isinstance(self.origin, LiteralOrigin):
            expected_type = _literal_data_type(self.origin.value)
            if self.data_type != expected_type:
                raise ValueError(
                    f"literal DataValue type must be {expected_type!r} for its exact builtin value")

        if type(self.origin) is ExactLiteralOrigin:
            from scar.ir.literals import literal_builtin_type
            self.origin.__post_init__()
            kind = literal_builtin_type(self.origin.literal)
            expected_type = kind.__module__ + "." + kind.__qualname__
            if self.data_type != expected_type:
                raise ValueError(f"exact literal DataValue type must be {expected_type!r}")


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    id: ValueID
    region: RegionID
    origin: Origin
    referent_identity: str | None = None
    targets: tuple[LocationID, ...] | None = None
    selector: Footprint = Footprint()

    def __post_init__(self) -> None:
        _value_fields(self.id, self.region, self.origin, allow_literal=True)
        if self.referent_identity is not None:
            _nonempty_text(self.referent_identity, "ReferenceValue.referent_identity")
        if self.targets is not None:
            _tuple(self.targets, "ReferenceValue.targets")
            if any(not isinstance(item, LocationID) for item in self.targets):
                raise TypeError("ReferenceValue.targets must contain LocationID")
            _unique(self.targets, "ReferenceValue.targets")
        if not isinstance(self.selector, Footprint):
            raise TypeError("ReferenceValue.selector must be Footprint")
        if isinstance(self.origin, LiteralOrigin) and (
                self.referent_identity is not None
                or self.targets != ()
                or self.selector.kind is not FootprintKind.UNKNOWN):
            raise ValueError(
                "literal ReferenceValue requires unknown identity, empty targets, and UNKNOWN selector")


@dataclass(frozen=True, slots=True)
class StateVersionValue:
    id: ValueID
    region: RegionID
    origin: Origin
    location: LocationID

    def __post_init__(self) -> None:
        _value_fields(self.id, self.region, self.origin)
        if not isinstance(self.location, LocationID):
            raise TypeError("StateVersionValue.location must be LocationID")


@dataclass(frozen=True, slots=True)
class LocalBindingValue:
    """SSA token for whether one Python local slot is bound and to what."""

    id: ValueID
    region: RegionID
    origin: BlockArgument | OperationResult
    slot: ValueSlotID

    def __post_init__(self) -> None:
        _value_fields(self.id, self.region, self.origin)
        if not isinstance(self.slot, ValueSlotID):
            raise TypeError("LocalBindingValue.slot must be ValueSlotID")


@dataclass(frozen=True, slots=True)
class ProtocolValue:
    """SSA protocol payload, distinct from Python references and state contents."""

    id: ValueID
    region: RegionID
    origin: BlockArgument | OperationResult
    protocol: ProtocolValueKind

    def __post_init__(self) -> None:
        if type(self.id) is not ValueID or type(self.region) is not RegionID:
            raise TypeError("protocol value requires exact value and region IDs")
        if type(self.origin) not in (BlockArgument, OperationResult):
            raise TypeError("protocol value origin must be an exact argument or result")
        _value_fields(self.id, self.region, self.origin)
        if type(self.protocol) is not ProtocolValueKind:
            raise TypeError("protocol value needs an explicit ProtocolValueKind")


Value: TypeAlias = DataValue | ReferenceValue | StateVersionValue | LocalBindingValue | ProtocolValue
ProgramValueType: TypeAlias = ValueType | LocalBindingType | ProtocolValueType


def _value_fields(identity: object, region: object, origin: object, *,
                  allow_literal: bool = False, allow_exact: bool = False) -> None:
    if not isinstance(identity, ValueID):
        raise TypeError("value.id must be ValueID")
    if not isinstance(region, RegionID):
        raise TypeError("value.region must be RegionID")
    if not isinstance(origin, (LiteralOrigin, ExactLiteralOrigin, BlockArgument, OperationResult)):
        raise TypeError("value.origin must be a supported Origin record")
    if isinstance(origin, ExactLiteralOrigin) and type(origin) is not ExactLiteralOrigin:
        raise TypeError("exact literal origin must have exact record type")
    if isinstance(origin, ExactLiteralOrigin) and not allow_exact:
        raise ValueError("ExactLiteralOrigin is valid only for DataValue")
    if isinstance(origin, LiteralOrigin) and not allow_literal:
        raise ValueError("LiteralOrigin is valid only for DataValue")


def _literal_data_type(value: bool | int | float | str | None) -> str:
    if value is None:
        return "builtins.NoneType"
    if type(value) is bool:
        return "builtins.bool"
    if type(value) is int:
        return "builtins.int"
    if type(value) is float:
        return "builtins.float"
    if type(value) is str:
        return "builtins.str"
    raise TypeError("unsupported literal builtin value")


def value_type(value: Value) -> ProgramValueType:
    """Return the declared type carried by a program value record."""
    if isinstance(value, DataValue):
        return ValueType(ValueKind.DATA, data_type=value.data_type)
    if isinstance(value, ReferenceValue):
        return ValueType(ValueKind.REFERENCE)
    if isinstance(value, StateVersionValue):
        return ValueType(ValueKind.STATE, location=value.location)
    if isinstance(value, LocalBindingValue):
        return LocalBindingType(value.slot)
    if isinstance(value, ProtocolValue):
        return ProtocolValueType(value.protocol)
    raise TypeError("value_type requires a program Value record")


class Behavior(str, Enum):
    COMPUTE = "COMPUTE"
    READ = "READ"
    WRITE = "WRITE"
    REPRESENT = "REPRESENT"
    MEMORY = "MEMORY"
    TRANSFER = "TRANSFER"
    CONTROL = "CONTROL"
    ORDER = "ORDER"


class UseRole(str, Enum):
    DATA = "DATA"
    REFERENCE = "REFERENCE"
    STATE_CONTENT = "STATE_CONTENT"
    STATE_ORDER = "STATE_ORDER"
    LOCAL_BINDING = "LOCAL_BINDING"
    PROTOCOL = "PROTOCOL"


@dataclass(frozen=True, slots=True)
class Use:
    id: UseID
    value: ValueID
    role: UseRole = UseRole.DATA

    def __post_init__(self) -> None:
        if not isinstance(self.id, UseID):
            raise TypeError("Use.id must be UseID")
        if not isinstance(self.value, ValueID):
            raise TypeError("Use.value must be ValueID")
        if not isinstance(self.role, UseRole):
            raise TypeError("Use.role must be UseRole")


@dataclass(frozen=True, slots=True)
class StateAccess:
    location: LocationID
    before: UseID
    mode: AccessMode
    after: ValueID | None = None
    footprint: Footprint = Footprint()
    full_overwrite: bool = False
    reference: UseID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.location, LocationID):
            raise TypeError("StateAccess.location must be LocationID")
        if not isinstance(self.before, UseID):
            raise TypeError("StateAccess.before must be UseID")
        if not isinstance(self.mode, AccessMode):
            raise TypeError("StateAccess.mode must be AccessMode")
        if self.after is not None and not isinstance(self.after, ValueID):
            raise TypeError("StateAccess.after must be ValueID or None")
        if not isinstance(self.footprint, Footprint):
            raise TypeError("StateAccess.footprint must be Footprint")
        if type(self.full_overwrite) is not bool:
            raise TypeError("StateAccess.full_overwrite must be bool")
        if self.reference is not None and not isinstance(self.reference, UseID):
            raise TypeError("StateAccess.reference must be UseID or None")
        if self.mode is AccessMode.READ and self.after is not None:
            raise ValueError("READ access cannot define a new state value")
        if self.mode is not AccessMode.READ and self.after is None:
            raise ValueError("write access must define its after state value")
        if self.full_overwrite and (self.mode is not AccessMode.WRITE
                                    or self.footprint.kind is not FootprintKind.WHOLE):
            raise ValueError("full_overwrite requires WRITE mode and WHOLE footprint")


class ExitKind(str, Enum):
    NORMAL = "NORMAL"
    RAISE = "RAISE"


@dataclass(frozen=True, slots=True)
class ExitPort:
    name: str
    kind: ExitKind
    types: tuple[ValueType | ProtocolValueType, ...]

    def __post_init__(self) -> None:
        _nonempty_text(self.name, "ExitPort.name")
        if not isinstance(self.kind, ExitKind):
            raise TypeError("ExitPort.kind must be ExitKind")
        _tuple(self.types, "ExitPort.types")
        if any(not isinstance(item, (ValueType, ProtocolValueType)) for item in self.types):
            raise TypeError("ExitPort.types must contain value or protocol types")


class TerminatorKind(str, Enum):
    JUMP = "JUMP"
    BRANCH = "BRANCH"
    RETURN = "RETURN"
    RAISE = "RAISE"
    INVOKE = "INVOKE"
    PENDING_DISPATCH = "PENDING_DISPATCH"
    CLEANUP_ROUTE = "CLEANUP_ROUTE"
    SUSPEND = "SUSPEND"
    BODY_DRIVE = "BODY_DRIVE"


@dataclass(frozen=True, slots=True)
class Successor:
    block: BlockID
    arguments: tuple[UseID, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.block, BlockID):
            raise TypeError("Successor.block must be BlockID")
        _tuple(self.arguments, "Successor.arguments")
        if any(not isinstance(item, UseID) for item in self.arguments):
            raise TypeError("Successor.arguments must contain UseID")


@dataclass(frozen=True, slots=True)
class CompletionSignature:
    kind: ExitKind
    types: tuple[ValueType | ProtocolValueType, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExitKind):
            raise TypeError("CompletionSignature.kind must be ExitKind")
        _tuple(self.types, "CompletionSignature.types")
        if any(not isinstance(item, (ValueType, ProtocolValueType)) for item in self.types):
            raise TypeError("CompletionSignature.types must contain value or protocol types")


@dataclass(frozen=True, slots=True)
class CompletionResult:
    index: int

    def __post_init__(self) -> None:
        _exact_nonnegative_int(self.index, "CompletionResult.index")


@dataclass(frozen=True, slots=True)
class InvokeLiteralResult:
    edge: ControlEdgeReference
    result: CompletionResult

    def __post_init__(self):
        if type(self.edge) is not ControlEdgeReference:
            raise TypeError("literal completion requires exact ControlEdgeReference")
        self.edge.__post_init__()
        if type(self.edge.operation.value) is not str or not self.edge.operation.value:
            raise ValueError("literal completion operation ID requires exact nonempty string")
        if type(self.result) is not CompletionResult:
            raise TypeError("literal completion requires exact CompletionResult")
        self.result.__post_init__()


@dataclass(frozen=True, slots=True)
class LiteralEvaluation:
    """Content declaration on an original producer, never an object identity."""
    site: OperationResult | InvokeLiteralResult
    literal: PythonLiteral | UninterpretedConstant
    definition: LiteralDefinition = UnlocatedLiteral()

    def __post_init__(self):
        from scar.ir.literals import require_exact_literal
        if type(self.site) not in (OperationResult, InvokeLiteralResult):
            raise TypeError("literal evaluation requires exact original result site")
        self.site.__post_init__()
        if type(self.site) is OperationResult:
            if type(self.site.operation) is not OperationID:
                raise TypeError("literal result operation must be exact OperationID")
            if type(self.site.operation.value) is not str or not self.site.operation.value:
                raise ValueError("literal result operation ID requires exact nonempty string")
        if type(self.literal) is PythonLiteral:
            require_exact_literal(self.literal)
        elif type(self.literal) is UninterpretedConstant:
            self.literal.__post_init__()
        else:
            raise TypeError("literal evaluation payload must be exact or uninterpreted")
        require_definition(self.definition)


from scar.ir.program.stored_values import StoredValueRead, StoredValueWrite, _bind_model_results
_bind_model_results(OperationResult, InvokeLiteralResult)


# Protocol annotations resolve only after the canonical result port classes
# exist. The private binding installs these exact classes, never copies of them.
from scar.ir.program.protocols import (ProtocolOperation, ProtocolScope, _bind_model_ports)
_bind_model_ports(OperationResult, InvokeLiteralResult)

# P4 connection records use canonical model result/formal ports. Bind those
# late, after the original classes exist, then close the protocol unions before
# ProgramGraph captures their annotations.
from scar.ir.program.protocol_connections import (
    AsyncSessionOutcome, CancelDelivery, CancelDeliveryRef, CancelHandling,
    DelegateLookupFallback, NormalizedThrowSource,
    InitialAdvance, InjectedPacketTrigger,
    ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers, RawOperandSource,
    RawRequestTrigger, RequestAssociation, RequestStateCondition,
    RequestStateRule, ResumeSourceBinding, TaskCreatedTarget,
    TaskStatusRead, TaskStatusRule, TaskTargetRead, TaskTargetRole,
    TaskTargetSource, _bind_connection_model_ports, _bind_protocol_records,
)
_bind_connection_model_ports(OperationResult, InvokeLiteralResult, BlockArgument)
_bind_protocol_records()

from scar.ir.program.protocol_await_records import AwaitBodyLink, _bind_await_records
_bind_await_records()
from scar.ir.program.protocol_connections import ProtocolBinding, PROTOCOL_BINDING_TYPES

from scar.ir.program.exception_matches import ExceptionMatcher


@dataclass(frozen=True, slots=True)
class CompletionSuccessor:
    kind: ExitKind
    block: BlockID
    arguments: tuple[UseID | CompletionResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExitKind):
            raise TypeError("CompletionSuccessor.kind must be ExitKind")
        if not isinstance(self.block, BlockID):
            raise TypeError("CompletionSuccessor.block must be BlockID")
        _tuple(self.arguments, "CompletionSuccessor.arguments")
        if any(not isinstance(item, (UseID, CompletionResult)) for item in self.arguments):
            raise TypeError(
                "CompletionSuccessor.arguments must contain UseID or CompletionResult")


@dataclass(frozen=True, slots=True)
class Terminator:
    """Canonical control terminator.

    For ``BRANCH``, ``successors[0]`` is the true edge and
    ``successors[1]`` is the false edge. This meaning is part of the core IR
    contract and does not change the ordered wire representation.
    """

    kind: TerminatorKind
    successors: tuple[Successor | CompletionSuccessor, ...] = ()
    condition: UseID | None = None
    exit: str | None = None
    values: tuple[UseID, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TerminatorKind):
            raise TypeError("Terminator.kind must be TerminatorKind")
        if self.kind in (TerminatorKind.PENDING_DISPATCH, TerminatorKind.CLEANUP_ROUTE,
                         TerminatorKind.SUSPEND, TerminatorKind.BODY_DRIVE):
            raise ValueError(f"{self.kind.value} requires its dedicated typed terminator")
        _tuple(self.successors, "Terminator.successors")
        if any(not isinstance(item, (Successor, CompletionSuccessor)) for item in self.successors):
            raise TypeError("Terminator.successors must contain successor records")
        if self.condition is not None and not isinstance(self.condition, UseID):
            raise TypeError("Terminator.condition must be UseID or None")
        if self.exit is not None:
            _nonempty_text(self.exit, "Terminator.exit")
        _tuple(self.values, "Terminator.values")
        if any(not isinstance(item, UseID) for item in self.values):
            raise TypeError("Terminator.values must contain UseID")

        if self.kind is TerminatorKind.INVOKE:
            if (not self.successors
                    or any(not isinstance(item, CompletionSuccessor) for item in self.successors)
                    or len({item.kind for item in self.successors}) != len(self.successors)
                    or not {item.kind for item in self.successors} <= {ExitKind.NORMAL, ExitKind.RAISE}
                    or len({item.block for item in self.successors}) != len(self.successors)
                    or self.condition is not None or self.exit is not None or self.values):
                raise ValueError(
                    "INVOKE requires a nonempty subset of distinct NORMAL/RAISE completion successors and no other terminator payload")
        elif any(not isinstance(item, Successor) for item in self.successors):
            raise TypeError("only INVOKE may use CompletionSuccessor")
        elif self.kind is TerminatorKind.JUMP:
            if len(self.successors) != 1 or self.condition is not None or self.exit is not None or self.values:
                raise ValueError("JUMP requires one successor and no condition or exit payload")
        elif self.kind is TerminatorKind.BRANCH:
            if len(self.successors) != 2 or self.condition is None or self.exit is not None or self.values:
                raise ValueError("BRANCH requires two successors and one condition")
        elif self.kind is TerminatorKind.RETURN:
            if self.successors or self.condition is not None or self.exit is None:
                raise ValueError("RETURN requires an exit name and no successors or condition")
        elif self.kind is TerminatorKind.RAISE:
            if self.successors or self.condition is not None or self.exit is None:
                raise ValueError("RAISE requires an exit name and no successors or condition")


@dataclass(frozen=True, slots=True)
class Operation:
    id: OperationID
    label: str
    behaviors: tuple[Behavior, ...]
    uses: tuple[Use, ...] = ()
    results: tuple[ValueID, ...] = ()
    accesses: tuple[StateAccess, ...] = ()
    effects_complete: bool = False
    terminator: (Terminator | PendingDispatchTerminator | CleanupRouteTerminator
                 | SuspendTerminator | BodyDriveTerminator | None) = None
    callee: RegionID | None = None
    call_arguments: tuple[UseID, ...] = ()
    completions: tuple[CompletionSignature, ...] = ()
    invoke_arguments: tuple[UseID, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, OperationID):
            raise TypeError("Operation.id must be OperationID")
        _nonempty_text(self.label, "Operation.label")
        _tuple(self.behaviors, "Operation.behaviors")
        if any(not isinstance(item, Behavior) for item in self.behaviors):
            raise TypeError("Operation.behaviors must contain Behavior")
        _unique(self.behaviors, "Operation.behaviors")
        _tuple(self.uses, "Operation.uses")
        if any(not isinstance(item, Use) for item in self.uses):
            raise TypeError("Operation.uses must contain Use")
        _unique(tuple(item.id for item in self.uses), "Operation use IDs")
        _tuple(self.results, "Operation.results")
        if any(not isinstance(item, ValueID) for item in self.results):
            raise TypeError("Operation.results must contain ValueID")
        _unique(self.results, "Operation.results")
        _tuple(self.accesses, "Operation.accesses")
        if any(not isinstance(item, StateAccess) for item in self.accesses):
            raise TypeError("Operation.accesses must contain StateAccess")
        if type(self.effects_complete) is not bool:
            raise TypeError("Operation.effects_complete must be bool")
        if self.terminator is not None and not isinstance(
                self.terminator, (Terminator, PendingDispatchTerminator, CleanupRouteTerminator,
                                  SuspendTerminator, BodyDriveTerminator)):
            raise TypeError("Operation.terminator must be a typed terminator or None")
        if (isinstance(self.terminator, CleanupRouteTerminator)
                and type(self.terminator) is not CleanupRouteTerminator):
            raise TypeError("cleanup route terminator must be exact CleanupRouteTerminator")
        if isinstance(self.terminator, SuspendTerminator) and type(self.terminator) is not SuspendTerminator:
            raise TypeError("suspend terminator must be exact SuspendTerminator")
        if isinstance(self.terminator, BodyDriveTerminator) and type(self.terminator) is not BodyDriveTerminator:
            raise TypeError("body drive terminator must be exact BodyDriveTerminator")
        if self.callee is not None and not isinstance(self.callee, RegionID):
            raise TypeError("Operation.callee must be RegionID or None")
        _tuple(self.call_arguments, "Operation.call_arguments")
        if any(not isinstance(item, UseID) for item in self.call_arguments):
            raise TypeError("Operation.call_arguments must contain UseID")
        _tuple(self.completions, "Operation.completions")
        if any(not isinstance(item, CompletionSignature) for item in self.completions):
            raise TypeError("Operation.completions must contain CompletionSignature")
        _tuple(self.invoke_arguments, "Operation.invoke_arguments")
        if any(not isinstance(item, UseID) for item in self.invoke_arguments):
            raise TypeError("Operation.invoke_arguments must contain UseID")

        uses_by_id = {item.id: item for item in self.uses}
        if len(set(self.call_arguments)) != len(self.call_arguments):
            raise ValueError("Operation.call_arguments must not repeat a use")
        if any(item not in uses_by_id for item in self.call_arguments):
            raise ValueError("Operation.call_arguments must reference its own uses")
        if len(set(self.invoke_arguments)) != len(self.invoke_arguments):
            raise ValueError("Operation.invoke_arguments must not repeat a use")
        if any(item not in uses_by_id for item in self.invoke_arguments):
            raise ValueError("Operation.invoke_arguments must reference its own uses")
        is_invoke = (self.terminator is not None
                     and self.terminator.kind is TerminatorKind.INVOKE)
        is_body_drive = type(self.terminator) is BodyDriveTerminator
        if is_invoke and self.call_arguments:
            raise ValueError("INVOKE uses invoke_arguments, not call_arguments")
        if self.callee is None and self.call_arguments and not is_invoke:
            raise ValueError("call_arguments require a callee")
        if is_invoke:
            if self.results or self.accesses:
                raise ValueError("INVOKE cannot define ordinary results or state accesses")
            if (not self.completions
                    or len({item.kind for item in self.completions}) != len(self.completions)
                    or {item.kind for item in self.completions}
                       != {item.kind for item in self.terminator.successors}):
                raise ValueError("INVOKE requires unique completion signatures matching its actual completion edges")
        else:
            if self.completions:
                raise ValueError("only INVOKE may carry completion signatures")
            if self.invoke_arguments:
                raise ValueError("only INVOKE may carry invoke_arguments")
        if is_body_drive and (self.results or self.accesses or self.callee is not None
                              or self.call_arguments or self.completions or self.invoke_arguments):
            raise ValueError(
                "BODY_DRIVE cannot carry ordinary results, accesses, callee, call arguments, "
                "completions, or invoke arguments")
        for access in self.accesses:
            before = uses_by_id.get(access.before)
            if before is None:
                raise ValueError("StateAccess.before must reference an operation use")
            expected_role = (UseRole.STATE_ORDER if access.full_overwrite
                             else UseRole.STATE_CONTENT)
            if before.role is not expected_role:
                raise ValueError("StateAccess.before role disagrees with overwrite semantics")
            if access.reference is not None:
                reference = uses_by_id.get(access.reference)
                if reference is None or reference.role is not UseRole.REFERENCE:
                    raise ValueError("StateAccess.reference must name a REFERENCE use")

        if self.terminator is not None:
            terminator_uses = set(self.terminator.values)
            if isinstance(self.terminator, (PendingDispatchTerminator, CleanupRouteTerminator)):
                terminator_uses.add(self.terminator.pending)
            if self.terminator.condition is not None:
                terminator_uses.add(self.terminator.condition)
            for successor in self.terminator.successors:
                terminator_uses.update(item for item in successor.arguments if isinstance(item, UseID))
            if not terminator_uses <= set(uses_by_id):
                raise ValueError("terminator operands must reference this operation's uses")


@dataclass(frozen=True, slots=True)
class Block:
    id: BlockID
    arguments: tuple[ValueID, ...]
    operations: tuple[OperationID, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, BlockID):
            raise TypeError("Block.id must be BlockID")
        _tuple(self.arguments, "Block.arguments")
        if any(not isinstance(item, ValueID) for item in self.arguments):
            raise TypeError("Block.arguments must contain ValueID")
        _unique(self.arguments, "Block.arguments")
        _tuple(self.operations, "Block.operations")
        if any(not isinstance(item, OperationID) for item in self.operations):
            raise TypeError("Block.operations must contain OperationID")
        _unique(self.operations, "Block.operations")


@dataclass(frozen=True, slots=True)
class Region:
    id: RegionID
    label: str
    entry: BlockID
    blocks: tuple[Block, ...]
    exits: tuple[ExitPort, ...]
    parent: RegionID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, RegionID):
            raise TypeError("Region.id must be RegionID")
        _nonempty_text(self.label, "Region.label")
        if not isinstance(self.entry, BlockID):
            raise TypeError("Region.entry must be BlockID")
        _tuple(self.blocks, "Region.blocks")
        if any(not isinstance(item, Block) for item in self.blocks):
            raise TypeError("Region.blocks must contain Block")
        _unique(tuple(item.id for item in self.blocks), "Region block IDs")
        if self.entry not in {item.id for item in self.blocks}:
            raise ValueError("Region.entry must name one of its local blocks")
        _tuple(self.exits, "Region.exits")
        if any(not isinstance(item, ExitPort) for item in self.exits):
            raise TypeError("Region.exits must contain ExitPort")
        exit_names = tuple(item.name for item in self.exits)
        _unique(exit_names, "Region exit names")
        if self.parent is not None and not isinstance(self.parent, RegionID):
            raise TypeError("Region.parent must be RegionID or None")


@dataclass(frozen=True, slots=True)
class OrderEdge:
    before: OperationID
    after: OperationID

    def __post_init__(self) -> None:
        if not isinstance(self.before, OperationID) or not isinstance(self.after, OperationID):
            raise TypeError("OrderEdge endpoints must be OperationID")
        if self.before == self.after:
            raise ValueError("OrderEdge cannot order an operation before itself")


@dataclass(frozen=True, slots=True)
class ProgramGraph:
    root: RegionID
    regions: tuple[Region, ...]
    operations: tuple[Operation, ...]
    values: tuple[Value, ...]
    locations: tuple[StateLocation, ...] = ()
    ordering: tuple[OrderEdge, ...] = ()
    binding_definitions: tuple[BindingDefinition, ...] = ()
    binding_reads: tuple[BindingRead, ...] = ()
    resources: tuple[ResourceDefinition, ...] = ()
    resource_requirements: tuple[ResourceRequirement, ...] = ()
    resource_uses: tuple[ResourceUse, ...] = ()
    resource_locations: tuple[ResourceLocation, ...] = ()
    environments: tuple[EnvironmentInterface, ...] = ()
    function_entries: tuple[FunctionEntryLayout, ...] = ()
    control_scopes: tuple[ControlScope, ...] = ()
    control_ports: tuple[ControlPort, ...] = ()
    exception_packets: tuple[ExceptionPacketDefinition, ...] = ()
    pending_completions: tuple[PendingCompletionDefinition, ...] = ()
    provider_envelopes: tuple[ProviderEnvelope, ...] = ()
    provider_regions: tuple[ProviderRegion, ...] = ()
    provider_bindings: tuple[ProviderBinding, ...] = ()
    native_boundaries: tuple[NativeBoundary, ...] = ()
    boundary_relations: tuple[BoundaryRelation, ...] = ()
    handled_context_domains: tuple[HandledContextDomain, ...] = ()
    cleanup_interfaces: tuple[CleanupInterface, ...] = ()
    cleanup_enters: tuple[CleanupEnter, ...] = ()
    cleanup_resumes: tuple[CleanupResume, ...] = ()
    cleanup_replacements: tuple[CleanupReplace, ...] = ()
    handled_context_reads: tuple[HandledContextRead, ...] = ()
    resumable_bodies: tuple[ResumableBody, ...] = ()
    frame_context_initials: tuple[FrameContextInitial, ...] = ()
    frame_context_attaches: tuple[FrameContextAttach, ...] = ()
    frame_context_detaches: tuple[FrameContextDetach, ...] = ()
    raw_driver_requests: tuple[RawRequestDefinition, ...] = ()
    resumable_creates: tuple[ResumableCreate, ...] = ()
    async_request_creates: tuple[AsyncRequestCreate, ...] = ()
    request_association_reads: tuple[RequestAssociationRead, ...] = ()
    driver_interfaces: tuple[DriverInterface, ...] = ()
    final_body_gates: tuple[FinalBodyGate, ...] = ()
    body_drives: tuple[BodyDrive, ...] = ()
    driver_lifecycles: tuple[DriverLifecycle, ...] = ()
    body_outcome_commits: tuple[BodyOutcomeCommit, ...] = ()
    created_close_tests: tuple[CreatedCloseTest, ...] = ()
    no_body_finishes: tuple[NoBodyFinish, ...] = ()
    session_updates: tuple[SessionUpdate, ...] = ()
    terminal_frame_releases: tuple[TerminalFrameRelease, ...] = ()
    state_address_refinements: tuple[StateAddressRefinement, ...] = ()
    literal_evaluations: tuple[LiteralEvaluation, ...] = ()
    protocol_scopes: tuple[ProtocolScope, ...] = ()
    protocol_operations: tuple[ProtocolOperation, ...] = ()
    protocol_call_inputs: tuple[ProtocolCallInputs, ...] = ()
    protocol_result_consumers: tuple[ProtocolResultConsumers, ...] = ()
    protocol_bindings: tuple[ProtocolBinding, ...] = ()
    exception_matches: tuple[ExceptionMatcher, ...] = ()
    call_effect_expansions: tuple[CallEffectExpansion, ...] = ()
    stored_value_writes: tuple[StoredValueWrite, ...] = ()
    stored_value_reads: tuple[StoredValueRead, ...] = ()
    frame_roots: tuple[FrameRoot | SourceCompilationFrameRoot, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.root, RegionID):
            raise TypeError("ProgramGraph.root must be RegionID")
        roots = _tuple(self.frame_roots, "ProgramGraph.frame_roots")
        root_types = (FrameRoot, SourceCompilationFrameRoot)
        if any(type(row) not in root_types for row in roots):
            raise TypeError("ProgramGraph.frame_roots requires exact supported frame-root records")
        for row in roots:
            row.__post_init__()
        _unique(tuple(row.scope for row in roots), "ProgramGraph frame root scopes")
        for name, row_type in (("stored_value_writes", StoredValueWrite),
                               ("stored_value_reads", StoredValueRead)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not row_type for row in rows):
                raise TypeError("ProgramGraph." + name + " requires exact " + row_type.__name__ + " records")
            for row in rows:
                row.__post_init__()
        _unique(tuple((row.site, row.effect_index, row.completion) for row in self.stored_value_writes),
                "stored value write keys")
        _unique(tuple(row.result for row in self.stored_value_reads), "stored value read results")
        expansions = _tuple(self.call_effect_expansions, 'ProgramGraph.call_effect_expansions')
        if any(type(row) is not CallEffectExpansion for row in expansions):
            raise TypeError('call_effect_expansions requires exact CallEffectExpansion records')
        for row in expansions:
            row.__post_init__()
        _unique(tuple(row.operation for row in expansions), 'call effect expansion operations')
        matches = _tuple(self.exception_matches, 'ProgramGraph.exception_matches')
        if any(type(row) is not ExceptionMatcher for row in matches):
            raise TypeError('ProgramGraph.exception_matches requires exact ExceptionMatcher records')
        for row in matches:
            row.__post_init__()
        _unique(tuple(row.operation for row in matches), 'ProgramGraph exception matcher operations')
        for name, row_type in (("protocol_scopes", ProtocolScope),
                               ("protocol_operations", ProtocolOperation)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not row_type for row in rows):
                raise TypeError("ProgramGraph." + name + " requires exact protocol records")
            for row in rows:
                row.__post_init__()
        _unique(tuple(row.id for row in self.protocol_scopes), "protocol scope IDs")
        _unique(tuple((row.scope, row.clause, row.operation, row.slot)
                      for row in self.protocol_operations), "protocol operation keys")
        for name, row_type in (
                ("protocol_call_inputs", ProtocolCallInputs),
                ("protocol_result_consumers", ProtocolResultConsumers)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not row_type for row in rows):
                raise TypeError("ProgramGraph." + name + " requires exact connection records")
            for row in rows:
                row.__post_init__()
            _unique(tuple(row.site for row in rows), "ProgramGraph." + name + " sites")
        bindings = _tuple(self.protocol_bindings, "ProgramGraph.protocol_bindings")
        if any(type(row) not in PROTOCOL_BINDING_TYPES for row in bindings):
            raise TypeError("ProgramGraph.protocol_bindings requires a closed exact binding union")
        for row in bindings:
            row.__post_init__()
        binding_keys = []
        for row in bindings:
            if type(row) is AsyncSessionOutcome:
                key = (type(row), row.scope, row.update, row.source)
            elif type(row) is CancelDelivery:
                key = (type(row), row.scope, row.expected_target,
                       row.packet_source, row.consumer)
            elif type(row) is CancelHandling:
                key = (type(row), row.delivery, row.handler_packet)
            elif type(row) is DelegateLookupFallback:
                key = (type(row), row.lookup, row.matcher, row.guard)
            elif type(row) is AwaitBodyLink:
                key = (type(row), row.source, row.advance, row.drive, row.guard)
            else:
                key = (type(row), row.scope, row.result)
            binding_keys.append(key)
        _unique(tuple(binding_keys), "ProgramGraph protocol binding keys")
        evaluations = _tuple(self.literal_evaluations, "ProgramGraph.literal_evaluations")
        if any(type(row) is not LiteralEvaluation for row in evaluations):
            raise TypeError("literal_evaluations requires exact LiteralEvaluation records")
        for row in evaluations:
            row.__post_init__()
        _unique(tuple(row.site for row in evaluations), "literal evaluation sites")
        refinements = _tuple(self.state_address_refinements,
                             "ProgramGraph.state_address_refinements")
        if any(type(row) is not StateAddressRefinement for row in refinements):
            raise TypeError("ProgramGraph.state_address_refinements needs exact address records")
        for row in refinements:
            row.__post_init__()
        _unique(tuple(row.site for row in refinements),
                "ProgramGraph.state_address_refinements sites")
        for name, row_type, key in (
                ("handled_context_domains", HandledContextDomain, "region"),
                ("cleanup_interfaces", CleanupInterface, "scope"),
                ("cleanup_enters", CleanupEnter, "operation"),
                ("cleanup_resumes", CleanupResume, "operation"),
                ("cleanup_replacements", CleanupReplace, "operation"),
                ("handled_context_reads", HandledContextRead, "operation")):
            rows = _tuple(getattr(self, name), f"ProgramGraph.{name}")
            if any(type(item) is not row_type for item in rows):
                raise TypeError(f"ProgramGraph.{name} contains an invalid cleanup record")
            _unique(tuple(getattr(item, key) for item in rows), f"ProgramGraph.{name} keys")
        _unique(tuple(row.operation for rows in (
            self.cleanup_enters, self.cleanup_resumes, self.cleanup_replacements,
            self.handled_context_reads) for row in rows), "cleanup action operation IDs")
        for name, row_type, key in (
                ("resumable_bodies", ResumableBody, "region"),
                ("frame_context_initials", FrameContextInitial, "operation"),
                ("frame_context_attaches", FrameContextAttach, "operation"),
                ("frame_context_detaches", FrameContextDetach, "operation")):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not row_type for row in rows):
                raise TypeError("ProgramGraph." + name + " needs exact resumption records")
            _unique(tuple(getattr(row, key) for row in rows), "ProgramGraph." + name)
        _unique(tuple(row.operation for rows in (
            self.frame_context_initials, self.frame_context_attaches, self.frame_context_detaches,
            self.cleanup_enters, self.cleanup_resumes, self.cleanup_replacements,
            self.handled_context_reads) for row in rows), "context primitive operation IDs")
        for name, row_type, key in (
                ("raw_driver_requests", RawRequestDefinition, "value"),
                ("resumable_creates", ResumableCreate, "operation"),
                ("async_request_creates", AsyncRequestCreate, "operation"),
                ("request_association_reads", RequestAssociationRead, "operation"),
                ("driver_interfaces", DriverInterface, "region"),
                ("final_body_gates", FinalBodyGate, "operation"),
                ("body_drives", BodyDrive, "operation")):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(item) is not row_type for item in rows):
                raise TypeError("ProgramGraph." + name + " needs exact driver records")
            _unique(tuple(getattr(item, key) for item in rows),
                    "ProgramGraph." + name + " keys")
        _unique(tuple(row.operation for rows in (
            self.resumable_creates, self.async_request_creates,
            self.request_association_reads, self.final_body_gates, self.body_drives)
            for row in rows), "driver operation IDs")
        _tuple(self.driver_lifecycles, "ProgramGraph.driver_lifecycles")
        if any(type(row) is not DriverLifecycle for row in self.driver_lifecycles):
            raise TypeError("ProgramGraph.driver_lifecycles needs exact typed records")
        for row in self.driver_lifecycles:
            row.__post_init__()
        _unique(tuple(row.region for row in self.driver_lifecycles),
                "ProgramGraph driver lifecycle regions")
        _tuple(self.body_outcome_commits, "ProgramGraph.body_outcome_commits")
        if any(type(row) is not BodyOutcomeCommit for row in self.body_outcome_commits):
            raise TypeError("ProgramGraph.body_outcome_commits needs exact typed records")
        for row in self.body_outcome_commits:
            row.__post_init__()
        body_commit_operations = tuple(row.operation for row in self.body_outcome_commits)
        _unique(body_commit_operations, "ProgramGraph body outcome commit operations")
        for name, row_type in (
                ("created_close_tests", CreatedCloseTest),
                ("no_body_finishes", NoBodyFinish),
                ("session_updates", SessionUpdate),
                ("terminal_frame_releases", TerminalFrameRelease)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not row_type for row in rows):
                raise TypeError("ProgramGraph." + name + " needs exact typed records")
            for row in rows:
                row.__post_init__()
            _unique(tuple(row.operation for row in rows), "ProgramGraph." + name + " operations")
        created_close_operations = tuple(row.operation for row in self.created_close_tests)
        no_body_finish_operations = tuple(row.operation for row in self.no_body_finishes)
        lifecycle_operations = (
            *body_commit_operations, *created_close_operations, *no_body_finish_operations,
            *(row.operation for row in self.session_updates),
            *(row.operation for row in self.terminal_frame_releases))
        _unique(lifecycle_operations, "ProgramGraph lifecycle action operation IDs")
        existing_role_operations = {
            row.operation for rows in (
                self.resumable_creates, self.async_request_creates,
                self.request_association_reads, self.final_body_gates, self.body_drives,
                self.frame_context_initials, self.frame_context_attaches,
                self.frame_context_detaches, self.cleanup_enters, self.cleanup_resumes,
                self.cleanup_replacements, self.handled_context_reads,
            ) for row in rows
        }
        if existing_role_operations.intersection(lifecycle_operations):
            raise ValueError(
                "lifecycle action operation conflicts with another typed operation role")
        for name, rows, row_type, id_field in (
            ("regions", self.regions, Region, "id"),
            ("operations", self.operations, Operation, "id"),
            ("values", self.values, (DataValue, ReferenceValue, StateVersionValue,
                                      LocalBindingValue, ProtocolValue), "id"),
            ("locations", self.locations, StateLocation, "id"),
        ):
            _tuple(rows, f"ProgramGraph.{name}")
            if any(not isinstance(item, row_type) for item in rows):
                raise TypeError(f"ProgramGraph.{name} contains an invalid record")
            _unique(tuple(getattr(item, id_field) for item in rows),
                    f"ProgramGraph.{name} IDs")
        _tuple(self.ordering, "ProgramGraph.ordering")
        if any(not isinstance(item, OrderEdge) for item in self.ordering):
            raise TypeError("ProgramGraph.ordering must contain OrderEdge")
        _tuple(self.binding_definitions, "ProgramGraph.binding_definitions")
        if any(not isinstance(item, BindingDefinition) for item in self.binding_definitions):
            raise TypeError("ProgramGraph.binding_definitions must contain BindingDefinition")
        _tuple(self.binding_reads, "ProgramGraph.binding_reads")
        if any(not isinstance(item, BindingRead) for item in self.binding_reads):
            raise TypeError("ProgramGraph.binding_reads must contain BindingRead")
        for name, row_type in (("resources", ResourceDefinition),
                               ("resource_requirements", ResourceRequirement),
                               ("resource_uses", ResourceUse),
                               ("resource_locations", ResourceLocation)):
            rows = _tuple(getattr(self, name), f"ProgramGraph.{name}")
            if any(type(item) is not row_type for item in rows):
                raise TypeError(f"ProgramGraph.{name} contains an invalid resource record")
            _unique(rows, f"ProgramGraph.{name}")
        _unique(tuple(row.id for row in self.resources), "ProgramGraph resource IDs")
        _unique(tuple(row.id for row in self.resource_requirements),
                "ProgramGraph resource requirement IDs")
        _tuple(self.environments, "ProgramGraph.environments")
        if any(type(item) is not EnvironmentInterface for item in self.environments):
            raise TypeError("ProgramGraph.environments contains an invalid environment interface")
        _unique(tuple(item.id for item in self.environments),
                "ProgramGraph environment interface IDs")
        _tuple(self.function_entries, "ProgramGraph.function_entries")
        if any(type(item) is not FunctionEntryLayout for item in self.function_entries):
            raise TypeError("ProgramGraph.function_entries contains an invalid entry layout")
        _unique(tuple(item.environment for item in self.function_entries),
                "ProgramGraph function entry environments")
        for name, cls, key in (
                ("control_scopes", ControlScope, "id"),
                ("control_ports", ControlPort, "id"),
                ("exception_packets", ExceptionPacketDefinition, "value"),
                ("pending_completions", PendingCompletionDefinition, "value")):
            rows = getattr(self, name)
            _tuple(rows, "ProgramGraph." + name)
            if any(type(row) is not cls for row in rows):
                raise TypeError("ProgramGraph." + name + " needs exact typed records")
            _unique(tuple(getattr(row, key) for row in rows), "ProgramGraph." + name)
        for name, cls in (("provider_envelopes", ProviderEnvelope),
                          ("provider_regions", ProviderRegion),
                          ("provider_bindings", ProviderBinding)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not cls for row in rows):
                raise TypeError("ProgramGraph." + name + " needs exact typed records")
            _unique(rows, "ProgramGraph." + name)
        _unique(tuple(row.id for row in self.provider_envelopes),
                "ProgramGraph provider IDs")
        for name, cls in (("native_boundaries", NativeBoundary),
                          ("boundary_relations", BoundaryRelation)):
            rows = _tuple(getattr(self, name), "ProgramGraph." + name)
            if any(type(row) is not cls for row in rows):
                raise TypeError("ProgramGraph." + name + " needs exact typed records")
            _unique(tuple(row.id for row in rows), "ProgramGraph." + name + " IDs")


__all__ = [
    "StoredValueWrite", "StoredValueRead",
    "ProtocolScope", "ProtocolOperation", "ProtocolOperationRef",
    "RawOperandSource", "RawRequestTrigger", "InjectedPacketTrigger", "InitialAdvance",
    "ProtocolCallInputCase", "ProtocolCallInputs", "ResumeSourceBinding",
    "ProtocolResultConsumers", "RequestAssociation", "RequestStateCondition",
    "RequestStateRule", "AsyncSessionOutcome", "TaskCreatedTarget", "TaskTargetRead",
    "TaskTargetRole", "TaskTargetSource", "CancelDelivery", "CancelDeliveryRef",
    "CancelHandling", "TaskStatusRead", "TaskStatusRule", "ProtocolBinding",
    "ExactLiteralOrigin", "LiteralEvaluation", "InvokeLiteralResult", "is_literal_origin",
    "AccessMode", "Behavior", "Block", "BlockArgument", "DataValue", "ExitKind",
    "CompletionResult", "CompletionSignature", "CompletionSuccessor", "ExitPort",
    "AsyncRequestCreate", "BodyDrive", "BodyDriveTerminator", "DriverInterface",
    "BodyOutcomeCommit", "CreatedCloseTest", "DriveOutcomeRef", "DriverLifecycle",
    "NoBodyFinish",
    "FinalBodyGate", "RawRequestDefinition", "RequestAssociationRead", "ResumableCreate",
    "Footprint", "FootprintKind", "LiteralOrigin", "LocalBindingType",
    "LocalBindingValue", "Operation", "OperationResult", "ProtocolValue",
    "OrderEdge", "Origin", "ProgramGraph",
    "ReferenceValue", "Region", "Stability", "StateAccess", "StateLocation",
    "StateAddressRefinement",
    "StateVersionValue", "Successor", "Terminator", "TerminatorKind", "Use",
    "ProgramValueType", "UseRole", "Value", "ValueKind", "ValueType", "value_type",
]

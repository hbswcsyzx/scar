"""Qualified static call relations over original graphs; never invocations.

These records add relationships, not operations, values or state carriers.
Every target is conditional. A sole candidate is not a verified dynamic target.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import copy
import json

from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from .functions import CandidateBinding
from .ids import BlockID, EnvironmentInterfaceID, LocationID, OperationID, UseID, ValueID
from .environments import EnvironmentMember, EnvironmentRole
from .model import ExitKind, ValueKind
from .native import ExitPortRef
from .providers import ProviderArtifact
from .source_call_bindings import SourceArgumentPort, SourceBodyNamespace
from .source_references import SourceDefinitionReference
from .source_returns import SourceReturnSite
from .structured import ControlEdgeReference


def _exact(value, kind):
    if type(value) is not kind:
        raise TypeError("static calls require exact " + kind.__name__)
    method = getattr(value, "__post_init__", None)
    if method is not None:
        method()


def _rows(value, kind):
    if type(value) is not tuple:
        raise TypeError("static relation rows must be tuples")
    for row in value:
        _exact(row, kind)


@dataclass(frozen=True, slots=True)
class StaticCallFrontier:
    kind: str
    detail: str
    source: SourceReference | None = None

    def __post_init__(self):
        if any(type(text) is not str or not text for text in (self.kind, self.detail)):
            raise ValueError("static frontier needs a precise kind/detail")
        if self.source is not None:
            _exact(self.source, SourceReference)


@dataclass(frozen=True, slots=True)
class StaticTerminalPort:
    """One original callee terminal operand, conditional on that exit site."""
    port: ExitPortRef
    block: BlockID
    operation: OperationID
    use: UseID
    value: ValueID

    def __post_init__(self):
        for value, kind in ((self.port, ExitPortRef), (self.block, BlockID),
                            (self.operation, OperationID), (self.use, UseID), (self.value, ValueID)):
            _exact(value, kind)


@dataclass(frozen=True, slots=True)
class StaticCompletionRoute:
    """Callee exit alternatives -> caller produced completion formal.

    STATE maps call interfaces, never equates LocationIDs or proves mod/ref.
    Reference payload mapping is language dependence, not observed equality.
    """
    kind: ExitKind
    value_kind: ValueKind
    caller_edge: ControlEdgeReference
    completion_index: int
    landing_block: BlockID
    landing_value: ValueID
    callee_port: ExitPortRef
    terminals: tuple[StaticTerminalPort, ...]

    def __post_init__(self):
        for value, kind in ((self.kind, ExitKind), (self.value_kind, ValueKind),
                            (self.caller_edge, ControlEdgeReference), (self.landing_block, BlockID),
                            (self.landing_value, ValueID), (self.callee_port, ExitPortRef)):
            _exact(value, kind)
        if type(self.completion_index) is not int or self.completion_index < 0:
            raise ValueError("completion index must be nonnegative")
        _rows(self.terminals, StaticTerminalPort)
        if not self.terminals or any(row.port != self.callee_port for row in self.terminals):
            raise ValueError("completion route needs its original exact terminal alternatives")


@dataclass(frozen=True, slots=True)
class StaticStateEntryRoute:
    caller_use: UseID
    caller_value: ValueID
    caller_location: LocationID
    callee_value: ValueID
    callee_location: LocationID
    basis: str = "COARSE_CALL_WORLD_INTERFACE_NOT_LOCATION_IDENTITY"

    def __post_init__(self):
        for value, kind in ((self.caller_use, UseID), (self.caller_value, ValueID),
                            (self.callee_value, ValueID), (self.caller_location, LocationID),
                            (self.callee_location, LocationID)):
            _exact(value, kind)
        if self.basis != "COARSE_CALL_WORLD_INTERFACE_NOT_LOCATION_IDENTITY":
            raise ValueError("static state mapping cannot claim state-content identity")


@dataclass(frozen=True, slots=True)
class StaticCallTarget:
    definition: SourceDefinitionReference
    body: SourceBodyNamespace | None
    basis: tuple[str, ...]
    binding: CandidateBinding | None = None
    arguments: tuple[SourceArgumentPort, ...] = ()
    normal_returns: tuple[SourceReturnSite, ...] = ()
    completions: tuple[StaticCompletionRoute, ...] = ()
    state_entry: StaticStateEntryRoute | None = None
    frontiers: tuple[StaticCallFrontier, ...] = ()
    qualification: str = "CONDITIONAL_STATIC_CANDIDATE"
    environment_routes: tuple[StaticFunctionEnvironmentRoute, ...] = ()

    def __post_init__(self):
        _exact(self.definition, SourceDefinitionReference)
        if self.body is not None:
            _exact(self.body, SourceBodyNamespace)
            if self.body.definition != self.definition.definition or self.body.source != self.definition.source:
                raise ValueError("callee body differs from the original qualified definition")
        if type(self.basis) is not tuple or not self.basis or any(type(x) is not str or not x for x in self.basis):
            raise ValueError("candidate needs explicit source-resolution bases")
        if self.binding is not None:
            _exact(self.binding, CandidateBinding)
            if self.binding.target != self.definition.definition:
                raise ValueError("signature binding names another candidate")
        for rows, kind in ((self.arguments, SourceArgumentPort), (self.normal_returns, SourceReturnSite),
                           (self.completions, StaticCompletionRoute), (self.frontiers, StaticCallFrontier)):
            _rows(rows, kind)
        if self.state_entry is not None:
            _exact(self.state_entry, StaticStateEntryRoute)
        _rows(self.environment_routes, StaticFunctionEnvironmentRoute)
        if self.body is None and (self.arguments or self.normal_returns or self.completions or self.state_entry or self.environment_routes):
            raise ValueError("missing body cannot supply invented ports")
        if self.body is not None:
            if any(port.formal_body != self.body for port in self.arguments):
                raise ValueError("formal belongs to another body namespace")
            if any(route.callee_port.region != self.body.region for route in self.completions):
                raise ValueError("completion belongs to another callee region")
            if any(route.callee != self.body or route.creation.definition != self.definition for route in self.environment_routes):
                raise ValueError("function environment belongs to another qualified callee or factory definition")
        if self.qualification != "CONDITIONAL_STATIC_CANDIDATE":
            raise ValueError("static target cannot claim an observed or unconditional dispatch")


class NamespaceFlowCondition(str, Enum):
    PATH_TAKEN = "PATH_TAKEN"
    ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT = "ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT"
    NORMAL_READ_RETURNS_MAPPING_BINDING = "NORMAL_READ_RETURNS_MAPPING_BINDING"
    INTERVENING_EFFECTS_PRESERVE_BINDING = "INTERVENING_EFFECTS_PRESERVE_BINDING"
    PRIOR_LOOKUP_NAMESPACES_MISSING = "PRIOR_LOOKUP_NAMESPACES_MISSING"
    NAMESPACE_OWNERS_ALIAS = "NAMESPACE_OWNERS_ALIAS"


@dataclass(frozen=True, slots=True)
class StaticNamespaceFlow:
    """Conditional binding dependence, not a mapping-content or alias proof.

    The two key Uses are separate references whose builtin string values agree.
    All endpoint IDs and path edges belong to the enclosing caller namespace.
    """
    write_operation: OperationID
    write_owner: UseID
    write_key: UseID
    assigned_reference: UseID
    write_world: UseID
    write_normal: ControlEdgeReference
    read_operation: OperationID
    read_owner: UseID
    read_key: UseID
    read_world: UseID
    read_normal: ControlEdgeReference
    read_result: ValueID
    prior_lookup_owners: tuple[UseID, ...]
    path: tuple[ControlEdgeReference, ...]
    intervening_operations: tuple[OperationID, ...]
    conditions: tuple[NamespaceFlowCondition, ...]
    qualification: str = "CONDITIONAL_NAMESPACE_BINDING_FLOW"

    def __post_init__(self):
        for value, kind in ((self.write_operation, OperationID), (self.read_operation, OperationID),
                            (self.write_owner, UseID), (self.write_key, UseID),
                            (self.assigned_reference, UseID), (self.write_world, UseID),
                            (self.read_owner, UseID), (self.read_key, UseID), (self.read_world, UseID),
                            (self.write_normal, ControlEdgeReference), (self.read_normal, ControlEdgeReference),
                            (self.read_result, ValueID)):
            _exact(value, kind)
        for rows, kind in ((self.prior_lookup_owners, UseID), (self.path, ControlEdgeReference),
                           (self.intervening_operations, OperationID), (self.conditions, NamespaceFlowCondition)):
            _rows(rows, kind)
        required = {NamespaceFlowCondition.PATH_TAKEN, NamespaceFlowCondition.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT,
                    NamespaceFlowCondition.NORMAL_READ_RETURNS_MAPPING_BINDING,
                    NamespaceFlowCondition.INTERVENING_EFFECTS_PRESERVE_BINDING}
        if not required <= set(self.conditions) or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("namespace dependence must retain mapping/path/effect conditions")
        if bool(self.prior_lookup_owners) != (NamespaceFlowCondition.PRIOR_LOOKUP_NAMESPACES_MISSING in self.conditions):
            raise ValueError("lookup priority condition differs from its original preceding owner Uses")
        if self.qualification != "CONDITIONAL_NAMESPACE_BINDING_FLOW":
            raise ValueError("namespace dependence cannot claim unconditional content identity")


@dataclass(frozen=True, slots=True)
class StaticFunctionCreationRoute:
    factory: OperationID
    normal_edge: ControlEdgeReference
    normal_value: ValueID
    code_use: UseID
    code_constant_operation: OperationID
    code_layout_key: str
    constant_path: tuple[int, ...]
    definition: SourceDefinitionReference

    def __post_init__(self):
        for value, kind in ((self.factory, OperationID), (self.normal_edge, ControlEdgeReference),
                            (self.normal_value, ValueID), (self.code_use, UseID),
                            (self.code_constant_operation, OperationID), (self.definition, SourceDefinitionReference)):
            _exact(value, kind)
        if type(self.code_layout_key) is not str or not self.code_layout_key:
            raise ValueError("creation needs its source-compiled layout key")
        if type(self.constant_path) is not tuple or not self.constant_path or any(type(i) is not int or i < 0 for i in self.constant_path):
            raise ValueError("creation needs an exact original child constant path")


@dataclass(frozen=True, slots=True)
class StaticQualifiedNamespaceFlow:
    """A local dependence whose endpoint IDs retain their original body."""
    body: SourceBodyNamespace
    flow: StaticNamespaceFlow

    def __post_init__(self):
        _exact(self.body, SourceBodyNamespace)
        _exact(self.flow, StaticNamespaceFlow)


@dataclass(frozen=True, slots=True)
class StaticQualifiedFunctionCreation:
    body: SourceBodyNamespace
    creation: StaticFunctionCreationRoute

    def __post_init__(self):
        _exact(self.body, SourceBodyNamespace)
        _exact(self.creation, StaticFunctionCreationRoute)


class FunctionEnvironmentRouteKind(str, Enum):
    REFERENCE_BINDING = "REFERENCE_BINDING"
    FIELD_INITIALIZER_DEPENDENCE = "FIELD_INITIALIZER_DEPENDENCE"


class FunctionEnvironmentCondition(str, Enum):
    TARGET_SELECTS_THIS_CREATION = "TARGET_SELECTS_THIS_CREATION"
    FACTORY_COMPLETED_NORMALLY = "FACTORY_COMPLETED_NORMALLY"
    CALLEE_DERIVES_FROM_THIS_FACTORY_OCCURRENCE = "CALLEE_DERIVES_FROM_THIS_FACTORY_OCCURRENCE"
    FUNCTION_CODE_MATCHES_CREATION = "FUNCTION_CODE_MATCHES_CREATION"
    FUNCTION_FIELD_PRESERVED_SINCE_CREATION = "FUNCTION_FIELD_PRESERVED_SINCE_CREATION"
    PACKED_INITIALIZER_RELATION_REQUIRED = "PACKED_INITIALIZER_RELATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class StaticFunctionEnvironmentRoute:
    """Original reference/member ports under a selected factory occurrence.

    Factory sites may execute repeatedly. These conditions select the callable
    reaching this call, rather than equating all instances with common code.
    Locations and cell contents are not identified by reference routing. A
    FIELD_INITIALIZER_DEPENDENCE is never a scalar-to-aggregate alias claim.
    """
    caller: SourceBodyNamespace
    call_operation: OperationID
    callee_use: UseID
    callee_value: ValueID
    call_world: UseID
    call_world_value: ValueID
    creation_body: SourceBodyNamespace
    creation: StaticFunctionCreationRoute
    factory_world: UseID
    factory_world_value: ValueID
    factory_post_world: ValueID
    source_use: UseID | None
    source_value: ValueID
    source_role: str
    source_index: int | None
    callee: SourceBodyNamespace
    environment: EnvironmentInterfaceID
    member: EnvironmentMember
    kind: FunctionEnvironmentRouteKind
    conditions: tuple[FunctionEnvironmentCondition, ...]
    qualification: str = "CONDITIONAL_FACTORY_ENVIRONMENT_DEPENDENCE"

    def __post_init__(self):
        for value,kind in ((self.caller,SourceBodyNamespace),(self.creation_body,SourceBodyNamespace),
                          (self.callee,SourceBodyNamespace),(self.call_operation,OperationID),
                          (self.callee_use,UseID),(self.callee_value,ValueID),(self.call_world,UseID),
                          (self.call_world_value,ValueID),(self.creation,StaticFunctionCreationRoute),
                          (self.factory_world,UseID),(self.factory_world_value,ValueID),
                          (self.factory_post_world,ValueID),(self.source_value,ValueID),
                          (self.environment,EnvironmentInterfaceID),(self.member,EnvironmentMember),
                          (self.kind,FunctionEnvironmentRouteKind)):
            _exact(value,kind)
        _rows(self.conditions,FunctionEnvironmentCondition)
        required={FunctionEnvironmentCondition.TARGET_SELECTS_THIS_CREATION,
                  FunctionEnvironmentCondition.FACTORY_COMPLETED_NORMALLY,
                  FunctionEnvironmentCondition.CALLEE_DERIVES_FROM_THIS_FACTORY_OCCURRENCE,
                  FunctionEnvironmentCondition.FUNCTION_CODE_MATCHES_CREATION}
        if not required<=set(self.conditions) or len(set(self.conditions))!=len(self.conditions):
            raise ValueError("function environment must retain selected occurrence/code/normal conditions")
        if self.callee.definition!=self.creation.definition.definition or self.callee.source!=self.creation.definition.source:
            raise ValueError("environment target differs from the original factory source definition")
        if self.member.role is EnvironmentRole.FUNCTION_OBJECT:
            if (self.source_use is not None or self.source_index is not None
                    or self.source_value!=self.creation.normal_value
                    or self.source_role!='factory-normal-function'
                    or self.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING):
                raise ValueError("function-object projection must use the original factory normal reference")
        else:
            _exact(self.source_use,UseID)
            if type(self.source_role)is not str or not self.source_role or type(self.source_index)is not int or self.source_index<0:
                raise ValueError("factory input projection needs its actual source role/index")
        if self.member.role in (EnvironmentRole.DEFAULTS,EnvironmentRole.KEYWORD_DEFAULTS):
            if (self.kind is not FunctionEnvironmentRouteKind.FIELD_INITIALIZER_DEPENDENCE
                    or FunctionEnvironmentCondition.FUNCTION_FIELD_PRESERVED_SINCE_CREATION not in self.conditions):
                raise ValueError("mutable default fields only have conditional initializer dependence")
        elif self.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING:
            raise ValueError("nondefault environment role requires reference binding")
        if self.member.role is EnvironmentRole.BUILTINS_NAMESPACE:
            raise ValueError("saved builtins requires a separate creation-time selection relation")
        if self.qualification!='CONDITIONAL_FACTORY_ENVIRONMENT_DEPENDENCE':
            raise ValueError("environment route cannot claim runtime identity or unconditional field equality")


@dataclass(frozen=True, slots=True)
class StaticQualifiedNamespaceWrite:
    body: SourceBodyNamespace
    operation: OperationID
    owner: UseID
    key: UseID
    assigned_reference: UseID
    world: UseID
    normal: ControlEdgeReference

    def __post_init__(self):
        for value, kind in ((self.body, SourceBodyNamespace), (self.operation, OperationID),
                            (self.owner, UseID), (self.key, UseID), (self.assigned_reference, UseID),
                            (self.world, UseID), (self.normal, ControlEdgeReference)):
            _exact(value, kind)
        if self.normal.operation != self.operation:
            raise ValueError("namespace write normal edge belongs to another operation")


@dataclass(frozen=True, slots=True)
class StaticQualifiedNamespaceRead:
    body: SourceBodyNamespace
    operation: OperationID
    owner: UseID
    key: UseID
    world: UseID
    normal: ControlEdgeReference
    result: ValueID
    prior_lookup_owners: tuple[UseID, ...] = ()

    def __post_init__(self):
        for value, kind in ((self.body, SourceBodyNamespace), (self.operation, OperationID),
                            (self.owner, UseID), (self.key, UseID), (self.world, UseID),
                            (self.normal, ControlEdgeReference), (self.result, ValueID)):
            _exact(value, kind)
        _rows(self.prior_lookup_owners, UseID)
        if self.normal.operation != self.operation:
            raise ValueError("namespace read normal edge belongs to another operation")


class NamespacePathStart(str, Enum):
    WRITE_NORMAL = "WRITE_NORMAL"
    ENTRY = "ENTRY"


@dataclass(frozen=True, slots=True)
class StaticNamespacePathSegment:
    """Original local CFG witness, ending immediately before a real operation.

    ``key`` is the query's builtin string value, not a fabricated graph Use.
    An entry segment starts at the original region entry, not a fake LOAD.
    """
    body: SourceBodyNamespace
    start_kind: NamespacePathStart
    start_block: BlockID
    start_operation: OperationID | None
    start_owner: ValueID
    query_operation: OperationID
    query_owner: ValueID
    query_world: UseID
    key: str
    path: tuple[ControlEdgeReference, ...]
    intervening_operations: tuple[OperationID, ...]
    conditions: tuple[NamespaceFlowCondition, ...]

    def __post_init__(self):
        for value, kind in ((self.body, SourceBodyNamespace), (self.start_kind, NamespacePathStart),
                            (self.start_block, BlockID), (self.start_owner, ValueID),
                            (self.query_operation, OperationID), (self.query_owner, ValueID),
                            (self.query_world, UseID)):
            _exact(value, kind)
        if self.start_operation is not None:
            _exact(self.start_operation, OperationID)
        if (self.start_kind is NamespacePathStart.WRITE_NORMAL) != (self.start_operation is not None):
            raise ValueError("only write-normal paths have an original start operation")
        if type(self.key) is not str:
            raise TypeError("namespace path key must be its builtin string value")
        for rows, kind in ((self.path, ControlEdgeReference), (self.intervening_operations, OperationID),
                           (self.conditions, NamespaceFlowCondition)):
            _rows(rows, kind)
        required = {NamespaceFlowCondition.PATH_TAKEN, NamespaceFlowCondition.INTERVENING_EFFECTS_PRESERVE_BINDING}
        if self.start_kind is NamespacePathStart.WRITE_NORMAL:
            required.add(NamespaceFlowCondition.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT)
        if self.start_owner != self.query_owner:
            required.add(NamespaceFlowCondition.NAMESPACE_OWNERS_ALIAS)
        if not required <= set(self.conditions) or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("namespace path must retain path/effect/owner conditions")


class CrossBodyNamespaceCondition(str, Enum):
    CALL_SELECTS_ENVIRONMENT_ROUTE = "CALL_SELECTS_ENVIRONMENT_ROUTE"
    CALLER_OWNER_ALIASES_FACTORY_GLOBALS = "CALLER_OWNER_ALIASES_FACTORY_GLOBALS"
    CALL_ENTRY_PRESERVES_NAMESPACE_BINDING = "CALL_ENTRY_PRESERVES_NAMESPACE_BINDING"


@dataclass(frozen=True, slots=True)
class StaticNamespaceCallBridge:
    """Call-entry dependence; never equates namespace contents or locations."""
    environment: StaticFunctionEnvironmentRoute
    state_entry: StaticStateEntryRoute
    caller_owner: ValueID
    callee_owner: ValueID
    conditions: tuple[CrossBodyNamespaceCondition, ...]
    caller_owner_routes: tuple[StaticFunctionEnvironmentRoute, ...] = ()

    def __post_init__(self):
        for value, kind in ((self.environment, StaticFunctionEnvironmentRoute),
                            (self.state_entry, StaticStateEntryRoute),
                            (self.caller_owner, ValueID), (self.callee_owner, ValueID)):
            _exact(value, kind)
        _rows(self.conditions, CrossBodyNamespaceCondition)
        _rows(self.caller_owner_routes, StaticFunctionEnvironmentRoute)
        route = self.environment
        if (route.member.role is not EnvironmentRole.GLOBALS_NAMESPACE
                or route.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING
                or self.callee_owner != route.member.reference):
            raise ValueError("namespace call bridge needs its existing callee globals reference member")
        if self.state_entry.caller_use != route.call_world or self.state_entry.caller_value != route.call_world_value:
            raise ValueError("namespace call bridge world differs from its original call world")
        required = {CrossBodyNamespaceCondition.CALL_SELECTS_ENVIRONMENT_ROUTE,
                    CrossBodyNamespaceCondition.CALL_ENTRY_PRESERVES_NAMESPACE_BINDING}
        owner_body, owner = route.caller, self.caller_owner
        for incoming in self.caller_owner_routes:
            if (incoming.callee != owner_body or incoming.member.reference != owner
                    or incoming.member.role is not EnvironmentRole.GLOBALS_NAMESPACE
                    or incoming.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING):
                raise ValueError("caller globals provenance is not an ordered qualified environment chain")
            owner_body, owner = incoming.creation_body, incoming.source_value
        if owner_body != route.creation_body or owner != route.source_value:
            required.add(CrossBodyNamespaceCondition.CALLER_OWNER_ALIASES_FACTORY_GLOBALS)
        if not required <= set(self.conditions) or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("namespace call bridge must retain target/entry/qualified-owner conditions")


@dataclass(frozen=True, slots=True)
class StaticCrossBodyNamespaceFlow:
    """Ordered conditional reaching binding across any number of call entries.

    The source reference reaches a namespace read under the listed path,
    owner, mapping and effect premises. This is not content equality, a unique
    runtime function instance or an unconditional reaching-definition proof.
    """
    write: StaticQualifiedNamespaceWrite
    read: StaticQualifiedNamespaceRead
    segments: tuple[StaticNamespacePathSegment, ...]
    bridges: tuple[StaticNamespaceCallBridge, ...]
    conditions: tuple[NamespaceFlowCondition, ...]
    qualification: str = "CONDITIONAL_CROSS_BODY_REACHING_NAMESPACE_BINDING"

    def __post_init__(self):
        _exact(self.write, StaticQualifiedNamespaceWrite)
        _exact(self.read, StaticQualifiedNamespaceRead)
        _rows(self.segments, StaticNamespacePathSegment)
        _rows(self.bridges, StaticNamespaceCallBridge)
        _rows(self.conditions, NamespaceFlowCondition)
        if not self.bridges or len(self.segments) != len(self.bridges) + 1:
            raise ValueError("cross-body flow needs one ordered local segment per call boundary plus its final read")
        first, last = self.segments[0], self.segments[-1]
        if (first.body != self.write.body or first.start_kind is not NamespacePathStart.WRITE_NORMAL
                or first.start_operation != self.write.operation or last.body != self.read.body
                or last.query_operation != self.read.operation or last.query_world != self.read.world):
            raise ValueError("cross-body flow endpoints differ from its original first/last segment")
        if any(segment.key != first.key for segment in self.segments):
            raise ValueError("cross-body namespace flow must query the same builtin key value")
        for position, bridge in enumerate(self.bridges):
            before, after = self.segments[position:position + 2]
            route = bridge.environment
            if (before.body != route.caller or before.query_operation != route.call_operation
                    or before.query_owner != bridge.caller_owner or before.query_world != route.call_world
                    or after.body != route.callee or after.start_kind is not NamespacePathStart.ENTRY
                    or after.start_owner != bridge.callee_owner):
                raise ValueError("cross-body namespace bridges are not ordered qualified segment joins")
        required = {NamespaceFlowCondition.PATH_TAKEN, NamespaceFlowCondition.ALL_NORMAL_NAMESPACE_STORES_COMMIT_INPUT,
                    NamespaceFlowCondition.NORMAL_READ_RETURNS_MAPPING_BINDING,
                    NamespaceFlowCondition.INTERVENING_EFFECTS_PRESERVE_BINDING}
        if not required <= set(self.conditions) or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("cross-body flow must retain path/mapping/effect conditions")
        if bool(self.read.prior_lookup_owners) != (NamespaceFlowCondition.PRIOR_LOOKUP_NAMESPACES_MISSING in self.conditions):
            raise ValueError("cross-body flow lost its original read lookup-priority condition")
        if self.qualification != "CONDITIONAL_CROSS_BODY_REACHING_NAMESPACE_BINDING":
            raise ValueError("cross-body namespace flow cannot claim unconditional contents or identity")


@dataclass(frozen=True, slots=True)
class StaticCallSite:
    caller: SourceBodyNamespace
    operation: OperationID
    source: SourceReference
    semantic_call: OperationDefinitionID | None
    callee_use: UseID | None
    callee_value: ValueID | None
    targets: tuple[StaticCallTarget, ...] = ()
    frontiers: tuple[StaticCallFrontier, ...] = ()
    target_set_complete: bool = False
    namespace_flows: tuple[StaticNamespaceFlow, ...] = ()
    function_creations: tuple[StaticFunctionCreationRoute, ...] = ()
    qualified_namespace_flows: tuple[StaticQualifiedNamespaceFlow, ...] = ()
    qualified_function_creations: tuple[StaticQualifiedFunctionCreation, ...] = ()
    cross_body_namespace_flows: tuple[StaticCrossBodyNamespaceFlow, ...] = ()

    def __post_init__(self):
        _exact(self.caller, SourceBodyNamespace)
        _exact(self.operation, OperationID)
        _exact(self.source, SourceReference)
        if self.semantic_call is not None:
            _exact(self.semantic_call, OperationDefinitionID)
        if (self.callee_use is None) != (self.callee_value is None):
            raise ValueError("callee Use/value must be present together")
        if self.callee_use is not None:
            _exact(self.callee_use, UseID)
            _exact(self.callee_value, ValueID)
        _rows(self.targets, StaticCallTarget)
        _rows(self.frontiers, StaticCallFrontier)
        _rows(self.namespace_flows, StaticNamespaceFlow)
        _rows(self.function_creations, StaticFunctionCreationRoute)
        _rows(self.qualified_namespace_flows, StaticQualifiedNamespaceFlow)
        _rows(self.qualified_function_creations, StaticQualifiedFunctionCreation)
        _rows(self.cross_body_namespace_flows, StaticCrossBodyNamespaceFlow)
        for target in self.targets:
            if any(port.actual_body != self.caller or port.operation != self.operation for port in target.arguments):
                raise ValueError("actual port belongs to another original caller")
            if any(route.caller!=self.caller or route.call_operation!=self.operation
                   or route.callee_use!=self.callee_use or route.callee_value!=self.callee_value
                   for route in target.environment_routes):
                raise ValueError("environment route belongs to another original call/callee Use")
        if self.target_set_complete is not False:
            raise ValueError("the initial linker does not prove target-set closure")


@dataclass(frozen=True, slots=True)
class StaticCallShard:
    source_model: ProviderArtifact
    caller: SourceBodyNamespace
    calls: tuple[StaticCallSite, ...]

    def __post_init__(self):
        _exact(self.source_model, ProviderArtifact)
        _exact(self.caller, SourceBodyNamespace)
        _rows(self.calls, StaticCallSite)
        if any(call.caller != self.caller for call in self.calls):
            raise ValueError("one static relation shard must preserve its caller namespace")
        if len({call.operation for call in self.calls}) != len(self.calls):
            raise ValueError("canonical CALL must occur once per caller")


def dumps(shard: StaticCallShard) -> str:
    _exact(shard, StaticCallShard)
    return json.dumps({"schema": "scar.static-calls", "schema_version": 4,
                       "relations": encode(shard)}, sort_keys=True, separators=(",", ":"), allow_nan=False)


def loads(payload: str) -> StaticCallShard:
    document = strict_loads(payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "relations"}
            or document["schema"] != "scar.static-calls" or type(document["schema_version"]) is not int
            or document["schema_version"] not in (1, 2, 3, 4)):
        raise ValueError("unsupported static call relation shard")
    relations = document["relations"]
    if document["schema_version"] in (1, 2, 3):
        # A closed historical wire must not silently carry new relationships.
        relations = copy.deepcopy(relations)
        v4_fields = {"qualified_namespace_flows", "qualified_function_creations", "cross_body_namespace_flows"}
        old_fields = set(StaticCallSite.__dataclass_fields__) - v4_fields
        if document["schema_version"] == 1:
            old_fields -= {"namespace_flows", "function_creations"}
        old_target_fields = set(StaticCallTarget.__dataclass_fields__)
        if document["schema_version"] < 3:
            old_target_fields -= {"environment_routes"}
        if type(relations) is not dict or type(relations.get("calls")) is not list:
            raise ValueError("historical call shard is malformed")
        for call in relations["calls"]:
            if type(call) is not dict or set(call) != old_fields:
                raise ValueError("historical call record cannot contain newer relationships")
            if document["schema_version"] > 1:
                if type(call['namespace_flows']) is not list:
                    raise ValueError("historical namespace relationships are malformed")
                for flow in call['namespace_flows']:
                    if (type(flow) is not dict or type(flow.get('conditions')) is not list
                            or NamespaceFlowCondition.NAMESPACE_OWNERS_ALIAS.value in flow['conditions']):
                        raise ValueError("historical namespace flow cannot carry v4 owner-alias conditions")
            if type(call['targets']) is not list:
                raise ValueError("historical static call targets are malformed")
            for target in call['targets']:
                if type(target) is not dict or set(target)!=old_target_fields:
                    raise ValueError("historical target has unsupported relationship fields")
                if document["schema_version"] < 3:
                    target['environment_routes']=[]
            if document["schema_version"] == 1:
                call.update(namespace_flows=[], function_creations=[])
            call.update(qualified_namespace_flows=[], qualified_function_creations=[], cross_body_namespace_flows=[])
    return decode(StaticCallShard, relations)


__all__ = ["StaticCallFrontier", "StaticTerminalPort", "StaticCompletionRoute",
           "StaticStateEntryRoute", "NamespaceFlowCondition", "StaticNamespaceFlow",
           "StaticQualifiedNamespaceFlow", "StaticQualifiedFunctionCreation",
           "StaticQualifiedNamespaceWrite", "StaticQualifiedNamespaceRead", "NamespacePathStart",
           "StaticNamespacePathSegment", "CrossBodyNamespaceCondition", "StaticNamespaceCallBridge",
           "StaticCrossBodyNamespaceFlow",
           "FunctionEnvironmentRouteKind", "FunctionEnvironmentCondition", "StaticFunctionEnvironmentRoute",
           "StaticFunctionCreationRoute", "StaticCallTarget", "StaticCallSite", "StaticCallShard", "dumps", "loads"]

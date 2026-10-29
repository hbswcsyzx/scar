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
    return json.dumps({"schema": "scar.static-calls", "schema_version": 3,
                       "relations": encode(shard)}, sort_keys=True, separators=(",", ":"), allow_nan=False)


def loads(payload: str) -> StaticCallShard:
    document = strict_loads(payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "relations"}
            or document["schema"] != "scar.static-calls" or type(document["schema_version"]) is not int
            or document["schema_version"] not in (1, 2, 3)):
        raise ValueError("unsupported static call relation shard")
    relations = document["relations"]
    if document["schema_version"] in (1, 2):
        # A closed historical wire must not silently carry new relationships.
        relations = copy.deepcopy(relations)
        old_fields = set(StaticCallSite.__dataclass_fields__)
        if document["schema_version"] == 1:
            old_fields -= {"namespace_flows", "function_creations"}
        old_target_fields = set(StaticCallTarget.__dataclass_fields__) - {"environment_routes"}
        if type(relations) is not dict or type(relations.get("calls")) is not list:
            raise ValueError("historical call shard is malformed")
        for call in relations["calls"]:
            if type(call) is not dict or set(call) != old_fields:
                raise ValueError("historical call record cannot contain newer relationships")
            if type(call['targets']) is not list:
                raise ValueError("historical static call targets are malformed")
            for target in call['targets']:
                if type(target) is not dict or set(target)!=old_target_fields:
                    raise ValueError("historical target cannot contain v3 environment relationships")
                target['environment_routes']=[]
            if document["schema_version"] == 1:
                call.update(namespace_flows=[], function_creations=[])
    return decode(StaticCallShard, relations)


__all__ = ["StaticCallFrontier", "StaticTerminalPort", "StaticCompletionRoute",
           "StaticStateEntryRoute", "NamespaceFlowCondition", "StaticNamespaceFlow",
           "FunctionEnvironmentRouteKind", "FunctionEnvironmentCondition", "StaticFunctionEnvironmentRoute",
           "StaticFunctionCreationRoute", "StaticCallTarget", "StaticCallSite", "StaticCallShard", "dumps", "loads"]

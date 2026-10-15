"""Function interfaces and conditional source binding plans, never live proofs."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import RegionID, UseID, ValueID
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


class ParameterKind(str, Enum):
    POSITIONAL_ONLY = "POSITIONAL_ONLY"
    POSITIONAL = "POSITIONAL"
    VAR_POSITIONAL = "VAR_POSITIONAL"
    KEYWORD_ONLY = "KEYWORD_ONLY"
    VAR_KEYWORD = "VAR_KEYWORD"


class BodyLoweringProfile(str, Enum):
    LEGACY = "LEGACY"
    BOUND_FORMALS = "BOUND_FORMALS_V1"


class FunctionKind(str, Enum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"
    GENERATOR = "GENERATOR"
    ASYNC_GENERATOR = "ASYNC_GENERATOR"


@dataclass(frozen=True, slots=True)
class FormalParameter:
    name: str
    kind: ParameterKind
    slot: ValueSlotID
    source: SourceReference
    default_source: SourceReference | None = None

    def __post_init__(self):
        if type(self.name) is not str or not self.name:
            raise ValueError("formal parameter needs a name")
        if self.kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD) and self.default_source:
            raise ValueError("variadic parameters cannot have declaration defaults")


@dataclass(frozen=True, slots=True)
class FunctionSignature:
    definition: OperationDefinitionID
    source: SourceReference
    parameters: tuple[FormalParameter, ...]
    kind: FunctionKind = FunctionKind.SYNC
    decorators: tuple[SourceReference, ...] = ()

    def __post_init__(self):
        if len({p.name for p in self.parameters}) != len(self.parameters) or len({p.slot for p in self.parameters}) != len(self.parameters):
            raise ValueError("function parameters need unique names and slots")
        order = {kind:index for index,kind in enumerate(ParameterKind)}
        ranks = [order[p.kind] for p in self.parameters]
        if ranks != sorted(ranks):
            raise ValueError("formal parameter kinds are not in canonical order")
        for kind in (ParameterKind.VAR_POSITIONAL, ParameterKind.VAR_KEYWORD):
            if sum(p.kind is kind for p in self.parameters) > 1:
                raise ValueError("duplicate variadic parameter")
        default_seen = False
        for parameter in self.parameters:
            if parameter.kind in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL):
                if default_seen and parameter.default_source is None:
                    raise ValueError("positional defaults must be trailing")
                default_seen |= parameter.default_source is not None


@dataclass(frozen=True, slots=True)
class FormalPort:
    slot: ValueSlotID
    value: ValueID


@dataclass(frozen=True, slots=True)
class BodyEntryInterface:
    definition: OperationDefinitionID
    region: RegionID
    parameters: tuple[FormalPort, ...]
    world: ValueID
    profile: BodyLoweringProfile = BodyLoweringProfile.BOUND_FORMALS

    def __post_init__(self):
        if self.profile is not BodyLoweringProfile.BOUND_FORMALS:
            raise ValueError("bound entry needs the bound-formal profile")
        if len({p.slot for p in self.parameters}) != len(self.parameters) or len({p.value for p in self.parameters}) != len(self.parameters):
            raise ValueError("body formal ports must be unique")
        if self.world in {p.value for p in self.parameters}:
            raise ValueError("world is not a Python formal")


class ArgumentKind(str, Enum):
    POSITIONAL = "POSITIONAL"
    KEYWORD = "KEYWORD"
    STARRED = "STARRED"
    DOUBLE_STARRED = "DOUBLE_STARRED"


@dataclass(frozen=True, slots=True)
class CallArgument:
    index: int
    source: SourceReference
    kind: ArgumentKind
    keyword: str | None = None
    use: UseID | None = None

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0:
            raise ValueError("argument index must be nonnegative")
        if (self.kind is ArgumentKind.KEYWORD and (type(self.keyword) is not str or not self.keyword)
                or self.kind is not ArgumentKind.KEYWORD and self.keyword is not None):
            raise ValueError("only explicit keyword arguments need keyword names")


class BindingOrigin(str, Enum):
    ARGUMENT = "ARGUMENT"
    DEFAULT_STATE = "DEFAULT_STATE"
    VAR_POSITIONAL_PACK = "VAR_POSITIONAL_PACK"
    VAR_KEYWORD_PACK = "VAR_KEYWORD_PACK"


@dataclass(frozen=True, slots=True)
class ParameterBinding:
    slot: ValueSlotID
    origin: BindingOrigin
    argument_indices: tuple[int, ...] = ()
    default_source: SourceReference | None = None

    def __post_init__(self):
        if any(type(i) is not int or i < 0 for i in self.argument_indices) or len(set(self.argument_indices)) != len(self.argument_indices):
            raise ValueError("binding arguments must be distinct nonnegative indices")
        if self.origin is BindingOrigin.ARGUMENT and len(self.argument_indices) != 1:
            raise ValueError("an explicit parameter needs one actual")
        if (self.origin is BindingOrigin.DEFAULT_STATE) != (self.default_source is not None):
            raise ValueError("only default-state routes carry a declaration source")
        if self.origin is BindingOrigin.DEFAULT_STATE and self.argument_indices:
            raise ValueError("default-state route cannot consume an actual")


class CallBindingStatus(str, Enum):
    CONDITIONAL = "CONDITIONAL"
    INCOMPLETE = "INCOMPLETE"
    INCOMPATIBLE = "INCOMPATIBLE"


class BindingIssueKind(str, Enum):
    EXPANDED_ARGUMENT = "EXPANDED_ARGUMENT"
    DECORATED_TARGET = "DECORATED_TARGET"
    SUSPENDED_BODY = "SUSPENDED_BODY"
    NO_SIGNATURE = "NO_SIGNATURE"
    TOO_MANY_POSITIONAL = "TOO_MANY_POSITIONAL"
    DUPLICATE_ARGUMENT = "DUPLICATE_ARGUMENT"
    POSITIONAL_ONLY_KEYWORD = "POSITIONAL_ONLY_KEYWORD"
    UNEXPECTED_KEYWORD = "UNEXPECTED_KEYWORD"
    MISSING_REQUIRED = "MISSING_REQUIRED"


@dataclass(frozen=True, slots=True)
class BindingIssue:
    kind: BindingIssueKind
    detail: str
    slot: ValueSlotID | None = None
    argument_indices: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.detail) is not str or not self.detail:
            raise ValueError("binding issue needs a detail")


class BindingCondition(str, Enum):
    RAW_FUNCTION_TARGET_MATCHES_SIGNATURE = "RAW_FUNCTION_TARGET_MATCHES_SIGNATURE"
    CODE_VERSION_MATCHES_SOURCE = "CODE_VERSION_MATCHES_SOURCE"
    FUNCTION_DEFAULT_STATE_MATCHES_SOURCE_DECLARATION = "FUNCTION_DEFAULT_STATE_MATCHES_SOURCE_DECLARATION"
    ARGUMENT_EVALUATION_AND_EXPANSION_COMPLETED = "ARGUMENT_EVALUATION_AND_EXPANSION_COMPLETED"
    PACKING_AND_BINDING_EFFECTS_PRESERVED = "PACKING_AND_BINDING_EFFECTS_PRESERVED"
    CALL_STATE_AND_FRAME_MAPPING_PRESERVED = "CALL_STATE_AND_FRAME_MAPPING_PRESERVED"


@dataclass(frozen=True, slots=True)
class CandidateBinding:
    call: OperationDefinitionID
    target: OperationDefinitionID
    source: SourceReference
    status: CallBindingStatus
    arguments: tuple[CallArgument, ...]
    routes: tuple[ParameterBinding, ...] = ()
    issues: tuple[BindingIssue, ...] = ()
    conditions: tuple[BindingCondition, ...] = tuple(BindingCondition)

    def __post_init__(self):
        if self.conditions != tuple(BindingCondition):
            raise ValueError("all source candidate binding requirements must remain explicit")
        if tuple(a.index for a in self.arguments) != tuple(range(len(self.arguments))):
            raise ValueError("call argument indices must be contiguous and ordered")
        if self.status is not CallBindingStatus.CONDITIONAL and (self.routes or not self.issues):
            raise ValueError("incomplete/incompatible bindings need issues and no formal routes")
        if self.status is CallBindingStatus.CONDITIONAL:
            if self.issues or len({r.slot for r in self.routes}) != len(self.routes):
                raise ValueError("conditional bindings require unique complete routes without issues")
            consumed = [i for route in self.routes for i in route.argument_indices]
            if sorted(consumed) != list(range(len(self.arguments))):
                raise ValueError("a conditional binding must consume each actual exactly once")


@dataclass(frozen=True, slots=True)
class FunctionInterfaceIssue:
    source: SourceReference
    detail: str


@dataclass(frozen=True, slots=True)
class FunctionInterfaces:
    signatures: tuple[FunctionSignature, ...]
    bodies: tuple[BodyEntryInterface, ...]
    bindings: tuple[CandidateBinding, ...]
    issues: tuple[FunctionInterfaceIssue, ...] = ()
    profile: BodyLoweringProfile = BodyLoweringProfile.BOUND_FORMALS

    def __post_init__(self):
        if self.profile is not BodyLoweringProfile.BOUND_FORMALS:
            raise ValueError("function interfaces need a bound-formal profile")
        if len({s.definition for s in self.signatures}) != len(self.signatures):
            raise ValueError("duplicate function signature")
        if len({b.definition for b in self.bodies}) != len(self.bodies):
            raise ValueError("duplicate body interface")
        if len({(b.call,b.target) for b in self.bindings}) != len(self.bindings):
            raise ValueError("duplicate source candidate binding")
        signatures = {s.definition:s for s in self.signatures}
        for body in self.bodies:
            if body.definition not in signatures or tuple(p.slot for p in body.parameters) != tuple(p.slot for p in signatures[body.definition].parameters):
                raise ValueError("body interface must cover the complete signature in order")
        for binding in self.bindings:
            if binding.status is CallBindingStatus.CONDITIONAL:
                signature = signatures.get(binding.target)
                if signature is None or tuple(r.slot for r in binding.routes) != tuple(p.slot for p in signature.parameters):
                    raise ValueError("conditional binding must cover every formal in order")

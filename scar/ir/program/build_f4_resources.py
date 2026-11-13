"""F4 resource declarations and snapshot references, never actual placement."""
from dataclasses import dataclass
from enum import Enum

from .dependencies import DependencyPoint
from .ids import OperationID
from .providers import ProviderFactReference
from .normal_targets import GlobalPort
from .python_bindings import NativeSchemaReference
from .native_resource_declarations import DeclaredDispatchCandidate
from .resources import ResourceDefinition
from .source_effects import FamilyRule
from .source_resource_graph import NativeResourceValue
from .target_hardware import TargetResourceRef


class F4ResourceApplicability(str, Enum):
    NOT_APPLICABLE = 'NOT_APPLICABLE'
    COMPOSITE = 'COMPOSITE'
    DECLARATION_ONLY = 'DECLARATION_ONLY'
    HOST = 'HOST'
    HOST_INTERFACE_OPEN = 'HOST_INTERFACE_OPEN'
    EXTERNAL_INTERFACE_OPEN = 'EXTERNAL_INTERFACE_OPEN'


@dataclass(frozen=True, slots=True)
class F4ResourceInterface:
    operation: DependencyPoint
    rule: FamilyRule
    reference_ports: tuple[DependencyPoint, ...]
    world_ports: tuple[DependencyPoint, ...]
    structural_or_compile_only: bool
    applicability: F4ResourceApplicability
    reason: str

    def __post_init__(self):
        structural = self.applicability in (F4ResourceApplicability.NOT_APPLICABLE,
            F4ResourceApplicability.COMPOSITE, F4ResourceApplicability.DECLARATION_ONLY)
        if (type(self.applicability) is not F4ResourceApplicability or not self.reason
                or self.structural_or_compile_only is not structural):
            raise ValueError('resource applicability must distinguish local demands from composition')


@dataclass(frozen=True, slots=True)
class F4TargetResource:
    definition: ResourceDefinition
    target: TargetResourceRef


@dataclass(frozen=True, slots=True)
class F4ResourceRoute:
    operation: DependencyPoint
    endpoints: tuple[DependencyPoint, ...]
    normalization: ProviderFactReference
    source_route: ProviderFactReference
    value: NativeResourceValue
    target: TargetResourceRef
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class F4NativeExecutorRoute:
    operation: DependencyPoint
    source_call: GlobalPort
    source_match: ProviderFactReference
    declaration: ProviderFactReference
    normalization: ProviderFactReference
    schema: NativeSchemaReference
    executor_option: ProviderFactReference
    dispatch: tuple[DeclaredDispatchCandidate, ...]
    dispatch_evidence: tuple[ProviderFactReference, ...]
    target: TargetResourceRef
    conditions: tuple[str, ...]

    def __post_init__(self):
        if (type(self.operation.node) is not OperationID
                or len(self.dispatch) != len(self.dispatch_evidence)
                or any(row.boundary != self.schema.boundary for row in self.dispatch)):
            raise ValueError('native executor route must retain its original operation/schema/dispatch')

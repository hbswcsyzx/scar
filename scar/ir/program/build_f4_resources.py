"""F4 resource declarations and snapshot references, never actual placement."""
from dataclasses import dataclass

from .dependencies import DependencyPoint
from .ids import OperationID
from .providers import ProviderFactReference
from .resources import ResourceDefinition
from .source_effects import FamilyRule
from .source_resource_graph import NativeResourceValue
from .target_hardware import TargetResourceRef


@dataclass(frozen=True, slots=True)
class F4ResourceInterface:
    operation: DependencyPoint
    rule: FamilyRule
    reference_ports: tuple[DependencyPoint, ...]
    world_ports: tuple[DependencyPoint, ...]
    structural_or_compile_only: bool


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

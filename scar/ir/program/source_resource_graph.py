"""Type-level software/resource constraints, distinct from physical use."""
from dataclasses import dataclass
from enum import Enum

from .ids import NativeBoundaryID
from .native import EntryPortRef, ExitPortRef
from .native_resource_declarations import TypeProjection
from .providers import ProviderFactReference
from .target_hardware import TargetResourceRef, ResourceCandidateKind


class ResourceValueRole(str, Enum):
    TENSOR = 'TENSOR'
    DEVICE = 'DEVICE'
    GENERATOR = 'GENERATOR'


class ResourceValueDirection(str, Enum):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'


@dataclass(frozen=True, slots=True)
class NativeResourceValue:
    boundary: NativeBoundaryID
    port: EntryPortRef | ExitPortRef
    direction: ResourceValueDirection
    role: ResourceValueRole
    schema_type: str
    type_path: tuple[TypeProjection, ...]
    evidence: ProviderFactReference


@dataclass(frozen=True, slots=True)
class ResourceTargetOption:
    value: int
    target: TargetResourceRef
    relation: ResourceCandidateKind
    conditions: tuple[str, ...]
    selected: bool = False


@dataclass(frozen=True, slots=True)
class SourceResourceRoute:
    normalization: ProviderFactReference
    value: int
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceUnitHostOption:
    unit: str
    source: ProviderFactReference
    target: TargetResourceRef
    conditions: tuple[str, ...] = (
        'SOURCE_SCOPE_ENTERED', 'HOST_CPU_AFFINITY_AND_NUMA_POLICY_PERMIT_EXECUTION',
        'SOURCE_UNIT_DECLARATION_NOT_RUNTIME_CPU_OR_THREAD_SELECTION',
    )
    selected: bool = False


@dataclass(frozen=True, slots=True)
class NativeExecutorOption:
    boundary: NativeBoundaryID
    target: TargetResourceRef
    declared_dispatch: tuple[int, ...]
    conditions: tuple[str, ...] = (
        'NATIVE_RUNTIME_DISPATCH_AND_IMPLEMENTATION_DEVICE_MATCH_EXECUTOR',
        'TARGET_COMPUTE_ACCESS_AND_EXECUTION_POLICY_PERMIT',
        'DECLARED_DISPATCH_IS_NOT_EXHAUSTIVE_CURRENT_KERNEL_REGISTRY',
    )
    selected: bool = False

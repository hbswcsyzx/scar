"""Typed target descriptions, separate from program requirements and actual use.

Inventory IDs are scoped by their target snapshot. Capacities are reported
totals; budgets and measured link performance remain unknown unless supplied.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.v2.ids import Identifier
from .providers import ProviderArtifact,ProviderFactReference


class TargetResourceID(Identifier):
    prefix='target_resource'


@dataclass(frozen=True,slots=True)
class CpuExecutor:
    id: TargetResourceID
    numa_node: int | None
    cpu_ids: tuple[int,...]
    physical_cores: int | None
    model_names: tuple[str,...]
    evidence: ProviderFactReference


class MemoryKind(str,Enum):
    HOST='HOST'
    DEVICE='DEVICE'


@dataclass(frozen=True,slots=True)
class MemoryDomain:
    id: TargetResourceID
    kind: MemoryKind
    owner: TargetResourceID | None
    numa_node: int | None
    capacity_bytes: int | None
    technology: str | None
    budget_bytes: int | None
    evidence: ProviderFactReference


@dataclass(frozen=True,slots=True)
class Accelerator:
    id: TargetResourceID
    family: str
    name: str
    uuid: str
    inventory_index: int
    pci_bus_id: str
    numa_node: int | None
    compute_capability: str | None
    evidence: ProviderFactReference


@dataclass(frozen=True,slots=True)
class StorageDevice:
    id: TargetResourceID
    kernel_name: str
    capacity_bytes: int | None
    transport: str | None
    media_kind: str | None
    evidence: ProviderFactReference


@dataclass(frozen=True,slots=True)
class StorageEndpoint:
    id: TargetResourceID
    mount_point: str
    source: str
    filesystem: str
    volume_bytes: int | None
    evidence: ProviderFactReference


TargetResource=CpuExecutor|MemoryDomain|Accelerator|StorageDevice|StorageEndpoint
TARGET_RECORD_TAGS={cls:('resource_type',cls.__name__) for cls in
    (CpuExecutor,MemoryDomain,Accelerator,StorageDevice,StorageEndpoint)}


class ConnectionKind(str,Enum):
    MEMORY_ATTACHED='MEMORY_ATTACHED'
    MEMORY_ACCESS='MEMORY_ACCESS'
    HOST_DEVICE_LINK='HOST_DEVICE_LINK'
    STORAGE_BACKING='STORAGE_BACKING'
    STORAGE_ACCESS='STORAGE_ACCESS'


@dataclass(frozen=True,slots=True)
class ResourceConnection:
    source: TargetResourceID
    target: TargetResourceID
    kind: ConnectionKind
    locality: str | None
    bandwidth_bytes_per_second: float | None
    latency_seconds: float | None
    advertised_link_speed: str | None
    advertised_link_width: int | None
    evidence: ProviderFactReference
    conditions: tuple[str,...]=()
    bidirectional: bool=False


@dataclass(frozen=True,slots=True)
class PathEndpoint:
    requested_path: str
    resolved_path: str
    endpoint: TargetResourceID | None
    backing_status: str
    evidence: ProviderFactReference


@dataclass(frozen=True,slots=True)
class TargetResourceRef:
    snapshot: ProviderArtifact
    resource: TargetResourceID


class ResourceCandidateKind(str,Enum):
    TENSOR_STORAGE_POOL='TENSOR_STORAGE_POOL'
    DEVICE_REFERENT='DEVICE_REFERENT'
    GENERATOR_DEVICE='GENERATOR_DEVICE'

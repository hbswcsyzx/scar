"""Resource occurrence records over canonical identities and state references.

These immutable declarations do not certify identity, permissions, availability,
or readiness. No constructor reads artifacts, retains runtime objects, or owns
another resource-state/producer graph. Cross-record facts belong to validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import TypeAlias

from scar.ir.program.ids import ResourceDefinitionID, ResourceRequirementID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole, _require_kind_role
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import ObjectID, StorageAllocationID
from .common import EvidencePoint, FactSource, MissingEvidence, Unresolved
from .coordinates import ExecutionPoint, OccurrencePoint, UseRef
from .ids import (
    ExternalRealmID, HandleBindingID, HostThreadInstanceID, NativeHandleLifetimeID,
    OperationOccurrenceID, ProcessInstanceID, RealizationID, RegionActivationID,
    ResourceAccessID, ResourceBindingID, ResourceInstanceID, RunID, ValueOccurrenceID,
    ProviderResourceAccessID, WorkTicketID,
)


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _id(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()
    if type(value.value) is not str or not value.value:
        raise ValueError(f"{name} must contain a nonempty exact string")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _variant(value, expected, name):
    if type(value) not in expected:
        raise TypeError(f"{name} must be a typed variant")
    value.__post_init__()


def _records(value, expected, name):
    _exact(value, tuple, name)
    for item in value:
        _record(item, expected, name + " item")


def _support(value, name="state support"):
    _exact(value, tuple, name)
    for item in value:
        _id(item, ValueOccurrenceID, name + " occurrence")


def _source(value, name="resource source"):
    _variant(value, (ProviderFactReference, MissingEvidence), name)


def _point(value, name="execution point"):
    _variant(value, (OccurrencePoint, EvidencePoint), name)


def _index(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True, slots=True)
class RunRealm:
    run: RunID

    def __post_init__(self):
        _id(self.run, RunID, "run realm")


@dataclass(frozen=True, slots=True)
class ProcessRealm:
    process: ProcessInstanceID

    def __post_init__(self):
        _id(self.process, ProcessInstanceID, "process realm")


@dataclass(frozen=True, slots=True)
class ExternalRealm:
    id: ExternalRealmID
    namespace: ProviderFactReference

    def __post_init__(self):
        _id(self.id, ExternalRealmID, "external realm ID")
        _record(self.namespace, ProviderFactReference, "external realm namespace")


IdentityRealm: TypeAlias = RunRealm | ProcessRealm | ExternalRealm


@dataclass(frozen=True, slots=True)
class InstanceTarget:
    instance: ResourceInstanceID

    def __post_init__(self):
        _id(self.instance, ResourceInstanceID, "resource instance target")


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    artifact: ProviderArtifact
    allocation: StorageAllocationID

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "allocation target artifact")
        _id(self.allocation, StorageAllocationID, "allocation target ID")


@dataclass(frozen=True, slots=True)
class ProcessTarget:
    process: ProcessInstanceID

    def __post_init__(self):
        _id(self.process, ProcessInstanceID, "process resource target")


@dataclass(frozen=True, slots=True)
class ThreadTarget:
    thread: HostThreadInstanceID

    def __post_init__(self):
        _id(self.thread, HostThreadInstanceID, "thread resource target")


ResourceTarget: TypeAlias = InstanceTarget | AllocationTarget | ProcessTarget | ThreadTarget


def _target(value, name="resource target"):
    _variant(value, (InstanceTarget, AllocationTarget, ProcessTarget, ThreadTarget), name)


def _realm(value):
    _variant(value, (RunRealm, ProcessRealm, ExternalRealm), "identity realm")


@dataclass(frozen=True, slots=True)
class CreatedAt:
    operation: OperationOccurrenceID

    def __post_init__(self):
        _id(self.operation, OperationOccurrenceID, "resource creation occurrence")


@dataclass(frozen=True, slots=True)
class ImportedAt:
    point: ExecutionPoint

    def __post_init__(self):
        _point(self.point, "resource import point")


ResourceOrigin: TypeAlias = CreatedAt | ImportedAt | Unresolved


@dataclass(frozen=True, slots=True)
class ResourceInstance:
    """One resource lifetime, distinct from its changing state and observations."""

    id: ResourceInstanceID
    kind: ResourceKind
    role: ResourceRole
    realm: IdentityRealm
    origin: ResourceOrigin
    source: FactSource

    def __post_init__(self):
        _id(self.id, ResourceInstanceID, "resource instance ID")
        _exact(self.kind, ResourceKind, "resource kind")
        _exact(self.role, ResourceRole, "resource role")
        _require_kind_role(self.kind, self.role)
        _realm(self.realm)
        _variant(self.origin, (CreatedAt, ImportedAt, Unresolved), "resource origin")
        _source(self.source)


def _owner(value, name):
    if type(value) is OperationOccurrenceID:
        _id(value, OperationOccurrenceID, name)
    elif type(value) is RegionActivationID:
        _id(value, RegionActivationID, name)
    else:
        raise TypeError(f"{name} must be an operation occurrence or region activation")


@dataclass(frozen=True, slots=True)
class ResourceRealization:
    id: RealizationID
    definition: ResourceDefinitionID
    site: OperationOccurrenceID | RegionActivationID
    target: ResourceTarget
    source: FactSource

    def __post_init__(self):
        _id(self.id, RealizationID, "resource realization ID")
        _id(self.definition, ResourceDefinitionID, "resource definition")
        _owner(self.site, "resource realization site")
        _target(self.target)
        _source(self.source)


@dataclass(frozen=True, slots=True)
class RequirementBinding:
    id: ResourceBindingID
    requirement: ResourceRequirementID
    owner: OperationOccurrenceID | RegionActivationID
    target: ResourceTarget
    source: FactSource

    def __post_init__(self):
        _id(self.id, ResourceBindingID, "resource binding ID")
        _id(self.requirement, ResourceRequirementID, "resource requirement")
        _owner(self.owner, "resource binding owner")
        _target(self.target)
        _source(self.source)


@dataclass(frozen=True, slots=True)
class HandleNamespace:
    realm: IdentityRealm
    protocol: ProviderFactReference

    def __post_init__(self):
        _realm(self.realm)
        _record(self.protocol, ProviderFactReference, "handle namespace protocol")


@dataclass(frozen=True, slots=True)
class ObjectHandle:
    value: ValueOccurrenceID
    artifact: ProviderArtifact
    object: ObjectID
    source: FactSource

    def __post_init__(self):
        _id(self.value, ValueOccurrenceID, "object handle value")
        _record(self.artifact, ProviderArtifact, "object handle artifact")
        _id(self.object, ObjectID, "object handle identity")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class NativeHandle:
    value: ValueOccurrenceID
    namespace: HandleNamespace
    lifetime: NativeHandleLifetimeID
    source: FactSource

    def __post_init__(self):
        _id(self.value, ValueOccurrenceID, "native handle value")
        _record(self.namespace, HandleNamespace, "native handle namespace")
        _id(self.lifetime, NativeHandleLifetimeID, "native handle lifetime")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class ProviderRecordSelector:
    """A manifest chunk reference plus actual JSONL line and line-local pointer.

    The chunk locator addresses ordinary manifest JSON. Line/ordinal address
    the referenced JSONL provider; they are never a fictional JSON array.
    Resolution requires an explicit bound provider reader, never URI opening.
    """
    chunk: ProviderFactReference
    table: str
    ordinal: int
    line: int
    pointer_within_line: str

    def __post_init__(self):
        _record(self.chunk, ProviderFactReference, "selector manifest chunk")
        _exact(self.table, str, "selector table")
        if re.fullmatch(r"[a-z][a-z0-9_]*", self.table) is None:
            raise ValueError("selector table must be an explicit table name")
        if re.fullmatch(r"#/tables/" + re.escape(self.table) + r"/chunks/(0|[1-9][0-9]*)", self.chunk.locator) is None:
            raise ValueError("selector chunk must address its real manifest table member")
        _index(self.ordinal, "selector ordinal")
        _index(self.line, "selector line")
        if self.line == 0:
            raise ValueError("selector JSONL line must be one-based")
        _exact(self.pointer_within_line, str, "line-local pointer")
        pointer = self.pointer_within_line
        if not (pointer == "/record" or pointer.startswith("/record/")) or re.search(r"~(?![01])", pointer):
            raise ValueError("selector requires a valid pointer inside the actual record envelope")


@dataclass(frozen=True, slots=True)
class ProviderHandle:
    namespace: HandleNamespace
    container: InstanceTarget | Unresolved
    selector: ProviderRecordSelector
    lifetime: NativeHandleLifetimeID
    source: FactSource

    def __post_init__(self):
        _record(self.namespace, HandleNamespace, "provider handle namespace")
        _variant(self.container, (InstanceTarget, Unresolved), "provider handle table container")
        _record(self.selector, ProviderRecordSelector, "provider handle selector")
        _id(self.lifetime, NativeHandleLifetimeID, "provider handle lifetime")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class UnresolvedHandle:
    value: ValueOccurrenceID | None
    gap: Unresolved

    def __post_init__(self):
        if self.value is not None:
            _id(self.value, ValueOccurrenceID, "unresolved handle value")
        _record(self.gap, Unresolved, "unresolved handle gap")


HandleEndpoint: TypeAlias = ObjectHandle | NativeHandle | ProviderHandle | UnresolvedHandle


@dataclass(frozen=True, slots=True)
class ProtocolRight:
    protocol: ProviderFactReference
    member: ProviderFactReference

    def __post_init__(self):
        _record(self.protocol, ProviderFactReference, "right protocol")
        _record(self.member, ProviderFactReference, "right member")


@dataclass(frozen=True, slots=True)
class RightsClaim:
    members: tuple[ProtocolRight, ...]
    completeness: Completeness
    support: tuple[ValueOccurrenceID, ...]
    source: FactSource

    def __post_init__(self):
        _records(self.members, ProtocolRight, "rights members")
        _exact(self.completeness, Completeness, "rights completeness")
        _support(self.support)
        _source(self.source)


@dataclass(frozen=True, slots=True)
class ObjectHolder:
    artifact: ProviderArtifact
    object: ObjectID

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "object holder artifact")
        _id(self.object, ObjectID, "object holder identity")


@dataclass(frozen=True, slots=True)
class HandleHolder:
    lifetime: NativeHandleLifetimeID

    def __post_init__(self):
        _id(self.lifetime, NativeHandleLifetimeID, "handle holder lifetime")


@dataclass(frozen=True, slots=True)
class ActivationHolder:
    activation: RegionActivationID

    def __post_init__(self):
        _id(self.activation, RegionActivationID, "activation holder")


@dataclass(frozen=True, slots=True)
class TargetHolder:
    target: ResourceTarget

    def __post_init__(self):
        _target(self.target, "ownership holder target")


OwnershipHolder: TypeAlias = ObjectHolder | HandleHolder | ActivationHolder | TargetHolder


class ReleaseAuthority(str, Enum):
    OWNED = "OWNED"
    BORROWED = "BORROWED"
    UNKNOWN = "UNKNOWN"


class Sharing(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OwnershipClaim:
    holder: OwnershipHolder
    authority: ReleaseAuthority
    sharing: Sharing
    support: tuple[ValueOccurrenceID, ...]
    source: FactSource

    def __post_init__(self):
        _variant(self.holder, (ObjectHolder, HandleHolder, ActivationHolder, TargetHolder), "ownership holder")
        _exact(self.authority, ReleaseAuthority, "release authority")
        _exact(self.sharing, Sharing, "ownership sharing")
        _support(self.support)
        _source(self.source)


@dataclass(frozen=True, slots=True)
class EndedAt:
    point: ExecutionPoint
    source: FactSource

    def __post_init__(self):
        _point(self.point, "handle end point")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class HandleBinding:
    id: HandleBindingID
    handle: HandleEndpoint
    target: ResourceTarget
    start: ExecutionPoint
    end: EndedAt | Unresolved
    support: tuple[ValueOccurrenceID, ...]
    rights: RightsClaim | Unresolved
    ownership: tuple[OwnershipClaim, ...] | Unresolved
    source: FactSource

    def __post_init__(self):
        _id(self.id, HandleBindingID, "handle binding ID")
        _variant(self.handle, (ObjectHandle, NativeHandle, ProviderHandle, UnresolvedHandle), "handle endpoint")
        _target(self.target)
        _point(self.start, "handle start point")
        _variant(self.end, (EndedAt, Unresolved), "handle end")
        _support(self.support)
        _variant(self.rights, (RightsClaim, Unresolved), "handle rights")
        if type(self.ownership) is Unresolved:
            _record(self.ownership, Unresolved, "handle ownership")
        else:
            _records(self.ownership, OwnershipClaim, "handle ownership")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class ExplicitHandle:
    binding: HandleBindingID

    def __post_init__(self):
        _id(self.binding, HandleBindingID, "explicit handle binding")


@dataclass(frozen=True, slots=True)
class ImplicitBinding:
    rule: ProviderFactReference
    support: tuple[ValueOccurrenceID, ...]

    def __post_init__(self):
        _record(self.rule, ProviderFactReference, "implicit binding rule")
        _support(self.support)


@dataclass(frozen=True, slots=True)
class CapacityAt:
    requirement: ResourceRequirementID
    index: int

    def __post_init__(self):
        _id(self.requirement, ResourceRequirementID, "capacity requirement")
        _index(self.index, "capacity index")


@dataclass(frozen=True, slots=True)
class RelationAt:
    requirement: ResourceRequirementID
    index: int
    other: ResourceBindingID

    def __post_init__(self):
        _id(self.requirement, ResourceRequirementID, "relation requirement")
        _index(self.index, "relation index")
        _id(self.other, ResourceBindingID, "related resource binding")


@dataclass(frozen=True, slots=True)
class ProtocolCondition:
    rule: ProviderFactReference
    condition: ProviderFactReference
    uses: tuple[UseRef, ...]

    def __post_init__(self):
        _record(self.rule, ProviderFactReference, "protocol condition rule")
        _record(self.condition, ProviderFactReference, "protocol condition member")
        _records(self.uses, UseRef, "protocol condition uses")


ConstraintRef: TypeAlias = CapacityAt | RelationAt | ProtocolCondition


@dataclass(frozen=True, slots=True)
class ConstraintEvidence:
    constraint: ConstraintRef
    support: tuple[ValueOccurrenceID, ...]
    source: FactSource

    def __post_init__(self):
        _variant(self.constraint, (CapacityAt, RelationAt, ProtocolCondition), "constraint reference")
        _support(self.support)
        _source(self.source)


@dataclass(frozen=True, slots=True)
class ResourceAccessBinding:
    id: ResourceAccessID
    operation: OperationOccurrenceID
    requirement: ResourceBindingID
    handle: ExplicitHandle | ImplicitBinding | Unresolved
    support: tuple[ValueOccurrenceID, ...]
    constraints: tuple[ConstraintEvidence, ...]
    source: FactSource

    def __post_init__(self):
        _id(self.id, ResourceAccessID, "resource access ID")
        _id(self.operation, OperationOccurrenceID, "resource access operation")
        _id(self.requirement, ResourceBindingID, "resource access requirement binding")
        _variant(self.handle, (ExplicitHandle, ImplicitBinding, Unresolved), "resource access handle association")
        _support(self.support)
        _records(self.constraints, ConstraintEvidence, "resource access constraints")
        _source(self.source)


@dataclass(frozen=True, slots=True)
class AllocationPlacement:
    allocation: AllocationTarget
    pool: InstanceTarget
    source: FactSource

    def __post_init__(self):
        _record(self.allocation, AllocationTarget, "placed allocation")
        _record(self.pool, InstanceTarget, "allocation pool")
        _source(self.source)


class ProviderAccessPurpose(str, Enum):
    EXECUTOR = "EXECUTOR"
    INPUT_SELECTOR = "INPUT_SELECTOR"
    OUTPUT_SELECTOR = "OUTPUT_SELECTOR"


@dataclass(frozen=True, slots=True)
class ProviderResourceAccess:
    id: ProviderResourceAccessID
    work: WorkTicketID
    purpose: ProviderAccessPurpose
    target: ResourceTarget
    handle: ExplicitHandle | ImplicitBinding | Unresolved
    point: EvidencePoint
    selector: ProviderRecordSelector
    source: FactSource

    def __post_init__(self):
        _id(self.id, ProviderResourceAccessID, "provider resource access ID")
        _id(self.work, WorkTicketID, "provider resource access work")
        _exact(self.purpose, ProviderAccessPurpose, "provider access purpose")
        _target(self.target)
        _variant(self.handle, (ExplicitHandle, ImplicitBinding, Unresolved), "provider access handle")
        _record(self.point, EvidencePoint, "provider access point")
        _record(self.selector, ProviderRecordSelector, "provider access selector")
        _source(self.source)


__all__ = [
    "RunRealm", "ProcessRealm", "ExternalRealm", "IdentityRealm",
    "InstanceTarget", "AllocationTarget", "ProcessTarget", "ThreadTarget", "ResourceTarget",
    "CreatedAt", "ImportedAt", "ResourceOrigin", "ResourceInstance", "ResourceRealization",
    "RequirementBinding", "HandleNamespace", "ObjectHandle", "NativeHandle", "UnresolvedHandle",
    "HandleEndpoint", "ProviderRecordSelector", "ProviderHandle", "ProviderAccessPurpose", "ProviderResourceAccess",
    "ProtocolRight", "RightsClaim", "ObjectHolder", "HandleHolder",
    "ActivationHolder", "TargetHolder", "OwnershipHolder", "ReleaseAuthority", "Sharing",
    "OwnershipClaim", "EndedAt", "HandleBinding", "ExplicitHandle", "ImplicitBinding",
    "CapacityAt", "RelationAt", "ProtocolCondition", "ConstraintRef", "ConstraintEvidence",
    "ResourceAccessBinding", "AllocationPlacement",
]

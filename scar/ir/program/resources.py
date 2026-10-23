"""Static resource identities and typed requirements for the canonical core.

These records define interfaces, not resource observations. A definition can
have many dynamic instances; an unsatisfied requirement is not an instance.
Resource state is held exclusively by the existing StateLocation/SSA records.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from scar.ir.program.ids import (
    LocationID, OperationID, RegionID, ResourceDefinitionID,
    ResourceRequirementID, UseID,
)
from scar.ir.v2.contracts import ResourceKind


class ResourceRole(str, Enum):
    EXECUTOR = "EXECUTOR"
    QUEUE = "QUEUE"
    MEMORY_POOL = "MEMORY_POOL"
    STORAGE_ENDPOINT = "STORAGE_ENDPOINT"
    FILE_ENTITY = "FILE_ENTITY"
    OPEN_FILE_DESCRIPTION = "OPEN_FILE_DESCRIPTION"
    HANDLE_TABLE = "HANDLE_TABLE"
    OPAQUE_RESOURCE = "OPAQUE_RESOURCE"


def _require_kind_role(kind, role):
    expected = {
        ResourceRole.MEMORY_POOL: ResourceKind.MEMORY,
        ResourceRole.FILE_ENTITY: ResourceKind.FILE,
        ResourceRole.OPEN_FILE_DESCRIPTION: ResourceKind.FILE,
        ResourceRole.HANDLE_TABLE: ResourceKind.OTHER,
    }.get(role)
    if expected is not None and kind is not expected:
        raise ValueError("resource kind is incompatible with its protocol role")


@dataclass(frozen=True, slots=True)
class CreatedResource:
    operation: OperationID

    def __post_init__(self):
        if type(self.operation) is not OperationID:
            raise TypeError("created resource needs a canonical OperationID")


@dataclass(frozen=True, slots=True)
class ExternalResource:
    region: RegionID
    port: str

    def __post_init__(self):
        if type(self.region) is not RegionID:
            raise TypeError("external resource needs an owning RegionID")
        if type(self.port) is not str or not self.port:
            raise ValueError("external resource needs an interface port name")


@dataclass(frozen=True, slots=True)
class ResourceDefinition:
    id: ResourceDefinitionID
    kind: ResourceKind
    role: ResourceRole
    origin: CreatedResource | ExternalResource

    def __post_init__(self):
        if type(self.id) is not ResourceDefinitionID:
            raise TypeError("resource definition needs ResourceDefinitionID")
        if type(self.kind) is not ResourceKind or type(self.role) is not ResourceRole:
            raise TypeError("resource kind and role must be typed")
        if type(self.origin) not in (CreatedResource, ExternalResource):
            raise TypeError("resource needs a typed creation or external origin")
        _require_kind_role(self.kind, self.role)


@dataclass(frozen=True, slots=True)
class CapacityConstraint:
    """A requirement bound; it is not a measurement of available capacity."""

    metric: str
    unit: str
    minimum: float
    maximum: float | None = None

    def __post_init__(self):
        if any(type(value) is not str or not value for value in (self.metric, self.unit)):
            raise ValueError("capacity needs a metric and unit")
        if self.minimum is None:
            raise TypeError("capacity minimum is required")
        for value in (self.minimum, self.maximum):
            if value is not None and (type(value) not in (float, int)
                                      or not math.isfinite(value) or value < 0):
                raise ValueError("capacity bounds must be finite nonnegative numbers")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("capacity maximum must not precede minimum")


class RequirementRelation(str, Enum):
    SAME_RESOURCE = "SAME_RESOURCE"
    DISTINCT_RESOURCE = "DISTINCT_RESOURCE"
    CHILD_RESOURCE = "CHILD_RESOURCE"


@dataclass(frozen=True, slots=True)
class ResourceRelationConstraint:
    """A relation within one owner's operation occurrence/region activation.

    Cross-owner occurrence pairing needs an explicit future interface. Static
    IDs from independent calls must not be treated as shared runtime bindings.
    """
    relation: RequirementRelation
    other: ResourceRequirementID

    def __post_init__(self):
        if type(self.relation) is not RequirementRelation:
            raise TypeError("resource relation must be typed")
        if type(self.other) is not ResourceRequirementID:
            raise TypeError("resource constraint references another requirement")


@dataclass(frozen=True, slots=True)
class ResourceRequirement:
    id: ResourceRequirementID
    owner: OperationID | RegionID
    kind: ResourceKind
    role: ResourceRole
    capacities: tuple[CapacityConstraint, ...] = ()
    relations: tuple[ResourceRelationConstraint, ...] = ()

    def __post_init__(self):
        if type(self.id) is not ResourceRequirementID:
            raise TypeError("requirement needs ResourceRequirementID")
        if type(self.owner) not in (OperationID, RegionID):
            raise TypeError("requirement owner must be an operation or region")
        if type(self.kind) is not ResourceKind or type(self.role) is not ResourceRole:
            raise TypeError("requirement kind and role must be typed")
        _require_kind_role(self.kind, self.role)
        for rows, row_type in ((self.capacities, CapacityConstraint),
                               (self.relations, ResourceRelationConstraint)):
            if type(rows) is not tuple or any(type(row) is not row_type for row in rows):
                raise TypeError("requirement constraints must be immutable typed tuples")
        if len({(row.metric, row.unit) for row in self.capacities}) != len(self.capacities):
            raise ValueError("capacity metric/unit constraints must be unique")
        if len(set(self.relations)) != len(self.relations):
            raise ValueError("resource relation constraints must be unique")
        if any(row.other == self.id for row in self.relations):
            raise ValueError("resource requirements cannot constrain themselves")


@dataclass(frozen=True, slots=True)
class ResourceUse:
    operation: OperationID
    requirement: ResourceRequirementID
    definition: ResourceDefinitionID | None = None
    handle: UseID | None = None

    def __post_init__(self):
        if type(self.operation) is not OperationID:
            raise TypeError("resource use needs a canonical OperationID")
        if type(self.requirement) is not ResourceRequirementID:
            raise TypeError("resource use needs a requirement, not an instance")
        if self.definition is not None and type(self.definition) is not ResourceDefinitionID:
            raise TypeError("static resource target must be ResourceDefinitionID")
        if self.handle is not None and type(self.handle) is not UseID:
            raise TypeError("handle must name this operation's ordinary reference Use")


@dataclass(frozen=True, slots=True)
class ResourceLocation:
    """Typed ownership; content/order versions remain canonical graph values."""

    location: LocationID
    resource: ResourceDefinitionID

    def __post_init__(self):
        if type(self.location) is not LocationID or type(self.resource) is not ResourceDefinitionID:
            raise TypeError("resource location requires typed location and resource identities")


__all__ = [
    "CapacityConstraint", "CreatedResource", "ExternalResource", "RequirementRelation",
    "ResourceDefinition", "ResourceKind", "ResourceLocation", "ResourceRelationConstraint",
    "ResourceRequirement", "ResourceRole", "ResourceUse",
]

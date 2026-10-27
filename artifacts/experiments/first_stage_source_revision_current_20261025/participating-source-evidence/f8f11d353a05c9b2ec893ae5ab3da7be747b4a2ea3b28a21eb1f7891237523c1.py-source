"""Descriptor based provenance and materialization validity registry.

No target objects or Tensor values are retained here.  Runtime adapters report
events and contracts; absent mutation coverage never becomes a stability proof.
The event clock is local to one registry scope, not a physical GPU/CPU clock.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from itertools import product
import json
import uuid
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from .v2 import (
    BindingRelation, Completeness, EquivalenceClaim, EvidenceClaim, EvidenceKind,
    LogicalValue, LogicalValueID, Materialization, MaterializationID, ObjectBinding,
    ObjectID, OperationInstanceID, ProofStatus, ProvenanceID, ProvenanceRecord,
    ProvenanceRelation, StorageAllocation, StorageAllocationID, StorageRegion,
    StorageRegionID, ValueGraph, ValueSlotID, ValueVersion, ValueVersionID,
)
from .v2.ids import Identifier
from .v2._validation import record_errors
from .v2.codec import values_from_dict


class GuardState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


class ReadyState(str, Enum):
    READY = "READY"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class Overlap(str, Enum):
    DISJOINT = "DISJOINT"
    OVERLAPS = "OVERLAPS"
    POSSIBLE = "POSSIBLE"


@dataclass(frozen=True)
class EventPoint:
    scope: str
    ordinal: int
    label: str = ""

    def __post_init__(self):
        if not self.scope or type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("event requires a scope and a non-negative integer ordinal")


@dataclass(frozen=True)
class ValueHandle:
    object_id: ObjectID
    version: ValueVersionID
    materialization: MaterializationID


@dataclass(frozen=True)
class MutationCoverage:
    scope: str
    completeness: Completeness = Completeness.UNKNOWN
    observed_writes: tuple[EventPoint, ...] = ()
    foreign_aliases: tuple[str, ...] = ()
    escaped_boundaries: tuple[str, ...] = ()
    evidence: tuple[EvidenceClaim, ...] = ()


@dataclass(frozen=True)
class ExactContract:
    reference: str
    status: ProofStatus
    scope: str
    evidence: EvidenceClaim
    version: str = "1"
    checked_versions: tuple[ValueVersionID, ...] = ()
    checked_at: EventPoint | None = None

    def __post_init__(self):
        if not self.reference or not self.version or not self.scope:
            raise ValueError("exact contract requires reference, version and scope")
        if self.status is ProofStatus.PROVEN and (
            self.evidence.kind in (EvidenceKind.UNKNOWN, EvidenceKind.PROPOSED)
            or not self.evidence.references
        ):
            raise ValueError("PROVEN exact contract requires auditable evidence")
        if self.checked_versions and self.checked_at is None:
            raise ValueError("checked versions require a scoped check event")


@dataclass(frozen=True)
class ValidityRecord:
    materialization: MaterializationID
    version: ValueVersionID
    start_event: EventPoint
    end_event: EventPoint | None
    state: GuardState
    ready: ReadyState
    branch_on_write: bool
    reason: str
    evidence: tuple[EvidenceClaim, ...]


@dataclass(frozen=True)
class BindingInterval:
    slot: ValueSlotID
    handle: ValueHandle
    scope: str
    start_event: EventPoint
    end_event: EventPoint | None
    evidence: EvidenceClaim


@dataclass(frozen=True)
class EqualityEvidence:
    left: ValueHandle
    right: ValueHandle
    relation: EquivalenceClaim
    method: str
    compared_at: EventPoint
    contract: ExactContract
    evidence: EvidenceClaim


@dataclass(frozen=True)
class ObservationAttachment:
    observation_id: str
    handle: ValueHandle
    attached_at: EventPoint
    evidence: EvidenceClaim


@dataclass(frozen=True)
class AllocationLifetime:
    allocation: StorageAllocationID
    witness: str | None
    start_event: EventPoint
    end_event: EventPoint | None = None


@dataclass(frozen=True)
class GuardResult:
    state: GuardState
    checked_versions: tuple[ValueVersionID, ...]
    checked_materializations: tuple[MaterializationID, ...]
    checked_at: EventPoint
    required_facts: tuple[str, ...]
    reason: str
    evidence: tuple[EvidenceClaim, ...] = ()


_WIDTHS = {
    "bool": 1, "uint8": 1, "int8": 1,
    "int16": 2, "uint16": 2, "float16": 2, "bfloat16": 2, "half": 2,
    "int32": 4, "uint32": 4, "float32": 4, "float": 4, "complex32": 4,
    "int64": 8, "uint64": 8, "float64": 8, "double": 8, "complex64": 8,
    "complex128": 16,
}


def _width(region: StorageRegion) -> int | None:
    return _WIDTHS.get(region.dtype.removeprefix("torch.").removeprefix("numpy."))


def _byte_bounds(region: StorageRegion) -> tuple[int, int] | None:
    width = _width(region)
    if width is None or region.layout != "strided":
        return None
    minimum = region.offset + sum(min(0, (size - 1) * stride)
                                  for size, stride in zip(region.shape, region.strides))
    maximum = region.offset + sum(max(0, (size - 1) * stride)
                                  for size, stride in zip(region.shape, region.strides))
    return minimum * width, (maximum + 1) * width


def _byte_intervals(region: StorageRegion, budget: int = 4096):
    width = _width(region)
    if width is None:
        return None
    dimensions = [range(size) if stride else range(1)
                  for size, stride in zip(region.shape, region.strides)]
    count = 1
    for dimension in dimensions:
        count *= len(dimension)
        if count > budget:
            return None
    offsets = sorted({(region.offset + sum(index * stride for index, stride in zip(indices, region.strides))) * width
                      for indices in product(*dimensions)})
    merged = []
    for offset in offsets:
        if merged and offset <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], offset + width))
        else:
            merged.append((offset, offset + width))
    return merged


def region_overlap(left: StorageRegion, right: StorageRegion) -> Overlap:
    """Compare byte-addressed views, conservatively bounding large strided sets."""
    if left.allocation != right.allocation or 0 in left.shape or 0 in right.shape:
        return Overlap.DISJOINT
    a, b = _byte_bounds(left), _byte_bounds(right)
    if a is None or b is None:
        return Overlap.POSSIBLE
    if a[1] <= b[0] or b[1] <= a[0]:
        return Overlap.DISJOINT
    aa, bb = _byte_intervals(left), _byte_intervals(right)
    if aa is None or bb is None:
        return Overlap.POSSIBLE
    i = j = 0
    while i < len(aa) and j < len(bb):
        if aa[i][1] <= bb[j][0]:
            i += 1
        elif bb[j][1] <= aa[i][0]:
            j += 1
        else:
            return Overlap.OVERLAPS
    return Overlap.DISJOINT


class ProvenanceRegistry:
    SCHEMA = "scar.provenance.registry"
    SCHEMA_VERSION = 1

    def __init__(self, scope: str = "run", namespace: str | None = None):
        # Separate captures must not accept each other's coincident handles.
        # An explicit unique namespace supports reproducible controlled replay.
        namespace = namespace if namespace is not None else "registry:" + uuid.uuid4().hex
        if not isinstance(scope, str) or not scope or not isinstance(namespace, str) or not namespace:
            raise ValueError("registry scope and namespace are required")
        self.scope, self.namespace = scope, namespace
        self.graph = ValueGraph()
        self.validity: dict[MaterializationID, ValidityRecord] = {}
        self.coverage: dict[MaterializationID, MutationCoverage] = {}
        self.handles: dict[MaterializationID, ValueHandle] = {}
        self.lifetimes: dict[StorageAllocationID, AllocationLifetime] = {}
        self.bindings: list[BindingInterval] = []
        self.equalities: list[EqualityEvidence] = []
        self.attachments: list[ObservationAttachment] = []
        self._allocation_keys: dict[tuple, StorageAllocationID] = {}
        self._region_keys: dict[tuple, StorageRegionID] = {}
        self._active_materializations: dict[StorageAllocationID, set[MaterializationID]] = {}
        self._latest_versions: dict[LogicalValueID, int] = {}
        self._serial = 0
        self.current_event = EventPoint(scope, 0, "start")

    def _id(self, cls):
        self._serial += 1
        return cls(f"{self.namespace}:{self._serial}")

    def event(self, label: str) -> EventPoint:
        self.current_event = EventPoint(self.scope, self.current_event.ordinal + 1, label)
        return self.current_event

    def _at(self, event: EventPoint | None, label: str) -> EventPoint:
        if event is None:
            return self.event(label)
        if event.scope != self.scope or event.ordinal < self.current_event.ordinal:
            raise ValueError("event must belong to registry scope and cannot move backwards")
        self.current_event = event
        return event

    def _preflight(self, evidence, *, object_id=None, region=None, coverage=None, event=None):
        errors = record_errors(evidence, EvidenceClaim, "evidence")
        if object_id is not None:
            errors.extend(record_errors(object_id, ObjectID, "object_id"))
        if event is not None:
            errors.extend(record_errors(event, EventPoint, "event"))
        if errors:
            raise ValueError("invalid registry request: " + "; ".join(errors))
        if event is not None and (event.scope != self.scope or event.ordinal < self.current_event.ordinal):
            raise ValueError("event must belong to registry scope and cannot move backwards")
        if region is not None:
            if not isinstance(region, StorageRegionID) or region not in self.graph.regions:
                raise ValueError("unknown region")
            allocation = self.graph.regions[region].allocation
            if self.lifetimes[allocation].end_event is not None:
                raise ValueError("region allocation lifetime has ended")
        if coverage is not None:
            self._coverage(coverage, evidence)

    def _check(self, handle: ValueHandle) -> None:
        if not isinstance(handle, ValueHandle) or self.handles.get(handle.materialization) != handle:
            raise ValueError("unknown or inconsistent value handle")

    def _coverage(self, coverage, evidence):
        result = coverage if isinstance(coverage, MutationCoverage) else MutationCoverage(
            self.scope, coverage, evidence=(evidence,))
        errors = record_errors(result, MutationCoverage, "coverage")
        if errors or result.scope != self.scope:
            raise ValueError("invalid mutation coverage: " + "; ".join(errors))
        if result.completeness is Completeness.COMPLETE and not any(
            claim.kind not in (EvidenceKind.UNKNOWN, EvidenceKind.PROPOSED) and claim.references
            for claim in result.evidence
        ):
            raise ValueError("complete mutation coverage requires auditable evidence")
        return result

    def allocation(self, device: str, nbytes: int | None = None,
                   token: str | None = None, lifetime: str | None = None,
                   *, event: EventPoint | None = None) -> StorageAllocationID:
        if not device or (nbytes is not None and (type(nbytes) is not int or nbytes < 0)):
            raise ValueError("allocation requires a device and non-negative integer nbytes")
        if lifetime is not None:
            identity = self._allocation_keys.get((device, token, lifetime))
            if identity is not None:
                record = self.lifetimes[identity]
                allocation = self.graph.allocations[identity]
                if record.end_event is not None:
                    raise ValueError("allocation lifetime already ended; supply a new lifetime witness")
                if allocation.nbytes != nbytes:
                    raise ValueError("same allocation lifetime has conflicting capacity")
                return identity
        point = self._at(event, "allocate")
        identity = self._id(StorageAllocationID)
        self.graph.add_allocation(StorageAllocation(identity, device, nbytes, token, lifetime))
        self.lifetimes[identity] = AllocationLifetime(identity, lifetime, point)
        if lifetime is not None:
            self._allocation_keys[(device, token, lifetime)] = identity
        self._active_materializations[identity] = set()
        return identity

    def end_lifetime(self, allocation: StorageAllocationID, evidence: EvidenceClaim,
                     *, event: EventPoint | None = None) -> None:
        if allocation not in self.lifetimes:
            raise ValueError("unknown allocation lifetime")
        self._preflight(evidence, event=event)
        record = self.lifetimes[allocation]
        if record.end_event is not None:
            raise ValueError("allocation lifetime already ended")
        point = self._at(event, "free")
        self.lifetimes[allocation] = replace(record, end_event=point)
        for identity in tuple(self._active_materializations[allocation]):
            self._invalidate(identity, point, "allocation lifetime ended", evidence)

    def region(self, allocation: StorageAllocationID, offset: int,
               shape: tuple[int, ...], strides: tuple[int, ...], dtype: str) -> StorageRegionID:
        if allocation not in self.graph.allocations or self.lifetimes[allocation].end_event is not None:
            raise ValueError("region requires a live allocation")
        candidate = StorageRegion(StorageRegionID("pending"), allocation, offset, tuple(shape), tuple(strides),
                                  dtype, self.graph.allocations[allocation].device)
        errors = record_errors(candidate, StorageRegion, "region")
        if not errors:
            errors.extend(self.graph._region_errors(candidate))
        if errors:
            raise ValueError("invalid region: " + "; ".join(errors))
        key = (allocation, offset, tuple(shape), tuple(strides), dtype)
        if key in self._region_keys:
            return self._region_keys[key]
        identity = self._id(StorageRegionID)
        self.graph.add_region(replace(candidate, id=identity))
        self._region_keys[key] = identity
        return identity

    def _new_version(self, relation, inputs, semantic_type, evidence, producer=None):
        logical = self._id(LogicalValueID)
        self.graph.add_logical_value(LogicalValue(logical, semantic_type))
        version, provenance = ValueVersionID(logical, 0), self._id(ProvenanceID)
        self.graph.add_version(ValueVersion(version, provenance, tuple(inputs), semantic_type, self.scope))
        self._latest_versions[logical] = 0
        self.graph.add_provenance(ProvenanceRecord(provenance, relation, tuple(inputs), (version,),
                                                  producer, evidence=evidence.kind.value))
        return version

    def _materialization(self, version, object_id, region_id, evidence, coverage, point,
                         *, ready=True, branch_on_write=False, producer=None, relation=BindingRelation.OWNS):
        if region_id not in self.graph.regions:
            raise ValueError("unknown materialization region")
        region = self.graph.regions[region_id]
        if self.lifetimes[region.allocation].end_event is not None:
            raise ValueError("cannot materialize into ended allocation")
        coverage = self._coverage(coverage, evidence)
        identity = self._id(MaterializationID)
        self.graph.add_materialization(Materialization(identity, version, "strided_tensor", region.device,
            region_id, producer, point.label if ready else None, self.scope, evidence.kind.value))
        handle = ValueHandle(object_id, version, identity)
        self.graph.add_binding(ObjectBinding(object_id, version, relation, self.scope, evidence.kind.value))
        self.handles[identity] = handle
        self.coverage[identity] = coverage
        ready_state = ReadyState.READY if ready else ReadyState.PENDING
        state = GuardState.VALID if ready and coverage.completeness is Completeness.COMPLETE and not (
            coverage.foreign_aliases or coverage.escaped_boundaries) else GuardState.NEEDS_VERIFICATION
        self.validity[identity] = ValidityRecord(identity, version, point, None, state, ready_state,
            branch_on_write, "observed representation; stability requires covered writes and readiness", (evidence,))
        self._active_materializations[region.allocation].add(identity)
        return handle

    def origin(self, object_id: ObjectID, region: StorageRegionID, evidence: EvidenceClaim,
               *, coverage: Completeness | MutationCoverage = Completeness.UNKNOWN,
               semantic_type: str = "tensor", event: EventPoint | None = None) -> ValueHandle:
        self._preflight(evidence, object_id=object_id, region=region, coverage=coverage, event=event)
        if not isinstance(semantic_type, str) or not semantic_type:
            raise ValueError("origin semantic type is required")
        point = self._at(event, "origin")
        version = self._new_version(ProvenanceRelation.ORIGIN, (), semantic_type, evidence)
        return self._materialization(version, object_id, region, evidence, coverage, point)

    def view(self, source: ValueHandle, object_id: ObjectID, region: StorageRegionID,
             evidence: EvidenceClaim, *, event: EventPoint | None = None) -> ValueHandle:
        self._check(source)
        self._preflight(evidence, object_id=object_id, region=region, event=event)
        if self.guard(source).state is GuardState.INVALID:
            raise ValueError("view source handle is invalid; observe current contents first")
        source_region = self.graph.regions[self.graph.materializations[source.materialization].region]
        if self.graph.regions[region].allocation != source_region.allocation:
            raise ValueError("a view must share its source allocation")
        point = self._at(event, "view")
        version = self._new_version(ProvenanceRelation.VIEW, (source.version,), "tensor", evidence)
        return self._materialization(version, object_id, region, evidence,
            self.coverage[source.materialization], point, relation=BindingRelation.VIEW)

    def _exact(self, source, contract):
        if contract is None:
            return False
        errors = record_errors(contract, ExactContract, "exact_contract")
        if errors:
            raise ValueError("invalid exact contract: " + "; ".join(errors))
        if contract.status is not ProofStatus.PROVEN or contract.scope != self.scope:
            return False
        if any(version not in self.graph.versions for version in contract.checked_versions):
            raise ValueError("exact contract references unknown checked versions")
        if contract.checked_at is not None and (contract.checked_at.scope != self.scope
                or contract.checked_at.ordinal > self.current_event.ordinal):
            raise ValueError("exact contract check event outside current execution scope")
        guard = self.guard(source)
        if self.validity[source.materialization].ready is not ReadyState.READY:
            return False
        return guard.state is GuardState.VALID or (
            guard.state is not GuardState.INVALID and source.version in contract.checked_versions
            and contract.checked_at == self.current_event)

    def copy(self, source: ValueHandle, object_id: ObjectID, region: StorageRegionID,
             evidence: EvidenceClaim, *, contract: ExactContract | None = None, mutable: bool = True,
             coverage: Completeness | MutationCoverage = Completeness.UNKNOWN,
             event: EventPoint | None = None) -> ValueHandle:
        self._check(source)
        self._preflight(evidence, object_id=object_id, region=region, coverage=coverage, event=event)
        if type(mutable) is not bool:
            raise ValueError("mutable must be bool")
        if self.guard(source).state is GuardState.INVALID:
            raise ValueError("copy source handle is invalid; observe current contents first")
        exact = self._exact(source, contract)
        source_region = self.graph.regions[self.graph.materializations[source.materialization].region]
        if self.graph.regions[region].allocation == source_region.allocation:
            raise ValueError("independent copy requires a distinct allocation")
        point = self._at(event, "copy")
        target_region = self.graph.regions[region]
        if source_region.shape != target_region.shape or source_region.dtype != target_region.dtype:
            return self.transform((source,), object_id, region, evidence, coverage=coverage, event=point)
        if exact and not mutable:
            version = source.version
        else:
            version = self._new_version(ProvenanceRelation.COPY, (source.version,), "tensor", evidence)
            provenance = self.graph.provenance[self.graph.versions[version].provenance_id]
            if exact:
                provenance.equivalence = EquivalenceClaim.EXACT_CONTENT_AT_TIME
        result = self._materialization(version, object_id, region, evidence, coverage, point,
            branch_on_write=version == source.version, relation=BindingRelation.COPY)
        if exact:
            self.equalities.append(EqualityEvidence(source, result, EquivalenceClaim.EXACT_CONTENT_AT_TIME,
                "versioned_copy_contract", point, contract, evidence))
        return result

    def materialize(self, source: ValueHandle, object_id: ObjectID, region: StorageRegionID,
                    evidence: EvidenceClaim, *, contract: ExactContract | None,
                    ready: bool = True, coverage: Completeness | MutationCoverage = Completeness.UNKNOWN,
                    event: EventPoint | None = None) -> ValueHandle:
        self._check(source)
        self._preflight(evidence, object_id=object_id, region=region, coverage=coverage, event=event)
        if type(ready) is not bool:
            raise ValueError("ready must be bool")
        if self.guard(source).state is GuardState.INVALID:
            raise ValueError("materialization source handle is invalid; observe current contents first")
        source_materialization = self.graph.materializations[source.materialization]
        if object_id == source.object_id and region == source_materialization.region:
            return source  # same-device no-op has no new copy or materialization
        exact = self._exact(source, contract)
        point = self._at(event, "materialize")
        source_region = self.graph.regions[source_materialization.region]
        target_region = self.graph.regions[region]
        if source_region.shape != target_region.shape or source_region.dtype != target_region.dtype:
            result = self.transform((source,), object_id, region, evidence, coverage=coverage, event=point)
            if not ready:
                self.validity[result.materialization] = replace(self.validity[result.materialization], ready=ReadyState.PENDING)
            return result
        version = source.version if exact else self._new_version(
            ProvenanceRelation.COPY, (source.version,), "tensor", evidence)
        if exact:
            self.graph.add_provenance(ProvenanceRecord(self._id(ProvenanceID), ProvenanceRelation.MATERIALIZE,
                (version,), (version,), equivalence=EquivalenceClaim.EXACT_LOGICAL, evidence=evidence.kind.value))
        result = self._materialization(version, object_id, region, evidence, coverage, point,
            ready=ready, branch_on_write=exact)
        if exact and ready:
            self.equalities.append(EqualityEvidence(source, result, EquivalenceClaim.EXACT_LOGICAL,
                "versioned_materialization_contract", point, contract, evidence))
        return result

    def transform(self, inputs: tuple[ValueHandle, ...], object_id: ObjectID, region: StorageRegionID,
                  evidence: EvidenceClaim, *, producer: OperationInstanceID | None = None,
                  aggregate: bool = False, coverage: Completeness | MutationCoverage = Completeness.UNKNOWN,
                  event: EventPoint | None = None) -> ValueHandle:
        for handle in inputs:
            self._check(handle)
            if self.guard(handle).state is GuardState.INVALID:
                raise ValueError("transform input handle is invalid; observe current contents first")
        self._preflight(evidence, object_id=object_id, region=region, coverage=coverage, event=event)
        if producer is not None and not isinstance(producer, OperationInstanceID):
            raise ValueError("producer must be OperationInstanceID")
        if type(aggregate) is not bool:
            raise ValueError("aggregate must be bool")
        point = self._at(event, "aggregate" if aggregate else "transform")
        parents = tuple(dict.fromkeys(handle.version for handle in inputs))
        version = self._new_version(ProvenanceRelation.AGGREGATE if aggregate else ProvenanceRelation.TRANSFORM,
                                    parents, "tensor", evidence, producer)
        return self._materialization(version, object_id, region, evidence, coverage, point, producer=producer)

    def _invalidate(self, identity, point, reason, evidence):
        record = self.validity[identity]
        if record.state is not GuardState.INVALID:
            self.validity[identity] = replace(record, state=GuardState.INVALID,
                end_event=point, reason=reason, evidence=record.evidence + (evidence,))
            region = self.graph.regions[self.graph.materializations[identity].region]
            self._active_materializations[region.allocation].discard(identity)

    def invalidate(self, handle: ValueHandle, reason: str, evidence: EvidenceClaim,
                   *, event: EventPoint | None = None) -> None:
        self._check(handle)
        self._preflight(evidence, event=event)
        if not reason:
            raise ValueError("invalidation reason is required")
        self._invalidate(handle.materialization, self._at(event, "invalidate"), reason, evidence)

    def mutate(self, handle: ValueHandle, written_region: StorageRegionID, evidence: EvidenceClaim,
               *, event: EventPoint | None = None) -> ValueHandle:
        self._check(handle)
        self._preflight(evidence, region=written_region, event=event)
        if self.guard(handle).state is GuardState.INVALID:
            raise ValueError("mutation source handle is invalid; observe current contents first")
        if evidence.kind is not EvidenceKind.OBSERVED:
            raise ValueError("mutation requires observed write evidence; missing coverage is not a write")
        materialization = self.graph.materializations[handle.materialization]
        source_region = self.graph.regions[materialization.region]
        write = self.graph.regions[written_region]
        if source_region.allocation != write.allocation:
            raise ValueError("write must target the handle's allocation")
        if region_overlap(source_region, write) is Overlap.DISJOINT:
            raise ValueError("write region is disjoint from the mutated handle")
        if self.lifetimes[write.allocation].end_event is not None:
            raise ValueError("write targets an ended allocation")
        point = self._at(event, "mutation")
        parent = handle.version
        if self.validity[handle.materialization].branch_on_write:
            parent = self._new_version(ProvenanceRelation.COPY, (parent,), "tensor", evidence)
        logical = parent.logical_value
        version_number = self._latest_versions[logical] + 1
        version, provenance = ValueVersionID(logical, version_number), self._id(ProvenanceID)
        self.graph.add_version(ValueVersion(version, provenance, (parent,), "tensor", self.scope))
        self._latest_versions[logical] = version_number
        self.graph.add_provenance(ProvenanceRecord(provenance, ProvenanceRelation.MUTATE,
            (parent,), (version,), evidence=evidence.kind.value))
        for identity in tuple(self._active_materializations[write.allocation]):
            candidate = self.graph.materializations[identity]
            region = self.graph.regions[candidate.region]
            overlap = region_overlap(region, write)
            if overlap is not Overlap.DISJOINT:
                self._invalidate(identity, point, "observed write overlaps representation" if overlap is Overlap.OVERLAPS
                                 else "observed write may overlap representation", evidence)
        coverage = self.coverage[handle.materialization]
        coverage = replace(coverage, observed_writes=coverage.observed_writes + (point,))
        return self._materialization(version, handle.object_id, materialization.region, evidence,
                                      coverage, point)

    def escape(self, handle: ValueHandle, boundary: str, evidence: EvidenceClaim,
               *, event: EventPoint | None = None) -> None:
        self._check(handle)
        self._preflight(evidence, event=event)
        if not boundary:
            raise ValueError("escape boundary is required")
        self._at(event, "escape")
        region = self.graph.regions[self.graph.materializations[handle.materialization].region]
        for identity in tuple(self._active_materializations[region.allocation]):
            candidate = self.graph.materializations[identity]
            other = self.graph.regions[candidate.region]
            if other.allocation == region.allocation:
                coverage = self.coverage[identity]
                self.coverage[identity] = replace(coverage, completeness=Completeness.PARTIAL,
                    escaped_boundaries=tuple(sorted(set(coverage.escaped_boundaries + (boundary,)))),
                    evidence=coverage.evidence + (evidence,))
                record = self.validity[identity]
                if record.state is not GuardState.INVALID:
                    self.validity[identity] = replace(record, state=GuardState.NEEDS_VERIFICATION,
                        reason="mutable storage escaped observed scope", evidence=record.evidence + (evidence,))

    def mark_ready(self, handle: ValueHandle, evidence: EvidenceClaim,
                   *, event: EventPoint | None = None) -> None:
        self._check(handle)
        self._preflight(evidence, event=event)
        if evidence.kind is not EvidenceKind.OBSERVED:
            raise ValueError("readiness requires observed completion evidence")
        point = self._at(event, "ready")
        record = self.validity[handle.materialization]
        self.validity[handle.materialization] = replace(record, ready=ReadyState.READY,
                                                       evidence=record.evidence + (evidence,))
        self.graph.materializations[handle.materialization].ready_event = point.label

    def set_coverage(self, handle: ValueHandle, coverage: MutationCoverage) -> None:
        self._check(handle)
        self.coverage[handle.materialization] = self._coverage(coverage, EvidenceClaim(EvidenceKind.UNKNOWN))

    def guard(self, handle: ValueHandle, scope: str | None = None) -> GuardResult:
        self._check(handle)
        record, coverage = self.validity[handle.materialization], self.coverage[handle.materialization]
        requirements = []
        if record.state is GuardState.INVALID:
            state, reason = GuardState.INVALID, record.reason
        else:
            if scope is not None and scope != self.scope:
                requirements.append("establish mutation coverage in requested execution scope")
            if record.ready is not ReadyState.READY:
                requirements.append("observe completion and required happens-before for materialization")
            if coverage.completeness is not Completeness.COMPLETE:
                requirements.append("close mutation observation or compare an enrolled exact checkpoint")
            if coverage.foreign_aliases:
                requirements.append("observe foreign alias writes or verify exact content")
            if coverage.escaped_boundaries:
                requirements.append("close escaped consumer boundaries or verify exact content")
            state = GuardState.NEEDS_VERIFICATION if requirements else GuardState.VALID
            reason = "required facts missing" if requirements else "ready representation with complete mutation coverage at this event"
        return GuardResult(state, (handle.version,), (handle.materialization,), self.current_event,
                           tuple(requirements), reason, record.evidence + coverage.evidence)

    def bind_slot(self, slot: ValueSlotID, handle: ValueHandle, evidence: EvidenceClaim,
                  *, scope: str | None = None, event: EventPoint | None = None) -> BindingInterval:
        self._check(handle)
        self._preflight(evidence, event=event)
        if not isinstance(slot, ValueSlotID) or (scope is not None and (not isinstance(scope, str) or not scope)):
            raise ValueError("binding requires typed slot and non-empty scope")
        point = self._at(event, "bind_slot")
        binding_scope = scope or self.scope
        self.finish_binding(slot, scope=binding_scope, event=point)
        interval = BindingInterval(slot, handle, binding_scope, point, None, evidence)
        self.bindings.append(interval)
        return interval

    def finish_binding(self, slot: ValueSlotID, *, scope: str | None = None,
                       event: EventPoint | None = None) -> None:
        point = self._at(event, "finish_binding")
        for index, interval in enumerate(self.bindings):
            if interval.slot == slot and interval.scope == (scope or self.scope) and interval.end_event is None:
                self.bindings[index] = replace(interval, end_event=point)

    def attach_observation(self, observation_id: str, handle: ValueHandle, evidence: EvidenceClaim,
                           *, event: EventPoint | None = None) -> ObservationAttachment:
        self._check(handle)
        self._preflight(evidence, event=event)
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("observation identity is required")
        point = self._at(event, "attach_observation")
        attachment = ObservationAttachment(observation_id, handle, point, evidence)
        self.attachments.append(attachment)
        return attachment

    def record_equality(self, left: ValueHandle, right: ValueHandle, contract: ExactContract,
                        method: str, evidence: EvidenceClaim,
                        *, event: EventPoint | None = None) -> EqualityEvidence:
        """Record a check at one event; this never upgrades future guards."""
        self._check(left)
        self._check(right)
        self._preflight(evidence, event=event)
        errors = record_errors(contract, ExactContract, "equality_contract")
        if errors:
            raise ValueError("invalid equality contract: " + "; ".join(errors))
        if not method or contract.status is not ProofStatus.PROVEN or contract.scope != self.scope:
            raise ValueError("equality requires a method and proven scoped contract")
        if any(version not in self.graph.versions for version in contract.checked_versions):
            raise ValueError("equality contract references unknown checked versions")
        if contract.checked_at is not None and (contract.checked_at.scope != self.scope
                or contract.checked_at.ordinal > self.current_event.ordinal):
            raise ValueError("equality contract check outside execution scope")
        if self.guard(left).state is GuardState.INVALID or self.guard(right).state is GuardState.INVALID:
            raise ValueError("equality uses an invalid historical handle")
        point = self._at(event, "equality_check")
        equality = EqualityEvidence(left, right, EquivalenceClaim.EXACT_CONTENT_AT_TIME,
                                    method, point, contract, evidence)
        self.equalities.append(equality)
        return equality

    def validate(self) -> dict[str, Any]:
        errors = ["values: " + error for error in self.graph.validate()["errors"]]
        errors.extend(record_errors(self.current_event, EventPoint, "current_event"))
        if errors:
            return {"valid": False, "errors": errors}
        if self.current_event.scope != self.scope:
            errors.append("current event scope differs from registry scope")
        if type(self._serial) is not int or self._serial < 0:
            errors.append("invalid registry identity serial")
            return {"valid": False, "errors": errors}
        generated = [identity for mapping in (self.graph.logical_values, self.graph.provenance,
            self.graph.allocations, self.graph.regions, self.graph.materializations) for identity in mapping]
        prefix = self.namespace + ":"
        serials = [int(identity.value[len(prefix):]) for identity in generated
                   if identity.value.startswith(prefix) and identity.value[len(prefix):].isdigit()]
        if serials and self._serial < max(serials):
            errors.append("identity serial precedes existing registry IDs")
        for name, records, expected in (
            ("validity", self.validity.values(), ValidityRecord),
            ("coverage", self.coverage.values(), MutationCoverage),
            ("handles", self.handles.values(), ValueHandle),
            ("lifetimes", self.lifetimes.values(), AllocationLifetime),
            ("bindings", self.bindings, BindingInterval),
            ("equalities", self.equalities, EqualityEvidence),
            ("attachments", self.attachments, ObservationAttachment),
        ):
            for index, record in enumerate(records):
                errors.extend(record_errors(record, expected, f"{name}[{index}]"))
        if errors:
            return {"valid": False, "errors": errors}
        materializations = set(self.graph.materializations)
        for name, records in (("validity", self.validity), ("coverage", self.coverage), ("handles", self.handles)):
            if set(records) != materializations:
                errors.append(f"{name} must cover exactly the materializations")
        if set(self.lifetimes) != set(self.graph.allocations):
            errors.append("allocation lifetimes must cover exactly the allocations")
        if errors:
            return {"valid": False, "errors": errors}
        for identity, record in self.validity.items():
            materialization = self.graph.materializations.get(identity)
            if identity != record.materialization or materialization is None or record.version != materialization.value_version:
                errors.append("validity references inconsistent materialization/version")
            self._interval_errors(record.start_event, record.end_event, errors)
            if record.state is GuardState.INVALID and record.end_event is None:
                errors.append("invalid materialization requires an end event")
        object_bindings = {(binding.object_id, binding.value_version) for binding in self.graph.bindings}
        for identity, handle in self.handles.items():
            materialization = self.graph.materializations.get(identity)
            if handle.materialization != identity or materialization is None or handle.version != materialization.value_version:
                errors.append("handle references inconsistent materialization/version")
            if (handle.object_id, handle.version) not in object_bindings:
                errors.append("handle lacks matching object binding")
        live_allocations = {self.graph.regions[self.graph.materializations[identity].region].allocation
                            for identity, record in self.validity.items() if record.state is not GuardState.INVALID}
        for identity, record in self.lifetimes.items():
            if identity != record.allocation:
                errors.append("allocation lifetime identity mismatch")
            self._interval_errors(record.start_event, record.end_event, errors)
            if record.end_event is not None and identity in live_allocations:
                errors.append("ended allocation retains a live materialization")
        for record in self.coverage.values():
            if record.scope != self.scope:
                errors.append("mutation coverage belongs to another registry scope")
            try:
                self._coverage(record, EvidenceClaim(EvidenceKind.UNKNOWN))
            except ValueError as exc:
                errors.append(str(exc))
            for point in record.observed_writes:
                self._interval_errors(point, None, errors)
        for interval in self.bindings:
            self._interval_errors(interval.start_event, interval.end_event, errors)
            self._handle_errors(interval.handle, errors)
            if not interval.scope:
                errors.append("binding interval requires an execution scope")
        per_slot = {}
        for interval in self.bindings:
            per_slot.setdefault((interval.slot, interval.scope), []).append(interval)
        for intervals in per_slot.values():
            intervals.sort(key=lambda interval: interval.start_event.ordinal)
            for left, right in zip(intervals, intervals[1:]):
                if left.end_event is None or left.end_event.ordinal > right.start_event.ordinal:
                    errors.append("overlapping binding intervals in the same slot/scope")
        for attachment in self.attachments:
            self._handle_errors(attachment.handle, errors)
            self._interval_errors(attachment.attached_at, None, errors)
            if not attachment.observation_id:
                errors.append("empty observation attachment identity")
        for equality in self.equalities:
            self._handle_errors(equality.left, errors)
            self._handle_errors(equality.right, errors)
            self._interval_errors(equality.compared_at, None, errors)
            if equality.contract.status is not ProofStatus.PROVEN or equality.contract.scope != self.scope:
                errors.append("exact equality requires a proven contract in this scope")
            if not equality.method:
                errors.append("equality comparison method is required")
            if any(version not in self.graph.versions for version in equality.contract.checked_versions):
                errors.append("equality contract references unknown versions")
            if equality.contract.checked_at is not None:
                point = equality.contract.checked_at
                if point.scope != self.scope or point.ordinal > equality.compared_at.ordinal:
                    errors.append("equality contract has an invalid check event")
        return {"valid": not errors, "errors": errors,
                "counts": {"versions": len(self.graph.versions), "materializations": len(materializations),
                           "bindings": len(self.bindings), "equalities": len(self.equalities),
                           "attachments": len(self.attachments)}}

    def _interval_errors(self, start, end, errors):
        if start.scope != self.scope or start.ordinal > self.current_event.ordinal:
            errors.append("event is outside registry execution scope")
        if end is not None and (end.scope != start.scope or end.ordinal < start.ordinal or end.ordinal > self.current_event.ordinal):
            errors.append("invalid event interval")

    def _handle_errors(self, handle, errors):
        if self.handles.get(handle.materialization) != handle:
            errors.append("ledger references unknown or inconsistent handle")

    def assert_valid(self):
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid provenance registry: " + "; ".join(report["errors"]))
        return report

    def validate_references(self, semantic=None, evidence=None) -> list[str]:
        """Check optional external graph references without merging identities."""
        errors = list(self.validate()["errors"])
        if semantic is not None:
            for interval in self.bindings:
                if interval.slot not in semantic.slots:
                    errors.append(f"binding references unknown semantic slot {interval.slot.wire}")
        if evidence is not None:
            for attachment in self.attachments:
                if attachment.observation_id not in evidence.observations:
                    errors.append(f"attachment references unknown observation {attachment.observation_id}")
            for provenance in self.graph.provenance.values():
                if provenance.producer is not None and provenance.producer not in evidence.instances:
                    errors.append(f"provenance references unknown producer {provenance.producer.wire}")
        return errors

    def to_dict(self):
        validation = self.assert_valid()
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
            "scope": self.scope, "namespace": self.namespace, "serial": self._serial,
            "current_event": _encode(self.current_event), "values": self.graph.to_dict(),
            "validity": [_encode(self.validity[key]) for key in sorted(self.validity, key=lambda item: item.wire)],
            "coverage": [{"materialization": _encode(key), "coverage": _encode(self.coverage[key])}
                         for key in sorted(self.coverage, key=lambda item: item.wire)],
            "handles": [_encode(self.handles[key]) for key in sorted(self.handles, key=lambda item: item.wire)],
            "lifetimes": [_encode(self.lifetimes[key]) for key in sorted(self.lifetimes, key=lambda item: item.wire)],
            "bindings": [_encode(item) for item in self.bindings],
            "equalities": [_encode(item) for item in self.equalities],
            "attachments": [_encode(item) for item in self.attachments], "validation": validation}

    @classmethod
    def from_dict(cls, document):
        keys = {"schema", "schema_version", "scope", "namespace", "serial", "current_event", "values",
                "validity", "coverage", "handles", "lifetimes", "bindings", "equalities", "attachments", "validation"}
        if not isinstance(document, dict) or set(document) != keys:
            raise ValueError("invalid registry document fields")
        if document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError("unsupported provenance registry schema")
        if any(not isinstance(document[field], str) or not document[field] for field in ("scope", "namespace")):
            raise ValueError("invalid registry scope or namespace")
        if any(not isinstance(document[field], list) for field in (
            "validity", "coverage", "handles", "lifetimes", "bindings", "equalities", "attachments")):
            raise ValueError("registry ledgers must be JSON arrays")
        registry = cls(document["scope"], document["namespace"])
        if type(document["serial"]) is not int or document["serial"] < 0:
            raise ValueError("invalid registry identity serial")
        registry._serial = document["serial"]
        registry.current_event = _decode(EventPoint, document["current_event"])
        registry.graph = values_from_dict(document["values"])
        for name, expected, key in (("validity", ValidityRecord, "materialization"),
                                    ("handles", ValueHandle, "materialization"),
                                    ("lifetimes", AllocationLifetime, "allocation")):
            records = getattr(registry, name)
            for item in document[name]:
                record = _decode(expected, item)
                identity = getattr(record, key)
                if identity in records:
                    raise ValueError("duplicate registry ledger identity")
                records[identity] = record
        for item in document["coverage"]:
            if set(item) != {"materialization", "coverage"}:
                raise ValueError("invalid coverage ledger fields")
            identity = _decode(MaterializationID, item["materialization"])
            if identity in registry.coverage:
                raise ValueError("duplicate coverage identity")
            registry.coverage[identity] = _decode(MutationCoverage, item["coverage"])
        for name, expected in (("bindings", BindingInterval), ("equalities", EqualityEvidence),
                               ("attachments", ObservationAttachment)):
            setattr(registry, name, [_decode(expected, item) for item in document[name]])
        registry.assert_valid()
        registry._rebuild_indexes()
        return registry

    def _rebuild_indexes(self):
        self._latest_versions = {}
        for identity in self.graph.versions:
            self._latest_versions[identity.logical_value] = max(
                self._latest_versions.get(identity.logical_value, -1), identity.version)
        self._allocation_keys = {
            (self.graph.allocations[identity].device, self.graph.allocations[identity].allocator_token, record.witness): identity
            for identity, record in self.lifetimes.items() if record.witness is not None}
        self._region_keys = {(record.allocation, record.offset, record.shape, record.strides, record.dtype): identity
                             for identity, record in self.graph.regions.items()}
        self._active_materializations = {identity: set() for identity in self.lifetimes}
        for identity, record in self.validity.items():
            if record.state is not GuardState.INVALID:
                region = self.graph.regions[self.graph.materializations[identity].region]
                self._active_materializations[region.allocation].add(identity)

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, payload: str):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result
        return cls.from_dict(json.loads(payload, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON value"))))


def _encode(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Identifier, ValueVersionID)):
        return value.as_dict()
    if is_dataclass(value):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _decode(expected, value):
    origin, arguments = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        for choice in arguments:
            try:
                return _decode(choice, value)
            except (ValueError, TypeError):
                pass
        raise ValueError("invalid optional registry record")
    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError("tuple field must be a JSON array")
        return tuple(_decode(arguments[0], item) for item in value)
    if isinstance(expected, type) and issubclass(expected, Enum):
        return expected(value)
    if isinstance(expected, type) and issubclass(expected, Identifier):
        if not isinstance(value, dict) or set(value) != {"kind", "value", "wire"}:
            raise ValueError("invalid typed registry ID")
        identity = expected(value["value"])
        if identity.prefix != value["kind"] or identity.wire != value["wire"]:
            raise ValueError("registry ID kind/wire mismatch")
        return identity
    if expected is ValueVersionID:
        if not isinstance(value, dict) or set(value) != {"logical_value", "version", "wire"}:
            raise ValueError("invalid registry version ID")
        identity = ValueVersionID(_decode(LogicalValueID, value["logical_value"]), _decode(int, value["version"]))
        if identity.wire != value["wire"]:
            raise ValueError("registry version wire mismatch")
        return identity
    if is_dataclass(expected):
        if not isinstance(value, dict) or set(value) != {field.name for field in fields(expected)}:
            raise ValueError("invalid registry record fields")
        hints = get_type_hints(expected)
        result = expected(**{name: _decode(hints[name], item) for name, item in value.items()})
        errors = record_errors(result, expected, "record")
        if errors:
            raise ValueError("; ".join(errors))
        return result
    if expected is float and type(value) in (float, int):
        return value
    if type(value) is not expected:
        raise ValueError(f"invalid registry primitive, expected {expected}")
    return value


__all__ = ["AllocationLifetime", "BindingInterval", "EqualityEvidence", "EventPoint", "ExactContract",
           "GuardResult", "GuardState", "MutationCoverage", "ObservationAttachment", "Overlap",
           "ProvenanceRegistry", "ReadyState", "ValidityRecord", "ValueHandle", "region_overlap"]

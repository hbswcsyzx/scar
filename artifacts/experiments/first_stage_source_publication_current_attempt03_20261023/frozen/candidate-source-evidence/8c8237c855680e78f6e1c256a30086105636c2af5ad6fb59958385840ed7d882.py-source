"""Explicit contract requirements and actual observations over original ports.

These records declare a Q association, not semantic/runtime correspondence or
endpoint visibility. They create no operations, work tickets, or state values.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.ids import ResourceRequirementID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.contracts import ContractFacet
from scar.ir.v2.ids import ContractID, ValueSlotID
from .common import FactSource, Unresolved
from .content import ProtocolInterval
from .coordinates import OccurrencePoint
from .ids import ObservationRequirementID, ObservationRootID, ResourceBindingID, ValueOccurrenceID
from .resources import ResourceTarget, _exact, _id, _record, _source, _support, _target, _variant


@dataclass(frozen=True, slots=True)
class ContractRef:
    artifact: ProviderArtifact
    contract: ContractID

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "contract artifact")
        _id(self.contract, ContractID, "contract ID")


@dataclass(frozen=True, slots=True)
class RequiredOutput:
    slot: ValueSlotID

    def __post_init__(self):
        _id(self.slot, ValueSlotID, "required output slot")


@dataclass(frozen=True, slots=True)
class RequiredEndpoint:
    requirement: ResourceRequirementID | Unresolved
    facet: ContractFacet

    def __post_init__(self):
        _variant(self.requirement, (ResourceRequirementID, Unresolved), "required core endpoint")
        _exact(self.facet, ContractFacet, "required endpoint facet")


@dataclass(frozen=True, slots=True)
class ObservationRequirement:
    id: ObservationRequirementID
    contract: ContractRef
    target: RequiredOutput | RequiredEndpoint
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, ObservationRequirementID, "observation requirement ID")
        _record(self.contract, ContractRef, "observation contract")
        _variant(self.target, (RequiredOutput, RequiredEndpoint), "observation requirement target")
        _record(self.protocol, ProviderFactReference, "observation protocol")
        _source(self.source, "observation requirement source")


@dataclass(frozen=True, slots=True)
class OutputValue:
    value: ValueOccurrenceID

    def __post_init__(self):
        _id(self.value, ValueOccurrenceID, "observed output value")


@dataclass(frozen=True, slots=True)
class BoundEndpoint:
    binding: ResourceBindingID

    def __post_init__(self):
        _id(self.binding, ResourceBindingID, "observed endpoint binding")


@dataclass(frozen=True, slots=True)
class ExternalEndpoint:
    target: ResourceTarget

    def __post_init__(self):
        _target(self.target, "external observation endpoint")


@dataclass(frozen=True, slots=True)
class ObservationRoot:
    id: ObservationRootID
    requirement: ObservationRequirementID
    actual: OutputValue | BoundEndpoint | ExternalEndpoint | Unresolved
    interval: ProtocolInterval
    anchor: OccurrencePoint | Unresolved
    support: tuple[ValueOccurrenceID, ...]
    source: FactSource

    def __post_init__(self):
        _id(self.id, ObservationRootID, "observation root ID")
        _id(self.requirement, ObservationRequirementID, "root observation requirement")
        _variant(self.actual, (OutputValue, BoundEndpoint, ExternalEndpoint, Unresolved), "root actual observation")
        _record(self.interval, ProtocolInterval, "observation interval")
        _variant(self.anchor, (OccurrencePoint, Unresolved), "observation state anchor")
        _support(self.support, "observation state support")
        _source(self.source, "observation root source")


__all__ = [
    "BoundEndpoint", "ContractRef", "ExternalEndpoint", "ObservationRequirement",
    "ObservationRoot", "OutputValue", "RequiredEndpoint", "RequiredOutput",
]

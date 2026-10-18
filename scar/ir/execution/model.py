"""Execution associations; canonical operations, Uses and state stay in ProgramGraph."""
from dataclasses import dataclass

from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.ids import OperationInstanceID
from .common import FactSource, _identifier
from .coordinates import (
    BlockVisit, ControlTransfer, ExecutionRun, ExecutionSegment, HostThreadInstance,
    OperationOccurrence, ProcessInstance, ProgramSnapshot, RegionActivation,
    UseOccurrence, ValueOccurrence,
)
from .ids import OperationOccurrenceID
from .resources import (
    AllocationPlacement, HandleBinding, RequirementBinding, ResourceAccessBinding,
    ResourceInstance, ResourceRealization,
)


@dataclass(frozen=True, slots=True)
class LegacyOperationRef:
    artifact: ProviderArtifact
    instance: OperationInstanceID

    def __post_init__(self):
        if type(self.artifact) is not ProviderArtifact or type(self.instance) is not OperationInstanceID:
            raise TypeError('legacy operation reference requires artifact and legacy instance ID')
        self.artifact.__post_init__()
        _identifier(self.instance, OperationInstanceID, 'legacy instance')


@dataclass(frozen=True, slots=True)
class OccurrenceEvidenceBinding:
    operation: OperationOccurrenceID
    legacy: LegacyOperationRef
    source: FactSource

    def __post_init__(self):
        from scar.ir.program.providers import ProviderFactReference
        from .common import MissingEvidence
        if type(self.operation) is not OperationOccurrenceID or type(self.legacy) is not LegacyOperationRef:
            raise TypeError('occurrence evidence binding requires distinct core/legacy endpoints')
        if type(self.source) not in (ProviderFactReference, MissingEvidence):
            raise TypeError('occurrence evidence source must be a fact or explicit gap')
        _identifier(self.operation, OperationOccurrenceID, 'core operation occurrence')
        self.legacy.__post_init__()
        self.source.__post_init__()


@dataclass(frozen=True, slots=True)
class ExecutionModel:
    snapshot: ProgramSnapshot
    runs: tuple[ExecutionRun, ...] = ()
    processes: tuple[ProcessInstance, ...] = ()
    threads: tuple[HostThreadInstance, ...] = ()
    activations: tuple[RegionActivation, ...] = ()
    segments: tuple[ExecutionSegment, ...] = ()
    visits: tuple[BlockVisit, ...] = ()
    operations: tuple[OperationOccurrence, ...] = ()
    values: tuple[ValueOccurrence, ...] = ()
    uses: tuple[UseOccurrence, ...] = ()
    transfers: tuple[ControlTransfer, ...] = ()
    resources: tuple[ResourceInstance, ...] = ()
    realizations: tuple[ResourceRealization, ...] = ()
    requirements: tuple[RequirementBinding, ...] = ()
    handles: tuple[HandleBinding, ...] = ()
    accesses: tuple[ResourceAccessBinding, ...] = ()
    placements: tuple[AllocationPlacement, ...] = ()
    evidence_bindings: tuple[OccurrenceEvidenceBinding, ...] = ()

    def __post_init__(self):
        if type(self.snapshot) is not ProgramSnapshot:
            raise TypeError('execution model requires a ProgramSnapshot')
        self.snapshot.__post_init__()
        for name, kind in TABLE_TYPES.items():
            rows = getattr(self, name)
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError(f'{name} must be a tuple of exact {kind.__name__}')
            for row in rows:
                row.__post_init__()


TABLE_TYPES = {
    'runs': ExecutionRun, 'processes': ProcessInstance, 'threads': HostThreadInstance,
    'activations': RegionActivation, 'segments': ExecutionSegment, 'visits': BlockVisit,
    'operations': OperationOccurrence, 'values': ValueOccurrence, 'uses': UseOccurrence,
    'transfers': ControlTransfer, 'resources': ResourceInstance, 'realizations': ResourceRealization,
    'requirements': RequirementBinding, 'handles': HandleBinding, 'accesses': ResourceAccessBinding,
    'placements': AllocationPlacement, 'evidence_bindings': OccurrenceEvidenceBinding,
}


__all__ = ['ExecutionModel', 'LegacyOperationRef', 'OccurrenceEvidenceBinding']

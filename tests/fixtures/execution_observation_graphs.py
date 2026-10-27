"""Explicit Q observations over a canonical resource worker, without work fiction."""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ProtocolInterval
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import (
    ObservationRequirementID, ObservationRootID, OperationOccurrenceID, ValueOccurrenceID,
)
from scar.ir.execution.observations import (
    BoundEndpoint, ContractRef, ExternalEndpoint, ObservationRequirement,
    ObservationRoot, OutputValue, RequiredEndpoint, RequiredOutput,
)
from scar.ir.execution.snapshot import external_artifact
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.contracts import ContractDefinition, ContractFacet, FacetRequirement
from scar.ir.v2.ids import ContractID, ValueSlotID
from scar.ir.v2.semantic import SemanticGraph, ValueSlot
from tests.fixtures.execution_resource_graphs import resource_execution_program


def observation_execution(*, output=False, external=False, activations=1, facet=ContractFacet.EXTERNAL,
                          required=True, anchor_activation=0):
    """Return ``(program, model, semantic_graphs)`` with exact snapshot catalogs.

    Output reads the existing handle occurrence. Endpoints reference the actual
    requirement binding, or explicitly retain an unresolved external association.
    """
    program, model = resource_execution_program(activations=activations)
    semantic = SemanticGraph()
    slot, other, contract = ValueSlotID("output"), ValueSlotID("other"), ContractID("required")
    semantic.add_slot(ValueSlot(slot, "output", "output"))
    semantic.add_slot(ValueSlot(other, "other", "output"))
    semantic.add_contract(ContractDefinition(contract, "explicit required observations", (slot,),
                                           (FacetRequirement(facet, required),)))
    artifact = external_artifact(semantic, "memory:observation-contract")
    protocol = ProviderFactReference(artifact, "declared-observation-protocol")
    point = model.activations[0].entry
    target = (RequiredOutput(slot) if output else
              RequiredEndpoint(Unresolved("no core endpoint", point) if external
                               else program.resource_requirements[0].id, facet))
    requirement = ObservationRequirement(ObservationRequirementID("required"),
        ContractRef(artifact, contract), target, protocol, model.runs[0].source)
    prefix = f"activation.{anchor_activation}.resource."
    anchor = OccurrencePoint(OperationOccurrenceID(prefix + "return"), OccurrencePhase.BEFORE)
    interval = ProtocolInterval(anchor, replace(anchor, phase=OccurrencePhase.AFTER), protocol,
                                model.runs[0].source)
    actual = (OutputValue(ValueOccurrenceID("activation.0.resource.handle")) if output else
              ExternalEndpoint(model.requirements[0].target) if external else
              BoundEndpoint(model.requirements[0].id))
    root = ObservationRoot(ObservationRootID("actual"), requirement.id, actual, interval, anchor,
                           (ValueOccurrenceID(prefix + "used.1"),), model.runs[0].source)
    model = replace(model, observation_requirements=(requirement,), observation_roots=(root,))
    return program, model, {artifact.sha256: semantic}


__all__ = ["observation_execution"]

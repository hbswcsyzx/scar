"""Small, canonical Q inputs for composition-scope ledger tests."""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.composition import CompositionScope
from scar.ir.execution.content import ContentRead, ObservationConsumer
from scar.ir.execution.ids import ContentReadID
from scar.ir.execution.observations import ContractRef
from tests.fixtures.execution_observation_graphs import observation_execution


def composition_scope_execution(
    *,
    owner_kind="run",
    output=True,
    activations=1,
    anchor_activation=0,
    owner_activation=None,
    include_requirement=True,
    include_root=True,
    include_content_read=False,
    include_semantic=True,
    contract_override=None,
):
    """Return program/model/catalog/scope/details using canonical observations.

    Removing both Q rows leaves a valid execution model while the explicit
    scope still retains the contract denominator. A linked ContentRead is
    deliberately unresolved: it demonstrates the Q join without asserting
    content identity, stability, materialization, or a work ticket.
    """
    program, model, semantic_graphs = observation_execution(
        output=output, activations=activations, anchor_activation=anchor_activation)
    original_requirement = model.observation_requirements[0]
    original_root = model.observation_roots[0]
    contract = ContractRef(original_requirement.contract.artifact,
                           original_requirement.contract.contract if contract_override is None
                           else contract_override)

    if owner_kind == "run":
        owner = model.runs[0].id
    elif owner_kind == "activation":
        owner = model.activations[anchor_activation if owner_activation is None else owner_activation].id
    elif owner_kind == "operation":
        owner = original_root.anchor.operation
    else:
        raise ValueError("owner_kind must be run, activation, or operation")

    requirements = model.observation_requirements if include_requirement else ()
    roots = model.observation_roots if include_root else ()
    reads = model.content_reads
    if include_content_read:
        if not include_root:
            raise ValueError("an ObservationConsumer ContentRead requires its original root")
        root = original_root
        point = root.anchor
        unresolved = Unresolved("content relation not captured by this fixture", model.activations[0].entry)
        read = ContentRead(
            ContentReadID("composition.observation.read"),
            ObservationConsumer(root.id),
            unresolved,
            unresolved,
            point,
            root.support,
            unresolved,
            model.runs[0].source,
        )
        reads = (*reads, read)
    model = replace(model, observation_requirements=requirements,
                    observation_roots=roots, content_reads=reads)
    scope = CompositionScope(contract, owner, model.runs[0].source)
    catalog = semantic_graphs if include_semantic else {}
    details = {
        "requirement": original_requirement.id,
        "root": original_root.id,
        "owner": owner,
        "contract": contract,
        "read": ContentReadID("composition.observation.read") if include_content_read else None,
    }
    return program, model, catalog, scope, details


__all__ = ["composition_scope_execution"]

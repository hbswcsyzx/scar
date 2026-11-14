"""A missing producer branch must not erase its acceptance obligation."""
from dataclasses import replace
import pytest

from scar.analysis import source_compilation_flow as producer
from scar.analysis import source_connection_contracts as gate
from scar.ir.program import source_productions as P
from scar.ir.program.source_contexts import ContextState, OwnerRef


def _branch_plan():
    source = P.ProductionOccurrence(0)
    context = ContextState(OwnerRef(0, 'ROOT'), 0, 0, 0)
    root, left, right = (P.ProductionRegionID(name) for name in ('root', 'left', 'right'))
    step = P.ProductionStep(P.ProductionStepID('branch'), root, source,
        P.BranchControl(P.ProductionRegionCall(left, ()), P.ProductionRegionCall(right, ())), (), ())
    regions = tuple(P.ProductionRegion(identity, None if identity == root else root,
        P.ProductionRegionKind.EXECUTION, source, context, (), (),
        (step.id,) if identity == root else ()) for identity in (root, left, right))
    ports = tuple(P.CompilationContextPort(identity, 0, 0) for identity in (root, left, right))
    # Actual producer output, as distinct from the gate's expected relations.
    edges = tuple(P.CompilationContextEdge(step.id, path, kind, target,
        P.CompilationTransition.QUALIFY_SITE) for path, kind, target in producer.references(step.instruction))
    return P.SourceProductionPlan(P.ProductionInput('/src/case.py', '/src', *('a'*64 for _ in range(8))),
        source, P.ProductionPurpose.ROOT, root, regions, (step,), (),
        compilation_flow=P.CompilationContextFlow(ports, edges, ()))


def test_joint_producer_validator_omission_is_rejected(monkeypatch):
    original = _branch_plan()
    assert gate.validate_connection_plan(original)['checked_entry_relations'] == 2
    # The old producer and its validator can agree on the same missing branch.
    monkeypatch.setattr(producer, 'references', lambda instruction: iter(()))
    incomplete = replace(original, compilation_flow=replace(original.compilation_flow, edges=()))
    producer.validate_flow(incomplete)
    with pytest.raises(gate.ConnectionContractError, match='missing=2'):
        gate.validate_connection_plan(incomplete)


def test_declared_reference_type_cannot_disappear_from_rules(monkeypatch):
    monkeypatch.delitem(gate._REFERENCE_RULES, P.LoopControl)
    with pytest.raises(gate.ConnectionContractError, match='LoopControl'):
        gate.connection_reference_catalog()


def test_wrong_target_and_duplicate_edges_are_rejected():
    original = _branch_plan(); flow = original.compilation_flow
    wrong = replace(flow.edges[0], target=original.root)
    with pytest.raises(gate.ConnectionContractError, match='WRONG_LOCAL_ENTRY_TARGET'):
        gate.validate_connection_plan(replace(original, compilation_flow=replace(flow, edges=(wrong,*flow.edges[1:]))))
    with pytest.raises(gate.ConnectionContractError, match='DUPLICATE_ENTRY_EDGE'):
        gate.validate_connection_plan(replace(original, compilation_flow=replace(flow, edges=(*flow.edges,flow.edges[0]))))

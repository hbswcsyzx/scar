from dataclasses import replace

import pytest

from scar.ir.execution.model import LegacyOperationRef, OccurrenceEvidenceBinding
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import require_valid, validate
from scar.ir.v2.evidence import EvidenceGraph, OperationInstance
from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID
from tests.fixtures.execution_resource_graphs import resource_execution_program, resource_execution_with_allocation


def test_acquiring_a_preexisting_instance_does_not_require_faking_a_second_creation():
    program, model = resource_execution_program()
    target = model.realizations[0].target
    # The second static provider occurrence acquires the existing instance.
    # It has its own current-state support, handle and requirement owner.
    model = replace(model, resources=(model.resources[0],),
        realizations=tuple(replace(row, target=target) for row in model.realizations),
        requirements=tuple(replace(row, target=target) for row in model.requirements),
        handles=tuple(replace(row, target=target) for row in model.handles))
    report = require_valid(model, program)
    assert report.gaps and not report.source_runtime_verified
    assert len(model.realizations) == 2 and len(model.resources) == 1
    # Sharing a target does not merge the two invocation-owned requirements.
    access = replace(model.accesses[2], requirement=model.requirements[0].id)
    wrong_owner = replace(model, accesses=(*model.accesses[:2], access, *model.accesses[3:]))
    assert 'resource_access_owner' in {row.code for row in validate(wrong_owner, program).issues}


@pytest.mark.parametrize('kind', ['missing', 'different-graph', 'wrong-size', 'same-hash-new-metadata'])
def test_external_allocation_catalog_is_exact_and_never_opened_from_uri(kind):
    program, model, values = resource_execution_with_allocation()
    if kind == 'missing':
        report = validate(model, program)
        assert report.valid and 'external_graph_unavailable' in {row.code for row in report.gaps}
    elif kind == 'different-graph':
        from scar.ir.v2.values import ValueGraph
        graph = ValueGraph()
        report = validate(model, program, value_graphs={next(iter(values)): graph})
        assert 'external_snapshot' in {row.code for row in report.issues}
    else:
        placement, = model.placements
        artifact = replace(placement.allocation.artifact, size_bytes=placement.allocation.artifact.size_bytes + 1)
        wrong = replace(placement, allocation=replace(placement.allocation, artifact=artifact))
        model = replace(model, placements=(wrong,) if kind == 'wrong-size' else (placement, wrong))
        assert 'external_snapshot' in {row.code for row in validate(model, program, value_graphs=values).issues}


@pytest.mark.parametrize('kind', ['valid', 'missing-catalog', 'missing-instance', 'wrong-family'])
def test_legacy_evidence_link_is_artifact_scoped_and_many_to_many_without_id_rebranding(kind):
    program, model = resource_execution_program(activations=1)
    graph = EvidenceGraph()
    identity = OperationInstanceID('legacy-observation')
    graph.add_instance(OperationInstance(identity, OperationDefinitionID('legacy-definition'), 10, 11))
    artifact = external_artifact(graph)
    link = OccurrenceEvidenceBinding(model.operations[0].id, LegacyOperationRef(artifact, identity), model.runs[0].source)
    # One legacy observed region can cover two core operations; this declares
    # correspondence only, not equality of the two definition namespaces.
    model = replace(model, evidence_bindings=(link, replace(link, operation=model.operations[1].id)))
    catalog = {artifact.sha256: graph}
    if kind == 'missing-catalog':
        report = validate(model, program)
        assert report.valid and 'external_graph_unavailable' in {row.code for row in report.gaps}
    elif kind == 'missing-instance':
        missing = replace(link, legacy=replace(link.legacy, instance=OperationInstanceID('absent')))
        model = replace(model, evidence_bindings=(missing,))
        assert 'evidence_instance' in {row.code for row in validate(model, program, evidence_graphs=catalog).issues}
    elif kind == 'wrong-family':
        from scar.ir.v2.values import ValueGraph
        assert 'external_graph_type' in {row.code for row in validate(model, program,
            evidence_graphs={artifact.sha256: ValueGraph()}).issues}
    else:
        report = require_valid(model, program, evidence_graphs=catalog)
        assert not report.source_runtime_verified and not report.transformation_authorized


@pytest.mark.parametrize('realm_kind', ['run', 'external'])
def test_native_handle_namespace_and_referent_identity_realm_need_not_be_identical(realm_kind):
    from scar.ir.execution.ids import ExternalRealmID
    from scar.ir.execution.resources import ExternalRealm, RunRealm
    from scar.ir.program.providers import ProviderFactReference
    program, model = resource_execution_program(activations=1, native_handles=True)
    realm = (RunRealm(model.runs[0].id) if realm_kind == 'run' else
             ExternalRealm(ExternalRealmID('shared-resource'), ProviderFactReference(model.snapshot.artifact, 'external-namespace')))
    model = replace(model, resources=(replace(model.resources[0], realm=realm), *model.resources[1:]))
    report = require_valid(model, program)
    assert report.gaps and not report.source_runtime_verified


def test_requirement_owner_cannot_bind_a_known_other_run_even_before_any_access():
    from scar.ir.execution.common import EvidencePoint
    from scar.ir.execution.coordinates import ExecutionRun
    from scar.ir.execution.ids import ResourceInstanceID, RunID
    from scar.ir.execution.resources import ImportedAt, InstanceTarget, RunRealm
    program, model = resource_execution_program(activations=1)
    other = ExecutionRun(RunID('other'), model.runs[0].source)
    point = EvidencePoint(other.id, None, other.source)
    resource = replace(model.resources[0], id=ResourceInstanceID('other-run-resource'),
                       realm=RunRealm(other.id), origin=ImportedAt(point))
    model = replace(model, runs=(*model.runs, other), resources=(*model.resources, resource),
        requirements=(replace(model.requirements[0], target=InstanceTarget(resource.id)),), accesses=())
    assert 'resource_realm_scope' in {row.code for row in validate(model, program).issues}


def test_malformed_same_family_external_graph_is_an_issue_not_an_exception_or_missing_graph():
    program, model, values = resource_execution_with_allocation()
    graph, = values.values()
    graph.allocations = []
    assert 'external_graph_invalid' in {row.code for row in validate(model, program, value_graphs=values).issues}

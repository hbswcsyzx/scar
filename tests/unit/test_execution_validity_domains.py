"""Original host/domain/causal associations, with no hand-authored proof flag."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OccurrencePhase
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validity_order import point_order
from tests.fixtures.execution_lifetime_graphs import host_lifetime_execution


def _validate(fixture):
    program, model, values, evidence, payloads, _ = fixture
    return validate(model, program, value_graphs=values, evidence_graphs=evidence,
                    semantic_graphs=fixture[-1].get('semantic_graphs'), artifact_bytes=payloads)


def _index(fixture):
    program, model, values, evidence, payloads, _ = fixture
    return ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence,
                          semantic_graphs=fixture[-1].get('semantic_graphs'), artifact_bytes=payloads)


def test_host_establishment_and_domain_retain_original_ports():
    fixture = host_lifetime_execution()
    report = _validate(fixture)
    assert report.valid, report.issues
    index = _index(fixture)
    details = fixture[-1]
    ctx = index._ctx
    assert ctx.resolved_establishments[details['established']]['rawprofile']['written_bytes'] == 16
    assert ctx.resolved_supports[details['support']]['status'] == 'MATCHED'
    assert not report.source_runtime_verified and not report.transformation_authorized


def test_establishment_cannot_substitute_host_before_for_after():
    program, model, values, evidence, payloads, details = host_lifetime_execution()
    row = model.established_productions[0]
    model = replace(model, established_productions=(replace(row,
        established=replace(row.established, phase=OccurrencePhase.BEFORE)),))
    report = _validate((program, model, values, evidence, payloads, details))
    assert any(issue.code == 'validity_establishment_point' for issue in report.issues)


def test_actual_host_order_and_reverse_are_distinct():
    fixture = host_lifetime_execution()
    ctx = _index(fixture)._ctx
    row = fixture[1].established_productions[0]
    end = fixture[1].content_reads[0].consumer.interval.end
    assert point_order(ctx, row.established, end, budget=ValidityBudget(1000))['status'] == 'CONDITIONAL'
    assert point_order(ctx, end, row.established, budget=ValidityBudget(1000))['status'] == 'CONTRADICTED'


def test_unknown_evidence_point_equality_is_not_clock_alignment():
    fixture = host_lifetime_execution()
    ctx = _index(fixture)._ctx
    point = fixture[1].activations[0].entry
    assert point_order(ctx, point, point, budget=ValidityBudget(1000))['status'] == 'UNRESOLVED'


@pytest.mark.parametrize('bad', ['absent', 'foreign'])
def test_host_native_result_has_independent_original_foreign_key(bad):
    from scar.ir.execution.ids import ValueOccurrenceID
    fixture = list(host_lifetime_execution())
    model, details = fixture[1], fixture[-1]
    result = ValueOccurrenceID('absent') if bad == 'absent' else details['data_value']
    fixture[1] = replace(model, established_productions=(replace(model.established_productions[0], result=result),))
    report = _validate(fixture)
    expected = 'validity_establishment_result' if bad == 'absent' else 'validity_establishment_result_owner'
    assert any(issue.code == expected for issue in report.issues)


def test_same_process_different_thread_is_not_the_host_domain():
    from scar.ir.execution.ids import HostThreadInstanceID
    from scar.ir.execution.validity import HostDomain
    fixture = list(host_lifetime_execution())
    model = fixture[1]
    other = replace(model.threads[0], id=HostThreadInstanceID('other-thread'), tid=999)
    support = model.contribution_supports[0]
    fixture[1] = replace(model, threads=(*model.threads, other), contribution_supports=(replace(support,
        visibility=replace(support.visibility, domain=HostDomain(other.id))),))
    assert any(issue.code == 'validity_host_domain' for issue in _validate(fixture).issues)


def test_unresolved_actual_thread_is_a_gap_instead_of_a_known_wrong_domain():
    from scar.ir.execution.coordinates import UnresolvedHostThread
    fixture = list(host_lifetime_execution())
    model = fixture[1]
    fixture[1] = replace(model, segments=(replace(model.segments[0],
        host_thread=UnresolvedHostThread('not captured', model.activations[0].entry)),))
    report = _validate(fixture)
    assert report.valid, report.issues
    assert _index(fixture)._ctx.resolved_supports[fixture[-1]['support']]['status'] == 'MISSING'


def test_unknown_completed_basis_is_not_successful_visibility():
    fixture = list(host_lifetime_execution())
    model = fixture[1]
    support = model.contribution_supports[0]
    fixture[1] = replace(model, contribution_supports=(replace(support,
        visibility=replace(support.visibility, basis=model.target_lifetime_events[0].stage)),))
    index = _index(fixture)
    assert index._ctx.resolved_supports[support.id]['status'] == 'MISSING'


@pytest.mark.parametrize('terminal', [False, True])
def test_pending_and_actual_queued_contributions_use_exact_consumer_start(terminal):
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = queue_lifetime_execution(terminal=terminal)
    index = _index(fixture)
    assert index._ctx.resolved_supports[fixture[-1]['support']]['status'] == 'MATCHED'
    assert not index.report.source_runtime_verified


def test_queue_prefix_end_without_fifo_does_not_support_start():
    from scar.ir.execution.ids import ResourceInstanceID
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = list(queue_lifetime_execution())
    model = fixture[1]
    fixture[1] = replace(model, queue_order_profiles=tuple(row for row in model.queue_order_profiles
                                                       if row.queue != ResourceInstanceID('order.qb')))
    assert _index(fixture)._ctx.resolved_supports[fixture[-1]['support']]['status'] == 'MISSING'


def test_terminal_actual_cannot_be_replaced_by_pending_request_selector():
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = list(queue_lifetime_execution(terminal=True))
    model = fixture[1]
    fixture[1] = replace(model, contribution_supports=(replace(model.contribution_supports[0], production=None),))
    assert any(issue.code == 'validity_support_terminal_actual' for issue in _validate(fixture).issues)


def test_deleting_outcome_and_actual_does_not_hide_an_independent_observed_result():
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = list(queue_lifetime_execution(terminal=True))
    model = fixture[1]
    fixture[1] = replace(model, outcomes=(), produced=(), contribution_supports=(
        replace(model.contribution_supports[0], production=None),))
    index = _index(fixture)
    assert index._ctx.resolved_supports[fixture[-1]['support']]['status'] == 'MISSING'
    assert any(gap.code == 'validity_unjoined_observed_result' for gap in index._ctx.gaps)
    assert not fixture[1].outcomes


def test_new_causal_declaration_is_assumption_without_native_interpretation():
    from scar.ir.execution.ids import OrderAssociationID
    from scar.ir.execution.order import WorkEnd
    from scar.ir.execution.validity import OrderAssociation
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = list(queue_lifetime_execution())
    model = fixture[1]
    before = WorkEnd(fixture[-1]['producer_ticket'])
    after = model.content_reads[0].anchor
    unknown = model.content_reads[0].basis
    row = OrderAssociation(OrderAssociationID('declared-cross-domain'), before, after, unknown,
                           model.submissions[0].protocol, model.runs[0].source)
    fixture[1] = replace(model, order_associations=(row,))
    ctx = _index(fixture)._ctx
    assert point_order(ctx, before, after, budget=ValidityBudget(4000))['status'] == 'ASSUMPTION'


def test_combined_fifo_event_and_new_declaration_cycle_is_rejected():
    from scar.ir.execution.ids import OrderAssociationID
    from scar.ir.execution.order import WorkEnd, WorkStart
    from scar.ir.execution.validity import OrderAssociation
    from tests.fixtures.execution_lifetime_graphs import queue_lifetime_execution
    fixture = list(queue_lifetime_execution())
    model = fixture[1]
    row = OrderAssociation(OrderAssociationID('reverse'), WorkStart(fixture[-1]['consumer_ticket']),
        WorkEnd(fixture[-1]['producer_ticket']), model.content_reads[0].basis,
        model.submissions[0].protocol, model.runs[0].source)
    fixture[1] = replace(model, order_associations=(row,))
    assert any(issue.code == 'validity_order_cycle' for issue in _validate(fixture).issues)


@pytest.mark.parametrize('changed_protocol', [False, True])
def test_endpoint_observation_matches_only_its_exact_protocol_not_any_flush(changed_protocol):
    from scar.ir.program.providers import ProviderFactReference
    from tests.fixtures.execution_lifetime_graphs import endpoint_lifetime_execution
    fixture = list(endpoint_lifetime_execution())
    if changed_protocol:
        model = fixture[1]
        row = model.contribution_supports[0]
        fixture[1] = replace(model, contribution_supports=(replace(row,
            visibility=replace(row.visibility, protocol=ProviderFactReference(model.snapshot.artifact,
                                                                             'arbitrary-flush'))),))
    ctx = _index(fixture)._ctx
    assert ctx.resolved_supports[fixture[-1]['support']]['status'] == 'MISSING'
    assert any(gap.code == 'content_selector_protocol_unverified' for gap in ctx.gaps)
    assert any(gap.code == 'validity_endpoint_interpreter_unsupported' for gap in ctx.gaps)


def test_result_literal_from_another_run_is_not_an_original_host_return():
    from scar.ir.execution.common import EvidencePoint
    from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance, RegionActivation, ValueOccurrence
    from scar.ir.execution.ids import ProcessInstanceID, RegionActivationID, RunID, ValueOccurrenceID
    from scar.ir.execution.snapshot import snapshot_for
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import DataValue, LiteralOrigin

    fixture = list(host_lifetime_execution())
    program, model = fixture[:2]
    run, process, activation = RunID('foreign'), ProcessInstanceID('foreign'), RegionActivationID('foreign')
    source = model.runs[0].source
    value = DataValue(ValueID('foreign.literal'), program.root, LiteralOrigin(16), 'builtins.int')
    occurrence = ValueOccurrence(ValueOccurrenceID('foreign.literal'), value.id, activation)
    program = replace(program, values=(*program.values, value))
    fixture[0] = program
    fixture[1] = replace(model, snapshot=snapshot_for(program), runs=(*model.runs, ExecutionRun(run, source)),
        processes=(*model.processes, ProcessInstance(process, run, 123, source)),
        activations=(*model.activations, RegionActivation(activation, program.root, process,
                                                       EvidencePoint(run, process, source))),
        values=(*model.values, occurrence))
    baseline = _validate(fixture)
    assert baseline.valid, baseline.issues
    fixture[1] = replace(fixture[1],
        established_productions=(replace(model.established_productions[0], result=occurrence.id),))
    assert any(issue.code == 'validity_establishment_result_run' for issue in _validate(fixture).issues)

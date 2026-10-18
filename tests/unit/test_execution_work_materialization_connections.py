"""Complete work sets agree with separately declared consumers/producers/borrows."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.execution.work import MaterializationRef
from scar.ir.v2.common import Completeness
from tests.fixtures.execution_content_graphs import content_connection_fixture
from tests.fixtures.execution_produced_graphs import produced_execution
from tests.fixtures.execution_work_graphs import ordinary_work_execution


def _case(kind):
    if kind == 'read':
        program, model, values, evidence, _ = content_connection_fixture(consumer='work')
        read = model.content_reads[0]
        ticket, mat = read.consumer.read.ticket, read.placement.materialization
    elif kind == 'write':
        program, model, values = produced_execution()
        evidence = {}
        write = model.writes[0]
        ticket, mat = write.writer.ticket, write.placement.materialization
    else:
        program, model, values = ordinary_work_execution(retained='materialization')
        evidence = {}
        retained = model.retentions[0]
        ticket, mat = retained.ticket, retained.target
        assert type(mat) is MaterializationRef
    return program, model, values, evidence, ticket, mat


def _set(model, ticket, coverage, mats):
    return replace(model, submissions=tuple(
        replace(row, materializations=mats, materializations_coverage=coverage)
        if row.id == ticket else row for row in model.submissions))


@pytest.mark.parametrize('kind', ('read', 'write', 'retained'))
def test_complete_work_set_cannot_omit_a_separately_declared_materialization(kind):
    program, model, values, evidence, ticket, _ = _case(kind)
    model = _set(model, ticket, Completeness.COMPLETE, ())
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert any(issue.code == 'work_materialization_unlisted' for issue in report.issues)
    with pytest.raises(ValueError, match='work_materialization_unlisted'):
        ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)


@pytest.mark.parametrize('kind', ('read', 'write', 'retained'))
@pytest.mark.parametrize('coverage', (Completeness.PARTIAL, Completeness.UNKNOWN))
def test_partial_or_unknown_set_omission_stays_a_specific_gap(kind, coverage):
    program, model, values, evidence, ticket, _ = _case(kind)
    model = _set(model, ticket, coverage, ())
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert report.valid, report.issues
    assert any(gap.code == 'work_materialization_unresolved' for gap in report.gaps)
    assert not report.source_runtime_verified and not report.transformation_authorized


@pytest.mark.parametrize('kind', ('read', 'write', 'retained'))
def test_matching_original_mat_in_complete_set_preserves_native_uncertainty(kind):
    program, model, values, evidence, ticket, mat = _case(kind)
    model = _set(model, ticket, Completeness.COMPLETE, (mat,))
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert report.valid, report.issues
    assert not any(issue.code == 'work_materialization_unlisted' for issue in report.issues)
    assert not any(gap.code == 'work_materialization_unresolved' for gap in report.gaps)
    assert any(gap.code == 'work_submission_protocol_unverified' for gap in report.gaps)


@pytest.mark.parametrize('kind', ('read', 'write', 'retained'))
def test_uri_alias_does_not_change_scoped_materialization_identity(kind):
    program, model, values, evidence, ticket, mat = _case(kind)
    alias = replace(mat, artifact=replace(mat.artifact, uri='memory:alternate-location'))
    assert alias != mat
    model = _set(model, ticket, Completeness.COMPLETE, (alias,))
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert report.valid, report.issues
    assert not any(gap.code == 'work_materialization_unresolved' for gap in report.gaps)


def test_materialization_from_another_ticket_cannot_fill_complete_consumer_set():
    program, model, values, evidence, _ = content_connection_fixture(consumer='work')
    read = model.content_reads[0]
    actual = read.consumer.read.ticket
    other = next(row.id for row in model.submissions if row.id != actual)
    model = _set(model, actual, Completeness.COMPLETE, ())
    model = _set(model, other, Completeness.COMPLETE, (read.placement.materialization,))
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert any(issue.code == 'work_materialization_unlisted' for issue in report.issues)


def test_missing_placement_stays_unknown_and_does_not_invent_a_materialization():
    from scar.ir.execution.common import Unresolved
    program, model, values, evidence, _ = content_connection_fixture(consumer='work')
    read = model.content_reads[0]
    model = replace(model, content_reads=(replace(read, placement=Unresolved(
        'content placement not captured', model.activations[0].entry)),))
    model = _set(model, read.consumer.read.ticket, Completeness.COMPLETE, ())
    report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
    assert report.valid, report.issues
    assert any(gap.code == 'content_placement_unresolved' for gap in report.gaps)
    assert not any(issue.code == 'work_materialization_unlisted' for issue in report.issues)

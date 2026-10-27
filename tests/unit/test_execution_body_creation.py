"""O08 distinguishes a contradictory failed Create from missing evidence."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_body_creation_graphs import body_creation_execution


def _old_valid(program, model, details):
    require_valid(program)
    report = validate(replace(model, body_drive_executions=(), body_activation_origins=()),
                      program, evidence_graphs=details['evidence_graphs'])
    assert report.valid, report.issues


def test_actual_create_raise_with_its_real_typed_landing_cannot_be_body_origin():
    program, model, details = body_creation_execution(mode='failed')
    _old_valid(program, model, details)
    item, = details['instances']
    transfer = next(row for row in model.transfers if row.operation == item['creation'])
    occurrence = next(row for row in model.operations if row.id == item['creation'])
    operation = next(row for row in program.operations if row.id == occurrence.operation)
    assert operation.terminator.successors[transfer.successor_index].kind is ExitKind.RAISE
    assert transfer.target == details['failed_visit']
    terminal = next(row for row in model.operations if row.id == details['failed_terminal'])
    assert next(row for row in program.operations if row.id == terminal.operation).terminator.kind is TerminatorKind.RAISE
    assert not model.call_activations
    assert not any(row.value.value == 'factory.created.arg.0' for row in model.values)
    report = validate(model, program, evidence_graphs=details['evidence_graphs'])
    assert 'body_creation_completion' in {issue.code for issue in report.issues}
    assert not {'transfer_block', 'value_origin', 'use_definition'} & {issue.code for issue in report.issues}


def test_plain_operation_cannot_be_claimed_as_an_actual_create():
    program, model, details = body_creation_execution(mode='plain')
    _old_valid(program, model, details)
    report = validate(model, program, evidence_graphs=details['evidence_graphs'])
    assert 'body_creation_kind' in {issue.code for issue in report.issues}


@pytest.mark.parametrize('mode,code', (('missing_transfer', 'body_creation_transfer_unobserved'),
                                     ('missing_handle', 'body_creation_handle_unobserved')))
def test_missing_normal_completion_evidence_keeps_capture_obligations_without_inventing_handle(mode, code):
    program, model, details = body_creation_execution(mode=mode)
    _old_valid(program, model, details)
    report = validate(model, program, evidence_graphs=details['evidence_graphs'])
    assert report.valid, report.issues
    item, = details['instances']
    index = ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])
    origin = index.body_activation_origin(item['activation'])
    assert origin['association'].creation == item['creation']
    assert origin['creation'].id == item['creation']
    assert origin['handle'] is None
    assert len(origin['captures']) == 6
    assert code in {gap.code for gap in origin['gaps']}
    start = index.drive_execution(item['drives'][0])
    assert start['input_count'] == 8
    assert start['instance']['creation_handle'] is None
    assert origin['source_runtime_verified'] is False and origin['value_identity_verified'] is False
    assert origin['transformation_authorized'] is False

"""C1's actual body terminal chooses completion versus exception consumers."""
from dataclasses import replace

import pytest

from scar.ir.program.control import LanguageCompletionKind
from scar.ir.program.model import ExitKind, OperationResult, TerminatorKind
from scar.ir.program.protocols import OutcomeAdapter, OutcomeAdapterRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_cleanup_final_graphs import await_cleanup_final_program


BUDGET = 1048576


def _index(program):
    require_valid(replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))
    require_valid(program)
    return ProgramIndex(program)


def _outcome(report, details):
    result, = tuple(row for row in report['outcomes']
        if row['drive_outcome'] == details['drive_outcome']
        and row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation'])
    return result


@pytest.mark.parametrize(('body_raised', 'depth'), ((False, 1), (False, 2), (True, 1)),
                         ids=('resume-return', 'resume-return-nested-extractor', 'replace-body-raise'))
def test_two_real_cleanup_cuts_end_in_the_correct_await_source_and_consumer(body_raised, depth):
    program, details = await_cleanup_final_program(body_raised=body_raised, depth=depth)
    index = _index(program)
    assert len(details['cuts']) == 2
    assert details['drivers'][0]['outcome_source'] == details['cuts'][0]
    assert details['drivers'][1]['drive'].target.suspend == details['cuts'][0]
    assert details['drivers'][1]['outcome_source'] == details['cuts'][1]
    assert details['drivers'][2]['drive'].target.suspend == details['cuts'][1]
    assert details['drivers'][2]['outcome_source'] == details['body_terminal'].id
    assert details['body_terminal'].terminator.kind is (
        TerminatorKind.RAISE if body_raised else TerminatorKind.RETURN)
    assert program.cleanup_enters
    assert program.cleanup_replacements if body_raised else program.cleanup_resumes

    ports = {port.id: port for port in program.control_ports}
    wanted = LanguageCompletionKind.RAISE if body_raised else LanguageCompletionKind.RETURN
    definition, = tuple(row for row in program.pending_completions if ports[row.port].kind is wanted)
    value = next(value for value in program.values if value.id == definition.value)
    assert type(value.origin) is OperationResult
    payload_source = OwnedUse(value.origin.operation, definition.payload)
    terminal = details['body_terminal']
    copied = index.source_binding(payload_source, OwnedUse(terminal.id, terminal.terminator.values[0]), budget=BUDGET)
    assert copied['match'] is True

    report = index.protocol_obligations(details['acquisition_scope'], budget=BUDGET)['connections']['families']['await']
    outcome = _outcome(report, details)
    assert outcome['kind'] == ('EXCEPTION' if body_raised else 'RETURN_COMPLETION')
    consumers = tuple(row for row in outcome['consumers'] if row['actual'] == details['extract_input'])
    assert consumers and all(row['binding']['match'] is True for row in consumers)
    if body_raised:
        assert outcome['conversion_legs'] == ()
        assert all(row['requires_final_extraction'] is False and row['final_rows'] == () for row in consumers)
        assert not any(type(row.contract) is OutcomeAdapter
            and row.contract.rule is OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION
            for row in program.protocol_operations)
        assert details['final'].terminator.kind is TerminatorKind.RAISE
        assert details['packet_use'].operation == details['final'].id
        assert details['packet_use'].use == details['final'].terminator.values[0]
        assert index.source_binding(details['root_source'], details['packet_use'], budget=BUDGET)['match'] is True
        # The terminal consumes this selected CALL's own current state slots,
        # not a prior pending/cleanup snapshot merely sharing the location.
        from scar.ir.program.model import CompletionResult, InvokeLiteralResult
        from scar.ir.program.structured import ControlEdgeReference

        call = details['drivers'][-1]['caller_call']
        selected = details['drivers'][-1]['selected_call_edge']
        assert call.terminator.successors[selected].kind is ExitKind.RAISE
        for slot, actual in enumerate(details['state_uses'], start=1):
            source = InvokeLiteralResult(ControlEdgeReference(call.id, selected), CompletionResult(slot))
            assert index.source_binding(source, actual, budget=BUDGET)['match'] is True
    else:
        assert outcome['conversion_legs']
        completed = tuple(row for row in consumers if row['requires_final_extraction'] is True)
        assert completed
        implementation = completed[0]['implementation']
        assert len(implementation['frames']) == depth
        assert len(implementation['outputs']) == sum(len(signature.types)
            for signature in details['extract'].completions)
        assert all(output['enumeration_complete'] and output['terminals']
            and all(terminal['match'] is True for terminal in output['terminals'])
            for output in implementation['outputs'])
    for flag in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[flag] is False


def test_budget_one_retains_original_drive_successor_denominator_and_cursor():
    program, details = await_cleanup_final_program()
    index = _index(program)
    operations = {operation.id: operation for operation in program.operations}
    successor_count = sum(len(operations[drive.operation].terminator.successors)
                          for drive in program.body_drives)
    report = index.protocol_obligations(details['acquisition_scope'], budget=1)['connections']['families']['await']
    inventory = report['outcome_inventory']
    assert inventory['drive_successors_total'] == successor_count
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None
    assert inventory['cursor'] is not None or report['cursor'] is not None

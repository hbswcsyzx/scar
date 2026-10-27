"""Native same-B terminal history, ordinary state contents and gate snapshots.

The selected paths are supplied captures. These tests do not identify Python
objects at runtime or infer phase from an observed predicate's True edge.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue
from scar.ir.program.protocols import BodyStatePredicateRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_coroutine_closed_graphs import (
    coroutine_callback_execution, coroutine_closed_execution,
)


_BUDGET = 250000
_FLAGS = ('native_phase_verified', 'source_runtime_verified',
          'runtime_identity_verified', 'value_identity_verified',
          'transformation_authorized')


def _index(program, model):
    require_valid(program)
    checked = validate_execution(model, program)
    assert checked.valid, checked.issues
    return ExecutionIndex(model, program)


def _flags(view):
    assert all(view[name] is False for name in _FLAGS)


def _candidate(view, details):
    driver, = details['drivers']
    rows = tuple(row for row in view['terminal_candidates']
        if row['commit'].outcome.drive == driver['drive'].operation
        and row['commit'].outcome.source == driver['outcome_source'])
    assert len(rows) == 1
    return rows[0]


def _value(model, operation, use):
    return next(value for value in model.values
        if value.id == next(row.value for row in model.uses
                            if row.operation == operation and row.use == use))


def _own_slot(program, model, occurrence, slot):
    definition = next(row for row in model.operations if row.id == occurrence)
    operation = next(row for row in program.operations if row.id == definition.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    edge = operation.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments, strict=True)
                    if type(actual) is CompletionResult and actual.index == slot)
    return next(row for row in model.values if row.origin == transfer.target and row.value == formal)


@pytest.mark.parametrize(('kind', 'extractor_kind', 'reject_kind'), (
    (RawRequestKind.NEXT, ExitKind.NORMAL, ExitKind.NORMAL),
    (RawRequestKind.SEND, ExitKind.RAISE, ExitKind.RAISE),
), ids=('next-after-extract-normal', 'send-none-after-extract-raise'))
def test_completed_native_same_body_reuse_has_history_and_its_own_rejection_packet(
        kind, extractor_kind, reject_kind):
    program, model, captured = coroutine_closed_execution(
        kind=kind, extractor_kind=extractor_kind, reject_kind=reject_kind)
    index = _index(program, model)
    details, = (captured['static'],)
    example, = captured['instances']
    closed = details['closed']
    assert program.resumable_bodies[0].kind is ResumableKind.COROUTINE
    assert len(program.resumable_creates) == len(model.body_activation_origins) == 1
    assert len(program.body_drives) == len(model.body_drive_executions) == 1
    retry_ids = {identity for block in closed['region'].blocks for identity in block.operations}
    assert not any(row.operation in retry_ids for row in program.body_drives)
    assert not any(row.operation in retry_ids for row in program.body_outcome_commits)
    assert not program.no_body_finishes
    assert example['body_origin'].creation == example['creation']

    view = index.body_state_history(captured['read'], budget=_BUDGET)
    candidate = _candidate(view, details)
    assert view['read'].id == captured['read']
    assert view['predicate'].contract.subject.rule is BodyStatePredicateRule.IS_CLOSED
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert candidate['source'].operation == candidate['commit'].operation
    assert candidate['drive'].id == model.body_drive_executions[0].drive
    assert candidate['association'] == model.body_drive_executions[0]
    assert candidate['post_established'] is True
    assert candidate['subject_binding']['match'] is True
    assert candidate['source_chain']['supported'] is True
    assert candidate['read_chain']['supported'] is True
    assert candidate['source_chain']['root'] == candidate['read_chain']['root'] == example['caller_activation']
    assert candidate['terminal_route']
    assert candidate['terminal_scope'].applicability.value == 'UNKNOWN'
    assert view['read_scope'].applicability.value == 'UNKNOWN'
    assert candidate['terminal_scope'].interface.body == view['read_scope'].interface.body == details['body'].id
    assert candidate['terminal_scope'].rule == view['read_scope'].rule
    assert candidate['expected_bool'] is view['expected_bool'] is True
    assert view['observed_branch'] is True
    # Fixed native/no-reset terminal history survives these real opaque calls.
    # That fact does not prove their ordinary state contents stayed unchanged.
    preservation = candidate['content_preservation']
    assert preservation['preserved'] is None
    assert preservation['blockers']
    blockers = {row['definition'].id for row in preservation['blockers'] if row.get('definition') is not None}
    assert details['extract'].id in blockers
    _flags(view)

    retry_scope = example['extra_scopes']['retry']
    retry_occurrences = retry_scope[2]
    helper = next(row for row in program.operations if row.id == closed['helper'])
    helper_occurrence = retry_occurrences[helper.id]
    selected_transfer, = tuple(row for row in model.transfers if row.operation == helper_occurrence)
    assert helper.terminator.successors[selected_transfer.successor_index].kind is reject_kind
    selected_terminal = next(row for row in program.operations if row.id == closed['selected_terminal'])
    terminal_occurrence = retry_occurrences[selected_terminal.id]
    signature = next(row for row in helper.completions if row.kind is reject_kind)
    assert len(selected_terminal.terminator.values) == len(signature.types)
    for slot, use in enumerate(selected_terminal.terminator.values):
        assert _value(model, terminal_occurrence, use).id == _own_slot(
            program, model, helper_occurrence, slot).id
    # The root caller receives every selected retry fullslot, with no old
    # body return payload or old StopIteration packet used as the new error.
    rejection = details['endings'][extractor_kind]
    actual_call = example['caller_operations'][rejection['call'].id]
    final_occurrence = example['caller_operations'][rejection['terminal'].id]
    for slot, use in enumerate(rejection['terminal'].terminator.values):
        assert _value(model, final_occurrence, use).id == _own_slot(program, model, actual_call, slot).id
    raw = next(row for row in program.raw_driver_requests if row.value == rejection['raw'].id)
    assert raw.kind is kind
    assert len(raw.operands) == (1 if kind is RawRequestKind.SEND else 0)
    if kind is RawRequestKind.SEND:
        operand = next(row for row in rejection['raw_operation'].uses if row.id == raw.operands[0])
        literal = next(row for row in program.values if row.id == operand.value)
        assert literal.origin.value is None
        assert literal.targets == ()
    # Every original extraction completion still has its actual observer and
    # original host receipt; adding the second attempt erased no consumer.
    for row in details['final_rows']:
        receipt = next(item for item in program.protocol_result_consumers
                       if item.site.operation == row.operation and item.site.slot == row.slot
                       and item.site.scope == row.scope)
        observer = details['endings'][details['extract'].terminator.successors[row.slot].kind]['observer']
        assert OwnedUse(observer.id, observer.uses[0].id) in receipt.targets


def test_missing_retry_call_does_not_borrow_the_first_drive_or_another_call_for_closed_history():
    program, model, captured = coroutine_closed_execution(missing_retry_call=True)
    index = _index(program, model)
    view = index.body_state_history(captured['read'], budget=_BUDGET)
    candidate = _candidate(view, captured['static'])
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert candidate['source'].operation == candidate['commit'].operation
    assert candidate['read_chain']['supported'] is False
    assert 'body_state_call_association_missing' in candidate['gaps']
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert view['observed_branch'] is True
    assert len(model.body_drive_executions) == 1
    _flags(view)


def test_missing_source_gate_transfer_keeps_terminal_inventory_but_not_a_complete_call_chain():
    program, model, captured = coroutine_closed_execution()
    example, = captured['instances']
    driver, = captured['static']['drivers']
    gate, = tuple(row for row in program.final_body_gates
                  if row.drive == driver['drive'].operation)
    gate_occurrence = example['driver_scopes'][0][2][gate.operation]
    removed, = tuple(row for row in model.transfers if row.operation == gate_occurrence)
    model = replace(model, transfers=tuple(row for row in model.transfers if row != removed))
    index = _index(program, model)
    source_call, = example['call_activations']
    call_view = index.call_activation(source_call.id)
    assert 'call_path_unobserved' in {row.code for row in call_view['gaps']}
    view = index.body_state_history(captured['read'], budget=_BUDGET)
    candidate = _candidate(view, captured['static'])
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert candidate['source'].operation == candidate['commit'].operation
    assert candidate['source_chain']['supported'] is False
    assert 'call_path_unobserved' in {
        getattr(row, 'code', row) for row in candidate['source_chain']['gaps']}
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert view['observed_branch'] is True
    _flags(view)


@pytest.mark.parametrize('callback_kind', (ExitKind.NORMAL, ExitKind.RAISE),
                         ids=('callback-normal-latest-gate', 'callback-raise-own-packet'))
def test_native_historical_phase_bool_does_not_supply_the_current_gate_snapshot(callback_kind):
    program, model, captured = coroutine_callback_execution(callback_kind=callback_kind)
    index = _index(program, model)
    details = captured['static']
    example, = captured['instances']
    guard = details['callback']['guard']
    scope = guard['row'].scope
    report = ProgramIndex(program).protocol_obligations(scope, budget=_BUDGET)
    predicate, = tuple(row['predicate'] for item in report['scopes'] if item['scope'].id == scope
        for clause in item['obligations'] for row in clause['rows']
        if row.get('predicate') is not None and row['predicate']['predicate'].operation == guard['predicate'])
    assert predicate['bool_must_copy'] is True
    frontier, = tuple(row for row in predicate['control_routes']['frontiers']
                      if row['kind'] == 'FINAL_GATE')
    assert frontier['read_snapshot_current'] is False
    assert frontier['target_compatible_at_snapshot'] is None
    assert 'admission_gate_support_changed_or_unresolved' in predicate['gaps']
    assert frontier['native_gate_verified'] is False
    history = index.body_state_history(captured['read'], budget=_BUDGET)
    assert history['observed_branch'] is True
    assert history['expected_bool'] is None  # Created content is not a terminal-F seed.
    _flags(history)
    driver_scope = example['driver_scopes'][0]
    callback = details['callback']['operation']
    occurrence = driver_scope[2][callback.id]
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    assert callback.terminator.successors[transfer.successor_index].kind is callback_kind
    if callback_kind is ExitKind.NORMAL:
        assert len(model.body_drive_executions) == 1
        assert len(model.body_activation_origins) == 1
    else:
        assert model.body_drive_executions == model.body_activation_origins == ()
        terminal = details['callback']['raise_terminal']
        actual_terminal = driver_scope[2][terminal.id]
        for slot, use in enumerate(terminal.terminator.values):
            assert _value(model, actual_terminal, use).id == _own_slot(program, model, occurrence, slot).id
        assert not any(row.operation == details['drivers'][0]['drive'].operation for row in model.operations)

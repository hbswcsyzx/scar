"""Exact BodyRaise, synchronous cleanup and caller evidence stay separate.

Two captures of the same static sites must not supply one another's missing
Uses, calls or cleanup transfers.  All evidence remains supplied IR.
"""
import pytest

from scar.ir.execution.coordinates import InitialEntry, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.model import CompletionResult, ExitKind, ValueKind
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_raise_cleanup_graphs import await_raise_cleanup_execution
from tests.fixtures.execution_await_raise_sources_graphs import await_raise_source_execution


BUDGET = 1_048_576


def _index(program, model, details):
    require_valid(program)
    result = validate(model, program, evidence_graphs=details.get('evidence_graphs'))
    assert result.valid, result.issues
    return ExecutionIndex(model, program, evidence_graphs=details.get('evidence_graphs'))


def _report(index, details, *, budget=BUDGET):
    return index.await_body_links(details['static']['acquisition_scope'], budget=budget)


def _row(report, details):
    row, = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['advance_operation'])
    assert row['definition']['kind'] == 'EXCEPTION'
    assert row['definition']['conversion_legs'] == ()
    return row


def _occurrence(row, example):
    occurrence, = tuple(row for row in row['occurrences']
        if row['advance'] is not None and row['advance'].id == example['advance'])
    assert occurrence['conversion_legs'] == ()
    return occurrence


def _terminal(occurrence, static):
    expected = {HostTerminal(operation.id) for operation in static['raise_cleanup']['terminals']}
    terminal, = tuple(row for row in occurrence['terminals']
        if row['definition']['terminal'] in expected)
    return terminal


def _flags(view):
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert view[name] is False


def _drive_payload(program, model, example):
    """Independently resolve this actual BodyDriveResult(0), not a type match."""
    operations = {operation.id: operation for operation in program.operations}
    occurrence = next(row for row in model.operations if row.id == example['body_drives'][-1].drive)
    operation = operations[occurrence.operation]
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence.id)
    edge = operation.terminator.successors[transfer.successor_index]
    body = next(row for row in model.operations if row.id == example['body_outcome'])
    assert edge.source == body.operation
    landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, landing.arguments)
        if type(actual) is BodyDriveResult and actual.index == 0)
    value, = tuple(row for row in model.values if row.origin == transfer.target and row.value == formal)
    return value


def _current_states(program, model, terminal, example, static):
    uses = {(row.operation, row.use): row for row in model.uses}
    canonical = {row.id: row for row in program.values}
    expected_sources = {uses[(example['driver_terminal'], actual.use)].value
        for actual in static['raise_cleanup']['state_uses']}
    assert expected_sources
    assert {row['source'].id for row in terminal['states']} == expected_sources
    advance = next(row for row in model.operations if row.id == example['advance'])
    parent = next(row for row in program.operations if row.id == advance.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == advance.id)
    edge = parent.terminator.successors[transfer.successor_index]
    landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    signature, = tuple(row for row in parent.completions if row.kind is edge.kind)
    slots = {slot: type_.location for slot, type_ in enumerate(signature.types)
             if type_.kind is ValueKind.STATE}
    assert len(terminal['states']) == len(slots) == len(expected_sources)
    for row in terminal['states']:
        slot = row['definition']['slot']
        assert canonical[row['source'].value].location == slots[slot]
        formal, = tuple(formal for actual, formal in zip(edge.arguments, landing.arguments)
            if type(actual) is CompletionResult and actual.index == slot)
        target, = tuple(value for value in model.values
            if value.origin == transfer.target and value.value == formal)
        assert row['target'] == target
        assert row['binding']['match'] is True


def _body_and_calls(index, program, model, details, example, occurrence, cuts):
    static = details['static']
    assert occurrence['selected'] is True
    assert occurrence['drive'].id == example['body_drives'][-1].drive
    assert occurrence['body_outcome'].id == example['body_outcome']
    assert occurrence['body_outcome'].operation == static['body_terminal'].id
    assert len(example['body_segments']) == cuts + 1
    segments = {row.id: row for row in model.segments}
    assert type(segments[example['body_segments'][0]].ingress) is InitialEntry
    for ordinal in range(1, cuts + 1):
        ingress = segments[example['body_segments'][ordinal]].ingress
        assert type(ingress) is ResumeIngress
        assert ingress.suspension == example['body_drives'][ordinal - 1].outcome
        assert any(row.operation == ingress.suspension and row.target == example['body_entries'][ordinal]
                   for row in model.transfers)
    origin = index.body_activation_origin(example['body_activation'], budget=BUDGET)
    assert origin['creation'].id == example['body_origin'].creation == example['creation']
    assert occurrence['call_chain']
    assert occurrence['call_chain'][-1]['association'].completion == example['driver_terminal']
    assert occurrence['call_chain'][-1]['association'].activation == example['driver_activation']
    assert occurrence['call_chain'][0]['association'].caller == example['advance']


def _delivered(index, program, model, details, example, occurrence, *, replaced, kind):
    static = details['static']
    terminal = _terminal(occurrence, static)
    assert terminal['selected'] is True
    assert terminal['operation'].id == example['driver_terminal']
    assert terminal['packet_use'].operation == example['driver_terminal']
    assert terminal['packet_use'].use == static['raise_cleanup']['payload_uses'][0].use
    assert terminal['definition']['current_source'] == static['raise_cleanup']['current_source']
    assert terminal['definition']['root_source'] == static['raise_cleanup']['root_source']
    assert terminal['binding']['match'] is True
    assert terminal['delivery_binding']['match'] is True
    assert terminal['current_binding']['match'] is True
    assert terminal['current_binding']['target_value'] == terminal['packet_value']
    root = _drive_payload(program, model, example)
    body_use, = tuple(use for use in model.uses
        if use.operation == example['body_outcome']
        and use.use == static['body_terminal'].terminator.values[0])
    body_value, = tuple(value for value in model.values if value.id == body_use.value)
    assert terminal['body_binding']['source_value'] == body_value
    assert terminal['body_binding']['target_value'] == root
    assert terminal['body_binding']['match'] is True
    assert terminal['root_binding']['source_value'] == root
    assert terminal['root_binding']['target_value'] == terminal['packet_value']
    if replaced:
        assert terminal['root_binding']['match'] is not True
    else:
        assert terminal['root_binding']['match'] is True
        assert terminal['current_value'] == root
    _current_states(program, model, terminal, example, static)
    advance = next(row for row in model.operations if row.id == example['advance'])
    parent = next(row for row in program.operations if row.id == advance.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == advance.id)
    assert parent.terminator.successors[transfer.successor_index].kind is kind
    consumers = tuple(row for row in terminal['consumers']
        if row['operation'] is not None and row['operation'].id == example['final'])
    assert consumers
    for consumer in consumers:
        assert consumer['definition']['requires_final_extraction'] is False
        assert consumer['binding']['match'] is True
        assert consumer['advance_value'] == terminal['parent_value']
        assert consumer['use'].operation == example['final']
    assert all(row['definition']['requires_final_extraction'] is False
               for row in occurrence['consumers'])
    assert example['extraction'] is None and example['implementation_frames'] == ()
    return terminal


@pytest.mark.parametrize(('mode', 'kind'), (
    ('preserve', ExitKind.RAISE), ('replace_raise', ExitKind.RAISE),
    ('replace_return', ExitKind.NORMAL),
), ids=('preserved-packet', 'new-raise', 'new-return'))
def test_two_actual_body_raises_cross_their_own_sync_cleanup_and_exact_parent_completion(mode, kind):
    program, model, details = await_raise_cleanup_execution(mode=mode, instances=2)
    index = _index(program, model, details)
    report = _report(index, details)
    row = _row(report, details)
    assert row['occurrence_count'] == len(row['occurrences']) == 2
    for example in details['instances']:
        occurrence = _occurrence(row, example)
        _body_and_calls(index, program, model, details, example, occurrence, 2)
        _delivered(index, program, model, details, example, occurrence,
            replaced=mode != 'preserve', kind=kind)
    _flags(report)


@pytest.mark.parametrize(('source_kind', 'zero_cut', 'mode'), (
    ('general', True, 'preserve'), ('general', False, 'replace_raise'),
    ('wrapper', True, 'replace_raise'), ('wrapper', False, 'preserve'),
), ids=('general-zero-preserve', 'general-two-new-raise',
        'wrapper-zero-new-raise', 'wrapper-two-preserve'))
def test_general_or_distinct_wrapper_source_reaches_the_actual_body_raise_and_current_consumer(
        source_kind, zero_cut, mode):
    program, model, details = await_raise_source_execution(source_kind=source_kind,
        zero_cut=zero_cut, cleanup_mode=mode, instances=2)
    index = _index(program, model, details)
    report = _report(index, details)
    row = _row(report, details)
    for example in details['instances']:
        occurrence = _occurrence(row, example)
        assert occurrence['matched_sources']
        _body_and_calls(index, program, model, details, example, occurrence, 0 if zero_cut else 2)
        _delivered(index, program, model, details, example, occurrence,
            replaced=mode != 'preserve', kind=ExitKind.RAISE)
    _flags(report)


@pytest.mark.parametrize('missing', ('missing_payload_use', 'missing_dispatch', 'missing_driver_call'))
def test_missing_instance_zero_cleanup_or_call_evidence_never_uses_the_complete_sibling(missing):
    program, model, details = await_raise_cleanup_execution(instances=2, **{missing: 0})
    index = _index(program, model, details)
    report = _report(index, details)
    row = _row(report, details)
    assert row['occurrence_count'] == len(row['occurrences']) == 2
    first, sibling = details['instances']
    partial, complete = _occurrence(row, first), _occurrence(row, sibling)
    assert partial['status'] not in ('DECLARED', 'NOT_APPLICABLE')
    assert partial['gaps']
    assert not any(terminal['binding']['match'] is True for terminal in partial['terminals'])
    terminal = _delivered(index, program, model, details, sibling, complete,
        replaced=False, kind=ExitKind.RAISE)
    assert terminal['operation'].id != first['driver_terminal']
    _flags(report)


def test_actual_opaque_boundary_after_cleanup_cannot_be_a_complete_body_raise_delivery():
    program, model, details = await_raise_cleanup_execution(mode='opaque', instances=2)
    index = _index(program, model, details)
    report = _report(index, details)
    row = _row(report, details)
    for example in details['instances']:
        occurrence = _occurrence(row, example)
        assert occurrence['status'] == 'PARTIAL'
        assert occurrence['gaps']
        assert not any(terminal['binding']['match'] is True for terminal in occurrence['terminals'])
        assert all(consumer['definition']['requires_final_extraction'] is False
                   for consumer in occurrence['consumers'])
    _flags(report)


def test_budget_one_keeps_static_exception_and_both_parent_capture_anchors():
    program, model, details = await_raise_cleanup_execution(instances=2)
    index = _index(program, model, details)
    complete = _report(index, details)
    limited = _report(index, details, budget=1)
    assert {row['definition']['key'] for row in limited['outcomes']} == {
        row['definition']['key'] for row in complete['outcomes']}
    row = _row(limited, details)
    assert row['occurrence_count'] == 2
    assert all(occurrence['status'] != 'DECLARED' for occurrence in row['occurrences'])
    inventory = limited['outcome_inventory']
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['cursor'] is not None or limited['cursor'] is not None
    assert limited['budget']['truncated'] is True
    _flags(limited)

"""One helper failure, one selected acquisition R, one caller continuation.

Neither a sibling capture nor a forwarded landing value proves ownership of
this acquisition result. Current state captures do not assert old-state copy.
"""
import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_failure_cleanup_graphs import await_failure_cleanup_execution


BUDGET = 1_048_576
STAGES = {
    'lookup_raise': 'LOOKUP', 'method_call_raise': 'METHOD_CALL',
    'qualification_reject': 'QUALIFICATION_REJECT',
    'wrapper_constructor_raise': 'WRAPPER_CONSTRUCTION_RAISE',
}


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _report(index, details, *, budget=BUDGET):
    return index.await_body_links(details['static']['failure_cleanup']['source_ref'].scope,
        budget=budget)


def _row(report, details, *, own=False):
    definition = details['static']['failure_cleanup']
    kind = ('WRAPPER_CONSTRUCTION_RAISE' if definition['stage'] == 'wrapper_constructor_raise'
        else 'ACQUISITION_RAISE') if own else STAGES[definition['stage']]
    row, = tuple(row for row in report['failure_paths']
        if row['definition']['source_operation'] == definition['source_operation'].id
        and getattr(row['definition']['stage'], 'value', row['definition']['stage']) == kind)
    assert row['definition']['source_result'] == definition['source_result']
    assert row['definition']['source_edge'] == definition['source_edge']
    return row


def _occurrence(row, example):
    occurrence, = tuple(occurrence for occurrence in row['occurrences']
        if occurrence['source'].id == example['source'])
    return occurrence


def _flags(view):
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert view[name] is False


def _source_value(program, model, definition, example):
    """Resolve the selected produced slot, deliberately past a forwarded Ref."""
    source = next(row for row in model.operations if row.id == example['source'])
    transfer, = tuple(row for row in model.transfers if row.operation == source.id)
    assert transfer.successor_index == definition['source_edge'].successor_index
    operation = next(row for row in program.operations if row.id == source.operation)
    edge = operation.terminator.successors[transfer.successor_index]
    assert edge.kind is ExitKind.RAISE
    landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    position, = tuple(position for position, argument in enumerate(edge.arguments)
        if type(argument) is CompletionResult and argument.index == definition['source_result'].result.index)
    assert position == 1
    root, = tuple(row for row in model.values
        if row.origin == transfer.target and row.value == landing.arguments[position])
    assert root == example['root_value']
    assert example['forwarded_value'].origin == root.origin
    assert example['forwarded_value'].value == landing.arguments[0]
    assert example['forwarded_value'].id != root.id
    return root


def _helper(model, occurrence, definition, example):
    if definition['helper_terminal'] is None:
        assert occurrence['terminals'] == ()
        assert example['helper_call'] is None
        return
    assert occurrence['selected'] is True
    assert occurrence['stage'].id == example['stage']
    assert tuple(link['association'] for link in occurrence['call_chain']) == (example['helper_call'],)
    assert example['helper_call'].caller == example['source']
    assert example['helper_call'].activation == example['helper_activation']
    assert example['helper_call'].completion == example['helper_terminal']
    terminal, = tuple(row for row in occurrence['terminals']
        if row['definition']['terminal'] == HostTerminal(definition['helper_terminal'].id))
    assert terminal['operation'].id == example['helper_terminal']
    assert terminal['packet_use'] == example['helper_terminal_use']
    assert terminal['packet_value'] == example['helper_terminal_value']
    assert terminal['parent_value'] == example['root_value']
    assert terminal['binding']['match'] is True
    assert terminal['binding']['source_value'] == example['helper_terminal_value']
    assert terminal['binding']['target_value'] == example['root_value']
    assert {row['source'].id for row in terminal['states']} == {
        row.id for row in example['helper_state_values']}
    assert {row['target'].id for row in terminal['states']} == {
        row.id for row in example['source_state_values']}
    assert all(row['binding']['match'] is True for row in terminal['states'])
    if definition['stage'] == 'qualification_reject':
        assert terminal['stage_binding'] is None
        assert terminal['stage_source_value'] is None
        packet, = tuple(row for row in terminal['stage_packets']
            if row['operation'] is not None and row['operation'].id == example['packet_constructor'])
        assert packet['selected'] is True
        assert packet['value'] == example['stage_source_value']
        assert packet['exception_use'] == example['packet_constructor_uses'][0]
        assert packet['traceback_use'] == example['packet_constructor_uses'][1]
        values = {row.id: row for row in model.values}
        assert packet['exception_value'] == values[packet['exception_use'].value]
        assert packet['traceback_value'] == values[packet['traceback_use'].value]
        assert packet['binding']['match'] is True
        assert packet['binding']['source_value'] == packet['value']
        assert packet['binding']['target_value'] == example['helper_terminal_value']
        assert terminal['definition']['control_anchor'] == definition['reject_edge']
    else:
        binding = terminal['stage_binding']
        assert binding['source_value'] == example['stage_source_value']
        assert binding['target_value'] == example['helper_terminal_value']
        assert binding['match'] is True


def _caller(program, model, occurrence, definition, example):
    assert occurrence['selected'] is True
    continuation, = occurrence['caller_continuations']
    root = _source_value(program, model, definition, example)
    assert continuation['source'] == root
    assert continuation['anchor'].id == example['source']
    assert continuation['drives'] == ()
    assert len(continuation['segments']) == 1
    assert continuation['segments'][0].activation == example['caller_activation']
    receipt, = tuple(row for row in occurrence['caller_terminals']
        if row['operation'] is not None and row['operation'].id == example['caller_terminal'])
    assert receipt['terminal'] == definition['consumer']
    assert receipt['actual'] == definition['consumer_payload_use']
    assert receipt['root_source'] == root
    assert receipt['use'] == example['current_payload_use']
    assert receipt['value'] == example['current_payload_value']
    assert receipt['binding']['match'] is True
    assert receipt['binding']['target_value'] == example['current_payload_value']
    assert receipt['root_binding']['source_value'] == root
    if definition['mode'] == 'preserve':
        assert receipt['root_binding']['match'] is True
    else:
        # Distinct producers need not prove distinct native object identity.
        assert receipt['root_binding']['match'] is not True
    assert receipt['requires_final_extraction'] is False
    assert receipt['crossed_suspend'] is False
    assert receipt['role'] == ('reference' if definition['mode'] == 'replace_return' else 'packet')
    actual_uses = {use.use: use for use in example['current_state_uses']}
    actual_values = {value.id: value for value in model.values}
    assert len(receipt['state_uses']) == len(actual_uses)
    for state in receipt['state_uses']:
        canonical = state['definition']
        use = actual_uses[canonical['actual'].use]
        assert state['use'] == use
        assert state['value'] == actual_values[use.value]
        assert state['value'].value == canonical['value'].id
        assert canonical['value'].location == canonical['location']
        assert state['capture_match'] is True
    assert example['pending_payload_occurrence'].operation == example['pending_constructor']
    assert example['pending_payload_occurrence'].value == root.id
    assert example['caller_terminal'] != example['helper_terminal']
    _flags(continuation)
    return receipt


@pytest.mark.parametrize('mode', ('preserve', 'replace_raise', 'replace_return'))
def test_two_qualification_failures_have_separate_helper_get_raise_and_current_caller_evidence(mode):
    program, model, details = await_failure_cleanup_execution(mode=mode, instances=2)
    index = _index(program, model)
    report = _report(index, details)
    definition = details['static']['failure_cleanup']
    selected, own = _row(report, details), _row(report, details, own=True)
    assert selected['occurrence_count'] == own['occurrence_count'] == 2
    assert model.body_drive_executions == () and model.body_activation_origins == ()
    for example in details['instances']:
        helper = _occurrence(selected, example)
        _helper(model, helper, definition, example)
        _caller(program, model, helper, definition, example)
        local = _occurrence(own, example)
        assert local['terminals'] == ()
        _caller(program, model, local, definition, example)
    _flags(report)


@pytest.mark.parametrize(('stage', 'mode'), (
    ('lookup_raise', 'preserve'), ('lookup_raise', 'replace_raise'),
    ('method_call_raise', 'preserve'), ('method_call_raise', 'replace_return'),
    ('wrapper_constructor_raise', 'preserve'), ('wrapper_constructor_raise', 'replace_return'),
), ids=('lookup-preserve', 'lookup-new-raise', 'call-preserve', 'call-new-return',
        'constructor-preserve', 'constructor-new-return'))
def test_other_failure_sources_use_their_own_raise_and_current_caller_capture(stage, mode):
    program, model, details = await_failure_cleanup_execution(stage=stage, mode=mode, instances=2)
    index = _index(program, model)
    report = _report(index, details)
    definition = details['static']['failure_cleanup']
    selected, own = _row(report, details), _row(report, details, own=True)
    assert selected['occurrence_count'] == own['occurrence_count'] == 2
    for example in details['instances']:
        failure = _occurrence(selected, example)
        _helper(model, failure, definition, example)
        _caller(program, model, failure, definition, example)
        _caller(program, model, _occurrence(own, example), definition, example)
    _flags(report)


@pytest.mark.parametrize('missing', ('missing_payload_use', 'missing_dispatch', 'missing_helper_call'))
def test_missing_one_instances_bridge_never_uses_the_siblings_helper_or_current_packet(missing):
    program, model, details = await_failure_cleanup_execution(instances=2, **{missing: 0})
    index = _index(program, model)
    report = _report(index, details)
    definition = details['static']['failure_cleanup']
    selected, own = _row(report, details), _row(report, details, own=True)
    assert selected['occurrence_count'] == own['occurrence_count'] == 2
    assert {row['actual'] for row in own['definition']['caller_terminals']} == set(definition['payload_uses'])
    first, sibling = details['instances']
    partial = _occurrence(selected, first)
    assert partial['status'] not in ('DECLARED', 'NOT_APPLICABLE') and partial['gaps']
    _helper(model, _occurrence(selected, sibling), definition, sibling)
    _caller(program, model, _occurrence(own, sibling), definition, sibling)
    if missing == 'missing_helper_call':
        assert partial['stage'] is None and partial['call_chain'] == ()
        # A missing expansion link does not erase the directly captured Get R
        # result, or its independent local caller continuation.
        _caller(program, model, _occurrence(own, first), definition, first)
    else:
        local = _occurrence(own, first)
        assert local['status'] not in ('DECLARED', 'NOT_APPLICABLE') and local['gaps']
        assert not any(row['binding']['match'] is True for row in local['caller_terminals'])


@pytest.mark.parametrize('source_kind', ('sibling', 'forwarded'))
def test_generic_cursor_does_not_own_a_sibling_or_forwarded_value_at_the_selected_result(source_kind):
    program, model, details = await_failure_cleanup_execution(instances=2)
    index = _index(program, model)
    first, sibling = details['instances']
    source = sibling['root_value'] if source_kind == 'sibling' else first['forwarded_value']
    assert source.id != first['root_value'].id
    if source_kind == 'forwarded':
        assert source.origin == first['root_value'].origin
    report = index.completion_continuations(source.id, first['source'],
        cross_resume=False, budget=BUDGET)
    assert 'completion_source_anchor_association_unproved' in report['gaps']
    assert report['status'] != 'DECLARED'
    assert all(row['root_binding']['match'] is None for row in report['terminals'])
    _flags(report)


def test_opaque_caller_after_cleanup_is_not_a_completed_failure_delivery():
    program, model, details = await_failure_cleanup_execution(mode='opaque', instances=2)
    index = _index(program, model)
    report = _report(index, details)
    definition = details['static']['failure_cleanup']
    own = _row(report, details, own=True)
    for example in details['instances']:
        occurrence = _occurrence(own, example)
        assert occurrence['status'] == 'PARTIAL'
        cursor, = occurrence['caller_continuations']
        assert any(boundary['operation'] is not None
            and boundary['operation'].id == example['caller_operations'][definition['opaque'].id]
            and boundary['kind'] == 'OPAQUE_OPERATION' for boundary in cursor['boundaries'])
        assert not any(row['binding']['match'] is True for row in occurrence['caller_terminals'])
    _flags(report)


def test_budget_one_keeps_static_failure_keys_and_each_raw_source_capture_count():
    program, model, details = await_failure_cleanup_execution(instances=2)
    index = _index(program, model)
    complete, limited = _report(index, details), _report(index, details, budget=1)
    assert {row['key'] for row in limited['failure_paths']} == {
        row['key'] for row in complete['failure_paths']}
    for row in limited['failure_paths']:
        assert row['occurrence_count'] == 2
        assert row['definition']['source_result'] == details['static']['failure_cleanup']['source_result']
        assert all(occurrence['status'] != 'DECLARED' for occurrence in row['occurrences'])
    inventory = limited['failure_path_inventory']
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['cursor'] is not None or limited['cursor'] is not None
    assert limited['budget']['truncated'] is True
    _flags(limited)

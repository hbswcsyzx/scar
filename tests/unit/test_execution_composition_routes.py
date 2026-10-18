"""Original ports remain distinct; declarations never become identity proofs."""
from dataclasses import replace

import pytest

from scar.ir.execution.composition_routes import routes
from scar.ir.execution.ids import OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.control import PendingPayload
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.ids import BlockID, OperationID, UseID
from scar.ir.program.model import CompletionResult, StateVersionValue
from scar.ir.program.resumption import ResumeInput, SavedInput
from tests.fixtures.execution_call_graphs import invoke_call_execution, shared_calls_execution
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_cleanup_graphs import resume_multistate_graph
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_graphs import loop_state_program
from tests.fixtures.program_resumption_graphs import resumption_program


def _routes(program, model, budget=None):
    ctx = ExecutionIndex(model, program)._ctx
    return ctx, routes(ctx, budget=ValidityBudget(4096) if budget is None else budget)


def _path(program, rows):
    return declared_path(program, [(BlockID(block), edge) for block, edge in rows])


def test_two_declared_calls_keep_original_input_result_state_and_activation_objects():
    program, model, _ = shared_calls_execution()
    ctx, view = _routes(program, model)
    assert view['status'] == 'DERIVED' and view['cursor'] is None
    assert len(view['operations']) == len(model.operations)
    assert len(view['values']) == len(model.values)
    assert view['pending'] == dict(operations=0, values=0, transfers=0, call_scan=0)
    assert len(view['calls']) == 2
    for result, link in zip(view['calls'], model.call_activations, strict=True):
        original = ctx.resolved_call_activations[link.id]
        assert result['association'] is link
        assert result['activation'] is ctx.activations[link.activation]
        assert result['status'] == 'DECLARED' and result['scan_complete']
        for route, source in zip(result['inputs'], original['inputs'], strict=True):
            assert route is source
            assert route['actual_definition'] is ctx.core_uses[route['actual'].use][1]
            assert route['formal'].id != route['actual_value'].id
        for route, source in zip(result['outputs'], original['outputs'], strict=True):
            assert route is source
            assert route['caller_result'].origin == link.caller
    first, second = view['calls']
    first_state = next(row for row in first['outputs'] if isinstance(row['caller_result_definition'], StateVersionValue))
    second_state = next(row for row in second['inputs'] if isinstance(row['formal_definition'], StateVersionValue))
    assert first_state['caller_result'] is second_state['actual_value']
    assert not view['source_runtime_verified'] and not view['runtime_identity_verified']
    assert not view['value_identity_verified'] and not view['transformation_authorized']


def test_same_dynamic_value_at_distinct_original_use_ports_is_not_deduplicated():
    program, model, _ = shared_calls_execution()
    _, result = _routes(program, model)
    repeated = [row for row in result['operations'] if row['definition'].id == OperationID('twice')]
    assert len(repeated) == 2
    for item in repeated:
        left, right = item['uses']
        assert left['definition'].id != right['definition'].id
        assert left['actual'].value == right['actual'].value
        assert left['value'] is right['value']
    assert repeated[0]['uses'][0]['value'].id != repeated[1]['uses'][0]['value'].id


def test_missing_association_is_still_a_call_and_missing_actual_is_still_a_use():
    program, model, _ = shared_calls_execution()
    omitted = model.uses[0]
    model = replace(model, call_activations=(), uses=tuple(row for row in model.uses if row is not omitted))
    _, view = _routes(program, model)
    assert len(view['calls']) == 2 and all(row['status'] == 'MISSING' for row in view['calls'])
    assert all(row['gaps'][0].code == 'call_activation_missing' for row in view['calls'])
    original = next(row for row in view['operations'] if row['occurrence'].id == omitted.operation)
    port = next(row for row in original['uses'] if row['definition'].id == omitted.use)
    assert port['actual'] is None
    assert 'composition_use_unobserved' in {row.code for row in view['gaps']}


@pytest.mark.parametrize('raised', (False, True))
def test_actual_invoke_completion_projection_has_no_copy_use_and_no_common_after(raised):
    program, model, details = invoke_call_execution(raised=raised)
    ctx, view = _routes(program, model)
    link = model.call_activations[0]
    transfer = next(row for row in view['transfers'] if row['transfer'].operation == link.caller)
    caller = next(row for row in view['operations'] if row['occurrence'].id == link.caller)
    assert caller['after'] and all(value is None for value in caller['after'].values())
    for row in transfer['arguments']:
        assert type(row['argument']) is CompletionResult
        assert row['source'] is None
        assert row['projection']['index'] == row['argument'].index
        assert row['projection']['completion'].kind == transfer['successor'].kind
        assert row['formal'] is ctx.results[(transfer['destination'].id, row['formal_definition'].id)]
    assert tuple(row['argument'].index for row in transfer['arguments']) == (1, 0)
    assert view['calls'][0]['outputs']


def test_resume_keeps_saved_reference_and_new_current_state_as_different_routes():
    program = resumption_program()
    model = _path(program, [('resume.entry', 0), ('resume.value', None)])
    ctx, view = _routes(program, model)
    transfer, = view['transfers']
    saved = [row for row in transfer['arguments'] if type(row['argument']) is SavedInput]
    supplied = [row for row in transfer['arguments'] if type(row['argument']) is ResumeInput]
    assert saved and supplied
    assert all(row['source']['actual'] is not None for row in saved)
    assert all(row['source'] is None and row['projection']['slot'] is not None for row in supplied)
    assert all(row['projection']['ingress'] is ctx.segments[model.visits[1].segment].ingress for row in supplied)
    state = next(row for row in supplied if isinstance(row['formal_definition'], StateVersionValue))
    assert transfer['state'][state['formal_definition'].location] == state['formal'].id
    assert state['formal'].origin == transfer['destination'].id


def test_cleanup_and_pending_payload_markers_remain_visible_with_current_state():
    program = resume_multistate_graph()
    model = _path(program, [('shared.entry', 0), ('shared.make_return', 0),
        ('shared.cleanup', 0), ('shared.cleanup.post-pop-route', 0),
        ('shared.dispatch.block', 0), ('shared.return_exit', None)])
    ctx, view = _routes(program, model)
    cleanup = [row for row in view['transfers'] if row['terminator'].kind.value == 'CLEANUP_ROUTE']
    assert cleanup and all(item['source'] is not None for row in cleanup for item in row['arguments'])
    dispatch = next(row for row in view['transfers'] if row['terminator'].kind.value == 'PENDING_DISPATCH')
    projected = next(row for row in dispatch['arguments'] if type(row['argument']) is PendingPayload)
    assert projected['source'] is None
    assert projected['projection']['pending']['actual'] is ctx.uses[(dispatch['occurrence'].id, dispatch['terminator'].pending)]
    assert projected['projection']['port'] == dispatch['successor'].port
    unknown = next(row for row in view['operations'] if row['definition'].id == OperationID('shared.cleanup.write'))
    assert unknown['effects_complete'] is False and unknown['accesses']
    for access in unknown['accesses']:
        assert access['access'].after == access['after'].value


def test_body_drive_marker_references_original_static_outcome_without_inventing_dynamic_body():
    program = driver_program()
    model = _path(program, [('driver.entry', 0), ('driver.ingress', 0), ('driver.outcome', None)])
    ctx, view = _routes(program, model)
    drive = next(row for row in view['transfers'] if row['operation'].id == OperationID('driver.drive'))
    assert drive['arguments'] and all(type(row['argument']) is BodyDriveResult for row in drive['arguments'])
    for row in drive['arguments']:
        assert row['source'] is None
        assert row['projection']['operation'] is ctx.core_operations[drive['successor'].source]
        assert row['projection']['dynamic_occurrence'] is None
        assert row['projection']['use'] is ctx.core_uses[row['projection']['use'].id][1]
    assert len(model.activations) == 1  # Driver declaration did not create a body occurrence.


def test_loop_visits_keep_fresh_results_and_original_state_access_links():
    program = loop_state_program()
    model = _path(program, [('loop.entry', 0), ('header', 0), ('body', 0),
        ('header', 0), ('body', 0), ('header', 1), ('exit', None)])
    _, view = _routes(program, model)
    comparisons = [row for row in view['operations'] if row['definition'].id == OperationID('compare')]
    actuals = [next(port for port in row['uses'] if port['definition'].id == UseID('compare.counter'))['value'] for row in comparisons]
    assert actuals[0].id != actuals[1].id
    assert actuals[0].origin != actuals[1].origin
    origin = next(row for row in view['values'] if row['value'].id == ValueOccurrenceID('3.counter.value'))
    assert origin['producer'].id == OperationOccurrenceID('3.read.counter')
    formal = next(row for row in view['values'] if row['value'].id == ValueOccurrenceID('3.header.state'))
    assert formal['formal_route']['transfer'].operation == OperationOccurrenceID('2.backedge')


def test_shared_budget_preserves_partial_port_cursor_and_never_resets_between_scans():
    program, model, _ = shared_calls_execution()
    budget = ValidityBudget(4)
    assert budget.spend('prior_stage', 2)
    ctx, result = _routes(program, model, budget)
    assert result['status'] == 'TRUNCATED' and budget.used == 4
    assert result['budget_used'] == 4
    assert result['visited']['operations'] == 1
    assert result['operations'][0]['scan_complete'] is False
    assert result['pending']['operations'] == len(model.operations) - 1
    assert result['pending']['values'] == len(model.values)
    assert result['pending']['call_scan'] == len(model.operations)
    assert result['cursor']['stage'] == 'uses'
    assert result['gaps'][0].code == 'composition_budget_exhausted'
    assert len(ctx.model.operations) == len(model.operations)
    with pytest.raises(TypeError, match='ValidityBudget'):
        routes(ctx, budget=4)

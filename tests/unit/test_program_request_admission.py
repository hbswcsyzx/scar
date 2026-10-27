"""Current request predicates constrain a static frontier, not native admission."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import CompletionResult, ExitKind
from scar.ir.program.protocol_async import async_connections, request_state_view
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import AdmissionPredicate
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_request_admission_graphs import request_admission_program, request_two_callers_program


def _view(graph, *, budget=4096):
    require_valid(graph)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(budget))
    return async_connections(ctx)


def _predicate(graph, details):
    require_valid(graph)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(4096))
    return request_state_view(ctx, details['predicate_row'])


def _gate(view):
    return next(item for item in view['control_routes']['frontiers'] if item['kind'] == 'FINAL_GATE')


def test_completed_request_rejects_on_true_with_actual_helper_packet_and_states():
    graph, details = request_admission_program()
    view = _predicate(graph, details)
    gate = _gate(view)
    assert gate['truth'] is False
    assert gate['same_request']['match'] is True and gate['currentness'] is True
    assert gate['request_target_compatible_at_snapshot'] is True
    assert gate['native_admission_verified'] is False
    exits = [item for item in view['control_routes']['frontiers'] if item['kind'] == 'HOST_EXIT']
    assert exits and all(item['edge'].successor_index == 0 for item in exits)
    helper = next(op for op in graph.operations if op.id == details['helper'])
    assert {edge.kind for edge in helper.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert all(type(arg) is CompletionResult for edge in helper.terminator.successors for arg in edge.arguments[:-1])
    assert view['native_phase_verified'] is False


def test_complete_true_and_current_same_request_refutes_potential_success_without_hard_reject():
    graph, details = request_admission_program(drive_on_true=True)
    view = _predicate(graph, details)
    gate = _gate(view)
    assert gate['truth'] is True and gate['currentness'] is True
    assert gate['request_binding']['match'] is True and gate['gate_request_binding']['match'] is True
    assert gate['same_request']['match'] is True
    assert gate['request_target_compatible_at_snapshot'] is False
    assert 'async_request_complete_success_incompatible_at_snapshot' in view['gaps']
    report = _view(graph)
    admission, = report['request_admissions']
    assert admission['status'] == 'PARTIAL'
    assert admission['gate'] is graph.final_body_gates[0]
    assert admission['native_admission_verified'] is False
    assert any(gap['code'] == 'async_request_complete_success_incompatible_at_snapshot'
               for gap in admission['gaps'])
    assert any(gap['code'] == 'async_request_complete_success_incompatible_at_snapshot'
               for gap in report['gaps'])


def test_unknown_callback_keeps_historical_true_but_removes_current_admission_support():
    graph, details = request_admission_program(drive_on_true=True, callback=True)
    view = _predicate(graph, details)
    gate = _gate(view)
    assert gate['truth'] is True
    assert gate['same_request']['match'] is True
    assert gate['read_snapshot_current'] is False and gate['currentness'] is False
    assert gate['request_target_compatible_at_snapshot'] is None
    assert 'async_request_admission_snapshot_unresolved' in view['gaps']
    assert 'async_request_complete_success_incompatible_at_snapshot' not in view['gaps']
    helper = details['callback']
    assert {edge.kind for edge in helper.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert all(type(arg) is CompletionResult for arg in helper.terminator.successors[1].arguments)
    assert view['source_runtime_verified'] is False
    assert any(gap['code'] == 'async_request_admission_snapshot_unresolved' for gap in _view(graph)['gaps'])


def test_same_typed_other_receiver_cannot_supply_this_drivers_request_predicate():
    graph, _ = request_admission_program(wrong_receiver=True)
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=()))
    assert 'admission_owner' in {issue.code for issue in validate(graph)}


def test_another_boolean_cannot_replace_this_predicates_actual_read_result():
    graph, _ = request_admission_program(wrong_bool=True)
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=()))
    assert 'admission_bool_source' in {issue.code for issue in validate(graph)}


def test_request_initial_step_is_not_body_created_or_general_admission():
    graph, details = request_admission_program(rule='IS_INITIAL_STEP')
    gate = _gate(_predicate(graph, details))
    assert gate['truth'] is True and gate['same_request']['match'] is True
    assert gate['request_target_compatible_at_snapshot'] is None
    assert gate['target_compatible_at_snapshot'] is None
    assert gate['native_admission_verified'] is False


def test_deleting_predicate_keeps_each_original_gate_missing_in_the_denominator():
    graph, _ = request_admission_program()
    graph = replace(graph, protocol_operations=tuple(row for row in graph.protocol_operations
                    if type(row.contract) is not AdmissionPredicate))
    report = _view(graph)
    assert len(report['request_admissions']) == len(graph.final_body_gates)
    admission, = report['request_admissions']
    assert admission['gate'] is graph.final_body_gates[0]
    assert admission['predicate_count'] == 0 and admission['status'] == 'MISSING'
    assert any(item['code'] == 'async_request_admission_predicate_missing' for item in report['gaps'])


def test_tiny_budget_retains_original_gate_and_a_not_checked_predicate_cursor():
    graph, _ = request_admission_program()
    report = _view(graph, budget=1)
    admission, = report['request_admissions']
    assert admission['gate'] is graph.final_body_gates[0]
    assert admission['predicate_count'] == 1
    assert admission['status'] == 'NOT_CHECKED' and admission['cursor']
    assert report['cursor'] and admission['candidates'] == ()
    assert report['inventory'][0]['gates'] == graph.final_body_gates


def test_two_real_calls_to_one_request_source_remain_two_original_caller_recipes():
    graph, details = request_two_callers_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(32768))
    row = details['predicate_row']
    from scar.ir.program.protocols import OwnedUse
    origins = ctx.origins(OwnedUse(row.operation, row.contract.subject.request_use))
    callers = {step['caller'].id for recipe in origins['recipes'] for step in recipe['path']
               if step['kind'] == 'CALL_ACTUAL_TO_FORMAL'}
    assert callers == {item.id for item in details['callers']}
    assert {recipe['origin'].edge.operation for recipe in origins['recipes']} == {details['request_create']}
    view = request_state_view(ctx, row)
    assert view['request_binding']['match'] is True
    assert view['native_phase_verified'] is view['source_runtime_verified'] is False


def test_public_inventory_exposes_missing_admission_without_changing_program_records():
    graph, _ = request_admission_program()
    graph = replace(graph, protocol_operations=tuple(row for row in graph.protocol_operations
                    if type(row.contract) is not AdmissionPredicate))
    view = ProgramIndex(graph).protocol_obligations(budget=32768)
    family = view['connections']['families']['async']
    assert family['request_admissions'][0]['status'] == 'MISSING'
    assert view['protocol_implementation_complete'] is False
    assert view['source_runtime_verified'] is view['transformation_authorized'] is False


def test_initial_selection_is_charged_and_truncation_cannot_return_a_partial_boolean():
    from scar.ir.program.protocol_async import _Analysis
    graph, details = request_admission_program(rule='IS_INITIAL_STEP')
    require_valid(graph)
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(4096))
    row = details['predicate_row']
    view = request_state_view(ctx, row)
    read_cost = ctx.budget.used
    scope = next(scope for scope in graph.protocol_scopes if scope.id == details['scope'])
    drive = graph.body_drives[0]
    assert _Analysis(ctx).initial_step(scope, drive) is True
    assert ctx.budget.costs['async_initial_step_predicates'] == 1
    assert ctx.budget.costs['async_initial_step_frontiers'] == len(view['control_routes']['frontiers'])
    limited = ConnectionContext(graph, index=index, budget=ValidityBudget(read_cost + 1))
    request_state_view(limited, row)
    assert limited.budget.used == read_cost and not limited.budget.truncated
    analysis = _Analysis(limited)
    assert analysis.initial_step(scope, drive) is None
    assert limited.budget.truncated and analysis.cursor
    assert limited.preparation['async_initial_predicate_index_rows'] == len(graph.protocol_operations)
    assert limited.preparation['async_initial_predicates'] == 1


def test_latent_selection_reports_historical_edge_without_claiming_current_phase():
    from tests.fixtures.program_async_connections import request_creation_program
    graph, _ = request_creation_program(kind='THROW', normalize=True)
    delivery, = _view(graph)['deliveries']
    assert delivery['initial_step'] is True
    assert delivery['selection_basis'] == 'ORIGINAL_PREDICATE_EDGE'
    assert delivery['current_step_verified'] is False
    assert delivery['conditions']

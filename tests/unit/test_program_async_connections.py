"""Conditional async protocol connections over real canonical IR ports."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import CompletionResult, InvokeLiteralResult
from scar.ir.program.protocol_async import async_connections
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_connections import async_driver_program
from tests.fixtures.program_async_connections import cancellation_program
from tests.fixtures.program_async_connections import request_creation_program, request_state_program


def _view(graph, *, budget=4096):
    require_valid(graph)
    index = ProgramIndex(graph)
    return async_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(budget)))


def _codes(graph):
    return {issue.code for issue in validate(graph)}


@pytest.mark.parametrize('target,flavor', [('start', 'ASYNC_YIELD'), ('start', 'AWAIT'),
                                         ('value', 'ASYNC_YIELD'), ('packet', 'ASYNC_YIELD')])
def test_real_async_association_gate_source_and_session_use_original_ports(target, flavor):
    graph, details = async_driver_program(target=target, flavor=flavor)
    report = _view(graph)
    assert not report['issues']
    association, = report['associations']
    assert association['declaration'] is details['association']
    assert association['receiver']['match'] is True
    gate, = association['gates']
    assert gate['body_binding']['match'] is True
    assert all(item['binding']['match'] is True for item in gate['state_support'])
    session, = report['session_outcomes']
    assert session['update'] is graph.session_updates[0]
    assert session['source'].source.outcome == details['outcome']
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False


def test_attachments_can_be_removed_without_fabricating_or_breaking_old_core_ports():
    graph, _ = async_driver_program()
    old = replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=())
    require_valid(old)
    assert old.operations == graph.operations
    assert old.values == graph.values
    assert old.request_association_reads == graph.request_association_reads


def test_deleting_session_source_relation_keeps_the_original_source_obligation():
    graph, details = async_driver_program()
    report = _view(replace(graph, protocol_bindings=()))
    obligations = [item for item in report['obligations'] if item.get('operation') == details['updates'][0].operation]
    assert obligations and all(item['status'] == 'MISSING' for item in obligations)
    assert any(item['code'] == 'async_session_outcome_missing' for item in report['gaps'])


@pytest.mark.parametrize('flavor,post', [('AWAIT', SessionPost.COMPLETE), ('ASYNC_YIELD', SessionPost.HOLD)])
def test_known_async_outcome_cannot_publish_the_other_session_post(flavor, post):
    graph, _ = async_driver_program(flavor=flavor, post=post)
    assert 'async_session_post' in _codes(graph)


def test_same_typed_external_body_cannot_replace_the_exact_request_projection():
    graph, details = async_driver_program()
    gate = next(op for op in graph.operations if op.id == details['gate'])
    body_actual = gate.invoke_arguments[0]
    original_external_body = next(region for region in graph.regions if region.id == graph.root).blocks[0].arguments[0]
    bad_gate = replace(gate, uses=tuple(replace(use, value=original_external_body)
        if use.value == details['sources']['body'] else use for use in gate.uses))
    assert body_actual in bad_gate.invoke_arguments
    bad = replace(graph, operations=tuple(bad_gate if op.id == gate.id else op for op in graph.operations))
    assert 'async_body_source' in _codes(bad)


def test_attached_association_cannot_swap_its_two_exact_normal_results():
    graph, details = async_driver_program()
    row = details['association_row']
    changed = replace(row, contract=replace(row.contract, body=row.contract.latent, latent=row.contract.body))
    bad = replace(graph, protocol_operations=tuple(changed if item == row else item for item in graph.protocol_operations))
    assert 'async_association_marker' in _codes(bad)


def test_session_relation_must_name_the_real_drive_source_not_a_same_region_operation():
    graph, details = async_driver_program()
    relation, = graph.protocol_bindings
    bad = replace(graph, protocol_bindings=(replace(relation, source=replace(
        relation.source, source=OperationID('resume.return'))),))
    assert 'async_session_reference' in _codes(bad)


def test_small_budget_retains_an_explicit_cursor_and_original_missing_inventory():
    graph, _ = async_driver_program()
    report = _view(graph, budget=1)
    assert report['cursor'] is not None
    assert any(item['code'] == 'protocol_budget_exhausted' for item in report['gaps'])
    assert report['source_runtime_verified'] is False
    scope, = report['inventory']
    assert scope['updates'] == graph.session_updates
    assert scope['drives'] == graph.body_drives
    assert scope['associations'] == graph.request_association_reads


def test_suspended_body_is_not_finished_when_its_async_request_completes():
    graph, _ = async_driver_program(release=True)
    assert 'terminal_release_unfinished' in _codes(graph)


@pytest.mark.parametrize('handled', (True, False))
def test_cancel_call_injection_handling_and_final_status_are_distinct_original_sites(handled):
    graph, details = cancellation_program(handled=handled)
    report = _view(graph)
    assert not report['issues']
    assert details['cancel'] != details['drive'].operation
    delivery = report['cancellation'][0]
    assert delivery['packet']['match'] is True
    assert delivery['target']['match'] is True
    status = report['cancellation'][-1]
    assert status['consumer']['match'] is True
    assert status['result'].operation == details['status'].id
    if handled:
        handling = report['cancellation'][1]
        assert handling['packet']['match'] is True
        assert handling['binding'].continuation == details['continuation']
    else:
        assert delivery['terminal_routes']
        assert all(item['match'] is True for item in delivery['terminal_routes'])
        from scar.ir.program.protocols import ProtocolClause
        terminal = next(item for item in report['obligations'] if item['clause'] is ProtocolClause.CANCEL_HANDLER_OR_TERMINAL)
        assert terminal['status'] == 'DECLARED' and terminal['derived_terminals']
    # Removing only semantic metadata leaves real operations/SSA unchanged.
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=()))


def test_actual_failed_task_creation_cannot_supply_expected_cancellation_target():
    from scar.ir.program.protocol_connections import CancelDelivery
    graph, _ = cancellation_program()
    delivery = next(row for row in graph.protocol_bindings if type(row) is CancelDelivery)
    bad_target = replace(delivery.expected_target,
        task_result=InvokeLiteralResult(ControlEdgeReference(delivery.expected_target.task_result.edge.operation, 1), CompletionResult(0)))
    bad = replace(graph, protocol_bindings=tuple(replace(row, expected_target=bad_target) if row is delivery else row
                                                for row in graph.protocol_bindings))
    assert 'cancel_binding_reference' in _codes(bad)


def test_full_delivery_reference_cannot_silently_choose_another_packet_source():
    from scar.ir.program.protocol_connections import CancelHandling
    graph, _ = cancellation_program()
    handling = next(row for row in graph.protocol_bindings if type(row) is CancelHandling)
    changed = replace(handling, delivery=replace(handling.delivery,
        packet_source=handling.delivery.expected_target.task_result))
    bad = replace(graph, protocol_bindings=tuple(changed if row is handling else row for row in graph.protocol_bindings))
    assert 'cancel_delivery_reference' in _codes(bad)


def test_deleting_cancel_relations_does_not_delete_request_delivery_handler_status_denominator():
    from scar.ir.program.protocol_connections import TaskStatusRead
    graph, _ = cancellation_program()
    graph = replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings if type(row) is TaskStatusRead))
    report = _view(graph)
    missing = {item['clause'] for item in report['obligations'] if item['status'] == 'MISSING'}
    from scar.ir.program.protocols import ProtocolClause
    assert {ProtocolClause.CANCEL_DELIVERY, ProtocolClause.CANCEL_HANDLER_OR_TERMINAL} <= missing
    assert len([item for item in report['obligations'] if item['scope'].value == 'cancel.scope']) == 3


def test_task_status_cannot_read_another_reference_and_report_this_cancelled_task():
    graph, details = cancellation_program()
    interface, = graph.driver_interfaces
    status = details['status']
    changed = replace(status, uses=tuple(replace(use, value=interface.receiver) if use.id == UseID('cancel.status.task') else use
                                        for use in status.uses))
    bad = replace(graph, operations=tuple(changed if row.id == status.id else row for row in graph.operations))
    assert 'cancel_status_task' in _codes(bad)


def test_task_status_cannot_use_the_earlier_cancel_calls_boolean_as_its_result():
    from scar.ir.program.protocol_connections import TaskStatusRead
    graph, details = cancellation_program()
    status = next(row for row in graph.protocol_bindings if type(row) is TaskStatusRead)
    changed = replace(status, result=InvokeLiteralResult(ControlEdgeReference(details['cancel'], 0), CompletionResult(0)))
    bad = replace(graph, protocol_bindings=tuple(changed if row is status else row for row in graph.protocol_bindings))
    assert 'cancel_binding_reference' in _codes(bad)


@pytest.mark.parametrize('rule', ('IS_INITIAL_STEP', 'IS_COMPLETE'))
def test_request_predicate_reads_r_and_its_own_boolean_on_original_branch(rule):
    from scar.ir.program.protocol_async import request_state_view
    graph, details = request_state_program(rule=rule)
    require_valid(graph)
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(4096))
    view = request_state_view(ctx, details['predicate_row'])
    assert view['bool_must_copy'] is True
    assert view['subject'].rule.value == rule
    assert view['input'].id == view['subject'].request_use
    assert view['branch'].id == details['branch']
    assert all(item['binding']['match'] is True for item in view['state_support'])
    assert view['control_routes']['frontiers']
    gates = [item for item in view['control_routes']['frontiers'] if item['kind'] == 'FINAL_GATE']
    assert gates and all(item['read_snapshot_current'] is True for item in gates)
    assert view['source_runtime_verified'] is False


@pytest.mark.parametrize('kind', ('NEXT', 'SEND', 'THROW', 'CLOSE'))
def test_request_origin_projects_its_exact_create_body_and_latent_not_scheduler(kind):
    graph, details = request_creation_program(kind=kind)
    report = _view(graph)
    association, = report['associations']
    projection, = association['projections']
    assert projection['create'].operation == details['request_create']
    assert projection['raw_requests']
    assert {item['definition'] for item in projection['raw_requests']} == {details['latent_definition']}
    assert details['latent_definition'].value != details['scheduler_definition'].value
    assert projection['create'].latent == projection['latent_input'].use
    assert projection['create'].body == projection['body_input'].use
    assert report['runtime_identity_verified'] is False
    if kind in ('NEXT', 'SEND'):
        delivery, = report['deliveries']
        assert delivery['initial_step'] is True
        assert delivery['alternatives']
        assert all(item['match'] is True for item in delivery['alternatives'])


@pytest.mark.parametrize('kind', ('THROW', 'CLOSE'))
def test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state(kind):
    from scar.ir.program.model import ExitKind
    graph, details = request_creation_program(kind=kind, normalize=True)
    report = _view(graph)
    delivery, = report['deliveries']
    alternative, = delivery['alternatives']
    assert alternative['match'] is True
    normalization, = alternative['normalizations']
    assert normalization['processing'].operation == details['normalization']
    assert normalization['latent']['match'] is True
    assert normalization['delivered']['match'] is True
    operation = next(op for op in graph.operations if op.id == details['normalization'])
    assert {edge.kind for edge in operation.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
    raised = operation.terminator.successors[1]
    region = next(region for region in graph.regions if region.id == details['interface'].region)
    landing = next(block for block in region.blocks if block.id == raised.block)
    assert len(landing.arguments) == 1 + len(graph.locations)
    assert all(type(arg) is CompletionResult for arg in raised.arguments)


@pytest.mark.parametrize('scheduler_kind', ('NEXT', 'SEND'))
def test_later_request_step_uses_current_scheduler_not_latent_payload(scheduler_kind):
    graph, details = request_creation_program(kind='SEND', initial_step=False, scheduler_kind=scheduler_kind)
    report = _view(graph)
    delivery, = report['deliveries']
    assert delivery['initial_step'] is False
    assert delivery['alternatives']
    assert all(item['match'] is True for item in delivery['alternatives'])
    assert {item['definition'] for item in delivery['alternatives']} == {details['scheduler_definition']}
    assert details['scheduler_definition'] != details['latent_definition']


def test_current_waiter_result_is_not_assumed_to_be_the_parent_body_without_forwarding():
    from tests.fixtures.program_async_connections import cancellation_waiter_program
    graph, details = cancellation_waiter_program()
    report = _view(graph)
    delivery = report['cancellation'][0]
    assert delivery['binding'].expected_target.target == details['target_result'].origin
    assert delivery['target']['match'] is None
    assert any(item['code'] == 'cancel_waiter_forwarding_unresolved' for item in report['gaps'])
    assert report['runtime_identity_verified'] is False


def test_own_continuation_read_does_not_choose_a_different_parent_actual():
    from tests.fixtures.program_async_connections import cancellation_waiter_program
    graph, _ = cancellation_waiter_program(role='OWN_CONTINUATION')
    assert 'cancel_target_source' in _codes(graph)


def test_request_predicate_cannot_branch_on_another_same_type_boolean():
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import DataValue, LiteralOrigin
    graph, details = request_state_program()
    branch = next(op for op in graph.operations if op.id == details['branch'])
    original = next(value for value in graph.values if value.id == branch.uses[0].value)
    other = DataValue(ValueID('async.other.bool'), original.region, LiteralOrigin(True), 'builtins.bool')
    changed = replace(branch, uses=tuple(replace(use, value=other.id) if use.id == branch.terminator.condition else use
                                         for use in branch.uses))
    bad = replace(graph, values=(*graph.values, other),
        operations=tuple(changed if op.id == changed.id else op for op in graph.operations))
    assert 'admission_bool_source' in _codes(bad)


def test_latent_close_normalizer_cannot_consume_the_same_type_scheduler_request():
    graph, details = request_creation_program(kind='CLOSE', normalize=True)
    operation = next(op for op in graph.operations if op.id == details['normalization'])
    # All roles retain their original block/formal coordinates. Only the
    # actual normalizer RAW input is incorrectly replaced with S.
    region = next(region for region in graph.regions if region.id == details['interface'].region)
    block = next(block for block in region.blocks if operation.id in block.operations)
    changed = replace(operation, uses=tuple(replace(use, value=block.arguments[2])
        if use.id == details['normalization_raw'].id else use for use in operation.uses))
    bad = replace(graph, operations=tuple(changed if op.id == operation.id else op for op in graph.operations))
    assert 'async_delivery_source' in _codes(bad)


def test_source_branch_survives_normalization_but_does_not_keep_old_gate_state_current():
    graph, _ = request_creation_program(kind='THROW', normalize=True)
    report = _view(graph)
    delivery, = report['deliveries']
    assert delivery['initial_step'] is True
    changed = [gap for gap in report['gaps'] if gap['code'] == 'async_initial_selection_snapshot_changed']
    assert changed and all(gap['current_gate_authorized'] is False for gap in changed)
    assert all(gap['frontier']['read_snapshot_current'] is False for gap in changed)


def test_real_session_helper_has_only_normal_post_and_real_partial_raise_states():
    from scar.ir.program.lifecycle import LifecyclePostBinding
    from scar.ir.program.model import ExitKind
    graph, _ = async_driver_program(target='value', helper=True, release=True)
    report = _view(graph)
    session, = report['session_outcomes']
    assert session['update'].binding is LifecyclePostBinding.NORMAL_COMPLETION
    operation = session['operation']
    normal, raised = operation.terminator.successors
    assert normal.kind is ExitKind.NORMAL and raised.kind is ExitKind.RAISE
    assert all(type(item) is CompletionResult for item in (*normal.arguments, *raised.arguments))
    assert len(raised.arguments) == 1 + len(normal.arguments)
    public = ProgramIndex(graph).session_publication(operation.id)
    assert public.point.successor_index == 0
    assert public.point.operation is operation
    assert len(graph.terminal_frame_releases) == 1


def test_a_second_delivery_does_not_borrow_the_first_deliveries_handler_coverage():
    from scar.ir.program.protocol_connections import CancelDelivery
    from scar.ir.program.protocols import ProtocolClause, StaticProtocolGap, StaticGapReason
    graph, _ = cancellation_program()
    original = next(item for item in graph.protocol_bindings if type(item) is CancelDelivery)
    second = replace(original, expected_target=StaticProtocolGap(StaticGapReason.TASK_IDENTITY_UNMODELED))
    report = _view(replace(graph, protocol_bindings=(*graph.protocol_bindings, second)))
    handler = next(item for item in report['obligations'] if item['clause'] is ProtocolClause.CANCEL_HANDLER_OR_TERMINAL)
    assert handler['status'] == 'MISSING'
    assert len(handler['delivery_coverage']) == 2
    assert {item['status'] for item in handler['delivery_coverage']} == {'DECLARED', 'MISSING'}


def test_async_return_cannot_publish_a_known_non_none_payload_as_natural_completion():
    from scar.ir.program.model import LiteralOrigin
    graph, _ = async_driver_program(target='value')
    original = next(value for value in graph.values if value.id.value == 'async.body.none')
    changed = replace(original, origin=LiteralOrigin(7))
    bad = replace(graph, values=tuple(changed if value is original else value for value in graph.values))
    assert 'async_return_value' in _codes(bad)


def test_public_query_keeps_async_inventory_and_all_authority_false_after_detaching():
    graph, _ = async_driver_program(flavor='AWAIT')
    require_valid(graph)
    view = ProgramIndex(graph).protocol_obligations(budget=32768)
    family = view['connections']['families']['async']
    assert family['associations'] and family['session_outcomes']
    assert len(family['inventory']) == 1
    assert family['inventory'][0]['updates'] == graph.session_updates
    assert family['source_runtime_verified'] is False
    assert family['transformation_authorized'] is False
    assert view['protocol_implementation_complete'] is False


"""Original async terminal legality survives deletion of optional consumers."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import LiteralOrigin
from scar.ir.program.protocol_async import async_connections
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_connections import async_driver_program


def test_known_non_none_async_return_is_rejected_without_its_session_source_attachment():
    graph, _ = async_driver_program(target='value')
    original = next(value for value in graph.values if value.id.value == 'async.body.none')
    changed = replace(original, origin=LiteralOrigin(7))
    graph = replace(graph, values=tuple(changed if value is original else value for value in graph.values),
        protocol_bindings=tuple(row for row in graph.protocol_bindings if type(row) is not AsyncSessionOutcome))
    assert 'async_return_value' in {issue.code for issue in validate(graph)}


def test_return_source_denominator_survives_deleted_consumers_and_budget_one():
    graph, _ = async_driver_program(target='value')
    graph = replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings
                                                  if type(row) is not AsyncSessionOutcome))
    require_valid(graph)
    index = ProgramIndex(graph)
    full = async_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(131072)))
    limited = async_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(1)))
    assert full['return_source_inventory']
    assert limited['return_source_inventory'] == full['return_source_inventory']
    assert len(limited['return_sources']) == len(full['return_sources'])
    assert all(row['status'] == 'NOT_CHECKED' and not row['checked'] and row['payload'] is None
               for row in limited['return_sources'])
    assert all(row['checked'] and row['known_none']
               and all(value is True for value in row['known_none']) for row in full['return_sources'])
    assert limited['cursor'] is not None
    assert limited['transformation_authorized'] is limited['source_runtime_verified'] is False


def _post_helper_failure(later_failure=False):
    """A later primitive failure replaces the old packet at the actual host."""
    from scar.ir.execution.common import Unresolved
    from scar.ir.execution.coordinates import ExecutionSegment, ResumeIngress
    from scar.ir.execution.ids import ExecutionSegmentID
    from scar.ir.execution.query import ExecutionIndex
    from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
    from scar.ir.execution.validation import validate as execution_validate
    from scar.ir.program.control import ProtocolValueKind
    from scar.ir.program.lifecycle import SessionPost
    from scar.ir.program.model import CompletionResult, ExitKind
    from tests.fixtures.execution_async_pipeline_graphs import _body_path
    from tests.fixtures.execution_call_graphs import _model
    from tests.fixtures.program_async_pipeline_graphs import _selected_path

    graph, details = async_driver_program(target='packet', helper=True)
    earlier = next(row for row in graph.operations if row.id == details['updates'][0].operation)
    if later_failure:
        from tests.fixtures.program_session_release_graphs import _Tail
        first_edge = next(row for row in earlier.terminator.successors if row.kind is ExitKind.RAISE)
        first_block = next(block for region in graph.regions for block in region.blocks if block.id == first_edge.block)
        update = details['updates'][0]
        tail = _Tail(graph, first_block.operations[-1],
            body=next(use.value for use in earlier.uses if use.id == update.body),
            request=next(use.value for use in earlier.uses if use.id == update.request))
        tail.invoke('a.later.helper')
        graph = tail.finish()
    require_valid(graph)
    operations = {row.id: row for row in graph.operations}
    blocks = {row.id: row for region in graph.regions for row in region.blocks}
    body = next(row for row in graph.regions if row.id == graph.resumable_bodies[0].region)
    driver = next(row for row in graph.regions if row.id == details['interface'].region)
    drive, = graph.body_drives
    helper = (next(row for row in graph.operations if row.id.value == 'a.later.helper')
              if later_failure else earlier)
    choices = {details['association'].operation: 0, details['gate']: 0,
        drive.operation: next(i for i, edge in enumerate(operations[drive.operation].terminator.successors)
                              if edge.source == details['source']),
        helper.id: next(i for i, edge in enumerate(helper.terminator.successors) if edge.kind is ExitKind.RAISE)}
    choices[earlier.id] = next(i for i, edge in enumerate(earlier.terminator.successors)
                             if edge.kind is ExitKind.RAISE)
    prefix = _body_path(graph, body, body.entry, drive.target.suspend)
    suffix = _body_path(graph, body, operations[drive.target.suspend].terminator.successors[
        drive.target.successor].block, details['source'])
    body_path = (*prefix[:-1], (prefix[-1][0], drive.target.successor), *suffix)
    model, scopes, evidence = _model(graph, (
        (driver.id, _selected_path(graph, driver, choices), 'helper.failure.driver'),
        (body.id, body_path, 'helper.failure.body')))
    _, visits, actuals = scopes[1]
    activation = scopes[1][0]
    point = model.activations[0].entry
    initial = next(row for row in model.segments if row.activation == activation)
    resumed = ExecutionSegment(ExecutionSegmentID('helper.failure.resume'), activation,
        initial.host_thread, ResumeIngress(actuals[drive.target.suspend], drive.target.successor, point))
    association = BodyDriveExecution(scopes[0][2][drive.operation], activation,
        visits[len(prefix)], actuals[details['source']], evidence)
    model = replace(model, segments=(*model.segments, resumed),
        visits=tuple(replace(row, segment=resumed.id) if row.id in visits[len(prefix):] else row
                     for row in model.visits), body_drive_executions=(association,),
        body_activation_origins=(BodyActivationOrigin(activation,
            Unresolved('external body creation was not captured', point), evidence),))
    validation = execution_validate(model, graph)
    assert validation.valid, validation.issues
    view = ExecutionIndex(model, graph).drive_execution(association.drive, budget=1048576)
    assert view['outcome'].id == association.outcome
    assert operations[details['source']].terminator.kind.value == 'RAISE'
    session = view['session']
    assert session['expected_post'] is SessionPost.COMPLETE
    target, = session['targets']
    assert target['post_established'] is False
    assert earlier.terminator.successors[target['selected_successor'].successor_index].kind is ExitKind.RAISE
    occurrence = scopes[0][2][helper.id]
    transfer = next(row for row in model.transfers if row.operation == occurrence)
    selected = transfer.successor_index
    edge = helper.terminator.successors[selected]
    assert edge.kind is ExitKind.RAISE
    signature = next(row for row in helper.completions if row.kind is ExitKind.RAISE)
    packet_slot = next(i for i, row in enumerate(signature.types)
                       if getattr(row, 'protocol', None) is ProtocolValueKind.EXCEPTION_PACKET)
    landing = next(row for row in model.visits if row.id == transfer.target)
    packet_formal = next(formal for actual, formal in zip(edge.arguments, blocks[landing.block].arguments)
                         if type(actual) is CompletionResult and actual.index == packet_slot)
    packet = next(row for row in model.values if row.origin == landing.id and row.value == packet_formal)
    host, = session['hosts']
    assert host['kind'] == 'HOST_FAILURE'
    assert host['source_value'] == packet
    body_use = operations[details['source']].terminator.values[0]
    old_packet = next(row.value for row in model.uses if (row.operation, row.use) == (association.outcome, body_use))
    assert packet.id != old_packet
    assert len(host['bindings']) == 1
    assert host['bindings'][0]['copy_status'] == 'DECLARED_ORIGINAL_COPY'
    for actual, formal in zip(edge.arguments, blocks[landing.block].arguments):
        if type(actual) is CompletionResult and actual.index != packet_slot:
            state = next(row for row in model.values if row.origin == landing.id and row.value == formal)
            assert any(row.operation == host['operation'].id and row.value == state.id for row in model.uses)
    assert all(session[key] is False for key in ('source_runtime_verified',
        'runtime_identity_verified', 'value_identity_verified', 'transformation_authorized'))


def test_post_helper_failure_owns_host_packet_after_terminal_body_raise():
    _post_helper_failure()


def test_later_non_session_helper_failure_supersedes_the_earlier_session_failure():
    _post_helper_failure(later_failure=True)


def test_post_helper_raise_cannot_report_the_old_body_packet_as_its_current_failure():
    """The older packet is available but is not this helper's own RAISE."""
    from scar.ir.program.model import StateVersionValue

    graph, details = async_driver_program(target='packet', helper=True)
    require_valid(graph)
    operations = {row.id: row for row in graph.operations}
    edge = next(row for row in operations[details['drive']].terminator.successors
                if row.source == details['source'])
    landing = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
    values = {row.id: row for row in graph.values}
    old = next(value for value in landing.arguments if not isinstance(values[value], StateVersionValue))
    host = next(row for row in graph.operations if row.id.value == 'async.session.helper.raise.exit')
    wrong = replace(host, uses=tuple(replace(use, value=old) if use.id == host.terminator.values[0]
                                    else use for use in host.uses))
    changed = replace(graph, operations=tuple(wrong if row is host else row for row in graph.operations))
    assert 'protocol_copy' in {issue.code for issue in validate(changed)}


@pytest.mark.parametrize('old_packet', (False, True), ids=('current-packet', 'old-packet'))
def test_two_helper_raises_follow_cfg_order_rather_than_sorted_operation_ids(old_packet):
    from scar.ir.program.model import ExitKind
    from tests.fixtures.program_session_release_graphs import _Tail

    graph, details = async_driver_program(target='packet', helper=True)
    earlier = next(row for row in graph.operations if row.id == details['updates'][0].operation)
    first_edge = next(row for row in earlier.terminator.successors if row.kind is ExitKind.RAISE)
    first_block = next(block for region in graph.regions for block in region.blocks if block.id == first_edge.block)
    old = first_block.arguments[0]
    first_host = first_block.operations[-1]
    update = details['updates'][0]
    tail = _Tail(graph, first_host,
        body=next(use.value for use in earlier.uses if use.id == update.body),
        request=next(use.value for use in earlier.uses if use.id == update.request))
    # This executes later but sorts before the earlier async.session.helper.
    tail.invoke('a.later.helper')
    graph = tail.finish()
    later = next(row for row in graph.operations if row.id.value == 'a.later.helper')
    assert later.id.wire < earlier.id.wire
    if old_packet:
        host = next(row for row in graph.operations if row.id.value == 'a.later.helper.raise.exit')
        wrong = replace(host, uses=tuple(replace(use, value=old) if use.id == host.terminator.values[0]
                                        else use for use in host.uses))
        graph = replace(graph, operations=tuple(wrong if row is host else row for row in graph.operations))
    issues = validate(graph)
    if old_packet:
        assert 'protocol_copy' in {issue.code for issue in issues}
    else:
        assert not issues, issues

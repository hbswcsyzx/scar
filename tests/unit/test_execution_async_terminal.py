"""Body-local conversion precedes the actual async BodyRaise/publication."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, ResumeIngress, UseRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as execution_validate
from scar.ir.execution.work import ActualCompletionState, InvokeBoundaryStateEffect
from scar.ir.program.exception_matches import BuiltinExceptionCategory
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import (
    BlockArgument, CompletionResult, ExitKind, InvokeLiteralResult, OperationResult,
    ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ExistingAccess, ObjectField, ReferenceOwner
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_terminal_graphs import async_terminal_execution, _state_use


_BUDGET = 1048576
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _index(program, model):
    require_valid(program)
    validation = execution_validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program)


def _use(model, operation, use):
    rows = tuple(row for row in model.uses if (row.operation, row.use) == (operation, use))
    assert len(rows) == 1
    return rows[0]


def _value(model, identity):
    return next(row for row in model.values if row.id == identity)


def _own(program, model, occurrence, port):
    operation = next(row for row in program.operations if row.id == port.operation) if type(port) is OperationResult else next(
        row for row in program.operations if row.id == port.edge.operation)
    if type(port) is OperationResult:
        rows = tuple(row for row in model.values if row.origin == occurrence and row.value == operation.results[port.index])
    else:
        assert type(port) is InvokeLiteralResult
        transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
        assert transfer.successor_index == port.edge.successor_index
        edge = operation.terminator.successors[transfer.successor_index]
        block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
        formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
                        if type(actual) is CompletionResult and actual.index == port.result.index)
        rows = tuple(row for row in model.values if row.origin == transfer.target and row.value == formal)
    assert len(rows) == 1
    return rows[0]


def _current(index, program, model, occurrence):
    actual = next(row for row in model.operations if row.id == occurrence)
    operation = next(row for row in program.operations if row.id == actual.operation)
    values = {row.id: row for row in program.values}
    current = index.state_at(OccurrencePoint(occurrence, OccurrencePhase.BEFORE))
    assert current is not None
    for use in operation.uses:
        if type(values[use.value]) is StateVersionValue:
            assert _use(model, occurrence, use.id).value == current[values[use.value].location]
    return current


def _scoped_value(program, model, example, definition):
    identity = getattr(definition, 'id', definition)
    origins = {example['caller_activation'], example['body_activation']}
    origins.update(example['caller_visits'])
    origins.update(example['caller_operations'].values())
    for activation, visits, operations in (*example['driver_scopes'],
            *example['body_scopes'].values(), *example['extra_scopes'].values()):
        origins.add(activation)
        origins.update(visits)
        origins.update(operations.values())
    rows = tuple(row for row in model.values if row.value == identity and row.origin in origins)
    assert len(rows) == 1
    return rows[0]


def _copied(index, model, target, source):
    """Independent oracle using public actual CFG and call port receipts."""
    calls = tuple(index.call_activation(row.id) for row in model.call_activations)
    inputs = {row['formal'].id: row['actual_value'].id for call in calls for row in call['inputs']
              if row['formal'] is not None and row['actual_value'] is not None}
    outputs = {row['caller_formal'].id: row['callee_use'].value for call in calls for row in call['outputs']
               if row['caller_formal'] is not None and row['callee_use'] is not None}
    current, seen = target, set()
    while current != source and current not in seen:
        seen.add(current)
        if current in inputs:
            current = inputs[current]
        elif current in outputs:
            current = outputs[current]
        else:
            try:
                route = index.formal_route(current)
            except ValueError:
                break
            if route.source_use is None:
                break
            current = route.source_use.value
    assert current == source


def _call(index, program, model, association):
    view = index.call_activation(association.id)
    assert view['association'] == association and view['entry'] is not None and view['completion'] is not None
    assert all(row['actual'] is not None and row['actual_value'] is not None and row['formal'] is not None
               for row in view['inputs'])
    terminal = next(row for row in program.operations if row.id == view['completion'].operation)
    assert {row['ordinal'] for row in view['outputs']} == set(range(len(terminal.terminator.values)))
    assert all(row['edge_argument'] == CompletionResult(row['ordinal']) and row['callee_use'] is not None
               and row['caller_formal'] is not None for row in view['outputs'])
    _current(index, program, model, association.caller)
    _current(index, program, model, association.completion)
    assert all(view[key] is False for key in _FLAGS)
    return view


def _complete(index, program, model, details, number):
    static, example = details['static'], details['instances'][number]
    intrinsic, terminal = static['intrinsic'], example['terminal']
    definitions = {row.id: row for row in program.operations}
    values = {row.id: row for row in program.values}
    assert len(example['body_segments']) == len(example['body_drives']) == 2
    assert example['active_driver_ordinals'] == (0, 1)
    assert {row.activation for row in example['body_drives']} == {example['body_activation']}
    assert example['body_origin'].creation == example['creation']
    origin = index.body_activation_origin(example['body_activation'], budget=_BUDGET)
    assert origin['association'] == example['body_origin']
    second = next(row for row in model.segments if row.id == example['body_segments'][1])
    assert type(second.ingress) is ResumeIngress
    assert second.ingress.suspension == example['body_drives'][0].outcome
    transfer, = tuple(row for row in model.transfers if row.operation == second.ingress.suspension)
    assert transfer.target == example['body_entries'][1]
    assert transfer.successor_index == static['drivers'][1]['drive'].target.successor
    for association in example['call_activations']:
        _call(index, program, model, association)
    child = _call(index, program, model, terminal['association'])
    assert child['caller'].id == terminal['body_call']
    assert child['activation'].id == terminal['activation']
    assert child['completion'].id == terminal['completion']
    assert ProgramIndex(program).native_boundary_for_region(intrinsic['region'].id) == intrinsic['native_boundary']
    original_packet = _scoped_value(program, model, example, intrinsic['original_packet'])
    original_exception = _scoped_value(program, model, example, intrinsic['original_exception'])
    old_packet = _scoped_value(program, model, example, intrinsic['old_packet'])
    assert old_packet.id != original_packet.id
    expected_categories = ((BuiltinExceptionCategory.STOP_ITERATION,) if static['route'] in
        ('stop-iteration', 'constructor-raise') else
        (BuiltinExceptionCategory.STOP_ITERATION, BuiltinExceptionCategory.STOP_ASYNC_ITERATION))
    assert tuple(row.handler.category for row, _, _ in terminal['matchers']) == expected_categories
    for row, occurrence, branch in terminal['matchers']:
        matcher = ProgramIndex(program).exception_match(row.operation)
        assert matcher['bool_binding']['match'] is True
        assert matcher['correlation']['match'] is True
        actual = _use(model, occurrence, row.input_use)
        _copied(index, model, actual.value, original_packet.id)
        result = _own(program, model, occurrence, row.normal_result)
        definition = definitions[row.branch]
        assert _use(model, branch, definition.terminator.condition).value == result.id
        transfer, = tuple(row for row in model.transfers if row.operation == branch)
        matches = (row.handler.category is BuiltinExceptionCategory.STOP_ITERATION and
                   static['route'] in ('stop-iteration', 'constructor-raise') or
                   row.handler.category is BuiltinExceptionCategory.STOP_ASYNC_ITERATION and
                   static['route'] == 'stop-async-iteration')
        assert transfer.successor_index == (0 if matches else 1)
        _current(index, program, model, occurrence)
    completion = definitions[child['completion'].operation]
    packet_use = next(identity for identity in completion.terminator.values
        if type(values[next(use.value for use in completion.uses if use.id == identity)]) is ProtocolValue
        and values[next(use.value for use in completion.uses if use.id == identity)].protocol is ProtocolValueKind.EXCEPTION_PACKET)
    packet = _value(model, _use(model, terminal['completion'], packet_use).value)
    assert packet.id != old_packet.id
    assert {row['caller_formal_definition'].location for row in child['outputs']
            if type(row['caller_formal_definition']) is StateVersionValue} == {
                values[identity].location for identity in intrinsic['entry_formals']
                if type(values[identity]) is StateVersionValue}
    output, = tuple(row for row in child['outputs'] if row['callee_use'].use == packet_use)
    assert output['callee_use'].value == packet.id
    actual_raise = definitions[next(row.operation for row in model.operations if row.id == terminal['body_raise'])]
    assert actual_raise.terminator.kind is TerminatorKind.RAISE
    actual_payload = _use(model, terminal['body_raise'], actual_raise.terminator.values[0])
    assert actual_payload.value == output['caller_formal'].id
    if static['route'] == 'ordinary':
        assert terminal['constructor'] is None and terminal['chaining'] == ()
        _copied(index, model, packet.id, original_packet.id)
    else:
        constructor = intrinsic['constructor']
        assert terminal['constructor'] is not None
        transfer, = tuple(row for row in model.transfers if row.operation == terminal['constructor'])
        selected = next(port for port in intrinsic['constructor_results']
                        if port.edge.successor_index == transfer.successor_index)
        edge = constructor.terminator.successors[transfer.successor_index]
        assert edge.kind is (ExitKind.RAISE if static['route'] == 'constructor-raise' else ExitKind.NORMAL)
        _current(index, program, model, terminal['constructor'])
        own = _own(program, model, terminal['constructor'], selected)
        assert own.id != original_packet.id
        if static['route'] == 'constructor-raise':
            assert terminal['chaining'] == ()
            _copied(index, model, packet.id, own.id)
        else:
            assert type(values[own.value]) is ReferenceValue
            assert terminal['chaining']
            fields = set()
            for operation in intrinsic['chaining']:
                if operation.id not in terminal['operations']:
                    continue
                occurrence = terminal['operations'][operation.id]
                before = _current(index, program, model, occurrence)
                after = index.state_at(OccurrencePoint(occurrence, OccurrencePhase.AFTER))
                references = tuple(use for use in operation.uses if type(values[use.value]) is ReferenceValue)
                assert len(references) >= 2
                actuals = tuple(_use(model, occurrence, use.id).value for use in references)
                assert own.id in actuals
                original, = tuple(actual for actual in actuals if actual != own.id)
                _copied(index, model, original, original_exception.id)
                for ordinal, access in enumerate(operation.accesses):
                    address = index.state_address(AccessRef(occurrence, ordinal), budget=_BUDGET)
                    assert address['canonical']['site'] == ExistingAccess(operation.id, ordinal)
                    assert address['before'].value == before[access.location]
                    if access.after is not None:
                        actual_after, = tuple(row for row in model.values if row.origin == occurrence and row.value == access.after)
                        assert after[access.location] == actual_after.id != before[access.location]
                    for item in address['items']:
                        if type(item['effect'].owner) is ReferenceOwner:
                            assert item['owner_use']['value'].id == own.id
                        for selector in item['effect'].path:
                            if type(selector) is ObjectField:
                                fields.add(selector.name)
            assert {'__cause__', '__context__'} <= fields
            packet_definition = intrinsic['packet_definition']
            producer = values[packet_definition.value].origin.operation
            component = _use(model, terminal['operations'][producer], packet_definition.exception)
            assert component.value == own.id
            assert packet.value == packet_definition.value
        assert packet.id != original_packet.id
    # The cursor's root is this selected intrinsic result, never the original
    # Stop packet. Conversion has already happened before the body terminal.
    continuation = index.completion_continuations(packet.id, terminal['body_call'], budget=_BUDGET)
    assert continuation['source'] == packet and continuation['anchor'].id == terminal['body_call']
    endpoint, = continuation['terminals']
    assert endpoint['operation'].id == terminal['body_raise']
    assert endpoint['root_binding']['match'] is True and endpoint['binding']['match'] is True
    assert endpoint['value'].id == actual_payload.value
    assert endpoint['crossed_suspend'] is False
    assert all(continuation[key] is False for key in _FLAGS)
    for ordinal, association in enumerate(example['body_drives']):
        driver = static['drivers'][ordinal]
        view = index.drive_execution(association.drive, budget=_BUDGET)
        assert view['association'] == association
        assert view['entry_bridge'] is True and view['path_complete'] is True
        assert association.outcome == example['body_occurrences'][ordinal][driver['outcome_source']]
        assert all(row['source_value'] is not None and row['formal'] is not None
                   for row in (*view['inputs'], *view['outputs']))
        session = view['session']
        assert session['source'] == driver['outcome']
        assert session['expected_post'] is (SessionPost.HOLD if ordinal == 0 else SessionPost.COMPLETE)
        target, = session['targets']
        assert target['post_established'] is True and target['update'] == driver['update']
        assert all(row['use'] is not None and row['value'] is not None and
                   row['current'] == row['value'].id for row in target['state_bindings'])
        host, = session['hosts']
        assert host['operation'].id == example['call_activations'][ordinal].completion
        assert host['definition'] == driver['host_terminal']
        assert all(view[key] is False for key in _FLAGS)
        if ordinal == 1:
            publication = ProgramIndex(program).body_publication(driver['publication'].operation)
            assert publication.commit == driver['publication']
            assert publication.commit.outcome.source == actual_raise.id
            assert publication.source.kind is TerminatorKind.RAISE
            declared = ProgramIndex(program).lifecycle_after(publication.commit.operation)
            assert declared.terminal.is_finished(publication.instance.use.value)
            assert host['adapter'] is None
            assert host['source_value'].id == actual_payload.value
            assert len(host['bindings']) == 1
            assert host['bindings'][0]['copy_status'] == 'DECLARED_ORIGINAL_COPY'
            assert _use(model, terminal['host'], driver['host_terminal'].terminator.values[0]).value == host['target_value'].id
            _current(index, program, model, terminal['body_raise'])
            _current(index, program, model, terminal['host'])
    assert not any(row.outcome.source in {intrinsic['constructor'].id, *(row.operation for row in intrinsic['matchers'])}
                   for row in program.body_outcome_commits)
    return packet, continuation


@pytest.mark.parametrize('route', ('stop-iteration', 'stop-async-iteration', 'ordinary', 'constructor-raise'))
def test_body_local_async_terminal_conversion_owns_its_current_packet_and_host(route):
    program, model, details = async_terminal_execution(route=route, instances=2)
    index = _index(program, model)
    assert len(model.body_activation_origins) == 2 and len(model.body_drive_executions) == 4
    assert len(model.call_activations) == 6
    assert len({example['creation'] for example in details['instances']}) == 2
    packets = tuple(_complete(index, program, model, details, number)[0] for number in range(2))
    assert packets[0].id != packets[1].id


@pytest.mark.parametrize('missing', ('intrinsic-call', 'constructor-input', 'chaining-owner', 'driver-input'))
def test_missing_conversion_input_or_exact_call_keeps_the_complete_sibling_independent(missing):
    keywords = {'intrinsic-call': 'missing_intrinsic_call', 'constructor-input': 'missing_constructor_input',
                'chaining-owner': 'missing_chaining_owner', 'driver-input': 'missing_driver_input'}
    program, model, details = async_terminal_execution(**{keywords[missing]: 0})
    index = _index(program, model)
    static, example = details['static'], details['instances'][0]
    intrinsic, terminal = static['intrinsic'], example['terminal']
    if missing == 'intrinsic-call':
        entries = index.call_entries(terminal['body_call'])
        assert entries['entries'] == () and entries['status'] == 'MISSING'
        assert any(gap.code == 'call_activation_missing' for gap in entries['gaps'])
        completion = intrinsic['completion']
        values = {row.id: row for row in program.values}
        packet_use = next(identity for identity in completion.terminator.values
            if type(values[next(use.value for use in completion.uses if use.id == identity)]) is ProtocolValue)
        source = _value(model, _use(model, terminal['completion'], packet_use).value)
        report = index.completion_continuations(source.id, terminal['body_call'], budget=_BUDGET)
        assert report['source'] == source and report['status'] == 'PARTIAL'
        assert 'completion_source_anchor_association_unproved' in report['gaps']
        endpoint, = report['terminals']
        assert endpoint['root_binding']['match'] is None
    elif missing == 'constructor-input':
        constructor = intrinsic['constructor']
        use = _state_use(program, constructor)
        occurrence = terminal['constructor']
        port = next(port for port in intrinsic['constructor_results'] if port.edge.successor_index == 0)
        own = _own(program, model, occurrence, port)
        transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
        definition = next(row for row in program.values if row.id == use.value)
        block = next(block for region in program.regions for block in region.blocks
                     if block.id == constructor.terminator.successors[transfer.successor_index].block)
        state = next(value for value in program.values if value.id in block.arguments
                     and type(value) is StateVersionValue and value.location == definition.location)
        actual, = tuple(value for value in model.values if value.origin == transfer.target and value.value == state.id)
        slot = next(argument.index for argument, formal in zip(
            constructor.terminator.successors[transfer.successor_index].arguments, block.arguments)
            if formal == state.id and type(argument) is CompletionResult)
        effect = InvokeBoundaryStateEffect(occurrence, UseRef(occurrence, use.id),
            ActualCompletionState(transfer.successor_index, slot, actual.id))
        address = index.state_address(effect, budget=_BUDGET)
        assert address['status'] == 'PARTIAL' and address['before'] is None
        assert any(gap['code'] == 'invoke_input_unobserved' for gap in address['gaps'])
        assert own is not None
    elif missing == 'chaining-owner':
        operation = next(row for row in intrinsic['chaining'] if row.id in terminal['operations'])
        site = next(row.site for row in program.state_address_refinements
                    if type(row.site) is ExistingAccess and row.site.operation == operation.id)
        address = index.state_address(AccessRef(terminal['operations'][operation.id], site.index), budget=_BUDGET)
        assert address['status'] == 'PARTIAL'
        owner, = tuple(item['owner_use'] for item in address['items'] if type(item['effect'].owner) is ReferenceOwner)
        assert owner['use'] is None and owner['value'] is None
        assert any(gap['code'] == 'state_address_operand_unobserved' for gap in address['gaps'])
    else:
        association = example['call_activations'][1]
        call = index.call_activation(association.id)
        use = _state_use(program, static['drivers'][1]['caller_call'])
        row, = tuple(row for row in call['inputs'] if row['actual_definition'].id == use.id)
        assert row['actual'] is None and row['actual_value'] is None and row['formal'] is not None
        assert any(gap.code == 'call_actual_unobserved' for gap in call['gaps'])
    _complete(index, program, model, details, 1)


def test_tiny_budget_keeps_both_actual_sources_and_all_terminal_session_targets():
    program, model, details = async_terminal_execution()
    index = _index(program, model)
    for example in details['instances']:
        for association in example['body_drives']:
            full = index.drive_execution(association.drive, budget=_BUDGET)
            limited = index.drive_execution(association.drive, budget=1)
            assert limited['association'] == association
            assert limited['outcome_candidates'] == full['outcome_candidates']
            assert limited['input_count'] == full['input_count']
            assert limited['output_count'] == full['output_count']
            assert limited['session']['source_candidates'] == full['session']['source_candidates']
            assert limited['session']['target_count'] == full['session']['target_count']
            assert limited['session']['source'] == full['session']['source']
            assert limited['budget']['truncated'] and limited['budget']['used'] == 1
            assert limited['cursor'] is not None and limited['status'] == 'PARTIAL'
            assert any(row['check_status'] == 'NOT_CHECKED' and row['compatibility'] is None
                       for row in (*limited['inputs'], *limited['outputs']))
            assert all(limited[key] is False for key in _FLAGS)

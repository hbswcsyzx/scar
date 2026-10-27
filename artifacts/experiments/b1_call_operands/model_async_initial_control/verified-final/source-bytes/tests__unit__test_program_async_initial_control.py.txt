"""Initial request state, associated body phase and effective operand compose."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.drivers import BodyResume, BodyStart, RawRequestKind
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost
from scar.ir.program.model import (
    AccessMode, Behavior, CompletionResult, DataValue, ExitKind, Footprint,
    FootprintKind, Operation, OperationResult, StateAccess, StateVersionValue,
    TerminatorKind,
)
from scar.ir.program.protocol_async import async_connections
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, OwnedUse, ReferenceIsNoneCondition,
    RequestOperandBinding, RequestProcessing,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program


_BUDGET = 1048576


def _core(program):
    return replace(program, protocol_scopes=(), protocol_operations=(), protocol_bindings=(),
                   protocol_call_inputs=(), protocol_result_consumers=())


def _report(program, *, budget=_BUDGET):
    return async_connections(ConnectionContext(program, index=ProgramIndex(program),
                                              budget=ValidityBudget(budget)))


def _row(program, operation):
    return next(row for row in program.protocol_operations
                if row.operation == operation and type(row.contract) is AdmissionPredicate)


def _inventory(program, details, view):
    inventory = view['inventory']
    assert inventory['predicates'] == details['initial_control']['predicates']
    assert inventory['processing'] == details['initial_control']['processing']
    assert inventory['drives'] == program.body_drives
    assert inventory['gates'] == program.final_body_gates
    assert inventory['associations'] == program.request_association_reads
    assert all(view[key] is False for key in ('source_runtime_verified',
        'runtime_identity_verified', 'value_identity_verified', 'transformation_authorized'))


def _selected_route(view, stage, *, terminal=False):
    wanted = tuple((operation, choice) for operation, choice in stage['path_choices'].items())
    routes = tuple(route for route in view['routes']
        if (route['terminal'] == stage['host_terminal'] if terminal else route['gate'] == stage['gate'])
        and all(dict((edge.operation, edge.successor_index) for edge in route['choices']).get(operation) == choice
                for operation, choice in wanted
                if any(edge.operation == operation for edge in route['choices'])))
    assert len(routes) == 1
    return routes[0]


@pytest.mark.parametrize('scenario,reject_raised', (
    ('created-none', False), ('created-reject', False),
    ('created-reject', True), ('suspended-new', False)),
    ids=('created-none-start', 'created-reject-own-normal',
         'created-reject-own-raise', 'yielded-new-nonNone-resume'))
def test_initial_asend_joint_control_keeps_real_sources_targets_and_all_ports(scenario, reject_raised):
    program, details = async_initial_control_program(scenario=scenario, reject_raised=reject_raised)
    require_valid(_core(program))
    require_valid(program)
    report = _report(program)
    assert not report['issues']
    view = report['initial_asend']
    _inventory(program, details, view)
    assert not view['issues'] and view['known_inventory_complete']
    assert len(program.resumable_creates) == 1
    assert len(program.async_request_creates) == (1 if scenario == 'created-none' else 2)
    assert all(request['latent'].kind is RawRequestKind.SEND for request in details['requests'])
    first_start = next(stage for stage in details['drivers'] if not stage['reject'])
    route = _selected_route(view, first_start)
    assert type(route['drive'].target) is BodyStart
    assert route['initial_step'] is True and route['body_created'] is True
    assert route['effective_is_none'] is True
    assert route['compatible_at_snapshot'] is True
    controls = first_start['initial_controls']
    selected = {edge.operation: edge.successor_index for edge in route['choices']}
    assert {controls['request']['branch']: 0, controls['phase']['branch']: 0,
            controls['none']['branch']: 0}.items() <= selected.items()
    assert all(predicate['binding']['match'] is True for predicate in route['predicates'])
    # None is selected from the actual first NEXT scheduler and independent
    # latent SEND operand, not from a nonexistent Start resume input.
    assert not first_start['drive'].resume_inputs
    assert first_start['scheduler'].kind is RawRequestKind.NEXT
    assert first_start['request']['operand'].origin.value is None
    body_predicate = _row(program, controls['phase']['predicate'])
    none_predicate = _row(program, controls['none']['predicate'])
    body_view = next(item['view'] for item in view['predicates'] if item['record'] == body_predicate)
    none_view = next(item['view'] for item in view['predicates'] if item['record'] == none_predicate)
    assert body_view['body_binding']['match'] is True and body_view['associations']
    assert none_view['binding']['match'] is True and none_view['operand_bindings']
    if scenario == 'created-reject':
        rejected = details['drivers'][0]
        reject_route = _selected_route(view, rejected, terminal=True)
        assert reject_route['drive'] is None and reject_route['gate'] is None
        assert reject_route['initial_step'] is True and reject_route['body_created'] is True
        assert reject_route['effective_is_none'] is False
        assert reject_route['processing']
        update = rejected['reject_complete']
        assert update.post is SessionPost.COMPLETE and update.binding is LifecyclePostBinding.AFTER_OPERATION
        assert not any(type(row) is AsyncSessionOutcome and row.update == update.operation
                       for row in program.protocol_bindings)
        assert not any(row.operation == update.operation for row in program.body_outcome_commits)
        request_index = ProgramIndex(program)
        assert request_index.source_binding(details['requests'][0]['result'],
            OwnedUse(update.operation, update.request), budget=_BUDGET)['match'] is True
        assert details['requests'][0]['result'] != details['requests'][1]['result']
        helper = next(operation for operation in program.operations
                      if operation.id == details['initial_control']['reject_helper'])
        rows = tuple(row for row in details['initial_control']['processing'] if row.operation == helper.id)
        assert len(rows) == 2
        for row in rows:
            assert tuple(binding.request_ordinal for binding in row.contract.operand_bindings) == (0,)
            edge = helper.terminator.successors[row.contract.result.edge.successor_index]
            assert edge.kind is (ExitKind.NORMAL if row.contract.result.edge.successor_index == 0 else ExitKind.RAISE)
            assert tuple(argument.index for argument in edge.arguments if type(argument) is CompletionResult) == tuple(
                range(1 + len(program.locations)))
            landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
            own = tuple(formal for actual, formal in zip(edge.arguments, landing.arguments)
                        if type(actual) is CompletionResult)
            terminal = next(operation for operation in program.operations if operation.id == landing.operations[-1])
            assert terminal.terminator.kind is TerminatorKind.RAISE
            assert tuple(next(use.value for use in terminal.uses if use.id == identity)
                         for identity in terminal.terminator.values) == own
        selected_processing = next(item for item in reject_route['processing_views']
            if item['record'].contract.result.edge.successor_index == int(reject_raised))
        assert selected_processing['applicable']
        assert all(binding['report']['match'] is True for binding in selected_processing['operand_bindings'])
        assert selected_processing['source_binding']['match'] is True
        for binding in selected_processing['operand_bindings']:
            assert binding['raw_operand_binding']['match'] is None
            assert binding['report']['semantic_projection'] is True
            assert binding['report']['raw_operand_binding'] == binding['raw_operand_binding']
            assert binding['report']['transformation_authorized'] is False
    if scenario == 'suspended-new':
        last = details['drivers'][-1]
        route = _selected_route(view, last)
        assert type(route['drive'].target) is BodyResume
        assert route['drive'].target.suspend == details['body_definition']['async_yield'].id
        assert route['initial_step'] is True and route['body_created'] is False
        assert route['effective_is_none'] is None
        assert route['compatible_at_snapshot'] is True
        assert last['request'] is details['requests'][1]
        assert last['request']['operand'].origin.value == 61
        assert details['drivers'][-2]['update'].post is SessionPost.COMPLETE


def _mutated(program, details, kind):
    stage = details['drivers'][0]
    controls = stage['initial_controls']
    operations = {row.id: row for row in program.operations}
    if kind in ('body', 'operand'):
        identity = controls['phase']['predicate'] if kind == 'body' else controls['none']['predicate']
        row = _row(program, identity)
        subject = row.contract.subject
        identity_use = subject.instance_use if kind == 'body' else subject.input_use
        operation = operations[identity]
        # Both are legal Reference SSA inputs; only the protocol role differs.
        changed = replace(operation, uses=tuple(replace(use, value=stage['interface'].receiver)
            if use.id == identity_use else use for use in operation.uses))
        return replace(program, operations=tuple(changed if row.id == changed.id else row for row in program.operations)), row
    if kind == 'ordinal':
        target = details['initial_control']['processing'][0]
        old, = target.contract.operand_bindings
        changed = replace(target, contract=replace(target.contract,
            operand_bindings=(RequestOperandBinding(1, old.operation_use),)))
        return replace(program, protocol_operations=tuple(changed if row == target else row
                                                          for row in program.protocol_operations)), target
    row = _row(program, controls['none']['predicate'])
    branch = operations[row.contract.branch]
    identity = OperationID('initial.independent.bool')
    value = DataValue(ValueID('initial.independent.bool.value'), stage['driver_region'].id,
                      OperationResult(identity, 0), 'builtins.bool')
    producer = Operation(identity, 'independent boolean producer', (Behavior.COMPUTE,),
                         results=(value.id,), effects_complete=True)
    changed = replace(branch, uses=tuple(replace(use, value=value.id)
        if use.id == branch.terminator.condition else use for use in branch.uses))
    graph = replace(program, values=(*program.values, value),
        operations=(*(changed if operation.id == changed.id else operation for operation in program.operations), producer),
        regions=tuple(replace(region, blocks=tuple(replace(block,
            operations=(*block.operations[:-1], identity, branch.id)) if branch.id in block.operations else block
            for block in region.blocks)) if region.id == stage['driver_region'].id else region for region in program.regions))
    return graph, row


@pytest.mark.parametrize('kind,code', (
    ('body', 'async_initial_body'), ('operand', 'async_initial_operand'),
    ('ordinal', 'async_initial_processing_ordinal'), ('bool', 'admission_bool_source')))
def test_independent_roles_and_bool_are_not_joint_initial_control(kind, code):
    program, details = async_initial_control_program()
    program, original = _mutated(program, details, kind)
    require_valid(_core(program))
    errors = validate(program)
    assert code in {issue.code for issue in errors}
    assert any(issue.code == code and str(original.operation) in issue.path for issue in errors)


def test_callback_keeps_historical_bool_legal_but_current_phase_support_unknown():
    program, details = async_initial_control_program()
    stage = details['drivers'][0]
    predicate = _row(program, stage['initial_controls']['phase']['predicate'])
    operations = {row.id: row for row in program.operations}
    read, branch = operations[predicate.operation], operations[predicate.contract.branch]
    access, = read.accesses
    before = next(use for use in read.uses if use.id == access.before)
    identity = OperationID('initial.callback.write')
    after = StateVersionValue(ValueID('initial.callback.after'), stage['driver_region'].id,
                              OperationResult(identity, 0), access.location)
    callback = Operation(identity, 'declared callback modifies phase support',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (before,), (after.id,),
        (StateAccess(access.location, before.id, AccessMode.READ_WRITE, after.id,
                     Footprint(FootprintKind.WHOLE)),), effects_complete=True)
    # The callback owns a distinct Use, while every outgoing state port now
    # carries its true post version. The old boolean remains an ordinary value.
    from scar.ir.program.ids import UseID
    callback_use = replace(before, id=UseID('initial.callback.before'))
    callback = replace(callback, uses=(callback_use,), accesses=(replace(callback.accesses[0], before=callback_use.id),))
    changed = replace(branch, uses=tuple(replace(use, value=after.id)
        if use.value == before.value else use for use in branch.uses))
    program = replace(program, values=(*program.values, after),
        operations=(*(changed if operation.id == branch.id else operation for operation in program.operations), callback),
        regions=tuple(replace(region, blocks=tuple(replace(block,
            operations=(*block.operations[:-1], callback.id, branch.id)) if branch.id in block.operations else block
            for block in region.blocks)) if region.id == stage['driver_region'].id else region for region in program.regions))
    require_valid(_core(program))
    report = _report(program)
    route = _selected_route(report['initial_asend'], stage)
    assert route['compatible_at_snapshot'] is None and route['status'] == 'PARTIAL'
    body = next(item for item in route['predicates'] if item['record'] == predicate)
    assert body['boolean']['match'] is True
    assert body['binding']['match'] is not True


def test_missing_none_attachment_retains_original_bool_branch_helper_and_gates():
    program, details = async_initial_control_program()
    original = _row(program, details['drivers'][0]['initial_controls']['none']['predicate'])
    changed = replace(program, protocol_operations=tuple(row for row in program.protocol_operations if row != original))
    require_valid(_core(changed))
    report = _report(changed)['initial_asend']
    assert changed.operations == program.operations and changed.values == program.values
    assert report['inventory']['processing'] == details['initial_control']['processing']
    assert report['inventory']['gates'] == program.final_body_gates
    assert report['inventory']['drives'] == program.body_drives
    assert original not in report['inventory']['predicates']
    route = _selected_route(report, details['drivers'][0])
    assert route['effective_is_none'] is None
    assert route['compatible_at_snapshot'] is None


def test_created_start_cannot_reuse_latent_none_when_first_scheduler_is_nonNone():
    from scar.ir.program.drivers import RawRequestDefinition
    from scar.ir.program.model import LiteralOrigin
    from tests.fixtures.program_driver_graphs import _use

    program, details = async_initial_control_program()
    stage = details['drivers'][0]
    definition = stage['scheduler']
    values = {value.id: value for value in program.values}
    pack_id = values[definition.value].origin.operation
    pack = next(operation for operation in program.operations if operation.id == pack_id)
    nonnone = next(value for value in program.values
                   if type(value.origin) is LiteralOrigin and value.origin.value == 61)
    operand = _use('initial.scheduler.override.operand', nonnone.id)
    changed = replace(pack, uses=(operand,))
    replacement = RawRequestDefinition(definition.value, RawRequestKind.SEND, (operand.id,))
    program = replace(program,
        operations=tuple(changed if operation.id == pack_id else operation for operation in program.operations),
        raw_driver_requests=tuple(replacement if row == definition else row for row in program.raw_driver_requests))
    require_valid(_core(program))
    assert details['requests'][0]['operand'].origin.value is None
    assert type(stage['drive'].target) is BodyStart
    # Public validation rejects this known wrong original connection before
    # ProgramIndex or a derived report can be constructed for it.
    none_row = _row(program, stage['initial_controls']['none']['predicate'])
    issues = validate(program)
    assert any(issue.code == 'async_initial_operand' and str(none_row.operation) in issue.path
               for issue in issues)
    assert program.body_drives == tuple(item['drive'] for item in details['drivers'])
    assert tuple(row for row in program.protocol_operations if type(row.contract) is AdmissionPredicate) == (
        details['initial_control']['predicates'])
    assert tuple(row for row in program.protocol_operations if type(row.contract) is RequestProcessing
                 and row in details['initial_control']['processing']) == details['initial_control']['processing']
    with pytest.raises(ValueError, match='async_initial_operand'):
        ProgramIndex(program)


def test_tiny_budget_preserves_whole_joint_inventory_and_never_grants_a_prefix():
    program, details = async_initial_control_program(scenario='created-reject')
    require_valid(program)
    shared = ValidityBudget(1)
    report = async_connections(ConnectionContext(program, index=ProgramIndex(program), budget=shared))
    view = report['initial_asend']
    _inventory(program, details, view)
    assert shared.truncated and shared.used == shared.limit == 1
    assert view['cursor'] is not None and report['cursor'] is not None
    assert 'protocol_budget_exhausted' in view['gaps']
    assert all(route['compatible_at_snapshot'] is not True for route in view['routes'])

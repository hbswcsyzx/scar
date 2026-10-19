"""Four original F12 source boundaries, without native execution authority.

The native self case is a complete supplied zero-cut graph and capture. The
general-method negatives retain their own NORMAL result and actual advance;
they do not classify an arbitrary object from a label or unresolved type.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance
from scar.ir.execution.ids import CallActivationID, HostThreadInstanceID, ProcessInstanceID, RunID
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.literals import PythonLiteral
from scar.ir.program.evaluated_sources import evaluated_sources
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.literal_sources import UninterpretedConstant
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSuccessor,
    ExitKind, ExitPort, InvokeLiteralResult, LiteralEvaluation, LiteralOrigin,
    Operation, ProtocolValue, ReferenceValue, Region, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_await_records import CoroutineAwaitWrapper, WrapperHeldBody
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import (
    DriverSubject, HostTerminal, OutcomeAdapter, OutcomeAdapterRule, OwnedUse,
    ProtocolClause, ProtocolProfile,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind, SuspendTerminator
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_acquisition_graphs import await_acquisition_program
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter
from tests.fixtures.program_protocol_graphs import _scope


_BUDGET = 1_048_576
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')
_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _classified(graph, details):
    core = _core(graph)
    require_valid(core)
    expected = details['await_call']['ports'][0]
    actual = OwnedUse(details['advance']['operation'].id, details['advance_receiver'].id)
    context = ConnectionContext(core, index=ProgramIndex(core), budget=ValidityBudget(_BUDGET))
    report = evaluated_sources(context, expected, actual, role='GENERAL_RETURN')
    assert report['binding']['match'] is True
    assert report['inventory_complete'] is True
    assert report['cases']
    assert all(case['current'] is True for case in report['cases'])
    assert report['source_runtime_verified'] is False
    assert report['runtime_identity_verified'] is False
    assert report['transformation_authorized'] is False
    return report


def _native_program():
    graph, details = await_resume_program(zero_cut=True, extra_creation=False)
    graph, final_rows = with_final_adapter(graph, details)
    template, implementation = await_final_region_program(zero_cut=True, depth=1)
    extract = details['extract']
    original = implementation['original_extract']
    assert (extract.uses, extract.completions, extract.terminator) == (
        original.uses, original.completions, original.terminator)
    # Only the genuine child implementation is grafted. In particular, the
    # template's second Create and root capture are not copied into this graph.
    region_ids = {region.id for region in implementation['stage_regions']}
    operation_ids = {identity for region in implementation['stage_regions']
                     for block in region.blocks for identity in block.operations}
    extract = replace(extract, callee=implementation['parent_call'].callee)
    graph = replace(graph,
        regions=(*graph.regions, *(row for row in template.regions if row.id in region_ids)),
        operations=tuple(extract if row.id == extract.id else row for row in graph.operations)
            + tuple(row for row in template.operations if row.id in operation_ids),
        values=(*graph.values, *(row for row in template.values if row.region in region_ids)),
        control_scopes=(*graph.control_scopes,
            *(row for row in template.control_scopes if row.region in region_ids)),
        protocol_result_consumers=(*graph.protocol_result_consumers,
                                   *implementation['conversion_receipts']))
    body, = graph.resumable_bodies
    assert body.kind is ResumableKind.GENERATOR_COROUTINE
    driver_regions = {row.region for row in graph.driver_interfaces if row.body == body.region}
    scopes = {row.id for row in graph.protocol_scopes if type(row.subject) is DriverSubject
              and row.subject.interface_region in driver_regions}
    conversions = tuple(row for row in graph.protocol_operations if row.scope in scopes
        and type(row.contract) is OutcomeAdapter
        and row.contract.rule is OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION)
    assert conversions
    converted_keys = {(row.scope, row.operation, row.slot) for row in conversions}

    def migration(site):
        if (site.scope, site.operation, site.slot) in converted_keys:
            assert site.clause is ProtocolClause.DIRECT_HOST_ADAPTER
            return replace(site, clause=ProtocolClause.AWAIT_COMPLETION_ADAPTER)
        return site

    graph = replace(graph,
        resumable_bodies=(replace(body, kind=ResumableKind.COROUTINE),),
        protocol_scopes=tuple(replace(row, profile=ProtocolProfile.COROUTINE_BODY_V1)
            if row.id in scopes else row for row in graph.protocol_scopes),
        protocol_operations=tuple(replace(row,
            clause=ProtocolClause.AWAIT_COMPLETION_ADAPTER,
            contract=replace(row.contract,
                rule=OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION))
            if row in conversions else row for row in graph.protocol_operations),
        protocol_result_consumers=tuple(replace(row, site=migration(row.site))
            for row in graph.protocol_result_consumers))
    return graph, {**details, 'extract': extract, 'final_rows': final_rows,
        'stage_records': implementation['stage_records'],
        'conversion_operations': {row.operation for row in conversions}}


def _native_capture(program, details):
    """Capture all canonical paths anew, including the actual child call."""
    evidence = MissingEvidence('supplied native-self ports; no Python/native execution proof')
    run, process = RunID('native.self'), ProcessInstanceID('native.self')
    thread = HostThreadInstanceID('native.self')
    point = EvidencePoint(run, process, evidence)
    combined = {name: [] for name in _TABLES}

    def activation(region, path, label):
        rows, owner, visits, operations = _activation(
            program, region, path, label, point, thread)
        for name in _TABLES:
            combined[name].extend(rows[name])
        return owner, visits, operations

    caller, caller_visits, caller_ops = activation(
        details['caller'].id, details['caller_path'], 'native.self.caller')
    driver, = details['drivers']
    driver_activation, driver_visits, driver_ops = activation(
        driver['driver_region'].id, driver['path'], 'native.self.driver')
    body_path = _body_path(program, details['body'], details['body'].entry,
                           driver['outcome_source'])
    body_activation, body_visits, body_ops = activation(
        details['body'].id, body_path, 'native.self.body')
    stage, = details['stage_records']
    child_activation, child_visits, child_ops = activation(
        stage['region'].id, stage['paths'][ExitKind.NORMAL], 'native.self.extractor')
    driver_call = CallActivation(CallActivationID('native.self.driver.call'),
        caller_ops[driver['caller_call'].id], driver_activation, driver_visits[0],
        driver_ops[driver['host_terminal'].id], evidence)
    child_call = CallActivation(CallActivationID('native.self.extractor.call'),
        caller_ops[details['extract'].id], child_activation, child_visits[0],
        child_ops[stage['terminals'][ExitKind.NORMAL].id], evidence)
    drive = BodyDriveExecution(driver_ops[driver['drive'].operation], body_activation,
        body_visits[0], body_ops[driver['outcome_source']], evidence)
    origin = BodyActivationOrigin(body_activation,
        caller_ops[details['primary_creation'].operation], evidence)
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, evidence),),
        processes=(ProcessInstance(process, run, 701, evidence),),
        threads=(HostThreadInstance(thread, process, 702, evidence),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=(driver_call, child_call), body_drive_executions=(drive,),
        body_activation_origins=(origin,))
    return model, {'caller': caller, 'caller_visits': caller_visits, 'caller_ops': caller_ops,
        'driver_ops': driver_ops, 'body_ops': body_ops, 'child_ops': child_ops,
        'driver_call': driver_call, 'child_call': child_call, 'drive': drive, 'origin': origin}


def _own_result(program, model, occurrence, port):
    assert type(port) is InvokeLiteralResult
    operation = next(row for row in program.operations if row.id == port.edge.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    assert transfer.successor_index == port.edge.successor_index
    edge = operation.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
        if type(actual) is CompletionResult and actual.index == port.result.index)
    return next(row for row in model.values if row.origin == transfer.target and row.value == formal)


def test_native_coroutine_self_no_wrapper_has_a_complete_zero_cut_supplied_chain():
    graph, details = _native_program()
    require_valid(_core(graph))
    require_valid(graph)
    body, = graph.resumable_bodies
    assert body.kind is ResumableKind.COROUTINE
    assert len(graph.resumable_creates) == 1
    assert not any(type(op.terminator) is SuspendTerminator for op in graph.operations)
    assert not any(type(row.contract) is CoroutineAwaitWrapper for row in graph.protocol_operations)
    assert not any(type(row) is WrapperHeldBody for row in graph.protocol_bindings)
    get_row = details['get_rows'][0]
    context = ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(_BUDGET))
    classification = evaluated_sources(context, get_row.contract.expected,
        OwnedUse(get_row.operation, get_row.contract.operand_use), role='DIRECT_INPUT')
    assert classification['classification_complete'] is True
    assert classification['cases']
    assert all(case['kind'] is ResumableKind.COROUTINE and case['current'] is True
               for case in classification['cases'])
    report = ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=_BUDGET)['connections']['families']['await']
    assert report['issues'] == ()
    driver, = details['drivers']
    static_outcome, = tuple(row for row in report['outcomes']
        if row['drive_outcome'] == DriveOutcomeRef(driver['drive'].operation, driver['outcome_source'])
        and row['advance_operation'] == driver['caller_call'].id)
    assert static_outcome['kind'] == 'RETURN_COMPLETION'
    static_consumers = tuple(row for row in static_outcome['consumers']
        if row['actual'] == details['extract_input'] and row['requires_final_extraction'] is True)
    assert static_consumers
    for consumer in static_consumers:
        assert consumer['binding']['match'] is True
        assert consumer['final_rows'] == details['final_rows']
        assert {leg['kind'] for leg in consumer['legs']} == {ExitKind.NORMAL, ExitKind.RAISE}
        assert len(consumer['implementation']['frames']) == 1

    model, captured = _native_capture(graph, details)
    validity = validate_execution(model, graph)
    assert validity.valid, validity.issues
    index = ExecutionIndex(model, graph)
    view = index.drive_execution(captured['drive'].drive, budget=_BUDGET)
    assert view['association'] == captured['drive']
    assert view['activation'].id == captured['origin'].activation
    assert view['outcome'].id == captured['body_ops'][driver['outcome_source']]
    dynamic = index.await_body_links(details['acquisition_scope'], budget=_BUDGET)
    selected = tuple(item for job in dynamic['jobs'] for item in job['occurrences']
        if item.get('advance_selected') is True)
    assert selected
    for item in selected:
        assert item['advance'].id == captured['driver_call'].caller
        assert {row['occurrence'].id for row in item['matched_sources']} == {
            captured['caller_ops'][details['get'].id]}
        assert any(route['drive_occurrence'].id == captured['drive'].drive
                   for route in item['routes'])
    outcome, = tuple(row for row in dynamic['outcomes']
        if row['definition']['key'] == static_outcome['key'])
    occurrence, = tuple(row for row in outcome['occurrences']
        if row['advance'].id == captured['driver_call'].caller
        and row['drive'].id == captured['drive'].drive)
    assert occurrence['body_outcome'].id == captured['drive'].outcome
    conversion, = tuple(row for row in occurrence['conversion_legs'] if row['selected'] is True)
    assert conversion['occurrence'].operation in details['conversion_operations']
    assert conversion['definition']['role'] == 'COMPLETION'
    packet, = conversion['packets']
    assert packet['binding']['match'] is True
    assert packet['exception_value'].id == conversion['own_value'].id
    assert packet['value'].id != conversion['own_value'].id
    consumer, = tuple(row for row in occurrence['consumers']
        if row['definition']['actual'] == details['extract_input'] and row['selected'] is True)
    assert consumer['operation'].id == captured['child_call'].caller
    assert consumer['binding']['match'] is True
    assert consumer['definition']['requires_final_extraction'] is True
    final_leg, = tuple(row for row in consumer['legs'] if row['selected'] is True)
    assert final_leg['definition']['kind'] is ExitKind.NORMAL
    own = _own_result(graph, model, captured['child_call'].caller,
                       final_leg['definition']['own_result'])
    assert final_leg['own_value'].id == own.id
    final_target, = tuple(row for row in final_leg['targets']
        if row['definition'] == HostTerminal(details['final'].id))
    assert final_target['operation'].id == captured['caller_ops'][details['final'].id]
    assert final_target['binding']['match'] is True
    assert final_target['binding']['source_value'].id == own.id
    assert final_leg['states']
    assert all(row['binding']['match'] is True for row in final_leg['states'])
    implementation = consumer['implementation']
    frame, = implementation['frames']
    assert frame['call']['association'] == captured['child_call']
    assert frame['completion'].id == captured['child_call'].completion
    assert any(path['status'] == 'DECLARED' and path['binding']['match'] is True
        for stage in implementation['stages'] for leg in stage['legs']
        for result in leg['results'] for path in result['paths'])
    assert all(report[flag] is False and dynamic[flag] is False for flag in _FLAGS)
    assert all(implementation[flag] is False for flag in _FLAGS)


def test_general_await_known_coroutine_return_cannot_be_continued_as_an_iterator():
    graph, details = await_acquisition_program()
    body = details['created_body']
    wrong = replace(graph, resumable_bodies=tuple(
        replace(row, kind=ResumableKind.COROUTINE) if row == body else row
        for row in graph.resumable_bodies))
    assert wrong.operations == graph.operations and wrong.regions == graph.regions
    assert wrong.values == graph.values and wrong.resumable_creates == graph.resumable_creates
    assert wrong.protocol_operations == graph.protocol_operations
    classified = _classified(wrong, details)
    assert classified['classification_complete'] is True
    assert all(row['kind'] is ResumableKind.COROUTINE and row['create'] == details['create']
               for row in classified['cases'])
    assert 'protocol_await_return_qualification' in {issue.code for issue in validate(wrong)}


def _literal_return_callee(graph, details):
    """A genuine N/R callee: perform P, then its NORMAL returns exact Ref 7.

    P's RAISE packet and each completion's current state are returned on their
    own exits. No extra exit is fabricated for a NORMAL-only identity helper.
    """
    original = details['await_call']['operation']
    values = {row.id: row for row in graph.values}
    uses = {row.id: row for row in original.uses}
    region_id, entry_id = RegionID('general.literal.callee'), BlockID('general.literal.entry')
    formals = tuple(replace(values[uses[identity].value],
        id=ValueID(f'general.literal.input.{slot}'), region=region_id,
        origin=BlockArgument(entry_id, slot))
        for slot, identity in enumerate(original.invoke_arguments))
    primitive_id = OperationID('general.literal.primitive')
    arguments = tuple(Use(UseID(f'general.literal.argument.{slot}'), value.id,
        uses[identity].role) for slot, (identity, value) in
        enumerate(zip(original.invoke_arguments, formals)))
    literal = ReferenceValue(ValueID('general.literal.seven'), region_id, LiteralOrigin(7), targets=())
    additions, operations, blocks, successors, exits, terminals = [*formals, literal], [], [], [], [], {}
    signatures = {row.kind: row for row in original.completions}
    for number, edge in enumerate(original.terminator.successors):
        landing_id = BlockID(f'general.literal.landing.{number}')
        signature = signatures[edge.kind]
        outer_block = next(block for region in graph.regions for block in region.blocks
                           if block.id == edge.block)
        produced = []
        for slot in range(len(signature.types)):
            outer_formal, = tuple(formal for actual, formal in zip(edge.arguments, outer_block.arguments)
                if type(actual) is CompletionResult and actual.index == slot)
            produced.append(replace(values[outer_formal],
                id=ValueID(f'general.literal.output.{number}.{slot}'), region=region_id,
                origin=BlockArgument(landing_id, slot)))
        produced = tuple(produced)
        additions.extend(produced)
        actual_outputs = (literal, *produced[1:]) if edge.kind is ExitKind.NORMAL else produced
        exit_uses = tuple(Use(UseID(f'general.literal.exit.{number}.{slot}'), value.id,
            UseRole.STATE_CONTENT if type(value) is StateVersionValue else
            UseRole.PROTOCOL if type(value) is ProtocolValue else UseRole.REFERENCE)
            for slot, value in enumerate(actual_outputs))
        label = 'normal' if edge.kind is ExitKind.NORMAL else 'failure'
        terminal = Operation(OperationID(f'general.literal.exit.{number}'),
            'actual literal return or original primitive exception', (Behavior.CONTROL,),
            exit_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN if edge.kind is ExitKind.NORMAL
                else TerminatorKind.RAISE, exit=label, values=tuple(use.id for use in exit_uses)))
        operations.append(terminal)
        terminals[edge.kind] = terminal
        blocks.append(Block(landing_id, tuple(row.id for row in produced), (terminal.id,)))
        successors.append(CompletionSuccessor(edge.kind, landing_id,
            tuple(CompletionResult(slot) for slot in range(len(produced)))))
        exits.append(ExitPort(label, edge.kind, signature.types))
    primitive = Operation(primitive_id, 'original N/R computation before literal return',
        (Behavior.CONTROL,), arguments, effects_complete=False,
        invoke_arguments=tuple(use.id for use in arguments), completions=original.completions,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
    entry = Block(entry_id, tuple(row.id for row in formals), (primitive.id,))
    blocks = (entry, *blocks)
    region = Region(region_id, 'known method implementation returning literal',
        entry_id, blocks, tuple(exits), parent=graph.root)
    call = replace(original, callee=region_id)
    changed = replace(graph, regions=(*graph.regions, region),
        operations=tuple(call if row.id == call.id else row for row in graph.operations)
            + (primitive, *operations), values=(*graph.values, *additions),
        control_scopes=(*graph.control_scopes, _scope(region_id, blocks)))
    return changed, {'region': region, 'primitive': primitive, 'literal': literal,
                     'terminals': terminals, 'call': call}


@pytest.mark.parametrize('representation', ('own-normal-literal', 'known-callee-return'))
def test_general_await_exact_builtin_return_cannot_be_continued_as_an_iterator(representation):
    graph, details = await_acquisition_program()
    call = details['await_call']['operation']
    graph = replace(graph, resumable_creates=tuple(
        row for row in graph.resumable_creates if row.operation != call.id))
    assert not graph.resumable_creates
    port = details['await_call']['ports'][0]
    if representation == 'own-normal-literal':
        graph = replace(graph, literal_evaluations=(*graph.literal_evaluations,
            LiteralEvaluation(port, PythonLiteral.from_python(7))))
        assert call.callee is None
    else:
        graph, implementation = _literal_return_callee(graph, details)
        normal = implementation['terminals'][ExitKind.NORMAL]
        assert normal.uses[0].value == implementation['literal'].id
        assert implementation['literal'].origin == LiteralOrigin(7)
        assert implementation['literal'].targets == ()
        assert {exit_.kind for exit_ in implementation['region'].exits} == {ExitKind.NORMAL, ExitKind.RAISE}
        assert implementation['call'].uses == call.uses
        assert implementation['call'].terminator == call.terminator
        assert implementation['call'].completions == call.completions
    classification = _classified(graph, details)
    assert classification['classification_complete'] is True
    assert all(row['kind'] == 'NON_ITERATOR' for row in classification['cases'])
    assert details['advance_receiver'].value == details['iterator_value']
    assert 'protocol_await_return_qualification' in {issue.code for issue in validate(graph)}

    if representation == 'own-normal-literal':
        # Exact content and uninterpreted content are separate declarations;
        # the latter cannot become known NON_ITERATOR from the operation label.
        unknown = replace(graph, literal_evaluations=tuple(
            replace(row, literal=UninterpretedConstant('opaque constant contents are not classified'))
            if row.site == port else row for row in graph.literal_evaluations))
        unresolved = _classified(unknown, details)
        assert unresolved['classification_complete'] is False
        assert all(row['kind'] is None for row in unresolved['cases'])
        require_valid(unknown)

"""Self-await eligibility is separate from a generator's legal NEXT drive.

Only independent known body kind and its exact driver annotations change in
this negative. The Get own NORMAL, actual advance, body, state and final N/R
consumer remain the same canonical records. No native applicability is proved.
"""
from dataclasses import replace

from scar.ir.program.drivers import BodyStart, RawRequestKind
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, TerminatorKind
from scar.ir.program.protocol_await_records import AwaitAcquisition
from scar.ir.program.protocols import (
    DriverSubject, OutcomeAdapter, OutcomeAdapterRule, ProtocolClause, ProtocolProfile,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind, SuspendTerminator
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter
from tests.fixtures.program_driver_graphs import driver_program


_BUDGET = 1_048_576


def _complete_self_await():
    graph, details = await_resume_program(zero_cut=True, extra_creation=False)
    graph, final_rows = with_final_adapter(graph, details)
    return graph, {**details, 'final_rows': final_rows}


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _ordinary_generator_variant(graph):
    body, = graph.resumable_bodies
    assert body.kind is ResumableKind.GENERATOR_COROUTINE
    driver_regions = {interface.region for interface in graph.driver_interfaces
                      if interface.body == body.region}
    original_scopes = tuple(scope for scope in graph.protocol_scopes
        if type(scope.subject) is DriverSubject
        and scope.subject.interface_region in driver_regions)
    assert original_scopes
    assert all(scope.profile is ProtocolProfile.GENERATOR_COROUTINE_BODY_V1
               for scope in original_scopes)
    identities = {scope.id for scope in original_scopes}
    adapter_rows = tuple(row for row in graph.protocol_operations
        if row.scope in identities and type(row.contract) is OutcomeAdapter)
    assert adapter_rows
    assert all(row.clause is ProtocolClause.DIRECT_HOST_ADAPTER
        and row.contract.rule is OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION
        for row in adapter_rows)
    changed = replace(graph,
        resumable_bodies=(replace(body, kind=ResumableKind.GENERATOR),),
        protocol_scopes=tuple(replace(scope, profile=ProtocolProfile.GENERATOR_BODY_V1)
            if scope.id in identities else scope for scope in graph.protocol_scopes),
        protocol_operations=tuple(replace(row, clause=ProtocolClause.HOST_ADAPTER)
            if row in adapter_rows else row for row in graph.protocol_operations))
    return changed, original_scopes, adapter_rows


def test_generator_coroutine_self_await_keeps_get_body_return_and_both_final_completions():
    graph, details = _complete_self_await()
    require_valid(_core(graph))
    require_valid(graph)
    body, = graph.resumable_bodies
    create, = graph.resumable_creates
    driver, = details['drivers']
    assert body.kind is ResumableKind.GENERATOR_COROUTINE
    assert create.body == body.region
    assert type(driver['drive'].target) is BodyStart
    assert not any(type(operation.terminator) is SuspendTerminator for operation in graph.operations)
    get = details['get']
    normal_index, normal = next((index, edge) for index, edge in
        enumerate(get.terminator.successors) if edge.kind is ExitKind.NORMAL)
    assert normal.arguments[0] == CompletionResult(0)
    call = driver['caller_call']
    assert call.terminator.kind is TerminatorKind.INVOKE
    receiver = next(use for use in call.uses if use.id == call.invoke_arguments[0])
    landing = next(block for region in graph.regions for block in region.blocks
                   if block.id == normal.block)
    assert receiver.value == landing.arguments[0]
    assert any(row.contract.output == InvokeLiteralResult(
        ControlEdgeReference(details['extract'].id, slot), CompletionResult(0))
        for slot in range(len(details['extract'].terminator.successors))
        for row in details['final_rows'])
    report = ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=_BUDGET)['connections']['families']['await']
    assert report['issues'] == ()
    assert any(job['source_operation'] == get.id and job['source'].slot == normal_index
        and job['advance_operation'] == call.id and job['binding']['match'] is True
        for job in report['inventory']['jobs'])
    outcome, = tuple(row for row in report['outcomes']
        if row['drive_outcome'] == DriveOutcomeRef(driver['drive'].operation, driver['outcome_source'])
        and row['advance_operation'] == call.id)
    assert outcome['kind'] == 'RETURN_COMPLETION'
    completion_consumers = tuple(consumer for consumer in outcome['consumers']
        if consumer['actual'] == details['extract_input']
        and consumer['requires_final_extraction'] is True)
    assert completion_consumers
    for consumer in completion_consumers:
        assert consumer['binding']['match'] is True
        assert consumer['final_rows'] == details['final_rows']
        assert {leg['kind'] for leg in consumer['legs']} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert report['source_runtime_verified'] is False
    assert report['runtime_identity_verified'] is False
    assert report['value_identity_verified'] is False
    assert report['transformation_authorized'] is False


def test_ordinary_generator_next_is_a_legal_body_drive_without_self_await_qualification():
    graph = driver_program(create=True, target='start')
    require_valid(graph)
    body, = graph.resumable_bodies
    create, = graph.resumable_creates
    drive, = graph.body_drives
    assert body.kind is ResumableKind.GENERATOR
    assert create.body == body.region
    assert type(drive.target) is BodyStart
    assert drive.target.body == body.region
    assert any(request.kind is RawRequestKind.NEXT and request.operands == ()
               for request in graph.raw_driver_requests)
    assert not any(type(row.contract) is AwaitAcquisition for row in graph.protocol_operations)


def test_known_ordinary_generator_cannot_continue_as_a_direct_self_await_source():
    eligible, details = _complete_self_await()
    require_valid(eligible)
    wrong, changed_scopes, changed_adapters = _ordinary_generator_variant(eligible)
    # This is an eligibility negative: no canonical producer, ordered Use,
    # state, completion, control edge, caller or final consumer was removed.
    assert wrong.operations == eligible.operations
    assert wrong.values == eligible.values
    assert wrong.regions == eligible.regions
    assert wrong.resumable_creates == eligible.resumable_creates
    assert wrong.driver_interfaces == eligible.driver_interfaces
    assert wrong.body_drives == eligible.body_drives
    assert wrong.protocol_call_inputs == eligible.protocol_call_inputs
    assert wrong.protocol_result_consumers == eligible.protocol_result_consumers
    assert wrong.protocol_bindings == eligible.protocol_bindings
    assert tuple(scope.id for scope in wrong.protocol_scopes) == tuple(
        scope.id for scope in eligible.protocol_scopes)
    assert len(wrong.protocol_operations) == len(eligible.protocol_operations)
    assert tuple((row.scope, row.operation, row.slot, row.contract, row.source)
        for row in wrong.protocol_operations) == tuple(
        (row.scope, row.operation, row.slot, row.contract, row.source)
        for row in eligible.protocol_operations)
    scope_ids = {scope.id for scope in changed_scopes}
    assert all(scope.profile is ProtocolProfile.GENERATOR_BODY_V1
               for scope in wrong.protocol_scopes if scope.id in scope_ids)
    for original in changed_adapters:
        migrated, = tuple(row for row in wrong.protocol_operations
            if (row.scope, row.operation, row.slot) == (original.scope, original.operation, original.slot))
        assert migrated == replace(original, clause=ProtocolClause.HOST_ADAPTER)
    assert tuple(row for row in wrong.protocol_operations
        if type(row.contract) is AwaitAcquisition) == details['get_rows']
    assert tuple(row for row in wrong.protocol_operations
        if row in details['final_rows']) == details['final_rows']
    require_valid(_core(wrong))
    issues = validate(wrong)
    assert issues
    assert {issue.code for issue in issues} == {'protocol_await_acquisition_kind'}

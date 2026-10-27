"""Another real Drive's adapter result is not this extractor's own result."""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    AccessMode, Behavior, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, InvokeLiteralResult, Operation,
    OperationResult, StateAccess, StateVersionValue, Terminator, TerminatorKind,
    ValueKind, ValueType, value_type,
)
from scar.ir.program.protocol_await_records import AwaitAcquisition, AwaitBodyLink
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    ContractResult, DriveResult, DriverSubject, HostTerminal,
    OperationSiteSubject, OutcomeAdapter, OutcomeAdapterRule, OwnedUse,
    ProtocolCall, ProtocolCallRule, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_protocol_graphs import _source_gap


QUERY_BUDGET = 1048576
_PART_TABLES = (
    'driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
    'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes',
    'protocol_operations', 'literal_evaluations', 'exception_packets',
)


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _rename(value, maps):
    if type(value) in maps:
        return maps[type(value)].get(value, value)
    if type(value) is tuple:
        return tuple(_rename(item, maps) for item in value)
    if is_dataclass(value):
        return replace(value, **{field.name: _rename(getattr(value, field.name), maps)
                                 for field in fields(value)})
    return value


def _port(operation, kind, slot=0):
    number, = tuple(number for number, edge in enumerate(operation.terminator.successors)
                    if edge.kind is kind)
    return InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(slot))


def _foreign_drive_result_program():
    """Drive the original decoy B before the original current B, without a loop.

    The foreign extractor is itself an AWAIT_STOPITER_TO_EXPRESSION adapter.
    Its own NORMAL Reference dominates the later current terminal. State Uses
    there still select the current extractor's own state slots.
    """
    graph, original = await_final_region_program(zero_cut=True, depth=2)
    values = {value.id: value for value in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    caller, current_get = original['caller'], original['get']
    owner, = tuple(block for block in caller.blocks if current_get.id in block.operations)
    assert owner.operations == (current_get.id,)
    decoy_create = next(operation for operation in original['create_operations']
                        if operation.id == original['decoy_creation'].operation)
    decoy_edge = next(edge for edge in decoy_create.terminator.successors
                      if edge.kind is ExitKind.NORMAL)
    decoy_id, = tuple(formal for actual, formal in
        zip(decoy_edge.arguments, blocks[decoy_edge.block].arguments)
        if type(actual) is CompletionResult
        and actual.index == original['decoy_creation'].handle_result.index)
    decoy = values[decoy_id]
    initial_states = tuple(values[use.value] for use in current_get.uses
        if use.id in current_get.invoke_arguments
        and type(values[use.value]) is StateVersionValue)
    domains = tuple(value.location for value in initial_states)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)

    # Only the actual D tables are cloned. In particular the shared body's and
    # E/F's literal evaluation sites are not appended again with each driver.
    current_driver = original['drivers'][0]
    driver_region = current_driver['driver_region']
    driver_ids = {identity for block in driver_region.blocks for identity in block.operations}
    driver_scopes = tuple(scope for scope in graph.protocol_scopes
        if type(scope.subject) is DriverSubject
        and scope.subject.interface_region == driver_region.id)
    scope_ids = {scope.id for scope in driver_scopes}
    narrow = replace(graph, protocol_scopes=driver_scopes,
        protocol_operations=tuple(row for row in graph.protocol_operations if row.scope in scope_ids),
        literal_evaluations=tuple(row for row in graph.literal_evaluations
            if getattr(row.site, 'operation',
                getattr(getattr(row.site, 'edge', None), 'operation', None)) in driver_ids))
    part, maps = _driver_part(narrow, 'await.foreign.driver')
    foreign_drive, = part['body_drives']
    foreign_outcome = DriveOutcomeRef(foreign_drive.operation, current_driver['outcome_source'])
    foreign_conversion_rows = tuple(row for row in part['protocol_operations']
        if type(row.contract) is OutcomeAdapter
        and row.contract.input == DriveResult(foreign_outcome, 0))
    assert foreign_conversion_rows
    copied_receipts = tuple(_rename(receipt, maps) for receipt in graph.protocol_result_consumers
                            if receipt.site.scope in scope_ids)

    b = _Builder(caller.id.value, domains)
    prefix = 'await.foreign'
    acquisition_scope = ProtocolScopeID(prefix + '.acquisition')
    advance_scope = ProtocolScopeID(prefix + '.advance.scope')
    acquired_name, get_failure_name = prefix + '.acquired', prefix + '.get.failure'
    acquired = b.formals(acquired_name, (REFERENCE, *state_types))
    get_failure = b.formals(get_failure_name, (PACKET, *state_types))
    get_uses = (_use(prefix + '.get.body', decoy.id),
        *(_use(prefix + f'.get.state.{slot}', value.id, state=True)
          for slot, value in enumerate(initial_states)))
    foreign_get = b.add(prefix + '.get', get_uses, effects_complete=False,
        invoke_arguments=tuple(use.id for use in get_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID(acquired_name),
                tuple(CompletionResult(slot) for slot in range(len(acquired)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID(get_failure_name),
                tuple(CompletionResult(slot) for slot in range(len(get_failure)))))))
    get_failure_terminal = b.terminal(prefix + '.get.failure.exit', get_failure, fail=True)
    b.block(get_failure_name, get_failure, (get_failure_terminal,))
    get_rows = tuple(ProtocolOperation(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
        foreign_get.id, number, AwaitAcquisition(get_uses[0].id, decoy.origin,
            _port(foreign_get, kind),
            tuple(InvokeStateOperand(foreign_get.id, use.id) for use in get_uses[1:]),
            _source_gap()), _source_gap())
        for number, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)))
    get_ref = ProtocolOperationRef(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
                                   foreign_get.id, 0)
    acquired_source = ContractResult(acquisition_scope, get_ref.clause,
                                     foreign_get.id, 0, get_rows[0].contract.result)

    raw_name = prefix + '.raw'
    raw = b.value(raw_name + '.value', OperationResult(OperationID(raw_name), 0), RAW)
    raw_operation = b.add(raw_name, results=(raw,), effects_complete=True)
    call_name, call_failure_name = prefix + '.advance', prefix + '.advance.raise'
    call_uses = tuple(_use(call_name + f'.input.{slot}', value,
        state=slot >= 2, protocol=slot == 1)
        for slot, value in enumerate((acquired[0], raw, *acquired[1:])))
    # The uncut D really exits only by RAISE after converting BodyReturn.
    assert {port.kind for port in part['region'].exits} == {ExitKind.RAISE}
    call_failure = b.formals(call_failure_name, (PACKET, *state_types))
    foreign_call = b.add(call_name, call_uses, effects_complete=True,
        callee=part['region'].id, invoke_arguments=tuple(use.id for use in call_uses),
        completions=tuple(CompletionSignature(port.kind, port.types) for port in part['region'].exits),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.RAISE, BlockID(call_failure_name),
                tuple(CompletionResult(slot) for slot in range(len(call_failure)))),)))
    b.block(acquired_name, acquired, (raw_operation, foreign_call))
    advance_row = ProtocolOperation(advance_scope, ProtocolClause.DELEGATE_ADVANCE,
        foreign_call.id, 0, ProtocolCall(call_uses[0].id, (),
            _port(foreign_call, ExitKind.RAISE),
            tuple(InvokeStateOperand(foreign_call.id, use.id) for use in call_uses[2:]),
            ProtocolCallRule.DELEGATE_NEXT), _source_gap())
    advance_ref = ProtocolOperationRef(advance_scope, advance_row.clause, foreign_call.id, 0)
    advance_result = ContractResult(advance_scope, advance_row.clause,
        foreign_call.id, 0, advance_row.contract.result)

    normal_name, failure_name = prefix + '.extracted.normal', prefix + '.extracted.raise'
    normal = b.formals(normal_name, (REFERENCE, *state_types))
    failure = b.formals(failure_name, (PACKET, *state_types))
    extract_uses = (_use(prefix + '.extract.packet', call_failure[0], protocol=True),
        *(_use(prefix + f'.extract.state.{slot}', value, state=True)
          for slot, value in enumerate(call_failure[1:])))
    foreign_extract = b.add(prefix + '.extract', extract_uses, effects_complete=False,
        callee=original['extract'].callee,
        invoke_arguments=tuple(use.id for use in extract_uses),
        completions=original['extract'].completions,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                tuple(CompletionResult(slot) for slot in range(len(normal)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID(failure_name),
                tuple(CompletionResult(slot) for slot in range(len(failure)))))))
    b.block(call_failure_name, call_failure, (foreign_extract,))
    observer_uses = (_use(prefix + '.observe.payload', normal[0]),
        *(_use(prefix + f'.observe.state.{slot}', value, state=True)
          for slot, value in enumerate(normal[1:])))
    observer = Operation(OperationID(prefix + '.observe'), 'observe the foreign own result',
        (Behavior.READ,), observer_uses,
        accesses=tuple(StateAccess(location, use.id, AccessMode.READ)
                       for location, use in zip(domains, observer_uses[1:])), effects_complete=True)
    b.operations.append(observer)
    latest_states = dict(zip(domains, normal[1:]))
    updated_get = replace(current_get, uses=tuple(replace(use,
        value=latest_states[values[use.value].location])
        if type(values[use.value]) is StateVersionValue else use for use in current_get.uses))
    b.block(normal_name, normal, (observer, updated_get))
    extraction_failure = b.terminal(prefix + '.extract.failure.exit', failure, fail=True)
    b.block(failure_name, failure, (extraction_failure,))
    final_rows = tuple(ProtocolOperation(acquisition_scope, ProtocolClause.AWAIT_RESULT_ADAPTER,
        foreign_extract.id, number, OutcomeAdapter(advance_result, extract_uses[0].id,
            _port(foreign_extract, kind), OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION),
        _source_gap()) for number, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)))
    observer_payload = OwnedUse(observer.id, observer_uses[0].id)
    receipts = (
        ProtocolResultConsumers(get_ref, (OwnedUse(foreign_call.id, call_uses[0].id),)),
        ProtocolResultConsumers(ProtocolOperationRef(acquisition_scope, get_ref.clause,
            foreign_get.id, 1), (HostTerminal(get_failure_terminal.id),)),
        ProtocolResultConsumers(advance_ref, (OwnedUse(foreign_extract.id, extract_uses[0].id),)),
        *(ProtocolResultConsumers(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
            (observer_payload if row.slot == 0 else HostTerminal(extraction_failure.id),))
          for row in final_rows),
    )
    added_blocks = tuple(b.blocks)
    caller = replace(caller, blocks=tuple(replace(block, operations=(foreign_get.id,))
        if block.id == owner.id else block for block in caller.blocks) + added_blocks)
    graph = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions)
                + (part['region'],),
        operations=tuple(updated_get if operation.id == current_get.id else operation
                         for operation in graph.operations) + part['operations'] + tuple(b.operations),
        values=(*graph.values, *part['values'], *b.values),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks,
            *(block.id for block in added_blocks))) if scope.region == caller.id else scope
            for scope in graph.control_scopes) + part['control_scopes'],
        raw_driver_requests=(*graph.raw_driver_requests, RawRequestDefinition(raw, RawRequestKind.NEXT, ())),
        protocol_call_inputs=(*graph.protocol_call_inputs, ProtocolCallInputs(advance_ref,
            (ProtocolCallInputCase(None, acquired_source, (), InitialAdvance(acquired_source)),))),
        protocol_result_consumers=(*graph.protocol_result_consumers, *copied_receipts, *receipts),
        protocol_bindings=(*graph.protocol_bindings,
            AwaitBodyLink(get_ref, advance_ref, foreign_drive.operation, None, None)),
        **{name: (*getattr(graph, name), *part[name],
            *(get_rows + (advance_row,) + final_rows if name == 'protocol_operations' else
              (ProtocolScope(acquisition_scope, ProtocolProfile.AWAIT_ACQUISITION_V1,
                  OperationSiteSubject(caller.id, foreign_get.id), _source_gap()),
               ProtocolScope(advance_scope, ProtocolProfile.DELEGATION_SITE_V1,
                  OperationSiteSubject(caller.id, foreign_call.id), _source_gap()))
              if name == 'protocol_scopes' else ())) for name in _PART_TABLES})
    current_raise_edge = next(edge for edge in original['extract'].terminator.successors
                              if edge.kind is ExitKind.RAISE)
    current_failure = next(operation for operation in graph.operations
        if operation.id == blocks[current_raise_edge.block].operations[-1])
    return graph, {
        'original': original, 'current_get': updated_get, 'foreign_get': foreign_get,
        'foreign_body': decoy, 'foreign_drive': foreign_drive,
        'foreign_conversion_rows': foreign_conversion_rows,
        'foreign_ref': next(value for value in b.values if value.id == normal[0]),
        'current_ref': values[original['final_value']],
        'foreign_port': _port(foreign_extract, ExitKind.NORMAL),
        'current_port': _port(original['extract'], ExitKind.NORMAL),
        'foreign_actual': observer_payload,
        'current_actual': OwnedUse(original['final'].id, original['final'].terminator.values[0]),
        'chains': (
            {'scope': acquisition_scope, 'source': get_ref, 'advance': foreign_call.id,
             'drive_outcome': foreign_outcome, 'extract': foreign_extract,
             'input': OwnedUse(foreign_extract.id, extract_uses[0].id), 'rows': final_rows,
             'state_targets': {
                 ExitKind.NORMAL: tuple(OwnedUse(observer.id, use.id) for use in observer_uses[1:]),
                 ExitKind.RAISE: tuple(OwnedUse(extraction_failure.id, use)
                     for use in extraction_failure.terminator.values[1:])}},
            {'scope': original['acquisition_scope'], 'source': original['source'],
             'advance': original['advance_operation'], 'drive_outcome': original['drive_outcome'],
             'extract': original['extract'], 'input': original['extract_input'],
             'rows': original['final_rows'], 'state_targets': {
                 ExitKind.NORMAL: tuple(OwnedUse(original['final'].id, use)
                     for use in original['final'].terminator.values[1:]),
                 ExitKind.RAISE: tuple(OwnedUse(current_failure.id, use)
                     for use in current_failure.terminator.values[1:])}},
        ),
    }


def _assert_complete_chains(graph, details):
    require_valid(_core(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    assert len(graph.resumable_creates) == 2
    assert len({row.body for row in graph.resumable_creates}) == 1
    assert len({row.operation for row in graph.resumable_creates}) == 2
    assert details['foreign_drive'].operation != details['original']['drive_outcome'].drive
    assert all(row.contract.rule is OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION
               for row in details['foreign_conversion_rows'])
    assert details['foreign_ref'].id != details['current_ref'].id
    assert details['foreign_port'] != details['current_port']
    assert value_type(details['foreign_ref']) == value_type(details['current_ref']) == REFERENCE
    for name in ('foreign', 'current'):
        assert index.source_binding(details[name + '_port'], details[name + '_actual'],
                                    budget=QUERY_BUDGET)['match'] is True
    for chain in details['chains']:
        for kind, targets in chain['state_targets'].items():
            assert len(targets) == 2
            for slot, target in enumerate(targets, 1):
                assert index.source_binding(_port(chain['extract'], kind, slot), target,
                                            budget=QUERY_BUDGET)['match'] is True
        public = index.protocol_obligations(chain['scope'], budget=QUERY_BUDGET)
        report = public['connections']['families']['await']
        outcomes = tuple(row for row in report['outcomes'] if row['source'] == chain['source']
            and row['advance_operation'] == chain['advance']
            and row['drive_outcome'] == chain['drive_outcome'])
        assert outcomes
        consumers = tuple(consumer for row in outcomes for consumer in row['consumers']
            if consumer['actual'] == chain['input']
            and consumer['requires_final_extraction'] is True)
        assert consumers
        for consumer in consumers:
            assert consumer['binding']['match'] is True
            assert consumer['final_rows'] == chain['rows']
            assert {leg['kind'] for leg in consumer['legs']} == {ExitKind.NORMAL, ExitKind.RAISE}
            for leg in consumer['legs']:
                assert leg['own_result'] == _port(chain['extract'], leg['kind'])
                assert leg['targets'] and leg['bindings']
                assert all(binding['match'] is True for binding in leg['bindings'])
                if any(type(target) is HostTerminal for target in leg['targets']):
                    assert {state['slot'] for state in leg['states']} == {1, 2}
                assert all(state['binding']['match'] is True for state in leg['states'])
        assert report['source_runtime_verified'] is False
        assert report['runtime_identity_verified'] is False
        assert report['transformation_authorized'] is False


def test_two_real_drives_keep_their_own_final_adapter_reference_results():
    graph, details = _foreign_drive_result_program()
    _assert_complete_chains(graph, details)
    assert ProgramIndex(graph).source_binding(details['foreign_port'], details['current_actual'],
                                             budget=QUERY_BUDGET)['match'] is False


def test_another_drives_same_typed_adapter_own_result_cannot_replace_current_final_result():
    graph, details = _foreign_drive_result_program()
    _assert_complete_chains(graph, details)
    final = details['original']['final']
    wrong_final = replace(final, uses=tuple(replace(use, value=details['foreign_ref'].id)
        if use.id == details['current_actual'].use else use for use in final.uses))
    wrong = replace(graph, operations=tuple(wrong_final if operation.id == final.id else operation
                                            for operation in graph.operations))
    assert graph.values == wrong.values and graph.regions == wrong.regions
    assert tuple(use for use in final.uses if use.id != details['current_actual'].use) == tuple(
        use for use in wrong_final.uses if use.id != details['current_actual'].use)
    core = _core(wrong)
    require_valid(core)
    index = ProgramIndex(core)
    assert index.source_binding(details['foreign_port'], details['current_actual'],
                                budget=QUERY_BUDGET)['match'] is True
    assert index.source_binding(details['current_port'], details['current_actual'],
                                budget=QUERY_BUDGET)['match'] is False
    assert 'protocol_await_final_copy' in {issue.code for issue in validate(wrong)}

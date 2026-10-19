"""Whole shared-input tuples retain their original final-result consumers."""
from dataclasses import replace

import pytest

from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_await_records import AwaitAcquisition, AwaitBodyLink
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import OwnedUse, StaticGapReason, StaticProtocolGap
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_shared_final_graphs import await_shared_final_program


QUERY_BUDGET = 4_194_304
FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
         'value_identity_verified', 'transformation_authorized')


def _core(program):
    return replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _report(program, details, *, budget=QUERY_BUDGET):
    require_valid(_core(program))
    require_valid(program)
    return ProgramIndex(program).protocol_obligations(details['acquisition_scope'],
        budget=budget)['connections']['families']['await']


def _own_results(operation):
    return {InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(slot))
        for number, edge in enumerate(operation.terminator.successors)
        for signature in operation.completions if signature.kind is edge.kind
        for slot in range(len(signature.types))}


def _first_jobs(report, details):
    first = details['shared_final']['first_advance']
    return tuple(job for job in report['inventory']['jobs']
        if job['source'] == details['source'] and job['advance_operation'] == first.id)


def _final_outcomes(report, details):
    return tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])


def _keys(report, *, source=None):
    return ({(job['source'], job['advance'], job.get('input_guard'), job['drive'])
             for job in report['inventory']['jobs'] if source is None or job['source'] == source},
            {row['key'] for row in report['outcomes'] if source is None or row['source'] == source})


def _implementations(report, details):
    targets = {site['input'] for site in details['shared_final']['extractors']}
    return tuple(consumer for outcome in _final_outcomes(report, details)
        for consumer in outcome['consumers']
        if consumer['actual'] in targets and consumer['requires_final_extraction'])


def _assert_final_implementations(report, details):
    shared = details['shared_final']
    sites = shared['extractors']
    assert len(sites) == 2
    assert sites[0]['operation'].id != sites[1]['operation'].id
    assert sites[0]['operation'].callee == sites[1]['operation'].callee
    outcomes = _final_outcomes(report, details)
    assert outcomes
    for site in sites:
        consumers = tuple(consumer for outcome in outcomes for consumer in outcome['consumers']
            if consumer['actual'] == site['input'] and consumer['requires_final_extraction'])
        assert consumers, 'each original extractor callsite remains a final consumer'
        for consumer in consumers:
            assert set(consumer['final_rows']) == set(site['rows'])
            implementation = consumer['implementation']
            assert len(implementation['frames']) == 2
            assert {output['source'] for output in implementation['outputs']} == _own_results(site['operation'])
            assert {output['kind'] for output in implementation['outputs']} == {ExitKind.NORMAL, ExitKind.RAISE}
            assert all(output['terminals'] and all(terminal['match'] is True
                for terminal in output['terminals']) for output in implementation['outputs'])
            primitive, = tuple(stage for stage in implementation['stages']
                if getattr(stage['operation'], 'id', stage['operation']) == details['primitive'].id)
            assert primitive['expanded'] is False
            assert len(primitive['inputs']) == 3
            assert primitive['inputs'][0]['must'] is True
            for leg in primitive['legs']:
                signature, = tuple(row for row in details['primitive'].completions
                                    if row.kind is leg['kind'])
                assert len(leg['results']) == len(signature.types)
                for result in leg['results']:
                    witnesses = tuple(path for path in result['paths']
                        if path['contribution']['match'] is True)
                    assert witnesses
                    assert any(len(path['hops']) == 2 and path['targets']
                        and all(hop['binding']['match'] is True for hop in path['hops'])
                        and all(target['binding']['match'] is True for target in path['targets'])
                        for path in witnesses)
            assert all(implementation[name] is False for name in FLAGS)


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_universal_tuple_preserves_both_original_incoming_keys_and_every_final_caller(zero_cut):
    program, details = await_shared_final_program(zero_cut=zero_cut, depth=2, case_mode='universal')
    report = _report(program, details)
    shared = details['shared_final']
    first = shared['first_advance']
    guards = set(shared['guards'])
    assert len(guards) == 2
    assert shared['backedge'].operation == shared['retry_branch'].id
    assert shared['backedge'].operation != first.id
    assert len(details['drivers']) == (1 if zero_cut else 3)
    assert sum(operation.terminator is not None
        and operation.terminator.kind is TerminatorKind.SUSPEND
        for operation in program.operations) == (0 if zero_cut else 2)

    # A universal declaration stays one original record.  It cannot define
    # the number of real incoming control obligations or erase one of them.
    attachments = tuple(row for row in program.protocol_call_inputs if row.site.operation == first.id)
    assert {row.site.slot for row in attachments} == {row.slot for row in shared['first_rows']}
    assert all(len(row.cases) == 1 and row.cases[0].guard is None for row in attachments)
    jobs = _first_jobs(report, details)
    assert {(job['advance'].slot, job['input_guard']) for job in jobs} == {
        (row.slot, guard) for row in shared['first_rows'] for guard in guards}
    assert len(jobs) == len(shared['first_rows']) * len(guards)
    assert all(job['case'] is not None and job['case'].guard is None
        and not job['input_case_missing'] and job['binding']['match'] is True for job in jobs)

    operations = {operation.id: operation for operation in program.operations}
    drive = details['drivers'][0]['drive']
    expected = {(guard, DriveOutcomeRef(drive.operation, edge.source))
        for guard in guards for edge in operations[drive.operation].terminator.successors}
    outcomes = tuple(row for row in report['outcomes']
        if row['source'] == details['source'] and row['advance_operation'] == first.id)
    assert {(row['input_guard'], row['drive_outcome']) for row in outcomes} == expected
    assert len(outcomes) == len(expected)
    _assert_final_implementations(report, details)
    assert all(report[name] is False for name in FLAGS)


def test_explicit_whole_tuples_reach_both_shared_extractors_without_combining_callers():
    program, details = await_shared_final_program(zero_cut=False, depth=2)
    report = _report(program, details)
    shared = details['shared_final']
    jobs = _first_jobs(report, details)
    assert len(jobs) == len(shared['first_rows']) * 2
    assert {(job['advance'].slot, job['input_guard']) for job in jobs} == {
        (row.slot, guard) for row in shared['first_rows'] for guard in shared['guards']}
    assert all(job['case'].guard == job['input_guard'] and job['binding']['match'] is True for job in jobs)
    _assert_final_implementations(report, details)


@pytest.mark.parametrize('case_mode', ('partial', 'missing'))
def test_missing_cases_keep_every_original_incoming_and_the_real_final_consumers(case_mode):
    baseline, details = await_shared_final_program(case_mode='explicit')
    complete = _report(baseline, details)
    program, missing_details = await_shared_final_program(case_mode=case_mode)
    assert program.operations == baseline.operations and program.values == baseline.values
    report = _report(program, missing_details)
    assert _keys(report) == _keys(complete)
    jobs = _first_jobs(report, missing_details)
    missing = tuple(job for job in jobs if job['input_case_missing'])
    assert len(missing) == len(missing_details['shared_final']['first_rows']) * (1 if case_mode == 'partial' else 2)
    assert all(job['case'] is None and 'await_input_case_missing' in job['gaps'] for job in missing)
    assert {consumer['actual'] for consumer in _implementations(report, missing_details)} == {
        site['input'] for site in missing_details['shared_final']['extractors']}


@pytest.mark.parametrize('removed', ('links', 'final_adapters', 'qualification'))
def test_deleting_semantic_attachments_retains_sources_calls_and_full_output_inventory(removed):
    program, details = await_shared_final_program()
    complete = _report(program, details)
    if removed == 'links':
        changed = replace(program, protocol_bindings=tuple(row for row in program.protocol_bindings
            if type(row) is not AwaitBodyLink))
    elif removed == 'final_adapters':
        sites = set(details['final_sites'])
        changed = replace(program,
            protocol_operations=tuple(row for row in program.protocol_operations
                if ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot) not in sites),
            protocol_result_consumers=tuple(row for row in program.protocol_result_consumers if row.site not in sites))
    else:
        qualification = details['qualification_row']
        site = ProtocolOperationRef(qualification.scope, qualification.clause, qualification.operation, qualification.slot)
        unknown = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
        changed = replace(program,
            protocol_operations=tuple(replace(row, contract=replace(row.contract,
                expansion=replace(row.contract.expansion, qualification=unknown)))
                if type(row.contract) is AwaitAcquisition and row.operation == details['get'].id else row
                for row in program.protocol_operations if row != qualification),
            protocol_result_consumers=tuple(row for row in program.protocol_result_consumers if row.site != site))
    assert changed.operations == program.operations and changed.values == program.values
    report = _report(changed, details)
    if removed == 'qualification':
        assert _keys(report, source=details['source']) == _keys(complete, source=details['source'])
        method_scope, = tuple(scope for scope in program.protocol_scopes if scope.id == details['method_scope'])
        missing, = tuple(job for job in report['inventory']['jobs']
                         if job['scope'] == method_scope.id and job['source'] is None)
        assert missing['source_operation'] == method_scope.subject.operation
        assert missing['advance'] is None and missing['advance_operation'] is None
        assert missing['drive'] is None and missing['binding'] is None and missing['links'] == ()
        assert 'await_source_row_missing' in missing['gaps']
        assert (method_scope.id, method_scope.subject.operation, None) in report['inventory']['original_anchors']['sources']
        assert not any(job['source'] == site for job in report['inventory']['jobs'])
    else:
        assert _keys(report) == _keys(complete)
    before = {consumer['actual']: {output['source'] for output in consumer['implementation']['outputs']}
              for consumer in _implementations(complete, details)}
    after = {consumer['actual']: {output['source'] for output in consumer['implementation']['outputs']}
             for consumer in _implementations(report, details)}
    assert after == before
    if removed == 'links':
        assert all(not job['links'] and 'await_body_link_missing' in job['gaps']
                   for job in report['inventory']['jobs'] if job['source'] == details['source'])
    elif removed == 'final_adapters':
        assert all(consumer['final_rows'] == () and 'await_final_adapter_missing' in consumer['gaps']
                   for consumer in _implementations(report, details))
    else:
        assert any(row['record'].operation == details['get'].id for row in report['acquisitions'])
        assert report['gaps'], 'unresolved qualification cannot become a proof by stage deletion'


@pytest.mark.parametrize('kind', (ExitKind.NORMAL, ExitKind.RAISE), ids=('old-reference', 'old-packet'))
def test_current_final_consumer_cannot_replay_an_available_pre_extraction_value(kind):
    program, details = await_shared_final_program()
    require_valid(program)
    shared = details['shared_final']
    terminal = shared['extractors'][0]['terminals'][kind]
    old = (details['A_value'].id if kind is ExitKind.NORMAL else
           shared['selection_block'].arguments[0])
    changed_terminal = replace(terminal, uses=tuple(replace(use, value=old)
        if use.id == terminal.terminator.values[0] else use for use in terminal.uses))
    changed = replace(program, operations=tuple(changed_terminal if row.id == terminal.id else row
                                              for row in program.operations))
    require_valid(_core(changed))
    site = shared['extractors'][0]
    source = site['own_results_by_kind'][kind][0]
    choices = (ControlEdgeReference(shared['extractor_branch'].id, 0), source.edge)
    actual = OwnedUse(terminal.id, terminal.terminator.values[0])
    assert ProgramIndex(_core(changed)).source_binding(source, actual,
        guard=choices, budget=QUERY_BUDGET)['match'] is False
    assert 'protocol_await_final_copy' in {issue.code for issue in validate(changed)}


@pytest.mark.parametrize('slot', (0, 1, 2), ids=('payload', 'world', 'context'))
def test_exact_left_result_slot_cannot_supply_the_right_callers_private_output(slot):
    program, details = await_shared_final_program()
    require_valid(program)
    shared = details['shared_final']
    left, right = shared['extractors']
    source = left['own_results_by_kind'][ExitKind.RAISE][slot]
    join = right['return_jumps'][ExitKind.RAISE]
    actual = OwnedUse(join.id, join.uses[slot].id)
    choices = (ControlEdgeReference(shared['extractor_branch'].id, 1),
               right['own_results_by_kind'][ExitKind.RAISE][slot].edge)
    report = ProgramIndex(program).source_binding(source, actual, guard=choices, budget=QUERY_BUDGET)
    assert report['match'] is False


def test_first_advance_cannot_replace_current_tuple_with_another_available_receiver():
    program, details = await_shared_final_program()
    first = details['shared_final']['first_advance']
    receiver = first.invoke_arguments[0]
    wrong = replace(first, uses=tuple(replace(use, value=details['A_value'].id)
        if use.id == receiver else use for use in first.uses))
    changed = replace(program, operations=tuple(wrong if operation.id == first.id else operation
                                              for operation in program.operations))
    require_valid(_core(changed))
    assert 'protocol_input_source' in {issue.code for issue in validate(changed)}


def test_pre_get_state_is_a_core_stale_state_error_not_a_protocol_gap():
    program, details = await_shared_final_program()
    values = {row.id: row for row in program.values}
    first = details['shared_final']['first_advance']
    current = next(use for use in first.uses if use.id in first.invoke_arguments
        and type(values[use.value]) is StateVersionValue)
    prior = next(use for use in details['get'].uses if use.id in details['get'].invoke_arguments
        and type(values[use.value]) is StateVersionValue
        and values[use.value].location == values[current.value].location)
    wrong = replace(first, uses=tuple(replace(use, value=prior.value)
        if use.id == current.id else use for use in first.uses))
    changed = replace(program, operations=tuple(wrong if operation.id == first.id else operation
                                              for operation in program.operations))
    assert 'stale_state' in {issue.code for issue in validate(_core(changed))}


def test_static_budget_one_preserves_raw_anchors_without_claiming_complete_pair_totals():
    program, details = await_shared_final_program()
    report = _report(program, details, budget=1)
    operations = {operation.id: operation for operation in program.operations}
    assert report['outcome_inventory']['drive_successors_total'] == sum(
        len(operations[drive.operation].terminator.successors) for drive in program.body_drives)
    assert report['outcome_inventory']['known_inventory_complete'] is False
    assert report['outcome_inventory']['jobs_total'] is None
    assert report['cursor'] is not None or report['outcome_inventory']['cursor'] is not None
    anchors = report['inventory']['original_anchors']['sources']
    assert report['inventory']['source_count'] == len(anchors) == 2
    assert {(scope, operation) for scope, operation, _source in anchors} == {
        (details['acquisition_scope'], details['get'].id),
        (details['qualification_row'].scope, details['qualification_row'].operation)}
    assert any(job['source_operation'] == details['get'].id for job in report['inventory']['jobs'])
    assert all(row['status'] == 'NOT_CHECKED' for row in report['outcomes'])
    assert all(report[name] is False for name in FLAGS)


__all__ = []

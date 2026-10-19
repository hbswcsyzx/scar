"""Current loop incoming and exact caller frames reach the true final Use."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.coordinates import InitialEntry, ResumeIngress
from scar.ir.execution.ids import DenotationID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import CompletionResult, ExitKind
from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_shared_final_graphs import await_shared_final_execution


QUERY_BUDGET = 4_194_304
FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
         'value_identity_verified', 'transformation_authorized')


def _index(program, model, **catalogs):
    require_valid(program)
    report = validate(model, program, **catalogs)
    assert report.valid, report.issues
    return ExecutionIndex(model, program, **catalogs)


def _report(program, model, details, *, budget=QUERY_BUDGET, **catalogs):
    return _index(program, model, **catalogs).await_body_links(
        details['static']['acquisition_scope'], budget=budget)


def _first_actual(report, static, example):
    return tuple((job, occurrence) for job in report['jobs']
        if job['source'] == static['source']
        and job['advance_operation'] == static['shared_final']['first_advance'].id
        for occurrence in job['occurrences']
        if occurrence['advance'].id == example['first_advance']
        and occurrence['advance_selected'] is True)


def _final_actual(report, static, example):
    return tuple(occurrence for outcome in report['outcomes']
        if outcome['definition']['source'] == static['source']
        and outcome['definition']['advance_operation'] == static['advance_operation']
        and outcome['definition']['drive_outcome'] == static['drive_outcome']
        for occurrence in outcome['occurrences']
        if occurrence['advance'].id == example['advance']
        and occurrence['selected'] is not False)


def _successful_paths(implementation):
    return tuple(path for stage in implementation['stages'] for leg in stage['legs']
        for result in leg['results'] for path in result['paths']
        if path['selected'] is True and path['contribution']['match'] is True)


def _selected_implementation(report, static, example):
    candidates = tuple((outcome, occurrence)
        for outcome in report['outcomes']
        if outcome['definition']['source'] == static['source']
        and outcome['definition']['advance_operation'] == static['advance_operation']
        and outcome['definition']['drive_outcome'] == static['drive_outcome']
        for occurrence in outcome['occurrences']
        if occurrence['advance'].id == example['advance'] and occurrence['selected'] is True)
    outcome, occurrence = candidates[0] if len(candidates) == 1 else (None, None)
    assert outcome is not None, 'one current incoming supplies this actual final outcome'
    consumer, = tuple(row for row in occurrence['consumers']
        if row['definition']['actual'].operation == example['extractor_site']
        and row['definition']['requires_final_extraction'] and row['selected'] is True)
    return consumer['implementation']


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_universal_loop_uses_the_last_incoming_and_its_exact_shared_final_caller(zero_cut):
    selections = (dict(arms=(0, 1), extractor=0, child_raised=False),
                  dict(arms=(1, 0), extractor=1, child_raised=True))
    program, model, details = await_shared_final_execution(zero_cut=zero_cut, depth=2,
        case_mode='universal', instances=2, instance_choices=selections)
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=QUERY_BUDGET)
    assert not report['budget']['truncated']
    static = details['static']
    shared = static['shared_final']
    first = shared['first_advance']
    jobs = tuple(job for job in report['jobs'] if job['source'] == static['source']
                 and job['advance_operation'] == first.id)
    assert {(job['advance'].slot, job['input_guard']) for job in jobs} == {
        (row.slot, guard) for row in shared['first_rows'] for guard in shared['guards']}
    assert len(jobs) == len(shared['first_rows']) * len(shared['guards'])
    operations = {row.id: row for row in model.operations}
    segments = {row.id: row for row in model.segments}
    assert len({example['extractor_site'] for example in details['instances']}) == 2
    assert len({example['body_activation'] for example in details['instances']}) == 2

    for selection, example in zip(selections, details['instances'], strict=True):
        assert len(example['merge_visits']) == len(selection['arms'])
        assert len(example['loop_transfers']) == len(selection['arms'])
        assert example['selected_guard'] == shared['guards'][selection['arms'][-1]]
        last = example['loop_transfers'][-1]
        assert operations[last.operation].operation == example['selected_guard'].operation
        assert last.successor_index == example['selected_guard'].successor_index
        assert len(example['caller_operations_by_site'][shared['retry_branch'].id]) == len(selection['arms'])
        first_occurrence = example['call_activations'][0].caller
        actual = tuple((job, occurrence) for job in jobs for occurrence in job['occurrences']
            if occurrence['advance'].id == first_occurrence
            and occurrence['advance_selected'] is True and occurrence['case_selected'] is True)
        assert len(actual) == 1
        job, occurrence = actual[0]
        assert job['case'].guard is None
        assert job['input_guard'] == example['selected_guard']
        assert tuple(source['occurrence'].id for source in occurrence['matched_sources']) == (example['acquisition'],)
        route, = occurrence['routes']
        assert tuple(row['association'] for row in route['call_chain']) == (example['call_activations'][0],)
        assert route['drive']['activation'].id == example['body_activation']

        assert example['body_origin'].creation == example['helper_operations'][static['helper_create'].operation]
        assert len(example['body_segments']) == (1 if zero_cut else 3)
        assert isinstance(segments[example['body_segments'][0]].ingress, InitialEntry)
        for number, association in enumerate(example['body_drives']):
            drive = index.drive_execution(association.drive, budget=QUERY_BUDGET)
            assert drive['activation'].id == example['body_activation']
            assert drive['entry'].id == example['body_entries'][number]
            assert drive['outcome'].id == association.outcome
            if number:
                ingress = segments[example['body_segments'][number]].ingress
                assert isinstance(ingress, ResumeIngress)
                assert ingress.suspension == example['body_drives'][number - 1].outcome

        implementation = _selected_implementation(report, static, example)
        calls = (example['implementation_root_call'], *example['implementation_nested_calls'])
        assert len(implementation['frames']) == 2
        assert tuple(frame['call']['association'].id for frame in implementation['frames']) == tuple(call.id for call in calls)
        assert calls[0].caller == example['extraction']
        assert operations[calls[0].caller].operation == example['extractor_site']
        paths = tuple(path for stage in implementation['stages'] for leg in stage['legs']
            for result in leg['results'] for path in result['paths']
            if path['selected'] is True and path['contribution']['match'] is True)
        assert paths
        assert any(len(path['hops']) == 2
            and {hop['call']['association'].id for hop in path['hops']} == {call.id for call in calls}
            and all(hop['binding']['match'] is True and hop['post_binding']['match'] is True for hop in path['hops'])
            and any(target['operation'].id == example['final'] and target['binding']['match'] is True
                    for target in path['targets']) for path in paths)
        selected_outputs = tuple(row for row in implementation['outputs'] if row['selected'] is True)
        assert len(selected_outputs) == len(next(signature.types for signature in example['parent_call'].completions
            if signature.kind is (ExitKind.RAISE if selection['child_raised'] else ExitKind.NORMAL)))
        assert all(terminal['match'] is True for output in selected_outputs
            for terminal in output['terminals'] if terminal['selected'] is True)
        assert all(implementation[name] is False for name in FLAGS)
    assert all(report[name] is False for name in FLAGS)


@pytest.mark.parametrize('arms', ((0,), (0, 1, 0, 1)), ids=('no-backedge', 'three-backedges'))
def test_explicit_current_incoming_is_preserved_through_zero_or_multiple_copy_loop_trips(arms):
    program, model, details = await_shared_final_execution(arms=arms, instances=1)
    report = _report(program, model, details)
    example, = details['instances']
    assert len(example['merge_visits']) == len(arms)
    assert len(set(example['merge_visits'])) == len(arms)
    assert len(example['caller_operations_by_site'][details['static']['shared_final']['retry_branch'].id]) == len(arms)
    selected = tuple((job, occurrence) for job, occurrence in _first_actual(report, details['static'], example)
                     if occurrence['case_selected'] is True)
    assert len(selected) == 1
    assert selected[0][0]['input_guard'] == details['static']['shared_final']['guards'][arms[-1]]
    assert selected[0][1]['matched_sources']
    assert _successful_paths(_selected_implementation(report, details['static'], example))


def test_a_link_guard_from_an_old_arm_cannot_supply_the_current_other_incoming():
    selections = (dict(arms=(0, 1), extractor=0), dict(arms=(1, 0), extractor=1))
    program, model, details = await_shared_final_execution(case_mode='universal', instance_choices=selections)
    shared = details['static']['shared_final']
    guard = shared['guards'][0]
    changed = replace(program, protocol_bindings=tuple(replace(row, guard=guard)
        if type(row) is AwaitBodyLink and row.advance.operation == shared['first_advance'].id else row
        for row in program.protocol_bindings))
    model = replace(model, snapshot=snapshot_for(changed))
    report = _report(changed, model, details)
    first, sibling = details['instances']
    assert first['loop_transfers'][0] != first['loop_transfers'][-1]
    jobs = tuple((job, occurrence) for job, occurrence in _first_actual(report, details['static'], first)
                 if occurrence['case_selected'] is True)
    assert len(jobs) == 1 and jobs[0][0]['input_guard'] == shared['guards'][1]
    assert jobs[0][1]['routes']
    assert all(route['projections'] == () for route in jobs[0][1]['routes'])
    assert jobs[0][1]['status'] == 'PARTIAL'
    assert 'await_body_link_missing' in {getattr(gap, 'code', gap) for gap in jobs[0][1]['gaps']}
    current = tuple((job, occurrence) for job, occurrence in _first_actual(report, details['static'], sibling)
                    if occurrence['case_selected'] is True)
    assert len(current) == 1 and current[0][0]['input_guard'] == guard
    assert any(route['projections'] for route in current[0][1]['routes'])


@pytest.mark.parametrize('missing', ('helper', 'child', 'payload', 'state'))
def test_one_instances_missing_exact_bridge_or_full_slot_never_borrows_the_shared_callee_sibling(missing):
    options = {'missing_helper_call': 0} if missing == 'helper' else {
        'missing_child_call': (0, 0)} if missing == 'child' else {
        'missing_terminal_use': (0, 1, 0 if missing == 'payload' else 1)}
    choices = (dict(arms=(0, 1), extractor=0, child_raised=False),
               dict(arms=(1, 0), extractor=1, child_raised=True))
    program, model, details = await_shared_final_execution(instance_choices=choices, **options)
    report = _report(program, model, details)
    first, sibling = details['instances']
    if missing == 'helper':
        for _job, occurrence in _first_actual(report, details['static'], first):
            if occurrence['case_selected'] is True:
                assert occurrence['gaps']
                assert all(source['occurrence'].id != sibling['acquisition']
                           for source in occurrence['matched_sources'])
        assert any(occurrence['gaps'] for occurrence in _final_actual(report, details['static'], first))
    else:
        implementation = _selected_implementation(report, details['static'], first)
        assert implementation['status'] == 'PARTIAL'
        assert len(implementation['frames']) == 2
        if missing == 'child':
            assert implementation['frames'][0]['call'] is not None
            assert implementation['frames'][1]['call'] is None
        else:
            assert any('region_return_use_unobserved' in path['gaps']
                for stage in implementation['stages'] for leg in stage['legs']
                for result in leg['results'] for path in result['paths'])
        assert any(terminal['match'] is not True for output in implementation['outputs']
            if output['selected'] is True for terminal in output['terminals']
            if terminal['selected'] is not False)
    assert _successful_paths(_selected_implementation(report, details['static'], sibling))
    assert report['status'] == 'PARTIAL'


def test_missing_current_merge_transfer_does_not_select_the_older_captured_arm():
    selections = (dict(arms=(0, 1), extractor=0), dict(arms=(1, 0), extractor=1))
    program, model, details = await_shared_final_execution(instance_choices=selections, missing_incoming=0)
    report = _report(program, model, details)
    first, sibling = details['instances']
    assert first['loop_transfers'][0] in model.transfers
    assert first['incoming'] not in model.transfers
    candidates = _first_actual(report, details['static'], first)
    assert candidates
    assert all(occurrence['case_selected'] is not True for _job, occurrence in candidates)
    assert all(not occurrence['matched_sources'] or occurrence['gaps'] for _job, occurrence in candidates)
    assert any(occurrence['case_selected'] is True
               for _job, occurrence in _first_actual(report, details['static'], sibling))
    assert report['status'] == 'PARTIAL'


def test_budget_one_keeps_original_parent_counts_and_does_not_authorize_a_prefix():
    program, model, details = await_shared_final_execution()
    report = _report(program, model, details, budget=1)
    inventory = report['outcome_inventory']
    assert report['inventory']['source_count'] == 1
    assert report['budget']['used'] <= 1 and report['budget']['truncated'] is True
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['occurrence_count'] is None
    assert inventory['observed_occurrence_count'] == sum(row['occurrence_count'] for row in report['outcomes'])
    assert all(row['occurrence_count'] == 2 for row in report['outcomes'])
    assert report['cursor'] is not None or inventory['cursor'] is not None
    assert all(report[name] is False for name in FLAGS)


def test_budget_ending_at_actual_output_join_preserves_keys_and_unproved_full_slots(monkeypatch):
    program, model, details = await_shared_final_execution(
        instance_choices=(dict(arms=(0, 1), extractor=0), dict(arms=(1, 0), extractor=1, child_raised=True)))
    index = _index(program, model)
    scope = details['static']['acquisition_scope']
    checkpoints = []
    original = ValidityBudget.spend

    def record(accounting, kind, cost=1, path=''):
        if kind == 'region_occurrence_output_slots':
            checkpoints.append(accounting.used)
        return original(accounting, kind, cost, path)

    # This phase is dynamic-only. In this queried scope the two shared E/F
    # extractors are the only final region implementations, not a side graph.
    with monkeypatch.context() as observed:
        observed.setattr(ValidityBudget, 'spend', record)
        complete = index.await_body_links(scope, budget=QUERY_BUDGET)
    assert checkpoints and checkpoints[0] > 0
    assert all(_successful_paths(_selected_implementation(complete, details['static'], example))
               for example in details['instances'])
    limited = index.await_body_links(scope, budget=checkpoints[0])
    assert {row['key'] for row in limited['outcomes']} == {row['key'] for row in complete['outcomes']}
    assert limited['status'] == 'PARTIAL' and limited['budget']['truncated'] is True
    implementations = tuple(consumer['implementation']
        for example in details['instances'] for occurrence in _final_actual(limited, details['static'], example)
        for consumer in occurrence['consumers'] if consumer.get('implementation') is not None)
    assert implementations
    outputs = tuple(output for implementation in implementations for output in implementation['outputs'])
    assert outputs and any(output['selected'] is None for output in outputs)
    assert all(terminal['match'] is not True for output in outputs for terminal in output['terminals']
               if output['selected'] is None)
    assert limited['outcome_inventory']['jobs_total'] is None
    assert limited['cursor'] is not None or limited['outcome_inventory']['cursor'] is not None


def test_whole_capture_deletion_preserves_static_keys_without_fabricated_pairs():
    program, model, details = await_shared_final_execution()
    complete = _report(program, model, details)
    empty = replace(model, activations=(), segments=(), visits=(), operations=(), values=(), uses=(),
        transfers=(), call_activations=(), body_drive_executions=(), body_activation_origins=())
    assert empty.snapshot == model.snapshot and empty.runs == model.runs
    assert empty.processes == model.processes and empty.threads == model.threads
    missing = _report(program, empty, details)
    for field, inventory in (('outcomes', 'outcome_inventory'), ('failure_paths', 'failure_path_inventory')):
        assert tuple(row['key'] for row in missing[field]) == tuple(row['key'] for row in complete[field])
        assert missing[inventory]['occurrence_count'] == 0
        assert all(row['occurrence_count'] == 0 and row['occurrences'] == ()
                   and row['status'] in ('MISSING', 'PARTIAL') for row in missing[field])
    assert missing['status'] == 'PARTIAL'
    assert all(report[name] is False for report in (complete, missing) for name in FLAGS)


def test_nested_shared_caller_returns_are_detached_from_the_next_public_query():
    program, model, details = await_shared_final_execution()
    index = _index(program, model)
    scope = details['static']['acquisition_scope']
    original_receipt = deepcopy(index.report)
    first = index.await_body_links(scope, budget=QUERY_BUDGET)
    expected = deepcopy(first)
    implementation = _selected_implementation(first, details['static'], details['instances'][0])
    implementation['frames'][0]['status'] = 'detached mutation'
    implementation['outputs'][0]['terminals'] = ()
    job, occurrence = next((job, occurrence) for job, occurrence in _first_actual(
        first, details['static'], details['instances'][0]) if occurrence['case_selected'] is True)
    occurrence['matched_sources'] = ()
    assert first != expected
    again = index.await_body_links(scope, budget=QUERY_BUDGET)
    assert again == expected
    assert index.report == original_receipt


def test_fresh_external_context_rechecks_the_actual_source_copy_after_the_loop():
    program, model, details = await_shared_final_execution(instances=1)
    example, = details['instances']
    operations = {row.id: row for row in model.operations}
    values = {row.id: row for row in model.values}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    transfer, = tuple(row for row in model.transfers if row.operation == example['acquisition'])
    get = details['static']['get']
    edge = get.terminator.successors[transfer.successor_index]
    block = blocks[next(row.block for row in model.visits if row.id == transfer.target)]
    formal, = tuple(formal for argument, formal in zip(edge.arguments, block.arguments)
                    if type(argument) is CompletionResult and argument.index == 0)
    source, = tuple(row for row in model.values if (row.origin, row.value) == (transfer.target, formal))
    first = details['static']['shared_final']['first_advance']
    actual, = tuple(row for row in model.uses if (row.operation, row.use) ==
                   (example['first_advance'], first.invoke_arguments[0]))
    target = values[actual.value]
    assert source.id != target.id
    assert operations[actual.operation].operation == first.id
    evidence = EvidenceGraph()
    identity = ObjectID('await.shared.actual.B')
    evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, identity))
    artifact = external_artifact(evidence, 'memory:await-shared-original-copy')
    basis = Unresolved('declared scoped identity, not native runtime proof', model.activations[0].entry)
    denotations = tuple(ValueDenotation(DenotationID('await.shared.' + label), value.id,
        ObjectIdentity(ObjectRef(artifact, identity)), basis, details['source'])
        for label, value in (('source', source), ('target', target)))
    model = replace(model, denotations=(*model.denotations, *denotations))
    index = _index(program, model, evidence_graphs={artifact.sha256: evidence})
    scope = details['static']['acquisition_scope']
    first_view = index.await_body_links(scope, budget=QUERY_BUDGET)
    selected = tuple(occurrence for _job, occurrence in _first_actual(first_view, details['static'], example)
                     if occurrence['case_selected'] is True)
    assert len(selected) == 1
    binding, = tuple(binding for binding in selected[0]['bindings']
                     if binding['source_value'] == source and binding['formal'] == target)
    assert binding['original_copy'] is True
    assert binding['compatibility']['status'] == 'DECLARED_SAME_OBJECT'
    evidence.add_control_event('external context changed after the previous public query')
    with pytest.raises(ValueError, match='snapshot|artifact|external'):
        index.await_body_links(scope, budget=QUERY_BUDGET)
    assert binding['compatibility']['status'] == 'DECLARED_SAME_OBJECT'
    assert all(first_view[name] is False for name in FLAGS)


__all__ = []

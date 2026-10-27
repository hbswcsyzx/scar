"""Original same-B running reentry, not a phase enum or a holder heuristic."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind, UseRole
from scar.ir.program.protocols import BodyStatePredicateRule, DriverSubject, ProtocolProfile
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_coroutine_running_graphs import coroutine_running_execution


_BUDGET = 1_048_576
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _index(program, model):
    require_valid(replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))
    require_valid(program)
    report = validate_execution(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _flags(view):
    assert all(view[name] is False for name in _FLAGS)
    if 'native_phase_verified' in view:
        assert view['native_phase_verified'] is False


def _read(details, instance):
    static = details['static']['running']
    example = details['instances'][instance]
    return example['extra_scopes']['inner'][2][static['predicate'].operation]


def _active(view, details, instance):
    association = details['instances'][instance]['body_drives'][1]
    candidate, = tuple(row for row in view['active_candidates']
        if row['drive'].id == association.drive)
    assert candidate['association'] == association
    return candidate


def _complete(index, program, details, instance):
    view = index.body_state_history(_read(details, instance), budget=_BUDGET)
    running = details['static']['running']
    example = details['instances'][instance]
    candidate = _active(view, details, instance)
    assert view['read'].id == _read(details, instance)
    assert view['predicate'] == running['predicate']
    assert view['predicate'].contract.subject.rule is BodyStatePredicateRule.IS_RUNNING
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert candidate['expected_bool'] is view['expected_bool'] is True
    assert view['observed_branch'] is True and view['consistent'] is True
    assert candidate['subject_binding']['match'] is True
    assert candidate['entry_order'] and candidate['outcome_order']
    assert candidate['drive_support']['supported'] is True
    assert candidate['call_chain']['supported'] is True
    inner = example['extra_call_activations']['inner']
    assert tuple(row['association'] for row in candidate['call_chain']['calls']) == (inner,)
    assert inner.caller == example['body_occurrences'][1][running['inner_call'].id]
    assert inner.activation == example['extra_scopes']['inner'][0]
    assert inner.completion == example['extra_scopes']['inner'][2][running['host_terminal'].id]
    assert candidate['call_chain']['root'] == example['body_activation']
    # A stable receiver handle alone is insufficient. The original copy
    # evidence must pass through the known result and the real body ingress.
    rules = {row['rule'] for row in candidate['subject_binding']['support']}
    assert {'ORIGINAL_CALL_OUTPUT', 'ORIGINAL_BODY_BINDING'} <= rules
    assert not any(row['expected_bool'] is True for row in view['active_candidates']
                   if row['drive'].id != candidate['drive'].id)
    _flags(view)
    return view


def test_native_same_body_is_actually_running_during_reentry_and_then_finishes():
    program, model, details = coroutine_running_execution(instances=2)
    index = _index(program, model)
    static, running = details['static'], details['static']['running']
    body, = program.resumable_bodies
    assert body.kind is ResumableKind.COROUTINE
    assert len(program.resumable_creates) == 1
    assert all(row.profile is ProtocolProfile.COROUTINE_BODY_V1
               for row in program.protocol_scopes if type(row.subject) is DriverSubject)
    body_operations = {site for block in static['body'].blocks for site in block.operations}
    cuts = tuple(row for row in program.operations if row.id in body_operations
                 and type(row.terminator) is SuspendTerminator)
    assert len(cuts) == 2 and all(row.terminator.flavor is SuspensionFlavor.AWAIT for row in cuts)
    assert running['raw'].kind.value == 'SEND'
    assert len(running['raw'].operands) == 1
    assert running['normalizer'].callee == running['normalizer_region'].id
    assert {edge.kind for edge in running['normalizer'].terminator.successors} == {
        ExitKind.NORMAL, ExitKind.RAISE}
    assert running['host_terminal'].terminator.kind is TerminatorKind.RAISE
    assert running['handler'].uses[0].role is UseRole.PROTOCOL
    assert running['context_access'].accesses[0].after is not None
    for number, example in enumerate(details['instances']):
        assert len(example['body_drives']) == 3
        assert {row.activation for row in example['body_drives']} == {example['body_activation']}
        assert example['body_origin'].creation == example['creation']
        origin = index.body_activation_origin(example['body_activation'], budget=_BUDGET)
        assert origin['association'] == example['body_origin']
        middle = index.drive_execution(example['body_drives'][1].drive, budget=_BUDGET)
        assert middle['association'] == example['body_drives'][1]
        assert middle['entry'].id == example['body_entries'][1]
        assert middle['outcome'].operation == running['second_suspend'].id
        sent, = tuple(row for row in middle['inputs']
                      if row['formal'] is not None and row['formal'].value == running['resume_formal'].id)
        assert sent['source_use'] is not None and sent['source_value'] is not None
        assert sent['formal'].origin == example['body_entries'][1]
        normalizer = index.call_activation(example['extra_call_activations']['send'].id)
        output, = tuple(row for row in normalizer['outputs'] if row['ordinal'] == 0)
        assert output['edge_argument'] == CompletionResult(0)
        assert output['caller_formal_definition'].origin.index == 2
        assert output['callee_use_definition'].value == running['normalizer_terminal'].uses[0].value
        inner = index.call_activation(example['extra_call_activations']['inner'].id)
        assert inner['inputs'][0]['actual_value'] == sent['formal']
        assert len(inner['outputs']) == len(running['host_terminal'].terminator.values)
        assert all(row['callee_use'] is not None and row['caller_formal'] is not None
                   for row in inner['outputs'])
        assert {row['formal_definition'].location for row in inner['inputs']
                if type(row['formal_definition']) is StateVersionValue} == {
            row.location for row in program.values if type(row) is StateVersionValue}
        inner_operations = example['extra_scopes']['inner'][2]
        rejected = inner_operations[running['reject'].id]
        transfer, = tuple(row for row in model.transfers if row.operation == rejected)
        edge = running['reject'].terminator.successors[transfer.successor_index]
        assert edge.kind is ExitKind.NORMAL
        block = next(row for row in running['inner_driver'].blocks if row.id == edge.block)
        packet_formal, = tuple(formal for argument, formal in zip(edge.arguments, block.arguments)
                               if argument == CompletionResult(0))
        packet, = tuple(row for row in model.values
                        if row.origin == transfer.target and row.value == packet_formal)
        host = inner_operations[running['host_terminal'].id]
        delivered, = tuple(row for row in model.uses if row.operation == host
            and row.use == running['host_terminal'].terminator.values[0])
        assert delivered.value == packet.id
        # Rejection occurs inside this second body segment, followed by its
        # actual handler/Detach/AWAIT. There is no inner recursive BodyDrive.
        assert not any(row.drive in set(inner_operations.values()) for row in model.body_drive_executions)
        third = index.drive_execution(example['body_drives'][2].drive, budget=_BUDGET)
        assert third['outcome'].operation == static['drivers'][2]['outcome_source']
        assert next(row for row in program.operations if row.id == third['outcome'].operation
                    ).terminator.kind is TerminatorKind.RETURN
        final = index.call_activation(example['extra_call_activations']['final'].id)
        assert final['caller'].operation == static['extract'].id
        assert final['completion'].operation == static['stage_records'][0]['terminals'][ExitKind.NORMAL].id
        _complete(index, program, details, number)


@pytest.mark.parametrize('missing', ('inner-call', 'sent-use', 'raw-use'))
def test_missing_this_instances_inner_chain_or_sent_source_cannot_borrow_its_sibling(missing):
    program, model, details = coroutine_running_execution(instances=2,
        missing_inner_call=0 if missing == 'inner-call' else None,
        missing_sent_use=0 if missing == 'sent-use' else None,
        missing_drive_request=0 if missing == 'raw-use' else None)
    index = _index(program, model)
    view = index.body_state_history(_read(details, 0), budget=_BUDGET)
    candidate = _active(view, details, 0)
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert candidate['gaps']
    assert view['drive_inventory'] == program.body_drives
    assert view['commit_inventory'] == program.body_outcome_commits
    assert view['observed_branch'] is True
    if missing == 'inner-call':
        assert candidate['call_chain']['supported'] is False
    elif missing == 'sent-use':
        assert candidate['drive_support']['supported'] is False
        assert candidate['subject_binding']['match'] is not True
    else:
        assert candidate['drive_support']['supported'] is False
    _flags(view)
    _complete(index, program, details, 1)


def test_running_budget_one_retains_all_original_sources_without_a_true_prefix():
    program, model, details = coroutine_running_execution(instances=2)
    index = _index(program, model)
    full = _complete(index, program, details, 0)
    limited = index.body_state_history(_read(details, 0), budget=1)
    assert limited['drive_inventory'] == full['drive_inventory'] == program.body_drives
    assert limited['commit_inventory'] == full['commit_inventory'] == program.body_outcome_commits
    assert limited['source_keys'] == full['source_keys']
    assert len(limited['active_candidates']) == len(full['active_candidates'])
    assert len(limited['terminal_candidates']) == len(full['terminal_candidates'])
    assert limited['expected_bool'] is None
    assert all(row['expected_bool'] is None for row in limited['active_candidates'])
    assert limited['budget']['truncated'] is True and limited['budget']['used'] <= 1
    assert limited['cursor'] is not None
    _flags(limited)

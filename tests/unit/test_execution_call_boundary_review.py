"""Independent boundary regressions for declared synchronous call links.

These are canonical IR declarations, not recovered calls or runtime witnesses.
The original shared fixtures remain unchanged.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.calls import CallActivation
from scar.ir.execution.coordinates import (
    BlockVisit, CaptureIngress, ExecutionSegment, HostThreadInstance, InitialEntry,
    UnresolvedHostThread,
)
from scar.ir.execution.ids import (
    BlockVisitID, CallActivationID, ExecutionSegmentID, HostThreadInstanceID,
)
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, LiteralOrigin,
    Operation, ProgramGraph, Region, Successor, Terminator, TerminatorKind, Use,
)
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_call_graphs import _model, invoke_call_execution, shared_calls_execution


def _codes(report):
    return {issue.code for issue in report.issues}


def _foreign_thread(model):
    return HostThreadInstance(HostThreadInstanceID('boundary.other-thread'), model.processes[0].id,
                              23, MissingEvidence('declared second host-thread incarnation'))


def test_unresolved_entry_does_not_hide_a_known_thread_conflict_at_child_completion():
    program, model, details = invoke_call_execution(raised=True)
    row, = model.call_activations
    child = next(item for item in model.activations if item.id == row.activation)
    other = _foreign_thread(model)
    changed = replace(model, threads=(*model.threads, other),
        segments=tuple(replace(segment, host_thread=other.id)
                       if segment.activation == child.id else segment for segment in model.segments),
        call_activations=(replace(row, entry=Unresolved('initial entry not paired', child.entry)),))
    report = validate(changed, program)
    assert 'call_thread' in _codes(report), report
    assert any(gap.code == 'call_entry_unobserved' for gap in report.gaps)
    assert any(item.id == details['completions'][0] for item in changed.operations)


def test_unknown_caller_thread_cannot_exempt_two_conflicting_known_child_segment_threads():
    program, model, details = invoke_call_execution(raised=True)
    row, = model.call_activations
    occurrence = next(item for item in model.operations if item.id == row.completion)
    child = next(item for item in model.activations if item.id == row.activation)
    other = _foreign_thread(model)
    capture = ExecutionSegment(ExecutionSegmentID('boundary.child.capture'), child.id, other.id,
                               CaptureIngress(child.entry, 'disconnected completion capture'))
    parent = next(item for item in model.activations if item.id == details['caller_activation'])
    changed = replace(model, threads=(*model.threads, other),
        segments=(*tuple(replace(segment, host_thread=UnresolvedHostThread(
            'caller thread was not captured', parent.entry))
            if segment.activation == parent.id else segment for segment in model.segments), capture),
        visits=tuple(replace(visit, segment=capture.id) if visit.id == occurrence.visit else visit
                     for visit in model.visits),
        transfers=tuple(transfer for transfer in model.transfers if transfer.target != occurrence.visit))
    report = validate(changed, program)
    assert 'call_thread' in _codes(report), report
    assert any(gap.code == 'call_thread_unresolved' for gap in report.gaps)
    # Partial capture is explicit; this is not an ordinary cross-segment edge.
    assert 'transfer_segment' not in _codes(report)


def test_one_linked_activation_cannot_claim_both_captured_return_and_raise_completions():
    program, model, details = invoke_call_execution(raised=False)
    alternate_program, alternate, alternate_details = invoke_call_execution(raised=True)
    assert alternate_program == program
    terminal = next(item for item in alternate.operations if item.id == alternate_details['completions'][0])
    captured_visit = next(item for item in alternate.visits if item.id == terminal.visit)
    child = next(item for item in model.activations if item.id == details['child'])
    segment = ExecutionSegment(ExecutionSegmentID('boundary.extra-terminal'), child.id, model.threads[0].id,
                               CaptureIngress(child.entry, 'second terminal fragment in the same activation'))
    visit = BlockVisit(BlockVisitID('boundary.extra-terminal'), segment.id, captured_visit.block)
    operations = tuple(replace(item, visit=visit.id) for item in alternate.operations
                       if item.visit == captured_visit.id)
    operation_ids = {item.id for item in operations}
    values = tuple(replace(item, origin=visit.id) if item.origin == captured_visit.id else item
                   for item in alternate.values if item.origin == captured_visit.id or item.origin in operation_ids)
    uses = tuple(item for item in alternate.uses if item.operation in operation_ids)
    changed = replace(model, segments=(*model.segments, segment), visits=(*model.visits, visit),
                      operations=(*model.operations, *operations), values=(*model.values, *values),
                      uses=(*model.uses, *uses))
    report = validate(changed, program)
    assert 'call_multiple_completion' in _codes(report), report
    assert not {'duplicate_id', 'duplicate_operation_visit', 'duplicate_definition'} & _codes(report)


@pytest.mark.parametrize('reused', ('caller', 'activation'))
def test_synchronous_link_cannot_reuse_either_end(reused):
    program, model, _ = shared_calls_execution()
    first, second = model.call_activations
    changed_row = (replace(second, caller=first.caller) if reused == 'caller' else replace(
        second, activation=first.activation, entry=first.entry, completion=first.completion))
    changed = replace(model, call_activations=(first, changed_row))
    report = validate(changed, program)
    expected = 'call_caller_reused' if reused == 'caller' else 'call_activation_reused'
    assert expected in _codes(report), report
    assert 'duplicate_id' not in _codes(report)


def _recursive_execution():
    """A real base case: recur(True) calls recur(False), then both return."""
    region_id = RegionID('boundary.recursive')
    entry, base, recursive = (BlockID('boundary.recursive.' + name)
                              for name in ('entry', 'base', 'step'))
    condition = DataValue(ValueID('boundary.condition'), region_id, BlockArgument(entry, 0), 'builtins.bool')
    false = DataValue(ValueID('boundary.false'), region_id, LiteralOrigin(False), 'builtins.bool')
    choose_use, recursive_use = Use(UseID('boundary.condition'), condition.id), Use(UseID('boundary.false'), false.id)
    choose = Operation(OperationID('boundary.choose'), 'choose base or recursive call',
        (Behavior.CONTROL,), (choose_use,), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (Successor(recursive, ()), Successor(base, ())),
                              condition=choose_use.id))
    base_return = Operation(OperationID('boundary.base.return'), 'base case return', (Behavior.CONTROL,),
                            terminator=Terminator(TerminatorKind.RETURN, exit='normal'))
    call = Operation(OperationID('boundary.recur'), 'recur with false', (Behavior.CONTROL,), (recursive_use,),
                     callee=region_id, call_arguments=(recursive_use.id,))
    outer_return = Operation(OperationID('boundary.outer.return'), 'return after recursive child',
        (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.RETURN, exit='normal'))
    region = Region(region_id, 'finite bool recursion', entry, (
        Block(entry, (condition.id,), (choose.id,)),
        Block(base, (), (base_return.id,)),
        Block(recursive, (), (call.id, outer_return.id))), (ExitPort('normal', ExitKind.NORMAL, ()),))
    program = ProgramGraph(region_id, (region,), (choose, base_return, call, outer_return), (condition, false))
    model, scopes, source = _model(program, (
        (region_id, ((entry, 0), (recursive, None)), 'recursive.parent'),
        (region_id, ((entry, 1), (base, None)), 'recursive.child')))
    parent, child = scopes
    link = CallActivation(CallActivationID('boundary.recursive'), parent[2][call.id], child[0],
                          child[1][0], child[2][base_return.id], source)
    model = replace(model, call_activations=(link,))
    return program, model, parent, child, outer_return.id


def test_dynamic_self_cycle_is_rejected_even_though_static_self_recursion_is_well_typed():
    program, model, parent, _child, outer_return = _recursive_execution()
    link, = model.call_activations
    parent_completion = next(item.id for item in model.operations if item.operation == outer_return)
    loop = replace(link, activation=parent[0], entry=parent[1][0],
                   completion=parent_completion)
    report = validate(replace(model, call_activations=(loop,)), program)
    assert 'call_activation_cycle' in _codes(report), report
    assert not {'call_activation_region', 'call_entry_activation', 'call_completion_activation'} & _codes(report)


def test_static_recursion_with_a_base_case_uses_fresh_activations_without_proving_runtime_termination():
    program, model, parent, child, _ = _recursive_execution()
    report = validate(model, program)
    assert report.valid, report.issues
    assert parent[0] != child[0]
    assert {item.region for item in model.activations} == {program.root}
    assert next(value.origin.value for value in program.values if type(value.origin) is LiteralOrigin) is False
    assert any(gap.code == 'call_source_runtime_unverified' for gap in report.gaps)
    assert not report.source_runtime_verified and not report.transformation_authorized


@pytest.mark.parametrize('alias', (False, True))
def test_independent_entry_facts_or_uri_aliases_do_not_define_different_entry_identity(alias):
    program, model, _ = shared_calls_execution()
    row = model.call_activations[0]
    child = next(item for item in model.activations if item.id == row.activation)
    artifact = model.snapshot.artifact
    first = ProviderFactReference(artifact, 'entry/activation')
    second = ProviderFactReference(replace(artifact, uri='memory:entry-evidence-alias') if alias else artifact,
                                   'entry/activation' if alias else 'entry/segment')
    activation_point = EvidencePoint(child.entry.run, child.entry.process, first)
    segment_point = EvidencePoint(child.entry.run, child.entry.process, second)
    assert activation_point != segment_point
    changed = replace(model,
        activations=tuple(replace(item, entry=activation_point) if item.id == child.id else item
                          for item in model.activations),
        segments=tuple(replace(item, ingress=InitialEntry(segment_point))
                       if item.activation == child.id else item for item in model.segments))
    report = validate(changed, program)
    assert report.valid, report.issues
    assert 'call_entry_source' not in _codes(report)
    assert any(gap.code == 'call_source_runtime_unverified' for gap in report.gaps)
    assert not report.source_runtime_verified


def test_completion_must_belong_to_the_declared_child_not_another_same_body_activation():
    program, model, _ = shared_calls_execution()
    first, second = model.call_activations
    changed = replace(model, call_activations=(replace(first, completion=second.completion), second))
    report = validate(changed, program)
    assert 'call_completion_activation' in _codes(report), report

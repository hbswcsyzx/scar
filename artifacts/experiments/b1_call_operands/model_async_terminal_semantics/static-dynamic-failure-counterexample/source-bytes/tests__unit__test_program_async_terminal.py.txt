"""Frame-local supplied conversion and propagation; no native replay claim."""
from dataclasses import replace

import pytest

from scar.ir.program.lifecycle import DriveOutcomeRef, SessionPost
from scar.ir.program.model import (BlockArgument, CompletionResult, ExitKind,
    InvokeLiteralResult, OperationResult, StateVersionValue, TerminatorKind)
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.protocols import OutcomeAdapter, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ObjectField, ReferenceOwner
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_terminal_graphs import async_terminal_program


BUDGET = 262144


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_bindings=(), protocol_call_inputs=(), protocol_result_consumers=(),
        exception_matches=())


def _actual(operation, identity):
    return next(use for use in operation.uses if use.id == identity)


def _no_authority(report):
    for field in ('source_runtime_verified', 'runtime_identity_verified',
                  'native_applicability_verified', 'transformation_authorized'):
        assert report[field] is False


def _bind(index, source, operation, use):
    return index.source_binding(source, OwnedUse(operation.id, use), budget=BUDGET)


@pytest.mark.parametrize('route', ('stop-iteration', 'stop-async-iteration',
                                  'ordinary', 'constructor-raise'))
def test_frame_local_conversion_uses_its_own_results_before_body_raise_and_host(route):
    graph, details = async_terminal_program(route=route)
    require_valid(_core(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    intrinsic = details['intrinsic']
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}

    # The same created B first hands off AWAIT, then actually raises after
    # executing the intrinsic in its frame. No external error adapter exists.
    assert len(graph.resumable_creates) == len(graph.async_request_creates) == 1
    assert len(details['drivers']) == 2
    first, last = details['drivers']
    assert first['update'].post is SessionPost.HOLD
    assert last['update'].post is SessionPost.COMPLETE
    assert operations[first['outcome_source']].terminator.kind is TerminatorKind.SUSPEND
    assert last['outcome_source'] == intrinsic['body_terminal'].id
    assert intrinsic['body_terminal'].terminator.kind is TerminatorKind.RAISE
    assert not any(type(row.contract) is OutcomeAdapter for row in graph.protocol_operations)
    assert {row.outcome for row in graph.body_outcome_commits} == {
        DriveOutcomeRef(drive.operation, edge.source) for drive in graph.body_drives
        for edge in operations[drive.operation].terminator.successors}

    for matcher in intrinsic['matchers']:
        report = index.exception_match(matcher.operation, budget=BUDGET)
        assert report['matcher'] == matcher
        assert report['inputs'][0]['match'] is True
        assert report['bool_binding']['match'] is True
        assert report['normal']['result'] == matcher.normal_result
        assert {row['truth'] for row in report['branches']} == {True, False}
        assert len(report['state_support']) == 2
        _no_authority(report)

    constructor = intrinsic['constructor']
    normal, raised = intrinsic['constructor_results']
    assert {edge.kind for edge in constructor.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert normal.result.index == raised.result.index == 0
    assert _bind(index, values[intrinsic['original_exception']].origin,
                 constructor, constructor.invoke_arguments[0])['match'] is True
    prior_world = None
    for number, (write, refinement) in enumerate(zip(intrinsic['chaining'], intrinsic['refinements'])):
        access, = write.accesses
        owner, original = write.uses[:2]
        assert refinement.effects[0].owner == ReferenceOwner(owner.id)
        assert refinement.effects[0].path == (ObjectField(('__cause__', '__context__')[number]),)
        assert _bind(index, normal, write, owner.id)['match'] is True
        assert _bind(index, values[intrinsic['original_exception']].origin,
                     write, original.id)['match'] is True
        if prior_world is not None:
            assert _actual(write, access.before).value == prior_world
        prior_world = access.after
    packet = intrinsic['packet_definition']
    pack = operations[values[packet.value].origin.operation]
    assert _bind(index, normal, pack, packet.exception)['match'] is True
    assert _actual(intrinsic['normal_terminal'], intrinsic['normal_terminal'].terminator.values[2]).value == prior_world

    unchanged = intrinsic['ordinary_terminal']
    assert _bind(index, values[intrinsic['original_packet']].origin,
                 unchanged, unchanged.terminator.values[1])['match'] is True
    failed = intrinsic['raise_terminal']
    assert _bind(index, raised, failed, failed.terminator.values[0])['match'] is True
    selected = 1 if route == 'constructor-raise' else 0
    call = intrinsic['call']
    edge = ControlEdgeReference(call.id, selected)
    payload_slot = 0 if selected else 1
    body_terminal = intrinsic['body_terminal']
    assert _bind(index, InvokeLiteralResult(edge, CompletionResult(payload_slot)),
                 body_terminal, body_terminal.terminator.values[0])['match'] is True
    detach = operations[next(block.operations[-2] for block in details['body'].blocks
                             if body_terminal.id in block.operations)]
    assert _actual(body_terminal, body_terminal.terminator.values[-1]).value == detach.accesses[0].after

    # Publication follows actual BodyRaise, not the original Stop* pack or
    # constructor's earlier completion. Host uses the current landing packet.
    host = last['host_terminal']
    assert host.terminator.kind is TerminatorKind.RAISE
    drive = operations[last['drive'].operation]
    body_edge = next(edge for edge in drive.terminator.successors if edge.source == body_terminal.id)
    landing = blocks[body_edge.block]
    packet_formal = next(value for value in landing.arguments
                         if not isinstance(values[value], StateVersionValue))
    assert _bind(index, values[packet_formal].origin, host, host.terminator.values[0])['match'] is True
    assert len(last['caller_call'].completions) == 1
    assert last['caller_call'].completions[0].kind is ExitKind.RAISE
    assert len(last['caller_call'].completions[0].types) == 1 + len(graph.locations)

    boundary = index.native_boundary(intrinsic['native_boundary'].id)
    assert boundary is intrinsic['native_boundary']
    assert len(boundary.inputs) == len(boundary.outputs) == 1
    assert boundary.inputs[0].port.value == intrinsic['original_exception']
    assert boundary.outputs[0].port.index == 0
    assert boundary.signature.artifact == intrinsic['artifact']
    assert intrinsic['artifact'].sha256 == '9c218e09ee44ef416440ee3e473d3f0686a1752ab68222d49ebcbce99bd1264f'
    assert graph.provider_envelopes[0].coverage
    public = index.protocol_obligations(budget=BUDGET)
    family = public['connections']['families']['async']
    expected = {commit.outcome for commit in graph.body_outcome_commits}
    assert {row['source'] for row in family['session_consumers']} == expected
    assert all(row['targets'] and all(target['source_binding']['match'] is True
                                     for target in row['targets'])
               for row in family['session_consumers'])
    assert public['source_runtime_verified'] is False
    assert public['transformation_authorized'] is False


def test_matcher_rejects_another_available_same_typed_packet():
    graph, details = async_terminal_program()
    matcher = details['intrinsic']['matchers'][0]
    operation = next(row for row in graph.operations if row.id == matcher.operation)
    wrong = replace(operation, uses=tuple(replace(use, value=details['intrinsic']['old_packet'])
        if use.id == matcher.input_use else use for use in operation.uses))
    bad = replace(graph, operations=tuple(wrong if row.id == wrong.id else row for row in graph.operations))
    require_valid(_core(bad))
    assert 'exception_match_source' in {issue.code for issue in validate(bad)}


def test_chaining_needs_the_original_exception_not_the_new_same_typed_owner():
    graph, details = async_terminal_program()
    intrinsic = details['intrinsic']
    index = ProgramIndex(graph)
    for write in intrinsic['chaining']:
        owner, original = write.uses[:2]
        original_source = index.values[intrinsic['original_exception']].origin
        assert _bind(index, original_source, write, original.id)['match'] is True
        assert _bind(index, intrinsic['constructor_results'][0], write, owner.id)['match'] is True
        # The new exception is a produced Reference, not an alias of the
        # original exception merely because both are used by the same write.
        assert _bind(index, original_source, write, owner.id)['match'] is False


def test_raw_packet_is_not_a_body_terminal_publication_before_intrinsic_completion():
    graph, details = async_terminal_program()
    chosen = details['drivers'][-1]['publication']
    original_pack = next(row for row in graph.values
                        if row.id == details['intrinsic']['body_packet_definitions'][0].value).origin.operation
    bad = replace(graph, body_outcome_commits=tuple(replace(row,
        outcome=DriveOutcomeRef(row.outcome.drive, original_pack)) if row is chosen else row
        for row in graph.body_outcome_commits))
    assert 'publication_outcome' in {issue.code for issue in validate(bad)}


def test_deleting_optional_session_receipts_or_budget_does_not_delete_body_raise_sources():
    graph, details = async_terminal_program()
    require_valid(graph)
    expected = {commit.outcome for commit in graph.body_outcome_commits}
    changed = replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings
                                                    if type(row) is not AsyncSessionOutcome))
    require_valid(changed)
    public = ProgramIndex(changed).protocol_obligations(budget=BUDGET)
    sources = public['connections']['families']['async']['session_consumers']
    assert {row['source'] for row in sources} == expected
    assert all(row['targets'] and all(target['binding'] is None for target in row['targets'])
               for row in sources)
    assert all(row['status'] == 'MISSING' for row in sources)
    limited = ProgramIndex(graph).protocol_obligations(budget=1)
    rows = limited['connections']['families']['async']['session_consumers']
    assert {row['source'] for row in rows} == expected
    assert limited['budget']['truncated'] and limited['cursor'] is not None
    assert all(not row['known_inventory_complete'] for row in rows)
    assert all(row['status'] in ('PARTIAL', 'NOT_CHECKED') for row in rows)

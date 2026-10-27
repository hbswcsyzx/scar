"""Original async-close outcomes, requests and frame termination stay distinct."""
from dataclasses import replace

import pytest

from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import DataValue, ExitKind, LiteralOrigin, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.ids import ValueID
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.protocols import DriveResult, HostTerminal, OutcomeAdapter, OutcomeAdapterRule
from scar.ir.program.resumption import SuspendTerminator, SuspensionFlavor
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_session_release_graphs import _Tail


_BUDGET = 1048576


def _graph(route):
    from tests.fixtures.program_async_close_chains_graphs import async_close_chains_program
    return async_close_chains_program(route=route)


def _checked(program):
    core = replace(program, protocol_scopes=(), protocol_operations=(), protocol_bindings=(),
        protocol_call_inputs=(), protocol_result_consumers=(), exception_matches=())
    require_valid(core)
    require_valid(program)
    return ProgramIndex(program)


def _report(index, budget=_BUDGET):
    public = index.protocol_obligations(budget=budget)
    return public, public['connections']['families']['async']


def _driven(details):
    return tuple(stage for stage in details['drivers'] if stage['drive'] is not None)


def _selected_source(report, stage):
    rows = tuple(row for row in report['session_consumers']
                 if row['source'] == stage['publication'].outcome and row['scope'] == stage['scope'].id)
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize('route', ('graceful-return', 'graceful-ge', 'graceful-ordinary', 'illegal'))
def test_real_close_chain_keeps_same_body_current_session_and_only_terminal_f(route):
    program, details = _graph(route)
    index = _checked(program)
    stages = _driven(details)
    definitions = {row.id: row for row in program.operations}
    assert len(program.resumable_creates) == 1
    assert len(stages) == 3
    assert {stage['drive'] for stage in stages} <= set(program.body_drives)
    assert len(program.async_request_creates) == (5 if route == 'illegal' else 2)
    assert len(details['drivers']) == (6 if route == 'illegal' else 3)
    first, middle, final = (definitions[stage['outcome_source']] for stage in stages)
    assert type(first.terminator) is SuspendTerminator
    assert first.terminator.flavor is SuspensionFlavor.ASYNC_YIELD
    assert type(middle.terminator) is SuspendTerminator
    assert middle.terminator.flavor is (SuspensionFlavor.ASYNC_YIELD if route == 'illegal' else SuspensionFlavor.AWAIT)
    assert final.terminator.kind is (TerminatorKind.RETURN if route == 'graceful-return' else TerminatorKind.RAISE)
    public, report = _report(index)
    assert not public['budget']['truncated']
    for ordinal, stage in enumerate(stages):
        publication = index.body_publication(stage['publication'].operation)
        assert publication.commit == stage['publication']
        assert publication.source.operation == stage['outcome_source']
        finished = index.lifecycle_after(publication.commit.operation).terminal.is_finished(publication.instance.use.value)
        assert finished is (ordinal == 2)
        source = _selected_source(report, stage)
        expected = SessionPost.HOLD if ordinal == 1 and route != 'illegal' else SessionPost.COMPLETE
        assert source['expected_post'] is expected
        assert source['known_inventory_complete'] is True
        assert source['targets']
        assert any(target['update'] == stage['update'] and target['source_binding']['match'] is True
                   for target in source['targets'])
    # A real asynchronous narrow release follows F; it remains an unknown
    # callback boundary and makes no physical-release or termination promise.
    assert program.terminal_frame_releases
    for row in program.terminal_frame_releases:
        view = index.terminal_release_publication(row.operation)
        assert index.lifecycle_before(row.operation).terminal.is_finished(view.owner.use.value)
        assert view.sources
        assert all(source.source.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                   for source in view.sources)
        operation = definitions[row.operation]
        assert operation.effects_complete is False
        assert row.rules.condition_status.value == row.rules.effects.value == 'UNKNOWN'
        assert row.rules.termination.value == 'MAY_NOT_COMPLETE'
        assert row.rules.release.value == 'NOT_GUARANTEED'
    assert public['source_runtime_verified'] is public['transformation_authorized'] is False
    assert public['protocol_implementation_complete'] is False


def test_illegal_yield_request_complete_still_rejects_release_before_real_body_terminal():
    program, details = _graph('illegal')
    index = _checked(program)
    middle = _driven(details)[1]
    publication = index.body_publication(middle['publication'].operation)
    assert index.lifecycle_after(publication.commit.operation).terminal.is_finished(publication.instance.use.value) is False
    # Reuse the original driver-tail constructor only on this exact interface;
    # restore all other original interfaces before public validation.
    local = replace(program, driver_interfaces=(middle['interface'],))
    tail = _Tail(local, middle['publication'].operation)
    tail.release(819)
    changed = replace(tail.finish(), driver_interfaces=program.driver_interfaces)
    issues = validate(changed)
    assert 'terminal_release_unfinished' in {issue.code for issue in issues}
    with pytest.raises(ValueError, match='terminal_release_unfinished'):
        ProgramIndex(changed)


def test_illegal_source_inventory_survives_missing_post_relation_and_tiny_budget():
    program, details = _graph('illegal')
    original = _checked(program)
    _, full = _report(original)
    selected = _driven(details)[1]
    missing = replace(program, protocol_bindings=tuple(row for row in program.protocol_bindings
        if not (type(row) is AsyncSessionOutcome and row.scope == selected['scope'].id
                and row.source == selected['publication'].outcome and row.update == selected['update'].operation)))
    _, removed = _report(ProgramIndex(missing))
    expected = {(row['scope'], row['source']) for row in full['session_consumers']}
    assert {(row['scope'], row['source']) for row in removed['session_consumers']} == expected
    absent = _selected_source(removed, selected)
    assert absent['expected_post'] is SessionPost.COMPLETE
    assert absent['targets'] and all(target['binding'] is None for target in absent['targets'])
    assert absent['status'] == 'MISSING'
    public, tiny = _report(original, budget=1)
    assert {(row['scope'], row['source']) for row in tiny['session_consumers']} == expected
    assert public['budget']['truncated'] is True
    assert tiny['cursor'] is not None
    assert all(row['known_inventory_complete'] is False for row in tiny['session_consumers'])
    assert public['source_runtime_verified'] is public['transformation_authorized'] is False


def test_illegal_yield_cannot_publish_hold_in_place_of_complete():
    program, details = _graph('illegal')
    selected = _driven(details)[1]
    changed = replace(program, session_updates=tuple(
        replace(row, post=SessionPost.HOLD) if row == selected['update'] else row
        for row in program.session_updates))
    assert 'async_session_post' in {issue.code for issue in validate(changed)}


def test_deleting_close_error_adapter_preserves_original_source_and_complete_obligation():
    program, details = _graph('illegal')
    selected = _driven(details)[1]
    _, full = _report(_checked(program))
    changed = replace(program, protocol_operations=tuple(row for row in program.protocol_operations
        if not (type(row.contract) is OutcomeAdapter
                and row.contract.rule is OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR
                and type(row.contract.input) is DriveResult
                and row.contract.input.outcome == selected['publication'].outcome)))
    _, removed = _report(ProgramIndex(changed))
    assert {(row['scope'], row['source']) for row in removed['session_consumers']} == {
        (row['scope'], row['source']) for row in full['session_consumers']}
    assert _selected_source(removed, selected)['expected_post'] is SessionPost.COMPLETE


@pytest.mark.parametrize('broken', ('matcher', 'bool', 'constructor_result'))
def test_handled_reply_cannot_bypass_exact_matcher_bool_and_constructor_result(broken):
    program, details = _graph('graceful-return')
    stage = _driven(details)[-1]
    reply, = tuple(row for row in stage['reply_stages'] if row.get('matchers'))
    if broken == 'matcher':
        changed = replace(program, exception_matches=())
    elif broken == 'bool':
        matcher = reply['matchers'][0]
        branch = next(row for row in program.operations if row.id == matcher.branch)
        literal = DataValue(ValueID('broken.matcher.bool'), stage['driver_region'].id,
                            LiteralOrigin(False), 'builtins.bool')
        changed = replace(program, values=(*program.values, literal), operations=tuple(
            replace(row, uses=tuple(replace(use, value=literal.id)
                if use.id == branch.terminator.condition else use for use in row.uses))
            if row.id == branch.id else row for row in program.operations))
    else:
        none, = tuple(value for value in program.values
            if type(value) is ReferenceValue and value.region == stage['driver_region'].id
            and type(value.origin) is LiteralOrigin and value.origin.value is None)
        pack = reply['pack']
        changed = replace(program, operations=tuple(replace(row, uses=tuple(
            replace(use, value=none.id) if use.id == reply['packet_definition'].exception else use
            for use in row.uses)) if row.id == pack.id else row for row in program.operations))
    require_valid(replace(changed, protocol_scopes=(), protocol_operations=(), protocol_bindings=(),
        protocol_call_inputs=(), protocol_result_consumers=(), exception_matches=()))
    codes = {issue.code for issue in validate(changed)}
    if broken == 'constructor_result':
        # PacketDefinition describes the changed actual operand. Without a
        # separate declared expected component this is missing proof, not an
        # independently established copy contradiction.
        first, = tuple(row for row in stage['reply_stages']
            if type(row['source']) is DriveResult and row['source'].outcome == stage['publication'].outcome)
        result = ProgramIndex(changed).handled_completion(first['own_results_by_kind'][ExitKind.NORMAL][0],
            HostTerminal(reply['hosts'][0].id), budget=_BUDGET)
        assert result['match'] is not True
        assert result['transformation_authorized'] is False
    else:
        assert codes & {'protocol_copy', 'exception_match_bool_source'}


@pytest.mark.parametrize('route', ('graceful-return', 'graceful-ge'))
def test_public_handler_receipt_separates_fresh_packet_from_original_and_respects_budget(route):
    program, details = _graph(route)
    index = _checked(program)
    stage = _driven(details)[-1]
    reply, = tuple(row for row in stage['reply_stages'] if row.get('matchers'))
    source = DriveResult(stage['publication'].outcome, 0)
    if route == 'graceful-return':
        first, = tuple(row for row in stage['reply_stages']
            if type(row['source']) is DriveResult and row['source'].outcome == stage['publication'].outcome)
        source = first['own_results_by_kind'][ExitKind.NORMAL][0]
    terminal = HostTerminal(reply['hosts'][0].id)
    tiny = index.handled_completion(source, terminal, budget=1)
    assert tiny['match'] is not True and tiny['budget']['truncated'] is True
    assert tiny['cursor'] is not None
    full = index.handled_completion(source, terminal, budget=_BUDGET)
    assert full['match'] is True and full['applicable'] is True
    assert full['budget']['truncated'] is False
    assert full['receipts'] and all(row['constructor'] == reply['constructor'] for row in full['receipts'])
    assert all(row['current_source'] != row['packet_source'] for row in full['receipts'])
    assert all(row['bindings'] for row in full['receipts'])
    assert all(full[flag] is False for flag in ('source_runtime_verified', 'runtime_identity_verified',
        'value_identity_verified', 'native_applicability_verified', 'transformation_authorized'))

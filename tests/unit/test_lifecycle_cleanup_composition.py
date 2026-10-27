"""Actual C1/body/driver/session/release compositions, not native proof."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.lifecycle import SessionPost, TerminalFrameRelease
from scar.ir.program.model import (
    OperationResult, StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_lifecycle_cleanup_graphs import (
    body_cleanup_session_release_program, driver_cleanup_release_program,
)


@pytest.mark.parametrize("helper", (False, True))
@pytest.mark.parametrize("factory", (body_cleanup_session_release_program, driver_cleanup_release_program))
def test_real_cleanup_lifecycle_compositions_validate(factory, helper):
    graph = factory(helper=helper)
    require_valid(graph)
    index = ProgramIndex(graph)
    assert len(graph.body_outcome_commits) == 2
    for row in graph.terminal_frame_releases:
        site = index.terminal_release_publication(row.operation)
        assert site.point.terminal.is_finished(site.owner.use.value)
        assert site.sources
    if factory is driver_cleanup_release_program:
        assert len(graph.cleanup_enters) == 2  # Existing body + new driver.
        assert ValueID("composition.entry.0") in index.cleanup_pending_copies(ControlScopeID("composition.cleanup"))


def operation(graph, name):
    return next(row for row in graph.operations if row.id == OperationID(name))


def change_operation(graph, changed):
    return replace(graph, operations=tuple(changed if row.id == changed.id else row for row in graph.operations))


def codes(graph):
    return {row.code for row in validate(graph)}


@pytest.mark.parametrize("helper", (False, True))
def test_driver_cleanup_keeps_multisource_owner_context_current_states_and_roundtrip(helper):
    graph = driver_cleanup_release_program(helper=helper)
    index = ProgramIndex(graph)
    expected = {row.operation for row in graph.body_outcome_commits}
    assert {row.outcome.source for row in graph.body_outcome_commits} == {
        OperationID("finally.return"), OperationID("finally.raise-exit.op")}
    scope = ControlScopeID("composition.cleanup")
    for release in graph.terminal_frame_releases:
        site = index.terminal_release_publication(release.operation)
        assert site.point.terminal.source_operations(site.owner.use.value) == expected
        assert {row.commit.operation for row in site.sources} == expected
        assert not index.lifecycle_after(release.operation).session.posts
    resume = operation(graph, "composition.resume")
    assert index.cleanup_action(resume.id).context in {item.id for item in resume.uses}
    selected = next(row for row in graph.cleanup_resumes if row.operation == resume.id)
    own = {row.id: row.value for row in resume.uses}
    assert own[selected.pending] in index.cleanup_pending_copies(scope)
    assert own[selected.context] in index.cleanup_context_copies(scope)
    assert index.cleanup_stack(BlockID("composition.entry")) == ()
    # Each Resume input is the exact last release result for that domain.
    released = operation(graph, "composition.release.normal" if helper else "composition.release")
    assert {row.value for row in resume.uses if row.role is UseRole.STATE_CONTENT} == set(released.results)
    restored = loads(dumps(graph))
    require_valid(restored)
    assert dumps(restored) == dumps(graph)


def test_session_post_is_current_only_and_real_helper_normal_reseeds_it():
    graph = driver_cleanup_release_program(helper=True)
    index = ProgramIndex(graph)
    post, call = OperationID("composition.post"), OperationID("composition.helper")
    entering = index.lifecycle_before(OperationID("composition.enter"))
    assert {row.post for row in entering.session.for_pair(
        ValueID("composition.entry.2"), ValueID("composition.entry.1"))} == {SessionPost.HOLD}
    assert not index.lifecycle_after(OperationID("composition.enter")).session.posts
    assert {row.post for row in index.lifecycle_after(post).session.posts} == {SessionPost.HOLD}
    assert {row.post for row in index.lifecycle_before(call).session.posts} == {SessionPost.HOLD}
    assert not index.lifecycle_after(call).session.posts
    assert {row.post for row in index.lifecycle_edge(call, 0).session.posts} == {
        SessionPost.COMPLETE, SessionPost.ABANDON}
    assert not index.lifecycle_edge(call, 1).session.posts
    assert index.session_publication(call).normal_successor is operation(graph, call.value).terminator.successors[0]
    assert not index.lifecycle_after(OperationID("composition.resume")).session.posts
    assert not index.lifecycle_after(OperationID("composition.replace")).session.posts
    failed = operation(graph, "composition.helper").terminator.successors[1]
    assert failed.block == BlockID("composition.helper.raise")
    replacement = operation(graph, "composition.replace")
    assert next(block.operations for region in graph.regions for block in region.blocks
                if block.id == BlockID("composition.replace-block")) == (
                    replacement.id, OperationID("composition.replace.jump"))
    fresh = operation(graph, "composition.fresh-raise").results[0]
    assert index.use_site(UseID("composition.failed.jump.1")).use.value == fresh
    definition = next(row for row in graph.pending_completions if row.value == fresh)
    assert index.use_site(definition.payload).use.value == ValueID("composition.helper.raise.0")


@pytest.mark.parametrize("through_phi", (False, True))
def test_wrong_request_or_one_unfinished_phi_arm_is_not_terminal_owner(through_phi):
    graph = driver_cleanup_release_program()
    if through_phi:
        commit = next(row for row in graph.body_outcome_commits
                      if operation(graph, row.outcome.source.value).terminator.kind is TerminatorKind.RETURN)
        number = graph.body_outcome_commits.index(commit)
        route = operation(graph, f"composition.route-in.{number}")
        block = next(block for region in graph.regions for block in region.blocks if route.id in block.operations)
        route = replace(route, uses=tuple(replace(row, value=block.arguments[0])
            if row.id == UseID(f"composition.route-in.{number}.1") else row for row in route.uses))
        graph = change_operation(graph, route)
    else:
        release = operation(graph, "composition.release")
        graph = change_operation(graph, replace(release, uses=tuple(replace(row,
            value=graph.driver_interfaces[0].receiver) if row.role is UseRole.REFERENCE else row
            for row in release.uses)))
    assert "terminal_release_unfinished" in codes(graph)


def test_saved_context_is_not_a_saved_old_world_after_release():
    graph = driver_cleanup_release_program()
    resume, enter = operation(graph, "composition.resume"), operation(graph, "composition.enter")
    values = {row.id: row for row in graph.values}
    old = {values[row].location: row for row in enter.results if isinstance(values[row], StateVersionValue)}
    before = resume.accesses[-1].before
    graph = change_operation(graph, replace(resume, uses=tuple(replace(row,
        value=old[values[row.value].location]) if row.id == before else row for row in resume.uses)))
    assert "stale_state" in codes(graph)


@pytest.mark.parametrize("saved_context", (False, True))
def test_private_pending_and_context_are_cfg_forwards_not_opaque_arguments(saved_context):
    graph = driver_cleanup_release_program(helper=True)
    call = operation(graph, "composition.helper")
    source = operation(graph, "composition.enter").results[0] if saved_context else ValueID("composition.entry.0")
    escaped = Use(UseID("composition.escape"), source, UseRole.PROTOCOL)
    graph = change_operation(graph, replace(call, uses=(*call.uses, escaped),
                                           invoke_arguments=(*call.invoke_arguments, escaped.id)))
    assert ("cleanup_context_escape" if saved_context else "pending_escape") in codes(graph)


def test_release_before_any_terminal_commit_cannot_borrow_future_history():
    graph = driver_cleanup_release_program()
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(row for row in region.blocks if row.id == region.entry)
    values = {row.id: row for row in graph.values}
    current = {values[row].location: row for row in entry.arguments if isinstance(values[row], StateVersionValue)}
    template = operation(graph, "composition.release")
    identity = OperationID("composition.early-release")
    own = (Use(UseID("composition.early.owner"), entry.arguments[0], UseRole.REFERENCE),
           *(Use(UseID(f"composition.early.before.{index}"), current[access.location], UseRole.STATE_CONTENT)
             for index, access in enumerate(template.accesses)))
    outputs = tuple(StateVersionValue(ValueID(f"composition.early.after.{index}"), region.id,
        OperationResult(identity, index), access.location) for index, access in enumerate(template.accesses))
    early = replace(template, id=identity, uses=own, results=tuple(row.id for row in outputs),
        accesses=tuple(replace(access, before=own[index + 1].id, after=outputs[index].id)
                       for index, access in enumerate(template.accesses)))
    after = {row.location: row.id for row in outputs}
    gate = operation(graph, "driver.gate")
    gate = replace(gate, uses=tuple(replace(row, value=after[values[row.value].location])
        if isinstance(values[row.value], StateVersionValue) else row for row in gate.uses))
    graph = change_operation(graph, gate)
    graph = replace(graph, operations=(*graph.operations, early), values=(*graph.values, *outputs),
        terminal_frame_releases=(*graph.terminal_frame_releases, TerminalFrameRelease(identity, own[0].id)),
        regions=tuple(replace(row, blocks=tuple(replace(block, operations=(identity, *block.operations))
            if block.id == entry.id else block for block in row.blocks)) if row.id == region.id else row
            for row in graph.regions))
    assert "terminal_release_unfinished" in codes(graph)

"""Connect actual body cleanup sources, publication and both helper outcomes."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import ExitKind, StateVersionValue, TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_lifecycle_body_composition import body_cleanup_lifecycle_program


@pytest.mark.parametrize("binding", ("AFTER_OPERATION", "NORMAL_COMPLETION"))
def test_actual_cleanup_return_and_raise_frontier_keep_independent_terminal_sources(binding):
    graph = body_cleanup_lifecycle_program(binding=binding)
    index = ProgramIndex(graph)
    assert len(graph.body_outcome_commits) == 2
    source_kinds = {index.operations[row.outcome.source].terminator.kind
                    for row in graph.body_outcome_commits}
    assert source_kinds == {TerminatorKind.RETURN, TerminatorKind.RAISE}
    assert graph.cleanup_interfaces and graph.cleanup_resumes and graph.cleanup_replacements
    assert graph.handled_context_domains
    for number, commit in enumerate(graph.body_outcome_commits):
        release = index.terminal_release_publication(OperationID(f"session.release.{number}"))
        assert len(release.sources) == 1
        assert release.sources[0].commit is commit
        assert release.sources[0].source.operation == commit.outcome.source
        assert {item.access.location for item in release.accesses} > set(graph.driver_interfaces[0].lifecycle)
        point = index.lifecycle_before(release.release.operation)
        assert point.terminal.is_finished(release.owner.use.value)
        assert index.lifecycle_after(release.release.operation).session.posts == ()


def test_real_helper_normal_and_raise_use_each_current_partial_poststate():
    graph = body_cleanup_lifecycle_program(binding="NORMAL_COMPLETION")
    index = ProgramIndex(graph)
    for number, update in enumerate(graph.session_updates):
        helper = index.operations[update.operation]
        assert {edge.kind for edge in helper.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
        view = index.session_publication(update.operation)
        normal = next(i for i, edge in enumerate(helper.terminator.successors) if edge.kind is ExitKind.NORMAL)
        raised = next(i for i, edge in enumerate(helper.terminator.successors) if edge.kind is ExitKind.RAISE)
        assert {fact.post for fact in index.lifecycle_edge(helper.id, normal).session.posts} == {
            SessionPost.COMPLETE, SessionPost.ABANDON}
        assert index.lifecycle_edge(helper.id, raised).session.posts == ()
        normal_release = index.terminal_release_publication(OperationID(f"session.release.{number}"))
        raise_release = index.terminal_release_publication(OperationID(f"session.release.{100 + number}"))
        assert normal_release.sources == raise_release.sources
        for edge, release in ((helper.terminator.successors[normal], normal_release),
                              (helper.terminator.successors[raised], raise_release)):
            block = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
            current = {value for value in block.arguments if isinstance(index.values[value], StateVersionValue)}
            assert {item.before.use.value for item in release.accesses} == current
        assert view.support


def test_unknown_callback_invalidates_post_but_does_not_erase_actual_terminal_history():
    graph = body_cleanup_lifecycle_program(callback=True)
    index = ProgramIndex(graph)
    for number, update in enumerate(graph.session_updates):
        assert index.lifecycle_after(update.operation).session.posts
        release = index.terminal_release_publication(OperationID(f"session.release.{number}"))
        point = index.lifecycle_before(release.release.operation)
        assert point.session.posts == ()
        assert point.terminal.is_finished(release.owner.use.value)


def test_body_cleanup_suspend_is_not_a_terminal_source_even_if_session_completes():
    graph = body_cleanup_lifecycle_program(target="start", release=False)
    assert not validate(graph)
    invalid = body_cleanup_lifecycle_program(target="start")
    assert "terminal_release_unfinished" in {issue.code for issue in validate(invalid)}


def test_cleanup_does_not_make_request_alias_the_finished_body():
    graph = body_cleanup_lifecycle_program()
    row = graph.terminal_frame_releases[0]
    index = ProgramIndex(graph)
    operation = index.operations[row.operation]
    request = graph.driver_interfaces[0].receiver
    changed = replace(operation, uses=tuple(replace(use, value=request) if use.id == row.owner else use
                                            for use in operation.uses))
    invalid = replace(graph, operations=tuple(changed if op.id == changed.id else op for op in graph.operations))
    assert "terminal_release_unfinished" in {issue.code for issue in validate(invalid)}


def test_raise_release_cannot_read_the_helpers_preinvoke_state():
    graph = body_cleanup_lifecycle_program(binding="NORMAL_COMPLETION")
    index = ProgramIndex(graph)
    row = next(row for row in graph.terminal_frame_releases if row.operation == OperationID("session.release.100"))
    release = index.operations[row.operation]
    helper = index.operations[OperationID("body.helper.0")]
    access = release.accesses[0]
    old = next(use.value for use in helper.uses if isinstance(index.values[use.value], StateVersionValue)
               and index.values[use.value].location == access.location)
    changed = replace(release, uses=tuple(replace(use, value=old) if use.id == access.before else use
                                          for use in release.uses))
    invalid = replace(graph, operations=tuple(changed if op.id == changed.id else op for op in graph.operations))
    assert "stale_state" in {issue.code for issue in validate(invalid)}

"""Original session/release endpoints and explicitly conditional flow queries."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from scar.ir.program.codec import dumps
from scar.ir.program.ids import OperationID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import AccessMode, ExitKind
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_session_release_graphs import session_release_program


@pytest.mark.parametrize("binding", ("AFTER_OPERATION", "NORMAL_COMPLETION"))
@pytest.mark.parametrize("source", ("return", "raise", "no-body"))
def test_post_queries_preserve_exact_uses_and_real_current_support(binding, source):
    graph = session_release_program(binding=binding, source=source, strict_subset=True, extra_domain=True)
    raw = dumps(graph)
    index = ProgramIndex(graph)
    row, = graph.session_updates
    assert index.session_update(row.operation) is row
    view = index.session_publication(row.operation)
    assert view.update is row
    assert view.request is index.use_site(row.request)
    assert view.body is index.use_site(row.body)
    assert all(value is index.values[value.id] for value in view.support)
    assert {value.location for value in view.support} == set(graph.driver_interfaces[0].lifecycle)
    if binding == "AFTER_OPERATION":
        assert view.normal_successor is None
        assert all(item.before is index.use_site(item.access.before) for item in view.accesses)
        assert {item.after for item in view.accesses if item.after is not None} <= set(view.support)
        point = index.lifecycle_after(row.operation)
    else:
        operation = index.operations[row.operation]
        number = next(i for i, edge in enumerate(operation.terminator.successors) if edge.kind is ExitKind.NORMAL)
        assert view.normal_successor is operation.terminator.successors[number]
        assert not view.accesses
        assert all(site is index.use_site(site.use.id) for site in view.state_inputs)
        point = index.lifecycle_edge(row.operation, number)
    facts = point.session.for_pair(view.request.use.value, view.body.use.value)
    assert {fact.post for fact in facts} == {SessionPost.COMPLETE, SessionPost.ABANDON}
    assert all(fact.support == view.support and fact.sources == {row.operation} for fact in facts)
    assert dumps(graph) == raw


@pytest.mark.parametrize("source", ("return", "raise", "no-body"))
def test_release_view_resolves_original_finish_sources_without_new_producers(source):
    graph = session_release_program(source=source, repeat_release=True)
    index = ProgramIndex(graph)
    for row in graph.terminal_frame_releases:
        assert index.terminal_frame_release(row.operation) is row
        view = index.terminal_release_publication(row.operation)
        assert view.release is row and view.owner is index.use_site(row.owner)
        point = index.lifecycle_before(row.operation)
        assert point.terminal.is_finished(view.owner.use.value)
        assert view.sources
        for origin in view.sources:
            if source == "no-body":
                assert origin.finish is graph.no_body_finishes[0]
            else:
                assert origin.commit is graph.body_outcome_commits[0]
        for item in view.accesses:
            assert item.access.mode is AccessMode.READ_WRITE
            assert item.after is index.values[item.access.after]
            assert index.producer(item.after.id) is item.after.origin
        assert index.lifecycle_after(row.operation).terminal.is_finished(view.owner.use.value)
        assert not index.lifecycle_after(row.operation).session.posts


def test_query_getters_remain_strict_and_absent_on_existing_operations():
    graph = session_release_program()
    index = ProgramIndex(graph)
    ordinary = graph.body_outcome_commits[0].operation
    for method in (index.session_update, index.session_publication, index.terminal_frame_release,
                   index.terminal_release_publication, index.lifecycle_before, index.lifecycle_after):
        with pytest.raises(TypeError):
            method("not-an-operation")
        with pytest.raises(KeyError):
            method(OperationID("missing"))
    assert index.session_update(ordinary) is index.terminal_frame_release(ordinary) is None
    assert index.session_publication(ordinary) is index.terminal_release_publication(ordinary) is None
    assert index.lifecycle_before(OperationID("resume.return")) is None
    for number in (True, -1, 999):
        with pytest.raises(ValueError):
            index.lifecycle_edge(ordinary, number)


def test_query_construction_cannot_bypass_the_terminal_owner_premise():
    with pytest.raises(ValueError, match="terminal_release_unfinished"):
        ProgramIndex(session_release_program(source="suspend"))


@pytest.mark.parametrize("binding", ("AFTER_OPERATION", "NORMAL_COMPLETION"))
def test_cli_separates_declared_flow_from_native_runtime_and_transformation(binding, tmp_path, capsys):
    from scar.cli import _check_program

    graph = session_release_program(binding=binding)
    path = tmp_path / "program.json"
    path.write_text(dumps(graph))
    assert _check_program(SimpleNamespace(graph=str(path), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["session_release_structure_validated"] is True
    assert report["conditional_lifecycle_facts_derived"] is True
    assert report["counts"]["session_updates"] == report["counts"]["terminal_frame_releases"] == 1
    for name in ("source_recovery", "transformation_authorized", "driver_lifecycle_verified",
                 "body_driver_verified", "body_runtime_verified", "body_source_verified"):
        assert report[name] is False

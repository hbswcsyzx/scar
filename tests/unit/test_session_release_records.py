"""D2.3 records declare conditional effects, never producer or runtime authority."""
from dataclasses import FrozenInstanceError, fields, replace
from functools import cache

import pytest

import scar.ir.program as program
from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import (
    LifecyclePostBinding, SessionPost, SessionUpdate, TerminalFrameRelease,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, Operation, ProgramGraph, ReferenceValue,
    Region, Use, UseRole,
)
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness, ProofStatus


def _update(tag="session", **changes):
    values = dict(operation=OperationID(tag), request=UseID(tag + ".r"),
                  body=UseID(tag + ".b"), binding=LifecyclePostBinding.AFTER_OPERATION,
                  post=SessionPost.COMPLETE)
    values.update(changes)
    return SessionUpdate(**values)


def _release(tag="release", **changes):
    values = dict(operation=OperationID(tag), owner=UseID(tag + ".owner"))
    values.update(changes)
    return TerminalFrameRelease(**values)


def _graph(**tables):
    region = RegionID("root")
    entry = Block(BlockID("entry"), (), ())
    return ProgramGraph(region, (Region(region, "root", entry.id, (entry,), ()),),
                        (), (), **tables)


def test_records_have_only_contract_fields_are_public_frozen_and_wire_roundtrip():
    assert program.LifecyclePostBinding is LifecyclePostBinding
    assert program.SessionPost is SessionPost
    assert program.SessionUpdate is SessionUpdate
    assert program.TerminalFrameRelease is TerminalFrameRelease
    assert tuple(f.name for f in fields(SessionUpdate)) == (
        "operation", "request", "body", "binding", "post")
    assert tuple(f.name for f in fields(TerminalFrameRelease)) == (
        "operation", "owner", "rules")
    for row in (_update(), _release()):
        assert not hasattr(row, "__dict__")
        assert decode(type(row), encode(row)) == row
        with pytest.raises(FrozenInstanceError):
            row.operation = OperationID("other")
    assert _release().rules == FrameRules()
    with pytest.raises(TypeError):
        TerminalFrameRelease(OperationID("release"), UseID("owner"), verified=True)


@pytest.mark.parametrize("binding", list(LifecyclePostBinding))
@pytest.mark.parametrize("post", list(SessionPost))
def test_both_binding_widths_and_posts_are_exact_declarations(binding, post):
    row = _update(binding=binding, post=post)
    assert row.binding is binding and row.post is post
    with pytest.raises(TypeError, match="exact LifecyclePostBinding"):
        _update(binding=binding.value)
    with pytest.raises(TypeError, match="exact SessionPost"):
        _update(post=post.value)


def test_distinct_use_occurrences_may_reference_the_same_actual_object():
    row = _update()
    region, block, actual = RegionID("root"), BlockID("entry"), ValueID("same.object")
    uses = (Use(row.request, actual, UseRole.REFERENCE),
            Use(row.body, actual, UseRole.REFERENCE))
    operation = Operation(row.operation, "declared session update", (Behavior.CONTROL,), uses)
    entry = Block(block, (actual,), (operation.id,))
    graph = ProgramGraph(region, (Region(region, "root", block, (entry,), ()),),
                         (operation,), (ReferenceValue(actual, region, BlockArgument(block, 0)),),
                         session_updates=(row,))
    assert graph.operations[0].uses[0].value == graph.operations[0].uses[1].value
    with pytest.raises(ValueError, match="UseIDs must be distinct"):
        _update(body=row.request)


def test_wrong_id_families_id_subclasses_and_booleans_cannot_enter_records():
    class DerivedUseID(UseID):
        pass

    for changes in ({"operation": RegionID("wrong")},
                    {"request": DerivedUseID("r")}, {"body": True},
                    {"binding": True}, {"post": False}):
        with pytest.raises(TypeError):
            _update(**changes)
    for changes in ({"operation": "op"}, {"owner": ValueID("wrong")},
                    {"owner": DerivedUseID("owner")}):
        with pytest.raises(TypeError):
            _release(**changes)


def test_frame_rules_are_exact_and_private_nested_mutations_are_rechecked():
    class DerivedRules(FrameRules):
        __slots__ = ()

    with pytest.raises(TypeError, match="exact FrameRules"):
        _release(rules=DerivedRules())
    for name, corrupted in (("condition_status", ProofStatus.PROVEN),
                            ("effects", Completeness.COMPLETE),
                            ("finalizer_errors", "UNRAISABLE")):
        rules = FrameRules()
        object.__setattr__(rules, name, corrupted)
        with pytest.raises(ValueError, match="FrameRules"):
            _release(rules=rules)
    # Deliberately corrupt a private per-test record, never the shared frozen
    # default used by unrelated constructor calls in this Python process.
    row = _release(rules=FrameRules())
    object.__setattr__(row.rules, "release", True)
    with pytest.raises(ValueError, match="FrameRules"):
        _graph(terminal_frame_releases=(row,))


def test_graph_tables_require_exact_tuples_records_unique_keys_and_nested_recheck():
    row = _update()
    with pytest.raises(TypeError, match="tuple"):
        _graph(session_updates=[row])
    with pytest.raises(TypeError, match="exact typed records"):
        _graph(session_updates=(_release(),))
    for name, item in (("session_updates", row), ("terminal_frame_releases", _release())):
        with pytest.raises(ValueError, match="operations"):
            _graph(**{name: (item, item)})
    object.__setattr__(row, "post", "COMPLETE")
    with pytest.raises(TypeError, match="exact SessionPost"):
        _graph(session_updates=(row,))


@cache
def _prior_roles():
    from tests.fixtures.program_cleanup_graphs import resume_multistate_graph
    from tests.fixtures.program_driver_graphs import async_request_program
    from tests.fixtures.program_no_body_graphs import no_body_program
    from tests.fixtures.program_resumption_graphs import resumption_cleanup_program

    graphs = (no_body_program(), async_request_program(),
              resumption_cleanup_program(), resumption_cleanup_program(replace_pending=True),
              resume_multistate_graph())
    names = ("body_outcome_commits", "created_close_tests", "no_body_finishes",
             "resumable_creates", "async_request_creates", "request_association_reads",
             "final_body_gates", "body_drives", "frame_context_initials",
             "frame_context_attaches", "frame_context_detaches", "cleanup_enters",
             "cleanup_resumes", "cleanup_replacements", "handled_context_reads")
    return {name: next(row for graph in graphs for row in getattr(graph, name))
            for name in names}


@pytest.mark.parametrize("role", (
    "body_outcome_commits", "created_close_tests", "no_body_finishes",
    "resumable_creates", "async_request_creates", "request_association_reads",
    "final_body_gates", "body_drives", "frame_context_initials",
    "frame_context_attaches", "frame_context_detaches", "cleanup_enters",
    "cleanup_resumes", "cleanup_replacements", "handled_context_reads"))
def test_new_actions_cannot_overlay_any_existing_lifecycle_driver_context_cleanup_role(role):
    previous = _prior_roles()[role]
    for name, row in (("session_updates", _update()),
                      ("terminal_frame_releases", _release())):
        with pytest.raises(ValueError, match="lifecycle action operation IDs|conflicts"):
            _graph(**{role: (previous,), name: (replace(row, operation=previous.operation),)})


def test_session_and_release_conflict_but_distinct_release_attempts_share_owner_legally():
    update, release = _update(), _release()
    with pytest.raises(ValueError, match="lifecycle action operation IDs"):
        _graph(session_updates=(update,),
               terminal_frame_releases=(replace(release, operation=update.operation),))
    second = replace(release, operation=OperationID("second.attempt"))
    graph = _graph(terminal_frame_releases=(release, second))
    assert graph.terminal_frame_releases == (release, second)
    # Neither source applicability nor one-time ownership/free is asserted.
    assert all(row.rules.effects is Completeness.UNKNOWN for row in graph.terminal_frame_releases)

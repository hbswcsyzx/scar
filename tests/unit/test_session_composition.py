"""Current session facts across real joins, loops and body-only state changes."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import (
    AccessMode, Behavior, Footprint, FootprintKind, Operation, OperationResult,
    StateAccess, StateVersionValue, Use, UseRole,
)
from scar.ir.program.validation import validate
from tests.fixtures.program_session_release_graphs import _Tail, session_release_program
from tests.unit.test_lifecycle_flow import _shared_flow_graph


def analyze(graph):
    collected = []
    issues = validate(graph, _lifecycle_facts=collected)
    assert not issues, issues
    return collected[0][graph.driver_interfaces[0].region]


def operation(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def pair(graph, row):
    own = {use.id: use.value for use in operation(graph, row.operation).uses}
    return own[row.request], own[row.body]


def with_path_posts(*, left, right, loop=False, wrong_owner=False):
    graph, owner = _shared_flow_graph(loop=loop, wrong_owner=wrong_owner)
    marks = (graph.no_body_finishes[0], graph.body_outcome_commits[0])
    for index, (row, post) in enumerate(zip(marks, (left, right))):
        if post is not None:
            tail = _Tail(graph, row.operation)
            tail.metadata(SessionPost(post), f"path.post.{index}")
            graph = tail.finish()
    # These are explicit pure forwarding jumps, not unknown callback regions.
    ids = {OperationID("driver.no_body.return"), OperationID("driver.outcome.exit")}
    graph = replace(graph, operations=tuple(replace(op, effects_complete=True) if op.id in ids else op
                                            for op in graph.operations))
    return graph, owner


@pytest.mark.parametrize("loop", (False, True))
@pytest.mark.parametrize("left,right,expected", (
    ("COMPLETE", "COMPLETE", {SessionPost.COMPLETE, SessionPost.ABANDON}),
    ("COMPLETE", "ABANDON", {SessionPost.ABANDON}),
    ("HOLD", "HOLD", {SessionPost.HOLD}),
    ("HOLD", "ABANDON", set()),
    ("COMPLETE", None, set()),
))
def test_posts_are_renamed_on_each_path_before_must_join_and_loop_meet(left, right, expected, loop):
    graph, owner = with_path_posts(left=left, right=right, loop=loop)
    facts = analyze(graph)
    identity = OperationID("flow.loop" if loop else "flow.return")
    point = facts.session.before[identity]
    posts = point.for_pair(owner, owner)
    assert {fact.post for fact in posts} == expected
    assert facts.terminal.before[identity].is_finished(owner)
    if expected:
        assert all(fact.sources == {OperationID("path.post.0"), OperationID("path.post.1")} for fact in posts)
        block = next(block for region in graph.regions for block in region.blocks if identity in block.operations)
        states = {value.id: value for value in graph.values if isinstance(value, StateVersionValue)}
        assert {value.id for value in posts[0].support} <= set(block.arguments)
        assert all(states[value.id] is value for value in posts[0].support)


def test_same_source_sets_cannot_cross_an_unrelated_owner_at_the_join():
    graph, owner = with_path_posts(left="COMPLETE", right="COMPLETE", wrong_owner=True)
    facts = analyze(graph)
    point = facts.session.before[OperationID("flow.return")]
    assert not point.for_pair(owner, owner)
    assert not facts.terminal.before[OperationID("flow.return")].is_finished(owner)


def test_no_body_state_publication_rebases_an_existing_post_without_creating_it():
    graph = session_release_program(source="no-body", release=False)
    predicate, = graph.created_close_tests
    op = operation(graph, predicate.operation)
    body = next(use.value for use in op.uses if use.id == predicate.instance)
    tail = _Tail(graph, predicate.operation, body=body)
    # Place a real metadata operation before the existing read-test/branch.
    tail.active = []
    tail.metadata(SessionPost.HOLD, "pretest.session")
    old_test = tail.operations[predicate.operation]
    tail.operations[old_test.id] = replace(old_test, uses=tuple(
        replace(use, value=tail.current[tail.values[use.value].location])
        if isinstance(tail.values[use.value], StateVersionValue) else use for use in old_test.uses))
    tail.active.append(old_test.id)
    graph = tail.finish()
    facts = analyze(graph)
    update = next(row for row in graph.session_updates if row.operation == OperationID("pretest.session"))
    request, body = pair(graph, update)
    finish, = graph.no_body_finishes
    before = facts.session.before[finish.operation].for_pair(request, body)
    after = facts.session.after[finish.operation].for_pair(request, body)
    assert {fact.post for fact in before} == {SessionPost.HOLD}
    assert {fact.post for fact in after} == {SessionPost.HOLD}
    assert all(fact.sources == {update.operation} for fact in (*before, *after))
    assert before[0].support != after[0].support
    assert any(isinstance(value.origin, OperationResult) and value.origin.operation == finish.operation
               for value in after[0].support)
    # The alternative actually enters the body and cannot inherit that P.
    assert not facts.session.before[graph.body_outcome_commits[0].operation].posts


@pytest.mark.parametrize("inside", (False, True))
def test_declared_writes_invalidate_only_session_support_domains(inside):
    graph = session_release_program(release=False, extra_domain=True)
    update, = graph.session_updates
    request, body = pair(graph, update)
    tail = _Tail(graph, update.operation, body=body, request=request)
    location = (tail.interface.lifecycle[0] if inside
                else next(location for location in tail.current if location not in tail.interface.lifecycle))
    identity = OperationID("ordinary.mutation")
    before = Use(UseID("ordinary.before"), tail.current[location], UseRole.STATE_CONTENT)
    after = StateVersionValue(ValueID("ordinary.after"), tail.region.id, OperationResult(identity, 0), location)
    tail.values[after.id] = after
    tail._add(Operation(identity, "declared complete mutation", (Behavior.READ, Behavior.WRITE), (before,),
        (after.id,), (StateAccess(location, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),),
        effects_complete=True))
    tail.current[location] = after.id
    facts = analyze(tail.finish())
    assert facts.session.before[identity].for_pair(request, body)
    assert bool(facts.session.after[identity].for_pair(request, body)) is not inside

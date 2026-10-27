"""Focused checks for derived session predicates over the actual driver CFG."""
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost
from scar.ir.program.model import AccessMode, StateVersionValue
from scar.ir.program.session_flow import _reference_targets, _rename_relation
from scar.ir.program.validation import validate
from tests.fixtures.program_session_release_graphs import session_release_program


def _analyze(graph):
    collected = []
    issues = validate(graph, _lifecycle_facts=collected)
    assert not issues, issues
    assert len(collected) == 1
    interface, = graph.driver_interfaces
    return collected[0][interface.region]


def _operation(graph, operation_id):
    return next(operation for operation in graph.operations if operation.id == operation_id)


def _pair(graph, row):
    operation = _operation(graph, row.operation)
    uses = {use.id: use for use in operation.uses}
    return uses[row.request].value, uses[row.body].value


def test_after_operation_support_uses_exact_lifecycle_current_state_versions():
    graph = session_release_program(extra_domain=True, release=False)
    facts = _analyze(graph)
    interface, = graph.driver_interfaces
    row, = graph.session_updates
    request, body = _pair(graph, row)
    point = facts.session.after[row.operation]
    posts = point.for_pair(request, body)
    by_post = {fact.post: fact for fact in posts}

    assert set(by_post) == {SessionPost.COMPLETE, SessionPost.ABANDON}
    assert point.reachable
    assert len(interface.lifecycle) < len({
        value.location for value in graph.values if isinstance(value, StateVersionValue)
    })

    operation = _operation(graph, row.operation)
    use_values = {use.id: use.value for use in operation.uses}
    accesses = {access.location: access for access in operation.accesses}
    expected = []
    values = {value.id: value for value in graph.values}
    for location in interface.lifecycle:
        access = accesses[location]
        value_id = (access.after if access.mode is AccessMode.READ_WRITE
                    else use_values[access.before])
        expected.append(values[value_id])
    assert by_post[SessionPost.COMPLETE].support == tuple(expected)
    assert all(type(value) is StateVersionValue for value in expected)
    assert tuple(value.location for value in expected) == interface.lifecycle


def test_normal_completion_seeds_only_its_real_normal_edge_and_not_raise():
    graph = session_release_program(binding="NORMAL_COMPLETION", post="HOLD", release=False)
    facts = _analyze(graph)
    row = next(row for row in graph.session_updates
               if row.binding is LifecyclePostBinding.NORMAL_COMPLETION)
    request, body = _pair(graph, row)
    operation = _operation(graph, row.operation)
    normal_index, normal_edge = next((index, edge) for index, edge in enumerate(operation.terminator.successors)
                                     if edge.kind.value == "NORMAL")
    raise_index, raise_edge = next((index, edge) for index, edge in enumerate(operation.terminator.successors)
                                   if edge.kind.value == "RAISE")

    assert facts.session.after[row.operation].for_pair(request, body) == ()
    normal = facts.session.edges[(row.operation, normal_index)].for_pair(request, body)
    assert len(normal) == 1 and normal[0].post is SessionPost.HOLD
    assert facts.session.edges[(row.operation, raise_index)].for_pair(request, body) == ()

    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    landing = blocks[normal_edge.block]
    state_args = {value.location: value
                  for value_id in landing.arguments
                  if isinstance((value := next(item for item in graph.values if item.id == value_id)),
                                StateVersionValue)}
    assert tuple(normal[0].support) == tuple(state_args[location] for location in graph.driver_interfaces[0].lifecycle)
    assert raise_edge.block != normal_edge.block


def test_callback_kills_current_session_facts_but_keeps_terminal_history():
    graph = session_release_program(callback=True, repeat_release=True)
    facts = _analyze(graph)
    row, = graph.session_updates
    request, body = _pair(graph, row)
    callback = next(operation for operation in graph.operations
                    if operation.id == OperationID("session.callback"))
    assert facts.session.before[callback.id].for_pair(request, body)
    assert facts.session.after[callback.id].for_pair(request, body) == ()
    for index, _edge in enumerate(callback.terminator.successors):
        assert facts.session.edges[(callback.id, index)].for_pair(request, body) == ()

    for release in graph.terminal_frame_releases:
        operation = _operation(graph, release.operation)
        owner = next(use.value for use in operation.uses if use.id == release.owner)
        assert facts.terminal.before[release.operation].is_finished(owner)
        assert facts.terminal.after[release.operation].is_finished(owner)
        assert facts.session.after[release.operation].for_pair(request, body) == ()


def test_complete_post_does_not_turn_a_suspended_body_into_a_terminal_body():
    graph = session_release_program(source="suspend", post="COMPLETE", release=False)
    facts = _analyze(graph)
    row, = graph.session_updates
    request, body = _pair(graph, row)
    assert {fact.post for fact in facts.session.after[row.operation].for_pair(request, body)} == {
        SessionPost.COMPLETE, SessionPost.ABANDON,
    }
    assert not facts.terminal.after[row.operation].is_finished(body)


def test_simultaneous_pair_renaming_keeps_roles_and_shared_body_facts_separate():
    request_a, request_b, body = map(ValueID, ("R.a", "R.b", "B.shared"))
    next_a, next_b, next_body = map(ValueID, ("R.a.next", "R.b.next", "B.next"))
    carriers = (request_a, request_b, body, next_a, next_b, next_body)
    assignments = {next_a: request_a, next_b: request_b, next_body: body}
    targets = _reference_targets(assignments, carriers)
    relation = frozenset({
        (request_a, body, SessionPost.COMPLETE),
        (request_b, body, SessionPost.ABANDON),
    })

    renamed = _rename_relation(relation, targets)
    assert (next_a, next_body, SessionPost.COMPLETE) in renamed
    assert (next_b, next_body, SessionPost.ABANDON) in renamed
    assert (next_a, next_body, SessionPost.ABANDON) not in renamed
    assert (next_b, next_body, SessionPost.COMPLETE) not in renamed


def test_simultaneous_swap_and_same_value_role_alias_are_not_conflated():
    request, body = ValueID("R"), ValueID("B")
    next_request, next_body = ValueID("R.next"), ValueID("B.next")
    carriers = (request, body, next_request, next_body)
    swap_targets = _reference_targets({next_request: body, next_body: request}, carriers)
    swapped = _rename_relation(frozenset({(request, body, SessionPost.HOLD)}), swap_targets)
    assert (next_body, next_request, SessionPost.HOLD) in swapped
    assert (next_request, next_body, SessionPost.HOLD) not in swapped

    same = ValueID("R.and.B")
    request_copy, body_copy = ValueID("R.copy"), ValueID("B.copy")
    alias_targets = _reference_targets({request_copy: same, body_copy: same},
                                       (same, request_copy, body_copy))
    aliases = _rename_relation(frozenset({(same, same, SessionPost.COMPLETE)}), alias_targets)
    assert (request_copy, body_copy, SessionPost.COMPLETE) in aliases
    assert (request_copy, body_copy, SessionPost.ABANDON) not in aliases

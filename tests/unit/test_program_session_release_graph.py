"""D2.3 adversarial canonical graphs, not native lifecycle implementations."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID
from scar.ir.program.lifecycle import LifecyclePostBinding
from scar.ir.program.model import AccessMode, Behavior, Footprint, FootprintKind, ReferenceValue, StateVersionValue
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_session_release_graphs import _Tail, session_release_program


def op(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def change(graph, operation):
    return replace(graph, operations=tuple(operation if row.id == operation.id else row for row in graph.operations))


def codes(graph):
    return {issue.code for issue in validate(graph)}


@pytest.mark.parametrize("binding", ("AFTER_OPERATION", "NORMAL_COMPLETION"))
@pytest.mark.parametrize("source", ("return", "raise", "no-body"))
def test_actual_terminal_owner_partial_lifecycle_and_whole_driver_release(binding, source):
    graph = session_release_program(binding=binding, source=source, repeat_release=True, extra_domain=True)
    require_valid(graph)
    interface, = graph.driver_interfaces
    post = op(graph, graph.session_updates[0].operation)
    if binding == "AFTER_OPERATION":
        assert {item.location for item in post.accesses} == set(interface.lifecycle)
    first, second = graph.terminal_frame_releases
    for row in (first, second):
        release = op(graph, row.operation)
        assert {item.location for item in release.accesses} > set(interface.lifecycle)
        assert not release.effects_complete
        assert row.rules.release.value == "NOT_GUARANTEED"


def test_shared_distinct_completion_sources_and_loop_preserve_exact_release_owner():
    from tests.unit.test_lifecycle_flow import _shared_flow_graph
    for loop in (False, True):
        graph, owner = _shared_flow_graph(loop=loop)
        if loop:
            from scar.ir.program.ids import ValueID
            owner = ValueID("flow.exit.owner")
        tail = _Tail(graph, OperationID("flow.return"), body=owner)
        tail.release(0)
        tail.release(1)
        require_valid(tail.finish())


def test_renaming_an_unfinished_payload_to_the_shared_owner_does_not_pass_release():
    from tests.unit.test_lifecycle_flow import _shared_flow_graph
    graph, owner = _shared_flow_graph(wrong_owner=True)
    tail = _Tail(graph, OperationID("flow.return"), body=owner)
    tail.release(0)
    assert "terminal_release_unfinished" in codes(tail.finish())


def test_suspend_or_request_complete_does_not_seed_body_terminal_history():
    assert "terminal_release_unfinished" in codes(session_release_program(source="suspend"))
    require_valid(session_release_program(source="suspend", release=False))


@pytest.mark.parametrize("table", ("session_updates", "terminal_frame_releases"))
def test_metadata_cannot_create_operation_or_omit_scope(table):
    graph = session_release_program()
    row, = getattr(graph, table)
    assert "session_release_operation" in codes(replace(graph, **{table: (replace(row, operation=OperationID("missing")),)}))
    assert codes(replace(graph, driver_lifecycles=()))


def test_typed_release_of_request_or_same_typed_produced_payload_is_not_release_of_owner():
    graph = session_release_program()
    row, = graph.terminal_frame_releases
    release = op(graph, row.operation)
    request = graph.driver_interfaces[0].receiver
    bad = replace(release, uses=tuple(replace(use, value=request) if use.id == row.owner else use for use in release.uses))
    assert "terminal_release_unfinished" in codes(change(graph, bad))
    commit, = graph.body_outcome_commits
    block = next(block for region in graph.regions for block in region.blocks if commit.operation in block.operations)
    payload = block.arguments[0]
    bad = replace(release, uses=tuple(replace(use, value=payload) if use.id == row.owner else use for use in release.uses))
    assert "terminal_release_unfinished" in codes(change(graph, bad))


@pytest.mark.parametrize("site", ("post", "release"))
def test_wrong_intrinsic_completeness_and_effect_tags_are_rejected(site):
    graph = session_release_program()
    identity = graph.session_updates[0].operation if site == "post" else graph.terminal_frame_releases[0].operation
    operation = op(graph, identity)
    expected = "session_post_shape" if site == "post" else "terminal_release_shape"
    assert expected in codes(change(graph, replace(operation, effects_complete=not operation.effects_complete)))
    assert expected in codes(change(graph, replace(operation, behaviors=(*operation.behaviors, Behavior.ORDER))))


def test_post_must_cover_read_domains_and_only_real_written_results():
    graph = session_release_program(strict_subset=True)
    row, = graph.session_updates
    operation = op(graph, row.operation)
    omitted = operation.accesses[-1]
    assert omitted.mode is AccessMode.READ
    changed = replace(operation, accesses=operation.accesses[:-1],
                      uses=tuple(use for use in operation.uses if use.id != omitted.before))
    assert "session_post_domains" in codes(change(graph, changed))
    changed = replace(operation, accesses=tuple(replace(access, mode=AccessMode.WRITE)
                                               if access.mode is AccessMode.READ_WRITE else access for access in operation.accesses))
    assert "session_post_access" in codes(change(graph, changed))


def test_release_cannot_omit_an_extra_driver_domain():
    graph = session_release_program(extra_domain=True)
    row, = graph.terminal_frame_releases
    release = op(graph, row.operation)
    omitted = release.accesses[-1]
    before = next(use.value for use in release.uses if use.id == omitted.before)
    graph = replace(graph, values=tuple(value for value in graph.values if value.id != omitted.after),
        operations=tuple(replace(operation, uses=tuple(replace(use, value=before) if use.value == omitted.after else use
                                                       for use in operation.uses)) for operation in graph.operations))
    release = op(graph, row.operation)
    release = replace(release, accesses=release.accesses[:-1],
                      uses=tuple(use for use in release.uses if use.id != omitted.before),
                      results=tuple(result for result in release.results if result != omitted.after))
    assert "terminal_release_domains" in codes(change(graph, release))


def test_old_post_state_cannot_be_reused_after_a_callback_partial_completion():
    graph = session_release_program(callback=True)
    row, = graph.terminal_frame_releases
    release = op(graph, row.operation)
    callback = op(graph, OperationID("session.callback"))
    location = release.accesses[0].location
    values = {value.id: value for value in graph.values}
    old = next(use.value for use in callback.uses
               if isinstance(values[use.value], StateVersionValue) and values[use.value].location == location)
    before = release.accesses[0].before
    changed = replace(release, uses=tuple(replace(use, value=old) if use.id == before else use for use in release.uses))
    assert "stale_state" in codes(change(graph, changed))


def test_ordinary_metadata_cannot_be_relabelled_as_a_normal_helper_post():
    graph = session_release_program()
    row, = graph.session_updates
    assert "session_post_invoke" in codes(replace(graph, session_updates=(replace(row, binding=LifecyclePostBinding.NORMAL_COMPLETION),)))


@pytest.mark.parametrize("site", ("post", "release"))
def test_existing_core_precision_is_supported_without_tag_granting_alias_proof(site):
    graph = session_release_program()
    location = graph.driver_interfaces[0].lifecycle[0]
    if site == "post":
        row, = graph.session_updates
        operation = op(graph, row.operation)
        reference_use = row.request
        reference = next(use.value for use in operation.uses if use.id == reference_use)
    else:
        row, = graph.terminal_frame_releases
        operation = op(graph, row.operation)
        reference_use = row.owner
        region = next(region for region in graph.regions if region.id == graph.driver_interfaces[0].region)
        reference = next(block for block in region.blocks if block.id == region.entry).arguments[0]
        operation = replace(operation, uses=tuple(replace(use, value=reference) if use.id == reference_use else use
                                                   for use in operation.uses))
    graph = replace(graph, values=tuple(replace(value, targets=(location,), selector=Footprint(FootprintKind.WHOLE))
                                        if value.id == reference else value for value in graph.values))
    operation = replace(operation, accesses=tuple(replace(access, reference=reference_use)
                                                  if access.location == location else access for access in operation.accesses))
    graph = change(graph, operation)
    require_valid(graph)
    if site == "post":
        graph = replace(graph, values=tuple(replace(value, targets=None) if value.id == reference else value
                                            for value in graph.values))
        assert "incomplete_alias" in codes(graph)

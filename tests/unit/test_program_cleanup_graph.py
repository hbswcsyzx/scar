"""Core C1 cleanup compositions, without claiming Python/source execution."""
from dataclasses import replace

import pytest

from scar.ir.program.cleanup_validation import CleanupRouteKind
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.model import StateAccess, Successor, Terminator, TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from scar.ir.program.cleanup import CleanupRouteTerminator
from tests.fixtures.program_cleanup_graphs import (
    cleanup_return_resume_graph, local_loop_transfers_in_cleanup_graph,
    nested_cleanup_fallthrough_and_replace_graph,
)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _replace_operation(graph, identity, transform):
    identity = identity if type(identity) is OperationID else OperationID(identity)
    return replace(graph, operations=tuple(
        transform(operation) if operation.id == identity else operation
        for operation in graph.operations))


def _operation(graph, identity):
    return next(operation for operation in graph.operations
                if operation.id == OperationID(identity))


def _remove_block_and_operations(graph, block_id):
    """Prune a mutation's now-dead target so validation reaches the C1 check."""
    block_id = block_id if type(block_id) is BlockID else BlockID(block_id)
    block = next(block for region in graph.regions for block in region.blocks
                 if block.id == block_id)
    removed_operations = set(block.operations)
    removed_values = set(block.arguments)
    for operation in graph.operations:
        if operation.id in removed_operations:
            removed_values.update(operation.results)
            removed_values.update(access.after for access in operation.accesses)
    return replace(
        graph,
        regions=tuple(replace(region, blocks=tuple(
            item for item in region.blocks if item.id != block_id)) for region in graph.regions),
        operations=tuple(operation for operation in graph.operations
                         if operation.id not in removed_operations),
        values=tuple(value for value in graph.values if value.id not in removed_values),
        cleanup_replacements=tuple(action for action in graph.cleanup_replacements
                                   if action.operation not in removed_operations),
        control_scopes=tuple(replace(scope, blocks=tuple(
            item for item in scope.blocks if item != block_id)) for scope in graph.control_scopes),
    )


def test_multistate_return_raise_resume_keeps_payload_state_and_context_distinct():
    graph = cleanup_return_resume_graph()
    require_valid(graph)
    index = ProgramIndex(graph)
    cleanup = ControlScopeID("shared.cleanup.scope")

    interface = index.cleanup_interface(cleanup)
    assert interface is not None
    assert index.cleanup_stack(BlockID("shared.cleanup")) == ()
    assert index.cleanup_stack(BlockID("shared.cleanup.post-pop-route")) == ()
    assert index.cleanup_action(OperationID("shared.cleanup.enter")) is not None
    assert index.cleanup_action(OperationID("shared.cleanup.resume")) is not None
    pending_copies = set(index.cleanup_pending_copies(cleanup))
    context_copies = set(index.cleanup_context_copies(cleanup))
    assert ValueID("shared.cleanup.pending") in pending_copies
    assert ValueID("shared.cleanup.saved-context") in context_copies
    assert ValueID("shared.cleanup.world.after") not in pending_copies
    assert ValueID("shared.cleanup.ambient.after") not in context_copies

    # Both Return and Raise leave through Enter; Resume then re-dispatches the
    # exact original pending value with post-cleanup state.
    for identity in ("shared.return.to.cleanup", "shared.raise.to.cleanup"):
        steps = index.cleanup_route_steps(OperationID(identity))
        assert len(steps) == 1
        assert steps[0].kind is CleanupRouteKind.ENTER
        assert steps[0].target == BlockID("shared.cleanup")
    route_steps = index.cleanup_route_steps(OperationID("shared.cleanup.route"))
    assert len(route_steps) == 2
    assert all(step.kind is CleanupRouteKind.FINAL_DISPATCH for step in route_steps)
    assert {step.port.value for step in route_steps} == {"shared.port.return", "shared.port.raise"}


def test_nested_fallthrough_dispatches_to_outer_resume_and_return_replaces_twice():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    require_valid(graph)
    index = ProgramIndex(graph)
    route_steps = {step.port.value: step for step in
                   index.cleanup_route_steps(OperationID("nested.inner.route"))}
    assert route_steps["nested.inner.port.fallthrough"].kind is CleanupRouteKind.FINAL_DISPATCH
    assert route_steps["nested.inner.port.fallthrough"].target == BlockID(
        "nested.inner.fallthrough-dispatch")
    assert route_steps["shared.port.return"].kind is CleanupRouteKind.REPLACE
    assert route_steps["shared.port.return"].target == BlockID("nested.outer.cleanup.replace")

    dispatch = _operation(graph, "nested.inner.fallthrough.dispatch")
    assert dispatch.terminator.successors[0].block == BlockID("nested.outer.cleanup.resume")
    assert index.cleanup_stack(BlockID("nested.inner.fallthrough-dispatch")) == (
        ControlScopeID("shared.cleanup.scope"),)
    assert index.cleanup_stack(BlockID("nested.outer.cleanup.resume")) == (
        ControlScopeID("shared.cleanup.scope"),)

    # Both replacement actions are reached by their own direct Replace route;
    # neither route re-enters a cleanup entry.
    assert index.cleanup_route_steps(OperationID("nested.inner.route"))[1].target != BlockID(
        "nested.inner.cleanup.entry")
    assert index.cleanup_action(OperationID("nested.inner.replace")) is not None
    assert index.cleanup_action(OperationID("nested.outer.replace")) is not None
    assert OperationID("nested.inner.replace") in {
        row.operation for row in graph.cleanup_replacements}
    assert OperationID("nested.outer.replace") in {
        row.operation for row in graph.cleanup_replacements}


def test_local_break_continue_dispatch_keeps_the_enclosing_cleanup_active():
    graph = local_loop_transfers_in_cleanup_graph()
    require_valid(graph)
    index = ProgramIndex(graph)
    cleanup = ControlScopeID("shared.cleanup.scope")
    loop = ControlScopeID("cleanup.loop")

    assert index.cleanup_stack(BlockID("cleanup.loop.header")) == (cleanup,)
    assert index.cleanup_stack(BlockID("cleanup.loop.dispatch")) == (cleanup,)
    assert index.control_scope(BlockID("cleanup.loop.dispatch")).id == loop
    assert index.cleanup_stack(BlockID("cleanup.loop.after")) == (cleanup,)
    steps = index.cleanup_route_steps(OperationID("shared.cleanup.route"))
    assert {step.kind for step in steps} == {CleanupRouteKind.FINAL_DISPATCH}
    assert not graph.cleanup_replacements
    assert len(graph.cleanup_resumes) == 1

    dispatch = _operation(graph, "cleanup.loop.pending-dispatch")
    targets = {edge.port.value: edge.block.value for edge in dispatch.terminator.successors}
    assert targets == {"cleanup.loop.port.break": "cleanup.loop.after",
                       "cleanup.loop.port.continue": "cleanup.loop.header"}
    assert ValueID("shared.cleanup.pending") in set(index.cleanup_pending_copies(cleanup))


@pytest.mark.parametrize("identity", [
    "shared.cleanup.resume",
])
def test_resume_must_read_and_advance_every_state_domain(identity):
    graph = cleanup_return_resume_graph()
    operation = _operation(graph, identity)
    altered = replace(operation,
        accesses=tuple(access for access in operation.accesses
                       if access.location.value != "shared.ambient-context"))
    graph = _replace_operation(graph, identity, lambda _: altered)
    assert {"cleanup_action_state", "stale_state", "unaccounted_state_result",
            "unaccounted_state_use"} & _codes(graph)


def test_nested_resume_cannot_restore_outer_context_instead_of_inner_saved_context():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    operation = _operation(graph, "nested.inner.resume")
    use_id = UseID("nested.inner.resume.context.use")
    altered = replace(operation, uses=tuple(
        replace(use, value=ValueID("nested.inner.resume.outer-context"))
        if use.id == use_id else use for use in operation.uses))
    graph = _replace_operation(graph, operation.id, lambda _: altered)
    assert "cleanup_context_forward" in _codes(graph)


def test_new_return_route_cannot_forward_outer_old_pending_as_replacement():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    operation = _operation(graph, "nested.inner.route")
    use_id = UseID("nested.inner.route.replace-return.pending")
    altered = replace(operation, uses=tuple(
        replace(use, value=ValueID("nested.inner.route.outer-pending"))
        if use.id == use_id else use for use in operation.uses))
    graph = _replace_operation(graph, operation.id, lambda _: altered)
    assert "cleanup_route_pending" in _codes(graph)


def test_protected_exit_cannot_bypass_its_cleanup_route():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    operation = _operation(graph, "nested.inner.protected.to-cleanup")
    assert isinstance(operation.terminator, CleanupRouteTerminator)
    edge = operation.terminator.successors[0]
    # Preserve the target and the exact typed actuals, but erase the C1 route
    # selection. This leaves a core-valid direct edge for the C1 guard to see.
    altered = replace(
        operation,
        uses=tuple(use for use in operation.uses if use.id != operation.terminator.pending),
        terminator=Terminator(TerminatorKind.JUMP,
                              (Successor(edge.block, edge.arguments),)),
    )
    graph = _replace_operation(graph, operation.id, lambda _: altered)
    assert {"cleanup_protected_bypass", "cleanup_entry_edge"} <= _codes(graph)


def test_inner_route_cannot_skip_the_final_c0_dispatch_only_block():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    operation = _operation(graph, "nested.inner.fallthrough.dispatch")
    edge = operation.terminator.successors[0]
    # Keep the routed target and edge arguments intact, but replace its C0
    # selector with a jump. The route now lands on a block that bypasses C0.
    altered = replace(
        operation,
        uses=tuple(use for use in operation.uses if use.id != operation.terminator.pending),
        terminator=Terminator(TerminatorKind.JUMP,
                              (Successor(edge.block, edge.arguments),)),
    )
    graph = _replace_operation(graph, operation.id, lambda _: altered)
    assert "cleanup_route_final" in _codes(graph)


def test_replace_cannot_reenter_the_cleanup_entry():
    graph = nested_cleanup_fallthrough_and_replace_graph()
    operation = _operation(graph, "nested.inner.route")
    edges = list(operation.terminator.successors)
    replacement_actuals = (
        UseID("nested.inner.route.replace-return.pending"),
        UseID("nested.inner.route.replace-return.world"),
        UseID("nested.inner.route.replace-return.ambient"),
    )
    edges[1] = replace(edges[1], block=BlockID("shared.cleanup"),
                       arguments=replacement_actuals)
    retained_uses = set(edges[0].arguments) | set(replacement_actuals) | {
        operation.terminator.pending}
    altered = replace(operation,
        uses=tuple(use for use in operation.uses if use.id in retained_uses),
        terminator=replace(operation.terminator, successors=tuple(edges)))
    graph = _replace_operation(graph, operation.id, lambda _: altered)
    # The old outer Replace target has no remaining predecessor after the
    # mutation; prune that action and its block so the graph stays core-valid.
    graph = _remove_block_and_operations(graph, "nested.outer.cleanup.replace")
    codes = _codes(graph)
    assert "cleanup_stack_merge" in codes
    assert "unreachable_block" not in codes

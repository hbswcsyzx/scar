"""Unknown INVOKE preserves state/anchors on both C1 paths; no runtime proof."""
from dataclasses import replace

import pytest

from scar.ir.program.cleanup import CleanupResume, CleanupRouteTerminator
from scar.ir.program.cleanup_validation import CleanupRouteKind
from scar.ir.program.codec import dumps, loads
from scar.ir.program.control import PendingCompletionDefinition, ProtocolValueKind as P
from scar.ir.program.ids import BlockID, ControlPortID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, ExitKind, Operation, OperationResult, ProtocolValue,
    StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate

from tests.fixtures.program_cleanup_invoke_graphs import (
    cleanup_invoke_graph, cleanup_invoke_may_diverge_graph,
)


def _operation(graph, identity):
    return next(row for row in graph.operations if row.id == OperationID(identity))


def _replace_operation(graph, operation):
    return replace(graph, operations=tuple(operation if row.id == operation.id else row
                                          for row in graph.operations))


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def test_unknown_invoke_has_two_domain_poststates_and_keeps_context_private():
    graph = cleanup_invoke_graph()
    assert validate(graph) == ()
    index = ProgramIndex(graph)
    invoke = _operation(graph, "shared.cleanup.write")
    assert invoke.terminator.kind is TerminatorKind.INVOKE
    assert not invoke.effects_complete and invoke.results == invoke.accesses == ()
    values = {value.id: value for value in graph.values}
    for signature, edge in zip(invoke.completions, invoke.terminator.successors):
        produced_states = {item.location for item in signature.types if item.kind.value == "STATE"}
        assert produced_states == {location.id for location in graph.locations}
        assert all(getattr(item, "protocol", None) is not P.SAVED_HANDLED_CONTEXT
                   for item in signature.types)
        # CompletionResult indices are not assumed equal to target positions.
        slots = [(position, actual.index) for position, actual in enumerate(edge.arguments)
                 if isinstance(actual, CompletionResult)]
        assert slots == ([(1, 0), (3, 1)] if edge.kind is ExitKind.NORMAL else [(0, 0), (2, 1), (4, 2)])
    assert all(isinstance(values[next(use.value for use in invoke.uses if use.id == actual)],
                          StateVersionValue) for actual in invoke.invoke_arguments)
    cleanup = graph.cleanup_interfaces[0].scope
    assert index.cleanup_stack(BlockID("invoke.cleanup.normal")) == (cleanup,)
    assert index.cleanup_stack(BlockID("invoke.cleanup.failed")) == (cleanup,)
    assert index.cleanup_stack(BlockID("invoke.cleanup.replace")) == (cleanup,)
    assert ValueID("invoke.normal.pending") in index.cleanup_pending_copies(cleanup)
    assert ValueID("invoke.failed.saved-pending") in index.cleanup_pending_copies(cleanup)
    assert ValueID("invoke.replace.saved-pending") in index.cleanup_pending_copies(cleanup)
    assert ValueID("invoke.normal.context") in index.cleanup_context_copies(cleanup)
    assert ValueID("invoke.failed.context") in index.cleanup_context_copies(cleanup)
    steps = index.cleanup_route_steps(OperationID("invoke.failed.route"))
    assert len(steps) == 1 and steps[0].kind is CleanupRouteKind.REPLACE
    assert steps[0].cleanup == cleanup and steps[0].target == BlockID("invoke.cleanup.replace")
    assert index.cleanup_stack(BlockID("shared.cleanup.post-pop-route")) == ()


def test_invoke_normal_and_raise_paths_roundtrip_with_distinct_route_variants():
    graph = cleanup_invoke_graph()
    restored = loads(dumps(graph))
    assert restored == graph
    index = ProgramIndex(restored)
    assert isinstance(_operation(restored, "invoke.failed.route").terminator, CleanupRouteTerminator)
    assert _operation(restored, "shared.dispatch").terminator.kind is TerminatorKind.PENDING_DISPATCH
    normal = index.cleanup_action(OperationID("shared.cleanup.resume"))
    replace_action = index.cleanup_action(OperationID("invoke.cleanup.replace-action"))
    assert type(normal) is CleanupResume
    assert type(replace_action).__name__ == "CleanupReplace"
    assert index.cleanup_route_steps(OperationID("shared.cleanup.route"))[0].kind is CleanupRouteKind.FINAL_DISPATCH


@pytest.mark.parametrize("operation_id,use_id", [
    ("shared.cleanup.resume", "shared.cleanup.resume.world"),
    ("invoke.cleanup.replace-action", "invoke.replace.world.use"),
])
def test_restore_cannot_roll_back_to_preinvoke_state(operation_id, use_id):
    graph = cleanup_invoke_graph()
    action = _operation(graph, operation_id)
    action = replace(action, uses=tuple(replace(use, value=ValueID("shared.cleanup.enter.world.after"))
        if use.id == UseID(use_id) else use for use in action.uses))
    assert "stale_state" in _codes(_replace_operation(graph, action))


@pytest.mark.parametrize("kind", [ExitKind.NORMAL, ExitKind.RAISE])
def test_unknown_completion_cannot_forward_old_ambient_instead_of_producing_it(kind):
    graph = cleanup_invoke_graph()
    invoke = _operation(graph, "shared.cleanup.write")
    forged = Use(UseID("invoke.forged-old-ambient." + kind.value),
                 ValueID("shared.cleanup.enter.ambient.after"), UseRole.STATE_CONTENT)
    signatures = tuple(replace(signature, types=signature.types[:-1]) if signature.kind is kind else signature
                       for signature in invoke.completions)
    edges = tuple(replace(edge, arguments=(*edge.arguments[:-1], forged.id)) if edge.kind is kind else edge
                  for edge in invoke.terminator.successors)
    invoke = replace(invoke, uses=(*invoke.uses, forged), completions=signatures,
                     terminator=replace(invoke.terminator, successors=edges))
    # Arity/types/produced-slot uniqueness remain consistent; the missing fresh
    # state must be rejected because this unknown completion affects all domains.
    assert "completion_unknown_state" in _codes(_replace_operation(graph, invoke))


def test_new_raise_cannot_be_silently_discarded_by_resuming_old_pending():
    graph = cleanup_invoke_graph()
    action, = graph.cleanup_replacements
    operation = _operation(graph, action.operation.value)
    operation = replace(operation, uses=tuple(use for use in operation.uses
                                             if use.id != action.replacement))
    graph = _replace_operation(graph, operation)
    old_value = next(use.value for use in operation.uses if use.id == action.saved_pending)
    jump = _operation(graph, action.continuation.operation.value)
    jump = replace(jump, uses=tuple(replace(use, value=old_value) if use.role is UseRole.PROTOCOL else use
                                   for use in jump.uses))
    graph = _replace_operation(graph, jump)
    resume = CleanupResume(action.operation, action.cleanup, action.saved_pending,
                           action.context, action.continuation)
    graph = replace(graph, cleanup_replacements=(), cleanup_resumes=(*graph.cleanup_resumes, resume))
    assert "cleanup_route_next" in _codes(graph)


def test_external_constructor_cannot_masquerade_as_this_activation_fresh_raise():
    graph = cleanup_invoke_graph()
    region = graph.regions[0]
    pack_id = OperationID("invoke.external.pending.pack")
    payload = Use(UseID("invoke.external.payload"), ValueID("shared.return.input"), UseRole.REFERENCE)
    old = ProtocolValue(ValueID("invoke.external.pending"), region.id,
                         OperationResult(pack_id, 0), P.PENDING_COMPLETION)
    operation = Operation(pack_id, "pending constructed before cleanup activation",
        (Behavior.CONTROL,), (payload,), (old.id,), effects_complete=True)
    definition = PendingCompletionDefinition(old.id, ControlPortID("shared.port.return"), payload.id)
    blocks = tuple(replace(block, operations=(pack_id, *block.operations)) if block.id == region.entry else block
                   for block in region.blocks)
    graph = replace(graph, regions=(replace(region, blocks=blocks),),
        operations=(*graph.operations, operation), values=(*graph.values, old),
        pending_completions=(*graph.pending_completions, definition))
    route = _operation(graph, "invoke.failed.route")
    route = replace(route, uses=tuple(replace(use, value=old.id)
        if use.value == ValueID("invoke.failed.new-pending") else use for use in route.uses),
        terminator=replace(route.terminator, successors=(replace(
            route.terminator.successors[0], port=definition.port),)))
    assert "cleanup_replacement_fresh" in _codes(_replace_operation(graph, route))


def test_exception_path_cannot_skip_replace_and_jump_to_postpop_corridor():
    graph = cleanup_invoke_graph()
    route = _operation(graph, "invoke.failed.route")
    kept = {UseID("invoke.failed.route.selector"), UseID("invoke.failed.route.new"),
            UseID("invoke.failed.route.world"), UseID("invoke.failed.route.ambient")}
    edge = replace(route.terminator.successors[0], block=BlockID("shared.cleanup.post-pop-route"),
                   arguments=(UseID("invoke.failed.route.new"), UseID("invoke.failed.route.world"),
                              UseID("invoke.failed.route.ambient")))
    route = replace(route, uses=tuple(use for use in route.uses if use.id in kept),
                    terminator=replace(route.terminator, successors=(edge,)))
    # The now-bypassed Replace block still has a predecessor-free fixture row;
    # delete it and its records so rejection measures the bypass, not dead CFG.
    removed = BlockID("invoke.cleanup.replace")
    removed_ops = {OperationID("invoke.cleanup.replace-action"), OperationID("invoke.replace.to-route")}
    removed_values = {value.id for value in graph.values if (
        getattr(value.origin, "block", None) == removed
        or getattr(value.origin, "operation", None) in removed_ops)}
    region = graph.regions[0]
    graph = replace(graph, regions=(replace(region, blocks=tuple(block for block in region.blocks
                                                               if block.id != removed)),),
        operations=tuple(row for row in graph.operations if row.id not in removed_ops),
        values=tuple(row for row in graph.values if row.id not in removed_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks if block != removed))
                             for scope in graph.control_scopes), cleanup_replacements=())
    assert _codes(_replace_operation(graph, route)) & {"cleanup_stack_entry", "cleanup_stack_merge"}


def test_cleanup_loop_can_diverge_without_popping_and_still_has_finite_exits():
    graph = cleanup_invoke_may_diverge_graph()
    assert validate(graph) == ()
    index = ProgramIndex(graph)
    scope = graph.cleanup_interfaces[0].scope
    header = BlockID("invoke.cleanup.loop")
    branch = _operation(graph, "invoke.loop.branch")
    assert branch.terminator.kind is TerminatorKind.BRANCH
    assert tuple(edge.block for edge in branch.terminator.successors) == (header, BlockID("invoke.cleanup.call"))
    assert index.cleanup_stack(header) == index.cleanup_stack(BlockID("invoke.cleanup.call")) == (scope,)
    assert ValueID("invoke.loop.pending") in index.cleanup_pending_copies(scope)
    assert ValueID("invoke.loop.context") in index.cleanup_context_copies(scope)
    assert ValueID("invoke.call.pending") in index.cleanup_pending_copies(scope)
    assert ValueID("invoke.call.context") in index.cleanup_context_copies(scope)
    assert loads(dumps(graph)) == graph
    assert graph.cleanup_interfaces[0].rules.termination.value == "MAY_NOT_COMPLETE"
    assert not hasattr(graph.cleanup_interfaces[0], "total")

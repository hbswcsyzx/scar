"""Small read-only IR mutations against the C1 integration; no target execution."""
from dataclasses import replace
import json

from scar.ir.program import (
    Behavior, Block, BlockArgument, BlockID, Operation, OperationID, OperationResult,
    StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseID, UseRole, ValueID,
)
from scar.ir.program.cleanup import CleanupReplace
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_cleanup_graphs import (
    local_loop_transfers_in_cleanup_graph,
    nested_cleanup_fallthrough_and_replace_graph, resume_multistate_graph,
)


def edit_operation(graph, identity, change):
    return replace(graph, operations=tuple(change(op) if op.id == OperationID(identity) else op
                                            for op in graph.operations))


def context_escape(graph):
    return edit_operation(graph, "shared.cleanup.write", lambda op: replace(op, uses=(*op.uses,
        Use(UseID("review.escape.context"), ValueID("shared.cleanup.saved-context"), UseRole.PROTOCOL))))


def stale_resume_state(graph):
    return edit_operation(graph, "shared.cleanup.resume", lambda op: replace(op, uses=tuple(
        replace(use, value=ValueID("shared.cleanup.enter.world.after"))
        if use.id == UseID("shared.cleanup.resume.world") else use for use in op.uses)))


def leave_without_pop(graph):
    action = graph.cleanup_resumes[0]
    protocol_uses = {action.pending, action.context}
    graph = edit_operation(graph, action.operation.value, lambda op: replace(op, uses=tuple(
        use for use in op.uses if use.id not in protocol_uses)))
    return replace(graph, cleanup_resumes=())


def bypass_route(graph):
    def change(op):
        term = op.terminator
        edge = term.successors[0]
        return replace(op, uses=tuple(use for use in op.uses if use.id != term.pending),
                       terminator=Terminator(TerminatorKind.JUMP, (Successor(edge.block, edge.arguments),)))
    return edit_operation(graph, "shared.return.to.cleanup", change)


def replace_old_pending(graph):
    """Split a legitimate exit block, then Replace using its saved old token."""
    action = graph.cleanup_resumes[0]
    region = graph.regions[0]
    cleanup_block = next(block for block in region.blocks if action.operation in block.operations)
    old_action = next(op for op in graph.operations if op.id == action.operation)
    action_block = BlockID("review.replace-old")
    state_inputs = {access.before for access in old_action.accesses}
    values, updated_uses, jump_uses = [], [], []
    for use in old_action.uses:
        if use.id not in state_inputs:
            updated_uses.append(use)
            continue
        previous = next(value for value in graph.values if value.id == use.value)
        formal = StateVersionValue(ValueID("review.state." + str(len(values))), graph.root,
                                   BlockArgument(action_block, len(values)), previous.location)
        values.append(formal)
        updated_uses.append(replace(use, value=formal.id))
        jump_uses.append(Use(UseID("review.into-replace." + str(len(values))), use.value, UseRole.STATE_CONTENT))
    old = next(use.value for use in old_action.uses if use.id == action.pending)
    replacement = Use(UseID("review.old.replacement"), old, UseRole.PROTOCOL)
    updated_action = replace(old_action, uses=(*updated_uses, replacement))
    jump = Operation(OperationID("review.into-replace"), "handoff to old-token Replace",
                     (Behavior.CONTROL,), tuple(jump_uses), terminator=Terminator(TerminatorKind.JUMP,
                         (Successor(action_block, tuple(use.id for use in jump_uses)),)))
    before = replace(cleanup_block, operations=(*cleanup_block.operations[:-2], jump.id))
    after = Block(action_block, tuple(value.id for value in values), cleanup_block.operations[-2:])
    region = replace(region, blocks=tuple(before if block.id == before.id else block for block in region.blocks) + (after,))
    return replace(graph, regions=(region,), values=(*graph.values, *values),
        operations=tuple(updated_action if op.id == action.operation else op for op in graph.operations) + (jump,),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, action_block))
                             if scope.id == action.cleanup else scope for scope in graph.control_scopes),
        cleanup_resumes=(), cleanup_replacements=(CleanupReplace(action.operation, action.cleanup,
            action.pending, replacement.id, action.context, action.continuation),))


def fully_diverging_cleanup(graph):
    """Keep Return/Raise saved, then enter a cleanup-local endless CFG loop."""
    region = graph.regions[0]
    interface = graph.cleanup_interfaces[0]
    entry = next(block for block in region.blocks if block.id == interface.entry)
    loop_id = BlockID("review.diverging-loop")
    cleanup = next(scope for scope in graph.control_scopes if scope.id == interface.scope)
    remove_blocks = {block.id for block in region.blocks if block.id.value in (
        "shared.cleanup.post-pop-route", "shared.dispatch.block", "shared.return_exit", "shared.raise_exit")}
    preserved_ops = {op for block in region.blocks if block.id not in remove_blocks
                     for op in (block.operations[:3] if block.id == entry.id else block.operations)}
    operations = [op for op in graph.operations if op.id in preserved_ops]
    values = [value for value in graph.values if
        not (isinstance(value.origin, BlockArgument) and value.origin.block in remove_blocks)
        and not (isinstance(value.origin, OperationResult) and value.origin.operation not in preserved_ops)]
    formals, into_uses, self_uses = [], [], []
    for index, actual_name in enumerate(("shared.cleanup.world.after", "shared.cleanup.ambient.after")):
        actual = next(value for value in graph.values if value.id == ValueID(actual_name))
        formal = StateVersionValue(ValueID("review.loop.state." + str(index)), graph.root,
                                   BlockArgument(loop_id, index), actual.location)
        formals.append(formal)
        into_uses.append(Use(UseID("review.into-loop." + str(index)), actual.id, UseRole.STATE_CONTENT))
        self_uses.append(Use(UseID("review.loop-back." + str(index)), formal.id, UseRole.STATE_CONTENT))
    for name, carried in (("review.into-loop", into_uses), ("review.loop-back", self_uses)):
        operations.append(Operation(OperationID(name), "cleanup diverges", (Behavior.CONTROL,), tuple(carried),
            terminator=Terminator(TerminatorKind.JUMP, (Successor(loop_id, tuple(use.id for use in carried)),))))
    blocks = tuple(replace(block, operations=(*entry.operations[:3], OperationID("review.into-loop")))
                   if block.id == entry.id else block for block in region.blocks if block.id not in remove_blocks)
    blocks += (Block(loop_id, tuple(value.id for value in formals), (OperationID("review.loop-back"),)),)
    return replace(graph, regions=(replace(region, blocks=blocks),), operations=tuple(operations),
        values=(*values, *formals), cleanup_resumes=(),
        control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks if block not in remove_blocks)
                                    + ((loop_id,) if scope.id == cleanup.id else ()))
                             for scope in graph.control_scopes))


def main():
    graph = resume_multistate_graph()
    nested = nested_cleanup_fallthrough_and_replace_graph()
    wrong_inner_context = edit_operation(nested, "nested.inner.resume", lambda op: replace(op, uses=tuple(
        replace(use, value=ValueID("nested.inner.resume.outer-context"))
        if use.id == UseID("nested.inner.resume.context.use") else use for use in op.uses)))
    wrong_outer_original = edit_operation(nested, "nested.outer.replace", lambda op: replace(op, uses=tuple(
        replace(use, value=ValueID("nested.outer.replace.new-pending"))
        if use.id == UseID("nested.outer.replace.saved.use") else use for use in op.uses)))
    wrong_route_actual = edit_operation(nested, "nested.inner.route", lambda op: replace(op, uses=tuple(
        replace(use, value=ValueID("nested.inner.route.outer-pending"))
        if use.id == UseID("nested.inner.route.replace-return.pending") else use for use in op.uses)))
    rows = []
    for name, candidate, expected in (
        ("baseline", graph, set()),
        ("context-ordinary-operation-escape", context_escape(graph), {"cleanup_context_escape"}),
        ("resume-stale-state", stale_resume_state(graph), {"stale_state"}),
        ("protected-entry-without-route", bypass_route(graph), {"cleanup_protected_bypass", "cleanup_entry_edge"}),
        ("replace-saved-old-pending", replace_old_pending(graph), {"cleanup_replacement_fresh"}),
        ("leave-active-cleanup-without-pop", leave_without_pop(graph), {"cleanup_stack_entry"}),
        ("nested-fallthrough-and-return", nested, set()),
        ("nested-restore-outer-context-as-inner", wrong_inner_context, {"cleanup_context_forward"}),
        ("nested-consume-new-pending-as-outer-original", wrong_outer_original, {"cleanup_pending_forward"}),
        ("nested-route-substitute-outer-old-pending", wrong_route_actual, {"cleanup_route_pending"}),
        ("local-break-continue-preserve-outer-pending", local_loop_transfers_in_cleanup_graph(), set()),
    ):
        issues = validate(candidate)
        codes = {issue.code for issue in issues}
        passed = expected <= codes if expected else not codes
        rows.append({"name": name, "pass": passed, "issues": [
            {"code": issue.code, "path": issue.path, "message": issue.message} for issue in issues]})
    index = ProgramIndex(graph)
    interface = graph.cleanup_interfaces[0]
    query = (index.cleanup_stack(interface.entry) == ()
             and interface.pending_argument in index.cleanup_pending_copies(interface.scope)
             and graph.cleanup_enters[0].saved_context in index.cleanup_context_copies(interface.scope)
             and bool(index.cleanup_route_steps(OperationID("shared.return.to.cleanup"))))
    rows.append({"name": "canonical-query-index", "pass": query})
    nested_steps = ProgramIndex(nested).cleanup_route_steps(OperationID("nested.inner.route"))
    nested_query = ({step.kind.value for step in nested_steps} == {"FINAL_DISPATCH", "REPLACE"}
                    and all(step.cleanup == graph.cleanup_interfaces[0].scope
                            for step in nested_steps if step.kind.value == "REPLACE"))
    rows.append({"name": "nested-query-route-steps", "pass": nested_query})
    print(json.dumps({"scope": "IR-only integration mutations, not runtime/source proof", "results": rows},
                     ensure_ascii=False, indent=2))
    assert all(row["pass"] for row in rows)


if __name__ == "__main__":
    main()

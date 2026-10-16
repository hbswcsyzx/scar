"""Potential language exits remain declared when cleanup never completes.

These are static IR compositions; neither the self-loop nor the pending target
declares a runtime termination result or manufactures an executed exit UseSite.
"""
from dataclasses import replace
import json

import pytest

from scar.ir.program import (
    Behavior, Block, BlockArgument, BlockID, ControlPort, ControlPortID,
    ControlScopeKind, ExitKind, LanguageCompletionKind, Operation, OperationID, OperationResult,
    PendingCompletionDefinition, ProtocolValue, ProtocolValueKind,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseID,
    UseRole, ValueID, dumps, loads,
)
from scar.ir.program.control_validation import derive_pending_facts
from scar.ir.program.native import ExitPortRef
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_cleanup_graphs import resume_multistate_graph
from tests.fixtures.program_control_graphs import shared_pending_graph


def _fully_diverging_cleanup():
    """The independent review reproducer, using only real canonical records."""
    graph = resume_multistate_graph()
    region = graph.regions[0]
    interface = graph.cleanup_interfaces[0]
    entry = next(block for block in region.blocks if block.id == interface.entry)
    loop_id = BlockID("review.diverging-loop")
    remove_blocks = {BlockID(name) for name in (
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
                                    + ((loop_id,) if scope.id == interface.scope else ()))
                             for scope in graph.control_scopes))


def _with_ghost_target(graph, *, support):
    """A ghost exit is idle, packed-but-unused, or only an extra entry argument."""
    region = graph.regions[0]
    normal = next(port for port in region.exits if port.kind is ExitKind.NORMAL)
    region = replace(region, exits=(*region.exits, replace(normal, name="ghost")))
    graph = replace(graph, regions=(region,))
    if support == "none":
        return graph
    function = next(scope for scope in graph.control_scopes if scope.kind is ControlScopeKind.FUNCTION)
    ghost_port = ControlPort(ControlPortID("review.ghost.port"), function.id,
                             LanguageCompletionKind.RETURN, exit="ghost")
    operation_id = OperationID("review.ghost.pack")
    pending = ProtocolValue(ValueID("review.ghost.pending"), graph.root,
                            OperationResult(operation_id, 0), ProtocolValueKind.PENDING_COMPLETION)
    payload = Use(UseID("review.ghost.payload"), ValueID("shared.return.input"), UseRole.REFERENCE)
    pack = Operation(operation_id, "unused pending Return", (Behavior.CONTROL,), (payload,),
                     (pending.id,), effects_complete=True)
    entry = next(block for block in region.blocks if block.id == region.entry)
    blocks = tuple(replace(block, operations=(pack.id, *block.operations))
                   if block.id == entry.id else block for block in region.blocks)
    graph = replace(graph, regions=(replace(region, blocks=blocks),), values=(*graph.values, pending),
        operations=(*graph.operations, pack), control_ports=(*graph.control_ports, ghost_port),
        pending_completions=(*graph.pending_completions,
                             PendingCompletionDefinition(pending.id, ghost_port.id, payload.id)))
    if support == "unused-pack":
        return graph
    interface = graph.cleanup_interfaces[0]
    cleanup_entry = next(block for block in blocks if block.id == interface.entry)
    extra = ProtocolValue(ValueID("review.ghost.extra"), graph.root,
        BlockArgument(cleanup_entry.id, len(cleanup_entry.arguments)), ProtocolValueKind.PENDING_COMPLETION)
    operations = []
    for operation in graph.operations:
        term = operation.terminator
        if term is None or not any(edge.block == cleanup_entry.id for edge in term.successors):
            operations.append(operation)
            continue
        carried = Use(UseID(operation.id.value + ".ghost.extra"), pending.id, UseRole.PROTOCOL)
        edges = tuple(replace(edge, arguments=(*edge.arguments, carried.id))
                      if edge.block == cleanup_entry.id else edge for edge in term.successors)
        operations.append(replace(operation, uses=(*operation.uses, carried),
                                  terminator=replace(term, successors=edges)))
    blocks = tuple(replace(block, arguments=(*block.arguments, extra.id))
                   if block.id == cleanup_entry.id else block for block in graph.regions[0].blocks)
    return replace(graph, regions=(replace(graph.regions[0], blocks=blocks),),
                   values=(*graph.values, extra), operations=tuple(operations))


def test_captured_return_and_raise_targets_allow_fully_diverging_cleanup_and_v9_roundtrip():
    graph = _fully_diverging_cleanup()
    assert validate(graph) == ()
    assert not graph.cleanup_resumes and not graph.cleanup_replacements
    assert all(operation.terminator is None or operation.terminator.exit is None
               for operation in graph.operations)
    wire = dumps(graph)
    assert json.loads(wire)["schema_version"] == 9
    assert loads(wire) == graph
    assert dumps(loads(wire)) == wire


def test_potential_exits_without_execution_sites_have_empty_canonical_use_queries():
    graph = _fully_diverging_cleanup()
    index = ProgramIndex(graph)
    entry = graph.cleanup_interfaces[0].pending_argument
    captured = index.pending_facts(entry)
    assert captured.complete and len(captured.ports) == 2
    for port in graph.regions[0].exits:
        for position in range(len(port.types)):
            assert index.exit_port_uses(ExitPortRef(graph.root, port.name, position)) == ()


def test_legacy_c0_cleanup_scope_does_not_relax_unbound_exit():
    graph = shared_pending_graph()
    assert any(scope.kind is ControlScopeKind.CLEANUP for scope in graph.control_scopes)
    assert not graph.handled_context_domains
    region = graph.regions[0]
    normal = next(port for port in region.exits if port.kind is ExitKind.NORMAL)
    graph = replace(graph, regions=(replace(region, exits=(*region.exits, replace(normal, name="ghost"))),))
    assert {issue.code for issue in validate(graph)} == {"unbound_exit"}


@pytest.mark.parametrize("support", ["none", "unused-pack", "extra-argument"])
def test_c1_idle_exit_and_uncaptured_pending_do_not_support_a_ghost_target(support):
    graph = _with_ghost_target(_fully_diverging_cleanup(), support=support)
    if support != "none":
        facts = derive_pending_facts(graph)
        selected = graph.cleanup_interfaces[0].pending_argument
        assert ControlPortID("review.ghost.port") not in facts[selected].ports
        if support == "extra-argument":
            assert ControlPortID("review.ghost.port") in facts[ValueID("review.ghost.extra")].ports
    assert {issue.code for issue in validate(graph)} == {"unbound_exit"}

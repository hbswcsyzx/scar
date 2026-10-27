"""A local pending value can survive a known call without becoming its input."""
from dataclasses import replace

import pytest

from scar.ir.program import (
    Behavior, BlockArgument, ControlPort, ControlPortID, ControlScope, ControlScopeID,
    ControlScopeKind, LanguageCompletionKind, Operation, OperationID, OperationResult,
    PendingCompletionDefinition, ProtocolValue, ProtocolValueKind, Use, UseID,
    UseRole, ValueID, dumps, loads,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.unit.test_program_completions_adversarial import _invoke_graph, _with_callee
from tests.unit.test_program_control_records import source


def local_pending_across_invoke(known):
    graph = _with_callee() if known else _invoke_graph()
    region = next(r for r in graph.regions if r.id == graph.root)
    entry = next(b for b in region.blocks if b.id == region.entry)
    invoke = next(o for o in graph.operations if o.id == OperationID("main.invoke"))
    pack_id, pending_id = OperationID("main.pack.return"), ValueID("main.pending")
    pack = Operation(pack_id, "pack pending return", (Behavior.CONTROL,),
                     (Use(UseID("main.pack.payload"), ValueID("main.input"), UseRole.REFERENCE),),
                     (pending_id,), effects_complete=True)
    pending = ProtocolValue(pending_id, graph.root, OperationResult(pack_id, 0),
                            ProtocolValueKind.PENDING_COMPLETION)
    uses, edges, extra_values, blocks = list(invoke.uses), [], [], []
    for edge in invoke.terminator.successors:
        target = next(b for b in region.blocks if b.id == edge.block)
        kept = Use(UseID("keep." + edge.kind.value), pending_id, UseRole.PROTOCOL)
        argument_id = ValueID("kept." + edge.kind.value)
        uses.append(kept)
        edges.append(replace(edge, arguments=(*edge.arguments, kept.id)))
        extra_values.append(ProtocolValue(argument_id, graph.root,
            BlockArgument(target.id, len(target.arguments)), ProtocolValueKind.PENDING_COMPLETION))
        blocks.append(replace(target, arguments=(*target.arguments, argument_id)))
    new_entry = replace(entry, operations=(pack_id, *entry.operations))
    region = replace(region, blocks=(new_entry, *blocks))
    scope_id, port_id = ControlScopeID("main.function"), ControlPortID("main.return")
    scope = ControlScope(scope_id, graph.root, None, ControlScopeKind.FUNCTION,
                         source(), tuple(b.id for b in region.blocks))
    port = ControlPort(port_id, scope_id, LanguageCompletionKind.RETURN, exit="normal")
    graph = replace(graph, regions=tuple(region if r.id == graph.root else r for r in graph.regions),
        operations=(pack, *(replace(o, uses=tuple(uses), terminator=replace(o.terminator, successors=tuple(edges)))
                             if o.id == invoke.id else o for o in graph.operations)),
        values=(*graph.values, pending, *extra_values), control_scopes=(scope,), control_ports=(port,),
        pending_completions=(PendingCompletionDefinition(pending_id, port_id, pack.uses[0].id),))
    return graph


@pytest.mark.parametrize("known", [False, True])
def test_forwarding_pending_on_completion_edges_does_not_pass_it_to_callee(known):
    graph = local_pending_across_invoke(known)
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    index = ProgramIndex(graph)
    invoke = index.operations[OperationID("main.invoke")]
    assert not any(u.id in invoke.invoke_arguments for u in invoke.uses if u.role is UseRole.PROTOCOL)
    for value in graph.values:
        if isinstance(value, ProtocolValue):
            assert index.pending_facts(value.id).ports == (ControlPortID("main.return"),)


def test_passing_pending_into_an_opaque_callee_requires_a_future_boundary_contract():
    graph = local_pending_across_invoke(False)
    actual = Use(UseID("main.forbidden.actual"), ValueID("main.pending"), UseRole.PROTOCOL)
    graph = replace(graph, operations=tuple(
        replace(o, uses=(*o.uses, actual), invoke_arguments=(*o.invoke_arguments, actual.id))
        if o.id == OperationID("main.invoke") else o for o in graph.operations))
    assert "pending_escape" in {i.code for i in validate(graph)}
    with pytest.raises(ValueError, match="pending_escape"):
        dumps(graph)

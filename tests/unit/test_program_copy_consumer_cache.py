"""Incomplete copy-flow cache hits retain their query-local proof limits."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.copy_consumers import consumer_graph
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, ExitKind, ExitPort, Operation, OperationResult,
    ReferenceValue, Region, StateVersionValue, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import recursive_return_program


def _recursive_result_consumer():
    """Read an unresolved recursive result through another genuine CALL.

    The original recursive helper retains its real base and recursive exits.
    A separate identity helper consumes the recursive result, so its actual
    membership must remain unknown when recursive result copies are omitted.
    """
    graph, original = recursive_return_program()
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    caller, recursive = (operations[identity] for identity in original["calls"])
    body = next(region for region in graph.regions if region.id == recursive.callee)
    old_terminal = operations[original["terminals"][1]]
    old_reference, old_state = (values[identity] for identity in recursive.results)

    helper_id = RegionID("cache.forward.helper")
    entry_id = BlockID("cache.forward.helper.entry")
    call_id = OperationID("cache.forward.call")
    terminal_id = OperationID("cache.forward.return")
    forwarded_reference = ReferenceValue(ValueID("cache.forward.result"), body.id,
                                          OperationResult(call_id, 0))
    forwarded_state = StateVersionValue(ValueID("cache.forward.state"), body.id,
        OperationResult(call_id, 1), old_state.location)
    call_uses = (
        Use(UseID("cache.forward.call.ref"), old_reference.id, UseRole.REFERENCE),
        Use(UseID("cache.forward.call.state"), old_state.id, UseRole.STATE_CONTENT),
    )
    call = Operation(call_id, "consume the original recursive outputs",
        (Behavior.CONTROL,), call_uses,
        (forwarded_reference.id, forwarded_state.id), callee=helper_id,
        call_arguments=tuple(use.id for use in call_uses), effects_complete=True)

    formal_reference = ReferenceValue(ValueID("cache.forward.input"), helper_id,
                                     BlockArgument(entry_id, 0))
    formal_state = StateVersionValue(ValueID("cache.forward.before"), helper_id,
        BlockArgument(entry_id, 1), old_state.location)
    terminal_uses = (
        Use(UseID("cache.forward.return.ref"), formal_reference.id, UseRole.REFERENCE),
        Use(UseID("cache.forward.return.state"), formal_state.id, UseRole.STATE_CONTENT),
    )
    terminal = Operation(terminal_id, "return the exact original helper inputs",
        (Behavior.CONTROL,), terminal_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in terminal_uses)))
    helper = Region(helper_id, "identity continuation after recursive output", entry_id,
        (Block(entry_id, (formal_reference.id, formal_state.id), (terminal.id,)),),
        (ExitPort("normal", ExitKind.NORMAL, (
            ValueType(ValueKind.REFERENCE),
            ValueType(ValueKind.STATE, location=old_state.location),
        )),), parent=body.id)

    replacements = {old_reference.id: forwarded_reference.id,
                    old_state.id: forwarded_state.id}
    updated_terminal = replace(old_terminal, uses=tuple(
        replace(use, value=replacements.get(use.value, use.value))
        for use in old_terminal.uses))
    updated_body = replace(body, blocks=tuple(
        replace(block, operations=tuple(
            identity for original_id in block.operations
            for identity in ((call.id, original_id) if original_id == old_terminal.id
                             else (original_id,))))
        for block in body.blocks))
    graph = replace(graph,
        regions=tuple(updated_body if region.id == body.id else region
                      for region in graph.regions) + (helper,),
        operations=tuple(updated_terminal if operation.id == old_terminal.id else operation
                         for operation in graph.operations) + (call, terminal),
        values=graph.values + (forwarded_reference, forwarded_state,
                               formal_reference, formal_state))
    return graph, {"caller": caller, "body": updated_body,
                   "recursive": recursive, "consumer": call}


@pytest.mark.parametrize("role,source_ordinal,consumer_ordinal", (
    ("reference", 0, 0),
    ("state", 2, 1),
))
def test_warmed_child_flow_keeps_missing_recursive_result_membership_unknown(
        role, source_ordinal, consumer_ordinal):
    graph, details = _recursive_result_consumer()
    require_valid(graph)
    index = ProgramIndex(graph)
    budget = ValidityBudget(1000000)
    context = ConnectionContext(graph, index=index, budget=budget)
    caller, body = details["caller"], details["body"]
    body_entry = next(block for block in body.blocks if block.id == body.entry)
    caller_use = context.owned_use(caller.id, caller.call_arguments[source_ordinal])
    root_source = context.values[caller_use.value].origin
    child_source = context.values[body_entry.arguments[source_ordinal]].origin
    assert type(root_source) is type(child_source) is BlockArgument
    assert root_source != child_source
    assert (isinstance(context.values[caller_use.value], StateVersionValue)
            is (role == "state"))

    warmed = consumer_graph(context, root_source)
    assert warmed["inventory"]["known_inventory_complete"] is False
    assert warmed["inventory"]["proofs_complete"] is False
    assert any(frame["key"] == (caller.id,) for frame in warmed["frames"])
    assert not budget.truncated

    report = consumer_graph(context, child_source)

    root, = tuple(frame for frame in report["frames"] if frame["key"] == ())
    assert root["region"] == body.id
    recursive, = tuple(row for row in root["calls"]
                       if row["operation"] == details["recursive"].id)
    # Known pre-call inputs survive incomplete recursive output bounds.
    assert recursive["arguments"][source_ordinal]["may"] is True
    assert recursive["arguments"][source_ordinal]["must"] is True
    consumer, = tuple(row for row in root["calls"]
                      if row["operation"] == details["consumer"].id)
    missing = consumer["arguments"][consumer_ordinal]
    assert missing["may"] is None
    assert missing["must"] is None
    assert missing["binding"]["match"] is None
    assert consumer["status"] != "NOT_APPLICABLE"
    assert "copy_consumer_partial_bounds" in root["gaps"]
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["inventory"]["proofs_complete"] is False
    assert report["inventory"]["frames_total"] is None
    assert report["inventory"]["consumers_total"] is None
    assert not budget.truncated
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False

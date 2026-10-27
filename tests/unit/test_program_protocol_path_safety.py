"""Bounded path and output-port safety for static protocol adapters."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import BlockID, OperationID, ValueID, UseID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, LiteralOrigin,
    Operation, ProtocolValue, ReferenceValue, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.protocol_validation import adapter_host_output, no_entry_route, no_entry_seeds
from scar.ir.program.protocols import HostTerminal, ProtocolClause
from scar.ir.program.validation import validate
from tests.fixtures.program_protocol_graphs import generator_protocol_program, no_entry_throw_program


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _adapter_row(graph, slot):
    return next(row for row in graph.protocol_operations
                if row.clause is ProtocolClause.HOST_ADAPTER and row.slot == slot)


def _replace_row(graph, old, new):
    return replace(graph, protocol_operations=tuple(new if row == old else row
                                                   for row in graph.protocol_operations))


def _role(value):
    if isinstance(value, StateVersionValue):
        return UseRole.STATE_CONTENT
    if isinstance(value, ProtocolValue):
        return UseRole.PROTOCOL
    if isinstance(value, DataValue):
        return UseRole.DATA
    return UseRole.REFERENCE


def _clone_argument(value, block, position, prefix):
    return replace(value, id=ValueID(f"{prefix}.{position}"),
                   origin=BlockArgument(block, position))


def _with_selected_route_cycle(graph, row):
    """Branch from the selected INVOKE edge to the terminal and a self-loop."""
    source = next(operation for operation in graph.operations if operation.id == row.operation)
    selected_index = row.contract.selected_edge.successor_index
    selected = source.terminator.successors[selected_index]
    region = next(region for region in graph.regions
                  if any(block.id == selected.block for block in region.blocks))
    target = next(block for block in region.blocks if block.id == selected.block)
    values = {value.id: value for value in graph.values}

    gate_id, loop_id = BlockID("path-safety.gate"), BlockID("path-safety.loop")
    gate_values = tuple(_clone_argument(values[value], gate_id, index, "path-safety.gate.arg")
                        for index, value in enumerate(target.arguments))
    loop_values = tuple(_clone_argument(value, loop_id, index, "path-safety.loop.arg")
                        for index, value in enumerate(gate_values))
    condition = DataValue(ValueID("path-safety.condition"), region.id,
                          LiteralOrigin(True), "builtins.bool")
    condition_use = Use(UseID("path-safety.condition.use"), condition.id, UseRole.DATA)

    branch_uses = [condition_use]
    terminal_actuals = []
    loop_actuals = []
    for index, value in enumerate(gate_values):
        use = Use(UseID(f"path-safety.terminal.{index}"), value.id, _role(value))
        branch_uses.append(use)
        terminal_actuals.append(use.id)
    for index, value in enumerate(gate_values):
        use = Use(UseID(f"path-safety.loop.{index}"), value.id, _role(value))
        branch_uses.append(use)
        loop_actuals.append(use.id)
    branch_id = OperationID("path-safety.branch")
    branch = Operation(
        branch_id, "selected route can terminate or continue forever", (Behavior.CONTROL,),
        tuple(branch_uses), effects_complete=True,
        terminator=Terminator(
            TerminatorKind.BRANCH,
            (Successor(target.id, tuple(terminal_actuals)),
             Successor(loop_id, tuple(loop_actuals))),
            condition=condition_use.id,
        ),
    )

    loop_uses = tuple(Use(UseID(f"path-safety.loop.back.{index}"), value.id, _role(value))
                      for index, value in enumerate(loop_values))
    loop_operation = Operation(
        OperationID("path-safety.loop.back"), "self-loop on selected route", (Behavior.CONTROL,),
        loop_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
                              (Successor(loop_id, tuple(use.id for use in loop_uses)),)),
    )

    successors = list(source.terminator.successors)
    successors[selected_index] = replace(selected, block=gate_id)
    changed_source = replace(source, terminator=replace(source.terminator,
                                                        successors=tuple(successors)))
    gate = Block(gate_id, tuple(value.id for value in gate_values), (branch_id,))
    loop = Block(loop_id, tuple(value.id for value in loop_values), (loop_operation.id,))
    changed_region = replace(region, blocks=(*region.blocks, gate, loop))
    changed_scopes = tuple(
        replace(scope, blocks=(*scope.blocks, gate_id, loop_id))
        if scope.region == region.id else scope
        for scope in graph.control_scopes
    )
    return replace(
        graph,
        regions=tuple(changed_region if item.id == region.id else item for item in graph.regions),
        operations=(*tuple(changed_source if item.id == source.id else item
                           for item in graph.operations), branch, loop_operation),
        values=(*graph.values, *gate_values, *loop_values, condition),
        control_scopes=changed_scopes,
    )


@pytest.mark.parametrize(
    "slot,terminal",
    (
        (0, "resume.raise"),
        (0, "driver.reject.raise"),
        (0, "boundary.raise"),
        (0, "adapter.failure.exit"),
        (1, "adapter.normal.exit"),
    ),
)
def test_host_terminal_must_copy_this_adapter_selected_result(slot, terminal):
    graph, _ = generator_protocol_program(target="value")
    assert any(operation.id == OperationID(terminal) for operation in graph.operations)
    row = _adapter_row(graph, slot)
    changed = _replace_row(graph, row, replace(
        row, contract=replace(row.contract, output=HostTerminal(OperationID(terminal)))))

    assert "protocol_copy" in _codes(changed)


@pytest.mark.parametrize(
    "slot,terminal",
    ((0, "adapter.normal.exit"), (1, "adapter.failure.exit")),
)
def test_host_terminal_can_receive_the_exact_adapter_normal_or_raise_result(slot, terminal):
    graph, _ = generator_protocol_program(target="value")
    row = _adapter_row(graph, slot)
    changed = _replace_row(graph, row, replace(
        row, contract=replace(row.contract, output=HostTerminal(OperationID(terminal)))))

    assert not _codes(changed)
    changed_row = _adapter_row(changed, slot)
    assert adapter_host_output(ProtocolFlow(changed), changed_row) is True


def test_adapter_cannot_claim_a_host_return_for_a_stop_iteration_rule():
    graph, _ = generator_protocol_program(target="value")
    row = _adapter_row(graph, 0)
    region = next(item for item in graph.regions if item.id == graph.root)
    terminal = next(operation for operation in graph.operations
                    if operation.id == OperationID("adapter.normal.exit"))
    payload = ValueID("adapter.exception")
    changed_terminal = replace(
        terminal,
        uses=tuple(replace(use, value=payload, role=UseRole.REFERENCE)
                   if index == 0 else use for index, use in enumerate(terminal.uses)),
        terminator=replace(terminal.terminator, kind=TerminatorKind.RETURN, exit="normal"),
    )
    old_failure = next(port for port in region.exits if port.kind is ExitKind.RAISE)
    normal = ExitPort(
        "normal", ExitKind.NORMAL,
        (ValueType(ValueKind.REFERENCE), *old_failure.types[1:]),
    )
    changed_region = replace(region, exits=(*region.exits, normal))
    changed = _replace_row(
        replace(
            graph,
            regions=tuple(changed_region if item.id == region.id else item for item in graph.regions),
            operations=tuple(changed_terminal if item.id == terminal.id else item
                             for item in graph.operations),
        ),
        row,
        replace(row, contract=replace(row.contract, output=HostTerminal(terminal.id))),
    )
    # The control graph is valid on its own; the rejection is the fixed
    # generator-to-StopIteration contract, not a malformed RETURN.
    assert not _codes(replace(changed, protocol_scopes=(), protocol_operations=()))
    assert "protocol_adapter_source" in _codes(changed)


def test_no_entry_path_with_reachable_terminal_and_cycle_does_not_seed_completion():
    graph, details = no_entry_throw_program(selected=ExitKind.NORMAL, reject=False)
    row = details["row"]
    changed = _with_selected_route_cycle(graph, row)

    assert not _codes(changed)
    context = ProtocolFlow(changed)
    changed_row = next(item for item in changed.protocol_operations if item == row)
    route = no_entry_route(context, changed_row)
    assert route["complete"] is False
    assert "no_entry_terminal_route_partial" in route["gaps"]
    assert (row.operation, row.slot) not in no_entry_seeds(changed, context.region_of[row.operation])

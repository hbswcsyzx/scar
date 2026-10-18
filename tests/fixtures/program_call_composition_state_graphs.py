"""Return then downward state routes over one original multi-region program."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, InvokeLiteralResult, Operation,
    OperationResult, ProtocolValue, ReferenceValue, Region, StateAccess,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_call_return_state_graphs import call_return_state_program
from tests.fixtures.program_protocol_graphs import _scope


def call_composition_state_program(*, branches=("raise",), invoke=False):
    """Insert H2 at exact H1 completion landings, retaining original state SSA.

    H1 NORMAL returns its original world; H1 RAISE writes world. Both preserve
    the independent context domain. Each selected branch calls the same H2,
    whose actual entry READ Uses are the query targets. These are declarations
    of original routes, not captured activations or native identity proofs.
    """
    if (type(branches) is not tuple or not branches or len(set(branches)) != len(branches)
            or any(branch not in ("normal", "raise") for branch in branches)):
        raise ValueError("branches must select distinct normal/raise landings")
    graph, base = call_return_state_program()
    root = graph.regions[0]
    h1 = base["callers"]["a"]
    h2_id, h2_entry = RegionID("compose-state.h2"), BlockID("compose-state.h2.entry")
    world_type = ValueType(ValueKind.STATE, location=base["world"])
    context_type = ValueType(ValueKind.STATE, location=base["context"])
    formals = tuple(StateVersionValue(ValueID(f"compose-state.h2.input.{index}"), h2_id,
        BlockArgument(h2_entry, index), location) for index, location in enumerate((base["world"], base["context"])))
    read_uses = tuple(Use(UseID(f"compose-state.h2.read.{index}"), value.id, UseRole.STATE_CONTENT)
                      for index, value in enumerate(formals))
    read = Operation(OperationID("compose-state.h2.read"), "original H2 state consumer",
        (Behavior.READ,), read_uses, accesses=tuple(StateAccess(location, use.id, AccessMode.READ)
            for location, use in zip((base["world"], base["context"]), read_uses)), effects_complete=True)
    return_uses = tuple(Use(UseID(f"compose-state.h2.return.{index}"), value.id, UseRole.STATE_CONTENT)
                        for index, value in enumerate(formals))
    terminal = Operation(OperationID("compose-state.h2.return"), "original H2 RETURN",
        (Behavior.CONTROL,), return_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in return_uses)))
    h2_block = Block(h2_entry, tuple(value.id for value in formals), (read.id, terminal.id))
    h2 = Region(h2_id, "second known state helper", h2_entry, (h2_block,),
                (ExitPort("normal", ExitKind.NORMAL, (world_type, context_type)),), parent=root.id)
    values = {value.id: value for value in graph.values}
    replacements, additions, new_values, new_blocks, calls = {}, [read, terminal], list(formals), [], {}
    blocks = list(root.blocks)
    for branch in branches:
        kind = ExitKind.NORMAL if branch == "normal" else ExitKind.RAISE
        consumer = h1["consumers"][kind]["operation"]
        block_index = next(index for index, block in enumerate(blocks) if consumer.id in block.operations)
        block = blocks[block_index]
        original_terminal = next(operation for operation in graph.operations if operation.id == block.operations[-1])
        name, call_id = "compose-state.call." + branch, OperationID("compose-state.call." + branch)
        actuals = tuple(Use(UseID(name + f".argument.{index}"), use.value, UseRole.STATE_CONTENT)
                        for index, use in enumerate(consumer.uses[1:]))
        if invoke:
            landing = BlockID(name + ".after")
            after = tuple(StateVersionValue(ValueID(name + f".state.{index}"), root.id,
                BlockArgument(landing, index), location)
                for index, location in enumerate((base["world"], base["context"])))
            original_payload = values[consumer.uses[0].value]
            payload_origin = BlockArgument(landing, 2)
            if isinstance(original_payload, ProtocolValue):
                payload = ProtocolValue(ValueID(name + ".payload"), root.id, payload_origin, original_payload.protocol)
                payload_role = UseRole.PROTOCOL
            else:
                payload = ReferenceValue(ValueID(name + ".payload"), root.id, payload_origin)
                payload_role = UseRole.REFERENCE
            forward = Use(UseID(name + ".payload.forward"), original_payload.id, payload_role)
            call = Operation(call_id, "original second-helper INVOKE", (Behavior.CONTROL,),
                (*actuals, forward), effects_complete=True, callee=h2_id,
                invoke_arguments=tuple(use.id for use in actuals),
                completions=(CompletionSignature(ExitKind.NORMAL, (world_type, context_type)),),
                terminator=Terminator(TerminatorKind.INVOKE, (
                    CompletionSuccessor(ExitKind.NORMAL, landing,
                        (CompletionResult(0), CompletionResult(1), forward.id)),)))
            sources = tuple(InvokeLiteralResult(ControlEdgeReference(call.id, 0), CompletionResult(index))
                            for index in range(2))
            new_values.append(payload)
            new_blocks.append(Block(landing, (*tuple(value.id for value in after), payload.id),
                                    (consumer.id, original_terminal.id)))
            blocks[block_index] = replace(block, operations=(call.id,))
        else:
            after = tuple(StateVersionValue(ValueID(name + f".state.{index}"), root.id,
                OperationResult(call_id, index), location)
                for index, location in enumerate((base["world"], base["context"])))
            payload = values[consumer.uses[0].value]
            call = Operation(call_id, "original second-helper CALL", (Behavior.CONTROL,),
                actuals, tuple(value.id for value in after), effects_complete=True,
                callee=h2_id, call_arguments=tuple(use.id for use in actuals))
            sources = tuple(value.origin for value in after)
            blocks[block_index] = replace(block, operations=(call.id, *block.operations))
        changed = {consumer.uses[0].value: payload.id,
                   consumer.uses[1].value: after[0].id, consumer.uses[2].value: after[1].id}
        replacements[consumer.id] = replace(consumer,
            uses=tuple(replace(use, value=changed.get(use.value, use.value)) for use in consumer.uses))
        replacements[original_terminal.id] = replace(original_terminal,
            uses=tuple(replace(use, value=changed.get(use.value, use.value)) for use in original_terminal.uses))
        additions.append(call)
        new_values.extend(after)
        calls[branch] = {"operation": call, "arguments": tuple(OwnedUse(call.id, use.id) for use in actuals),
                         "sources": sources, "outputs": after}
    root = replace(root, blocks=(*blocks, *new_blocks))
    graph = replace(graph, regions=(root, *graph.regions[1:], h2),
        operations=tuple(replacements.get(operation.id, operation) for operation in graph.operations) + tuple(additions),
        values=(*graph.values, *new_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in root.blocks))
            if scope.region == root.id else scope for scope in graph.control_scopes) + (_scope(h2_id, (h2_block,)),))
    return graph, {"base": base, "h1": h1, "h2": h2, "calls": calls, "h2_formals": formals,
        "targets": {"world": OwnedUse(read.id, read_uses[0].id),
                    "context": OwnedUse(read.id, read_uses[1].id)},
        "old_world": h1["arguments"][3], "old_context": h1["arguments"][4],
        "new_raise_world": base["raise_world"], "internal_context": base["callee_arguments"][4].origin}

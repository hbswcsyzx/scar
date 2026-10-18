"""Original branch ports extended with paired owner/key address requests."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, DataValue, LiteralOrigin, Operation,
    OperationResult, ReferenceValue, StateAccess, Use, UseRole,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, Element, ExistingAccess, ReferenceOwner,
    StateAddressRefinement,
)
from tests.fixtures.program_graphs import branch_state_program


def branch_address_program():
    program = branch_state_program()
    values = {row.id: row for row in program.values}
    operations = {row.id: row for row in program.operations}
    reference = values[ValueID('reference')]
    buffer = program.locations[0].id
    other = replace(reference, id=ValueID('other.reference'), referent_identity=None,
                    origin=BlockArgument(BlockID('entry'), 5))
    other_key = DataValue(ValueID('other.key'), program.root, LiteralOrigin(1), 'builtins.int')
    added, refinements, blocks, forwards = [other, other_key], [], [], []
    choose = operations[OperationID('choose')]
    successors = []
    for edge, label in enumerate(('normal', 'failure')):
        block = next(block for block in program.regions[0].blocks if block.id == BlockID(label))
        owner = replace(reference, id=ValueID(label + '.owner'), referent_identity=None,
                        origin=BlockArgument(block.id, len(block.arguments)))
        key = DataValue(ValueID(label + '.key'), program.root,
                        BlockArgument(block.id, len(block.arguments)+1), 'builtins.int')
        added.extend((owner, key))
        owner_forward = Use(UseID('choose.'+label+'.owner'), reference.id if edge == 0 else other.id,
                            UseRole.REFERENCE)
        key_forward = Use(UseID('choose.'+label+'.key'), ValueID('input') if edge == 0 else other_key.id)
        forwards.extend((owner_forward, key_forward))
        successors.append(replace(choose.terminator.successors[edge],
            arguments=(*choose.terminator.successors[edge].arguments, owner_forward.id, key_forward.id)))
        op_id = OperationID('read' if edge == 0 else 'read.failure')
        ref_use = Use(UseID('read.reference' if edge == 0 else 'failure.read.reference'), owner.id,
                      UseRole.REFERENCE)
        key_use = Use(UseID(label+'.read.key'), key.id)
        if edge == 0:
            old = operations[op_id]
            operations[op_id] = replace(old, uses=tuple(
                ref_use if use.id == ref_use.id else use for use in old.uses)+(key_use,))
            block_ops = block.operations
        else:
            state_use = Use(UseID('failure.read.state'), ValueID('buffer.failure'), UseRole.STATE_CONTENT)
            result = DataValue(ValueID('failure.read.value'), program.root, OperationResult(op_id, 0),
                               'builtins.int')
            added.append(result)
            operations[op_id] = Operation(op_id, 'read selected branch owner/key', (Behavior.READ,),
                (ref_use, key_use, state_use), (result.id,),
                (StateAccess(buffer, state_use.id, AccessMode.READ, footprint=reference.selector,
                             reference=ref_use.id),), effects_complete=True)
            block_ops = (op_id, *block.operations)
        blocks.append(replace(block, arguments=(*block.arguments, owner.id, key.id), operations=block_ops))
        refinements.append(StateAddressRefinement(ExistingAccess(op_id, 0),
            (AddressEffect(ReferenceOwner(ref_use.id), (Element(key_use.id),), AccessMode.READ),),
            AddressCoverage.PARTIAL))
    operations[choose.id] = replace(choose, uses=(*choose.uses, *forwards),
                                    terminator=replace(choose.terminator, successors=tuple(successors)))
    entry = program.regions[0].blocks[0]
    entry = replace(entry, arguments=(*entry.arguments, other.id))
    return replace(program, values=(*program.values, *added), operations=tuple(operations.values()),
        regions=(replace(program.regions[0], blocks=(entry, *blocks)),),
        state_address_refinements=tuple(refinements))

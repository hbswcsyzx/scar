"""Original call chains whose helpers receive references, never a raw pack."""
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, ExitKind, ExitPort, LiteralOrigin,
    Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue,
    Region, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocols import OwnedUse


def helper_request_program(*, arity=3, depth=1, late_pack=False, shared_operands=False):
    """Two callers of one helper, with independent raw anchors in the caller.

    All literal contents are None; separate canonical producers still differ.
    ``late_pack`` is a valid core where the selected pack is constructed only
    after both helper calls, so it cannot be their current request source.
    No helper consumes RAW_DRIVER_REQUEST or an invented raw argument.
    """
    assert arity in (1, 2, 3) and depth in (1, 2)
    root_id = RegionID('helper.root')
    root_block = BlockID('helper.root.entry')
    helper_ids = tuple(RegionID(f'helper.level.{number}') for number in range(depth))
    operations, values, regions, requests = [], [], [], []
    payloads = {}
    for label in ('left', 'right'):
        payloads[label] = tuple(ValueID(f'helper.{label}.value.{number}') for number in range(arity))
        values.extend(ReferenceValue(identity, root_id, LiteralOrigin(None), targets=())
                      for identity in payloads[label])
    if shared_operands:
        payloads['right'] = payloads['left']

    packs, anchors, calls = {}, {}, {}
    for label in ('left', 'right'):
        pack_id = OperationID(f'helper.{label}.pack')
        raw_id = ValueID(f'helper.{label}.raw')
        pack_uses = tuple(Use(UseID(f'{pack_id.value}.operand.{number}'), identity,
                              UseRole.REFERENCE) for number, identity in enumerate(payloads[label]))
        packs[label] = Operation(pack_id, 'original raw THROW pack', (Behavior.COMPUTE,),
                                pack_uses, (raw_id,), effects_complete=True)
        values.append(ProtocolValue(raw_id, root_id, OperationResult(pack_id, 0),
                                    ProtocolValueKind.RAW_DRIVER_REQUEST))
        requests.append(RawRequestDefinition(raw_id, RawRequestKind.THROW,
                                             tuple(use.id for use in pack_uses)))
        raw_use = Use(UseID(f'helper.{label}.anchor.raw'), raw_id, UseRole.PROTOCOL)
        anchors[label] = Operation(OperationID(f'helper.{label}.anchor'), 'original raw consumer',
                                  (Behavior.COMPUTE,), (raw_use,), effects_complete=True)
        arguments = tuple(Use(UseID(f'helper.{label}.call.arg.{number}'), identity,
                             UseRole.REFERENCE) for number, identity in enumerate(payloads[label]))
        calls[label] = Operation(OperationID(f'helper.{label}.call'), 'call reference-only helper',
                                 (Behavior.CONTROL,), arguments, callee=helper_ids[0],
                                 call_arguments=tuple(use.id for use in arguments), effects_complete=True)

    def terminal(name):
        return Operation(OperationID(name), 'original normal completion', (Behavior.CONTROL,),
                         terminator=Terminator(TerminatorKind.RETURN, exit='normal'))

    done = terminal('helper.root.done')
    root_ops = ([packs['right'], anchors['right'], calls['left'], calls['right'],
                 packs['left'], anchors['left'], done] if late_pack else
                [packs['left'], packs['right'], anchors['left'], anchors['right'],
                 calls['left'], calls['right'], done])
    operations.extend(root_ops)
    regions.append(Region(root_id, 'caller with real raw anchors', root_block,
        (Block(root_block, (), tuple(op.id for op in root_ops)),),
        (ExitPort('normal', ExitKind.NORMAL, ()),)))
    consumer = None
    for level, region_id in enumerate(helper_ids):
        block_id = BlockID(f'{region_id.value}.entry')
        arguments = tuple(ReferenceValue(ValueID(f'{region_id.value}.arg.{number}'), region_id,
                            BlockArgument(block_id, number)) for number in range(arity))
        values.extend(arguments)
        uses = tuple(Use(UseID(f'{region_id.value}.use.{number}'), value.id, UseRole.REFERENCE)
                     for number, value in enumerate(arguments))
        final = terminal(f'{region_id.value}.done')
        if level + 1 < depth:
            action = Operation(OperationID(f'{region_id.value}.call'), 'forward original reference inputs',
                (Behavior.CONTROL,), uses, callee=helper_ids[level + 1],
                call_arguments=tuple(use.id for use in uses), effects_complete=True)
        else:
            action = Operation(OperationID(f'{region_id.value}.consume'), 'consume actual reference inputs',
                               (Behavior.COMPUTE,), uses, effects_complete=True)
            consumer = action
        operations.extend((action, final))
        regions.append(Region(region_id, 'reference-only helper', block_id,
            (Block(block_id, tuple(value.id for value in arguments), (action.id, final.id)),),
            (ExitPort('normal', ExitKind.NORMAL, ()),),
            parent=root_id if level == 0 else helper_ids[level - 1]))
    graph = ProgramGraph(root_id, tuple(regions), tuple(operations), tuple(values),
                         raw_driver_requests=tuple(requests))
    return graph, {'raw': {label: OwnedUse(op.id, op.uses[0].id) for label, op in anchors.items()},
                   'calls': calls, 'consumer': consumer,
                   'inputs': tuple(OwnedUse(consumer.id, use.id) for use in consumer.uses)}

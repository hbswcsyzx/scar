"""A returned result does not make its conditional source input unconditional."""
from dataclasses import replace

from scar.ir.program.control import ExceptionPacketDefinition, ProtocolValueKind
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, DataValue, ExitKind,
    InvokeLiteralResult, Operation, OperationResult, ProtocolValue, ReferenceValue,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_final_region_graphs import await_final_region_program


def _use(name, value):
    return Use(UseID(name), value.id,
        UseRole.STATE_CONTENT if type(value) is StateVersionValue else
        UseRole.PROTOCOL if type(value) is ProtocolValue else UseRole.DATA)


def _conditional_packet_input_program():
    """Either the original packet P or a separately constructed Q reaches F.

    Both paths carry their actual current world/context parameters. F keeps
    its real N/R and its result still reaches the interface's original exits.
    """
    program, details = await_final_region_program()
    record = details['stage_records'][0]
    region, primitive = record['region'], record['operation']
    packet, world, context = record['formals']
    prefix = 'await.final.conditional.input'
    refs_id = OperationID(prefix + '.references')
    exception = ReferenceValue(ValueID(prefix + '.exception'), region.id,
                               OperationResult(refs_id, 0))
    traceback = ReferenceValue(ValueID(prefix + '.traceback'), region.id,
                               OperationResult(refs_id, 1))
    references = Operation(refs_id, 'independent original exception and traceback references',
        (Behavior.COMPUTE,), results=(exception.id, traceback.id), effects_complete=True)
    pack_id = OperationID(prefix + '.pack')
    other_packet = ProtocolValue(ValueID(prefix + '.other.packet'), region.id,
        OperationResult(pack_id, 0), ProtocolValueKind.EXCEPTION_PACKET)
    packet_uses = (
        Use(UseID(prefix + '.pack.exception'), exception.id, UseRole.REFERENCE),
        Use(UseID(prefix + '.pack.traceback'), traceback.id, UseRole.REFERENCE),
    )
    pack = Operation(pack_id, 'construct the independent original packet Q',
        (Behavior.CONTROL,), packet_uses, (other_packet.id,), effects_complete=True)
    definition = ExceptionPacketDefinition(other_packet.id,
        packet_uses[0].id, packet_uses[1].id)
    test_id = OperationID(prefix + '.decision')
    condition = DataValue(ValueID(prefix + '.condition'), region.id,
                          OperationResult(test_id, 0), 'builtins.bool')
    test = Operation(test_id, 'original boolean choice without a declared literal result',
        (Behavior.COMPUTE,),
        (Use(UseID(prefix + '.decision.input'), exception.id, UseRole.REFERENCE),),
        (condition.id,), effects_complete=True)

    merge_id = BlockID(prefix + '.merge')
    merged = tuple(replace(value, id=ValueID(f'{prefix}.merged.{ordinal}'),
        origin=BlockArgument(merge_id, ordinal))
        for ordinal, value in enumerate((packet, world, context)))
    arms, operations, values, branch_edges, branch_uses = [], [], [], [], []
    for label, input_packet in (('p', packet), ('q', other_packet)):
        block_id = BlockID(prefix + '.' + label)
        formals = tuple(replace(value, id=ValueID(f'{prefix}.{label}.input.{ordinal}'),
            origin=BlockArgument(block_id, ordinal))
            for ordinal, value in enumerate((packet, world, context)))
        actuals = tuple(_use(f'{prefix}.branch.{label}.{ordinal}', value)
                        for ordinal, value in enumerate((input_packet, world, context)))
        branch_uses.extend(actuals)
        branch_edges.append(Successor(block_id, tuple(use.id for use in actuals)))
        jump_uses = tuple(_use(f'{prefix}.{label}.jump.{ordinal}', value)
                          for ordinal, value in enumerate(formals))
        jump = Operation(OperationID(prefix + '.' + label + '.jump'),
            'forward this arm packet and its current state', (Behavior.CONTROL,),
            jump_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(merge_id, tuple(use.id for use in jump_uses)),)))
        arms.append(Block(block_id, tuple(value.id for value in formals), (jump.id,)))
        operations.append(jump)
        values.extend(formals)
    condition_use = Use(UseID(prefix + '.branch.condition'), condition.id, UseRole.DATA)
    branch = Operation(OperationID(prefix + '.branch'), 'select P or Q before the same primitive',
        (Behavior.CONTROL,), (condition_use, *branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(branch_edges),
                              condition=condition_use.id))
    substitutions = {value.id: formal.id
                     for value, formal in zip((packet, world, context), merged)}
    changed_primitive = replace(primitive, uses=tuple(
        replace(use, value=substitutions.get(use.value, use.value))
        for use in primitive.uses))
    entry = replace(record['entry'],
        operations=(references.id, pack.id, test.id, branch.id))
    merge = Block(merge_id, tuple(value.id for value in merged), (changed_primitive.id,))
    changed_region = replace(region,
        blocks=(entry, *arms, merge,
                *(block for block in region.blocks if block.id != region.entry)))
    added_blocks = tuple(block.id for block in (*arms, merge))
    program = replace(program,
        regions=tuple(changed_region if candidate.id == region.id else candidate
                      for candidate in program.regions),
        operations=tuple(changed_primitive if operation.id == primitive.id else operation
                         for operation in program.operations)
                   + (references, pack, test, branch, *operations),
        values=(*program.values, exception, traceback, other_packet, condition,
                *values, *merged),
        exception_packets=(*program.exception_packets, definition),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *added_blocks))
            if scope.region == region.id else scope for scope in program.control_scopes))
    return program, details


def test_output_copy_does_not_upgrade_a_may_only_packet_input_to_full_contribution():
    program, details = _conditional_packet_input_program()
    core = replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())
    require_valid(core)
    require_valid(program)
    report = ProgramIndex(program).protocol_obligations(details['acquisition_scope'],
        budget=1048576)['connections']['families']['await']
    outcome, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['drive_outcome'] == details['drive_outcome']
        and row['advance_operation'] == details['advance_operation'])
    consumer, = tuple(row for row in outcome['consumers']
        if row['actual'] == details['extract_input']
        and row['requires_final_extraction'] is True)
    implementation = consumer['implementation']
    stage, = tuple(stage for stage in implementation['stages']
        if stage['operation'] == details['primitive'].id)
    packet_input = stage['inputs'][0]
    assert packet_input['actual'] == details['stage_records'][0]['arguments'][0]
    assert packet_input['may'] is True
    assert packet_input['must'] is False
    assert packet_input['binding']['match'] is False
    normal_index = next(number for number, edge in enumerate(
        details['parent_call'].terminator.successors) if edge.kind is ExitKind.NORMAL)
    required = InvokeLiteralResult(ControlEdgeReference(details['parent_call'].id, normal_index),
                                  CompletionResult(0))
    paths = tuple(path for leg in stage['legs'] if leg['kind'] is ExitKind.NORMAL
        for result in leg['results'] if result['slot'] == 0
        for path in result['paths'] if path['interface_result'] == required)
    assert paths and all(path['binding']['match'] is True for path in paths)
    output, = tuple(row for row in implementation['outputs'] if row['source'] == required)
    terminal, = tuple(row for row in output['terminals']
        if row['terminal'] == details['stage_records'][0]['terminal_payloads'][ExitKind.NORMAL])
    # Output equality remains true; it cannot discharge the independent
    # obligation that this same F invocation actually received source P.
    assert terminal['match'] is not True
    assert output['status'] != 'DECLARED'
    assert all(path['input_support']['match'] is not True for path in paths)
    assert all(path['contribution']['match'] is not True for path in paths)
    assert implementation['source_runtime_verified'] is False
    assert implementation['runtime_identity_verified'] is False
    assert implementation['transformation_authorized'] is False

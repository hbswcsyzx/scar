"""Typed iterator checks constrain paths without inventing a producer or bool.

All graphs are supplied canonical declarations. Their fixed native predicate
meaning remains conditional; these fixtures do not recover runtime behavior.
"""
from dataclasses import replace

from scar.ir.literals import PythonLiteral
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, LiteralEvaluation, LiteralOrigin,
    Operation, StateVersionValue, Successor, Terminator, TerminatorKind, Use,
    UseRole,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import StaticGapReason, StaticProtocolGap
from scar.ir.program.resumption import ResumableKind
from tests.fixtures.program_await_general_graphs import await_general_program


def qualified_general_program(*, result_kind=ResumableKind.GENERATOR_COROUTINE):
    """Return the original complete accept/reject CFG and its typed check."""
    return await_general_program(result_kind=result_kind)


def predicate_literal_program():
    """The own bool claims True although this exact declared check must reject."""
    graph, details = qualified_general_program()
    declaration = LiteralEvaluation(details['qualification_row'].contract.result,
                                    PythonLiteral.from_python(True, exact=True))
    return replace(graph, literal_evaluations=(*graph.literal_evaluations, declaration)), {
        **details, 'predicate_literal': declaration}


def unknown_general_program():
    """Keep the real method result but omit its optional Create interpretation."""
    graph, details = qualified_general_program()
    return replace(graph, resumable_creates=tuple(create for create in graph.resumable_creates
        if create != details['helper_create'])), details


def unqualified_general_program():
    """Remove only the typed check declaration; keep its original CFG/advance.

The generic computation and branch still exist. They cannot certify iterator
qualification after their fixed semantic contract has been removed.
"""
    graph, details = qualified_general_program()
    qualifier = details['qualification_row']
    site = ProtocolOperationRef(qualifier.scope, qualifier.clause,
                                qualifier.operation, qualifier.slot)
    gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    get_rows = tuple(replace(row, contract=replace(row.contract,
        expansion=replace(row.contract.expansion, qualification=gap)))
        for row in details['get_rows'])
    replacement = {row.slot: row for row in get_rows}
    graph = replace(graph, protocol_operations=tuple(
        replacement[row.slot] if row in details['get_rows'] else row
        for row in graph.protocol_operations if row != qualifier),
        protocol_result_consumers=tuple(receipt for receipt in graph.protocol_result_consumers
                                        if receipt.site != site))
    return graph, {**details, 'get_rows': get_rows, 'removed_qualification': qualifier}


def wrong_bool_general_program():
    """Keep the check but make its exact branch consume an unrelated bool."""
    graph, details = qualified_general_program()
    branch = details['qualification_branch']
    wrong = DataValue(ValueID('await.qualification.unrelated.bool'), details['helper'].id,
                      LiteralOrigin(False), 'builtins.bool')
    branch = replace(branch, uses=tuple(replace(use, value=wrong.id)
        if use.id == branch.terminator.condition else use for use in branch.uses))
    return replace(graph,
        operations=tuple(branch if op.id == branch.id else op for op in graph.operations),
        values=(*graph.values, wrong)), {**details, 'qualification_branch': branch, 'wrong_bool': wrong}


def bypass_qualification_program():
    """A real post-call branch can reach the successful return without checking.

The other arm still enters the original check and its accept/reject paths.
The mere presence of that check cannot qualify the bypassed candidate.
"""
    graph, details = qualified_general_program()
    helper = details['helper']
    call = details['helper_call']
    old = next(block for block in helper.blocks if block.id == details['helper_call_normal'])
    values = {value.id: value for value in graph.values}
    block_id = BlockID('await.qualification.bypass')
    operation_id = OperationID('await.qualification.bypass.branch')
    formals = tuple(replace(values[identity],
        id=ValueID(f'await.qualification.bypass.argument.{index}'),
        origin=BlockArgument(block_id, index)) for index, identity in enumerate(old.arguments))
    condition = DataValue(ValueID('await.qualification.bypass.condition'), helper.id,
                          LiteralOrigin(True), 'builtins.bool')
    condition_use = Use(UseID('await.qualification.bypass.choose'), condition.id, UseRole.DATA)
    arms = tuple(tuple(Use(UseID(f'await.qualification.bypass.{arm}.{index}'), value.id,
        UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else UseRole.REFERENCE)
        for index, value in enumerate(formals)) for arm in range(2))
    accepted = details['qualification_branch'].terminator.successors[0].block
    branch = Operation(operation_id, 'original path bypasses the iterator check',
        (Behavior.CONTROL,), (condition_use, *arms[0], *arms[1]), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(accepted, tuple(use.id for use in arms[0])),
            Successor(old.id, tuple(use.id for use in arms[1]))), condition=condition_use.id))
    block = Block(block_id, tuple(value.id for value in formals), (branch.id,))
    call = replace(call, terminator=replace(call.terminator,
        successors=tuple(replace(edge, block=block.id) if edge.kind is ExitKind.NORMAL else edge
                         for edge in call.terminator.successors)))
    helper = replace(helper, blocks=(*helper.blocks, block))
    graph = replace(graph,
        regions=tuple(helper if region.id == helper.id else region for region in graph.regions),
        operations=tuple(call if op.id == call.id else op for op in graph.operations) + (branch,),
        values=(*graph.values, *formals, condition),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, block.id))
            if scope.region == helper.id else scope for scope in graph.control_scopes))
    return graph, {**details, 'helper': helper, 'helper_call': call, 'bypass': branch}


__all__ = ['qualified_general_program', 'predicate_literal_program', 'unknown_general_program',
           'unqualified_general_program',
           'wrong_bool_general_program', 'bypass_qualification_program']

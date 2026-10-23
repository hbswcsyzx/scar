"""Conditional expression rules over the existing canonical source body CFG.

Value context retains the selected object; predicate context produces a boolean
without testing a short-circuit result a second time. Source children remain
separate operations and Uses. Nothing here executes a target or proves effects.

The distinction follows CPython 3.14 Python/codegen.c's codegen_boolop,
codegen_ifexp and codegen_jump_if. Lifetimes retain the existing conditional
FrameRules; a held selected reference is forwarded, never released/recreated.
"""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _BOOL, _REF, _Unsupported
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import (
    Behavior, DataValue, LiteralOrigin, Operation, Successor, Terminator,
    TerminatorKind,
)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind


def _value(builder, node, cursor):
    if isinstance(node, ast.BoolOp):
        return lower_bool_expression(builder, node, cursor)
    if isinstance(node, ast.IfExp):
        return lower_if_expression(builder, node, cursor)
    return builder.expr(node, cursor)


def _hold(builder, cursor, node, value):
    builder.frame_transition(cursor, node, ((value, node, "held-condition-reference"),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(value)


def _finish_hold(builder, value):
    # The INVOKE failure path has already captured this active temporary.
    # Other branches must not inherit references defined only in this path.
    if not builder.active_temporaries or builder.active_temporaries[-1] != value:
        raise ValueError("conditional expression temporary stack differs")
    builder.active_temporaries.pop()


def _release(builder, cursor, node, value):
    builder.frame_transition(cursor, node, ((value, node, "discarded-condition-reference"),),
                             PythonProtocolKind.FRAME_RELEASE_TEMPORARY)


def _names(builder, cursors, node):
    names = tuple(sorted(cursors[0].env))
    if any(set(cursor.env) != set(names) for cursor in cursors):
        raise _Unsupported(GapKind.CONTROL_FLOW, node,
                           "conditional expression changed the ordinary binding domain")
    return names


def _merge_paths(builder, cursors, node):
    if not cursors:
        return None
    return builder.merge(cursors, _names(builder, cursors, node), node)


def _jump_payload(builder, cursor, target, names, value, node, role):
    operation_id = builder.fresh(OperationID, "conditional-value-jump")
    uses = tuple(builder.use(operation_id, cursor.env[name], node, "carried-binding", index)
                 for index, name in enumerate(names))
    uses += (builder.use(operation_id, value, node, role, 0),
             builder.use(operation_id, cursor.state, node, "state", 0))
    builder.emit(cursor, Operation(operation_id, "conditional-jump", (Behavior.CONTROL,), uses,
        terminator=Terminator(TerminatorKind.JUMP,
            (Successor(target.block, tuple(use.id for use in uses)),))), node, SourceRole.CONTROL)


def _join_payloads(builder, incoming, node, kind, *, semantic_value=None, role=SourceRole.MERGE):
    if not incoming:
        return None, None
    if len(incoming) == 1:
        cursor, value = incoming[0]
        builder.link_value(builder.values_by_id[value], node, role, semantic_value=semantic_value)
        return cursor, value
    cursors = [cursor for cursor, _ in incoming]
    names = _names(builder, cursors, node)
    changed = tuple(name for name in names if len({cursor.env[name] for cursor in cursors}) > 1)
    target = builder.new_block(node, named=changed, role=role, extra_types=(kind,))
    target.env.update({name: cursors[0].env[name] for name in names if name not in changed})
    value = builder.block_arguments[target.block][len(changed)]
    builder.link_value(builder.values_by_id[value], node, role, semantic_value=semantic_value)
    for cursor, payload in incoming:
        _jump_payload(builder, cursor, target, changed, payload, node,
                      "selected-reference" if kind == _REF else "predicate-result")
    return target, value


def _condition_paths(builder, node, cursor):
    """Return normal true/false cursors; raises already carry their post-world."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yes, no = _condition_paths(builder, node.operand, cursor)
        return no, yes
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)) or len(node.values) < 2:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "invalid boolean expression source")
        short_paths = []
        current = cursor
        for index, child in enumerate(node.values):
            yes, no = _condition_paths(builder, child, current)
            proceeding, short = (yes, no) if isinstance(node.op, ast.And) else (no, yes)
            short_paths.extend(short)
            if index == len(node.values) - 1:
                return (proceeding, short_paths) if isinstance(node.op, ast.And) else (short_paths, proceeding)
            current = _merge_paths(builder, proceeding, child)
            if current is None:
                return ([], short_paths) if isinstance(node.op, ast.And) else (short_paths, [])
    if isinstance(node, ast.IfExp):
        yes, no = _condition_paths(builder, node.test, cursor)
        truthy, falsy = [], []
        for paths, child in ((yes, node.body), (no, node.orelse)):
            current = _merge_paths(builder, paths, node.test)
            if current is not None:
                branch_yes, branch_no = _condition_paths(builder, child, current)
                truthy.extend(branch_yes)
                falsy.extend(branch_no)
        return truthy, falsy
    cursor, value = _value(builder, node, cursor)
    if cursor is None:
        return [], []
    _hold(builder, cursor, node, value)
    cursor, boolean, _ = builder.invoke_protocol(cursor, node, (value,),
                                                 PythonProtocolKind.TRUTH, result_type=_BOOL)
    _finish_hold(builder, value)
    _release(builder, cursor, node, value)
    yes, no = builder.new_block(node), builder.new_block(node)
    builder.branch(cursor, boolean, yes, no, node)
    return [yes], [no]


def lower_condition_expression(builder, node, cursor):
    """Return (normal cursor, boolean DataValue) for a predicate context.

    If/While callers use this boolean directly in their existing final branch.
    They must not call TRUTH again. All helper transfers use expression source,
    leaving a loop's own preheader/backedge source correspondence unchanged.
    """
    yes, no = _condition_paths(builder, node, cursor)
    incoming = []
    for paths, literal in ((yes, True), (no, False)):
        if not paths:
            continue
        value = DataValue(builder.fresh(ValueID, "predicate-literal"), builder.function_context,
                          LiteralOrigin(literal), "builtins.bool")
        builder.add_value(value)
        builder.link_value(value, node, SourceRole.TRUTH)
        incoming.extend((path, value.id) for path in paths)
    return _join_payloads(builder, incoming, node, _BOOL, role=SourceRole.TRUTH)


def lower_bool_expression(builder, node, cursor):
    """Return the original short-circuit operand, or the untested last value."""
    if not isinstance(node, ast.BoolOp) or not isinstance(node.op, (ast.And, ast.Or)) or len(node.values) < 2:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected a boolean value expression")
    old = builder.old_operation(node)
    incoming = []
    for index, child in enumerate(node.values):
        cursor, value = _value(builder, child, cursor)
        if cursor is None:
            break
        if index == len(node.values) - 1:
            incoming.append((cursor, value))
            break
        _hold(builder, cursor, child, value)
        cursor, boolean, _ = builder.invoke_protocol(cursor, child, (value,),
                                                     PythonProtocolKind.TRUTH, result_type=_BOOL)
        _finish_hold(builder, value)
        yes, no = builder.new_block(child), builder.new_block(child)
        builder.branch(cursor, boolean, yes, no, node)
        proceeding, short = (yes, no) if isinstance(node.op, ast.And) else (no, yes)
        incoming.append((short, value))
        # The short path transfers its held reference to the result. Only the
        # continuation discards it before the next operand can run or raise.
        _release(builder, proceeding, child, value)
        cursor = proceeding
    return _join_payloads(builder, incoming, node, _REF, semantic_value=old.result)


def lower_if_expression(builder, node, cursor):
    """Evaluate a condition and exactly one result arm, retaining each Use."""
    if not isinstance(node, ast.IfExp):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected a conditional value expression")
    old = builder.old_operation(node)
    yes, no = _condition_paths(builder, node.test, cursor)
    incoming = []
    for paths, child in ((yes, node.body), (no, node.orelse)):
        current = _merge_paths(builder, paths, node.test)
        if current is not None:
            current, value = _value(builder, child, current)
            if current is not None:
                incoming.append((current, value))
    return _join_payloads(builder, incoming, node, _REF, semantic_value=old.result)


__all__ = ["lower_bool_expression", "lower_if_expression", "lower_condition_expression"]

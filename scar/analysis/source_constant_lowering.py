"""Read non-scalar Python constants from a witnessed code-constant slot.

This is a source interface, not object construction or a content-version proof.
The reference keeps its original producer; no Python object ID is inferred.
"""
from __future__ import annotations

import ast
import dis
import math
import struct

from scar.analysis.program_lowering import _Unsupported
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Operation, OperationResult, ReferenceValue, StateAccess,
)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource
from scar.ir.program.structured import PythonProtocolKind


def needs_code_constant(node):
    """Legacy exact scalar literals keep their existing representation."""
    if not isinstance(node, ast.Constant):
        return False
    value = node.value
    return not (value is None or type(value) in (bool, int, str)
                or type(value) is float and math.isfinite(value))


def same_constant(left, right):
    """Bounded builtin comparison, including signed zero and NaN payloads."""
    if type(left) is not type(right):
        return False
    if type(left) is bytes:
        return left == right
    if type(left) is float:
        return struct.pack('!d', left) == struct.pack('!d', right)
    if type(left) is complex:
        return (struct.pack('!dd', left.real, left.imag)
                == struct.pack('!dd', right.real, right.imag))
    return left is Ellipsis and right is Ellipsis


def witnessed_constant(evidence, node, *, index=None):
    """Resolve the exact original LOAD_CONST position without compiling code."""
    if evidence is None:
        raise ValueError('non-scalar constant requires its independent CodeWitness')
    if not needs_code_constant(node):
        raise ValueError('source constant is outside the explicit constant profile')
    span = (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
    matches = [row for row in dis.get_instructions(evidence.code)
               if row.opname == 'LOAD_CONST' and type(row.arg) is int
               and tuple(row.positions) == span
               and (index is None or row.arg == index)]
    if len(matches) != 1:
        raise ValueError('constant requires one exact original LOAD_CONST position')
    row, = matches
    if (row.arg >= len(evidence.code.co_consts)
            or evidence.code.co_consts[row.arg] is not row.argval
            or not same_constant(row.argval, node.value)):
        raise ValueError('source constant differs from its witnessed constant slot')
    return row.arg


def lower_code_constant(builder, node, cursor):
    evidence = builder.language_options.code_evidence
    try:
        index = witnessed_constant(evidence, node)
    except ValueError as error:
        raise _Unsupported(GapKind.CODE_VERSION, node, str(error)) from error
    old = builder.old_operation(node)
    operation_id = builder.fresh(OperationID, 'source-code-constant')
    before = builder.use(operation_id, cursor.state, node, 'code-constant-world', 0)
    result = ReferenceValue(builder.fresh(ValueID, 'source-code-constant'),
        builder.function_context, OperationResult(operation_id, 0))
    builder.add_value(result)
    builder.link_value(result, node, SourceRole.EXPRESSION,
                       semantic_value=old.result if old else None)
    operation = Operation(operation_id, 'code constant reference', (Behavior.READ,),
        (before,), (result.id,),
        (StateAccess(builder.world, before.id, AccessMode.READ),), effects_complete=False)
    # The code-table read is the explicit implementation of the source
    # constant reference, not the source semantic CONSTANT operation itself.
    # Keep original semantic value correspondence above; the protocol has its
    # own source link, as existing slice/function constant reads do.
    builder.emit(cursor, operation, node, SourceRole.EXPRESSION)
    builder.protocol(operation_id, PythonProtocolKind.READ_CODE_CONSTANT, node)
    builder.language_constants.append(CodeConstantSource(operation_id, builder.source(node),
        evidence.captured.key, (index,)))
    builder.gap(GapKind.CODE_VERSION, node,
        'source and code constant slot are witnessed; active code/constant object identity remains unproved')
    return cursor, result.id


__all__ = ['needs_code_constant', 'same_constant', 'witnessed_constant', 'lower_code_constant']

"""Slice/key construction without a global 'slice' lookup or allocation guess."""
from __future__ import annotations

import ast
import dis
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _Unsupported
from scar.analysis.source_heap_lowering import _hold
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.model import AccessMode, Behavior, ExitKind, Operation, OperationResult, ReferenceValue, StateAccess
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource, SliceShape
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.state_addresses import AddressEffect, Element, ReferenceOwner


def _constant_slice(node):
    return isinstance(node, ast.Slice) and all(child is None or isinstance(child, ast.Constant)
                                               for child in (node.lower, node.upper, node.step))


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _instructions(builder, node):
    evidence = builder.language_options.code_evidence
    if evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION, node, "SLICE_CODE_WITNESS_REQUIRED")
    if not hasattr(builder, "language_instructions"):
        builder.language_instructions = tuple(dis.get_instructions(evidence.code))
    return tuple(instruction for instruction in builder.language_instructions
                 if tuple(instruction.positions) == _span(node))


def _constant(builder, node, cursor):
    matches = [row for row in _instructions(builder, node) if row.opname == "LOAD_CONST"
               and type(row.arg) is int and type(row.argval) in (slice, tuple)]
    if len(matches) != 1:
        raise _Unsupported(GapKind.CODE_VERSION, node,
                           "source key has no unique exact LOAD_CONST position in its CodeWitness")
    instruction, = matches
    evidence = builder.language_options.code_evidence
    if evidence.code.co_consts[instruction.arg] is not instruction.argval:
        raise _Unsupported(GapKind.CODE_VERSION, node, "code constant slot differs from disassembly")
    operation_id = builder.fresh(OperationID, "code-constant-reference")
    before = builder.use(operation_id, cursor.state, node, "code-constant-world", 0)
    result = ReferenceValue(builder.fresh(ValueID, "code-constant-reference"), builder.function_context,
                            OperationResult(operation_id, 0))
    builder.add_value(result); builder.link_value(result, node, SourceRole.EXPRESSION)
    operation = Operation(operation_id, "code constant reference", (Behavior.READ,), (before,),
        (result.id,), (StateAccess(builder.world, before.id, AccessMode.READ),), effects_complete=False)
    builder.emit(cursor, operation, node, SourceRole.EXPRESSION)
    builder.protocol(operation_id, PythonProtocolKind.READ_CODE_CONSTANT, node)
    builder.language_constants.append(CodeConstantSource(operation_id, builder.source(node),
        evidence.captured.key, (instruction.arg,)))
    builder.gap(GapKind.CODE_VERSION, node,
        "code constant slot is witnessed; active CodeType/constant object instance identity remains unproved")
    return cursor, result.id


def _invoke(builder, cursor, node, inputs, consumed, *, old=None, kind=None, memory=False):
    def failed(failure, exception):
        pending = tuple(builder.active_temporaries)
        try:
            _transfer(builder, consumed, node)
            builder.finish_exit(failure, node, exception, ExitKind.RAISE)
        finally:
            builder.active_temporaries[:] = pending
    cursor, value, operation = builder.invoke(cursor, node, tuple(inputs), old=old,
                                             failure_handler=failed)
    if kind is not None:
        builder.protocol(operation, kind, node)
    if memory:
        original = builder.operation_records[operation]
        marked = replace(original, behaviors=original.behaviors + (Behavior.MEMORY,))
        builder.operations[builder.operations.index(original)] = marked
        builder.operation_records[operation] = marked
    _transfer(builder, consumed, node)
    return cursor, value, operation


def lower_slice(builder, node, cursor):
    if not isinstance(node, ast.Slice):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected exact Slice source")
    if _constant_slice(node):
        return _constant(builder, node, cursor)
    instructions = _instructions(builder, node)
    count = 3 if node.step is not None else 2
    if not any(row.opname == "BUILD_SLICE" and row.arg == count for row in instructions):
        raise _Unsupported(GapKind.CODE_VERSION, node, "COMBINED_SLICE_LIFETIME_UNRECOVERED")
    baseline = len(builder.active_temporaries)
    held, inputs = [], []
    try:
        for index, (role, child) in enumerate((('slice-lower', node.lower), ('slice-upper', node.upper),
                                              ('slice-step', node.step))[:count]):
            cursor, value = (builder.expr(child, cursor) if child is not None
                             else (cursor, builder.literal(node, None)))
            if cursor is None:
                return None, None
            origin = child or node
            _hold(builder, cursor, origin, value)
            held.append((origin, value))
            inputs.append((value, origin, role, index, None))
        cursor, value, operation = _invoke(builder, cursor, node, inputs, tuple(held),
            kind=PythonProtocolKind.BUILD_SLICE, memory=True)
        builder.language_slices.append(SliceShape(operation, builder.source(node),
            builder.source(node.lower) if node.lower is not None else None,
            builder.source(node.upper) if node.upper is not None else None,
            builder.source(node.step) if node.step is not None else None))
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "slice syntax bounds/order are connected; allocation, identity, lifetime and consumer dispatch remain unproved")
        return cursor, value
    finally:
        del builder.active_temporaries[baseline:]


def lower_key(builder, node, cursor):
    if isinstance(node, ast.Slice):
        return lower_slice(builder, node, cursor)
    if not isinstance(node, ast.Tuple):
        return builder.expr(node, cursor)
    if any(isinstance(child, ast.Starred) for child in node.elts):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "starred index key requires a separate construction rule")
    instructions = _instructions(builder, node)
    if any(row.opname == 'LOAD_CONST' and type(row.argval) is tuple for row in instructions):
        return _constant(builder, node, cursor)
    if not any(row.opname == 'BUILD_TUPLE' and row.arg == len(node.elts) for row in instructions):
        raise _Unsupported(GapKind.CODE_VERSION, node, "INDEX_TUPLE_CODE_LOWERING_UNRECOVERED")
    old = builder.old_operation(node)
    if len(old.operands) != len(node.elts):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "index tuple operands differ from original source semantics")
    baseline, held, inputs = len(builder.active_temporaries), [], []
    try:
        for child, operand in zip(node.elts, old.operands):
            cursor, value = lower_key(builder, child, cursor)
            if cursor is None:
                return None, None
            _hold(builder, cursor, child, value); held.append((child, value))
            inputs.append((value, child, operand.role, operand.index, operand.value))
        cursor, value, _ = _invoke(builder, cursor, node, inputs, tuple(held), old=old, memory=True)
        return cursor, value
    finally:
        del builder.active_temporaries[baseline:]


def lower_subscript(builder, node, cursor):
    if not isinstance(node, ast.Subscript) or not isinstance(node.ctx, ast.Load):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "subscript read requires Load context")
    if (isinstance(node.slice, ast.Slice) and not _constant_slice(node.slice)
            and node.slice.step is None):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "COMBINED_SLICE_LIFETIME_UNRECOVERED")
    old = builder.old_operation(node)
    if len(old.operands) != 2:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "subscript source operands differ")
    baseline, held, inputs = len(builder.active_temporaries), [], []
    try:
        cursor, receiver = builder.expr(node.value, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.value, receiver); held.append((node.value, receiver))
        cursor, key = lower_key(builder, node.slice, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.slice, key); held.append((node.slice, key))
        for value, child, operand in zip((receiver, key), (node.value, node.slice), old.operands):
            inputs.append((value, child, operand.role, operand.index, operand.value))
        cursor, result, operation = _invoke(builder, cursor, node, inputs, tuple(held), old=old)
        uses = builder.operation_records[operation].uses
        builder._addresses(operation, (AddressEffect(ReferenceOwner(uses[0].id),
            (Element(uses[1].id),), AccessMode.READ),))
        builder.gap(GapKind.DYNAMIC_DISPATCH, node,
            "subscription key/order are connected; consumer dispatch, mutation, aliasing and resources remain unproved")
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


__all__ = ["lower_slice", "lower_key", "lower_subscript"]

"""Slice/key construction without a global 'slice' lookup or allocation guess."""
from __future__ import annotations

import ast
import dis
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _Unsupported
from scar.analysis.source_heap_lowering import _hold, _source_definition, _associate, expression_for_heap_target
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.model import AccessMode, Behavior, ExitKind, Operation, OperationResult, ReferenceValue, StateAccess
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource, SliceShape
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind
from scar.ir.program.state_addresses import AddressEffect, Element, ReferenceOwner, Slice


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
        evidence.code_layout_key, (instruction.arg,)))
    builder.gap(GapKind.CODE_VERSION, node,
        "code constant slot is witnessed; active CodeType/constant object instance identity remains unproved")
    return cursor, result.id


def _invoke(builder, cursor, node, inputs, normal_consumed, *, raise_consumed=None,
            old=None, kind=None, memory=False, result_type=_REF, role=SourceRole.EXPRESSION):
    # Most existing slice/index primitives consume the same input holds in both
    # completions. BUILD_TUPLE steals only on success (CPython 3.14.7). Keeping
    # the exceptional contract explicit avoids a second release before unwind.
    if raise_consumed is None:
        raise_consumed = normal_consumed
    def failed(failure, exception):
        pending = tuple(builder.active_temporaries)
        try:
            _transfer(builder, raise_consumed, node)
            builder.finish_exit(failure, node, exception, ExitKind.RAISE)
        finally:
            builder.active_temporaries[:] = pending
    cursor, value, operation = builder.invoke(cursor, node, tuple(inputs), old=old,
        failure_handler=failed, result_type=result_type, role=role)
    if kind is not None:
        builder.protocol(operation, kind, node)
    if memory:
        original = builder.operation_records[operation]
        marked = replace(original, behaviors=original.behaviors + (Behavior.MEMORY,))
        builder.operations[builder.operations.index(original)] = marked
        builder.operation_records[operation] = marked
    _transfer(builder, normal_consumed, node)
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
            if child is None:
                cursor, value = cursor, builder.literal(node, None)
            elif builder.has_language('SLICE_ACCESS_314_V1'):
                cursor, value = expression_for_heap_target(builder, child, cursor)
            else:
                cursor, value = builder.expr(child, cursor)
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
        return (expression_for_heap_target(builder, node, cursor)
                if builder.has_language('SLICE_ACCESS_314_V1') else builder.expr(node, cursor))
    if any(isinstance(child, ast.Starred) for child in node.elts):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "starred index key requires a separate construction rule")
    instructions = _instructions(builder, node)
    if any(row.opname == 'LOAD_CONST' and type(row.argval) is tuple for row in instructions):
        return _constant(builder, node, cursor)
    if sum(row.opname == 'BUILD_TUPLE' and row.arg == len(node.elts) for row in instructions) != 1:
        raise _Unsupported(GapKind.CODE_VERSION, node, "INDEX_TUPLE_CODE_LOWERING_UNRECOVERED")
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           "index tuple has ambiguous computational source records")
    old, definition = (records[0], None) if records else (None, _source_definition(builder, node))
    if old is not None:
        if old.opcode is not Opcode.BUILD_TUPLE or len(old.operands) != len(node.elts):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                               "index tuple operands differ from original source semantics")
        operands = tuple((row.role, row.index, row.value) for row in old.operands)
    else:
        if (definition.kind is not OperationKind.OPERATOR or definition.metadata.get("ast_type") != "Tuple"
                or len(definition.output_slots) != 1):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                               "index tuple requires its unique original SG Tuple/output slot")
        operands = tuple(("element", index, None) for index in range(len(node.elts)))
    baseline, held, inputs = len(builder.active_temporaries), [], []
    try:
        for child, (role, index, static) in zip(node.elts, operands):
            cursor, value = expression_for_heap_target(builder, child, cursor)
            if cursor is None:
                return None, None
            _hold(builder, cursor, child, value); held.append((child, value))
            inputs.append((value, child, role, index, static))
        cursor, value, operation = _invoke(builder, cursor, node, inputs, tuple(held),
            raise_consumed=(), old=old, memory=True)
        if definition is not None:
            _associate(builder, operation, node, definition, Opcode.BUILD_TUPLE)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "tuple key inputs transfer only on normal completion; modeled pending references are checked separately; "
            "runtime code instance, finalizers, allocation and complete lifetime effects remain unproved")
        return cursor, value
    finally:
        del builder.active_temporaries[baseline:]


def lower_subscript(builder, node, cursor):
    if not isinstance(node, ast.Subscript) or not isinstance(node.ctx, ast.Load):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "subscript read requires Load context")
    expanded = builder.has_language("SLICE_ACCESS_314_V1")
    if (expanded and isinstance(node.slice, ast.Slice)
            and any(row.opname == 'BINARY_SLICE' for row in _instructions(builder, node))):
        return _combined_read(builder, node, cursor)
    if (not expanded and isinstance(node.slice, ast.Slice) and not _constant_slice(node.slice)
            and node.slice.step is None):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "COMBINED_SLICE_LIFETIME_UNRECOVERED")
    old, definition = _index_source(builder, node) if expanded else (builder.old_operation(node), None)
    if old is not None and len(old.operands) != 2:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "subscript source operands differ")
    baseline, held, inputs = len(builder.active_temporaries), [], []
    try:
        cursor, receiver = expression_for_heap_target(builder, node.value, cursor) if expanded else builder.expr(node.value, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.value, receiver); held.append((node.value, receiver))
        cursor, key = lower_key(builder, node.slice, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.slice, key); held.append((node.slice, key))
        for index, (value, child, role) in enumerate(((receiver, node.value, 'receiver'), (key, node.slice, 'index'))):
            operand = old.operands[index] if old is not None else None
            inputs.append((value, child, operand.role if operand else role,
                           operand.index if operand else index, operand.value if operand else None))
        cursor, result, operation = _invoke(builder, cursor, node, inputs, tuple(held), old=old)
        if definition is not None:
            _associate(builder, operation, node, definition, Opcode.INDEX)
        uses = builder.operation_records[operation].uses
        builder._addresses(operation, (AddressEffect(ReferenceOwner(uses[0].id),
            (Element(uses[1].id),), AccessMode.READ),))
        builder.gap(GapKind.DYNAMIC_DISPATCH, node,
            "subscription key/order are connected; consumer dispatch, mutation, aliasing and resources remain unproved")
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


def _index_source(builder, node):
    """Original SG ownership, with an optional existing computational overlay."""
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'slice index has ambiguous computational records')
    definition = _source_definition(builder, node)
    if definition.kind is not OperationKind.INDEX or len(definition.output_slots) != 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'slice read requires its exact original SG INDEX/output')
    if records:
        old, = records
        if old.operation != definition.id or old.opcode is not Opcode.INDEX or len(old.operands) != 2:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'slice read differs from original SG index operands')
        return old, None
    return None, definition


def _bound_inputs(builder, node, cursor, held):
    """Evaluate only existing lower/upper children; omissions are exact None."""
    inputs = []
    for index, (role, child) in enumerate((('slice-lower', node.slice.lower), ('slice-upper', node.slice.upper))):
        origin = child or node.slice
        cursor, value = (expression_for_heap_target(builder, child, cursor) if child is not None
                         else (cursor, builder.literal(node.slice, None)))
        if cursor is None:
            return None, None
        _hold(builder, cursor, origin, value); held.append((origin, value))
        # A bound is not the old whole-key StaticValue. Its source and core Use
        # suffice until a real SG value for this exact child is available.
        inputs.append((value, origin, role, index, None))
    return cursor, inputs


def _combined_read(builder, node, cursor):
    if node.slice.step is not None or sum(row.opname == 'BINARY_SLICE' for row in _instructions(builder, node)) != 1:
        raise _Unsupported(GapKind.CODE_VERSION, node, 'slice read has no unique exact BINARY_SLICE witness')
    old, definition = _index_source(builder, node)
    baseline, held = len(builder.active_temporaries), []
    try:
        cursor, receiver = expression_for_heap_target(builder, node.value, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.value, receiver); held.append((node.value, receiver))
        cursor, bounds = _bound_inputs(builder, node, cursor, held)
        if cursor is None:
            return None, None
        inputs = [(receiver, node.value, 'receiver', 0, old.operands[0].value if old is not None else None), *bounds]
        cursor, result, operation = _invoke(builder, cursor, node, inputs, tuple(held),
            old=old, kind=PythonProtocolKind.BINARY_SLICE)
        if definition is not None:
            _associate(builder, operation, node, definition, Opcode.INDEX)
        uses = builder.operation_records[operation].uses
        builder._addresses(operation, (AddressEffect(ReferenceOwner(uses[0].id),
            (Slice(uses[1].id, uses[2].id),), AccessMode.READ),))
        builder.link_value(builder.values_by_id[result], node, SourceRole.EXPRESSION,
                           semantic_value=old.result if old is not None else None)
        builder.gap(GapKind.DYNAMIC_DISPATCH, node,
            'compound slice receiver/bounds/world and consuming completions are connected; '
            'internal temporary slice, dispatch, aliasing and complete effects remain unproved')
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


def lower_slice_store(builder, node, rhs, cursor, *, rhs_held=False):
    """CPython slice assignment: RHS, receiver, bounds/key, consuming store."""
    if not isinstance(node, ast.Subscript) or not isinstance(node.ctx, ast.Store):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'slice store requires original Subscript Store')
    combined = isinstance(node.slice, ast.Slice) and any(row.opname == 'STORE_SLICE' for row in _instructions(builder, node))
    expected = 'STORE_SLICE' if combined else 'STORE_SUBSCR'
    if sum(row.opname == expected for row in _instructions(builder, node)) != 1:
        raise _Unsupported(GapKind.CODE_VERSION, node, 'slice assignment has no unique exact consuming compiler operation')
    if combined and node.slice.step is not None:
        raise _Unsupported(GapKind.CODE_VERSION, node, 'STORE_SLICE cannot have a step')
    definition = _source_definition(builder, node, binding=True)
    if rhs_held and (not builder.active_temporaries or builder.active_temporaries[-1] != rhs):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'slice store lost original pending unpack result')
    baseline = len(builder.active_temporaries) - int(rhs_held)
    held = [(node, rhs)]
    try:
        if not rhs_held:
            _hold(builder, cursor, node, rhs)
        cursor, receiver = expression_for_heap_target(builder, node.value, cursor)
        if cursor is None:
            return None
        _hold(builder, cursor, node.value, receiver); held.append((node.value, receiver))
        inputs = [(rhs, node, 'assigned-reference', 0, None), (receiver, node.value, 'heap-owner', 0, None)]
        if combined:
            cursor, bounds = _bound_inputs(builder, node, cursor, held)
            if cursor is None:
                return None
            inputs.extend(bounds)
            kind = PythonProtocolKind.STORE_SLICE
        else:
            cursor, key = lower_key(builder, node.slice, cursor)
            if cursor is None:
                return None
            _hold(builder, cursor, node.slice, key); held.append((node.slice, key))
            inputs.append((key, node.slice, 'element-key', 0, None))
            kind = PythonProtocolKind.STORE_SLICE_SUBSCRIPT
        cursor, _, operation = _invoke(builder, cursor, node, inputs, tuple(held), kind=kind,
            result_type=None, role=SourceRole.LOCAL_BINDING)
        _associate(builder, operation, node, definition, Opcode.OPAQUE)
        uses = builder.operation_records[operation].uses
        selector = Slice(uses[2].id, uses[3].id) if combined else Element(uses[2].id)
        builder._addresses(operation, (AddressEffect(ReferenceOwner(uses[1].id), (selector,), AccessMode.WRITE),))
        builder.gap(GapKind.DYNAMIC_DISPATCH, node,
            'slice assignment retains RHS-first evaluation, original receiver/bounds/key Uses, '
            'world and consuming normal/raise outcomes; runtime dispatch and complete effects remain unproved')
        return cursor
    finally:
        del builder.active_temporaries[baseline:]


__all__ = ["lower_slice", "lower_key", "lower_subscript", "lower_slice_store"]

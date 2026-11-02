"""SG-backed expression ports absent from the historical computational overlay.

The source operator selector is an explicit literal Use, not a guessed callee.
The real operands retain their SG/source identities. Python rich comparisons
produce references; truth conversion is a separate potentially raising action.

Reference consumption follows CPython v3.14.7 Python/bytecodes.c: _BINARY_OP
retains its operands on failure (ERROR_NO_POP); _COMPARE_OP and _CONTAINS_OP
consume both before testing failure. No target code is executed here.
"""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_heap_lowering import _source_definition, _associate, _hold
from scar.analysis.source_slice_lowering import _invoke
from scar.ir.program.ids import ValueID
from scar.ir.program.model import DataValue, LiteralOrigin, ReferenceValue
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind


BINARY_OPCODES = {
    'Add': Opcode.ADD, 'Sub': Opcode.SUB, 'Mult': Opcode.MUL,
    'Div': Opcode.TRUE_DIV, 'FloorDiv': Opcode.FLOOR_DIV, 'Mod': Opcode.MOD,
    'Pow': Opcode.POW, 'LShift': Opcode.LSHIFT, 'RShift': Opcode.RSHIFT,
    'BitAnd': Opcode.BIT_AND, 'BitOr': Opcode.BIT_OR, 'BitXor': Opcode.BIT_XOR,
    'MatMult': Opcode.OPAQUE,
}
COMPARE_OPERATORS = frozenset(('Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE',
                               'Is', 'IsNot', 'In', 'NotIn'))


def forward_source_reference(builder, cursor, node, reference):
    """Transfer a helper's existing result hold to its expression consumer.

    This is a reference-ownership boundary, not a decref, allocation or Python
    call. Input primitives' consumption remains their own separate contract.
    Historical profiles retain their original construction unchanged.
    """
    if builder.has_language('SOURCE_REFERENCE_LIFETIME_314_V1'):
        builder.frame_transition(cursor, node,
            ((reference, node, 'forwarded-expression-reference'),), K.FRAME_FORWARD_TEMPORARY)


def source_operator(node):
    if isinstance(node, ast.BinOp) and type(node.op).__name__ in BINARY_OPCODES:
        return type(node.op).__name__
    if (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
            and type(node.ops[0]).__name__ in COMPARE_OPERATORS):
        return type(node.ops[0]).__name__
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                       'SOURCE_EXPRESSION_OPERATOR_OR_CHAIN_UNIMPLEMENTED')


def lower_source_literal(builder, node, cursor, *, definition=None):
    definition = definition or _source_definition(builder, node)
    if not isinstance(node, ast.Constant) or definition.kind is not OperationKind.CONSTANT:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           'source literal requires its original SG Constant')
    try:
        origin = LiteralOrigin(node.value)
    except (TypeError, ValueError) as error:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           'source literal requires code-table constant support: ' + str(error)) from error
    value = ReferenceValue(builder.fresh(ValueID, 'source-literal'), builder.function_context,
                           origin, targets=())
    builder.add_value(value)
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1 or records and records[0].operation != definition.id:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           'source literal computational record differs from its exact SG definition')
    builder.link_value(value, node, SourceRole.EXPRESSION,
                       semantic_value=records[0].result if records else None)
    return cursor, value.id


def lower_source_expression(builder, node, cursor, *, evaluate=None, definition=None):
    """One binary or single comparison, with real ordered operands and world."""
    selector = source_operator(node)
    definition = definition or _source_definition(builder, node)
    if (definition.kind is not OperationKind.OPERATOR
            or definition.metadata.get('ast_type') != type(node).__name__
            or len(definition.output_slots) != 1):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           'source expression requires its original SG operator/output')
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1 or records and records[0].operation != definition.id:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           'source expression computational record differs from its exact SG definition')
    old = records[0] if records else None
    if evaluate is None:
        from scar.analysis.source_heap_lowering import expression_for_heap_target
        evaluate = lambda child, at: expression_for_heap_target(builder, child, at,
                                                               parent_definition=definition)
    children = (node.left, node.right if isinstance(node, ast.BinOp) else node.comparators[0])
    baseline, held, inputs = len(builder.active_temporaries), [], []
    try:
        for index, (child, role) in enumerate(zip(children, ('left', 'right'))):
            # This is a source port check, independent of the old overlay.
            _source_definition(builder, child, parent=definition)
            cursor, value = evaluate(child, cursor)
            if cursor is None:
                return None, None
            _hold(builder, cursor, child, value)
            held.append((child, value))
            static = old.operands[index].value if old is not None and len(old.operands) == 2 else None
            inputs.append((value, child, role, index, static))
        # A static protocol selector is DATA, not a Python str allocation or
        # evaluation-stack reference belonging to the analyzed program.
        tag = DataValue(builder.fresh(ValueID, 'source-operator'), builder.function_context,
                        LiteralOrigin(selector), 'builtins.str')
        builder.add_value(tag); builder.link_value(tag, node, SourceRole.CONTROL)
        inputs.append((tag.id, node, 'source-operator', 0, None))
        binary = isinstance(node, ast.BinOp)
        cursor, result, identity = _invoke(builder, cursor, node, inputs, tuple(held),
            raise_consumed=() if binary else tuple(held),
            kind=K.SOURCE_BINARY if binary else K.SOURCE_COMPARE)
        opcode = BINARY_OPCODES[selector] if binary else (
            Opcode.IS if selector == 'Is' else Opcode.IS_NOT if selector == 'IsNot' else Opcode.OPAQUE)
        _associate(builder, identity, node, definition, opcode)
        builder.link_value(builder.values_by_id[result], node, SourceRole.EXPRESSION,
                           semantic_value=old.result if old is not None else None)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            'source operator and ordered reference/world completions are connected; operand finalizers, '
            'dispatch and complete effects remain unproved' if selector not in ('Is', 'IsNot') else
            'identity comparison has no user comparison dispatch; operand evaluation/finalizers and world effects remain distinct')
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


__all__ = ['BINARY_OPCODES', 'COMPARE_OPERATORS', 'source_operator',
           'lower_source_literal', 'lower_source_expression']

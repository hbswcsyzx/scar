"""CPython 3.14 f-string construction over existing canonical CFG/world.

An interpolation evaluates its value, performs !s/!r/!a conversion, evaluates
its format specification, then formats.  Later pieces run only after that
finishes.  Nested specifications use exactly the same source rule.  Literal
pieces remain literals; zero/one-piece JoinedStr has no BUILD_STRING action.

Protocol contracts (all incomplete invokes with NORMAL(ref,world) and
RAISE(ref,world)):

* FSTRING_CONVERT(value, conversion): conversion is a source-generated exact
  integer literal, 115/114/97 for str/repr/ascii.  This is interpreter conversion,
  not a lookup of the globals named str/repr/ascii.
* FSTRING_FORMAT(value, spec): exact literal None denotes FORMAT_SIMPLE,
  including its exact-str forwarding path; an actual spec reference denotes
  FORMAT_WITH_SPEC, including an explicitly empty string.  Formatting may
  dispatch __format__ and must validate its result without a purity assumption.
* BUILD_STRING(parts...): two through thirty ordered formatted/literal pieces.
  More pieces select CPython's list/append/join path, which is explicitly
  unsupported here rather than moving intermediate allocation to the end.

Consumed input holds are released in both completions before propagation.
No target code, conversion, format method or tensor value is executed here.
Rules were checked with this interpreter's compile/dis and these primary
sources: CPython v3.14.0 Python/codegen.c (codegen_formatted_value,
codegen_joined_str) and Python/generated_cases.c.h (CONVERT_VALUE,
FORMAT_SIMPLE, FORMAT_WITH_SPEC, BUILD_STRING).
https://github.com/python/cpython/blob/v3.14.0/Python/codegen.c
https://github.com/python/cpython/blob/v3.14.0/Python/generated_cases.c.h
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _Unsupported
from scar.ir.program.model import Behavior, ExitKind
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind


_MAX_STACK_PIECES = 30
_CONVERSIONS = frozenset((115, 114, 97))


def _kind(name, node):
    kind = getattr(PythonProtocolKind, name, None)
    if kind is None:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           "source profile has not connected the " + name + " protocol")
    return kind


def _hold(builder, cursor, node, reference):
    builder.frame_transition(cursor, node, ((reference, node, "fstring-held-reference"),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _release(builder, cursor, held):
    for node, reference in reversed(held):
        if not builder.active_temporaries or builder.active_temporaries[-1] != reference:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "f-string temporary ownership is not nested")
        builder.active_temporaries.pop()
        builder.frame_transition(cursor, node, ((reference, node, "fstring-consumed-reference"),),
                                 PythonProtocolKind.FRAME_RELEASE_TEMPORARY)


def _invoke(builder, cursor, node, inputs, name, held):
    """Keep pending outer pieces; consume only this operation's input suffix."""
    def failed(failure, exception):
        pending = tuple(builder.active_temporaries)
        try:
            _release(builder, failure, held)
            builder.finish_exit(failure, node, exception, ExitKind.RAISE)
        finally:
            # Construction next visits the normal arm, which has its own
            # unconsumed input holds.  No runtime reference is retained here.
            builder.active_temporaries[:] = pending

    cursor, result, operation_id = builder.invoke_protocol(cursor, node, tuple(inputs),
        _kind(name, node), failure_handler=failed)
    operation = builder.operation_records[operation_id]
    # This marks possible allocation, including user format/conversion work;
    # it does not assert that every runtime path allocates a fresh string.
    marked = replace(operation, behaviors=operation.behaviors + (Behavior.MEMORY,))
    builder.operations[builder.operations.index(operation)] = marked
    builder.operation_records[operation_id] = marked
    _release(builder, cursor, held)
    return cursor, result


def _link_result(builder, node, reference):
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                           "f-string expression has ambiguous computational source records")
    builder.link_value(builder.values_by_id[reference], node, SourceRole.EXPRESSION,
                       semantic_value=records[0].result if records else None)


def _formatted_value(builder, node, cursor):
    if node.conversion != -1 and node.conversion not in _CONVERSIONS:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "unsupported f-string conversion code")
    initial_holds = len(builder.active_temporaries)
    try:
        cursor, value = builder.expr(node.value, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, node.value, value)
        if node.conversion != -1:
            conversion = builder.literal(node, node.conversion)
            cursor, value = _invoke(builder, cursor, node, (value, conversion),
                                    "FSTRING_CONVERT", ((node.value, value),))
            _hold(builder, cursor, node, value)
        held = [(node, value)]
        if node.format_spec is None:
            spec = builder.literal(node, None)
        else:
            if not isinstance(node.format_spec, ast.JoinedStr):
                raise _Unsupported(GapKind.SOURCE_MAPPING, node.format_spec,
                                   "f-string format specification must retain its JoinedStr source")
            cursor, spec = lower_joined_string(builder, node.format_spec, cursor)
            if cursor is None:
                return None, None
            _hold(builder, cursor, node.format_spec, spec)
            held.append((node.format_spec, spec))
        cursor, result = _invoke(builder, cursor, node, (value, spec), "FSTRING_FORMAT", tuple(held))
        _link_result(builder, node, result)
        return cursor, result
    finally:
        del builder.active_temporaries[initial_holds:]


def lower_joined_string(builder, node, cursor):
    """Construct ordinary f-strings; preserve every child and evaluation edge."""
    if not isinstance(node, ast.JoinedStr):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected JoinedStr source")
    if len(node.values) > _MAX_STACK_PIECES:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           "large f-string requires the compiler's incremental list/append/join protocol")
    if not node.values:
        result = builder.literal(node, "")
        _link_result(builder, node, result)
        return cursor, result
    initial_holds = len(builder.active_temporaries)
    pieces, held = [], []
    try:
        for child in node.values:
            if isinstance(child, ast.Constant) and type(child.value) is str:
                value = builder.literal(child, child.value)
            elif isinstance(child, ast.FormattedValue):
                cursor, value = _formatted_value(builder, child, cursor)
                if cursor is None:
                    return None, None
            else:
                raise _Unsupported(GapKind.SOURCE_MAPPING, child,
                                   "JoinedStr piece must be an exact string literal or FormattedValue")
            pieces.append(value)
            if len(node.values) > 1:
                _hold(builder, cursor, child, value)
                held.append((child, value))
        if len(pieces) == 1:
            result = pieces[0]
        else:
            cursor, result = _invoke(builder, cursor, node, pieces, "BUILD_STRING", tuple(held))
        _link_result(builder, node, result)
        return cursor, result
    finally:
        del builder.active_temporaries[initial_holds:]


def validate_string_protocols(model, graph, interface, metadata, semantic):
    from scar.ir.program.model import (CompletionResult, LiteralOrigin, ReferenceValue,
        StateVersionValue, TerminatorKind, ValueKind, ValueType)
    kinds = (PythonProtocolKind.FSTRING_CONVERT, PythonProtocolKind.FSTRING_FORMAT,
             PythonProtocolKind.BUILD_STRING)
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    links = {link.operation: link for link in metadata.operation_links}
    world_location = values[interface.world].location
    ref_type, state_type = ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world_location)
    for protocol in model.protocols:
        if protocol.kind not in kinds:
            continue
        operation, link = operations[protocol.operation], links[protocol.operation]
        atom = semantic.source_atoms.get(link.source.atom_id)
        expected = "JoinedStr" if protocol.kind is PythonProtocolKind.BUILD_STRING else "FormattedValue"
        arity = len(operation.uses) - 1
        arity_ok = 2 <= arity <= 30 if protocol.kind is PythonProtocolKind.BUILD_STRING else arity == 2
        if (atom is None or atom.kind != expected or link.semantic_operation is not None or not arity_ok
                or any(type(values[use.value]) is not ReferenceValue for use in operation.uses[:-1])
                or type(values[operation.uses[-1].value]) is not StateVersionValue
                or values[operation.uses[-1].value].location != world_location
                or operation.effects_complete or operation.callee is not None
                or Behavior.MEMORY not in operation.behaviors
                or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                or operation.invoke_arguments != tuple(use.id for use in operation.uses)):
            raise ValueError("string protocol must retain its exact source, ordered references and incomplete world invoke")
        if protocol.kind is PythonProtocolKind.FSTRING_CONVERT:
            origin = values[operation.uses[1].value].origin
            if type(origin) is not LiteralOrigin or type(origin.value) is not int or origin.value not in _CONVERSIONS:
                raise ValueError("f-string conversion must use its exact source-generated ASCII literal")
        if (tuple((signature.kind, signature.types) for signature in operation.completions) !=
                ((ExitKind.NORMAL, (ref_type, state_type)), (ExitKind.RAISE, (ref_type, state_type)))
                or tuple(edge.kind for edge in operation.terminator.successors) != (ExitKind.NORMAL, ExitKind.RAISE)
                or any(edge.arguments != (CompletionResult(0), CompletionResult(1))
                       for edge in operation.terminator.successors)):
            raise ValueError("string protocol must keep normal and exceptional payload/post-world")


__all__ = ["lower_joined_string", "validate_string_protocols"]

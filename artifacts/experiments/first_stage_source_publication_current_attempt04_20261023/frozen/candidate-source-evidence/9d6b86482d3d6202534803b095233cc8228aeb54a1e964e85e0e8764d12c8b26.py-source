"""Function-body AnnAssign, Assert and Raise over existing core control/state.

Rules follow CPython 3.14 Python/codegen.c (codegen_annassign,
codegen_check_ann_subscr, codegen_assert, Raise_kind) and Python/ceval.c
(do_raise).  The local compiler context is optimize=0.  This source model does
not claim correspondence to a live callable compiled with assertions removed.

All original AST nodes/source identities are retained.  Statement protocols
are synthetic semantic operations rather than invented runtime observations:

* MAKE_ASSERTION_ERROR: zero/one reference -> exception reference + world.
  It constructs the interpreter's AssertionError, independent of a Python
  binding named AssertionError.  Construction failure is a separate RAISE.
* RERAISE: no reference -> current handled exception + world; absent context
  raises RuntimeError.  Its contract preserves re-raise traceback semantics.
* RAISE_EXCEPTION: exception reference -> normalized exception + world.
* RAISE_WITH_CAUSE: exception, cause -> normalized exception + world, including
  explicit None cause/context suppression.  Class instantiation, validation,
  cause assignment and exception-context effects belong to this protocol.

For all four, the protocol's NORMAL means normalization/construction succeeded,
not that the source raise/assert-failure falls through.  Its RAISE completion
is the exception produced while performing that work.  Both carry the existing
coarse world, which includes thread exception context; no input reference is
presumed to be a BaseException.  No effect-completeness claim is made.

Primary references:
https://github.com/python/cpython/blob/v3.14.0/Python/codegen.c
https://github.com/python/cpython/blob/v3.14.0/Python/ceval.c
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _Unsupported
from scar.ir.program.model import Behavior, ExitKind
from scar.ir.program.source import GapKind
from scar.ir.program.structured import PythonProtocolKind


def _kind(name, node):
    kind = getattr(PythonProtocolKind, name, None)
    if kind is None:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           "source profile has not connected the " + name + " protocol")
    return kind


def _hold(builder, cursor, node, reference):
    builder.frame_transition(cursor, node, ((reference, node, "statement-held-reference"),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _release(builder, cursor, node, reference):
    if not builder.active_temporaries or builder.active_temporaries[-1] != reference:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "statement temporary ownership is not nested")
    builder.active_temporaries.pop()
    builder.frame_transition(cursor, node, ((reference, node, "statement-released-reference"),),
                             PythonProtocolKind.FRAME_RELEASE_TEMPORARY)


def _discard_expression(builder, node, cursor):
    # Annotation-only complex targets lack some old computational overlays.
    # The existing recovery helper handles exact SG-backed Name/Constant
    # leaves; all other absent overlays remain explicit coverage boundaries.
    from scar.analysis.source_heap_lowering import expression_for_heap_target
    cursor, value = expression_for_heap_target(builder, node, cursor)
    if cursor is not None:
        builder.frame_transition(cursor, node, ((value, node, "annotation-target-discard"),),
                                 PythonProtocolKind.FRAME_DISCARD)
    return cursor


def _annotation_subscript(builder, node, cursor):
    if isinstance(node, ast.Slice):
        # Bounds are full expressions.  A tuple-valued bound must retain its
        # real tuple construction; only the index's extended-slice Tuple is
        # recursively checked without materialization by CPython codegen.
        for child in (node.lower, node.upper, node.step):
            if child is not None and cursor is not None:
                cursor = _discard_expression(builder, child, cursor)
        return cursor
    elif isinstance(node, ast.Tuple):
        children = node.elts
    elif isinstance(node, ast.Starred):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           "annotation-only starred index requires its compiler evaluation rule")
    else:
        return _discard_expression(builder, node, cursor)
    for child in children:
        if cursor is None:
            break
        cursor = _annotation_subscript(builder, child, cursor)
    return cursor


def annotated_assignment(builder, node, cursor):
    """Evaluate RHS/store, or only complex-target checks; never the annotation.

    In a function a bare name annotation changes compiler-local classification
    but performs no binding at runtime.  With no assigned value, Attribute
    evaluates/discards only its receiver; Subscript then evaluates/discards
    each index or slice bound independently, without getitem/building a tuple
    or slice.  These function rules do not apply to module/class annotations.
    """
    if not isinstance(node, ast.AnnAssign):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected annotated assignment source")
    if node.value is not None:
        cursor, value = builder.expr(node.value, cursor)
        return builder.store(node.target, value, cursor) if cursor is not None else None
    target = node.target
    if isinstance(target, ast.Name):
        return cursor
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        cursor = _discard_expression(builder, target.value, cursor)
        if cursor is not None and isinstance(target, ast.Subscript):
            cursor = _annotation_subscript(builder, target.slice, cursor)
        return cursor
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target,
                       "annotation target requires Name, Attribute or Subscript")


def raise_statement(builder, node, cursor):
    """Evaluate exception then cause; normalize both before the RAISE exit."""
    if not isinstance(node, ast.Raise):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected raise source")
    initial_holds = len(builder.active_temporaries)
    held, operands = [], []
    try:
        if node.exc is None:
            if node.cause is not None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, node, "bare raise cannot have an explicit cause")
            name = "RERAISE"
        else:
            cursor, exception = builder.expr(node.exc, cursor)
            if cursor is None:
                return None
            _hold(builder, cursor, node.exc, exception)
            held.append((node.exc, exception)); operands.append(exception)
            name = "RAISE_EXCEPTION"
            if node.cause is not None:
                cursor, cause = builder.expr(node.cause, cursor)
                if cursor is None:
                    return None
                _hold(builder, cursor, node.cause, cause)
                held.append((node.cause, cause)); operands.append(cause)
                name = "RAISE_WITH_CAUSE"
        cursor, normalized, _ = builder.invoke_protocol(cursor, node, tuple(operands), _kind(name, node))
        for child, reference in reversed(held):
            _release(builder, cursor, child, reference)
        builder.finish_exit(cursor, node, normalized, ExitKind.RAISE)
        return None
    finally:
        # Failure edges already captured their pending inputs in FRAME_EXIT.
        # Do not retain branch-local references while constructing another arm.
        del builder.active_temporaries[initial_holds:]


def assert_statement(builder, node, cursor):
    """Predicate once; construct the assertion error only on the false arm."""
    if not isinstance(node, ast.Assert):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected assert source")
    cursor, boolean = builder.condition(node.test, cursor)
    if cursor is None:
        return None
    succeeded, failed = builder.new_block(node), builder.new_block(node)
    builder.branch(cursor, boolean, succeeded, failed, node)
    initial_holds = len(builder.active_temporaries)
    message = None
    try:
        if node.msg is not None:
            failed, message = builder.expr(node.msg, failed)
            if failed is None:
                return succeeded
            _hold(builder, failed, node.msg, message)
        failed, exception, operation_id = builder.invoke_protocol(failed, node,
            () if node.msg is None else (message,), _kind("MAKE_ASSERTION_ERROR", node))
        operation = builder.operation_records[operation_id]
        marked = replace(operation, behaviors=operation.behaviors + (Behavior.MEMORY,))
        builder.operations[builder.operations.index(operation)] = marked
        builder.operation_records[operation_id] = marked
        if node.msg is not None:
            _release(builder, failed, node.msg, message)
        builder.finish_exit(failed, node, exception, ExitKind.RAISE)
    finally:
        del builder.active_temporaries[initial_holds:]
    return succeeded


def validate_statement_protocols(model, graph, interface, metadata, semantic):
    """Validate language protocol ports; exact evaluation source is replayed."""
    from scar.ir.program.model import (CompletionResult, ReferenceValue, StateVersionValue,
        TerminatorKind, ValueKind, ValueType)
    arities = {
        PythonProtocolKind.MAKE_ASSERTION_ERROR: (0, 1),
        PythonProtocolKind.RERAISE: (0,),
        PythonProtocolKind.RAISE_EXCEPTION: (1,),
        PythonProtocolKind.RAISE_WITH_CAUSE: (2,),
    }
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    links = {link.operation: link for link in metadata.operation_links}
    ref_type = ValueType(ValueKind.REFERENCE)
    location = values[interface.world].location
    state_type = ValueType(ValueKind.STATE, location=location)
    for protocol in model.protocols:
        if protocol.kind not in arities:
            continue
        operation, link = operations[protocol.operation], links[protocol.operation]
        expected = "Assert" if protocol.kind is PythonProtocolKind.MAKE_ASSERTION_ERROR else "Raise"
        atom = semantic.source_atoms.get(link.source.atom_id)
        if (atom is None or atom.kind != expected or link.semantic_operation is not None
                or len(operation.uses) - 1 not in arities[protocol.kind]
                or any(type(values[use.value]) is not ReferenceValue for use in operation.uses[:-1])
                or type(values[operation.uses[-1].value]) is not StateVersionValue
                or values[operation.uses[-1].value].location != location
                or operation.effects_complete or operation.callee is not None
                or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                or operation.invoke_arguments != tuple(use.id for use in operation.uses)):
            raise ValueError("statement protocol source, ordered references or world differ")
        if (tuple((signature.kind, signature.types) for signature in operation.completions) !=
                ((ExitKind.NORMAL, (ref_type, state_type)), (ExitKind.RAISE, (ref_type, state_type)))
                or tuple(edge.kind for edge in operation.terminator.successors) != (ExitKind.NORMAL, ExitKind.RAISE)
                or any(edge.arguments != (CompletionResult(0), CompletionResult(1))
                       for edge in operation.terminator.successors)):
            raise ValueError("statement protocol must keep its own normal/raise post-world")
        if protocol.kind is PythonProtocolKind.MAKE_ASSERTION_ERROR and Behavior.MEMORY not in operation.behaviors:
            raise ValueError("assertion error construction must record allocation behavior")


__all__ = ["annotated_assignment", "raise_statement", "assert_statement", "validate_statement_protocols"]

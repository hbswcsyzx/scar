"""CPython 3.14 dictionary displays over the existing CFG and coarse world.

BUILD_MAP consumes ordered key/value references and returns an exact dict;
MAP_ADD consumes key/value, retaining its exact-dict receiver; DICT_UPDATE
consumes the update reference, retaining its receiver.  Input consumption,
hash/equality dispatch, partial mutation and cleanup belong to each invoke's
normal/exceptional post-world.  They are not pure calls or global lookups.
DICT_UPDATE has dict-display overwrite semantics, not kwargs DICT_MERGE.

Small ordinary runs evaluate all pairs before construction.  Larger runs build
an empty dict before their first child, then insert after each pair.  Runs and
** updates follow codegen_dict/codegen_subdict, including the 30-slot compiler
guideline and its 17-pair flush.  A completed dict reference is forwarded to
its caller; it is never released and recreated at the expression boundary.

Primary implementation contracts (not live-code correspondence proof):
https://github.com/python/cpython/blob/v3.14.0/Python/codegen.c
https://github.com/python/cpython/blob/v3.14.0/Python/bytecodes.c
https://github.com/python/cpython/blob/v3.14.0/Include/internal/pycore_compile.h
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _Unsupported
from scar.ir.program.model import Behavior, ExitKind
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind


_STACK_GUIDELINE = 30


def _kind(name, node):
    result = getattr(PythonProtocolKind, name, None)
    if result is None:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           "source profile has not connected the " + name + " protocol")
    return result


def _hold(builder, cursor, node, reference):
    builder.frame_transition(cursor, node, ((reference, node, "mapping-held-reference"),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _transfer(builder, held, node):
    """Remove interpreter-consumed/forwarded holds, without a second decref."""
    references = tuple(reference for _, reference in held)
    if references:
        if tuple(builder.active_temporaries[-len(references):]) != references:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "dictionary temporary ownership is not nested")
        del builder.active_temporaries[-len(references):]


def _invoke(builder, cursor, node, inputs, name, consumed=()):
    def failed(failure, exception):
        pending = tuple(builder.active_temporaries)
        try:
            # The bytecode consumed these inputs before propagating its error.
            # Remaining operands belong to the enclosing evaluation stack.
            _transfer(builder, consumed, node)
            builder.finish_exit(failure, node, exception, ExitKind.RAISE)
        finally:
            builder.active_temporaries[:] = pending

    cursor, result, operation_id = builder.invoke(cursor, node, tuple(inputs),
        result_type=_REF if name == "BUILD_MAP" else None, failure_handler=failed)
    builder.protocol(operation_id, _kind(name, node), node)
    operation = builder.operation_records[operation_id]
    marked = replace(operation, behaviors=operation.behaviors + (Behavior.MEMORY,))
    builder.operations[builder.operations.index(operation)] = marked
    builder.operation_records[operation_id] = marked
    _transfer(builder, consumed, node)
    return cursor, result


def _empty(builder, node, cursor):
    cursor, result = _invoke(builder, cursor, node, (), "BUILD_MAP")
    _hold(builder, cursor, node, result)
    return cursor, result


def _run(builder, node, begin, end, cursor):
    """Return one held subdict, preserving the compiler's insertion boundary."""
    incremental = (end - begin) * 2 > _STACK_GUIDELINE
    result, held, inputs = None, [], []
    if incremental:
        cursor, result = _empty(builder, node, cursor)
    for index in range(begin, end):
        key_node, value_node = node.keys[index], node.values[index]
        if key_node is None:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "ordinary dictionary run contains unpacking")
        cursor, key = builder.expr(key_node, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, key_node, key)
        cursor, value = builder.expr(value_node, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, value_node, value)
        pair = ((key, key_node, "mapping-key", index, None),
                (value, value_node, "mapping-value", index, None))
        consumed = ((key_node, key), (value_node, value))
        if incremental:
            cursor, _ = _invoke(builder, cursor, node,
                ((result, node, "mapping-owner", 0, None),) + pair, "MAP_ADD", consumed)
        else:
            inputs.extend(pair)
            held.extend(consumed)
    if not incremental:
        cursor, result = _invoke(builder, cursor, node, inputs, "BUILD_MAP", tuple(held))
        _hold(builder, cursor, node, result)
    return cursor, result


def _update(builder, node, cursor, receiver, update, update_node):
    cursor, _ = _invoke(builder, cursor, node,
        ((receiver, node, "mapping-owner", 0, None),
         (update, update_node, "mapping-update", 0, None)),
        "DICT_UPDATE", ((update_node, update),))
    return cursor


def _append_run(builder, node, begin, end, cursor, receiver):
    cursor, subdict = _run(builder, node, begin, end, cursor)
    if cursor is None or receiver is None:
        return cursor, subdict
    return _update(builder, node, cursor, receiver, subdict, node), receiver


def lower_dictionary(builder, node, cursor):
    """Lower ast.Dict only, retaining original children and exact source atoms.

    Child expressions use the existing builder, so calls/names/state remain
    connected.  Dict comprehensions and unsupported child expressions retain
    their ordinary explicit coverage boundary.  No target is executed here.
    """
    if not isinstance(node, ast.Dict) or len(node.keys) != len(node.values):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expected a dictionary display source")
    initial_holds = len(builder.active_temporaries)
    receiver, elements = None, 0
    try:
        for index, key in enumerate(node.keys):
            if key is None:
                if elements:
                    cursor, receiver = _append_run(builder, node, index - elements, index, cursor, receiver)
                    if cursor is None:
                        return None, None
                    elements = 0
                if receiver is None:
                    cursor, receiver = _empty(builder, node, cursor)
                child = node.values[index]
                cursor, update = builder.expr(child, cursor)
                if cursor is None:
                    return None, None
                _hold(builder, cursor, child, update)
                cursor = _update(builder, node, cursor, receiver, update, child)
            elif elements * 2 > _STACK_GUIDELINE:
                cursor, receiver = _append_run(builder, node, index - elements, index + 1, cursor, receiver)
                if cursor is None:
                    return None, None
                elements = 0
            else:
                elements += 1
        if elements:
            cursor, receiver = _append_run(builder, node, len(node.keys) - elements,
                                            len(node.keys), cursor, receiver)
            if cursor is None:
                return None, None
        if receiver is None:
            cursor, receiver = _empty(builder, node, cursor)
        _transfer(builder, ((node, receiver),), node)
        records = builder.old_by_atom.get(builder.source(node).atom_id, ())
        if len(records) > 1:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "dictionary has ambiguous computational source records")
        builder.link_value(builder.values_by_id[receiver], node, SourceRole.EXPRESSION,
                           semantic_value=records[0].result if records else None)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "dictionary hash/equality, mapping dispatch, allocation, partial mutation and cleanup effects remain unproved")
        return cursor, receiver
    finally:
        del builder.active_temporaries[initial_holds:]


def validate_mapping_protocols(model, graph, interface, metadata, semantic, *, language=None):
    """Check dict protocol shapes; fixed-source replay owns exact child order."""
    from scar.ir.program.model import (CompletionResult, ReferenceValue, StateVersionValue,
        TerminatorKind, ValueKind, ValueType)
    from scar.analysis.source_language import function_exception_types
    kinds = (PythonProtocolKind.BUILD_MAP, PythonProtocolKind.MAP_ADD, PythonProtocolKind.DICT_UPDATE)
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    links = {link.operation: link for link in metadata.operation_links}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    built_maps = {}
    for protocol in model.protocols:
        if protocol.kind is PythonProtocolKind.BUILD_MAP:
            operation = operations[protocol.operation]
            if operation.terminator is not None:
                for edge in operation.terminator.successors:
                    block = blocks.get(edge.block)
                    if edge.kind is ExitKind.NORMAL and block is not None and block.arguments:
                        built_maps[block.arguments[0]] = links[protocol.operation].source
    location = values[interface.world].location
    ref_type, state_type = ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=location)
    for protocol in model.protocols:
        if protocol.kind not in kinds:
            continue
        operation, link = operations[protocol.operation], links[protocol.operation]
        atom = semantic.source_atoms.get(link.source.atom_id)
        if atom is not None and atom.kind == "Call":
            from scar.ir.program.source_language import SourceLanguageCapability
            if (language is None or SourceLanguageCapability.CALL_KWARGS_314_V1 not in language.capabilities
                    or protocol.kind is PythonProtocolKind.DICT_UPDATE):
                raise ValueError("call keyword packing requires its explicit capability and cannot use DICT_UPDATE")
            # The independent call validator owns the original Call, compiler,
            # receiver, ordered child Uses and both completion cleanup rules.
            continue
        arity = len(operation.uses) - 1
        build = protocol.kind is PythonProtocolKind.BUILD_MAP
        arity_ok = 0 <= arity <= _STACK_GUIDELINE and arity % 2 == 0 if build else (
            arity == (3 if protocol.kind is PythonProtocolKind.MAP_ADD else 2))
        if (atom is None or atom.kind != "Dict" or protocol.source != link.source
                or link.semantic_operation is not None or not arity_ok
                or any(type(values[use.value]) is not ReferenceValue for use in operation.uses[:-1])
                or not operation.uses or type(values[operation.uses[-1].value]) is not StateVersionValue
                or values[operation.uses[-1].value].location != location
                or operation.effects_complete or operation.callee is not None
                or not all(behavior in operation.behaviors for behavior in
                           (Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY))
                or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                or operation.invoke_arguments != tuple(use.id for use in operation.uses)):
            raise ValueError("dictionary protocol source, ordered references or incomplete world invoke differ")
        normal_types = (ref_type, state_type) if build else (state_type,)
        if (tuple((signature.kind, signature.types) for signature in operation.completions) !=
                ((ExitKind.NORMAL, normal_types), (ExitKind.RAISE, function_exception_types(language, ref_type, state_type)))
                or tuple(edge.kind for edge in operation.terminator.successors) != (ExitKind.NORMAL, ExitKind.RAISE)
                or any(edge.arguments != tuple(CompletionResult(index) for index in range(len(signature.types)))
                       for edge, signature in zip(operation.terminator.successors, operation.completions))):
            raise ValueError("dictionary protocol must retain its normal and exceptional payload/post-world")
        if not build and built_maps.get(operation.uses[0].value) != link.source:
            raise ValueError("dictionary mutation receiver must come from this display's exact BUILD_MAP result")


__all__ = ["lower_dictionary", "validate_mapping_protocols"]

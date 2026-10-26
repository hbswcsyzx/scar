"""Bounded heap-target construction over the existing environment builder.

This module belongs to the environment source profile and uses the builder's
``read_source_name(node, cursor, old=None)`` hook.  The hook uses the existing
local/cell/global rules, accepts absent legacy computational semantics, and
must never invent a StaticValue or treat a free cell as a global name.

The RHS has already been evaluated by the caller.  The rules below preserve
RHS -> receiver -> index -> store evaluation, hold references across each
possibly raising operation, and retain the same coarse-world state carrier.
Missing legacy target-child overlays are recovered from exact SG-backed
Names, scalar Constants, attribute/index reads and fixed-argument calls.
No legacy StaticValue or binding fact is fabricated for these expressions.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _Unsupported
from scar.ir.program.ids import ValueID
from scar.ir.program.model import (
    AccessMode, BlockArgument, ExitKind, LiteralOrigin, OperationResult,
    ReferenceValue, TerminatorKind,
)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.state_addresses import AddressEffect, Element, ObjectField, ReferenceOwner
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def _unsupported(node, detail):
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, detail)


def _source_definition(builder, node, *, binding=False):
    """Select a definition by its exact source atom and declared source role."""
    reference = builder.source(node)
    definitions = builder.by_atom.get(reference.atom_id.wire, ())
    if binding:
        candidates = [definition for definition in definitions
                      if definition.metadata.get("role") == "binding"]
    else:
        candidates = [definition for definition in definitions
                      if definition.output_slots
                      and definition.kind not in (OperationKind.FUNCTION, OperationKind.METHOD)
                      and definition.metadata.get("role") != "binding"]
    if len(candidates) != 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "heap target requires one exact SG source definition for its evaluation role")
    definition = candidates[0]
    if definition.code_id != reference.atom_id.wire or reference.atom_id not in definition.source_atoms:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "heap target SG definition does not own the exact source atom")
    return definition


def _associate(builder, operation_id, node, definition, opcode):
    """Connect a real core operation to SG without fabricating an old overlay."""
    matches = [index for index, link in enumerate(builder.operation_links) if link.operation == operation_id]
    if len(matches) != 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "recovered source operation has no unique core/source correspondence")
    index = matches[0]
    link = builder.operation_links[index]
    if link.source != builder.source(node) or link.semantic_operation is not None:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "recovered source operation already has a different source correspondence")
    builder.operation_links[index] = replace(link, semantic_operation=definition.id, opcode=opcode)


def _normal_producer(builder, node, value, first_operation):
    record = builder.values_by_id[value]
    candidates = builder.operations[first_operation:]
    if isinstance(record.origin, OperationResult):
        producers = [operation.id for operation in candidates if operation.id == record.origin.operation]
    elif isinstance(record.origin, BlockArgument):
        producers = [operation.id for operation in candidates
            if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
            and any(edge.kind is ExitKind.NORMAL and edge.block == record.origin.block
                    for edge in operation.terminator.successors)]
    else:
        producers = []
    if len(producers) != 1:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "recovered Name result has no unique newly constructed producer")
    return producers[0]


def expression_for_heap_target(builder, node, cursor):
    """Evaluate an existing overlay or recover a source-backed leaf.

    A missing old record is not an opaque computational record, an immutable
    value, or evidence of a reaching binding.  SG ownership and real core Uses
    are retained while semantic_value remains absent.
    """
    if (isinstance(node, ast.Call) and (
            getattr(builder, "has_language", lambda _: False)("CALL_KWARGS_314_V1") and any(keyword.arg is None for keyword in node.keywords)
            or getattr(builder, "has_language", lambda _: False)("CALL_EXPANSION_314_V1") and any(isinstance(arg, ast.Starred) for arg in node.args))):
        from scar.analysis.source_call_lowering import lower_kwargs_call
        return lower_kwargs_call(builder, node, cursor)
    if (getattr(builder, "has_language", lambda _: False)("SLICE_KEYS")
            and isinstance(node, (ast.Slice, ast.Tuple))):
        from scar.analysis.source_slice_lowering import lower_key
        return lower_key(builder, node, cursor)
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) == 1:
        return builder.expr(node, cursor)
    if records:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
            "heap target child has ambiguous legacy computational records")
    definition = _source_definition(builder, node)
    if isinstance(node, ast.JoinedStr):
        if (definition.kind is not OperationKind.OPERATOR
                or definition.metadata.get("ast_type") != "JoinedStr"
                or len(definition.output_slots) != 1):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "heap target string requires its unique original SG JoinedStr/output slot")
        from scar.analysis.source_string_lowering import lower_joined_string
        return lower_joined_string(builder, node, cursor, recover_missing_children=True)
    if isinstance(node, ast.Name):
        reads = [edge for edge in builder.semantic.edges.values()
                 if edge.relation is SemanticRelation.READS_SLOT and edge.source.id == definition.id]
        if len(reads) != 1 or reads[0].target.id not in builder.semantic.slots:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "recovered Name requires one existing SG binding-read edge")
        hook = getattr(builder, "read_source_name", None)
        if not callable(hook):
            _unsupported(node, "source profile has not connected its missing-overlay Name-read rule")
        first_operation = len(builder.operations)
        cursor, value = hook(node, cursor, old=None)
        if cursor is not None:
            operation_id = _normal_producer(builder, node, value, first_operation)
            _associate(builder, operation_id, node, definition, Opcode.READ)
        return cursor, value
    if isinstance(node, ast.Constant) and definition.kind is OperationKind.CONSTANT:
        try:
            origin = LiteralOrigin(node.value)
        except (TypeError, ValueError) as error:
            _unsupported(node, "heap target literal is outside exact scalar support: " + str(error))
        value = ReferenceValue(builder.fresh(ValueID, "heap-target-literal"), builder.function_context,
                               origin, targets=())
        builder.add_value(value)
        builder.link_value(value, node, SourceRole.EXPRESSION)
        return cursor, value.id
    children = None
    if (getattr(builder,'has_language',lambda _:False)('GENEXPR_CREATION_314_V1')
            and isinstance(node,ast.List) and not any(isinstance(n,ast.Starred)for n in node.elts)):
        # Ordinary BUILD_LIST already exists in the source language. The old
        # generator overlay omitted its eager iterable subtree; recover only
        # the original ordered SG-backed elements, without a fake old record.
        from scar.analysis.source_slice_lowering import _invoke
        baseline=len(builder.active_temporaries);held=[];inputs=[]
        try:
            for i,child in enumerate(node.elts):
                cursor,value=expression_for_heap_target(builder,child,cursor)
                if cursor is None:return None,None
                _hold(builder,cursor,child,value);held.append((child,value));inputs.append((value,child,'element',i,None))
            cursor,result,identity=_invoke(builder,cursor,node,tuple(inputs),tuple(held),raise_consumed=(),memory=True)
            _associate(builder,identity,node,definition,Opcode.BUILD_LIST)
            builder.link_value(builder.values_by_id[result],node,SourceRole.EXPRESSION)
            return cursor,result
        finally:del builder.active_temporaries[baseline:]
    if (getattr(builder, 'has_language', lambda _: False)('GENEXPR_CREATION_314_V1')
            and isinstance(node, ast.Compare) and len(node.ops)==len(node.comparators)==1
            and isinstance(node.ops[0], (ast.In, ast.NotIn))):
        # The old overlay omits the lazy elt. Its exact SG source still owns
        # this one comparison. Contains/iteration fallback + truth + optional
        # negation remain one incomplete stateful interface, never a pure op.
        from scar.analysis.source_slice_lowering import _invoke
        baseline=len(builder.active_temporaries);held=[];inputs=[]
        try:
            for index,(child,role)in enumerate(((node.left,'left'),(node.comparators[0],'right'))):
                cursor,value=expression_for_heap_target(builder,child,cursor)
                if cursor is None:return None,None
                _hold(builder,cursor,child,value);held.append((child,value));inputs.append((value,child,role,index,None))
            negative=builder.literal(node,isinstance(node.ops[0],ast.NotIn))
            inputs.append((negative,node,'membership-negated',0,None))
            cursor,result,identity=_invoke(builder,cursor,node,tuple(inputs),tuple(held),kind=PythonProtocolKind.GENEXPR_CONTAINS)
            _associate(builder,identity,node,definition,None)
            builder.link_value(builder.values_by_id[result],node,SourceRole.EXPRESSION)
            builder.gap(GapKind.DYNAMIC_DISPATCH,node,
                'membership retains ordered operands, contains/iteration fallback, truth, world and failures; runtime dispatch/identity/content remain unproved')
            return cursor,result
        finally:del builder.active_temporaries[baseline:]
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("__") and not node.attr.endswith("__"):
            _unsupported(node, "private attribute lookup requires exact compiler-class name mangling")
        children = ((node.value, "receiver", 0),)
        opcode = Opcode.ATTRIBUTE
    elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
        key_index = 1 if getattr(builder, "has_language", lambda _: False)("SLICE_KEYS") else 0
        children = ((node.value, "receiver", 0), (node.slice, "index", key_index))
        opcode = Opcode.INDEX
    elif (isinstance(node, ast.Call) and not any(isinstance(arg, ast.Starred) for arg in node.args)
            and all(keyword.arg is not None for keyword in node.keywords)):
        children = ((node.func, "callee", 0),)
        children += tuple((child, "argument", index) for index, child in enumerate(node.args))
        children += tuple((child.value, "keyword:" + child.arg, index)
                          for index, child in enumerate(node.keywords))
        opcode = Opcode.CALL
    if children is not None:
        # A computational overlay deliberately omits assignment-target children.
        # Recover their actual ordered Uses from the source graph instead of
        # requiring that overlay to invent values in the target subtree.
        inputs = []
        for child, role, index in children:
            cursor, value = expression_for_heap_target(builder, child, cursor)
            if cursor is None:
                return None, None
            inputs.append((value, child, role, index, None))
        cursor, result, operation_id = builder.invoke(cursor, node, tuple(inputs))
        _associate(builder, operation_id, node, definition, opcode)
        if opcode is Opcode.INDEX and getattr(builder, "has_language", lambda _: False)("SLICE_KEYS"):
            # This is a source-level, partial receiver/key address. The helper
            # binds the same invoke's existing last coarse-world Use; neither
            # physical storage access nor complete __getitem__ effects follow.
            uses = builder.operation_records[operation_id].uses
            builder._addresses(operation_id, (AddressEffect(ReferenceOwner(uses[0].id),
                (Element(uses[1].id),), AccessMode.READ),))
        builder.link_value(builder.values_by_id[result], node, SourceRole.EXPRESSION)
        builder.gap(GapKind.DYNAMIC_DISPATCH, node,
            "source-backed target expression operands are connected; actual dispatch, aliasing and effects remain unproved")
        if isinstance(node, ast.Call):
            callee = inputs[0][0]
            builder.pending_targets.append((operation_id, callee, builder.reference_candidates.get(callee), node))
            builder.gap(GapKind.DYNAMIC_TARGET, node, "source-backed call is not verified runtime dispatch")
        return cursor, result
    _unsupported(node, "missing target-child computational semantics require a checked rule for " + type(node).__name__)


def _hold(builder, cursor, node, reference):
    builder.frame_transition(cursor, node, ((reference, node, "heap-target-held-reference"),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _release(builder, cursor, node, reference):
    if not builder.active_temporaries or builder.active_temporaries[-1] != reference:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "heap target reference ownership is not nested")
    builder.active_temporaries.pop()
    builder.frame_transition(cursor, node, ((reference, node, "heap-target-released-reference"),),
                             PythonProtocolKind.FRAME_RELEASE_TEMPORARY)


def store_heap_target(builder, target, rhs, cursor, *, rhs_held=False):
    """Construct one Attribute or nonslice Subscript store, or reject explicitly.

    STORE_ATTRIBUTE inputs are receiver, RHS; STORE_SUBSCRIPT inputs are
    receiver, key, RHS.  invoke() adds the current world and both completion
    paths.  On failure FRAME_EXIT sees every currently held reference; no
    normal-path release is inserted on an exceptional path.
    """
    if not isinstance(target, (ast.Attribute, ast.Subscript)):
        _unsupported(target, "heap target rule accepts only Attribute and Subscript")
    if not isinstance(target.ctx, ast.Store):
        raise _Unsupported(GapKind.SOURCE_MAPPING, target, "heap assignment target lacks Store context")
    if isinstance(target, ast.Subscript):
        if getattr(builder, "has_language", lambda _: False)("SLICE_KEYS"):
            if any(isinstance(child, ast.Slice) for child in ast.walk(target.slice)):
                # The capability proves load-key construction only. Reusing
                # the historical store contract would silently broaden it.
                _unsupported(target, "SLICE_STORE_LIFETIME_UNRECOVERED")
        elif isinstance(target.slice, ast.Slice):
            _unsupported(target, "slice assignment needs its own evaluation and mutation rule")
    if isinstance(target, ast.Attribute) and target.attr.startswith("__") and not target.attr.endswith("__"):
        _unsupported(target, "private attribute assignment requires exact compiler-class name mangling")
    definition = _source_definition(builder, target, binding=True)
    kind_name = "STORE_ATTRIBUTE" if isinstance(target, ast.Attribute) else "STORE_SUBSCRIPT"
    protocol = getattr(PythonProtocolKind, kind_name, None)
    if protocol is None:
        _unsupported(target, "source profile has not connected the " + kind_name + " protocol")
    if rhs_held and (not builder.active_temporaries or builder.active_temporaries[-1] != rhs):
        raise _Unsupported(GapKind.SOURCE_MAPPING, target, "heap store lost its exact pending unpack result")
    initial_holds = len(builder.active_temporaries) - int(rhs_held)
    try:
        if not rhs_held:
            _hold(builder, cursor, target, rhs)
        cursor, receiver = expression_for_heap_target(builder, target.value, cursor)
        if cursor is None:
            return None
        _hold(builder, cursor, target.value, receiver)
        references = [(receiver, target.value, "heap-owner", 0, None)]
        if isinstance(target, ast.Subscript):
            cursor, key = expression_for_heap_target(builder, target.slice, cursor)
            if cursor is None:
                return None
            _hold(builder, cursor, target.slice, key)
            references.append((key, target.slice, "element-key", 0, None))
        references.append((rhs, target, "assigned-reference", 0, None))
        cursor, _, operation_id = builder.invoke(cursor, target, tuple(references),
            role=SourceRole.LOCAL_BINDING, result_type=None)
        _associate(builder, operation_id, target, definition, Opcode.OPAQUE)
        builder.protocol(operation_id, protocol, target)
        operation = builder.operation_records[operation_id]
        selector = (ObjectField(target.attr) if isinstance(target, ast.Attribute)
                    else Element(operation.uses[1].id))
        builder._addresses(operation_id, (AddressEffect(ReferenceOwner(operation.uses[0].id),
            (selector,), AccessMode.WRITE),))
        if isinstance(target, ast.Subscript):
            _release(builder, cursor, target.slice, key)
        _release(builder, cursor, target.value, receiver)
        _release(builder, cursor, target, rhs)
        builder.gap(GapKind.DYNAMIC_DISPATCH, target,
            "heap assignment receiver/key/order are connected; descriptor/index dispatch, aliasing and complete effects remain unproved")
        return cursor
    finally:
        # Construction also visits exceptional/closed branches.  Their
        # FRAME_EXIT already owns the pending references; do not emit releases
        # into a different branch or retain them in subsequent construction.
        del builder.active_temporaries[initial_holds:]


__all__ = ["expression_for_heap_target", "store_heap_target"]

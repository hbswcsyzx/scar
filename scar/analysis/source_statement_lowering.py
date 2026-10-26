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
from scar.ir.program.source import GapKind, SourceRole
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


def try_statement(builder,node,cursor):
    """Single ordinary handler, using existing C0/C1 authorities and real CFG."""
    from scar.ir.program.control import (ControlPort,ControlScopeKind as S,LanguageCompletionKind as L,
        ProtocolValueKind as P,ProtocolValueType)
    from scar.ir.program.cleanup import CleanupInterface,CleanupEnter,CleanupRouteTerminator,CleanupRouteSuccessor
    from scar.ir.program.exception_matches import ExceptionMatcher,ExceptionHandlerOperand
    from scar.ir.program.ids import ControlPortID,OperationID,ValueID
    from scar.ir.program.model import (DataValue,Operation,OperationResult,ProtocolValue,StateVersionValue,StateAccess,
        AccessMode,Footprint,FootprintKind,BlockArgument)
    from scar.ir.program.state_addresses import ExistingAccess
    from scar.ir.program.module_entries import FrameBodyProtocolKind as K
    from scar.analysis.program_lowering import _REF
    parent=builder.current_owner;handler=node.handlers[0]
    after=builder.new_block(node)
    normal_clear=builder.new_block(handler) if handler.name else after
    fallthrough=ControlPort(builder.fresh(ControlPortID,'handled-fallthrough'),parent,L.FALLTHROUGH,block=normal_clear.block)
    builder.control_ports.append(fallthrough)
    body_scope=builder.new_scope(S.BLOCK,node,parent)
    gate_scope=builder.new_scope(S.BLOCK,node,parent)
    cleanup=builder.new_scope(S.CLEANUP,handler,parent)
    with builder.in_owner(body_scope):body=builder.new_block(node)
    with builder.in_owner(gate_scope):gate=builder.new_block(node,extra_types=(_REF,_REF))
    with builder.in_owner(cleanup):entry=builder.new_block(handler,extra_types=(ProtocolValueType(P.PENDING_COMPLETION),_REF))
    builder.cleanup_interfaces.append(CleanupInterface(cleanup,gate_scope,entry.block,builder.block_arguments[entry.block][0]))
    builder.jump_values(cursor,body,(),node)
    def caught(failed,payload):builder.jump_values(failed,gate,(payload.exception,payload.traceback),node)
    with builder.in_owner(body_scope):
        builder.failure_sinks.append(caught)
        try:normal=builder.statements(node.body,body)
        finally:builder.failure_sinks.pop()
        if normal is not None:builder.jump_values(normal,after,(),node)
    # Exception-only entry: the normal try path never enters or saves context.
    from scar.analysis.source_module_lowering import PropagationOperands
    exception,traceback=builder.block_arguments[gate.block][:-1]
    original_port=builder.raise_landing(node)
    packet=builder.packet(gate,node,PropagationOperands(exception,traceback))
    original_pending=builder.pending(gate,node,original_port,packet)
    identity=builder.fresh(OperationID,'caught-exception-route')
    selector=builder.use(identity,original_pending,node,'pending-selector',0)
    forwarded=builder.use(identity,original_pending,node,'entry-pending',0)
    exception_use=builder.use(identity,exception,node,'caught-exception',0)
    state=builder.use(identity,gate.state,node,'exception-world',0)
    builder.emit(gate,Operation(identity,'caught-exception-route',(Behavior.CONTROL,),(selector,forwarded,exception_use,state),
        terminator=CleanupRouteTerminator(selector.id,(CleanupRouteSuccessor(original_port.id,entry.block,
            (forwarded.id,exception_use.id,state.id)),))),node,SourceRole.CONTROL)
    entry_pending,caught_ref=builder.block_arguments[entry.block][:-1]
    with builder.in_owner(cleanup):
        identity=builder.fresh(OperationID,'handler-context-enter')
        pending_use=builder.use(identity,entry_pending,handler,'entry-pending',0)
        before=builder.use(identity,entry.state,handler,'context-world',0)
        saved=ProtocolValue(builder.fresh(ValueID,'saved-handled-context'),builder.frame_region,OperationResult(identity,0),P.SAVED_HANDLED_CONTEXT)
        after_state=StateVersionValue(builder.fresh(ValueID,'handler-enter-world'),builder.frame_region,OperationResult(identity,1),builder.world)
        for value in (saved,after_state):builder.add_value(value);builder.link_value(value,handler,SourceRole.EXCEPTION)
        builder.emit(entry,Operation(identity,'handler-context-enter',(Behavior.CONTROL,Behavior.READ,Behavior.WRITE),
            (pending_use,before),(saved.id,after_state.id),
            (StateAccess(builder.world,before.id,AccessMode.READ_WRITE,after_state.id,Footprint(FootprintKind.WHOLE)),),effects_complete=False),handler,SourceRole.CONTROL)
        builder.cleanup_enters.append(CleanupEnter(identity,cleanup,pending_use.id,saved.id));entry.state=after_state.id
        def replace_exception(failed,payload):
            port=builder.raise_landing(handler);new_packet=builder.packet(failed,handler,payload)
            replacement=builder.pending(failed,handler,port,new_packet)
            builder.cleanup_exit(failed,handler,cleanup,entry_pending,replacement,saved.id,port)
        builder.failure_sinks.append(replace_exception)
        current=entry
        try:
            if handler.type is not None:
                current,handler_ref=builder.expr(handler.type,current)
                builder.frame_transition(current,handler,((handler_ref,handler.type,'handler-type-hold'),),PythonProtocolKind.FRAME_HOLD_TEMPORARY)
                builder.active_temporaries.append(handler_ref)
                def invalid_type(failed,payload):
                    held=builder.active_temporaries.pop()
                    try:
                        builder.frame_transition(failed,handler,((held,handler.type,'handler-type-release'),),PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
                        replace_exception(failed,payload)
                    finally:builder.active_temporaries.append(held)
                current,validated_ref,validate=builder.invoke(current,handler,((handler_ref,handler.type,'handler-type',0,None),),failure_handler=invalid_type)
                builder.protocol(validate,K.VALIDATE_EXCEPT_TYPE_314,handler)
                match_id=builder.fresh(OperationID,'borrowed-exception-match')
                exception_use=builder.use(match_id,caught_ref,handler,'caught-exception',0)
                handler_use=builder.use(match_id,validated_ref,handler.type,'dynamic-handler',0)
                state=builder.use(match_id,current.state,handler,'match-world',0)
                result=DataValue(builder.fresh(ValueID,'exception-match-bool'),builder.frame_region,OperationResult(match_id,0),'builtins.bool')
                builder.add_value(result);builder.link_value(result,handler,SourceRole.TRUTH)
                builder.emit(current,Operation(match_id,'borrowed-exception-match',(Behavior.COMPUTE,Behavior.READ,Behavior.CONTROL),
                    (exception_use,handler_use,state),(result.id,),
                    (StateAccess(builder.world,state.id,AccessMode.READ,footprint=Footprint(FootprintKind.WHOLE)),),effects_complete=True),handler,SourceRole.TRUTH)
                builder.protocol(match_id,K.MATCH_EXCEPTION_BORROWED_314,handler)
                builder.active_temporaries.pop()
                builder.frame_transition(current,handler,((handler_ref,handler.type,'handler-type-release'),),PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
                yes,no=builder.new_block(handler),builder.new_block(handler)
                builder.branch(current,result.id,yes,no,handler);branch=builder.operations[-1].id
                builder.exception_matches.append(ExceptionMatcher(match_id,exception_use.id,BlockArgument(entry.block,1),
                    ExceptionHandlerOperand(handler_use.id,builder.values_by_id[validated_ref].origin),OperationResult(match_id,0),None,branch,(ExistingAccess(match_id,0),)))
                builder.cleanup_exit(no,handler,cleanup,entry_pending,entry_pending,saved.id,original_port,resume=True)
                current=yes
            if handler.name:current=builder.store_name(handler,handler.name,caught_ref,current)
            # Binding failure has not yet entered the name-clear protection.
            error_block=None
            body_base=len(builder.active_temporaries)
            deferred_ports=[]
            def handler_failed(failed,payload):
                nonlocal error_block
                if not handler.name:return replace_exception(failed,payload)
                if error_block is None:error_block=builder.new_block(handler,extra_types=(ProtocolValueType(P.PENDING_COMPLETION),))
                held=tuple(builder.active_temporaries[body_base:]);del builder.active_temporaries[body_base:]
                try:
                    if held:builder.frame_transition(failed,handler,tuple((ref,handler,'handler-unwind-temporary') for ref in reversed(held)),PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
                    port=builder.raise_landing(handler);deferred_ports.append(port)
                    new_packet=builder.packet(failed,handler,payload);replacement=builder.pending(failed,handler,port,new_packet)
                    builder.jump_values(failed,error_block,(replacement,),handler)
                finally:builder.active_temporaries.extend(held)
            builder.failure_sinks.append(handler_failed)
            try:completed=builder.statements(handler.body,current)
            finally:builder.failure_sinks.pop()
            if completed is not None:
                success=builder.pending(completed,handler,fallthrough)
                builder.cleanup_exit(completed,handler,cleanup,entry_pending,success,saved.id,fallthrough)
            if error_block is not None:
                selected=builder.block_arguments[error_block.block][0]
                error_block=builder.store_name(handler,handler.name,builder.literal(handler,None),error_block)
                error_block=builder.delete_name(handler,handler.name,error_block)
                # This shared block can carry several exact fresh Raise ports.
                builder.cleanup_exit_cases(error_block,handler,cleanup,entry_pending,selected,saved.id,tuple(deferred_ports))
        finally:builder.failure_sinks.pop()
    if handler.name:
        # Normal handler has already restored ambient context before these ops.
        normal_clear=builder.store_name(handler,handler.name,builder.literal(handler,None),normal_clear)
        normal_clear=builder.delete_name(handler,handler.name,normal_clear)
        builder.jump_values(normal_clear,after,(),handler)
    return after

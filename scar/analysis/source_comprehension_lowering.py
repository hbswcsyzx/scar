"""Eager source comprehensions in the existing function CFG and world.

Private SSA keys name original comprehension slots; they are not Python local
names, new source slots, child frames, or extra target-program operations.
Outer bindings remain held and the scoped target is released on scope exit.
"""
from __future__ import annotations

import ast
import dis
from dataclasses import replace

from scar.analysis.program_lowering import _Unsupported, _REF, _BOOL
from scar.analysis.source_heap_lowering import _source_definition, _associate, _hold, _normal_producer
from scar.analysis.source_mapping_lowering import _transfer
from scar.analysis.source_slice_lowering import _invoke
from scar.ir.program.bindings import BindingRead
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import (AccessMode, Behavior, DataValue, ExitKind, Operation,
    OperationResult, ReferenceValue, StateAccess, TerminatorKind)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind

VERSION = 'PYTHON_COMPREHENSION_314_V1'
KINDS = frozenset((K.COMPREHENSION_BUILD, K.COMPREHENSION_NEXT,
                   K.COMPREHENSION_ADD, K.COMPREHENSION_LEAVE))


def shape(node):
    return (isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp))
        and len(node.generators) == 1 and not node.generators[0].is_async
        and isinstance(node.generators[0].target, ast.Name) and not node.generators[0].ifs
        and not any(isinstance(n, (ast.NamedExpr, ast.Yield, ast.YieldFrom, ast.Await)) for n in ast.walk(node))
        and not any(isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                    for child in ast.iter_child_nodes(node) for n in ast.walk(child)))


def compiler_scope(node, code):
    """Witness the inlined scope's original build/update/compiler target, not execution."""
    span=lambda n:(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
    positions=span(node);all_rows=tuple(dis.get_instructions(code))
    def within(row):
        p=row.positions
        return (p.lineno is not None and (node.lineno,node.col_offset)<=(p.lineno,p.col_offset)
                and (p.end_lineno,p.end_col_offset)<=(node.end_lineno,node.end_col_offset))
    rows=[r for r in all_rows if within(r)]
    build,update={ast.ListComp:('BUILD_LIST','LIST_APPEND'),ast.SetComp:('BUILD_SET','SET_ADD'),ast.DictComp:('BUILD_MAP','MAP_ADD')}[type(node)]
    target=node.generators[0].target.id
    builds=[r for r in rows if r.opname==build and r.arg==0 and tuple(r.positions)==positions]
    updates=[r for r in rows if r.opname==update]
    clears=[r for r in all_rows if r.opname=='LOAD_FAST_AND_CLEAR' and r.argval==target and tuple(r.positions)==positions]
    if (len(builds)!=1 or len(updates)!=1 or len(clears)!=1 or target in code.co_cellvars
            or not clears[0].offset<builds[0].offset<updates[0].offset):
        raise _Unsupported(GapKind.CODE_VERSION,node,'COMPREHENSION_INLINED_BUILD_UPDATE_TARGET_INTERFACE_UNRECOVERED')


def _target_read(builder, node, cursor, old=None):
    scope = getattr(builder, 'comprehension_scope', None)
    if scope is None or node.id != scope[0]:
        return NotImplemented
    binding = cursor.env[scope[1]]
    identity = builder.fresh(OperationID, 'comprehension-read')
    use = builder.use(identity, binding, node, 'local-binding', 0)
    value = ReferenceValue(builder.fresh(ValueID, 'comprehension-reference'), builder.function_context,
                           OperationResult(identity, 0))
    builder.add_value(value); builder.link_value(value, node, SourceRole.EXPRESSION)
    builder.emit(cursor, Operation(identity, 'read-local', (Behavior.COMPUTE,), (use,), (value.id,),
                                  effects_complete=True), node, SourceRole.EXPRESSION, old=old)
    builder.binding_reads.append(BindingRead(identity, use.id, value.id))
    return cursor, value.id


def expression(builder, node, cursor):
    """Original SG children absent from the old opaque comprehension overlay."""
    definition = _source_definition(builder, node)
    if isinstance(node, ast.Name):
        first = len(builder.operations)
        cursor, value = builder.read_source_name(node, cursor, None)
        if cursor is not None:
            _associate(builder, _normal_producer(builder, node, value, first), node, definition, Opcode.READ)
        return cursor, value
    if isinstance(node, ast.Constant):
        return builder.expr(node, cursor)
    if isinstance(node, ast.JoinedStr):
        from scar.analysis.source_string_lowering import lower_joined_string
        return lower_joined_string(builder, node, cursor, recover_missing_children=True)
    if isinstance(node, ast.Attribute):
        children = ((node.value, 'receiver', 0),); opcode = Opcode.ATTRIBUTE
    elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
        children = ((node.value, 'receiver', 0), (node.slice, 'index', 1)); opcode = Opcode.INDEX
    elif isinstance(node, ast.Call) and not any(isinstance(a, ast.Starred) for a in node.args) and all(k.arg is not None for k in node.keywords):
        children = ((node.func, 'callee', 0),) + tuple((c, 'argument', i) for i,c in enumerate(node.args)) + tuple((k.value, 'keyword:'+k.arg, i) for i,k in enumerate(node.keywords))
        opcode = Opcode.CALL
    else:
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           'COMPREHENSION_EXPRESSION_INTERFACE_UNIMPLEMENTED: '+type(node).__name__)
    base = len(builder.active_temporaries); held=[]; inputs=[]
    try:
        for child, role, position in children:
            cursor, value = expression(builder, child, cursor)
            if cursor is None: return None, None
            _hold(builder, cursor, child, value); held.append((child,value))
            inputs.append((value,child,role,position,None))
        cursor, value, identity = _invoke(builder,cursor,node,inputs,tuple(held))
        _associate(builder,identity,node,definition,opcode)
        if opcode is Opcode.INDEX:
            from scar.ir.program.state_addresses import AddressEffect, Element, ReferenceOwner
            uses=builder.operation_records[identity].uses
            builder._addresses(identity,(AddressEffect(ReferenceOwner(uses[0].id),(Element(uses[1].id),),AccessMode.READ),))
        builder.link_value(builder.values_by_id[value],node,SourceRole.EXPRESSION)
        if opcode is Opcode.CALL: builder.pending_targets.append((identity,inputs[0][0],None,node))
        return cursor,value
    finally: del builder.active_temporaries[base:]


def _update(builder,node,cursor,container,children):
    base=len(builder.active_temporaries);held=[];inputs=[(container,node,'container',0,None)]
    try:
        for i,child in enumerate(children):
            cursor,value=expression(builder,child,cursor)
            if cursor is None:return None
            _hold(builder,cursor,child,value);held.append((child,value));inputs.append((value,child,'element',i,None))
        def failed(at,exception):
            pending=tuple(builder.active_temporaries)
            try:
                _transfer(builder,tuple(held),node)
                builder.finish_exit(at,node,exception,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=pending
        cursor,_,identity=builder.invoke_results(cursor,node,tuple(inputs),result_types=(),failure_handler=failed)
        builder.protocol(identity,K.COMPREHENSION_ADD,node)
        _transfer(builder,tuple(held),node)
        return cursor
    finally:del builder.active_temporaries[base:]


def lower_comprehension(builder,node,cursor):
    if not shape(node):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'COMPREHENSION_ASYNC_MULTI_CLAUSE_NESTED_OR_TARGET_INTERFACE_UNIMPLEMENTED')
    if getattr(builder,'try_depth',0) or builder.has_language('FUNCTION_TRY_314_V1'):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'COMPREHENSION_PARENT_CLEANUP_INTERFACE_UNIMPLEMENTED')
    evidence=builder.language_options.code_evidence
    if evidence is None:raise _Unsupported(GapKind.CODE_VERSION,node,'COMPREHENSION_READONLY_CODE_WITNESS_REQUIRED')
    compiler_scope(node,evidence.code)
    definition=_source_definition(builder,node);clause=node.generators[0];target=clause.target
    if definition.kind is not OperationKind.OPAQUE or definition.metadata.get('ast_type')!=type(node).__name__:
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'COMPREHENSION_ORIGINAL_SOURCE_SCOPE_REQUIRED')
    slots=[s.slot_id for s in builder.semantic.slots.values() if s.owner==definition.id and s.name==target.id and s.metadata.get('scope_kind')=='comprehension']
    if len(slots)!=1:raise _Unsupported(GapKind.SOURCE_MAPPING,target,'COMPREHENSION_ORIGINAL_TARGET_SLOT_REQUIRED')
    baseline=len(builder.active_temporaries);prior=getattr(builder,'comprehension_scope',None)
    alias='\x00comprehension:'+definition.id.wire+':'+target.id
    original_slots=builder.slots;builder.slots={**builder.slots,(builder.function_definition.id,alias):slots[0]}
    try:
        cursor,iterable=expression(builder,clause.iter,cursor)
        if cursor is None:return None,None
        _hold(builder,cursor,clause.iter,iterable)
        def get_failed(at,exception):
            held=tuple(builder.active_temporaries)
            try:
                _transfer(builder,((clause.iter,iterable),),node)
                builder.finish_exit(at,node,exception,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=held
        cursor,iterator,_=builder.invoke_protocol(cursor,clause.iter,(iterable,),K.GET_ITERATOR,failure_handler=get_failed)
        _transfer(builder,((clause.iter,iterable),),node);_hold(builder,cursor,node,iterator)
        cursor,container,identity=builder.invoke(cursor,node,())
        builder.protocol(identity,K.COMPREHENSION_BUILD,node)
        _associate(builder,identity,node,definition,Opcode.OPAQUE)
        _hold(builder,cursor,node,container)
        builder.define_binding(alias,cursor,target)
        names=tuple(sorted(cursor.env));header=builder.new_block(node,named=names)
        builder.jump(cursor,header,names,node)
        natural=builder.new_block(node)
        def exhausted(at,exception):
            identity=builder.fresh(OperationID,'comprehension-stop-match')
            use=builder.use(identity,builder.exception_reference(exception),node,'exception',0)
            before=builder.use(identity,at.state,node,'exception-type-state',0)
            boolean=DataValue(builder.fresh(ValueID,'comprehension-stop'),builder.function_context,OperationResult(identity,0),'builtins.bool')
            builder.add_value(boolean);builder.link_value(boolean,node,SourceRole.TRUTH)
            builder.emit(at,Operation(identity,'match-stop-iteration',(Behavior.COMPUTE,Behavior.READ),(use,before),(boolean.id,),
                (StateAccess(builder.world,before.id,AccessMode.READ),),effects_complete=True),node,SourceRole.TRUTH)
            builder.protocol(identity,K.MATCH_STOP_ITERATION,node)
            raised=builder.new_block(node);builder.branch(at,boolean.id,natural,raised,node)
            builder.frame_transition(natural,node,tuple((v,node,'consumed-exhaustion')for v in builder.failure_references(exception)),K.FRAME_DISCARD)
            builder.finish_exit(raised,node,exception,ExitKind.RAISE)
        body,item,identity=builder.invoke_protocol(header,node,(iterator,),K.COMPREHENSION_NEXT,failure_handler=exhausted)
        builder.frame_transition(body,target,((body.env[alias],target,'previous-binding'),(item,target,'assigned-reference')),K.FRAME_BIND)
        builder.define_binding(alias,body,target,item)
        builder.comprehension_scope=(target.id,alias)
        if body is not None:
            children=(node.key,node.value) if isinstance(node,ast.DictComp) else(node.elt,)
            body=_update(builder,node,body,container,children)
        if body is not None:builder.jump(body,header,names,node)
        # Clear this transient binding while the result/container and enclosing
        # bindings remain held. The physical save/restore staging is folded.
        builder.frame_transition(natural,node,((natural.env[alias],target,'scoped-binding'),(iterator,node,'exhausted-iterator')),K.COMPREHENSION_LEAVE)
        natural.env.pop(alias)
        _transfer(builder,((node,iterator),(node,container)),node)
        builder.link_value(builder.values_by_id[container],node,SourceRole.EXPRESSION)
        builder.gap(GapKind.EFFECT_SUMMARY,node,'comprehension scoped iteration/container dependencies are explicit; dispatch, contents, identity, iteration count and complete effects remain unproved')
        return natural,container
    finally:
        builder.slots=original_slots;builder.comprehension_scope=prior
        del builder.active_temporaries[baseline:]

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


def target_leaves(target):
    """Original left-to-right occurrences; repeated names remain repeated."""
    if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
        return (target,)
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(target.ctx, ast.Store):
        return tuple(leaf for child in target.elts for leaf in target_leaves(child))
    raise ValueError('comprehension target requires recursive Tuple/List -> Store Name')


def target_shape(target):
    try:
        leaves=target_leaves(target)
    except (ValueError, RecursionError):
        return False
    return bool(leaves)


def shape(node, *, recursive_targets=False):
    return (isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp))
        and len(node.generators) == 1 and not node.generators[0].is_async
        and (target_shape(node.generators[0].target) if recursive_targets else isinstance(node.generators[0].target, ast.Name))
        and not node.generators[0].ifs
        and not any(isinstance(n, (ast.NamedExpr, ast.Yield, ast.YieldFrom, ast.Await)) for n in ast.walk(node))
        and not any(isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                    for child in ast.iter_child_nodes(node) for n in ast.walk(child)))


def compiler_scope(node, code, *, recursive_targets=False):
    """Witness the inlined scope's original build/update/compiler target, not execution."""
    if recursive_targets:
        return _compiler_targets(node, code)
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


def _fast_store_names(code, instruction):
    """Decode only the fixed 3.14.7 local-store encodings used by targets.

    Like the existing dual-borrow load decoder, check both nibble indexes
    against dis's decoded names and the original code's local table. The
    fused instruction keeps only its first source position; it does not
    establish a second bytecode source occurrence.
    """
    if instruction.opname=='STORE_FAST':
        indexes=(instruction.arg,);names=(instruction.argval,)
    elif instruction.opname=='STORE_FAST_STORE_FAST':
        packed=instruction.arg;names=instruction.argval
        if (type(packed)is not int or not 0<=packed<=0xff
                or type(names)is not tuple or len(names)!=2):
            return None
        indexes=(packed>>4,packed&0xf)
    else:return None
    if any(type(index)is not int or not 0<=index<code.co_nlocals
           or index>=len(code.co_varnames) or type(name)is not str
           or code.co_varnames[index]!=name for index,name in zip(indexes,names)):
        return None
    return names


def _compiler_targets(node, code):
    """Exact clear/store/restore corridors; no guessed physical name ordering."""
    span=lambda n:(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
    position=span(node);rows=tuple(dis.get_instructions(code))
    def inside(row):
        p=row.positions
        return (p.lineno is not None and p.col_offset is not None and p.end_lineno is not None
                and p.end_col_offset is not None and (node.lineno,node.col_offset)<=(p.lineno,p.col_offset)
                and (p.end_lineno,p.end_col_offset)<=(node.end_lineno,node.end_col_offset))
    build_name,update_name={ast.ListComp:('BUILD_LIST','LIST_APPEND'),ast.SetComp:('BUILD_SET','SET_ADD'),ast.DictComp:('BUILD_MAP','MAP_ADD')}[type(node)]
    builds=[r for r in rows if r.opname==build_name and r.arg==0 and tuple(r.positions)==position]
    updates=[r for r in rows if r.opname==update_name and inside(r)]
    leaves=target_leaves(node.generators[0].target);names=set(n.id for n in leaves)
    clears=[r for r in rows if r.opname=='LOAD_FAST_AND_CLEAR' and tuple(r.positions)==position]
    def reject(detail):
        raise _Unsupported(GapKind.CODE_VERSION,node,'COMPREHENSION_TARGET_COMPILER_'+detail)
    if (len(builds)!=1 or len(updates)!=1 or len(clears)!=len(names)
            or {r.argval for r in clears}!=names or any(name in code.co_cellvars for name in names)
            or any(r.offset>=builds[0].offset for r in clears) or builds[0].offset>=updates[0].offset):
        reject('CLEAR_BUILD_UPDATE_UNRECOVERED')
    expected=[]
    def target(n):
        if isinstance(n,ast.Name):expected.append(('STORE_FAST',n.id,span(n)))
        else:
            expected.append(('UNPACK_SEQUENCE',len(n.elts),span(n)))
            for child in n.elts:target(child)
    target(node.generators[0].target)
    positions={item[2] for item in expected}
    actual=[r for r in rows if tuple(r.positions) in positions
            and r.opname in ('STORE_FAST','STORE_FAST_STORE_FAST','UNPACK_SEQUENCE','UNPACK_EX')
            and builds[0].offset<r.offset<updates[0].offset]
    index=0
    for row in actual:
        if row.opname in ('STORE_FAST','STORE_FAST_STORE_FAST'):
            names_in_order=_fast_store_names(code,row)
            if names_in_order is None:reject('FAST_STORE_OPERANDS_DIFFER')
            original=expected[index:index+len(names_in_order)]
            # A fused pair consumes exactly the next two original Name
            # leaves, not a set of names. Its retained position must be the
            # first leaf's; the second leaf retains its AST SourceReference,
            # without inventing a missing second instruction/position.
            if (len(original)!=len(names_in_order)
                    or any(item[0]!='STORE_FAST'for item in original)
                    or tuple(item[1]for item in original)!=names_in_order
                    or tuple(row.positions)!=original[0][2]):
                reject('ORDERED_UNPACK_STORES_UNRECOVERED')
            index+=len(names_in_order)
        else:
            if index>=len(expected) or (row.opname,row.arg,tuple(row.positions))!=expected[index]:
                reject('ORDERED_UNPACK_STORES_UNRECOVERED')
            index+=1
    if index!=len(expected):reject('ORDERED_UNPACK_STORES_UNRECOVERED')
    entries=[e for e in dis.Bytecode(code).exception_entries
             if e.start<=builds[0].offset<e.end and updates[0].offset<e.end]
    if len(entries)!=1:reject('EXCEPTION_CORRIDOR_UNRECOVERED')
    handler=entries[0];tail=[r for r in rows if r.offset>=handler.target]
    stop=next((i for i,r in enumerate(tail)if r.opname=='RERAISE'),None)
    if stop is None:reject('RESTORE_RERAISE_MISSING')
    tail=tail[:stop+1]
    if (any(r.opname not in ('SWAP','POP_TOP','STORE_FAST','NOP','RERAISE')for r in tail)
            or tail[-1].arg!=0):reject('RESTORE_RERAISE_PROTOCOL_DIFFERS')
    error=[r.argval for r in tail if r.opname=='STORE_FAST' and tuple(r.positions)==position]
    normal=[r.argval for r in rows if r.opname=='STORE_FAST' and tuple(r.positions)==position
            and updates[0].offset<r.offset<handler.target]
    if (len(normal)!=len(names) or set(normal)!=names or len(error)!=len(names) or set(error)!=names):
        reject('NORMAL_EXCEPTION_RESTORE_NAMES_DIFFER')
    return {'clear_order':tuple(r.argval for r in clears),'normal_order':tuple(normal),
            'failure_order':tuple(error),'handler':handler.target}


def _target_read(builder, node, cursor, old=None):
    scope = getattr(builder, 'comprehension_scope', None)
    if isinstance(scope,_ScopedTargets):
        alias=scope.aliases.get(node.id)
        if alias is None:return NotImplemented
    elif scope is not None and node.id==scope[0]:
        alias=scope[1]
    else:
        return NotImplemented
    binding = cursor.env[alias]
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


class _ScopedTargets:
    """Private construction context; all binding endpoints are original slots."""
    def __init__(self,builder,node,definition,plan,baseline,iterator):
        self.builder,self.node,self.definition,self.plan=builder,node,definition,plan
        self.baseline,self.iterator,self.container=baseline,iterator,None
        self.leaves=target_leaves(node.generators[0].target)
        self.first={}
        for leaf in self.leaves:self.first.setdefault(leaf.id,leaf)
        self.aliases={name:'\x00comprehension:'+definition.id.wire+':'+name for name in plan['clear_order']}
        self.slots={}
        for name in self.aliases:
            slots=[s.slot_id for s in builder.semantic.slots.values()if s.owner==definition.id
                   and s.name==name and s.metadata.get('scope_kind')=='comprehension']
            if len(slots)!=1:
                raise _Unsupported(GapKind.SOURCE_MAPPING,self.first[name],'COMPREHENSION_ORIGINAL_TARGET_SLOT_REQUIRED')
            self.slots[name]=slots[0]
        self.sink=self.failed

    def bind(self,target,value,cursor):
        if not isinstance(target,ast.Name) or target.id not in self.aliases:
            raise _Unsupported(GapKind.SOURCE_MAPPING,target,'COMPREHENSION_TARGET_OCCURRENCE_UNRECOVERED')
        alias=self.aliases[target.id]
        self.builder.frame_transition(cursor,target,
            ((cursor.env[alias],target,'previous-binding'),(value,target,'assigned-reference')),K.FRAME_BIND)
        self.builder.define_binding(alias,cursor,target,value)
        return cursor

    def leave(self,cursor,*,failure):
        """One versioned scope protocol; no claim of actual deallocation.

        The compiler exception corridor drops iterator then result-container
        before restoring scoped names. Normal exhaustion forwards the result.
        Existing outer-name binding tokens are carried unchanged, not rebound.
        """
        order=self.plan['failure_order'if failure else'normal_order']
        refs=[(self.iterator,self.node,'comprehension-exception-iterator'if failure else'exhausted-iterator')]
        if failure and self.container is not None:
            refs.append((self.container,self.node,'comprehension-exception-container'))
        refs.extend((cursor.env[self.aliases[name]],self.first[name],
                     'comprehension-exception-binding'if failure else'scoped-binding')for name in order)
        self.builder.frame_transition(cursor,self.node,tuple(refs),K.COMPREHENSION_LEAVE)
        for alias in self.aliases.values():cursor.env.pop(alias)

    def failed(self,cursor,payload):
        builder=self.builder;saved=tuple(builder.active_temporaries)
        if not builder.failure_sinks or builder.failure_sinks[-1] is not self.sink:
            raise _Unsupported(GapKind.SOURCE_MAPPING,self.node,'COMPREHENSION_FAILURE_SINK_OWNERSHIP_DIFFERS')
        reserved=(self.iterator,)if self.container is None else(self.iterator,self.container)
        owned=tuple(builder.active_temporaries[self.baseline:])
        if owned[:len(reserved)]!=reserved:
            raise _Unsupported(GapKind.SOURCE_MAPPING,self.node,'COMPREHENSION_PENDING_PREFIX_DIFFERS')
        builder.failure_sinks.pop()
        try:
            # Helpers already removed interpreter-consumed arguments. Remaining
            # unpack siblings/child operands unwind in reverse retained order.
            for value in reversed(owned[len(reserved):]):
                builder.frame_transition(cursor,self.node,((value,self.node,'function-exception-unwind'),),K.FRAME_RELEASE_TEMPORARY)
            self.leave(cursor,failure=True)
            del builder.active_temporaries[self.baseline:]
            # Preserve this INVOKE's exception/traceback pair and latest W;
            # the original outer C0/C1 sink remains the sole pending authority.
            builder.finish_exit(cursor,self.node,payload,ExitKind.RAISE)
        finally:
            builder.active_temporaries[:]=saved
            builder.failure_sinks.append(self.sink)


def scoped_target(builder,target):
    """Resolve only a current original comprehension Store-Name occurrence."""
    scope=getattr(builder,'comprehension_scope',None)
    if not isinstance(scope,_ScopedTargets) or not isinstance(target,ast.Name):return None
    reference=builder.source(target)
    if not any(builder.source(leaf)==reference for leaf in scope.leaves):return None
    return scope


def scoped_target_slots(semantic,source_tree,language):
    """Exact leaf SourceReference -> original comp slot for shared validators."""
    from scar.ir.program.source_language import SourceLanguageCapability as C
    if C.COMPREHENSION_TARGETS_314_V1 not in language.capabilities:return {}
    atoms={(a.kind,a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column):a
           for a in semantic.source_atoms.values()if a.reference.path==language.source.path
           and a.reference.fingerprint==language.source.fingerprint}
    result={}
    for node in ast.walk(source_tree):
        if not shape(node,recursive_targets=True):continue
        key=(type(node).__name__,node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
        atom=atoms.get(key)
        if atom is None:continue
        owners=[d.id for d in semantic.definitions.values()if d.kind is OperationKind.OPAQUE
                and d.code_id==atom.id.wire and d.metadata.get('ast_type')==type(node).__name__]
        if len(owners)!=1:continue
        for leaf in target_leaves(node.generators[0].target):
            leaf_atom=atoms.get(('Name',leaf.lineno,leaf.end_lineno,leaf.col_offset,leaf.end_col_offset))
            slots=[s.slot_id for s in semantic.slots.values()if s.owner==owners[0]
                   and s.name==leaf.id and s.metadata.get('scope_kind')=='comprehension']
            if leaf_atom is not None and len(slots)==1:result[leaf_atom.reference]=slots[0]
    return result


def _lower_targets(builder,node,cursor):
    if not shape(node,recursive_targets=True):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'COMPREHENSION_RECURSIVE_TARGET_SHAPE_UNIMPLEMENTED')
    if (not builder.has_language('FUNCTION_TRY_314_V1') or not builder.has_language('FIXED_UNPACK')
            or not hasattr(builder,'failure_sinks')):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'COMPREHENSION_TARGETS_REQUIRE_EXISTING_PAIRED_PROPAGATION_AND_UNPACK')
    evidence=builder.language_options.code_evidence
    from scar.analysis.source_language import supports_cpython_compiler
    if not supports_cpython_compiler(evidence):
        raise _Unsupported(GapKind.CODE_VERSION,node,'COMPREHENSION_TARGETS_REQUIRE_CPYTHON_3147_COMPILER')
    plan=compiler_scope(node,evidence.code,recursive_targets=True)
    definition=_source_definition(builder,node)
    if definition.kind is not OperationKind.OPAQUE or definition.metadata.get('ast_type')!=type(node).__name__:
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'COMPREHENSION_ORIGINAL_SOURCE_SCOPE_REQUIRED')
    baseline=len(builder.active_temporaries);clause=node.generators[0]
    prior=getattr(builder,'comprehension_scope',None);original_slots=builder.slots
    scope=None
    try:
        # Outermost iterable and GET_ITER happen before target save/clear.
        cursor,iterable=expression(builder,clause.iter,cursor)
        if cursor is None:return None,None
        _hold(builder,cursor,clause.iter,iterable)
        def get_failed(at,payload):
            saved=tuple(builder.active_temporaries)
            try:
                _transfer(builder,((clause.iter,iterable),),node)
                builder.finish_exit(at,node,payload,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=saved
        cursor,iterator,_=builder.invoke_protocol(cursor,clause.iter,(iterable,),K.GET_ITERATOR,failure_handler=get_failed)
        _transfer(builder,((clause.iter,iterable),),node);_hold(builder,cursor,node,iterator)
        scope=_ScopedTargets(builder,node,definition,plan,baseline,iterator)
        builder.slots={**builder.slots,**{(builder.function_definition.id,scope.aliases[name]):slot
                                       for name,slot in scope.slots.items()}}
        for name in plan['clear_order']:
            builder.define_binding(scope.aliases[name],cursor,scope.first[name])
        builder.comprehension_scope=scope
        builder.failure_sinks.append(scope.sink)
        cursor,container,identity=builder.invoke(cursor,node,())
        scope.container=container
        builder.protocol(identity,K.COMPREHENSION_BUILD,node)
        _associate(builder,identity,node,definition,Opcode.OPAQUE)
        _hold(builder,cursor,node,container)
        names=tuple(sorted(cursor.env));header=builder.new_block(node,named=names)
        builder.jump(cursor,header,names,node)
        natural=builder.new_block(node)
        def exhausted(at,payload):
            identity=builder.fresh(OperationID,'comprehension-stop-match')
            use=builder.use(identity,builder.exception_reference(payload),node,'exception',0)
            before=builder.use(identity,at.state,node,'exception-type-state',0)
            boolean=DataValue(builder.fresh(ValueID,'comprehension-stop'),builder.function_context,OperationResult(identity,0),'builtins.bool')
            builder.add_value(boolean);builder.link_value(boolean,node,SourceRole.TRUTH)
            builder.emit(at,Operation(identity,'match-stop-iteration',(Behavior.COMPUTE,Behavior.READ),(use,before),(boolean.id,),
                (StateAccess(builder.world,before.id,AccessMode.READ),),effects_complete=True),node,SourceRole.TRUTH)
            builder.protocol(identity,K.MATCH_STOP_ITERATION,node)
            raised=builder.new_block(node);builder.branch(at,boolean.id,natural,raised,node)
            builder.frame_transition(natural,node,tuple((v,node,'consumed-exhaustion')for v in builder.failure_references(payload)),K.FRAME_DISCARD)
            builder.finish_exit(raised,node,payload,ExitKind.RAISE)
        body,item,_=builder.invoke_protocol(header,node,(iterator,),K.COMPREHENSION_NEXT,failure_handler=exhausted)
        if isinstance(clause.target,ast.Name):
            body=scope.bind(clause.target,item,body)
        else:
            from scar.analysis.source_unpack_lowering import lower_unpack_target
            body=lower_unpack_target(builder,clause.target,item,body)
        children=(node.key,node.value)if isinstance(node,ast.DictComp)else(node.elt,)
        body=_update(builder,node,body,container,children)
        if body is not None:builder.jump(body,header,names,node)
        scope.leave(natural,failure=False)
        _transfer(builder,((node,iterator),(node,container)),node)
        builder.link_value(builder.values_by_id[container],node,SourceRole.EXPRESSION)
        builder.gap(GapKind.EFFECT_SUMMARY,node,'recursive comp target/partial-unpack/paired cleanup interfaces are explicit; object aliasing, contents, finalizers, iteration count and full effects remain open')
        return natural,container
    finally:
        if scope is not None and builder.failure_sinks and builder.failure_sinks[-1] is scope.sink:
            builder.failure_sinks.pop()
        builder.slots=original_slots;builder.comprehension_scope=prior
        del builder.active_temporaries[baseline:]


def lower_comprehension(builder,node,cursor):
    if builder.has_language('COMPREHENSION_TARGETS_314_V1'):
        return _lower_targets(builder,node,cursor)
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

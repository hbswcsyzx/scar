"""Exact CPython 3.14 module annotation stages; no annotation is executed.

The generated annotation child remains the compiler prelude's deferred child.
Its captured globals reference does not establish later namespace contents.
Implicit compiler operands use the original AnnAssign source, never fake ASTs.
"""
from __future__ import annotations

import ast
import __future__
from dataclasses import dataclass, replace
import dis

from scar.analysis.static_compilation import StaticCodeEvidence
from scar.ir.program.module_entries import (
    ModuleAnnotationCompilerWitness, ModuleAnnotationMode as Mode,
    FrameBodyProtocolKind as K,
)
from scar.ir.program.structured import PythonProtocolKind as P
from scar.ir.program.model import Behavior, ExitKind
from scar.ir.program.source import GapKind


def _span(node):
    return node.lineno,node.end_lineno,node.col_offset,node.end_col_offset


@dataclass(frozen=True, slots=True)
class ModuleAnnotationPlan:
    witness: ModuleAnnotationCompilerWitness
    store: dis.Instruction | None
    lookup: dis.Instruction
    value: dis.Instruction
    update: dis.Instruction
    key: dis.Instruction | None = None
    discard: dis.Instruction | None = None
    empty_dict: dis.Instruction | None = None


def module_annotation_plan(context,evidence,node,*,profile):
    """Recognize a unique original statement window, not an evaluation plan."""
    from scar.analysis.source_module_lowering import (
        module_unit,require_root_evidence,_mapping_source_instructions,_module_statement_ref,
    )
    from scar.analysis.source_module_compiler_lowering import compiler_prelude_plan
    if (type(evidence) is not StaticCodeEvidence or not isinstance(node,ast.AnnAssign)
            or node.simple!=1 or not isinstance(node.target,ast.Name)):
        raise ValueError('module annotations currently require an original simple-name AnnAssign')
    require_root_evidence(module_unit(context),evidence,allow_compiler_locals=True)
    pending=list(context.tree.body);owned=False
    while pending:
        current=pending.pop()
        if current is node:owned=True;break
        if not isinstance(current,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            pending.extend(ast.iter_child_nodes(current))
    if not owned:raise ValueError('annotation statement is not owned by the original module scope')
    for source in (node,node.target,node.annotation):_module_statement_ref(context,source)
    prelude=compiler_prelude_plan(evidence.code,context.tree)
    rows=tuple(row for row in _mapping_source_instructions(context,evidence,profile=profile)
               if row.opname!='EXTENDED_ARG')
    if not rows or rows[0].offset<prelude.first_source_offset:
        raise ValueError('module annotation requires its independently modeled compiler prelude')
    at={row.offset:index for index,row in enumerate(rows)}
    own=[row for row in rows if tuple(row.positions)==_span(node)]
    stores=[row for row in rows if row.opname in ('STORE_NAME','STORE_GLOBAL')
            and row.argval==node.target.id and tuple(row.positions)==_span(node.target)]
    if len(stores)!=(node.value is not None):
        raise ValueError('annotation RHS has no unique original namespace store')
    store=stores[0] if stores else None
    future=bool(evidence.code.co_flags & __future__.annotations.compiler_flag)
    key=discard=None
    if future:
        loads=[row for row in rows if row.opname=='LOAD_CONST' and type(row.argval) is str
               and tuple(row.positions)==_span(node.annotation)]
        if len(loads)!=1:raise ValueError('future annotation lacks its exact compiler string slot')
        value=loads[0]
        if len(own)<3:raise ValueError('future annotation update sequence is incomplete')
        lookup,key,update=own[:3];stages=[value,lookup,key,update]
        if (lookup.opname!='LOAD_NAME' or lookup.argval!='__annotations__'
                or key.opname!='LOAD_CONST' or type(key.argval) is not str or key.argval!=node.target.id
                or update.opname!='STORE_SUBSCR'):
            raise ValueError('future annotation changed its original owner/key/update sequence')
        mode=Mode.FUTURE_STRING;tail=own[3:]
    else:
        if len(own)<4:raise ValueError('lazy annotation registration sequence is incomplete')
        lookup,value,update,discard=own[:4];stages=[lookup,value,update,discard]
        if (lookup.opname!='LOAD_NAME' or lookup.argval!='__conditional_annotations__'
                or value.opname not in ('LOAD_SMALL_INT','LOAD_CONST')
                or type(value.argval) is not int or value.argval<0
                or update.opname!='SET_ADD' or update.arg!=1 or discard.opname!='POP_TOP'):
            raise ValueError('lazy annotation changed its original lookup/index/set/discard sequence')
        if len(prelude.children)!=1:
            raise ValueError('lazy annotation lacks its exact deferred compiler child')
        child=evidence.code.co_consts[prelude.children[0].code_path[0]]
        child_rows=tuple(dis.get_instructions(child,adaptive=False,show_caches=False))
        registrations=[window for index in range(len(child_rows)-2)
            if len(window:=child_rows[index:index+3])==3
            and window[0].opname in ('LOAD_SMALL_INT','LOAD_CONST')
            and type(window[0].argval) is int and window[0].argval==value.argval
            and window[1].opname=='LOAD_GLOBAL' and window[1].argval=='__conditional_annotations__'
            and window[2].opname=='CONTAINS_OP' and window[2].arg==0
            and all(tuple(row.positions)==_span(node) for row in window)]
        if len(registrations)!=1:
            raise ValueError('lazy annotation index does not match this deferred child source test')
        mode=Mode.LAZY_SET;tail=own[4:]
    if tail and not (len(tail)==2 and tail[0].opname=='LOAD_CONST' and tail[0].argval is None
            and tail[1].opname=='RETURN_VALUE'):
        raise ValueError('annotation source span contains extra compiler stages')
    if any(at[right.offset]!=at[left.offset]+1 for left,right in zip(stages,stages[1:])):
        raise ValueError('annotation compiler stages are not one original contiguous window')
    if store is not None and at[stages[0].offset]!=at[store.offset]+1:
        raise ValueError('annotation update must immediately follow its successful RHS store')
    empty_dict=None
    if isinstance(node.value,ast.Dict):
        if node.value.keys or node.value.values:
            raise ValueError('module annotation dictionary RHS currently requires an empty display')
        builds=[row for row in rows if row.opname=='BUILD_MAP' and row.arg==0
                and tuple(row.positions)==_span(node.value)]
        if len(builds)!=1 or store is None or at[store.offset]!=at[builds[0].offset]+1:
            raise ValueError('empty dict RHS has no exact BUILD_MAP 0 to namespace-store sequence')
        empty_dict=builds[0]
    instructions=(([store] if store is not None else [])+stages)
    witness=ModuleAnnotationCompilerWitness(mode,evidence.root_code_layout_key,
        tuple(row.offset for row in instructions),empty_dict.offset if empty_dict else None)
    return ModuleAnnotationPlan(witness,store,lookup,value,update,key,discard,empty_dict)


def lower_module_annotation(builder,node,cursor,plan):
    """Connect original compiler operands and both completion worlds."""
    from scar.analysis.source_call_lowering import _constant
    from scar.ir.program.state_addresses import (
        AddressEffect,ReferenceOwner,NamespaceKey,Element,WholeOwner,
    )
    from scar.ir.program.model import AccessMode
    baseline=len(builder.active_temporaries)

    def hold(value,role):
        builder.frame_transition(cursor,node,((value,node,role),),P.FRAME_HOLD_TEMPORARY)
        builder.active_temporaries.append(value)

    def lookup():
        nonlocal cursor
        key=builder.literal(node,plan.lookup.argval)
        references=builder.entry_references
        cursor,owner,identity=builder.invoke(cursor,node,tuple((reference,node,role,index,None)
            for index,(reference,role) in enumerate(zip((*references,key),
                ('locals-owner','globals-owner','saved-builtins-owner','namespace-key')))))
        builder.protocol(identity,K.LOAD_NAME_314,node)
        operation=builder.operation_records[identity]
        builder._addresses(identity,tuple(AddressEffect(ReferenceOwner(operation.uses[index].id),
            (NamespaceKey(operation.uses[3].id),),AccessMode.READ) for index in range(3)))
        return owner

    def update(inputs,kind,consumed=()):
        nonlocal cursor
        def failed(failure,payload):
            saved=tuple(builder.active_temporaries)
            try:
                if consumed:
                    if tuple(builder.active_temporaries[-len(consumed):])!=consumed:
                        raise ValueError('annotation update lost its consumed stack references')
                    del builder.active_temporaries[-len(consumed):]
                builder.finish_exit(failure,node,payload,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=saved
        cursor,_,identity=builder.invoke(cursor,node,inputs,result_type=None,failure_handler=failed)
        builder.protocol(identity,kind,node)
        original=builder.operation_records[identity]
        marked=replace(original,behaviors=original.behaviors+(Behavior.MEMORY,))
        builder.operations[builder.operations.index(original)]=marked;builder.operation_records[identity]=marked
        if consumed:del builder.active_temporaries[-len(consumed):]
        return marked

    try:
        if node.value is not None:
            if plan.empty_dict is not None:
                cursor,value,identity=builder.invoke(cursor,node.value,())
                builder.protocol(identity,P.BUILD_MAP,node.value)
                original=builder.operation_records[identity]
                marked=replace(original,behaviors=original.behaviors+(Behavior.MEMORY,))
                builder.operations[builder.operations.index(original)]=marked;builder.operation_records[identity]=marked
            else:cursor,value=builder.expr(node.value,cursor)
            cursor=builder.store(node.target,value,cursor)
        if plan.witness.mode is Mode.LAZY_SET:
            owner=lookup();hold(owner,'annotation-set-owner')
            index=(_constant(builder,node,cursor,plan.value) if plan.value.opname=='LOAD_CONST'
                   else builder.literal(node,plan.value.argval))
            operation=update(((owner,node,'annotation-set-owner',0,None),
                (index,node,'annotation-index',0,None)),K.SET_ADD_314)
            builder._addresses(operation.id,(AddressEffect(ReferenceOwner(operation.uses[0].id),
                (WholeOwner(),),AccessMode.READ_WRITE),))
            builder.frame_transition(cursor,node,((owner,node,'annotation-set-owner'),),P.FRAME_RELEASE_TEMPORARY)
            builder.active_temporaries.pop()
        else:
            annotation=_constant(builder,node.annotation,cursor,plan.value)
            hold(annotation,'annotation-string')
            owner=lookup();hold(owner,'annotation-mapping-owner')
            key=_constant(builder,node,cursor,plan.key)
            operation=update(((owner,node,'annotation-mapping-owner',0,None),
                (key,node,'annotation-key',0,None),(annotation,node.annotation,'annotation-string',0,None)),
                P.STORE_SUBSCRIPT,(annotation,owner))
            builder._addresses(operation.id,(AddressEffect(ReferenceOwner(operation.uses[0].id),
                (Element(operation.uses[1].id),),AccessMode.WRITE),))
        builder.gap(GapKind.EFFECT_SUMMARY,node,
            'annotation registration uses actual namespace lookup results; lookup/update/allocation/cleanup '
            'effects and later annotation reads remain open; generated annotation child remains deferred')
        return cursor
    finally:del builder.active_temporaries[baseline:]

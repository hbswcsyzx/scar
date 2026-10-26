"""Ordered starred Tuple/List displays, using existing list primitive ports.

A display has no callee, kwargs, parameter binding or implicit function frame.
Its temporary list survives append/extend; element references are consumed on
both completions, while initial BUILD_LIST steals only on success. Tuple
conversion consumes the temporary list; a List display forwards that list.
"""
from __future__ import annotations

import ast
import dis

from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_call_lowering import _invoke, _instructions
from scar.analysis.source_heap_lowering import _source_definition, _associate
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode

KINDS=frozenset((K.BUILD_DISPLAY_LIST,K.EXTEND_DISPLAY,K.APPEND_DISPLAY,K.DISPLAY_LIST_TO_TUPLE))


def _shape(node):
    return (isinstance(node,(ast.Tuple,ast.List)) and isinstance(node.ctx,ast.Load)
        and any(isinstance(n,ast.Starred)for n in node.elts) and len(node.elts)<=30)


def _expected(node):
    if not _shape(node):raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'STARRED_DISPLAY_SHAPE_OR_LARGE_INCREMENTAL_INTERFACE_UNIMPLEMENTED')
    first=next(i for i,n in enumerate(node.elts)if isinstance(n,ast.Starred))
    stages=[(K.BUILD_DISPLAY_LIST,first,None)]
    stages.extend((K.EXTEND_DISPLAY if isinstance(n,ast.Starred)else K.APPEND_DISPLAY,1,i)for i,n in enumerate(node.elts[first:],first))
    if isinstance(node,ast.Tuple):stages.append((K.DISPLAY_LIST_TO_TUPLE,None,None))
    return stages


def _compiler(node,rows):
    expected=_expected(node);span=(node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
    names={'BUILD_LIST','BUILD_TUPLE','LIST_APPEND','LIST_EXTEND','CALL_INTRINSIC_1'}
    actual=[r for r in rows if tuple(r.positions)==span and r.opname in names]
    if len(actual)!=len(expected):raise _Unsupported(GapKind.CODE_VERSION,node,'STARRED_DISPLAY_EXACT_COMPILER_SEQUENCE_UNAVAILABLE')
    for row,(kind,arg,_)in zip(actual,expected):
        if kind is K.DISPLAY_LIST_TO_TUPLE:
            ok=row.opname=='CALL_INTRINSIC_1' and dis._intrinsic_1_descs[row.arg]=='INTRINSIC_LIST_TO_TUPLE'
        else:
            name={K.BUILD_DISPLAY_LIST:'BUILD_LIST',K.EXTEND_DISPLAY:'LIST_EXTEND',K.APPEND_DISPLAY:'LIST_APPEND'}[kind]
            ok=row.opname==name and row.arg==arg
        if not ok:raise _Unsupported(GapKind.CODE_VERSION,node,'STARRED_DISPLAY_EXACT_COMPILER_SEQUENCE_UNAVAILABLE')


def _hold(builder,cursor,node,reference,role):
    # Same ordinary lifetime transition as call expansion, with display-owned
    # roles: the call validator must not mistake an inner display for its own
    # callee/argument-packing stack.
    builder.frame_transition(cursor,node,((reference,node,'display-held-'+role),),K.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def lower_starred_display(builder,node,cursor):
    stages=_expected(node);_compiler(node,_instructions(builder,node))
    definition=_source_definition(builder,node)
    if definition.metadata.get('ast_type')!=type(node).__name__ or len(definition.output_slots)!=1:
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'STARRED_DISPLAY_ORIGINAL_CONTAINER_SOURCE_REQUIRED')
    baseline=len(builder.active_temporaries);held=[];inputs=[]
    try:
        first=stages[0][1]
        for index,child in enumerate(node.elts[:first]):
            cursor,value=builder.expr(child,cursor)
            if cursor is None:return None,None
            _hold(builder,cursor,child,value,'element');held.append((child,value));inputs.append((value,child,'element',index,None))
        cursor,container,build=_invoke(builder,cursor,node,inputs,K.BUILD_DISPLAY_LIST,tuple(held),raise_consumed=(),result=True)
        _hold(builder,cursor,node,container,'container')
        for index,argument in enumerate(node.elts[first:],first):
            child=argument.value if isinstance(argument,ast.Starred)else argument
            cursor,value=builder.expr(child,cursor)
            if cursor is None:return None,None
            _hold(builder,cursor,child,value,'element')
            cursor,_,_=_invoke(builder,cursor,node,
                ((container,node,'display-container',0,None),(value,child,'starred-element'if isinstance(argument,ast.Starred)else'element',index,None)),
                K.EXTEND_DISPLAY if isinstance(argument,ast.Starred)else K.APPEND_DISPLAY,((child,value),))
        if isinstance(node,ast.Tuple):
            cursor,result,identity=_invoke(builder,cursor,node,((container,node,'display-container',0,None),),
                K.DISPLAY_LIST_TO_TUPLE,((node,container),),result=True)
            _associate(builder,identity,node,definition,Opcode.BUILD_TUPLE)
        else:
            result=container;_transfer(builder,((node,container),),node)
            _associate(builder,build,node,definition,Opcode.BUILD_LIST)
        builder.link_value(builder.values_by_id[result],node,SourceRole.EXPRESSION)
        builder.gap(GapKind.EFFECT_SUMMARY,node,'ordered starred display construction is connected; iteration dispatch, partial mutation, finalizers, object identity and contents remain unproved inside each current-world interface')
        return cursor,result
    finally:del builder.active_temporaries[baseline:]


def validate_starred_displays(model,graph,interface,metadata,semantic,language,*,source_tree=None,options=None,structural_only=False):
    from scar.analysis.program_lowering import _REF
    from scar.analysis.source_language import require_source_tree,function_exception_types
    from scar.analysis.source_call_validation import _pop_suffix,_check_failure_pending
    from scar.analysis.source_string_validation import _ordered_next
    from scar.ir.program.model import Behavior,CompletionResult,ExitKind,ReferenceValue,StateVersionValue,TerminatorKind,value_type
    from scar.ir.program.source_language import SourceLanguageCapability as C
    selected={p.operation:p for p in model.protocols if p.kind in KINDS}
    if not selected:return set()
    def need(ok,detail):
        if not ok:raise ValueError('starred display: '+detail)
    need(C.STARRED_DISPLAY_314_V1 in language.capabilities and isinstance(source_tree,ast.Module),'capability and exact retained AST required')
    operations={o.id:o for o in graph.operations};values={v.id:v for v in graph.values};blocks={b.id:b for r in graph.regions for b in r.blocks}
    protocols={p.operation:p for p in model.protocols};links={r.operation:r for r in metadata.operation_links};uses={(r.operation,r.use):r for r in metadata.use_links}
    positions={o:(b.id,i)for b in blocks.values()for i,o in enumerate(b.operations)};world=value_type(values[interface.world])
    grouped={}
    for identity,p in selected.items():grouped.setdefault(p.source,[]).append(identity)
    for source,group in grouped.items():
        matches=[n for n in require_source_tree(source_tree,language.source,source)if isinstance(n,(ast.Tuple,ast.List))]
        need(len(matches)==1 and _shape(matches[0]),'original display shape differs')
        node=matches[0];expected=_expected(node)
        need(tuple(protocols[i].kind for i in group)==tuple(k for k,_,_ in expected),'ordered display stages differ from original AST')
        container=None;owned=set();stage_set=set(group)
        for n,(identity,(kind,count,index))in enumerate(zip(group,expected)):
            op=operations[identity];normal=blocks[op.terminator.successors[0].block]if op.terminator else None
            results=(_REF,)if kind in(K.BUILD_DISPLAY_LIST,K.DISPLAY_LIST_TO_TUPLE)else()
            arity=count if kind is K.BUILD_DISPLAY_LIST else 1 if kind is K.DISPLAY_LIST_TO_TUPLE else 2
            need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE and op.callee is None and not op.effects_complete
                 and Behavior.MEMORY in op.behaviors and len(op.uses)==arity+1 and op.invoke_arguments==tuple(u.id for u in op.uses)
                 and all(type(values[u.value])is ReferenceValue for u in op.uses[:-1])and type(values[op.uses[-1].value])is StateVersionValue,'display primitive operands/world/shape differ')
            need(tuple((c.kind,c.types)for c in op.completions)==((ExitKind.NORMAL,results+(world,)),(ExitKind.RAISE,function_exception_types(language,_REF,world)))
                 and tuple(e.kind for e in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
                 and all(e.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))for e,c in zip(op.terminator.successors,op.completions)), 'normal/raise completion ports differ')
            if kind is K.BUILD_DISPLAY_LIST:container=normal.arguments[0];children=node.elts[:count];operands=op.uses[:-1];indexes=range(count)
            elif kind is K.DISPLAY_LIST_TO_TUPLE:
                need(op.uses[0].value==container,'tuple conversion must consume its own temporary list');children=();operands=();indexes=()
            else:
                need(op.uses[0].value==container,'append/extend changed display receiver');argument=node.elts[index]
                children=(argument.value if isinstance(argument,ast.Starred)else argument,);operands=(op.uses[1],);indexes=(index,)
            for child,use,position in zip(children,operands,indexes):
                row=uses[identity,use.id];ref=row.source
                need(row.index==position and row.role==('starred-element'if kind is K.EXTEND_DISPLAY else'element')
                     and(ref.start_line,ref.end_line,ref.start_column,ref.end_column)==(child.lineno,child.end_lineno,child.col_offset,child.end_col_offset),'element source or evaluation order differs')
            owned.update(u.value for u in op.uses[:-1]);owned.update(normal.arguments[:-1])
            if n:_ordered_next(group[n-1],identity,stage_set,operations,blocks,positions)
            link=links[identity];association=kind is(K.DISPLAY_LIST_TO_TUPLE if isinstance(node,ast.Tuple)else K.BUILD_DISPLAY_LIST)
            if association:
                d=semantic.definitions.get(link.semantic_operation)
                need(d is not None and d.code_id==source.atom_id.wire and d.metadata.get('ast_type')==type(node).__name__
                     and len(d.output_slots)==1 and link.opcode is(Opcode.BUILD_TUPLE if isinstance(node,ast.Tuple)else Opcode.BUILD_LIST),'final container lost original source association')
            else:need(link.semantic_operation is None,'intermediate list stage invented a source operation')
        # Reuse the existing call-expansion suffix/paired-handoff checks. Display
        # holds are separate; no callee or call/binding qualification is added.
        ordered=list(operations);end=ordered.index(group[-1]);starts=[]
        for i,identity in enumerate(ordered[:ordered.index(group[0])+1]):
            p=protocols.get(identity);op=operations[identity]
            if p is not None and p.kind is K.FRAME_HOLD_TEMPORARY and len(op.uses)==2:
                row=uses.get((identity,op.uses[0].id))
                if row is not None and row.role=='display-held-element'and op.uses[0].value in owned:starts.append(i)
        begin=min(starts)if starts else ordered.index(group[0]);stack=();prefix=None;deferred=[]
        for identity in ordered[begin:end+1]:
            op=operations[identity];p=protocols.get(identity);kind=p.kind if p else None
            if kind is K.FRAME_HOLD_TEMPORARY and len(op.uses)==2:
                row=uses.get((identity,op.uses[0].id))
                if row is not None and op.uses[0].value in owned and (row.role=='display-held-element'or row.role=='display-held-container'and row.source==source):stack+=((identity,op.uses[0].value),)
            if op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:continue
            normal_stack=failure_stack=stack
            if identity in stage_set:
                consumed=tuple(u.value for u in op.uses[:-1])if kind in(K.BUILD_DISPLAY_LIST,K.DISPLAY_LIST_TO_TUPLE)else(op.uses[-2].value,)
                normal_stack=_pop_suffix(stack,consumed)
                if kind is not K.BUILD_DISPLAY_LIST:failure_stack=normal_stack
            failure=blocks[op.terminator.successors[1].block]
            if C.FUNCTION_TRY_314_V1 in language.capabilities:
                from scar.analysis.source_function_try_validation import exception_handoff_holds
                actual=exception_handoff_holds(failure.id,operations,protocols,blocks,uses)
            else:
                cleanup=operations[failure.operations[0]]
                need(protocols[cleanup.id].kind is K.FRAME_EXIT,'display failure lost frame cleanup')
                actual=tuple(u.value for u in cleanup.uses if uses[cleanup.id,u.id].role=='held-temporary')
            if identity in stage_set:prefix=_check_failure_pending(actual,failure_stack,prefix)
            else:deferred.append((actual,failure_stack))
            stack=normal_stack
        need(prefix is not None and (not stack if isinstance(node,ast.Tuple)else tuple(v for _,v in stack)==(container,)),'display did not transfer its result/temporary list correctly')
        for actual,local in deferred:_check_failure_pending(actual,local,prefix,exact=False)
        if not structural_only:
            need(options is not None and options.code_evidence is not None,'independent readonly CodeWitness required')
            options.code_evidence.require_definition(metadata.source,interface.definition,model.source)
            _compiler(node,tuple(dis.get_instructions(options.code_evidence.code)))
    return set(selected)

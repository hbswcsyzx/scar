"""Source-owned eager comprehension ports over ordinary core SSA/world."""
from __future__ import annotations

import ast
from scar.analysis.program_lowering import _REF
from scar.analysis.source_language import function_exception_types, require_source_tree
from scar.ir.program.model import (Behavior, BlockArgument, CompletionResult, ExitKind,
    LocalBindingValue, ReferenceValue, StateVersionValue, TerminatorKind, value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def validate_comprehensions(model,graph,interface,metadata,semantic,language,*,source_tree=None,options=None,structural_only=False):
    from scar.analysis.source_comprehension_lowering import KINDS, shape, compiler_scope
    selected={p.operation:p for p in model.protocols if p.kind in KINDS}
    if not selected:return set()
    def need(ok,detail):
        if not ok:raise ValueError('source comprehension: '+detail)
    need(C.COMPREHENSION_314_V1 in language.capabilities and isinstance(source_tree,ast.Module),'explicit capability and retained original AST required')
    ops={o.id:o for o in graph.operations};values={v.id:v for v in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks};owner={o:b for b in blocks.values()for o in b.operations}
    links={r.operation:r for r in metadata.operation_links};use_links={(r.operation,r.use):r for r in metadata.use_links}
    protocols={p.operation:p for p in model.protocols};world=value_type(values[interface.world])
    reference=lambda value:type(values[value])is ReferenceValue
    def invoke(identity,count,result_types):
        op=ops[identity]
        need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE and op.callee is None and not op.effects_complete,
             'primitive must keep incomplete ordinary normal/raise invoke')
        need(len(op.uses)==count+1 and all(reference(u.value)for u in op.uses[:-1])
             and type(values[op.uses[-1].value])is StateVersionValue and value_type(values[op.uses[-1].value])==world
             and op.invoke_arguments==tuple(u.id for u in op.uses),'ordered primitive reference/world Uses differ')
        need(tuple((c.kind,c.types)for c in op.completions)==((ExitKind.NORMAL,(*result_types,world)),
             (ExitKind.RAISE,function_exception_types(language,_REF,world)))
             and tuple(e.kind for e in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
             and all(e.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))for e,c in zip(op.terminator.successors,op.completions)),
             'primitive must preserve its own payload/world completion order')
        return op,blocks[op.terminator.successors[0].block],blocks[op.terminator.successors[1].block]
    grouped={}
    for identity,p in selected.items():grouped.setdefault(p.source,{}).setdefault(p.kind,[]).append(identity)
    for source,kinds in grouped.items():
        need(set(kinds)=={K.COMPREHENSION_BUILD,K.COMPREHENSION_NEXT,K.COMPREHENSION_ADD,K.COMPREHENSION_LEAVE}
             and all(len(v)==1 for v in kinds.values()),'one original comprehension needs exactly build/next/add/leave')
        matches=[n for n in require_source_tree(source_tree,language.source,source)if isinstance(n,(ast.ListComp,ast.SetComp,ast.DictComp))]
        need(len(matches)==1 and shape(matches[0]),'original AST scope/strict supported clause differs')
        node=matches[0];clause=node.generators[0]
        build,next_,add,leave=(kinds[k][0]for k in(K.COMPREHENSION_BUILD,K.COMPREHENSION_NEXT,K.COMPREHENSION_ADD,K.COMPREHENSION_LEAVE))
        definition=semantic.definitions.get(links[build].semantic_operation)
        need(definition is not None and definition.kind is OperationKind.OPAQUE and definition.metadata.get('ast_type')==type(node).__name__
             and definition.code_id==source.atom_id.wire and len(definition.output_slots)==1 and links[build].opcode is Opcode.OPAQUE,
             'allocation lost the original source comprehension/output')
        slots=[s.slot_id for s in semantic.slots.values()if s.owner==definition.id and s.name==clause.target.id and s.metadata.get('scope_kind')=='comprehension']
        need(len(slots)==1,'target needs one original comprehension slot')
        slot=slots[0]
        op,allocated,_=invoke(build,0,(_REF,));container=allocated.arguments[0]
        nxt,body,failure=invoke(next_,1,(_REF,));iterator=nxt.uses[0].value
        producers=[o for o in ops.values()if protocols.get(o.id) is not None and protocols[o.id].kind is K.GET_ITERATOR
            and any(e.kind is ExitKind.NORMAL and blocks[e.block].arguments[0]==iterator for e in o.terminator.successors)]
        need(len(producers)==1,'loop iterator is not the original GET_ITERATOR normal result')
        get_source=links[producers[0].id].source
        need((get_source.start_line,get_source.end_line,get_source.start_column,get_source.end_column)==
             (clause.iter.lineno,clause.iter.end_lineno,clause.iter.col_offset,clause.iter.end_col_offset),'eager iterable source differs')
        # The exhaustion matcher consumes this NEXT's original failure; a body
        # exception cannot be mistaken for natural exhaustion.
        branch=ops[failure.operations[-1]]
        need(branch.terminator is not None and branch.terminator.kind is TerminatorKind.BRANCH,'next failure lacks exhaustion split')
        match=ops[failure.operations[-2]]
        need(protocols.get(match.id) is not None and protocols[match.id].kind is K.MATCH_STOP_ITERATION
             and match.uses[0].value==failure.arguments[0] and branch.uses[0].value==match.results[0],
             'exhaustion test must use this NEXT failure/boolean')
        natural=blocks[branch.terminator.successors[0].block]
        need(owner[leave].id==natural.id,'scope cleanup is not on this natural exhaustion edge')
        # An original target binding must receive precisely this iteration's
        # item before elt evaluation; its real source slot never aliases the
        # enclosing name merely because the spellings coincide.
        bind=ops[body.operations[0]];definition_op=ops[body.operations[1]]
        need(protocols.get(bind.id) is not None and protocols[bind.id].kind is K.FRAME_BIND
             and protocols[bind.id].source==links[definition_op.id].source
             and bind.uses[1].value==body.arguments[0] and len(definition_op.results)==1
             and type(values[definition_op.results[0]])is LocalBindingValue and values[definition_op.results[0]].slot==slot
             and definition_op.uses[0].value==body.arguments[0],'target did not retain the original per-item normal reference/slot')
        target_source=links[definition_op.id].source
        need((target_source.start_line,target_source.end_line,target_source.start_column,target_source.end_column)==
             (clause.target.lineno,clause.target.end_lineno,clause.target.col_offset,clause.target.end_col_offset),'target original AST differs')
        update,after,_=invoke(add,3 if isinstance(node,ast.DictComp)else 2,())
        need(update.uses[0].value==container,'container update changed the allocated receiver')
        children=(node.key,node.value)if isinstance(node,ast.DictComp)else(node.elt,)
        for i,(child,use)in enumerate(zip(children,update.uses[1:-1])):
            row=use_links[(add,use.id)]
            need(row.role=='element' and row.index==i and(row.source.start_line,row.source.end_line,row.source.start_column,row.source.end_column)==
                 (child.lineno,child.end_lineno,child.col_offset,child.end_col_offset),'key/value or element source evaluation order differs')
        jump=ops[after.operations[-1]]
        need(jump.terminator is not None and jump.terminator.kind is TerminatorKind.JUMP
             and jump.terminator.successors[0].block==owner[next_].id,'successful update must repeat original iterator header')
        cleanup=ops[leave]
        need(cleanup.terminator is None and cleanup.callee is None and not cleanup.effects_complete
             and len(cleanup.uses)==3 and cleanup.uses[1].value==iterator and type(values[cleanup.uses[0].value])is LocalBindingValue
             and values[cleanup.uses[0].value].slot==slot and len(cleanup.accesses)==1,'scope leave must release this transient binding through the current world')
        for read in graph.binding_reads:
            use=next(u for u in ops[read.operation].uses if u.id==read.binding)
            if values[use.value].slot!=slot:continue
            link=links[read.operation];d=semantic.definitions.get(link.semantic_operation)
            need(d is not None and link.opcode is Opcode.READ and d.code_id==link.source.atom_id.wire
                 and any(e.source.id==d.id and e.target.id==slot and e.relation is SemanticRelation.READS_SLOT for e in semantic.edges.values()),
                 'scoped read does not name its exact original SG binding slot')
        if not structural_only:
            need(options is not None and options.code_evidence is not None,'independent readonly CodeWitness required')
            options.code_evidence.require_definition(metadata.source,interface.definition,model.source)
            compiler_scope(node,options.code_evidence.code)
    return set(selected)

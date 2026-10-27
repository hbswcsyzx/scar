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
    if C.COMPREHENSION_TARGETS_314_V1 in language.capabilities:
        _validate_targets(model,graph,interface,metadata,semantic,language,source_tree,options,structural_only)
        return set(selected)
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


def _validate_targets(model,graph,interface,metadata,semantic,language,source_tree,options,structural_only):
    """Validate the explicit recursive-target/paired-scope capability.

    UNPACK_FIXED's existing checker owns arity and leaf-result correspondence;
    this checker owns the surrounding iteration, current scoped bindings and
    local cleanup before the original C0/C1 propagation corridor.
    """
    from scar.analysis.source_comprehension_lowering import KINDS,shape,target_leaves,scoped_target_slots,compiler_scope
    from scar.ir.program.model import OperationResult
    def need(ok,detail):
        if not ok:raise ValueError('source comprehension targets: '+detail)
    need(C.FUNCTION_TRY_314_V1 in language.capabilities and C.FIXED_UNPACK in language.capabilities,
         'recursive targets require the existing paired propagation and fixed-unpack capabilities')
    ops={o.id:o for o in graph.operations};values={v.id:v for v in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks}
    positions={o:(b.id,i)for b in blocks.values()for i,o in enumerate(b.operations)}
    protocols={p.operation:p for p in model.protocols}
    links={r.operation:r for r in metadata.operation_links}
    use_links={(r.operation,r.use):r for r in metadata.use_links}
    world=value_type(values[interface.world]);scoped_slots=scoped_target_slots(semantic,source_tree,language)
    incoming={key:[]for key in blocks}
    for op in ops.values():
        term=op.terminator
        for edge in getattr(term,'successors',()):incoming[edge.block].append(positions[op.id])
    memo={}
    def latest(slot,block_id,stop,visiting=frozenset()):
        key=(slot,block_id,stop)
        if key in memo:return memo[key]
        need(key not in visiting,'binding cycle lacks its original slot block argument')
        block=blocks[block_id]
        for identity in reversed(block.operations[:stop]):
            found=[v for v in ops[identity].results if type(values[v])is LocalBindingValue and values[v].slot==slot]
            if found:
                need(len(found)==1,'one statement produced ambiguous scoped binding versions')
                memo[key]=frozenset(found);return memo[key]
        arguments=[v for v in block.arguments if type(values[v])is LocalBindingValue and values[v].slot==slot]
        if arguments:
            need(len(arguments)==1,'scope header duplicates its slot argument')
            memo[key]=frozenset(arguments);return memo[key]
        result=set()
        for parent,index in incoming[block_id]:
            result.update(latest(slot,parent,index+1,visiting|{key}))
        need(bool(result),'scoped binding has no preceding original definition/header')
        memo[key]=frozenset(result);return memo[key]
    def kind(identity):
        row=protocols.get(identity)
        return None if row is None else row.kind
    def invoke(identity,count,result_types):
        op=ops[identity]
        need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
             and op.callee is None and not op.effects_complete,'primitive lost its normal/raise boundary')
        need(len(op.uses)==count+1 and all(type(values[u.value])is ReferenceValue for u in op.uses[:-1])
             and type(values[op.uses[-1].value])is StateVersionValue
             and value_type(values[op.uses[-1].value])==world
             and op.invoke_arguments==tuple(u.id for u in op.uses),'ordered reference/world ports differ')
        need(tuple((c.kind,c.types)for c in op.completions)==((ExitKind.NORMAL,(*result_types,world)),
             (ExitKind.RAISE,function_exception_types(language,_REF,world)))
             and tuple(e.kind for e in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
             and all(e.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))
                     for e,c in zip(op.terminator.successors,op.completions)),
             'primitive dropped/changed the original paired completion or post-world')
        return op,blocks[op.terminator.successors[0].block],blocks[op.terminator.successors[1].block]
    packet_ops={values[packet.value].origin.operation:packet for packet in graph.exception_packets
                if isinstance(values[packet.value].origin,OperationResult)}
    def pair_handoff(block_id,start,payload):
        cursor=(block_id,start);seen=set();matched=False
        while cursor not in seen:
            seen.add(cursor);block=blocks[cursor[0]]
            need(cursor[1]<len(block.operations),'scope failure falls out before original propagation handoff')
            op=ops[block.operations[cursor[1]]]
            packet=packet_ops.get(op.id)
            if packet is not None:
                own={use.id:use for use in op.uses}
                need((own[packet.exception].value,own[packet.traceback].value)==payload,
                     'scope cleanup replaced the original exception/propagation traceback pair')
                matched=True
            term=op.terminator
            if term is None:cursor=(block.id,cursor[1]+1)
            elif term.kind in (TerminatorKind.PENDING_DISPATCH,TerminatorKind.CLEANUP_ROUTE):
                need(matched,'scope error reached pending routing without its original pair packet');return
            elif term.kind is TerminatorKind.JUMP and len(term.successors)==1:
                edge=term.successors[0]
                if not matched:
                    own={use.id:use for use in op.uses};target=blocks[edge.block]
                    forwarded=[]
                    for reference in payload:
                        indices=[i for i,argument in enumerate(edge.arguments)
                                 if argument in own and own[argument].value==reference]
                        need(len(indices)==1 and type(values[target.arguments[indices[0]]])is ReferenceValue,
                             'scope error failed to forward its exact original pair into the outer C0/C1 gate')
                        forwarded.append(target.arguments[indices[0]])
                    payload=tuple(forwarded)
                cursor=(edge.block,0)
            else:
                need(False,'scope error skipped its canonical C0/C1 pair handoff')
        need(False,'scope error cycles before its pair handoff')
    grouped={}
    for identity,p in protocols.items():
        if p.kind in KINDS:grouped.setdefault(p.source,{}).setdefault(p.kind,[]).append(identity)
    for source,kinds in grouped.items():
        need(set(kinds)==KINDS and all(len(kinds[k])==1 for k in(K.COMPREHENSION_BUILD,K.COMPREHENSION_NEXT,K.COMPREHENSION_ADD))
             and bool(kinds[K.COMPREHENSION_LEAVE]),'build/next/add/leave scope indices differ')
        matches=[n for n in require_source_tree(source_tree,language.source,source)
                 if isinstance(n,(ast.ListComp,ast.SetComp,ast.DictComp))]
        need(len(matches)==1 and shape(matches[0],recursive_targets=True),'original recursive target/clause differs')
        node=matches[0];clause=node.generators[0];leaves=target_leaves(clause.target)
        build,next_,add=(kinds[k][0]for k in(K.COMPREHENSION_BUILD,K.COMPREHENSION_NEXT,K.COMPREHENSION_ADD))
        definition=semantic.definitions.get(links[build].semantic_operation)
        need(definition is not None and definition.kind is OperationKind.OPAQUE
             and definition.code_id==source.atom_id.wire and definition.metadata.get('ast_type')==type(node).__name__
             and len(definition.output_slots)==1 and links[build].opcode is Opcode.OPAQUE,
             'comprehension lost its original source/output')
        refs={}
        for leaf in leaves:
            atoms=[a for a in semantic.source_atoms.values()if a.kind=='Name'
                   and a.reference.path==language.source.path and a.reference.fingerprint==language.source.fingerprint
                   and(a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column)==
                   (leaf.lineno,leaf.end_lineno,leaf.col_offset,leaf.end_col_offset)]
            need(len(atoms)==1 and atoms[0].reference in scoped_slots,'target leaf lacks its original source slot')
            refs[(leaf.lineno,leaf.end_lineno,leaf.col_offset,leaf.end_col_offset)]=atoms[0].reference
        slots={leaf.id:scoped_slots[refs[(leaf.lineno,leaf.end_lineno,leaf.col_offset,leaf.end_col_offset)]]for leaf in leaves}
        need(all(semantic.slots[slot].owner==definition.id for slot in slots.values()),'target was rebound into outer function scope')
        _,allocated,build_failure=invoke(build,0,(_REF,));container=allocated.arguments[0]
        nxt,body,next_failure=invoke(next_,1,(_REF,));iterator=nxt.uses[0].value
        gets=[o for o in ops.values()if kind(o.id)is K.GET_ITERATOR and o.terminator is not None
              and any(e.kind is ExitKind.NORMAL and blocks[e.block].arguments[0]==iterator for e in o.terminator.successors)]
        need(len(gets)==1,'loop iterator lost original eager GET_ITERATOR')
        get_source=links[gets[0].id].source
        need((get_source.start_line,get_source.end_line,get_source.start_column,get_source.end_column)==
             (clause.iter.lineno,clause.iter.end_lineno,clause.iter.col_offset,clause.iter.end_col_offset),
             'outer iterable source differs')
        plan=None
        if not structural_only:
            need(options is not None and options.code_evidence is not None,'independent static compiler input required')
            from scar.analysis.source_language import supports_cpython_compiler
            need(supports_cpython_compiler(options.code_evidence),'recursive target compiler protocol requires CPython 3.14.7')
            options.code_evidence.require_definition(metadata.source,interface.definition,model.source)
            plan=compiler_scope(node,options.code_evidence.code,recursive_targets=True)
        # Distinct unique names, not leaf occurrences, own saved bindings.
        need(len(set(slots.values()))==len(slots),'different names share an invented scoped slot')
        if isinstance(clause.target,(ast.Tuple,ast.List)):
            need(len(body.operations)>=2 and kind(body.operations[0])is K.FRAME_HOLD_TEMPORARY
                 and ops[body.operations[0]].uses[0].value==body.arguments[0]
                 and kind(body.operations[1])is K.UNPACK_FIXED,'NEXT item did not enter the original root unpack')
            root_unpack=ops[body.operations[1]]
            need(root_unpack.uses[0].value==body.arguments[0],'root unpack changed the exact NEXT result')
        # Ordered target binding occurrences (including repeated names). Shared
        # unpack validators separately check every N result -> child mapping.
        cursor=(body.id,0);seen=set();stored=[];unpack_pending={}
        pending_results=(body.arguments[0],)if isinstance(clause.target,(ast.Tuple,ast.List))else()
        while len(stored)<len(leaves):
            need(cursor not in seen,'target stores cycle before all original leaves');seen.add(cursor)
            block=blocks[cursor[0]];need(cursor[1]<len(block.operations),'target binding is missing')
            identity=block.operations[cursor[1]];op=ops[identity]
            if kind(identity)is K.FRAME_BIND:
                leaf=leaves[len(stored)];reference=refs[(leaf.lineno,leaf.end_lineno,leaf.col_offset,leaf.end_col_offset)]
                need(protocols[identity].source==reference and len(op.uses)==3
                     and type(values[op.uses[0].value])is LocalBindingValue and values[op.uses[0].value].slot==slots[leaf.id],
                     'leaf occurrence bound a different name/source/previous slot')
                need(latest(slots[leaf.id],block.id,cursor[1])==frozenset((op.uses[0].value,)),
                     'repeated/scoped target did not replace the latest binding')
                need(cursor[1]+1<len(block.operations),'target binding definition missing')
                defined=ops[block.operations[cursor[1]+1]]
                need(len(defined.results)==1 and type(values[defined.results[0]])is LocalBindingValue
                     and values[defined.results[0]].slot==slots[leaf.id] and len(defined.uses)==1
                     and defined.uses[0].value==op.uses[1].value,'target did not retain its ordered assigned reference')
                if isinstance(clause.target,ast.Name):need(op.uses[1].value==body.arguments[0],'Name target lost NEXT payload')
                else:
                    need(pending_results and pending_results[-1]==op.uses[1].value,
                         'leaf store changed the next published unpack result')
                    pending_results=pending_results[:-1]
                stored.append(identity);cursor=(block.id,cursor[1]+2);continue
            term=op.terminator
            if term is None:cursor=(block.id,cursor[1]+1)
            elif term.kind is TerminatorKind.INVOKE and kind(identity)is K.UNPACK_FIXED:
                need(pending_results and op.uses[0].value==pending_results[-1],
                     'nested unpack did not consume its exact next published reference')
                # UNPACK_FIXED consumes its input in either completion. On
                # failure only already-published outer siblings remain held.
                unpack_pending[identity]=tuple(reversed(pending_results[:-1]))
                normal=blocks[term.successors[0].block]
                pending_results=pending_results[:-1]+tuple(reversed(normal.arguments[:-1]))
                cursor=(normal.id,0)
            else:need(False,'target store path executes another expression before binding leaves')
        need(not pending_results,'target completed while a published unpack sibling remained held')
        update,after,_=invoke(add,3 if isinstance(node,ast.DictComp)else 2,())
        need(update.uses[0].value==container,'update changed original container')
        children=(node.key,node.value)if isinstance(node,ast.DictComp)else(node.elt,)
        for i,(child,use)in enumerate(zip(children,update.uses[1:-1])):
            row=use_links[(add,use.id)]
            need(row.role=='element' and row.index==i and(row.source.start_line,row.source.end_line,row.source.start_column,row.source.end_column)==
                 (child.lineno,child.end_lineno,child.col_offset,child.end_col_offset),'key/value/elt order differs')
        jump=ops[after.operations[-1]]
        need(jump.terminator is not None and jump.terminator.kind is TerminatorKind.JUMP
             and jump.terminator.successors[0].block==positions[next_][0],'update lost original loop backedge')
        need(len(next_failure.operations)==2,'NEXT failure acquired another error producer before exhaustion test')
        match,branch=(ops[i]for i in next_failure.operations)
        need(kind(match.id)is K.MATCH_STOP_ITERATION and match.uses[0].value==next_failure.arguments[0]
             and branch.terminator is not None and branch.terminator.kind is TerminatorKind.BRANCH
             and branch.uses[0].value==match.results[0],'only NEXT failure may select natural exhaustion')
        natural=blocks[branch.terminator.successors[0].block]
        false=blocks[branch.terminator.successors[1].block]
        # Traverse all successful scope paths; every potentially raising child
        # must pass a local leave before its pre-existing propagation corridor.
        pending=[(allocated.id,0),(natural.id,0)];visited=set();active={build};normal_leaves=set()
        while pending:
            point=pending.pop()
            if point in visited:continue
            visited.add(point);block=blocks[point[0]]
            need(point[1]<len(block.operations),'scope normal path falls through without leave')
            op=ops[block.operations[point[1]]]
            if kind(op.id)is K.COMPREHENSION_LEAVE:
                normal_leaves.add(op.id);continue
            term=op.terminator
            if term is None:pending.append((block.id,point[1]+1))
            elif term.kind is TerminatorKind.INVOKE:
                active.add(op.id);pending.extend((e.block,0)for e in term.successors if e.kind is ExitKind.NORMAL)
            elif term.kind in(TerminatorKind.JUMP,TerminatorKind.BRANCH):pending.extend((e.block,0)for e in term.successors)
            else:need(False,'scope normal path escapes before leave')
        need(len(normal_leaves)==1 and positions[next_][0] in {b for b,_ in visited},'normal exhaustion must have exactly one scope leave')
        normal_leave=next(iter(normal_leaves))
        need(positions[normal_leave][0]==natural.id,'normal scope leave is not on NEXT natural exhaustion')
        consumed=[ops[i].uses[0].value for i in natural.operations[:positions[normal_leave][1]]if kind(i)is K.FRAME_DISCARD]
        need(consumed==list(next_failure.arguments[:-1]),'natural exhaustion dropped/replaced exception or propagation traceback')
        def validate_leave(identity,failure,has_container):
            op=ops[identity];refs_used=op.uses[:-1]
            resources=[iterator]+([container]if failure and has_container else[])
            roles=['comprehension-exception-iterator'if failure else'exhausted-iterator']
            if failure and has_container:roles.append('comprehension-exception-container')
            need(op.terminator is None and not op.effects_complete and len(op.accesses)==1
                 and len(refs_used)==len(resources)+len(slots)
                 and [u.value for u in refs_used[:len(resources)]]==resources,
                 'scope cleanup changed its iterator/container or dropped binding tokens')
            names=[];seen_slots=set()
            for use,role in zip(refs_used[:len(resources)],roles):
                need(use_links[(identity,use.id)].role==role,'scope cleanup completion role differs')
            for use in refs_used[len(resources):]:
                token=values[use.value]
                need(type(token)is LocalBindingValue and token.slot in slots.values()and token.slot not in seen_slots,
                     'scope cleanup duplicates or misses a unique target binding')
                seen_slots.add(token.slot);names.append(next(name for name,slot in slots.items()if slot==token.slot))
                block,index=positions[identity]
                need(latest(token.slot,block,index)==frozenset((token.id,)),
                     'scope cleanup rolled back a partially assigned/repeated binding')
                need(use_links[(identity,use.id)].role==('comprehension-exception-binding'if failure else'scoped-binding'),
                     'scope binding cleanup role differs')
            if plan is not None:need(tuple(names)==plan['failure_order'if failure else'normal_order'],'compiler name restore order differs')
            access=op.accesses[0]
            need(access.location==values[interface.world].location and access.before==op.uses[-1].id
                 and access.after==op.results[0]and values[op.uses[-1].value].location==access.location
                 and type(values[access.after])is StateVersionValue,'scope cleanup lost current-world state chain')
        validate_leave(normal_leave,False,True)
        checked={normal_leave}
        for identity in active:
            op=ops[identity]
            failure=blocks[op.terminator.successors[1].block]
            payload=tuple(failure.arguments[:2]);start=false.id if identity==next_ else failure.id
            point=(start,0);seen=set();leave=None;released=[]
            while point not in seen:
                seen.add(point);block=blocks[point[0]]
                need(point[1]<len(block.operations),'scope error lost local cleanup')
                current=ops[block.operations[point[1]]]
                if kind(current.id)is K.COMPREHENSION_LEAVE:
                    leave=current.id;break
                need(kind(current.id)is K.FRAME_RELEASE_TEMPORARY
                     and use_links[(current.id,current.uses[0].id)].role=='function-exception-unwind',
                     'scope error ran another producer or outer cleanup before local leave')
                released.append(current.uses[0].value)
                point=(block.id,point[1]+1)
            need(leave is not None,'scope failure cycles without local leave')
            if identity in unpack_pending or identity in(build,next_,add):
                need(tuple(released)==unpack_pending.get(identity,()),
                     'failed unpack changed the remaining sibling release order or released an assigned binding again')
            validate_leave(leave,True,identity!=build);checked.add(leave)
            block,index=positions[leave]
            pair_handoff(block,index+1,payload)
        need(checked==set(kinds[K.COMPREHENSION_LEAVE]),'unowned or unreachable scope leave was inserted')
        for read in graph.binding_reads:
            use=next(u for u in ops[read.operation].uses if u.id==read.binding)
            token=values[use.value]
            if type(token)is not LocalBindingValue or token.slot not in slots.values():continue
            link=links[read.operation];definition_read=semantic.definitions.get(link.semantic_operation)
            need(definition_read is not None and link.opcode is Opcode.READ
                 and definition_read.code_id==link.source.atom_id.wire
                 and any(e.source.id==definition_read.id and e.target.id==token.slot and e.relation is SemanticRelation.READS_SLOT
                         for e in semantic.edges.values()),'scoped read escaped its original target slot')

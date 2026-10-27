"""Closed Lambda creation, captures and original expression-body validation."""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _REF
from scar.analysis.source_language import function_exception_types,require_source_tree
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import (Behavior,BlockArgument,CompletionResult,ExitKind,LiteralOrigin,
    OperationResult,ReferenceValue,StateVersionValue,TerminatorKind,value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C
from scar.ir.program.structured import PythonProtocolKind as K,StructuredBodyModel
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind,SemanticRelation


def need(condition,detail):
    if not condition:raise ValueError('Lambda expression: '+detail)


def span(node):return node.lineno,node.end_lineno,node.col_offset,node.end_col_offset
def refspan(ref):return ref.start_line,ref.end_line,ref.start_column,ref.end_column


def region_projection(model,graph,metadata,region,*,strip_parent=False):
    """Ephemeral verifier view, never a replacement artifact or source fact."""
    ids={i for b in region.blocks for i in b.operations};values={v.id for v in graph.values if v.region==region.id}
    environment=[e for e in graph.environments if e.region==region.id]
    env_ids={e.id for e in environment}
    projected=replace(graph,root=region.id,regions=(replace(region,parent=None)if strip_parent else region,),
        operations=tuple(o for o in graph.operations if o.id in ids),values=tuple(v for v in graph.values if v.id in values),
        environments=tuple(environment),function_entries=tuple(e for e in graph.function_entries if e.environment in env_ids),
        binding_definitions=tuple(r for r in graph.binding_definitions if r.value in values),
        binding_reads=tuple(r for r in graph.binding_reads if r.operation in ids),
        state_address_refinements=tuple(r for r in graph.state_address_refinements if r.site.operation in ids),
        control_scopes=(),control_ports=(),exception_packets=(),pending_completions=(),
        handled_context_domains=(),cleanup_interfaces=(),cleanup_enters=(),cleanup_resumes=(),cleanup_replacements=(),handled_context_reads=(),
        resumable_bodies=(),resumable_creates=(),frame_context_initials=(),frame_context_attaches=(),frame_context_detaches=(),
        driver_interfaces=(),raw_driver_requests=(),final_body_gates=(),body_drives=(),driver_lifecycles=(),body_outcome_commits=())
    projected_model=replace(model,region=region.id,protocols=tuple(p for p in model.protocols if p.operation in ids),
        loops=tuple(l for l in model.loops if l.region==region.id))
    projected_metadata=replace(metadata,operation_links=tuple(r for r in metadata.operation_links if r.operation in ids),
        value_links=tuple(r for r in metadata.value_links if r.value in values),
        use_links=tuple(r for r in metadata.use_links if r.operation in ids),call_targets=tuple(r for r in metadata.call_targets if r.operation in ids))
    return projected_model,projected,projected_metadata


def _check_expression(node,result,model,graph,metadata,semantic,interface):
    """Actual expression result Uses, not a source-body label or old CFG claim."""
    operations={r.id:r for r in graph.operations};values={r.id:r for r in graph.values}
    protocols={r.operation:r for r in model.protocols};links={r.operation:r for r in metadata.operation_links}
    sources={(r.operation,r.use):r for r in metadata.use_links};by_value={}
    for op in operations.values():
        if op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE:
            for edge in op.terminator.successors:
                if edge.kind is ExitKind.NORMAL:by_value[edge.block]=op
    verified=set()
    def expression(n,value):
        original=values[value]
        need(type(original)is ReferenceValue,'expression result is not a Python reference')
        if isinstance(n,ast.Constant):
            need(type(original.origin)is LiteralOrigin and type(original.origin.value)is type(n.value)
                 and original.origin.value==n.value,'literal changed its exact original value/type')
            return
        if type(original.origin)is OperationResult:op=operations[original.origin.operation]
        else:
            need(type(original.origin)is BlockArgument and original.origin.index==0,'expression lost its exact NORMAL result')
            op=by_value[original.origin.block]
        link=links[op.id];verified.add(op.id)
        need(refspan(link.source)==span(n),'expression producer lost its exact original AST occurrence')
        if isinstance(n,ast.Name):
            need(link.opcode is Opcode.READ,'Name is not its original read')
            return  # Existing binding/environment validation owns exact lexical/cell/global addressing.
        if isinstance(n,ast.Dict):
            need(protocols[op.id].kind is K.BUILD_MAP and len(n.keys)<=15 and all(k is not None for k in n.keys),
                 'Dict expression lost its original ordinary mapping construction')
            children=[(v,role,i)for i,(key,val)in enumerate(zip(n.keys,n.values))for v,role in((key,'mapping-key'),(val,'mapping-value'))]
        elif isinstance(n,ast.Call):
            need(link.opcode is Opcode.CALL,'Call lost its exact source call interface')
            children=[(n.func,'callee',0),*((a,'argument',i)for i,a in enumerate(n.args)),
                      *((k.value,'keyword:'+k.arg,i)for i,k in enumerate(n.keywords))]
        elif isinstance(n,ast.Attribute):
            need(link.opcode is Opcode.ATTRIBUTE,'Attribute lost its source interface');children=[(n.value,'receiver',0)]
        elif isinstance(n,ast.Subscript):
            need(link.opcode is Opcode.INDEX,'Subscript lost its source interface');children=[(n.value,'receiver',0),(n.slice,'index',1)]
        else:raise ValueError('Lambda expression: unsupported original expression entered the body')
        operands=op.uses[:-1]
        need(len(operands)==len(children),'expression operand arity differs from its original AST')
        for use,(child,role,index)in zip(operands,children):
            source=sources.get((op.id,use.id))
            need(source is not None and source.role==role and source.index==index and refspan(source.source)==span(child),
                 'expression original operand Use/order/source differs')
            expression(child,use.value)
    expression(node,result)
    bindings={values[r.value].origin.operation for r in graph.binding_definitions}
    for op in graph.operations:
        if op.id in verified or op.id in bindings:continue
        marker=protocols.get(op.id)
        need(op.terminator is not None and op.terminator.kind in(TerminatorKind.RETURN,TerminatorKind.RAISE)
             or marker is not None and marker.kind in(K.FRAME_ENTER,K.FRAME_EXIT,K.FRAME_HOLD_TEMPORARY,K.FRAME_RELEASE_TEMPORARY),
             'unclaimed executable operation in Lambda expression body')


def validate_lambda_regions(model,graph,interface,metadata,semantic,control,language,*,
                            source_tree=None,options=None,structural_only=False,sealed_source=None):
    records={r.creation:r for r in language.lambda_bodies}
    makes={r.operation for r in model.protocols if r.kind is K.MAKE_LAMBDA_FUNCTION}
    need(len(records)==len(language.lambda_bodies) and set(records)==makes,'Lambda creation/body coverage differs')
    if not records:return set()
    need(C.LAMBDA_EXPRESSION_314_V1 in language.capabilities and isinstance(source_tree,ast.Module),
         'explicit expression-body capability and exact original AST required')
    operations={r.id:r for r in graph.operations};values={r.id:r for r in graph.values}
    regions={r.id:r for r in graph.regions};blocks={b.id:b for r in graph.regions for b in r.blocks}
    owners={i:r.id for r in graph.regions for b in r.blocks for i in b.operations}
    protocols={r.operation:r for r in model.protocols};links={r.operation:r for r in metadata.operation_links}
    sources={(r.operation,r.use):r for r in metadata.use_links};constants={r.operation:r for r in language.constants}
    environments={e.id:e for e in graph.environments};layouts={e.environment:e for e in graph.function_entries}
    root_env=next(e for e in graph.environments if e.region==graph.root)
    parent_cells={m.reference for m in root_env.members if m.role is EnvironmentRole.CAPTURED_CELL}
    own_cells=[blocks[o.terminator.successors[0].block].arguments[0]for p in model.protocols
        if p.kind is K.MAKE_CELL and owners[p.operation]==graph.root and(o:=operations[p.operation])is not None]
    parent_cells.update(own_cells);world=value_type(values[interface.world]);delegated=set();body_regions=set()
    for identity,record in records.items():
        need(owners[identity]==graph.root,'only the original creating frame owns the creation interface')
        nodes=[n for n in require_source_tree(source_tree,language.source,record.source)if isinstance(n,ast.Lambda)]
        need(len(nodes)==1,'original Lambda AST/source is missing or ambiguous');node,=nodes
        bodies=[d for d in semantic.definitions.values()if d.code_id==record.source.atom_id.wire
                and record.source.atom_id in d.source_atoms and d.metadata.get('phase')=='call_time'
                and d.kind in(OperationKind.FUNCTION,OperationKind.METHOD)]
        declarations=[d for d in semantic.definitions.values()if d.code_id==record.source.atom_id.wire
                and record.source.atom_id in d.source_atoms and d.metadata.get('phase')=='definition_time']
        need(len(bodies)==len(declarations)==1 and record.body.definition==bodies[0].id
             and links[identity].semantic_operation==declarations[0].id and links[identity].opcode is None,
             'creation/body must reference original SG phases/IDs, never a fabricated callable definition')
        need(len(bodies[0].output_slots)==1 and semantic.slots[bodies[0].output_slots[0]].name=='$return'
             and semantic.slots[bodies[0].output_slots[0]].owner==bodies[0].id,
             'Lambda body lost its original semantic return slot')
        region=regions[record.body.region];body_regions.add(region.id)
        environment=environments[record.environment];layout=layouts[record.environment]
        need(region.id!=graph.root and region.parent==graph.root and environment.region==region.id
             and environment.code_definition==record.body.definition and layout.parameters==record.body.parameters,
             'deferred body/entry/environment ownership differs')
        op=operations[identity]
        need(op.callee is None and not op.effects_complete and op.terminator is not None
             and op.terminator.kind is TerminatorKind.INVOKE
             and op.invoke_arguments==tuple(u.id for u in op.uses)
             and all(type(values[u.value])is ReferenceValue for u in op.uses[:-1])
             and tuple((c.kind,c.types)for c in op.completions)==((ExitKind.NORMAL,(_REF,world)),
                 (ExitKind.RAISE,function_exception_types(language,_REF,world))),
             'creation has only its function payload/world; it cannot execute child or assert purity')
        read=operations[record.code_constant];constant=constants[read.id]
        need(protocols[read.id].kind is K.READ_CODE_CONSTANT and constant.source==record.source
             and len(constant.constant_path)==1 and len(read.results)==1 and read.terminator is None
             and read.behaviors==(Behavior.READ,) and not read.effects_complete,
             'child code must remain an original nonexecuting code-table reference')
        args=op.uses[:-1];roles=[sources[identity,u.id]for u in args]
        need(len(args)>=2 and [(r.role,r.index)for r in roles[:2]]==[('lambda-code',0),('lambda-globals',0)]
             and args[0].value==read.results[0] and args[1].value==root_env.members[1].reference,
             'Lambda factory changed original code/globals inputs')
        cursor=2
        for i,default in enumerate(node.args.defaults):
            need(cursor<len(args)and(roles[cursor].role,roles[cursor].index)==('lambda-default',i)
                 and refspan(roles[cursor].source)==span(default),'positional default evaluation/source order differs');cursor+=1
        for i,(parameter,default)in enumerate(zip(node.args.kwonlyargs,node.args.kw_defaults)):
            if default is None:continue
            need(cursor<len(args)and(roles[cursor].role,roles[cursor].index)==('lambda-keyword-default:'+parameter.arg,i)
                 and refspan(roles[cursor].source)==span(default),'keyword default evaluation/source order differs');cursor+=1
        closure=args[cursor:]
        need(len(closure)==len(environment.members)-5 and all(u.value in parent_cells for u in closure)
             and [(r.role,r.index)for r in roles[cursor:]]==[('lambda-closure-cell',i)for i in range(len(closure))],
             'capture substituted contents/foreign cells or changed order')
        from scar.ir.program.lambda_bodies import LambdaEnvironmentField
        need(tuple(c.formal for c in record.captures)==tuple(m.reference for m in environment.members)
             and record.captures[0].normal_result==0 and record.captures[1].source_use==args[1].id
             and tuple(c.created_field for c in record.captures[2:5])==tuple(LambdaEnvironmentField)
             and tuple(c.source_use for c in record.captures[5:])==tuple(u.id for u in closure)
             and all(c.normal_result is None for c in record.captures[5:]),'entry captures differ from creation NORMAL ports/original Uses')
        if not structural_only:
            from scar.analysis.source_lambda_lowering import compiler_lambda
            from scar.analysis.environment_lowering import captured_cell_slot
            evidence=options.code_evidence
            need(evidence is not None,'independent readonly parent CodeWitness required')
            load,child=compiler_lambda(node,evidence.code)
            need(constant.code_key==evidence.code_layout_key and constant.constant_path==(load.arg,),
                 'Lambda code constant differs from original parent slot')
            transient={r.name for r in language.compiler_locals if r.category=='COMPREHENSION_TRANSIENT'}
            names=tuple(n for n in evidence.code.co_cellvars if n not in transient)
            need(len(names)==len(own_cells),'parent cell layout differs')
            by_name=dict(zip(names,own_cells));by_name.update(zip(evidence.code.co_freevars,(m.reference for m in root_env.members[5:])))
            need(tuple(u.value for u in closure)==tuple(by_name[n]for n in child.co_freevars),
                 'Lambda did not capture exact original compiler-ordered cell identities')
            need(tuple(m.cell_slot for m in environment.members[5:])==tuple(captured_cell_slot(record.body.definition,n)for n in child.co_freevars),
                 'child free-cell interface differs from original code/definition')
        child_model,child_graph,child_metadata=region_projection(model,graph,metadata,region,strip_parent=True)
        child_model=replace(child_model,definition=record.body.definition,source=record.source)
        from scar.analysis.structured_lowering import _require_valid_structured_body
        _require_valid_structured_body(child_model,child_graph,record.body,child_metadata,
            semantic=semantic,control=control,sealed_source=sealed_source,language=None,source_tree=source_tree,
            structural_only=True)
        normals=[o for o in child_graph.operations if o.terminator is not None and o.terminator.kind is TerminatorKind.RETURN]
        need(len(normals)==1,'ordinary expression body must retain one actual NORMAL return site')
        terminal=normals[0];own={u.id:u for u in terminal.uses}
        result=own[terminal.terminator.values[0]].value
        need(len(terminal.terminator.values)==2 and type(values[result])is ReferenceValue
             and type(values[own[terminal.terminator.values[1]].value])is StateVersionValue,
             'Lambda normal exit must separate its Python payload from world')
        _check_expression(node.body,result,child_model,child_graph,child_metadata,semantic,record.body)
        atoms={(type(n).__name__,span(n))for n in ast.walk(node.body)if hasattr(n,'end_lineno')and n.end_lineno is not None}
        need(not any(owners[l.operation]==graph.root and(semantic.source_atoms[l.source.atom_id].kind,refspan(l.source))in atoms
                     for l in metadata.operation_links),'creating frame eagerly executed the deferred body expression')
        delegated.update((identity,read.id))
    need(len(body_regions)==len(records),'Lambda body Region reused by different source creations')
    return delegated


def root_projection(model,graph,metadata,language,delegated):
    removed={r.body.region for r in language.lambda_bodies}
    kept={i for r in graph.regions if r.id not in removed for b in r.blocks for i in b.operations}
    values={v.id for v in graph.values if v.region not in removed}
    environments=tuple(e for e in graph.environments if e.region not in removed);envs={e.id for e in environments}
    graph=replace(graph,regions=tuple(r for r in graph.regions if r.id not in removed),
        operations=tuple(o for o in graph.operations if o.id in kept),values=tuple(v for v in graph.values if v.id in values),
        environments=environments,function_entries=tuple(e for e in graph.function_entries if e.environment in envs),
        binding_definitions=tuple(r for r in graph.binding_definitions if r.value in values),
        binding_reads=tuple(r for r in graph.binding_reads if r.operation in kept),
        state_address_refinements=tuple(r for r in graph.state_address_refinements if r.site.operation in kept))
    model=replace(model,protocols=tuple(p for p in model.protocols if p.operation in kept and p.operation not in delegated))
    metadata=replace(metadata,operation_links=tuple(r for r in metadata.operation_links if r.operation in kept),
        value_links=tuple(r for r in metadata.value_links if r.value in values),
        use_links=tuple(r for r in metadata.use_links if r.operation in kept),call_targets=tuple(r for r in metadata.call_targets if r.operation in kept))
    language=replace(language,constants=tuple(r for r in language.constants if r.operation not in delegated),lambda_bodies=())
    return model,graph,metadata,language


__all__=['validate_lambda_regions','root_projection']

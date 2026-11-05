"""Connect standard exec code-value alternatives to verified F4 root graphs.

The graph contains namespace selection, conditional builtins insertion,
closure checks, audit, a shared body call and discard/release. None selection
uses identity predicates. Protocol values never impersonate source ports.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import source_f4_variants as f4,source_execution,source_compiled_values as compiled
from scar.analysis import source_context_variants,source_compilation_contexts
from scar.analysis import source_symbol_variants
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.effects import ActionLabel as L
from scar.ir.literals import PythonLiteral
from scar.ir.program import source_exec_roots as X,source_execution as E,source_compiled_values as C
from scar.ir.program import source_context_variants as CV,normal_graph as G,normal_targets as T,normal_links as F
from scar.ir.program.source_template_links import SourceTemplateGraph
from scar.ir.program.control import LanguageCompletionKind as K
from scar.ir.program.model import ValueType,ValueKind
from scar.ir.program import source_productions as P
from scar.ir.record_codec import encode,decode


def _conditions(*groups):
    return tuple(dict.fromkeys(value for group in groups for value in group))


def _none_cases(argument):
    if argument.literal is not None:
        return ((argument.literal.to_python() is None,()),)
    if argument.source is not None:
        return ((True,(X.ExecPredicate('IS_NONE_IDENTITY',argument.source),)),
                (False,(X.ExecPredicate('IS_NOT_NONE_IDENTITY',argument.source),)))
    return ()


def exec_root_connections(boundary,candidate,root_template,root,free_variables,*,frame_kind=None,code_use=None):
    """Conditional protocol graph, not proof that this alternative executes."""
    if boundary.builtin is not E.SourceBuiltin.EXEC or boundary.binding is T.ArgumentBinding.NOT_MODELED:
        return (),()
    params={p.name:p for p in boundary.parameters}
    pending=[]
    if free_variables:
        return (),(X.ExecRootObligation(boundary.site.result,'ROOT_ABI_HAS_NO_CLOSURE_CELL_PARAMETERS'),)
    closure=params['closure']
    closure_cases=[predicates for is_none,predicates in _none_cases(closure) if is_none]
    if not closure_cases:
        return (),(X.ExecRootObligation(boundary.site.result,'ZERO_FREEVAR_CODE_REQUIRES_CLOSURE_NONE'),)
    if len(root_template.parameters)!=3:
        raise ValueError('exec root must have globals/locals/world parameters')
    if any(type(t) is not ValueType or t.kind is not kind for t,kind in
            zip(root_template.parameters,(ValueKind.REFERENCE,ValueKind.REFERENCE,ValueKind.STATE))):
        raise ValueError('exec root namespace/state parameter types differ')
    normal=[c for c in root_template.completions if c.kind is K.RETURN]
    if len(normal)!=1:
        raise ValueError('exec root must expose one normal return ABI')
    completion=normal[0]
    state=[i for i,t in enumerate(completion.types) if type(t) is ValueType and t.kind is ValueKind.STATE]
    if len(state)!=1:
        raise ValueError('exec normal return needs its state result')
    namespace=root.owner.unit
    if root.template!=root_template.key or root.region!=root_template.root:
        raise ValueError('exec root witness differs from original template interface')
    site=boundary.site
    gp=lambda kind,i=0,completed=None:T.GlobalPort(namespace,G.Port(root_template.key,root_template.root,kind,i,completed))
    input_ports=tuple(gp(G.PortKind.PARAMETER,i) for i in range(3))
    root_enter=gp(G.PortKind.ENTER)
    root_exit=gp(G.PortKind.EXIT,completed=K.RETURN)
    root_world=gp(G.PortKind.RESULT,state[0],K.RETURN)
    caller_enter=T.GlobalPort(site.result.unit,G.Port(site.result.port.template,site.result.port.owner,G.PortKind.ENTER))
    caller_exit=T.GlobalPort(site.result.unit,G.Port(site.result.port.template,site.result.port.owner,
        G.PortKind.EXIT,completion=site.result.port.completion))
    results=[]
    for gnone,gpred in _none_cases(params['globals']):
        for lnone,lpred in _none_cases(params['locals']):
            for closure_pred in closure_cases:
                predicates=(*gpred,*lpred,*closure_pred,X.ExecPredicate('COMPILED_CODE_HAS_NO_FREEVARS'))
                if not gnone:predicates+= (X.ExecPredicate('PYDICT_CHECK_ACCEPTS_VALUE',params['globals'].source),)
                if not lnone:predicates+= (X.ExecPredicate('PYMAPPING_CHECK_ACCEPTS_VALUE',params['locals'].source),)
                branch=('CALLER_GLOBALS' if gnone else 'EXPLICIT_GLOBALS')+'/'+('DEFAULT_LOCALS' if lnone else 'EXPLICIT_LOCALS')
                identity=sha256(_json(encode(dict(site=site.result,candidate=candidate.id,
                    namespace=namespace,case=branch),record_tags=P.PRODUCTION_RECORD_TAGS))).hexdigest()
                protocol=lambda role:X.ExecProtocolValue(site.result,identity,role,boundary.owner)
                if gnone:
                    globals=X.ExecNamespaceSelection(X.ExecNamespaceKind.CALLER_GLOBALS,
                        protocol('CALLER_GLOBALS'),boundary.owner,frame_kind,'FRAME_GLOBALS_REFERENCE',gpred)
                else:
                    globals=X.ExecNamespaceSelection(X.ExecNamespaceKind.EXPLICIT_VALUE,
                        params['globals'].source,None,None,'EXPLICIT_DICT_REFERENCE',gpred)
                if not lnone:
                    locals=X.ExecNamespaceSelection(X.ExecNamespaceKind.EXPLICIT_VALUE,
                        params['locals'].source,None,None,'EXPLICIT_MAPPING_REFERENCE',lpred)
                elif not gnone:
                    locals=X.ExecNamespaceSelection(X.ExecNamespaceKind.EXPLICIT_VALUE,
                        globals.value,None,None,'SAME_REFERENCE_AS_EXPLICIT_GLOBALS',lpred)
                else:
                    optimized=frame_kind in ('FUNCTION','LAMBDA','COMPREHENSION','GENERATOR_EXPRESSION')
                    representation=('OPTIMIZED_FRAME_LOCALS_NEW_DICT_SNAPSHOT' if optimized else
                        'FRAME_LOCALS_MAPPING' if frame_kind in ('ROOT_EXEC','ROOT_EVAL','ROOT_INTERACTIVE','CLASS')
                        else 'FRAME_LOCALS_MAPPING_OR_OPTIMIZED_SNAPSHOT')
                    locals=X.ExecNamespaceSelection(X.ExecNamespaceKind.CALLER_LOCALS,
                        protocol('CALLER_LOCALS'),boundary.owner,frame_kind,representation,lpred)
                actions=[];edges=[];world=site.world;control=caller_enter
                def action(phase,labels,reads,writes=(),conditions=(),inputs=(),outputs=()):
                    nonlocal world,control
                    out_world=protocol('WORLD_AFTER_'+phase.value)
                    enter=protocol('CONTROL_ENTER_'+phase.value);leave=protocol('CONTROL_EXIT_'+phase.value)
                    edges.append(X.ExecGraphEdge(control,enter,G.EdgeKind.CONTROL,G.Transition.DIRECT))
                    actions.append(X.ExecProtocolAction(phase,world,out_world,enter,leave,labels,reads,writes,
                        inputs=inputs,outputs=outputs,conditions=conditions))
                    world,control=out_world,leave
                action(X.ExecPhase.NAMESPACE_SELECTION,(L.STATE,L.MEM,L.CTRL),
                    ('CALLER_FRAME_AND_ARGUMENTS',),('DEFAULT_OPTIMIZED_LOCALS_SNAPSHOT_IF_REQUIRED',),
                    inputs=tuple(p.source for name,p in params.items() if name in ('globals','locals') and p.source is not None),
                    outputs=tuple(v for v in (globals.value,locals.value,protocol('CALLER_BUILTINS'))
                        if type(v) is X.ExecProtocolValue))
                action(X.ExecPhase.ENSURE_BUILTINS,(L.STATE,L.CTRL),('GLOBALS_BUILTINS_KEY','CALLER_FRAME_BUILTINS'),
                    ('INSERT_CURRENT_BUILTINS_ONLY_IF_GLOBALS_KEY_ABSENT',),
                    inputs=(globals.value,protocol('CALLER_BUILTINS')))
                action(X.ExecPhase.CHECK_CLOSURE,(L.STATE,L.CTRL),('CODE_FREEVARS','CLOSURE_ARGUMENT'),
                    inputs=tuple(p.source for name,p in params.items() if name in ('source','closure') and p.source is not None))
                action(X.ExecPhase.AUDIT,(L.STATE,L.IO,L.CTRL),('CODE_VALUE','AUDIT_HOOKS'),
                    inputs=tuple(p.source for name,p in params.items() if name=='source' and p.source is not None))
                body_world=protocol('WORLD_AFTER_BODY');body_enter=protocol('CONTROL_ENTER_BODY');body_exit=protocol('CONTROL_EXIT_BODY')
                edges.extend((X.ExecGraphEdge(control,body_enter,G.EdgeKind.CONTROL,G.Transition.DIRECT),
                    X.ExecGraphEdge(body_enter,root_enter,G.EdgeKind.CONTROL,G.Transition.CALL),
                    X.ExecGraphEdge(globals.value,input_ports[0],G.EdgeKind.DATA,G.Transition.CALL),
                    X.ExecGraphEdge(locals.value,input_ports[1],G.EdgeKind.DATA,G.Transition.CALL),
                    X.ExecGraphEdge(world,input_ports[2],G.EdgeKind.STATE,G.Transition.CALL),
                    X.ExecGraphEdge(root_world,body_world,G.EdgeKind.STATE,G.Transition.RETURN),
                    X.ExecGraphEdge(root_exit,body_exit,G.EdgeKind.CONTROL,G.Transition.RETURN)))
                actions.append(X.ExecProtocolAction(X.ExecPhase.BODY,world,body_world,body_enter,body_exit,
                    (L.CTRL,L.STATE),('COMPILED_ROOT_AND_NAMESPACES',),inputs=(globals.value,locals.value)))
                world,control=body_world,body_exit
                action(X.ExecPhase.DISCARD_AND_RELEASE,(L.MEM,L.STATE,L.CTRL),
                    ('BODY_RETURN_VALUE','TEMPORARY_REFERENCES'),('RELEASE_TEMPORARY_REFERENCES',),
                    inputs=tuple(protocol('DISCARD_BODY_RESULT_'+str(i)) for i in range(len(completion.types)) if i!=state[0]),
                    outputs=(site.result,))
                for i in range(len(completion.types)):
                    if i!=state[0]:edges.append(X.ExecGraphEdge(gp(G.PortKind.RESULT,i,K.RETURN),
                        protocol('DISCARD_BODY_RESULT_'+str(i)),G.EdgeKind.DATA,G.Transition.RETURN))
                edges.extend((X.ExecGraphEdge(world,site.result_world,G.EdgeKind.STATE,G.Transition.RETURN),
                    X.ExecGraphEdge(control,caller_exit,G.EdgeKind.CONTROL,G.Transition.RETURN)))
                results.append(X.ExecRootConnection(identity,site,boundary.owner,candidate.id,root,globals,locals,
                    predicates,tuple(actions),tuple(edges),PythonLiteral.from_python(None),tuple(free_variables),
                    _conditions(boundary.conditions,candidate.conditions,() if code_use is None else code_use.conditions,
                        ('COMPILED_CODE_REFERENCE_VERSION_SELECTED','STANDARD_EXEC_CODE_BRANCH_COMPLETES_NORMALLY',
                         'NO_RUNTIME_INVOCATION_OR_NAMESPACE_VERSION_IDENTITY_CLAIM')),code_use=code_use))
    if not results:pending.append(X.ExecRootObligation(site.result,'EXEC_NAMESPACE_PACK_VALUE_BINDING_OPEN'))
    return tuple(results),tuple(pending)


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('f4',f4),('builtins',source_execution),('compiled',compiled),('contexts',source_context_variants),
        ('compiler_digest',source_compilation_contexts),('table_reader',source_symbol_variants),('types',X))}


def build_exec_roots(facts,executions,compiled_sources,f4_graphs,out):
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh exec root output required')
    store=SourceFactStore(facts)
    er,ers,eref=compiled._overlay(executions,'scar.source-builtin-execution',source_execution,E,
        {'boundaries':E.SourceBuiltinInvocation,'compiled-code-uses':E.CompiledCodeUse})
    cr,crs,cref=compiled._overlay(compiled_sources,'scar.source-compiled-values',compiled,C,
        {'candidates':C.CompiledSourceCandidate})
    fp=Path(f4_graphs).absolute();fraw=(fp/'result.json').read_bytes();fr=json.loads(fraw)
    if ((fr['schema'],fr['schema_version'])!=('scar.source-f4-variants',1)
            or fr['implementation_sha256']!=sha256(Path(f4.__file__).read_bytes()).hexdigest() or fr['pins']!=f4.pins()):
        raise ValueError('F4 variant producer differs')
    if (cr['source_execution']!=eref or any(r['source_facts_sha256']!=sha256(store.raw).hexdigest() for r in (er,cr,fr))):
        raise ValueError('exec source/compiler/graph parents differ')
    sp=Path(fr['compiler_symbols']['path']);sraw=(sp/'result.json').read_bytes()
    if sha256(sraw).hexdigest()!=fr['compiler_symbols']['sha256']:raise ValueError('F4 compiler-symbol parent differs')
    sr=json.loads(sraw);cp=Path(sr['context_variants']['path']);craw=(cp/'result.json').read_bytes()
    if sha256(craw).hexdigest()!=sr['context_variants']['sha256']:raise ValueError('C1 context parent differs')
    contexts=json.loads(craw)
    contexts_data={n:f4.S._variant(cp,d) for n,d in contexts['variants'].items()}
    initial_pins=pins();producer_sha=sha256(Path(__file__).read_bytes()).hexdigest()
    snapshots=[(fp/'result.json',fraw),(sp/'result.json',sraw),(cp/'result.json',craw)]
    for ref in (eref,cref):
        path=Path(ref['path'])/'result.json';raw=path.read_bytes()
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('exec parent changed during admission')
        snapshots.append((path,raw))
    connections=[];obligations=[]
    caller=store.load(er['unit'])
    from scar.analysis.static_query import _Fragments
    caller_manifest=Path(store.model_for(caller.unit))/'manifest.json'
    snapshots.append((caller_manifest,caller_manifest.read_bytes()))
    caller_context=_Fragments(store.model_for(caller.unit)).read(store.model_units[caller.unit]['artifacts']['source_contexts'])
    for namespace,descriptor in fr['variants'].items():
        ctx_doc=contexts_data[namespace];context=decode(CV.SourceContextVariant,ctx_doc)
        graph_rows=_table(fp/descriptor['path'],descriptor['tables']['templates'])
        graph=decode(SourceTemplateGraph,graph_rows[0],record_tags=P.PRODUCTION_RECORD_TAGS)
        facts_rows=_table(fp/descriptor['path'],descriptor['tables']['facts'])
        primitive=decode(F.UnitFacts,facts_rows[0],record_tags=P.PRODUCTION_RECORD_TAGS)
        if primitive.unit!=namespace or graph.unit!=namespace:
            raise ValueError('exec root graph namespace differs')
        root_template=next(n for n in graph.templates if n.key.purpose is P.ProductionPurpose.ROOT)
        for candidate in crs['candidates']:
            if (candidate.source_unit!=context.source_unit or candidate.context!=context.context
                    or candidate.code_digest!=context.code_digest
                    or candidate.text_utf8_sha256!=context.text_utf8_sha256):continue
            # A compiled source top-level module root has no closure cells.
            # C1 admits only module flags; no extracted/replaced function code
            # is silently treated as such a root.
            if context.context.compiled_code_flags & ~context.context.compiled_future_flags:
                raise ValueError('exec graph has a non-module compilation root')
            for use in ers['compiled-code-uses']:
                if use.producer!=candidate.compile_result:continue
                for boundary in ers['boundaries']:
                    if boundary.builtin is not E.SourceBuiltin.EXEC or boundary.site.result!=use.exec_result:continue
                    actual=next(p.source for p in boundary.parameters if p.name=='source')
                    if actual!=use.consumer or boundary.owner.unit!=caller.unit:
                        raise ValueError('exec code-use actual source or owner differs')
                    frame_kind=caller_context['scopes'][boundary.owner.ordinal]['kind']
                    edges,pending=exec_root_connections(boundary,candidate,root_template,primitive.root_scope,(),
                        frame_kind=frame_kind,code_use=use)
                    connections.extend(edges);obligations.extend(pending)
    _durable_mkdir(out)
    from scar.analysis.normal_output import write_table
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,rows in
        (('connections',connections),('obligations',obligations))}
    if ((store.path/'result.json').read_bytes()!=store.raw or any(path.read_bytes()!=raw for path,raw in snapshots)
            or pins()!=initial_pins or sha256(Path(__file__).read_bytes()).hexdigest()!=producer_sha):
        raise ValueError('exec graph inputs or producer changed during construction')
    result=dict(schema='scar.source-exec-roots',schema_version=1,status='CONDITIONAL_EXEC_ROOT_GRAPHS_CONNECTED',
        source_facts=str(store.path),source_facts_sha256=sha256(store.raw).hexdigest(),source_execution=eref,
        compiled_sources=cref,f4_graphs=dict(path=str(fp),sha256=sha256(fraw).hexdigest()),tables=tables,
        connections=len(connections),runtime_dispatch_verified=False,namespace_contents_propagated=False,
        profile='NORMAL_SUCCESS',exception_completions_connected=False,target_executed=False,first_stage_complete=False,
        implementation_sha256=producer_sha,pins=initial_pins)
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('facts','executions','compiled-sources','f4-graphs','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(build_exec_roots(args.facts,args.executions,args.compiled_sources,args.f4_graphs,args.out)),flush=True)


if __name__=='__main__':main()

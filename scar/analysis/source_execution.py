"""Lower known standard compile/exec interfaces without executing source.

Builtin candidates follow original namespace/reference edges, not a call's
spelling. Every boundary retains its full call ABI and world ports. Source
payload interpretation and compiled body selection remain separate tasks.
"""
from collections import defaultdict, deque
from hashlib import sha256
import argparse
import ast
import builtins
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_containers import ContainerFlow
from scar.analysis.source_interface_store import SourceInterfaceStore
from scar.analysis.source_pack_shapes import StaticPackShapes, StaticPackShape
from scar.analysis.source_launch import read_script_entry
from scar.analysis.static_query import _Fragments
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.call_compilation import supported_future_flag_mask
from scar.ir.literals import PythonLiteral
from scar.ir.program import source_execution as X, normal_links as F, normal_targets as T
from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.program.python_bindings import SourceCallSite
from scar.ir.record_codec import decode


def _reach(adjacency, seeds):
    reached=set(seeds);pending=deque(seeds)
    while pending:
        for target in adjacency.get(pending.popleft(), ()):
            if target not in reached:reached.add(target);pending.append(target)
    return reached


def source_builtin_boundaries(store, unit, *, interfaces=None, entry=None):
    """Build a unit-local overlay; no program scope is activated or unrolled."""
    if entry is not None and entry.source.unit!=unit.unit:
        raise ValueError('entry context belongs to another original source unit')
    syntax=_Fragments(store.model_for(unit.unit)).read(
        store.model_units[unit.unit]['artifacts']['source_syntax'])
    runtime=syntax['profile']['runtime']
    if (tuple(runtime['version'])!=tuple(sys.version_info)
            or runtime['implementation']!=sys.implementation.name):
        raise ValueError('builtin signature metadata must match the retained source runtime')
    if entry is not None and (entry.root!=unit.root_scope
            or entry.source.raw_sha256!=syntax['input']['raw_sha256']):
        raise ValueError('declared caller context differs from its original source version')
    fields={r['name']:{n:i for i,n in enumerate(r['fields'])} for r in syntax['profile']['ast_schema']}
    nodes=syntax['nodes'];ports={}
    def gp(index):
        if index not in ports:
            port=unit.ports[index]
            if type(port) is dict:port=decode(G.Port,port,record_tags=P.PRODUCTION_RECORD_TAGS)
            ports[index]=T.GlobalPort(unit.unit,port)
        return ports[index]
    def field(node,name):return node['fields'][fields[node['constructor']][name]]
    def scalar(node,name):return decode(PythonLiteral,field(node,name)['scalar']).to_python()
    adjacency=defaultdict(set)
    for source,target in unit.aliases:adjacency[source].add(target)
    for access in unit.names:
        ns=access.namespace;channel=('namespace',ns.kind,ns.owner,ns.name)
        adjacency[access.value if access.write else channel].add(channel if access.write else access.value)
    modules=_reach(adjacency,[x.value for x in unit.imports if x.module=='builtins'])
    candidates={}
    for kind in X.SourceBuiltin:
        seeds=[a.value for a in unit.names if not a.write
            and a.namespace.kind is F.NamespaceKind.BUILTINS and a.namespace.name==kind.value]
        seeds.extend(a.value for a in unit.attributes if a.receiver in modules
            and a.name==kind.value and a.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER))
        candidates[kind]=_reach(adjacency,seeds)
    owners={i:group.owner for group in unit.scope_groups for span in group.tables
        if span.table is F.FactTable.CALLS for i in range(span.start,span.stop)}
    # Only immutable source metadata is needed for pack shape projection.
    state=SimpleNamespace(units=[unit],offsets={unit.unit:0},writes={},
        interface_store=interfaces,values=defaultdict(set))
    shapes=StaticPackShapes(ContainerFlow(state,[]))
    invocations=[];compilations=[];exec_arguments=[];compile_results=[]
    for index,call in enumerate(unit.calls):
        selected=[kind for kind,points in candidates.items() if call.callee in points]
        if not selected:continue
        site=SourceCallSite(gp(call.callee),tuple(map(gp,call.positional)),
            tuple((name,gp(p)) for name,p in call.keywords),gp(call.result),gp(call.world),gp(call.result_world),
            None if call.positional_pack is None else gp(call.positional_pack),
            None if call.keyword_pack is None else gp(call.keyword_pack))
        positional=list(call.positional);keywords=dict(call.keywords);dependencies=set();opened=False;collision=''
        binding=T.ArgumentBinding.DIRECT
        for point,kind in ((call.positional_pack,'SEQUENCE'),(call.keyword_pack,'MAPPING')):
            if point is None:continue
            witness=shapes.shape(point,kind)
            if type(witness) is not StaticPackShape:opened=True;continue
            dependencies.update(witness.dependencies)
            if kind=='SEQUENCE':positional.extend(witness.contents)
            else:
                if any(name in keywords for name,_ in witness.contents):
                    collision='closed keyword packs contain a duplicate parameter name'
                keywords.update(witness.contents)
            binding=T.ArgumentBinding.CLOSED_PACK
        if opened:binding=T.ArgumentBinding.SYMBOLIC_PACK
        # Exact source literals are taken only from original direct argument
        # expressions. A singleton may-set is never promoted to an exact value.
        literals={}
        source=nodes[gp(call.result).port.template.occurrence]
        if source['constructor']=='Call':
            args=field(source,'args')['items']
            if call.positional_pack is None and not any(nodes[v['reference']]['constructor']=='Starred' for v in args):
                for point,value in zip(call.positional,args):
                    expression=nodes[value['reference']]
                    if expression['constructor']=='Constant':
                        literals[point]=(decode(PythonLiteral,field(expression,'value')['scalar']),
                                         P.ProductionOccurrence(value['reference']))
            for value in field(source,'keywords')['items']:
                keyword=nodes[value['reference']];name=scalar(keyword,'arg')
                expression_ref=field(keyword,'value')['reference'];expression=nodes[expression_ref]
                if name in dict(call.keywords) and expression['constructor']=='Constant':
                    literals[dict(call.keywords)[name]]=(decode(PythonLiteral,field(expression,'value')['scalar']),
                                                        P.ProductionOccurrence(expression_ref))
        for kind in selected:
            signature=inspect.signature(getattr(builtins,kind.value));note=collision
            try:bound=(signature.bind_partial if opened else signature.bind)(*positional,**keywords).arguments
            except TypeError as error:bound={};note=str(error)
            parameters=[]
            for name,parameter in signature.parameters.items():
                if name in bound:
                    point=bound[name];literal,occurrence=literals.get(point,(None,None))
                    origin=X.BuiltinArgumentOrigin.SOURCE_VALUE if literal is None else X.BuiltinArgumentOrigin.SOURCE_LITERAL
                    parameters.append(X.BuiltinArgument(name,origin,gp(point),literal,occurrence))
                elif not opened and parameter.default is not inspect.Parameter.empty:
                    parameters.append(X.BuiltinArgument(name,X.BuiltinArgumentOrigin.LANGUAGE_DEFAULT,None,
                                                        PythonLiteral.from_python(parameter.default,exact=True)))
                else:
                    parameters.append(X.BuiltinArgument(name,X.BuiltinArgumentOrigin.OPEN_PACK,None))
            record=X.SourceBuiltinInvocation(kind,site,owners[index],tuple(parameters),
                T.ArgumentBinding.NOT_MODELED if note else binding,
                tuple(X.PackConstructionDependency(gp(p),F.ContainerKind(k)) for p,k in sorted(dependencies)),
                str(signature),note,PythonLiteral.from_python(None) if kind is X.SourceBuiltin.EXEC and not note else None)
            invocations.append(record)
            if note:continue
            values={p.name:p.literal.to_python() for p in parameters if p.literal is not None}
            if kind is X.SourceBuiltin.EXEC:
                actual=next((p.source for p in parameters if p.name=='source'),None)
                if actual is not None:exec_arguments.append((bound['source'],actual,site.result))
                continue
            compile_results.append(call.result)
            flags=values.get('flags');dont_inherit=values.get('dont_inherit');optimize=values.get('optimize')
            flags=flags if type(flags) is int else None
            dont_inherit=bool(dont_inherit) if type(dont_inherit) in (bool,int) else None
            optimize=optimize if type(optimize) is int else None
            process=None if entry is None else entry.compilation.optimize
            inherited=(0 if dont_inherit is True else None if dont_inherit is None or entry is None
                       or entry.compilation.effective_flags is None else
                       entry.compilation.effective_flags & supported_future_flag_mask())
            effective=process if optimize==-1 else optimize if optimize in (0,1,2) else None
            result_kind='UNRESOLVED' if flags is None else ('AST' if flags & ast.PyCF_ONLY_AST else 'CODE_OBJECT')
            compilations.append(X.SourceCompilationRequest(site.result,owners[index],flags,dont_inherit,
                optimize,process,inherited,effective,result_kind))
    uses=[]
    for producer in compile_results:
        reached=_reach(adjacency,(producer,))
        for point,actual,result in exec_arguments:
            if point in reached:
                uses.append(X.CompiledCodeUse(gp(producer),actual,result))
    return tuple(invocations),tuple(compilations),tuple(uses)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('facts','source','out'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--interfaces');parser.add_argument('--entry-contract')
    args=parser.parse_args();store=SourceFactStore(args.facts)
    identities=store.units_for_source(args.source)
    if len(identities)!=1:raise ValueError('source must select one original unit')
    unit=store.load(identities[0])
    interfaces=None if args.interfaces is None else SourceInterfaceStore(args.interfaces,store)
    entry=None if args.entry_contract is None else read_script_entry(args.entry_contract,store)
    boundaries,contexts,uses=source_builtin_boundaries(store,unit,interfaces=interfaces,entry=entry)
    out=Path(args.out).absolute()
    if out.exists():raise ValueError('fresh builtin boundary output required')
    _durable_mkdir(out)
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,rows in (
        ('boundaries',boundaries),('compilation-contexts',contexts),('compiled-code-uses',uses))}
    result=dict(schema='scar.source-builtin-execution',schema_version=1,
        status='CONDITIONAL_SOURCE_INTERFACES_MODELED',source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),source=store.rows[unit.unit]['path'],unit=unit.unit,
        tables=tables,interface_summary=None if interfaces is None else interfaces.receipt,
        entry_contract=None if args.entry_contract is None else dict(path=str(Path(args.entry_contract).absolute()),
            sha256=sha256((Path(args.entry_contract)/'entry.json').read_bytes()).hexdigest()),
        target_executed=False,source_body_activated=False,payload_resolved=False,first_stage_complete=False,
        scope='UNIT_LOCAL_REFERENCE_FLOW_AND_DECLARED_CALLER_CONTEXT',
        runtime=sys.version,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        types_sha256=sha256(Path(X.__file__).read_bytes()).hexdigest())
    _durable_bytes(out/'result.json',_json(result),replace=False)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()

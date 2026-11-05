"""Attach generated Python/native declarations to the shared source graph.

The torchgen adapter runs isolated build tooling only. Export matching and
propagation are conditional alternatives, not observations of Python bindings,
argument acceptance, selected dispatch, memory movement, or pure effects.
"""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import time

from scar.analysis.normal_query import NormalCallGraph
from scar.analysis.normal_targets import _Solver,_star_imports
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json,_stream
from scar.analysis.static_native_materials import read_static_native_materials,NativeMaterialBudget
from scar.analysis.static_native_interfaces import native_material_document,lower_static_native_materials
from scar.analysis import tensor_stub_contracts,tensor_return_flow
from scar.ir.program import python_bindings as B,normal_namespaces as N,source_productions as P
from scar.ir.program.binding_returns import ReceiverMode,NativeReturnSlot
from scar.ir.program import binding_returns,tensor_values
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.codec import dumps as graph_dumps,loads as graph_loads
from scar.ir.record_codec import decode


def _artifact(path,schema):
    raw=path.read_bytes()
    return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _catalog(site,catalog=None):
    worker=Path(__file__).with_name('_static_python_bindings_worker.py')
    if catalog is None:
        completed=subprocess.run([sys.executable,'-I','-S','-B',str(worker)],
            input=_json(dict(site=str(site))),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=120,check=False)
        if completed.returncode:raise ValueError(completed.stderr[:1500].decode(errors='replace'))
        raw=completed.stdout
    else:raw=Path(catalog).read_bytes()
    result=json.loads(raw)
    if result['protocol_version']!=2 or result['torch_imported'] or not result['worker']['isolated'] or not result['worker']['no_site']:
        raise ValueError('expected isolated static binding declarations')
    if result['worker']['sha256']!=sha256(worker.read_bytes()).hexdigest():raise ValueError('binding worker differs')
    for receipt in (*result['tools'],*result['materials']):
        path=Path(receipt['path']);payload=path.read_bytes()
        if not path.is_relative_to(site) or len(payload)!=receipt['size_bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:
            raise ValueError('installed binding material changed: '+str(path))
    return result


def _definition(row,index,artifact,revision,conditions,wrapper_sha256):
    # Code identity includes source revision, signature branch and exact
    # generated transformations. Different source query scopes share IDs.
    identity=dict(revision=revision,symbol=row['export_namespace']+'.'+row['export_name'],
        selector=row['native_selector'],signature=row['parser_signature'],branch=row['branch_condition'],
        conversions=row['conversions'],cpp=row['cpp_argument_bindings'],deprecated=row['deprecated'],
        dispatch=row['dispatch_expression'],wrapper_sha256=wrapper_sha256,
        registration_container=row['registration_container'],parser_index=row['parser_index'],kind=row['kind'],
        native_returns=row['native_returns'],python_return=row['python_return'])
    identity=B.PythonBindingID(sha256(_json(identity)).hexdigest())
    arguments=tuple(B.ParserArgument(a['name'],a['schema_name'],a['type'],a['position'],a['parser_index'],
        a['keyword_only'],a['default'],a.get('default_init'),a['parser_type'],a['parser_formal'],a['kind'],
        a['output'],a['tensor_option'],a.get('generator_default')) for a in row['arguments'])
    conversions=tuple(B.ArgumentConversion(B.ConversionStage(c['stage']),c['argument'],c['expression'],c.get('type'),
        c.get('parser_index'),tuple(c['schema_arguments']),c.get('output',False)) for c in row['conversions'])
    conversions+=tuple(B.ArgumentConversion(B.ConversionStage.CPP_ARGUMENT,c['name'],c['expression'],c['type'],
        schema_arguments=tuple(c['schema_arguments'])) for c in row['cpp_argument_bindings'])
    pointer=row['wrapper_id'].replace('~','~0').replace('/','~1')
    return B.PythonBinding(identity,row['export_namespace'],row['export_name'],B.BindingKind(row['kind']),
        row['registration_container'],row['native_selector'],row['parser_signature'],arguments,conversions,
        row['dispatch_expression'],ProviderFactReference(artifact,'#/bindings/'+str(index)),
        ProviderFactReference(artifact,'#/wrappers/'+pointer),row['family_complete'],None,'DECLARATION_ONLY',conditions,
        row['parser_index'],row['group_id'],row['branch_condition'],row['implicit_receiver'],row['deprecated'],
        tuple(NativeReturnSlot(r['ordinal'],r['name'],tensor_return_flow.schema_type(r['type']),r['annotation']) for r in row['native_returns']),
        tensor_return_flow.value_shape(row['python_return']))


def _symbols(definitions):
    result=defaultdict(list)
    for definition in definitions:
        for symbol in {definition.namespace+'.'+definition.name,definition.registration_container+'.'+definition.name}:
            result[symbol].append(definition)
    return result


class _BindingSolver(_Solver):
    """Extend existing reference flow with declaration origins, not new rules per workload."""
    def __init__(self,units,stars,definitions,stub=None,stub_artifact=None):
        self.binding_symbols=_symbols(definitions);self.bindings={d.id.value:d for d in definitions}
        self.native_calls={}
        super().__init__(units,stars)
        self.return_flow=tensor_return_flow.TensorReturnFlow(self,units,stub or dict(methods=[],attributes=[]),stub_artifact)

    def attribute(self,point,value,name,target):
        super().attribute(point,value,name,target)
        if value[0] in ('module','external'):
            for definition in self.binding_symbols.get(value[1]+'.'+name,()):
                self.add(target,('generated_binding',definition.id.value))
        self.return_flow.attribute(point,value,name,target)

    def call(self,index,value):
        if value[0]=='declared_member':return self.return_flow.call_member(index,value)
        if value[0] not in ('generated_binding','generated_bound'):return super().call(index,value)
        unit,call=self.call_rows[index];offset=self.offsets[unit.unit];gp=lambda p:self.gp(offset+p)
        definition=self.bindings[value[1]];receiver=None;mode=ReceiverMode.FUNCTION
        if value[0]=='generated_bound':receiver=value[2];mode=ReceiverMode.BOUND
        elif definition.kind is B.BindingKind.METHOD:
            mode=ReceiverMode.UNBOUND
            if call.positional:receiver=offset+call.positional[0]
        identity=(index,value[1],receiver,mode)
        if identity in self.native_calls:return
        site=B.SourceCallSite(gp(call.callee),tuple(map(gp,call.positional)),tuple((n,gp(p)) for n,p in call.keywords),
            gp(call.result),gp(call.world),gp(call.result_world),
            None if call.positional_pack is None else gp(call.positional_pack),None if call.keyword_pack is None else gp(call.keyword_pack))
        conditions=(*definition.conditions,'NO_TORCH_FUNCTION_OVERRIDE_OR_MODE','NO_TORCH_DISPATCH_OVERRIDE_OR_MODE',
            'STANDARD_TENSOR_DESCRIPTOR_ADMISSION','NORMAL_NATIVE_WRAPPER_RETURN',
            'PARSER_VARIANT:'+str(definition.parser_index),'BINDING_BRANCH:'+str(definition.branch_condition))
        candidate=B.NativeCallCandidate(site,definition.id,conditions,False,None if receiver is None else self.gp(receiver),mode)
        self.native_calls[identity]=candidate
        # Keep an open namespace/override alternative alongside conditional
        # native return declarations; neither branch proves a storage alias.
        self.add(offset+call.result,('external_value',offset+call.result))
        self.return_flow.native_return(index,definition,candidate,offset+call.result)


def _native_batch(task):
    site,out,index,selectors=task;directory=out/'native'/f'{index:04d}';_durable_mkdir(directory)
    materials=read_static_native_materials(site,selectors,budget=NativeMaterialBudget(
        max_selectors=64,max_total_bytes=64_000_000,max_output_bytes=16_000_000,max_seconds=90))
    path=directory/'materials.json';_durable_bytes(path,_json(native_material_document(materials)),replace=False)
    artifact=_artifact(path,'scar.static-native-materials');graphs=lower_static_native_materials(materials,artifact);result={}
    for declaration,graph in zip(materials.declarations,graphs):
        raw=graph_dumps(graph).encode();payload=gzip.compress(raw,compresslevel=3,mtime=0)
        path=directory/(sha256(declaration.selector.encode()).hexdigest()[:24]+'.json.gz')
        _durable_bytes(path,payload,replace=False)
        locator=SourceArtifactLocator(_artifact(path,'scar.program-graph'),sha256(raw).hexdigest(),len(raw),'gzip-canonical-json')
        result[declaration.selector]=(B.NativeSchemaReference(declaration.selector,locator,graph.native_boundaries[0].id),
            {port.name:slot.port for port,slot in zip(declaration.inputs,graph.native_boundaries[0].inputs)})
    return result


def build_binding_graph(targets,out,site,*,catalog=None,jobs=4,propagate=True):
    started=time.monotonic();out=Path(out).absolute();site=Path(site).absolute();view=NormalCallGraph(targets)
    if out.exists():raise ValueError('fresh binding output required')
    document=_catalog(site,catalog);_durable_mkdir(out);path=out/'materials.json'
    _durable_bytes(path,_json(document),replace=False);artifact=_artifact(path,'scar.generated-python-bindings')
    stub=tensor_stub_contracts.collect_tensor_contracts(site);stub_path=out/'tensor-stubs.json'
    _durable_bytes(stub_path,_json(stub),replace=False);stub_artifact=_artifact(stub_path,'scar.tensor-stub-contracts')
    conditions=tuple(document['open_conditions'])+('CURRENT_NAMESPACE_EXPORT_ADMISSION','NATIVE_OVERRIDE_PATH_NOT_SELECTED')
    definitions=[_definition(row,i,artifact,document['source_revision'],conditions,document['wrappers'][row['wrapper_id']]['sha256'])
        for i,row in enumerate(document['bindings'])]
    symbols=_symbols(definitions);definition_by_id={d.id:d for d in definitions};links=defaultdict(list)
    namespace_path=view.path/view.report['namespaces']['path']
    namespace_artifact=_artifact(namespace_path,'scar.normal-namespace-lookups+gzip-jsonl')
    selected=set()
    for index,wire in enumerate(view._documents('namespaces',None,None,'result'),1):
        candidates=symbols.get(wire['namespace']+'.'+wire['member'],())
        if not candidates:continue
        lookup=decode(N.NamespaceLookup,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
        for definition in candidates:
            selected.add(definition.selector)
            links[lookup.result.unit].append(B.NamespaceBindingLink(
                ProviderFactReference(namespace_artifact,'jsonl:'+str(index)),lookup.receiver,lookup.result,definition.id,conditions))
    propagation=None;native_calls=();return_facts=();member_calls=();protocol_calls=()
    if propagate:
        units=list(view.unit_facts());model_units=json.loads((Path(view.inputs['model'])/'manifest.json').read_bytes())['units']
        model_units={u['key']:u for u in model_units}
        with ThreadPoolExecutor(max_workers=8) as pool:
            stars=list(pool.map(lambda u:_star_imports(view.inputs['model'],model_units[u.unit],u.module),units))
        solver=_BindingSolver(units,stars,definitions,stub,stub_artifact);fixed=solver.solve()
        native_calls=tuple(solver.native_calls.values())
        return_facts=tuple(solver.return_flow.facts.values());member_calls=tuple(solver.return_flow.member_calls.values())
        protocol_calls=tuple(solver.return_flow.protocol_calls.values())
        selected.update(definition_by_id[c.binding].selector for c in native_calls)
        propagation=dict(status='FIXED_POINT' if fixed else 'BUDGET_FRONTIER',events=solver.events,frontier=len(solver.queue),
            source_calls=len(solver.call_rows),native_call_sites=len({c.site.result for c in native_calls}),native_call_candidates=len(native_calls))
        # Preserve only typed output records; the source graph is still shared.
        del solver,units
    yaml_path=site/'torchgen/packaged/ATen/native/native_functions.yaml'
    raw_names=set(re.findall(r'^- func: ([^\s(]+)\(',yaml_path.read_text(),re.M))
    raw_selectors={name if '::' in name else 'aten::'+name for name in raw_names}
    admitted=sorted(s for s in selected if s in raw_selectors and s.startswith('aten::'))
    tasks=[(site,out,i,admitted[start:start+64]) for i,start in enumerate(range(0,len(admitted),64))]
    natives={}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for result in pool.map(_native_batch,tasks):natives.update(result)
    normalization=[]
    for i,definition in enumerate(definitions):
        native=natives.get(definition.selector)
        if native is None:
            status='NOT_REQUESTED' if definition.selector not in selected else 'GENERATED_OR_UNAVAILABLE_RAW_SCHEMA'
            definitions[i]=replace(definition,native_status=status);continue
        reference,ports=native;definitions[i]=replace(definition,native=reference,native_status='DECLARED_NATIVE_INTERFACE')
        for index,conversion in enumerate(definition.conversions):
            for name in conversion.schema_arguments:
                if name in ports:normalization.append(B.NormalizationLink(definition.id,index,name,ports[name]))
    families=defaultdict(list)
    for definition in definitions:families[definition.namespace+'.'+definition.name].append(definition)
    exports=[]
    for symbol,rows in sorted(families.items()):
        directory=out/'exports'/sha256(symbol.encode()).hexdigest()[:24];_durable_mkdir(directory)
        table=_stream(directory/'bindings.jsonl.gz',rows)
        exports.append(dict(symbol=symbol,path=str((directory/'bindings.jsonl.gz').relative_to(out)),**{k:v for k,v in table.items() if k!='path'}))
    units=[]
    for unit,rows in sorted(links.items()):
        directory=out/'units'/unit;_durable_mkdir(directory);table=_stream(directory/'lookups.jsonl.gz',rows)
        units.append(dict(unit=unit,path=str((directory/'lookups.jsonl.gz').relative_to(out)),**{k:v for k,v in table.items() if k!='path'}))
    norm=_stream(out/'normalization.jsonl.gz',normalization);calls=_stream(out/'native-calls.jsonl.gz',native_calls)
    returns=_stream(out/'return-types.jsonl.gz',return_facts);members=_stream(out/'declared-members.jsonl.gz',member_calls)
    protocols=_stream(out/'declared-protocols.jsonl.gz',protocol_calls)
    result=dict(schema='scar.generated-python-binding-graph',schema_version=2,status='DECLARATIONS_CONNECTED',
        source_targets=str(view.path),source_result_sha256=sha256((view.path/'result.json').read_bytes()).hexdigest(),
        package_version=document['package_version'],source_revision=document['source_revision'],materials=dict(uri=artifact.uri,sha256=artifact.sha256,size_bytes=artifact.size_bytes),
        definitions=len(definitions),wrappers=len(document['wrappers']),export_families=len(families),exports=exports,units=units,
        namespace_links=sum(len(rows) for rows in links.values()),selected_native_selectors=len(selected),native_interfaces=len(natives),
        native_interface_frontier=sorted(selected-set(natives)),normalization=norm,native_calls=calls,propagation=propagation,
        return_types=returns,declared_members=members,declared_protocols=protocols,
        return_type_kinds=dict(Counter(row.shape.value for row in return_facts)),
        tensor_stubs=dict(uri=stub_artifact.uri,sha256=stub_artifact.sha256,size_bytes=stub_artifact.size_bytes),
        conditions=conditions,manual_bindings_included=False,python_reexports_resolved=False,runtime_binding_verified=False,
        target_executed=False,first_stage_complete=False,transformation_authorized=False,seconds=time.monotonic()-started,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(B.__file__).read_bytes()).hexdigest(),
        return_flow_sha256=sha256(Path(tensor_return_flow.__file__).read_bytes()).hexdigest(),
        stub_collector_sha256=sha256(Path(tensor_stub_contracts.__file__).read_bytes()).hexdigest(),
        return_types_sha256=sha256(Path(binding_returns.__file__).read_bytes()).hexdigest(),
        value_types_sha256=sha256(Path(tensor_values.__file__).read_bytes()).hexdigest())
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--targets',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--site-packages',default=sysconfig.get_paths()['purelib']);parser.add_argument('--catalog');parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--no-propagate',action='store_true');args=parser.parse_args()
    result=build_binding_graph(args.targets,args.out,args.site_packages,catalog=args.catalog,jobs=args.jobs,propagate=not args.no_propagate)
    print(json.dumps({k:result[k] for k in ('status','definitions','export_families','namespace_links','native_interfaces','native_interface_frontier','propagation','return_type_kinds','seconds')},indent=2))


if __name__=='__main__':main()

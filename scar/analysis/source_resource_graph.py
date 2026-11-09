"""Connect canonical schema values and original source routes to target pools.

Resource requirements stay factored by native value/type projection. Source
callers reference them; neither tensors nor list elements are materialized.
The retained hardware graph stays shared, including storage topology. No live
inventory probe, workload execution, placement decision or transfer is made.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_binding_native_graph import BindingNativeStore
from scar.analysis.native_resource_declarations import _projections
from scar.analysis.target_graph import TargetHardwareGraph, _resources
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_resource_graph as R, target_hardware as H
from scar.ir.program import native_resource_declarations as D, source_productions as P
from scar.ir.program import source_binding_native_graph as N
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import decode, encode


SCHEMA='scar.source-resource-graph'
NO_PROOF=('runtime_placement_proven','physical_resource_use_proven','transfers_observed',
    'allocations_observed','allocation_budgets_established','source_relations_rederived',
    'target_executed','first_stage_complete')
ROLES={D.ResourceOperandKind.TENSOR_ARGUMENT:R.ResourceValueRole.TENSOR,
    D.ResourceOperandKind.DEVICE_ARGUMENT:R.ResourceValueRole.DEVICE,
    D.ResourceOperandKind.GENERATOR_ARGUMENT:R.ResourceValueRole.GENERATOR}


def _target(path):
    graph=TargetHardwareGraph(path);resources=graph.resources();connections=graph.connections();paths=graph.paths()
    document=graph.inventory;artifact=_artifact(Path(graph.report['inventory']['uri']),'scar.target-inventory')
    if (document['schema'],document['schema_version'])!=('scar.target-inventory',1):
        raise ValueError('resource target inventory format differs')
    for source in document['sources']:
        if source['text'] is not None and sha256(source['text'].encode()).hexdigest()!=source['sha256']:
            raise ValueError('retained target description source differs')
    nodes,edges,expected_paths=_resources(document,artifact)
    if (len({r.id for r in resources})!=len(resources)
            or {r.id:r for r in resources}!={r.id:r for r in nodes}
            or tuple(edges)!=connections or tuple(expected_paths)!=paths):
        raise ValueError('target resources/topology differ from their retained inventory')
    return graph,resources


def _values(store):
    values=[];dispatch=[];materials={}
    for _,_,boundary in store.natives.values():
        artifact=boundary.signature.artifact
        if artifact not in materials:
            raw=Path(artifact.uri).read_bytes()
            if len(raw)!=artifact.size_bytes or sha256(raw).hexdigest()!=artifact.sha256:
                raise ValueError('native resource schema material receipt differs')
            materials[artifact]=json.loads(raw)
        pointer=boundary.signature.locator.rsplit('/',1)[0];row=materials[artifact]
        for key in pointer.removeprefix('#/').split('/'):row=row[int(key)] if isinstance(row,list) else row[key]
        for direction,name,slots in ((R.ResourceValueDirection.INPUT,'inputs',boundary.inputs),
                (R.ResourceValueDirection.OUTPUT,'outputs',boundary.outputs)):
            for index,(parameter,slot) in enumerate(zip(row[name],slots,strict=True)):
                for category,type_,path,tail in _projections(parameter['type']):
                    values.append(R.NativeResourceValue(boundary.id,slot.port,direction,ROLES[category],type_,path,
                        ProviderFactReference(artifact,pointer+'/'+name+'/'+str(index)+'/type'+tail)))
        for index,candidate in enumerate(row['dispatch']):
            dispatch.append(D.DeclaredDispatchCandidate(boundary.id,tuple(candidate['keys']),candidate['symbol'],
                ProviderFactReference(artifact,pointer+'/dispatch/'+str(index))))
    return tuple(values),tuple(dispatch)


def _options(values,resources,target):
    result=[];snapshot=_artifact(target.path/'result.json',target.report['schema'])
    for ordinal,value in enumerate(values):
        for resource in resources:
            if value.role is R.ResourceValueRole.TENSOR and type(resource) is H.MemoryDomain:
                relation=H.ResourceCandidateKind.TENSOR_STORAGE_POOL
                guards=('MATERIALIZED_TENSOR_LEAF_PRESENT','NATIVE_VALUE_DEVICE_AND_STORAGE_MATCH_POOL',
                    'TARGET_MEMORY_ACCESS_POLICY_PERMITS_PLACEMENT','NO_ALLOCATION_OR_STORAGE_IDENTITY_PROOF')
            elif value.role is R.ResourceValueRole.DEVICE and type(resource) in (H.CpuExecutor,H.Accelerator):
                relation=H.ResourceCandidateKind.DEVICE_REFERENT
                guards=('DEVICE_VALUE_PRESENT','FRAMEWORK_VISIBILITY_AND_TARGET_DEVICE_MAPPING_MATCH')
            elif value.role is R.ResourceValueRole.GENERATOR and type(resource) in (H.CpuExecutor,H.Accelerator):
                relation=H.ResourceCandidateKind.GENERATOR_DEVICE
                guards=('GENERATOR_VALUE_PRESENT','GENERATOR_DEVICE_AND_TARGET_DEVICE_MAPPING_MATCH',
                    'NO_RNG_CONSUMPTION_OR_GENERATOR_STATE_IDENTITY_PROOF')
            else:continue
            result.append(R.ResourceTargetOption(ordinal,H.TargetResourceRef(snapshot,resource.id),relation,
                (*guards,'OPTIONAL_AND_LIST_TYPE_PATH_IS_NOT_PRESENT_VALUE_OR_ELEMENT_COUNT')))
    return tuple(result)


def _host_options(store,resources,target):
    source_root=store.parents.source_root;source=json.loads((source_root/'result.json').read_bytes())
    snapshot=_artifact(target.path/'result.json',target.report['schema']);result=[]
    for unit in store.report['shards']:
        declaration=decode(ProviderArtifact,source['shards'][unit]['result'])
        if declaration!=_artifact(source_root/source['shards'][unit]['path']/'result.json','scar.source-declared-call-unit'):
            raise ValueError('source unit host execution declaration material differs')
        for resource in resources:
            if type(resource) is H.CpuExecutor:
                result.append(R.SourceUnitHostOption(unit,ProviderFactReference(declaration,'#/unit'),
                    H.TargetResourceRef(snapshot,resource.id)))
    return tuple(result)


def _executor_options(store,dispatch,resources,target):
    by_boundary=defaultdict(list)
    for index,row in enumerate(dispatch):by_boundary[row.boundary].append(index)
    snapshot=_artifact(target.path/'result.json',target.report['schema'])
    return tuple(R.NativeExecutorOption(boundary.id,H.TargetResourceRef(snapshot,resource.id),
        tuple(by_boundary[boundary.id])) for _,_,boundary in store.natives.values()
        for resource in resources if type(resource) in (H.CpuExecutor,H.Accelerator))


def _source_routes(store,unit,values):
    shard=store.report['shards'][unit];root=store.path/shard['path']
    inputs=tuple(decode(N.SourceOperandNormalization,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(root,shard['tables']['inputs']))
    outputs=tuple(decode(N.SourceOutputNormalization,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(root,shard['tables']['outputs']))
    by_port=defaultdict(list);by_output=defaultdict(list)
    for ordinal,value in enumerate(values):
        if value.direction is R.ResourceValueDirection.INPUT:by_port[value.boundary,value.port].append(ordinal)
        else:by_output[value.boundary].append((ordinal,value.port))
    routes=[]
    for index,row in enumerate(inputs):
        for value in by_port[row.dependency.boundary,row.dependency.native_port]:
            routes.append(R.SourceResourceRoute(_table_ref(root,shard['tables']['inputs'],
                'scar.source-native-input-normalization',index),value,(
                    'PARENT_SOURCE_NORMALIZATION_AND_SCHEMA_TYPE_PROJECTION_SELECTED',
                    'CONVERSION_DEPENDENCY_NOT_SOURCE_OBJECT_STORAGE_PLACEMENT')))
    for index,row in enumerate(outputs):
        ports={slot.port for slot in row.native_outputs}
        for value,port in by_output[row.boundary]:
            if port not in ports:raise ValueError('native resource output is absent from original return slots')
            routes.append(R.SourceResourceRoute(_table_ref(root,shard['tables']['outputs'],
                'scar.source-native-output-normalization',index),value,(
                    'PARENT_SOURCE_WRAPPING_AND_NATIVE_RETURN_SLOT_SELECTED',
                    'NATIVE_RESULT_OR_WRAPPED_MEMBER_NOT_PYTHON_CONTAINER_STORAGE_PLACEMENT',
                    'NO_PYTHON_NATIVE_OBJECT_OR_LOGICAL_CONTENT_IDENTITY_PROOF')))
    return tuple(routes)


def _pins():
    from scar.analysis import source_binding_native_graph,native_resource_declarations,target_graph
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in (
        ('producer',__file__),('types',R.__file__),('native',source_binding_native_graph.__file__),
        ('projection',native_resource_declarations.__file__),('target',target_graph.__file__),('target_types',H.__file__))}


def build_source_resources(native,target,out):
    started=time.monotonic();pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh source resource output required')
    store=BindingNativeStore(native);hardware,resources=_target(target)
    parents=[encode(_artifact(store.path/'result.json',store.report['schema'])),
        encode(_artifact(hardware.path/'result.json',hardware.report['schema']))]
    values,dispatch=_values(store);options=_options(values,resources,hardware)
    hosts=_host_options(store,resources,hardware);_durable_mkdir(out)
    executors=_executor_options(store,dispatch,resources,hardware)
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,rows in (
        ('values',values),('dispatch',dispatch),('options',options),('hosts',hosts),('executors',executors))}
    shards={};source_routes=0
    for unit in store.report['shards']:
        routes=_source_routes(store,unit,values);folder=out/'units'/unit;_durable_mkdir(folder)
        receipt=write_table(folder/'routes.jsonl.gz',routes)
        shards[unit]=dict(path='units/'+unit,tables=dict(routes=receipt),routes=len(routes));source_routes+=len(routes)
        tables[unit+'/routes']=dict(receipt,path='units/'+unit+'/'+receipt['path'])
    store.validate()
    current_target,current_resources=_target(hardware.path)
    if (parents[1]!=encode(_artifact(current_target.path/'result.json',current_target.report['schema']))
            or current_resources!=resources):raise ValueError('target resource snapshot changed during projection')
    if pins!=_pins():raise ValueError('source resource projection rules changed')
    report=dict(schema=SCHEMA,schema_version=1,status='SOURCE_NATIVE_VALUE_RESOURCE_CONSTRAINTS',
        native=str(store.path),target=str(hardware.path),
        parents=parents,
        pins=pins,tables=tables,shards=shards,
        counts=dict(units=len(shards),resource_values=len(values),target_options=len(options),
            source_routes=source_routes,host_options=len(hosts),dispatch_declarations=len(dispatch),
            executor_options=len(executors),
            value_roles=dict(Counter(v.role.value for v in values)),
            value_directions=dict(Counter(v.direction.value for v in values)),
            target_resources=dict(Counter(type(r).__name__ for r in resources))),
        hardware_inventory_shared=True,source_result_wrapping_preserved=True,
        **{name:False for name in NO_PROOF},seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


class SourceResourceGraph:
    def __init__(self,path):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'])!=(SCHEMA,1) or r['pins']!=_pins():raise ValueError('source resource producer differs')
        self.native=BindingNativeStore(r['native']);self.target,self.resources=_target(r['target'])
        self.target_artifact=_artifact(self.target.path/'result.json',self.target.report['schema'])
        parents=[encode(_artifact(self.native.path/'result.json',self.native.report['schema'])),
            encode(_artifact(self.target.path/'result.json',self.target.report['schema']))]
        if parents!=r['parents'] or set(r['shards'])!=set(self.native.report['shards']):
            raise ValueError('source resource native/target inputs or source unit coverage differ')
        classes=dict(values=R.NativeResourceValue,dispatch=D.DeclaredDispatchCandidate,
            options=R.ResourceTargetOption,hosts=R.SourceUnitHostOption,executors=R.NativeExecutorOption)
        self.rows={name:tuple(decode(cls,row,record_tags=P.PRODUCTION_RECORD_TAGS)
            for row in _table(self.path,r['tables'][name])) for name,cls in classes.items()}
        values,dispatch=_values(self.native)
        if (self.rows['values']!=values or self.rows['dispatch']!=dispatch
                or self.rows['options']!=_options(values,self.resources,self.target)
                or self.rows['hosts']!=_host_options(self.native,self.resources,self.target)
                or self.rows['executors']!=_executor_options(self.native,dispatch,self.resources,self.target)):
            raise ValueError('source resource type projections or target candidates differ')
        flat={name:r['tables'][name] for name in classes}
        for unit,shard in r['shards'].items():
            if shard['path']!='units/'+unit or set(shard['tables'])!={'routes'} or shard['tables']['routes']['path']!='routes.jsonl.gz':
                raise ValueError('source resource unit shard path or table set differs')
            flat[unit+'/routes']=dict(shard['tables']['routes'],path=shard['path']+'/routes.jsonl.gz')
        counts=dict(units=len(r['shards']),resource_values=len(values),target_options=len(self.rows['options']),
            source_routes=sum(s['routes'] for s in r['shards'].values()),host_options=len(self.rows['hosts']),
            dispatch_declarations=len(dispatch),value_roles=dict(Counter(v.role.value for v in values)),
            executor_options=len(self.rows['executors']),
            value_directions=dict(Counter(v.direction.value for v in values)),
            target_resources=dict(Counter(type(value).__name__ for value in self.resources)))
        if r['tables']!=flat or r['counts']!=counts:raise ValueError('source resource global table index or counts differ')
        if (any(r[k] is not False for k in NO_PROOF) or r['hardware_inventory_shared'] is not True
                or r['source_result_wrapping_preserved'] is not True):
            raise ValueError('resource constraints cannot grant physical use, placement or execution')
        self.validate()

    def validate(self):
        self.native.validate()
        target,resources=_target(self.target.path)
        if self.target_artifact!=_artifact(target.path/'result.json',target.report['schema']) or resources!=self.resources:
            raise ValueError('source resource target snapshot changed')
        if self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins():
            raise ValueError('source resource report or rules changed')

    def read_unit(self,unit):
        self.validate();shard=self.report['shards'][unit]
        rows=tuple(decode(R.SourceResourceRoute,row) for row in _table(self.path/shard['path'],shard['tables']['routes']))
        if rows!=_source_routes(self.native,unit,self.rows['values']) or len(rows)!=shard['routes']:
            raise ValueError('source normalization to resource value routes differ')
        self.validate();return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native');parser.add_argument('--target');parser.add_argument('--out')
    parser.add_argument('--read');parser.add_argument('--unit');args=parser.parse_args()
    if args.read:
        graph=SourceResourceGraph(args.read)
        if args.unit:graph.read_unit(args.unit)
        report=graph.report
    else:
        if not args.native or not args.target or not args.out:parser.error('--native, --target, --out required')
        report=build_source_resources(args.native,args.target,args.out)
    print(json.dumps(dict(status=report['status'],counts=report['counts'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()

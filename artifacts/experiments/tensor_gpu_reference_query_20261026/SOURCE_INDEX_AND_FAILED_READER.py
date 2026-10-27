"""Rebuildable ID/locator navigation of original Tensor storage evidence.

Index rows contain existing IDs and original row coordinates only. Queries
re-read and type-check original records/edges; index bytes grant no graph fact.
"""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import gzip
import json
import re

from scar.ir.record_codec import decode, encode, loads
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.evidence import EvidenceEdge, EvidenceNodeKind as N, EvidenceRelation as R, OperationInstance, ProviderReference
from scar.ir.v2.values import StorageRegion, StorageAllocation, ObjectInstance
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.tensor_physical import PROFILE, PROVIDER_REVISION
from scar.analysis.tensor_storage_query import _Meter, _json, _report, _need, _record, _stamp

_SCHEMA='scar.tensor-storage-locator-index'
_TABLES=(('values','regions'),('values','allocations'),('values','objects'),('evidence','provider_references'),('evidence','edges'))

def _canonical(d):return json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def _wire(x):return x['wire'] if type(x) is dict else x

def _write(root,name,rows,maximum):
    payload=_canonical(rows);raw=gzip.compress(payload,mtime=0)
    _need(len(payload)<=16_000_000 and len(raw)<=maximum,'locator shard budget exceeded')
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw)
    return {'path':name,'stored_bytes':len(raw),'stored_sha256':sha256(raw).hexdigest(),'decoded_bytes':len(payload),'decoded_sha256':sha256(payload).hexdigest()}

def _source_chunk(partitions,chunk):
    return ProviderArtifact(str(partitions.root/chunk['uri']),chunk['physical_sha256'],chunk['physical_bytes'],'scar.bundle-record-chunk')

def _source_ref(partitions,row):
    c=row['locator']['artifact']
    return ProviderFactReference(_source_chunk(partitions,c),f"#/lines/{row['locator']['line']}/record")

def _scope(capture_model,meter):
    capture=_json(capture_model,meter);_need(capture.get('schema')=='scar.capture-model','unsupported retained capture model')
    coordinates_artifact=decode(ProviderArtifact,capture['coordinate_binding']);coordinates=_json(coordinates_artifact,meter)
    _need(coordinates['run']==capture['run'],'retained coordinates Run differs')
    process=coordinates['target_process'];actors=[x for x in coordinates['processes'] if x['id']==process]
    _need(len(actors)==1 and actors[0]['run']==capture['run']['id'],'process/Run membership differs')
    d=coordinates.get('tensor_physical_collector_declaration',{})
    _need(d.get('profile')==PROFILE and d.get('provider_revision')==PROVIDER_REVISION and d.get('process_id')==actors[0]['pid'],'unsupported pinned physical scope')
    return capture,coordinates,coordinates_artifact,process,actors[0]['pid']


def build_tensor_storage_reference_index(bundle:ProviderArtifact,capture_model:ProviderArtifact,eto_source:ProviderArtifact,out,*,
                                          max_input_bytes=2_050_000_000,max_seconds=180,max_output_bytes=200_000_000):
    meter=_Meter(max_input_bytes,max_seconds);root=Path(out).resolve();_need(not root.exists(),'index output must be fresh');root.mkdir()
    capture,coords,coords_artifact,process,pid=_scope(capture_model,meter)
    outputs={r['path']:r for r in capture['outputs']}
    _need(bundle.uri in outputs and outputs[bundle.uri]['stored_sha256']==bundle.sha256,'bundle not in capture outputs')
    _need(any(r['artifact']==encode(eto_source) and r['process']==process for r in coords['membership']),'original ETO namespace not in retained capture')
    meter.artifact(bundle);meter.charge(stored=bundle.size_bytes,decoded=bundle.size_bytes);partitions=BundlePartitions(bundle.uri)
    descriptors={};storage_edges=defaultdict(list);object_provider=defaultdict(list);cuda={};object_regions=set();counts={};output=0
    def publish(name,entries):
        nonlocal output
        result=[]
        for start in range(0,len(entries),1000):
            batch=entries[start:start+1000];ref=_write(root,f'{name}/{start//1000:05d}.json.gz',batch,max_output_bytes-output)
            output+=ref['stored_bytes'];_need(output<=max_output_bytes,'locator index output budget exceeded')
            result.append({**ref,'first':batch[0]['id'],'last':batch[-1]['id'],'rows':len(batch)})
        return result
    for graph,table in _TABLES:
        family=graph+'/'+table;table_refs=[];visited=kept=0
        for chunk_no,chunk in enumerate(partitions.manifest['graphs'][graph]['tables'][table]['chunks']):
            meter.charge(stored=chunk['physical_bytes'],decoded=chunk['decoded_bytes']);entries=[]
            # Normal row/chunk reader, not another JSON graph codec.
            for row in partitions.selected_records(graph,table,tuple(range(chunk['first_ordinal'],chunk['last_ordinal']+1))):
                record=row['record'];visited+=1
                identity=record['edge_id'] if table=='edges' else record['reference_id'] if table=='provider_references' else _wire(record['id'])
                keep=True
                if table=='regions':
                    region=decode(StorageRegion,record)
                    if region.device.split(':',1)[0]=='cuda' and 'marker_instance' in region.metadata:cuda[identity]=row['ordinal']
                if table=='edges':
                    relation=record['relation'];source,target=record['source'],record['target']
                    keep=(relation=='uses_storage' and target['kind']=='storage_region' and source['kind'] in ('object','operation_instance')) or relation=='object_reference_association'
                    if keep and relation=='uses_storage':
                        storage_edges[_wire(target['reference'])].append(identity)
                        if source['kind']=='object':object_regions.add(_wire(target['reference']))
                    elif keep:
                        for ref in record['evidence']['references']:
                            if ref.startswith('sha256:'+eto_source.sha256+'#/nodes/') and '/inputs/values/' in ref:object_provider[ref].append(identity)
                if keep:entries.append({'id':identity,'ordinal':row['ordinal']});kept+=1
            entries.sort(key=lambda r:r['id'])
            refs=publish(f'primary/{graph}-{table}/{chunk_no:05d}',entries)
            if refs:table_refs.append({'source_chunk':chunk,'shards':refs})
        descriptors[family]=table_refs;counts[family]={'visited':visited,'indexed':kept}
    descriptors['storage_edges']=publish('secondary/storage_edges',[{'id':key,'edge_ids':value} for key,value in sorted(storage_edges.items())])
    descriptors['object_provider']=publish('secondary/object_provider',[{'id':key,'edge_ids':value} for key,value in sorted(object_provider.items())])
    dispatch_refs=[r for r in capture['outputs'] if r['path'].endswith('/dispatch-bridge.json.gz')]
    _need(len(dispatch_refs)==1,'capture lacks a unique declared dispatch report')
    d=dispatch_refs[0];dispatch=ProviderArtifact(d['path'],d['stored_sha256'],d['stored_bytes'],'scar.dispatch-observation-import')
    markers={}
    def observe(index,row):
        ancestry=row.get('actual_provider_ancestry');marker=row.get('marker_instance')
        _need(ancestry and ancestry[0]['instance']==marker,'original dispatch ancestry differs')
        raw=ancestry[0]['raw_reference'];prefix='sha256:'+eto_source.sha256+'#/nodes/'
        _need(raw.startswith(prefix) and re.fullmatch(r'0|[1-9][0-9]*',raw[len(prefix):]),'dispatch marker has no exact source ordinal')
        _need(marker not in markers,'duplicate original dispatch marker')
        markers[marker]={'id':marker,'ordinal':int(raw[len(prefix):]),'observation_index':index}
        return False
    header,_,_=_report(dispatch,meter,{'observations':observe})
    _need(header.get('schema')=='scar.dispatch-observation-import','unsupported dispatch report')
    descriptors['markers']=publish('secondary/markers',[markers[k] for k in sorted(markers)])
    eligible=[(ordinal,identity) for identity,ordinal in cuda.items() if identity in object_regions]
    _need(eligible,'no typed CUDA region with existing storage evidence')
    # This is a mechanical selector hint; query rechecks CUDA and object edge.
    selected=None
    for ordinal,identity in sorted(eligible):
        # Existing physical producer emits use then object-use. Both actual IDs
        # stay in the index; query selects by normal source kind, never ID name.
        if identity in object_regions:selected={'region':identity,'ordinal':ordinal};break
    _need(selected is not None,'no CUDA observation has an object/storage association')
    measurement=meter.finish()
    manifest={'schema':_SCHEMA,'schema_version':1,'bundle':encode(bundle),'capture_model':encode(capture_model),'coordinates':encode(coords_artifact),
        'eto_source':encode(eto_source),'dispatch_report':encode(dispatch),'run':capture['run'],'process':process,'pid':pid,'tables':descriptors,
        'first_cuda_region':selected,'counts':counts,'cuda_regions':len(cuda),'input_measurements':measurement,'stored_index_bytes':output,
        'index_is_graph_authority':False,'producer_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    payload=_canonical(manifest);_need(output+len(payload)<=max_output_bytes,'manifest output budget exceeded')
    with (root/'manifest.json').open('xb') as f:f.write(payload)
    return ProviderArtifact(str(root/'manifest.json'),sha256(payload).hexdigest(),len(payload),_SCHEMA)


class TensorStorageReferenceIndex:
    """Small immutable locator reader; all graph facts come from original rows."""
    def __init__(self,artifact,meter):
        self.artifact=artifact;self.meter=meter;self.root=Path(artifact.uri).parent
        self.document=_json(artifact,meter)
        _need(self.document.get('schema')==_SCHEMA and self.document.get('schema_version')==1,'unsupported locator index')
        _need(self.document['producer_source_sha256']==sha256(Path(__file__).read_bytes()).hexdigest(),'locator policy source changed; rebuild derived index')
        bundle=decode(ProviderArtifact,self.document['bundle']);meter.artifact(bundle);meter.charge(stored=bundle.size_bytes,decoded=bundle.size_bytes)
        self.partitions=BundlePartitions(bundle.uri);self.cache={}
    def _shard(self,ref):
        p=self.root/ref['path'];artifact=ProviderArtifact(str(p),ref['stored_sha256'],ref['stored_bytes'],'scar.tensor-storage-locators')
        raw=self.meter.artifact(artifact,16_000_000);data=gzip.decompress(raw);self.meter.charge(decoded=len(data))
        _need(len(data)==ref['decoded_bytes'] and sha256(data).hexdigest()==ref['decoded_sha256'],'locator decoded receipt differs')
        rows=loads(data.decode('utf8'));_need(len(rows)==ref['rows'] and [r['id'] for r in rows]==sorted({r['id'] for r in rows}) and rows[0]['id']==ref['first'] and rows[-1]['id']==ref['last'],'locator bounds/order differ')
        return rows
    def lookup(self,family,identity):
        refs=self.document['tables'][family]
        if family in ('storage_edges','object_provider','markers'):groups=[{'shards':refs}]
        else:groups=refs
        found=[]
        for group in groups:
            for ref in group['shards']:
                if ref['first']<=identity<=ref['last']:
                    found.extend(r for r in self._shard(ref) if r['id']==identity)
        _need(len(found)==1,'original ID has no unique locator: '+identity)
        return found[0]
    def record(self,graph,table,identity):
        family=graph+'/'+table
        if family=='evidence/instances':hint=self.lookup('markers',identity)
        else:hint=self.lookup(family,identity)
        key=(graph,table,hint['ordinal'])
        if key not in self.cache:self.cache[key]=_record(self.partitions,graph,table,hint['ordinal'],self.meter)
        record,reference=self.cache[key];actual=record['edge_id'] if table=='edges' else record['reference_id'] if table=='provider_references' else _wire(record['id'])
        _need(actual==identity,'derived locator changed original record identity')
        return record,reference


def query_tensor_storage_source(reference_index:ProviderArtifact,association:ProviderFactReference|None=None,*,
                                region_id=None,max_input_bytes=180_000_000,max_seconds=60):
    """Read an original OBJECT→USES_STORAGE edge and its same-capture endpoints.

    None mechanically chooses the index's first typed CUDA observation hint.
    The hint/index does not validate the relation: original edges do.
    """
    meter=_Meter(max_input_bytes,max_seconds);index=TensorStorageReferenceIndex(reference_index,meter);d=index.document
    capture,coords,coord_artifact,process,pid=_scope(decode(ProviderArtifact,d['capture_model']),meter)
    _need(coord_artifact==decode(ProviderArtifact,d['coordinates']) and capture['run']==d['run'] and process==d['process'],'index/source Run differs')
    region_id=region_id or d['first_cuda_region']['region']
    raw_region,region_ref=index.record('values','regions',region_id);region=decode(StorageRegion,raw_region)
    edge_ids=index.lookup('storage_edges',region_id)['edge_ids'];edges=[]
    for identity in edge_ids:
        record,ref=index.record('evidence','edges',identity);edge=decode(EvidenceEdge,record)
        _need(edge.relation is R.USES_STORAGE and edge.target.kind is N.STORAGE_REGION and edge.target.reference==region.id,'original storage evidence target differs')
        edges.append((edge,ref))
    objects=[(e,r) for e,r in edges if e.source.kind is N.OBJECT];markers=[(e,r) for e,r in edges if e.source.kind is N.OPERATION_INSTANCE]
    _need(len(objects)==len(markers)==1,'observation needs one original object/storage and marker/storage edge')
    object_edge,object_edge_ref=objects[0];marker_edge,marker_edge_ref=markers[0]
    if association is not None:_need(association==object_edge_ref,'requested original physical SourceFact differs')
    _need(object_edge.evidence==marker_edge.evidence,'object/marker do not share the original physical claim')
    physical_ref=region.metadata['physical_observation']
    _need(physical_ref in object_edge.evidence.references,'storage claim does not cite this physical observation')
    raw_object,object_ref=index.record('values','objects',object_edge.source.wire);obj=decode(ObjectInstance,raw_object)
    raw_marker,marker_ref=index.record('evidence','instances',marker_edge.source.wire);marker=decode(OperationInstance,raw_marker)
    _need(obj.metadata['process_id']==pid and marker.id.wire==region.metadata['marker_instance']
          and marker.metadata['raw_reference'].startswith('sha256:'+d['eto_source']['sha256']+'#/nodes/'),'object/process/marker namespace differs')
    slots=[x for x in marker.metadata.get('tensor_slots',()) if x['role']=='inputs' and x['ordered_path']==[region.metadata['argument_ordinal']]]
    _need(len(slots)==1,'marker original ordered input absent/ambiguous');slot=slots[0]
    raw_provider,provider_ref=index.record('evidence','provider_references',slot['provider_reference']);provider=decode(ProviderReference,raw_provider)
    descriptors=[x for x in provider.metadata['descriptors'] if x['descriptor_id']==slot['descriptor_id']]
    _need(len(descriptors)==1,'original marker descriptor differs');descriptor=descriptors[0];tensor=descriptor['tensor_tuple']
    _need(descriptor['shape']==list(region.shape) and descriptor['strides']==list(region.strides) and tensor[2]==region.offset and tensor[5]==region.device,'original descriptor/view geometry differs')
    links=index.lookup('object_provider',slot['raw_reference'])['edge_ids'];qualified=[]
    for identity in links:
        record,ref=index.record('evidence','edges',identity);edge=decode(EvidenceEdge,record)
        if edge.source.reference==obj.id and edge.target.reference==provider.reference_id:
            _need(edge.relation is R.OBJECT_REFERENCE_ASSOCIATION and slot['raw_reference'] in edge.evidence.references and edge.evidence.scope==obj.scope,'original object/provider slot evidence differs');qualified.append(ref)
    _need(len(qualified)==1,'Python object/native marker slot is absent/ambiguous')
    raw_allocation,allocation_ref=index.record('values','allocations',region.allocation.wire);allocation=decode(StorageAllocation,raw_allocation)
    _need(allocation.id==region.allocation and allocation.device==region.device,'original allocation/device differs')
    hint=index.lookup('markers',marker.id.wire)
    context=ProviderFactReference(decode(ProviderArtifact,d['dispatch_report']),f"#/observations/{hint['observation_index']}")
    # Retained raw-artifact membership is a declaration consumed here, not new
    # OS replay; every selected physical edge keeps its original claim scope.
    physical_sha=physical_ref.split('#',1)[0].removeprefix('sha256:')
    _need(any(x['artifact']['sha256']==physical_sha and x['process']==process and x['artifact']==capture['native']['tensor_physical']['artifacts']['observations'] for x in coords['membership']),'physical observation is not the declared same-process artifact')
    return {'schema':'scar.tensor-storage-source-query','schema_version':1,'run':d['run'],'process':process,'association':encode(object_edge_ref),
        'original_edges':[encode(object_edge),encode(marker_edge)],'object':obj.as_dict(),'object_source':encode(object_ref),
        'marker':encode(marker),'marker_source':encode(marker_ref),'marker_slot':slot,'object_marker_edge':encode(qualified[0]),
        'provider_reference':provider.as_dict(),'provider_source':encode(provider_ref),'storage_region':region.as_dict(),'region_source':encode(region_ref),
        'allocation':allocation.as_dict(),'allocation_source':encode(allocation_ref),'retained_source_context':encode(context),
        'source_context_dereferenced':False,'materialization':None,'new_value_graph_nodes':0,
        'scope':'original held-Tensor marker observation only; no actual-op cross-point storage/content/ready binding',
        'measurements':meter.finish()}

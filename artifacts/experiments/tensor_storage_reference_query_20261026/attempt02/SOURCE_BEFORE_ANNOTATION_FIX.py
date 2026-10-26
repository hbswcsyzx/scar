"""Observation-local Tensor reference/storage queries over existing records.

No value, version, materialization, producer or state is minted. Native op
symbols elsewhere in an existing fragment remain provider-reference candidates;
only an exact held-Tensor marker argument acquires this physical observation.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import gzip
import json
import re
import time

from scar.ir.record_codec import decode, encode, loads
from scar.ir.execution.content import ObjectRef
from scar.ir.execution.ids import RunID, ProcessInstanceID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.values import StorageAllocation, StorageRegion
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_capture_batch import _JSONStream
from scar.trace.native_operator_value_interface import read_native_operator_value_fragment
from scar.trace.native_reference_flow import read_native_reference_flow_index, _bucket, _read_flow_shard
from scar.trace.native_port_sidecar import query_native_ports
from scar.trace.tensor_physical import PROFILE, PROVIDER_REVISION


def _need(value, message):
    if not value: raise ValueError('Tensor storage query: '+message)


@dataclass(frozen=True, slots=True)
class TensorStorageObservation:
    """References to one existing observation; no persistent object/value alias."""
    run: RunID
    process: ProcessInstanceID
    object: ObjectRef
    marker: ProviderFactReference
    marker_input: ProviderFactReference
    physical_association: ProviderFactReference
    source_context: ProviderFactReference
    storage_region: ProviderFactReference
    allocation: ProviderFactReference
    scope: str = 'EXACT_HELD_TENSOR_MARKER_OBSERVATION'

    def __post_init__(self):
        for name, kind in [('run',RunID),('process',ProcessInstanceID),('object',ObjectRef),
                           *[(x,ProviderFactReference) for x in ('marker','marker_input','physical_association','source_context','storage_region','allocation')]]:
            value=getattr(self,name);_need(type(value) is kind,'typed original '+name+' required');value.__post_init__()
        _need(self.scope=='EXACT_HELD_TENSOR_MARKER_OBSERVATION','unsupported association scope')


class _Meter:
    def __init__(self, maximum, seconds):
        _need(type(maximum) is int and maximum>0 and type(seconds) is int and seconds>0,'positive bounded inputs required')
        self.maximum,self.seconds,self.started=maximum,seconds,time.monotonic()
        self.stored=self.decoded=0;self.inputs=[]
    def charge(self, stored=0, decoded=0):
        self.stored+=stored;self.decoded+=decoded
        _need(self.stored+self.decoded<=self.maximum,'combined stored+decoded input budget exceeded')
        _need(time.monotonic()-self.started<=self.seconds,'wall budget exceeded')
    def artifact(self, artifact, maximum=16_000_000):
        _need(type(artifact) is ProviderArtifact,'exact artifact required');artifact.__post_init__()
        path=Path(artifact.uri);_need(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink(),'original artifact URI unavailable')
        before=path.stat();_need(before.st_size==artifact.size_bytes<=maximum,'artifact size/budget differs')
        with path.open('rb') as stream:raw=stream.read(maximum+1)
        self.charge(stored=len(raw))
        _need(sha256(raw).hexdigest()==artifact.sha256 and _stamp(path)==_stamp_value(before),'artifact SHA/stability differs')
        self.inputs.append((path,_stamp(path)));return raw
    def finish(self):
        for p,stamp in self.inputs:_need(_stamp(p)==stamp,'input changed during query')
        self.charge();return {'stored_bytes':self.stored,'decoded_bytes':self.decoded,'total_bytes':self.stored+self.decoded,'elapsed_seconds':time.monotonic()-self.started}


def _stamp_value(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def _stamp(path):return _stamp_value(path.stat())


class _Decoded:
    def __init__(self, stream, meter):self.stream,self.meter,self.size=stream,meter,0
    def read(self,n):
        raw=self.stream.read(n);self.size+=len(raw);self.meter.charge(decoded=len(raw));return raw


def _report(artifact, meter, selectors):
    """Check complete original compressed bytes; strictly parse bounded rows."""
    raw=meter.artifact(artifact,32_000_000)
    import io
    stream=gzip.GzipFile(fileobj=io.BytesIO(raw)) if Path(artifact.uri).suffix=='.gz' else io.BytesIO(raw)
    reader=_Decoded(stream,meter);parser=_JSONStream(reader,4_000_000)
    fields,selected={},{};seen=set();parser.take('{')
    if parser.peek()!='}':
        while True:
            key=parser.value();_need(type(key) is str and key not in seen,'duplicate/non-text report field');seen.add(key);parser.take(':')
            if parser.peek()=='[':
                parser.take('[');index=0;kept=[]
                if parser.peek()!=']':
                    while True:
                        value=parser.value()
                        if key in selectors and selectors[key](index,value):kept.append((index,value))
                        index+=1
                        if parser.peek()!=',':break
                        parser.take(',')
                parser.take(']');selected[key]=kept;fields[key+'_count']=index
            else:fields[key]=parser.value()
            if parser.peek()!=',':break
            parser.take(',')
    parser.take('}');_need(parser.peek()=='','extra data after report EOF');stream.close()
    return fields,selected,reader.size


def _json(artifact,meter):
    raw=meter.artifact(artifact);meter.charge(decoded=len(raw));return loads(raw.decode('utf8'))


def _record(partitions,graph,table,ordinal,meter):
    table_desc=partitions.manifest['graphs'][graph]['tables'][table]
    chunks=[c for c in table_desc['chunks'] if c['first_ordinal']<=ordinal<=c['last_ordinal']]
    _need(len(chunks)==1,'record locator outside original table')
    chunk=chunks[0];meter.charge(stored=chunk['physical_bytes'],decoded=chunk['decoded_bytes'])
    row=partitions.selected_records(graph,table,(ordinal,))[0]
    artifact=ProviderArtifact(str(partitions.root/chunk['uri']),chunk['physical_sha256'],chunk['physical_bytes'],'scar.bundle-record-chunk')
    meter.inputs.append((Path(artifact.uri),_stamp(Path(artifact.uri))))
    reference=ProviderFactReference(artifact,f"#/lines/{row['locator']['line']}/record")
    return row['record'],reference


def query_tensor_storage_observation(value_fragment: ProviderArtifact, capture_model: ProviderArtifact, *,
                                     candidate_index=0,max_input_bytes=512_000_000,max_seconds=180):
    """Resolve one original physical candidate at its exact marker endpoint.

    Retained coordinates/imported facts are consumed, not replayed raw capture
    ownership. This query never upgrades a different op's payload/version.
    """
    meter=_Meter(max_input_bytes,max_seconds)
    meter.artifact(value_fragment)
    meter.charge(stored=value_fragment.size_bytes)
    fragment,values=read_native_operator_value_fragment(value_fragment.uri,expected_sha256=value_fragment.sha256)
    _need(type(candidate_index) is int and 0<=candidate_index<len(fragment.physical_candidates),'physical candidate absent')
    candidate=fragment.physical_candidates[candidate_index]
    capture=_json(capture_model,meter);_need(capture.get('schema')=='scar.capture-model','unsupported capture model')
    coordinates_artifact=decode(ProviderArtifact,capture['coordinate_binding']);coordinates=_json(coordinates_artifact,meter)
    _need(coordinates.get('schema')=='scar.capture-coordinates' and coordinates['run']==capture['run'],'retained capture coordinate identity differs')
    process=coordinates['target_process'];actors=[p for p in coordinates['processes'] if p['id']==process]
    _need(len(actors)==1 and actors[0]['run']==capture['run']['id'],'target process is not in this Run')
    pid=actors[0]['pid']
    _need(candidate.object_reference is not None and candidate.object_reference.rsplit(':',2)[-2]==str(pid),'candidate Python weak epoch is from another process')
    outputs={r['path']:r for r in capture['outputs']}
    bundle=fragment.bundle_manifest
    _need(bundle.uri in outputs and outputs[bundle.uri]['stored_sha256']==bundle.sha256,'value fragment bundle is not in this capture model')
    meter.artifact(bundle);meter.charge(stored=bundle.size_bytes);partitions=BundlePartitions(bundle.uri)
    _need(partitions.manifest_receipt['physical_sha256']==bundle.sha256,'native bundle receipt differs')
    match=re.fullmatch(r'#/associations/(0|[1-9][0-9]*)',candidate.association.locator)
    _need(match is not None,'unsupported original physical association locator');association_index=int(match[1])
    physical,selected,_=_report(candidate.association.artifact,meter,{
        'associations':lambda i,r:i==association_index,
        'epochs':lambda i,r:r.get('allocation')==candidate.allocation_id})
    _need(physical.get('schema')=='scar.tensor-physical-import' and physical.get('profile')==PROFILE,'physical importer profile differs')
    associations=selected['associations'];epochs=selected['epochs'];_need(len(associations)==len(epochs)==1,'physical original association/allocation absent')
    association=associations[0][1];allocation_ordinal,epoch=epochs[0]
    _need(all(association.get(k)==v for k,v in {'marker_instance':candidate.marker_instance_id,'provider_reference':candidate.provider_reference,
        'storage_region':candidate.storage_region_id,'allocation':candidate.allocation_id,'object':candidate.object_reference,'physical_reference':candidate.physical_locator}.items()),'candidate differs from exact original physical association')
    physical_artifacts=[decode(ProviderArtifact,v) for v in physical['artifacts'].values()]
    memberships={(json.dumps(r['artifact'],sort_keys=True),json.dumps(r['process'],sort_keys=True)) for r in coordinates['membership']}
    _need(all((json.dumps(encode(a),sort_keys=True),json.dumps(process,sort_keys=True)) in memberships for a in physical_artifacts),'physical inputs are not in this retained same-process capture')
    flow_artifact=fragment.reference_flow_index;meter.artifact(flow_artifact)
    meter.charge(stored=flow_artifact.size_bytes)
    flow,_=read_native_reference_flow_index(Path(flow_artifact.uri).parent,expected_sha256=flow_artifact.sha256)
    _need(flow.evidence_bundle_manifest==bundle and flow.eto_source==fragment.eto_source,'flow original bundle/ETO differs')
    bucket=_bucket(candidate.provider_reference,flow.bucket_count);refs=[r for r in flow.shards if r.bucket==bucket]
    _need(len(refs)==1,'provider port bucket absent');ref=refs[0];meter.charge(stored=ref.stored_bytes,decoded=ref.decoded_bytes)
    shard=_read_flow_shard(Path(flow_artifact.uri).parent,ref)
    rows=[r for g in shard['groups'].values() if g['provider_reference']==candidate.provider_reference for r in g['inputs']
          if r['instance']['wire']==candidate.marker_instance_id and r['path']==[association['argument_ordinal']]]
    _need(len(rows)==1,'exact original marker argument is absent/ambiguous');port_hint=rows[0]
    raw_instance,instance_ref=_record(partitions,'evidence','instances',port_hint['source_ordinal'],meter)
    instance=decode(OperationInstance,raw_instance)
    _need(instance.id.wire==candidate.marker_instance_id,'derived ordinal points at another original instance')
    port_index=fragment.native_port_index;meter.artifact(port_index)
    # The normal port reader rechecks exact row/instance/namespace and chunk.
    from scar.trace.native_port_sidecar import read_native_port_index
    meter.charge(stored=2*port_index.size_bytes+bundle.size_bytes)
    index=read_native_port_index(port_index.uri,expected_sha256=port_index.sha256)
    needed=[r for r in index.shards if r.first_source_ordinal<=port_hint['source_ordinal']<r.stop_source_ordinal]
    _need(len(needed)==1,'port shard locator absent');meter.charge(stored=needed[0].stored_bytes,decoded=needed[0].decoded_bytes)
    # query_native_ports normally re-reads the original instance's whole chunk.
    for c in partitions.manifest['graphs']['evidence']['tables']['instances']['chunks']:
        if c['first_ordinal']<=port_hint['source_ordinal']<=c['last_ordinal']:meter.charge(stored=c['physical_bytes'],decoded=c['decoded_bytes'])
    row=query_native_ports(instance,Path(port_index.uri).parent,bundle.uri,expected_index_sha256=port_index.sha256)
    ports=[p for p in row.ports if p.direction=='input' and p.path==(association['argument_ordinal'],)]
    _need(len(ports)==1 and ports[0].provider_reference==candidate.provider_reference and ports[0].descriptor_id==port_hint['descriptor_id'],'normal original marker port differs')
    marker_slots=[s for s in instance.metadata.get('tensor_slots',()) if s['role']=='inputs' and s['ordered_path']==[association['argument_ordinal']]]
    _need(len(marker_slots)==1 and marker_slots[0]['provider_reference']==candidate.provider_reference,'original marker tensor slot differs')
    raw_region,region_ref=_record(partitions,'values','regions',association_index,meter)
    region=decode(StorageRegion,raw_region)
    _need(region.id.wire==candidate.storage_region_id and region.allocation.wire==candidate.allocation_id
          and region.metadata['marker_instance']==candidate.marker_instance_id and region.metadata['argument_ordinal']==association['argument_ordinal']
          and region.metadata['physical_observation']==candidate.physical_locator,'original storage/view record differs')
    raw_allocation,allocation_ref=_record(partitions,'values','allocations',allocation_ordinal,meter)
    allocation=decode(StorageAllocation,raw_allocation)
    _need(allocation.id==region.allocation and allocation.device==region.device
          and allocation.metadata['provider_allocation_id']==epoch['provider_allocation_id'],'original physical allocation differs')
    dispatch_path=str(Path(candidate.association.artifact.uri).with_name('dispatch-bridge.json.gz'))
    _need(dispatch_path in outputs,'capture lacks original dispatch report')
    decl=outputs[dispatch_path];dispatch_artifact=ProviderArtifact(dispatch_path,decl['stored_sha256'],decl['stored_bytes'],'scar.dispatch-observation-import')
    dispatch,selected,_=_report(dispatch_artifact,meter,{
        'paths':lambda i,r:r.get('marker_instance')==candidate.marker_instance_id and r.get('provider_argument_ordinal')==association['argument_ordinal'],
        'observations':lambda i,r:r.get('marker_instance')==candidate.marker_instance_id})
    _need(dispatch.get('schema')=='scar.dispatch-observation-import' and len(selected['paths'])==len(selected['observations'])==1,'original dispatch marker/path absent')
    path_index,path=selected['paths'][0];observation_index,observation=selected['observations'][0]
    _need(observation['sequence']==path['sequence'] and observation['phase']==path['phase'],'dispatch original slot/context differs')
    context_ref=ProviderFactReference(dispatch_artifact,f'#/observations/{observation_index}')
    from scar.ir.v2.ids import ObjectID
    object_id=ObjectID(candidate.object_reference.removeprefix('object:'))
    result=TensorStorageObservation(decode(RunID,capture['run']['id']),decode(ProcessInstanceID,process),ObjectRef(bundle,object_id),instance_ref,
        ProviderFactReference(instance_ref.artifact,instance_ref.locator+'/metadata/tensor_slots/'+str(instance.metadata['tensor_slots'].index(marker_slots[0]))),
        candidate.association,context_ref,region_ref,allocation_ref)
    candidates=[{'interface':encode(i.instance),'port':encode(p),'qualification':'PROVIDER_REFERENCE_CANDIDATE_ONLY'} for i in fragment.interfaces for p in i.inputs+i.outputs if p.provider_reference==candidate.provider_reference]
    return {'schema':'scar.tensor-storage-observation-query','schema_version':1,'binding':encode(result),
        'marker_instance':encode(instance),'marker_port':encode(ports[0]),'storage_region':region.as_dict(),'allocation':allocation.as_dict(),
        'physical_association':association,'python_context':observation,'python_payload_path':path['original_payload_path'],
        'actual_operator_candidates':candidates,'marker_materialization':None,
        'scope':'existing marker object/port/storage observation only; retained same-capture provenance, no raw replay',
        'evidence_kind':'INFERRED_FIXED_COLLECTOR_SAME_HELD_TENSOR',
        'open':['actual-op storage binding at a different point','logical content/version identity','actual mutation and foreign writes','allocation bounds when no birth receipt','ready/completion and persistent object lifetime'],
        'measurements':meter.finish()}

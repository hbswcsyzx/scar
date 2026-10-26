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
from scar.ir.v2.evidence import OperationInstance, ProviderReference
from scar.ir.v2.values import StorageAllocation, StorageRegion, ObjectInstance
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_capture_batch import _JSONStream
from scar.trace.native_operator_value_interface import read_native_operator_value_fragment
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



def _find_record(partitions,graph,table,wire,meter):
    # This first-use bounded lookup walks only the necessary original chunks.
    # It returns the original record/locator and never constructs an index.
    for chunk in partitions.manifest['graphs'][graph]['tables'][table]['chunks']:
        meter.charge(stored=chunk['physical_bytes'],decoded=chunk['decoded_bytes'])
        # Use the ordinary reader, budgeted before opening each whole chunk.
        rows=partitions.selected_records(graph,table,tuple(range(chunk['first_ordinal'],chunk['last_ordinal']+1)))
        for row in rows:
            record=row['record'];identity=record['reference_id' if (graph,table)==('evidence','provider_references') else 'id']
            actual=identity.get('wire') if type(identity) is dict else identity
            if actual==wire:
                artifact=ProviderArtifact(str(partitions.root/chunk['uri']),chunk['physical_sha256'],chunk['physical_bytes'],'scar.bundle-record-chunk')
                meter.inputs.append((Path(artifact.uri),_stamp(Path(artifact.uri))))
                return record,ProviderFactReference(artifact,f"#/lines/{row['locator']['line']}/record")
    raise KeyError('original '+table+' record is absent: '+wire)

def query_tensor_storage_observation(value_fragment: ProviderArtifact, capture_model: ProviderArtifact, *,
                                     candidate_index=0,max_input_bytes=512_000_000,max_seconds=180):
    """Resolve one original physical candidate at its exact marker endpoint.

    Retained coordinates/imported facts are consumed, not replayed raw capture
    ownership. This query never upgrades a different op's payload/version.
    """
    meter=_Meter(max_input_bytes,max_seconds)
    meter.artifact(value_fragment)
    meter.charge(stored=value_fragment.size_bytes,decoded=value_fragment.size_bytes)
    fragment,values=read_native_operator_value_fragment(value_fragment.uri,expected_sha256=value_fragment.sha256)
    _need(type(candidate_index) is int and 0<=candidate_index<len(fragment.physical_candidates),'physical candidate absent')
    candidate=fragment.physical_candidates[candidate_index]
    capture=_json(capture_model,meter);_need(capture.get('schema')=='scar.capture-model','unsupported capture model')
    coordinates_artifact=decode(ProviderArtifact,capture['coordinate_binding']);coordinates=_json(coordinates_artifact,meter)
    _need(coordinates.get('schema')=='scar.capture-coordinates' and coordinates['run']==capture['run'],'retained capture coordinate identity differs')
    process=coordinates['target_process'];actors=[p for p in coordinates['processes'] if p['id']==process]
    _need(len(actors)==1 and actors[0]['run']==capture['run']['id'],'target process is not in this Run')
    pid=actors[0]['pid']
    declared=coordinates.get('tensor_physical_collector_declaration',{})
    _need(declared.get('profile')==PROFILE and declared.get('provider_revision')==PROVIDER_REVISION
          and declared.get('process_id')==pid,'unsupported physical provider profile/revision/process')
    _need(candidate.object_reference is not None and candidate.object_reference.rsplit(':',2)[-2]==str(pid),'candidate Python weak epoch is from another process')
    outputs={r['path']:r for r in capture['outputs']}
    bundle=fragment.bundle_manifest
    _need(bundle.uri in outputs and outputs[bundle.uri]['stored_sha256']==bundle.sha256,'value fragment bundle is not in this capture model')
    meter.artifact(bundle);meter.charge(stored=bundle.size_bytes,decoded=bundle.size_bytes);partitions=BundlePartitions(bundle.uri)
    _need(partitions.manifest_receipt['physical_sha256']==bundle.sha256,'native bundle receipt differs')
    match=re.fullmatch(r'#/associations/(0|[1-9][0-9]*)',candidate.association.locator)
    _need(match is not None,'unsupported original physical association locator');association_index=int(match[1])
    physical,selected,_=_report(candidate.association.artifact,meter,{
        'associations':lambda i,r:i==association_index,
        'epochs':lambda i,r:r.get('allocation')==candidate.allocation_id})
    _need(physical.get('schema')=='scar.tensor-physical-import' and type(physical.get('schema_version')) is int and physical['schema_version']==1 and physical.get('profile')==PROFILE,'physical importer profile differs')
    associations=selected['associations'];epochs=selected['epochs'];_need(len(associations)==len(epochs)==1,'physical original association/allocation absent')
    association=associations[0][1];allocation_ordinal,epoch=epochs[0]
    _need(all(association.get(k)==v for k,v in {'marker_instance':candidate.marker_instance_id,'provider_reference':candidate.provider_reference,
        'storage_region':candidate.storage_region_id,'allocation':candidate.allocation_id,'object':candidate.object_reference,'physical_reference':candidate.physical_locator}.items()),'candidate differs from exact original physical association')
    physical_artifacts=[decode(ProviderArtifact,v) for v in physical['artifacts'].values()]
    memberships={(json.dumps(r['artifact'],sort_keys=True),json.dumps(r['process'],sort_keys=True)) for r in coordinates['membership']}
    _need(all((json.dumps(encode(a),sort_keys=True),json.dumps(process,sort_keys=True)) in memberships for a in physical_artifacts),'physical inputs are not in this retained same-process capture')
    dispatch_path=str(Path(candidate.association.artifact.uri).with_name('dispatch-bridge.json.gz'))
    _need(dispatch_path in outputs,'capture lacks original dispatch report')
    decl=outputs[dispatch_path];dispatch_artifact=ProviderArtifact(dispatch_path,decl['stored_sha256'],decl['stored_bytes'],'scar.dispatch-observation-import')
    dispatch,selected,_=_report(dispatch_artifact,meter,{
        'paths':lambda i,r:r.get('marker_instance')==candidate.marker_instance_id and r.get('provider_argument_ordinal')==association['argument_ordinal'],
        'observations':lambda i,r:r.get('marker_instance')==candidate.marker_instance_id})
    _need(dispatch.get('schema')=='scar.dispatch-observation-import' and type(dispatch.get('schema_version')) is int and dispatch['schema_version']==1 and len(selected['paths'])==len(selected['observations'])==1,'original dispatch marker/path absent')
    path_index,path=selected['paths'][0];observation_index,observation=selected['observations'][0]
    _need(observation['sequence']==path['sequence'] and observation['phase']==path['phase'],'dispatch original slot/context differs')
    ancestry=observation['actual_provider_ancestry']
    _need(ancestry and ancestry[0]['instance']==candidate.marker_instance_id,'dispatch original marker ancestry differs')
    prefix='sha256:'+fragment.eto_source.sha256+'#/nodes/'
    raw_reference=ancestry[0]['raw_reference']
    _need(raw_reference.startswith(prefix) and re.fullmatch(r'0|[1-9][0-9]*',raw_reference[len(prefix):]) is not None,'marker has no exact original ETO ordinal locator')
    ordinal=int(raw_reference[len(prefix):])
    raw_instance,instance_ref=_record(partitions,'evidence','instances',ordinal,meter)
    instance=decode(OperationInstance,raw_instance)
    _need(instance.id.wire==candidate.marker_instance_id and instance.metadata['raw_reference']==raw_reference,
          'derived ordinal points at another original instance')
    marker_slots=[s for s in instance.metadata.get('tensor_slots',()) if s['role']=='inputs' and s['ordered_path']==[association['argument_ordinal']]]
    _need(len(marker_slots)==1 and marker_slots[0]['provider_reference']==candidate.provider_reference,'original marker tensor slot differs')
    # Markers are user annotations; the existing op-port sidecar deliberately
    # omits them. Their real ordered observation slots remain in this instance.
    marker_port=marker_slots[0]
    raw_region,region_ref=_record(partitions,'values','regions',association_index,meter)
    region=decode(StorageRegion,raw_region)
    _need(region.id.wire==candidate.storage_region_id and region.allocation.wire==candidate.allocation_id
          and region.metadata['marker_instance']==candidate.marker_instance_id and region.metadata['argument_ordinal']==association['argument_ordinal']
          and region.metadata['physical_observation']==candidate.physical_locator,'original storage/view record differs')
    raw_allocation,allocation_ref=_find_record(partitions,'values','allocations',candidate.allocation_id,meter)
    allocation=decode(StorageAllocation,raw_allocation)
    _need(allocation.id==region.allocation and allocation.device==region.device
          and allocation.metadata['provider_allocation_id']==epoch['provider_allocation_id'],'original physical allocation differs')
    raw_provider,provider_ref=_find_record(partitions,'evidence','provider_references',candidate.provider_reference,meter)
    provider=decode(ProviderReference,raw_provider)
    descriptors=[d for d in provider.metadata['descriptors'] if d['descriptor_id']==marker_port['descriptor_id']]
    _need(len(descriptors)==1,'original marker descriptor is absent/ambiguous');descriptor=descriptors[0]
    tensor=descriptor['tensor_tuple']
    _need(descriptor['shape']==list(region.shape) and descriptor['strides']==list(region.strides)
          and tensor[2]==region.offset and tensor[5]==region.device,'marker descriptor/storage geometry differs')
    raw_object,object_ref=_find_record(partitions,'values','objects',candidate.object_reference,meter)
    original_object=decode(ObjectInstance,raw_object)
    _need(original_object.metadata['process_id']==pid and original_object.scope==dispatch['scope'],
          'original Python object belongs to another process/dispatch scope')
    context_ref=ProviderFactReference(dispatch_artifact,f'#/observations/{observation_index}')
    result=TensorStorageObservation(decode(RunID,capture['run']['id']),decode(ProcessInstanceID,process),ObjectRef(bundle,original_object.id),instance_ref,
        ProviderFactReference(instance_ref.artifact,instance_ref.locator+'/metadata/tensor_slots/'+str(instance.metadata['tensor_slots'].index(marker_slots[0]))),
        candidate.association,context_ref,region_ref,allocation_ref)
    candidates=[{'interface':encode(i.instance),'port':encode(p),'qualification':'PROVIDER_REFERENCE_CANDIDATE_ONLY'} for i in fragment.interfaces for p in i.inputs+i.outputs if p.provider_reference==candidate.provider_reference]
    return {'schema':'scar.tensor-storage-observation-query','schema_version':1,'binding':encode(result),
        'marker_instance':encode(instance),'marker_port':marker_port,'provider_reference':encode(provider),'provider_reference_source':encode(provider_ref),'object_record':original_object.as_dict(),'object_record_source':encode(object_ref),'storage_region':region.as_dict(),'allocation':allocation.as_dict(),
        'physical_association':association,'python_context':observation,'python_payload_path':path['original_payload_path'],
        'actual_operator_candidates':candidates,'marker_materialization':None,
        'scope':'existing marker object/port/storage observation only; retained same-capture provenance, no raw replay',
        'evidence_kind':'INFERRED_FIXED_COLLECTOR_SAME_HELD_TENSOR',
        'open':['actual-op storage binding at a different point','logical content/version identity','actual mutation and foreign writes','allocation bounds when no birth receipt','ready/completion and persistent object lifetime'],
        'measurements':meter.finish()}

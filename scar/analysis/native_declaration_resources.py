"""Read-only native declaration -> original provider work/resource navigation.

The SQLite file only locates original EEG edges. Every returned edge, native
occurrence and work row is read normally from its exact original artifact. No
ProgramGraph/ExecutionModel/WorkTicket or resource identity is minted here.
"""
from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
import gzip, io, json, sqlite3

from scar.analysis.native_declaration_interfaces import (
    NativeDeclarationBudget, read_native_declaration_fragment, _locator)
from scar.analysis.tensor_storage_index import _decode_edge
from scar.analysis.tensor_storage_query import _Meter, _need
from scar.ir.execution.content import WorkEvidenceBinding
from scar.ir.execution.coordinates import ExecutionRun
from scar.ir.execution.fragment_relations import (
    Encoding, EvidenceEdgeRef, EvidenceInstanceRef, FragmentLocator, HostRelationKind,
    RuntimeScope, WorkActivityProjectionLink, WorkHostRelation, WorkTicketRef)
from scar.ir.execution.ids import ProcessInstanceID
from scar.ir.execution.model import LegacyOperationRef
from scar.ir.execution.native_declarations import NativeDeclarationOccurrence
from scar.ir.execution.work import ExternalWorkSource, WorkQuiescence, WorkSubmission
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.evidence import EvidenceNodeKind, EvidenceRelation, OperationInstance
from scar.ir.v2.contracts import ResourceRequirement
from scar.ir.v2.ids import OperationInstanceID, ResourceID
from scar.store.bundle_partitions import BundlePartitions

INDEX_SCHEMA = 'scar.native-work-resource-locator-index'
_RELATIONS = ('submits_work', 'provider_scope_association', 'uses_resource')


def _canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False)+'\n').encode()


@dataclass(frozen=True, slots=True)
class NativeResourceBudget:
    max_input_bytes: int = 2_000_000_000
    max_output_bytes: int = 128_000_000
    max_seconds: int = 240
    max_connections: int = 4096

    def __post_init__(self):
        _need(all(type(getattr(self, f.name)) is int and getattr(self, f.name)>0
                  for f in fields(self)), 'positive native resource budgets required')


class _Records:
    def __init__(self, artifact, meter):
        self.artifact, self.meter, self.cache = artifact, meter, {}
        raw=meter.artifact(artifact,4_000_000);meter.charge(decoded=len(raw))
        _need(artifact.schema=='scar.partitioned-ir-bundle','original bundle required')
        self.partitions=BundlePartitions(artifact.uri)
        _need(self.partitions.manifest_receipt=={'path':artifact.uri,
            'physical_sha256':artifact.sha256,'physical_bytes':artifact.size_bytes},'bundle receipt differs')
        # The public partition reader also read this exact small root.
        meter.charge(stored=artifact.size_bytes,decoded=artifact.size_bytes)

    def chunk(self, graph, table, number):
        d=self.partitions.manifest['graphs'][graph]['tables'][table]['chunks'][number]
        key=(graph,table)
        if key not in self.cache or self.cache[key][0]!=number:
            a=ProviderArtifact(str(self.partitions.root/d['uri']),d['physical_sha256'],
                               d['physical_bytes'],'scar.bundle-record-chunk')
            raw=self.meter.artifact(a,17_000_000)
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:payload=stream.read(16_000_001)
            self.meter.charge(decoded=len(payload))
            _need(len(payload)==d['decoded_bytes'] and sha256(payload).hexdigest()==d['decoded_sha256']
                  and payload.endswith(b'\n') and payload.count(b'\n')==d['lines'],'original chunk EOF/bytes/SHA/lines differ')
            # One immutable verified byte chunk per table, not every chunk or
            # mutable IR validation. This avoids edge/instance/resource thrash.
            self.cache[key]=(number,payload)
        return d,self.cache[key][1]

    def row(self, graph, table, ordinal):
        chunks=self.partitions.manifest['graphs'][graph]['tables'][table]['chunks']
        no=next((i for i,d in enumerate(chunks)if d['first_ordinal']<=ordinal<=d['last_ordinal']),None)
        _need(no is not None,'original table ordinal absent')
        d,payload=self.chunk(graph,table,no)
        line=payload.splitlines()[ordinal-d['first_ordinal']]
        row=loads(line.decode());_need(set(row)=={'ordinal','record'} and row['ordinal']==ordinal,'original row envelope differs')
        row={**row,'locator':{'artifact':d,'line':ordinal-d['first_ordinal']+1}}
        return row,_locator(self.partitions,graph,table,row)

    def iter_edges(self):
        table=self.partitions.manifest['graphs']['evidence']['tables']['edges'];visited=0
        for no in range(len(table['chunks'])):
            d,payload=self.chunk('evidence','edges',no)
            for local,line in enumerate(payload.splitlines()):
                row=loads(line.decode());ordinal=d['first_ordinal']+local
                _need(set(row)=={'ordinal','record'} and row['ordinal']==ordinal,'original edge ordinal differs')
                visited+=1;yield ordinal,row['record']
        _need(visited==table['records'],'original edge denominator differs')


def build_native_resource_index(bundle:ProviderArtifact, out, *, budget=None)->ProviderArtifact:
    """One bounded owned edge pass; only ID/relation/ordinal locators persist."""
    b=budget or NativeResourceBudget();b.__post_init__();meter=_Meter(b.max_input_bytes,b.max_seconds)
    records=_Records(bundle,meter);root=Path(out).resolve();root.mkdir(parents=True,exist_ok=False)
    database=root/'locators.sqlite';db=sqlite3.connect(database)
    selected=visited=0
    try:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA temp_store=FILE; PRAGMA cache_size=-2048; '
            'CREATE TABLE edges(id TEXT PRIMARY KEY, relation TEXT,source TEXT,target TEXT,ordinal INTEGER UNIQUE);')
        for ordinal,row in records.iter_edges():
            visited+=1
            if row.get('relation') not in _RELATIONS:continue
            edge=_decode_edge(row)
            _need(edge.source.kind is EvidenceNodeKind.OPERATION_INSTANCE,'resource edge source differs')
            if edge.relation is EvidenceRelation.USES_RESOURCE:
                if edge.target.kind is not EvidenceNodeKind.RESOURCE:continue
            else:_need(edge.target.kind is EvidenceNodeKind.OPERATION_INSTANCE,'provider work edge target differs')
            db.execute('INSERT INTO edges VALUES(?,?,?,?,?)',(edge.edge_id,edge.relation.value,
                       edge.source.reference.wire,edge.target.reference.wire,ordinal));selected+=1
            if selected%4096==0:
                meter.charge();_need(database.stat().st_size<=b.max_output_bytes,'locator output budget exceeded')
        db.executescript('CREATE INDEX source_relation ON edges(source,relation); CREATE INDEX target_relation ON edges(target,relation);')
        db.commit()
    finally:db.close()
    raw=database.read_bytes();_need(len(raw)<=b.max_output_bytes,'locator output budget exceeded')
    # Hashing this derived output is output I/O, never claimed as source input.
    dbref=ProviderArtifact(str(database),sha256(raw).hexdigest(),len(raw),'sqlite.native-work-resource-locators')
    doc={'schema':INDEX_SCHEMA,'schema_version':1,'bundle':encode(bundle),'database':encode(dbref),
         'original_edges_visited':visited,'provider_resource_locators':selected,'index_is_graph_authority':False,
         'input_measurements':meter.finish(),'output_bytes':len(raw)}
    payload=_canonical(doc);_need(len(raw)+len(payload)<=b.max_output_bytes,'index manifest output budget exceeded')
    p=root/'manifest.json';p.write_bytes(payload)
    return ProviderArtifact(str(p),sha256(payload).hexdigest(),len(payload),INDEX_SCHEMA)


@dataclass(frozen=True, slots=True)
class NativeResourceReference:
    resource: ResourceID
    original_edge: FragmentLocator
    original_requirement: FragmentLocator
    requirement: ResourceRequirement


@dataclass(frozen=True, slots=True)
class NativeDeclarationWorkConnection:
    native: NativeDeclarationOccurrence
    projection: WorkActivityProjectionLink
    host: WorkHostRelation
    submission: WorkSubmission
    binding: WorkEvidenceBinding
    quiescence: WorkQuiescence
    resources: tuple[NativeResourceReference,...]


class NativeDeclarationResourceSession:
    """Exact same-Run query/batch view; close rejects source mutation."""
    def __init__(self,index:ProviderArtifact,work_manifest:ProviderArtifact,
                 coordinates:ProviderArtifact,*,budget=None):
        self.budget=budget or NativeResourceBudget(max_input_bytes=512_000_000,max_seconds=180)
        self.budget.__post_init__();self.meter=_Meter(self.budget.max_input_bytes,self.budget.max_seconds)
        self.closed=False;self._work_cache={};self._receipt_locations={}
        self.index=index;doc=self._document(index)
        _need(doc['schema']==INDEX_SCHEMA and doc['schema_version']==1 and doc['index_is_graph_authority'] is False,'unsupported resource locator index')
        self.bundle=decode(ProviderArtifact,doc['bundle']);self.records=_Records(self.bundle,self.meter)
        database=decode(ProviderArtifact,doc['database']);self.meter.artifact(database,self.budget.max_output_bytes)
        self.db=sqlite3.connect(Path(database.uri).as_uri()+'?mode=ro&immutable=1',uri=True)
        self.work_artifact=work_manifest;self.work=self._document(work_manifest)
        _need(self.work['schema']=='scar.native-activity-work-report' and self.work['schema_version'] in (1,2),'normal native work manifest required')
        _need(self.work['original_eeg_manifest']=={'path':self.bundle.uri,'physical_sha256':self.bundle.sha256,'physical_bytes':self.bundle.size_bytes},'work/index original namespace differs')
        coord=self._document(coordinates);self.coordinates=coordinates
        _need(coord['schema']=='scar.capture-coordinates' and self.work['coordinates']['sha256']==coordinates.sha256
              and self.work['coordinates']['size_bytes']==coordinates.size_bytes,'work/coordinate receipt differs')
        run=decode(ExecutionRun,coord['run']);process=decode(ProcessInstanceID,coord['target_process'])
        _need(encode(run.id)==self.work['run'] and encode(process)==self.work['process'],'work/index crosses Run or process')
        self.scope=RuntimeScope(run.id,process,coordinates)
        self.eto=next(decode(ProviderArtifact,m['artifact'])for m in coord['membership']
                      if m['artifact']['schema']=='pytorch.execution-trace.v1')
        _need(any(m['artifact']==encode(self.eto) and m['process']==encode(process)for m in coord['membership']),
              'ETO source is not in exact Run/process')
        self.pid=next(p['pid']for p in coord['processes']if p['id']==encode(process))
        total=0
        for shard in self.work['shards']:
            desc=shard['source_receipts'];payload=self._payload(desc,'scar.native-activity-work.receipts')
            rows=payload.splitlines();_need(len(rows)==shard['records'],'work receipt denominator differs')
            for line,raw in enumerate(rows,1):
                r=loads(raw.decode());identity=self.work['native_namespace']+':kineto:'+str(r['raw_ordinal'])
                _need(identity not in self._receipt_locations,'duplicate original work activity')
                self._receipt_locations[identity]=(shard,line,r);total+=1
        _need(total==self.work['qualified_single_activities'],'work denominator not conserved')
        self.work_denominator=total

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
    def close(self):
        if not self.closed:
            try:self.meter.finish()
            finally:self.db.close();self._work_cache.clear();self.closed=True
    def _check(self):_need(not self.closed,'native resource session is closed');self.meter.charge()
    def _document(self,artifact):
        raw=self.meter.artifact(artifact,16_000_000);self.meter.charge(decoded=len(raw));return loads(raw.decode())
    def _payload(self,d,schema):
        a=ProviderArtifact(d['uri'],d['stored_sha256'],d['stored_bytes'],schema)
        raw=self.meter.artifact(a,16_000_000)
        if d['compression']=='gzip':
            with gzip.GzipFile(fileobj=io.BytesIO(raw))as stream:payload=stream.read(16_000_001)
        else:_need(d['compression']=='none','unsupported work encoding');payload=raw
        self.meter.charge(decoded=len(payload))
        _need(len(payload)==d['decoded_bytes'] and sha256(payload).hexdigest()==d['decoded_sha256'],'work payload SHA/bytes differs')
        return payload
    def _edge(self,entry):
        identity,relation,source,target,ordinal=entry
        row,locator=self.records.row('evidence','edges',ordinal);edge=_decode_edge(row['record'])
        _need((edge.edge_id,edge.relation.value,edge.source.reference.wire,edge.target.reference.wire)==entry[:4],
              'derived edge locator changed original fact')
        _need(edge.evidence.scope==self.work['native_namespace'],'original provider edge changes native namespace')
        return edge,locator
    def _resource(self,identity):
        table=self.records.partitions.manifest['graphs']['semantic']['tables']['resources']
        found=[]
        for no,d in enumerate(table['chunks']):
            _,payload=self.records.chunk('semantic','resources',no)
            for offset,line in enumerate(payload.splitlines()):
                row=loads(line.decode());ordinal=d['first_ordinal']+offset
                _need(row['ordinal']==ordinal,'resource requirement ordinal differs')
                if row['record']['id']['wire']==identity.wire:
                    value=decode(ResourceRequirement,row['record'])
                    item={**row,'locator':{'artifact':d,'line':offset+1}}
                    found.append((value,_locator(self.records.partitions,'semantic','resources',item)))
        _need(len(found)==1,'original resource requirement missing or ambiguous')
        return found[0]
    def _paths(self,source):
        result=[]
        for edge in self.db.execute("SELECT * FROM edges WHERE source=? AND relation='provider_scope_association' ORDER BY ordinal",(source.wire,)):
            if edge[3].removeprefix('opinst:')in self._receipt_locations:result.append((edge,))
            for submit in self.db.execute("SELECT * FROM edges WHERE source=? AND relation='submits_work' ORDER BY ordinal",(edge[3],)):
                if submit[3].removeprefix('opinst:')in self._receipt_locations:result.append((edge,submit))
        return result
    def candidate(self,shard_manifest:ProviderArtifact):
        """Metadata-only mechanical selector; query() supplies qualification."""
        self._check();doc=self._document(shard_manifest)
        _need(doc['schema']=='scar.native-declaration-shard','native shard manifest required')
        for a in doc['fragments']:
            artifact=decode(ProviderArtifact,a);fragment=self._document(artifact)
            for row in fragment['occurrences']:
                link=decode(NativeDeclarationOccurrence,row)
                if self._paths(link.native.instance):return artifact,link.native.instance
        return None
    def _projection(self,identity):
        shard,line,receipt=self._receipt_locations[identity]
        if shard['index'] not in self._work_cache:
            evidence=self._document(ProviderArtifact(shard['evidence']['uri'],shard['evidence']['stored_sha256'],
                shard['evidence']['stored_bytes'],'scar.ir.v2.evidence'))
            work=self._payload(shard['work_records'],'scar.native-activity-work.rows').splitlines()
            _need(len(work)==len(evidence['instances'])==shard['records'],'work shard inventory differs')
            self._work_cache={shard['index']:(evidence,work)}
        evidence,rows=self._work_cache[shard['index']]
        row=loads(rows[line-1].decode());submission=decode(WorkSubmission,row['submission'])
        binding=decode(WorkEvidenceBinding,row['binding']);quiet=decode(WorkQuiescence,row['quiescence'])
        instance=decode(OperationInstance,evidence['instances'][line-1]);ea=ProviderArtifact(
            shard['evidence']['uri'],shard['evidence']['stored_sha256'],shard['evidence']['stored_bytes'],'scar.ir.v2.evidence')
        _need(instance.id.value==identity and binding.instance==instance.id and binding.artifact==ea
              and binding.source==ProviderFactReference(ea,f'#/instances/{line-1}')
              and submission.id==binding.ticket==quiet.ticket and encode(submission.id)==receipt['ticket']
              and receipt['projection_index']==line-1,'work original ticket/projection differs')
        _need(type(submission.origin)is ExternalWorkSource and submission.origin.point.run==self.scope.run
              and submission.origin.point.process==self.scope.process and quiet.observed_at.run==self.scope.run
              and quiet.observed_at.process==self.scope.process,'work source crosses Run/process')
        original,loc=self.records.row('evidence','instances',receipt['original_eeg_ordinal'])
        _need(original['record']==evidence['instances'][line-1]
              and original['record']['metadata']['raw_reference']==receipt['raw_reference']
              and receipt['original_locator']['artifact']==original['locator']['artifact']
              and receipt['original_locator']['line']==original['locator']['line'],'work original EEG source differs')
        d=shard['work_records'];a=ProviderArtifact(d['uri'],d['stored_sha256'],d['stored_bytes'],'scar.native-activity-work.rows')
        workloc=FragmentLocator(a,d['decoded_sha256'],d['decoded_bytes'],Encoding.GZIP_JSONL,line,'#/submission',
            ProviderFactReference(self.work_artifact,f"#/shards/{shard['index']}/work_records"))
        r=shard['source_receipts'];ra=ProviderArtifact(r['uri'],r['stored_sha256'],r['stored_bytes'],'scar.native-activity-work.receipts')
        rl=FragmentLocator(ra,r['decoded_sha256'],r['decoded_bytes'],Encoding.GZIP_JSONL,line,'#',
            ProviderFactReference(self.work_artifact,f"#/shards/{shard['index']}/source_receipts"))
        bl=FragmentLocator(a,d['decoded_sha256'],d['decoded_bytes'],Encoding.GZIP_JSONL,line,'#/binding',workloc.declaration)
        projection=WorkActivityProjectionLink(self.scope,WorkTicketRef(workloc,submission.id),bl,
            LegacyOperationRef(ea,instance.id),EvidenceInstanceRef(loc,instance.id),rl)
        return projection,submission,binding,quiet
    def query(self,fragment:ProviderArtifact,*,source_instances=None):
        self._check()
        if source_instances is not None:_need(type(source_instances)is tuple and all(type(x)is OperationInstanceID for x in source_instances),'typed original native selectors required')
        view=read_native_declaration_fragment(fragment,budget=NativeDeclarationBudget(
            max_input_bytes=self.budget.max_input_bytes-self.meter.stored-self.meter.decoded,
            max_seconds=self.budget.max_seconds))
        self.meter.charge(stored=view.measurements['stored_bytes'],decoded=view.measurements['decoded_bytes'])
        _need(any(r.id==self.scope.run for r in view.execution.runs)
              and any(p.id==self.scope.process for p in view.execution.processes),'canonical fragment crosses Run/process')
        links=view.occurrences if source_instances is None else tuple(x for x in view.occurrences if x.native.instance in source_instances)
        _need(source_instances is None or len(links)==len(set(source_instances)),'native selector missing/ambiguous')
        result=[]
        for native in links:
            _need(native.native.locator.declaration.artifact==self.bundle,'canonical native changes original bundle namespace')
            ordinal_chunk=native.native.locator.declaration.locator.rsplit('/',1)[-1]
            chunks=self.records.partitions.manifest['graphs']['evidence']['tables']['instances']['chunks']
            d=chunks[int(ordinal_chunk)];ordinal=d['first_ordinal']+native.native.locator.line-1
            hostrow,hostloc=self.records.row('evidence','instances',ordinal)
            host=decode(OperationInstance,hostrow['record'])
            _need(hostloc==native.native.locator and host.id==native.native.instance and host.process_id==self.pid
                  and host.metadata.get('provider')=='ETO'
                  and host.metadata.get('raw_reference','').startswith('sha256:'+self.eto.sha256+'#/nodes/'),
                  'canonical original ETO host/source/process differs')
            for path in self._paths(host.id):
                checked=[self._edge(e)for e in path]
                refs=tuple(EvidenceEdgeRef(loc,edge.edge_id,edge.relation.value,edge.source.reference,edge.target.reference)
                           for edge,loc in checked)
                identity=refs[-1].target.value
                projection,submission,binding,quiet=self._projection(identity)
                relation=WorkHostRelation(projection.work,HostRelationKind.PROVIDER_SCOPE_CONTEXT,
                    native.native,projection.original,refs,None)
                resources=[]
                for edge_entry in self.db.execute("SELECT * FROM edges WHERE source=? AND relation='uses_resource' ORDER BY ordinal",(projection.original.instance.wire,)):
                    edge,locator=self._edge(edge_entry)
                    _need(edge.target.kind is EvidenceNodeKind.RESOURCE,'original GPU resource target differs')
                    requirement,requirement_locator=self._resource(edge.target.reference)
                    resources.append(NativeResourceReference(edge.target.reference,locator,requirement_locator,requirement))
                _need(len(result)<self.budget.max_connections,'native work connection budget exceeded')
                result.append(NativeDeclarationWorkConnection(native,projection,relation,submission,binding,quiet,tuple(resources)))
        return {'connections':tuple(result),'selected_native_occurrences':len(links),'declared_work_count':self.work_denominator,
            'measurements':self.meter.finish(),'scope':'EXACT_ORIGINAL_PROVIDER_SCOPE_PATH',
            'direct_call_established':False,'normal_completion_established':False,'state_content_ready_established':False}

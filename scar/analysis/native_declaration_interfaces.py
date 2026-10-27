"""Build canonical native structure from published ordered ports, without markers.

The original bundle and port rows remain the only native fact authority. The
new typed relation points to their exact records rather than projecting an EEG
or pretending an unknown completion selected NORMAL. Static interfaces share
one catalog; bounded execution fragments contain only their input/invoke side.
"""
from dataclasses import dataclass,fields
from hashlib import sha256
from pathlib import Path
import json,time

from scar.analysis.tensor_storage_query import _Meter,_need,_stamp
from scar.ir.record_codec import decode,encode,loads as strict_json
from scar.ir.program.codec import dumps as program_dumps,loads as program_loads
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference,ProviderRunScope
from scar.ir.execution.codec import dumps as execution_dumps,loads as execution_loads
from scar.ir.execution.common import EvidencePoint,Unresolved
from scar.ir.execution.content import NativeInputRef,ValueDenotation
from scar.ir.execution.coordinates import (ExecutionRun,ProcessInstance,RegionActivation,ExecutionSegment,
    InitialEntry,UnresolvedHostThread,BlockVisit,OperationOccurrence,ValueOccurrence,UseOccurrence,ProgramSnapshot)
from scar.ir.execution.fragment_relations import EvidenceInstanceRef,FragmentLocator,Encoding
from scar.ir.execution.ids import (RegionActivationID,ExecutionSegmentID,BlockVisitID,OperationOccurrenceID,
    ValueOccurrenceID,DenotationID)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.native_declarations import NativeDeclarationOccurrence
from scar.ir.execution.native_port_protocol import PROFILE_V2,canonical
from scar.ir.execution.validation import prepare_program_snapshot,validate
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.semantic import OperationDefinition
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import (read_native_port_index,_read_shard,_manifest_identity,_identity_from_values)
from scar.trace.native_protocol import _build_program
from scar.trace.native_schema import PROVIDER_REVISION

PROFILE='NATIVE_DECLARATION_CANONICAL_INTERFACE_V1'


@dataclass(frozen=True,slots=True)
class NativeDeclarationBudget:
    max_input_bytes:int=4_000_000_000
    max_output_bytes:int=8_000_000_000
    max_seconds:int=1800
    max_operations_per_fragment:int=256
    max_fragment_bytes:int=64_000_000

    def __post_init__(self):
        _need(all(type(getattr(self,f.name))is int and getattr(self,f.name)>0 for f in fields(self)),'positive native declaration budgets required')
        _need(self.max_operations_per_fragment<=4096,'native fragment operation ceiling')


def _artifact(path,raw,schema):return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _locator(partitions,graph,table,row):
    c=row['locator']['artifact'];n=next(i for i,v in enumerate(partitions.manifest['graphs'][graph]['tables'][table]['chunks'])if v==c)
    return FragmentLocator(ProviderArtifact(str(partitions.root/c['uri']),c['physical_sha256'],c['physical_bytes'],
        'scar.bundle-record-chunk'),c['decoded_sha256'],c['decoded_bytes'],Encoding.GZIP_JSONL,
        row['locator']['line'],'#/record',ProviderFactReference(
        ProviderArtifact(partitions.manifest_receipt['path'],partitions.manifest_receipt['physical_sha256'],
            partitions.manifest_receipt['physical_bytes'],partitions.manifest['schema']),
        f'#/graphs/{graph}/tables/{table}/chunks/{n}'))


class NativeDeclarationSession:
    def __init__(self,index:ProviderArtifact,bundle_dir,coordinates:ProviderArtifact,*,budget=None):
        self.budget=budget or NativeDeclarationBudget();self.budget.__post_init__()
        self.meter=_Meter(self.budget.max_input_bytes,self.budget.max_seconds)
        _need(type(index)is ProviderArtifact and index.schema=='scar.native-boxed-port-index','typed native port index required')
        self.index_artifact=index;self.root=Path(index.uri).parent
        self.meter.artifact(index,16_000_000)
        self.meter.charge(stored=index.size_bytes,decoded=index.size_bytes)
        self.index=read_native_port_index(index.uri,expected_sha256=index.sha256)
        if type(bundle_dir)is ProviderArtifact:
            self.bundle=bundle_dir;self.meter.artifact(self.bundle,4_000_000)
        else:
            p=Path(bundle_dir).resolve();p=p/'manifest.json'if p.is_dir()else p
            self.bundle=ProviderArtifact(str(p),self.index.evidence_manifest_sha256,p.stat().st_size,'scar.partitioned-ir-bundle')
            self.meter.artifact(self.bundle,4_000_000)
        self.meter.charge(stored=self.bundle.size_bytes,decoded=self.bundle.size_bytes)
        self.partitions=BundlePartitions(self.bundle.uri)
        _need(_manifest_identity(self.partitions)==_identity_from_values(self.index),'bundle/port source identities differ')
        self.coordinates=coordinates
        raw=self.meter.artifact(coordinates,16_000_000);self.meter.charge(decoded=len(raw));doc=strict_json(raw.decode())
        _need(doc['schema']=='scar.capture-coordinates','normal retained coordinates required')
        self.run=decode(ExecutionRun,doc['run'])
        self.process=next(decode(ProcessInstance,p)for p in doc['processes']if p['id']==doc['target_process'])
        self.eto=ProviderArtifact(self.index.source_uri,self.index.source_sha256,self.index.source_raw_bytes,'pytorch.execution-trace.v1')
        _need(any(r['artifact']==encode(self.eto)and r['process']==encode(self.process.id)for r in doc['membership']),
              'original ETO is outside this retained Run/process membership')
        self._source_cache={};self._definitions={};self._port_cache=None;self._closed=False
        self._output=0;self._catalog=None;self._prepared=None;self._program=None;self._layouts=None
        self._interfaces={};self._row_signatures={};self._native_scope=None

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
    def close(self):
        if not self._closed:
            try:self.meter.finish()
            finally:
                self._closed=True;self._source_cache.clear();self._definitions.clear();self._port_cache=None
                self._program=None;self._layouts=None;self._prepared=None
    def _check(self):_need(not self._closed,'native declaration session is closed');self.meter.charge()
    def _write(self,path,raw,schema,maximum=None):
        self._check();_need(len(raw)<=(maximum or self.budget.max_fragment_bytes),'native output file ceiling')
        _need(self._output+len(raw)<=self.budget.max_output_bytes,'native output total ceiling')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb')as f:f.write(raw)
        self._output+=len(raw);return _artifact(path,raw,schema)
    def _ports(self,no):
        self._check();_need(type(no)is int and 0<=no<len(self.index.shards),'native source shard selector')
        if self._port_cache is None or self._port_cache[0]!=no:
            ref=self.index.shards[no];self.meter.charge(stored=ref.stored_bytes,decoded=ref.decoded_bytes)
            shard=_read_shard(self.root,ref);p=self.root/ref.path;self.meter.inputs.append((p,_stamp(p)))
            self._port_cache=(no,shard)
        return self._port_cache[1]
    def _records(self,graph,table,ordinals):
        self._check();result=[]
        for chunk in self.partitions.manifest['graphs'][graph]['tables'][table]['chunks']:
            wanted=[n for n in ordinals if chunk['first_ordinal']<=n<=chunk['last_ordinal']]
            if not wanted:continue
            key=(graph,table,chunk['first_ordinal'])
            if key not in self._source_cache:
                self.meter.charge(stored=chunk['physical_bytes'],decoded=chunk['decoded_bytes'])
                rows=self.partitions.selected_records(graph,table,tuple(range(chunk['first_ordinal'],chunk['last_ordinal']+1)))
                if graph=='evidence':
                    for old in tuple(self._source_cache):
                        if old[:2]==(graph,table):del self._source_cache[old]
                # Cache owned immutable source bytes, not mutable validated IR.
                self._source_cache[key]={r['ordinal']:(canonical(r['record']),r['locator'])for r in rows}
                p=self.partitions.root/chunk['uri'];self.meter.inputs.append((p,_stamp(p)))
            for n in wanted:
                raw,locator=self._source_cache[key][n]
                result.append({'ordinal':n,'record':strict_json(raw.decode()),'locator':locator})
        _need(len(result)==len(set(ordinals)),'original bundle row selector incomplete')
        return sorted(result,key=lambda r:r['ordinal'])
    def _definition(self,identity):
        if identity not in self._definitions:
            for chunk in self.partitions.manifest['graphs']['semantic']['tables']['definitions']['chunks']:
                key=('semantic','definitions',chunk['first_ordinal'])
                if key not in self._source_cache:
                    rows=self._records('semantic','definitions',tuple(range(chunk['first_ordinal'],chunk['last_ordinal']+1)))
                else:
                    rows=[{'ordinal':n,'record':strict_json(raw.decode()),'locator':loc}
                          for n,(raw,loc)in self._source_cache[key].items()]
                for r in rows:
                    id_=r['record']['id']['wire']
                    if id_ not in self._definitions:self._definitions[id_]=(canonical(r['record']),_locator(self.partitions,'semantic','definitions',r))
                if identity in self._definitions:break
        _need(identity in self._definitions,'native definition missing from original bundle')
        raw,loc=self._definitions[identity];return decode(OperationDefinition,strict_json(raw.decode())),loc
    def _source(self,row):
        r=self._records('evidence','instances',(row.source_ordinal,))[0]
        instance=decode(OperationInstance,r['record'])
        _need(instance.id==row.instance and instance.definition==row.definition
            and instance.metadata.get('provider')=='ETO'
            and instance.metadata.get('raw_reference')=='sha256:'+self.eto.sha256+'#/nodes/'+str(row.source_ordinal)
            and instance.process_id==self.process.pid,'native instance/ports/Run/process/source differs')
        for p in row.ports:
            if p.kind=='TENSOR':
                slots=[s for s in instance.metadata.get('tensor_slots',())if s.get('role')==('inputs'if p.direction=='input'else'outputs')and s.get('ordered_path')==list(p.path)]
                _need(len(slots)==1 and slots[0]['provider_reference']==p.provider_reference
                    and slots[0]['descriptor_id']==p.descriptor_id,'ordered Tensor port differs from original instance')
        definition,definition_loc=self._definition(row.definition.wire)
        native=EvidenceInstanceRef(_locator(self.partitions,'evidence','instances',r),instance.id)
        return instance,definition,native,definition_loc
    def _interface(self,row,definition):
        raw=definition.metadata.get('op_schema');contract=definition.metadata.get('native_schema_contract',{})
        schema=type(raw)is str and bool(raw)
        if schema:
            _need(definition.metadata.get('provider_revision')==PROVIDER_REVISION
                and contract.get('raw_schema')==raw
                and contract.get('schema_sha256')==sha256(raw.encode()).hexdigest(),
                'pinned original schema declaration differs')
        ports={d:[{'path':list(p.path),'type':p.provider_type or 'opaque.unresolved','tensor':p.kind=='TENSOR'}
            for p in row.ports if p.direction==direction]for d,direction in(('inputs','input'),('outputs','output'))}
        signature={'provider_revision':PROVIDER_REVISION,'schema':raw if schema else 'observed boxed interface: '+definition.label,
            **ports,'interface_kind':'REGISTERED_SCHEMA'if schema else 'OBSERVED_BOXED_INTERFACE'}
        sig=sha256(canonical(signature)).hexdigest()
        return {'signature_id':sig,'signature':signature,'ports':ports}
    def prepare_catalog(self,out_dir,*,shard_indices=None,source_ordinals=None):
        self._check();_need(self._catalog is None,'native catalog already prepared')
        root=Path(out_dir).resolve();_need(not root.exists(),'fresh native catalog directory required')
        selected=tuple(range(len(self.index.shards)))if shard_indices is None else tuple(shard_indices)
        wanted=None if source_ordinals is None else set(source_ordinals)
        for no in selected:
            for row in self._ports(no).rows:
                if wanted is not None and row.source_ordinal not in wanted:continue
                instance,definition,_,_=self._source(row)
                scope=instance.id.value.rsplit(':eto:',1)[0]
                _need(self._native_scope in(None,scope),'native source scope differs within catalog');self._native_scope=scope
                interface=self._interface(row,definition);sig=interface['signature_id']
                self._interfaces.setdefault(sig,interface);self._row_signatures[row.source_ordinal]=sig
        _need(self._interfaces,'selected native catalog has no original operator rows')
        doc={'schema':'scar.pinned-torch-protocol-interface','schema_version':1,'profile':PROFILE,
            'interfaces':{k:v['signature']for k,v in self._interfaces.items()},
            'effect_contract':'UNKNOWN; observed ports and optional schema are distinct','content_version_claimed':False}
        self._interface_bytes=canonical(doc)
        iface=self._write(root/'interfaces.json',self._interface_bytes,doc['schema'])
        source={'reference_profile':PROFILE_V2,'native_scope':self._native_scope,
            'run':self.run.id.value,'pid':self.process.pid,'artifacts':{'eto':encode(self.eto)}}
        scope=ProviderRunScope(self.run.id.value,self.process.pid,
            f'published native source ordinals [{self.index.first_source_ordinal},{self.index.stop_source_ordinal}); completion unselected',
            'retained ETO source records; no inferred execution total order')
        program,layouts=_build_program(list(self._interfaces.values()),source,iface,execution_scope=scope,
            interface_description='observed native boxed interfaces with optional pinned schema declarations')
        self._prepared=prepare_program_snapshot(program);raw=self._prepared.canonical_bytes(program)
        pa=self._write(root/'program.json',raw,'scar.program-graph')
        self._program=program;self._layouts=layouts;self._snapshot=ProgramSnapshot(pa,self._prepared.schema_version)
        self._interface_artifact=iface
        manifest={'schema':'scar.native-declaration-catalog','schema_version':1,'profile':PROFILE,
            'index':encode(self.index_artifact),'bundle':encode(self.bundle),'coordinates':encode(self.coordinates),
            'program':encode(pa),'snapshot':encode(self._snapshot),'interfaces':encode(iface),
            'source_shard_indices':list(selected),'selected_operation_rows':len(self._row_signatures),
            'shared_interfaces':len(layouts),'whole_model_established':False}
        self._catalog=self._write(root/'manifest.json',canonical(manifest),manifest['schema'])
        return self._catalog
    def _construct(self,rows,shard_no):
        activations=[];segments=[];visits=[];operations=[];values=[];uses=[];denotations=[];sources=[]
        ref=self.index.shards[shard_no]
        for row in rows:
            instance,definition,native,definition_loc=self._source(row)
            _need(row.source_ordinal in self._row_signatures,'operator is outside the prepared catalog')
            layout=self._layouts[self._row_signatures[row.source_ordinal]]
            key=sha256(canonical({'eto':encode(self.eto),'instance':encode(instance.id),'profile':PROFILE})).hexdigest()
            prefix='native-declaration:'+key
            aid,sid,entry,invoke=RegionActivationID(prefix),ExecutionSegmentID(prefix+':segment'),BlockVisitID(prefix+':entry'),OperationOccurrenceID(prefix+':invoke')
            fact=ProviderFactReference(self.eto,'#/nodes/'+str(row.source_ordinal));point=EvidencePoint(self.run.id,self.process.id,fact)
            activations.append(RegionActivation(aid,layout['region'],self.process.id,point))
            segments.append(ExecutionSegment(sid,aid,UnresolvedHostThread('original ETO actor is not an established host-thread mapping',point),InitialEntry(point)))
            visits.append(BlockVisit(entry,sid,layout['entry']));operations.append(OperationOccurrence(invoke,entry,layout['invoke']))
            inputs=[]
            source_ports=[p for p in row.ports if p.direction=='input']
            for j,(value,use)in enumerate(zip(layout['before'],layout['input_uses'])):
                actual=ValueOccurrenceID(prefix+':input:'+str(j));values.append(ValueOccurrence(actual,value.id,entry));uses.append(UseOccurrence(invoke,use.id,actual))
                if j<len(source_ports):
                    basis=NativeInputRef(layout['boundary'].id,entry,j);inputs.append(basis)
                    p=source_ports[j];original=ProviderFactReference(self.eto,fact.locator+p.source_locator)
                    denotations.append(ValueDenotation(DenotationID(prefix+':input:'+str(j)),actual,
                        Unresolved('native port declaration does not establish Python object or payload identity',point),basis,original))
            p=ProviderArtifact(str(self.root/ref.path),ref.stored_sha256,ref.stored_bytes,'scar.native-boxed-port-shard')
            position=next(i for i,r in enumerate(self._ports(shard_no).rows)if r.source_ordinal==row.source_ordinal)
            loc=FragmentLocator(p,ref.decoded_sha256,ref.decoded_bytes,Encoding.GZIP_JSON,None,
                '#/value/rows/'+str(position),ProviderFactReference(self.index_artifact,'#/value/shards/'+str(shard_no)))
            output=tuple(ProviderFactReference(self.eto,fact.locator+p.source_locator)for p in row.ports if p.direction=='output')
            sources.append((native,definition_loc,loc,invoke,layout['boundary'].id,tuple(inputs),output,
                Unresolved('declaration-only source does not select NORMAL or RAISE',point)))
        model=ExecutionModel(self._snapshot,runs=(self.run,),processes=(self.process,),activations=tuple(activations),
            segments=tuple(segments),visits=tuple(visits),operations=tuple(operations),values=tuple(values),uses=tuple(uses),denotations=tuple(denotations))
        return model,sources

    def _fragment(self,rows,root,shard_no):
        model,sources=self._construct(rows,shard_no)
        report=validate(model,self._program,prepared_snapshot=self._prepared,
            artifact_bytes={self._interface_artifact.sha256:self._interface_bytes})
        _need(report.valid,'native declaration execution contradicts core: '+str(report.issues[:5]))
        ea=self._write(root/'execution.json',execution_dumps(model).encode(),'scar.execution-model')
        links=tuple(NativeDeclarationOccurrence(n,d,p,ea,self._snapshot,o,b,i,out,c)for n,d,p,o,b,i,out,c in sources)
        doc={'schema':'scar.native-declaration-fragment','schema_version':1,'profile':PROFILE,
            'catalog':encode(self._catalog),'execution':encode(ea),'occurrences':encode(links),
            'validation':{'valid':report.valid,'issues':encode(report.issues),'gaps':encode(report.gaps)},
            'operation_rows':len(rows),'input_ports':sum(len(l.inputs)for l in links),
            'conditional_output_ports':sum(len(l.output_sources)for l in links),
            'completion_selected_count':0,'whole_model_established':False}
        return self._write(root/'manifest.json',canonical(doc),doc['schema'])
    def publish_shard(self,shard_no,out,source_ordinals=None):
        self._check();root=Path(out).resolve();_need(not root.exists(),'fresh native shard output required')
        if self._catalog is None:self.prepare_catalog(root.parent/'catalog')
        shard=self._ports(shard_no);wanted=None if source_ordinals is None else set(source_ordinals)
        rows=[r for r in shard.rows if wanted is None or r.source_ordinal in wanted]
        _need(wanted is None or wanted=={r.source_ordinal for r in rows},'selected source ordinal absent from original operator shard')
        fragments=[]
        for start in range(0,len(rows),self.budget.max_operations_per_fragment):
            fragments.append(self._fragment(rows[start:start+self.budget.max_operations_per_fragment],root/f'{len(fragments):06d}',shard_no))
        ref=self.index.shards[shard_no]
        doc={'schema':'scar.native-declaration-shard','schema_version':1,'profile':PROFILE,
            'index':encode(self.index_artifact),'bundle':encode(self.bundle),'coordinates':encode(self.coordinates),'catalog':encode(self._catalog),
            'source_shard_index':shard_no,'first_source_ordinal':ref.first_source_ordinal,'stop_source_ordinal':ref.stop_source_ordinal,
            'scope_operation_rows':self.index.operation_rows,'declared_operation_rows':ref.operation_rows,
            'selected_operation_rows':len(rows),'processed_operation_rows':len(rows),'canonical_operation_occurrences':len(rows),
            'canonical_input_ports':sum(p.direction=='input'for r in rows for p in r.ports),
            'conditional_output_ports':sum(p.direction=='output'for r in rows for p in r.ports),
            'completion_selected_count':0,'fragments':encode(tuple(fragments)),'whole_model_established':False,
            'status':'CANONICAL_INPUTS_WITH_UNSELECTED_COMPLETION',
            'input_measurements':self.meter.finish(),'output_bytes_before_manifest':self._output}
        return self._write(root/'manifest.json',canonical(doc),doc['schema'])


@dataclass(frozen=True,slots=True)
class NativeDeclarationView:
    occurrences:tuple[NativeDeclarationOccurrence,...]
    program:object
    execution:ExecutionModel
    validation:object
    measurements:dict


def read_native_declaration_fragment(artifact:ProviderArtifact,*,budget=None):
    """Ordinary exact-source readback; stored validation booleans grant nothing.

    Whole core is checked, but catalog source correspondence is rechecked only
    for this fragment's exact original rows, not all unselected native shards.
    """
    b=budget or NativeDeclarationBudget();b.__post_init__();meter=_Meter(b.max_input_bytes,b.max_seconds)
    def read(a,maximum=64_000_000):
        raw=meter.artifact(a,maximum);meter.charge(decoded=len(raw));return strict_json(raw.decode())
    _need(type(artifact)is ProviderArtifact and artifact.schema=='scar.native-declaration-fragment','typed native fragment required')
    doc=read(artifact)
    _need(set(doc)=={'schema','schema_version','profile','catalog','execution','occurrences','validation',
        'operation_rows','input_ports','conditional_output_ports','completion_selected_count','whole_model_established'}
        and doc['schema']==artifact.schema and doc['schema_version']==1 and doc['profile']==PROFILE,
        'unsupported native declaration fragment')
    cat_art=decode(ProviderArtifact,doc['catalog']);cat=read(cat_art)
    _need(cat['schema']=='scar.native-declaration-catalog'and cat['schema_version']==1 and cat['profile']==PROFILE,'unsupported native catalog')
    with NativeDeclarationSession(decode(ProviderArtifact,cat['index']),decode(ProviderArtifact,cat['bundle']),
                                  decode(ProviderArtifact,cat['coordinates']),budget=b)as session:
        session.meter.charge(stored=meter.stored,decoded=meter.decoded)
        pa=decode(ProviderArtifact,cat['program']);raw=session.meter.artifact(pa,64_000_000);session.meter.charge(decoded=len(raw))
        program=program_loads(raw.decode());session._prepared=prepare_program_snapshot(program)
        snapshot=decode(ProgramSnapshot,cat['snapshot'])
        _need(snapshot.artifact==pa and session._prepared.sha256==pa.sha256,'catalog snapshot differs')
        iface_art=decode(ProviderArtifact,cat['interfaces']);raw=session.meter.artifact(iface_art,64_000_000);session.meter.charge(decoded=len(raw))
        interface_doc=strict_json(raw.decode());_need(interface_doc['profile']==PROFILE,'catalog interface profile differs')
        session._catalog=cat_art;session._snapshot=snapshot;session._program=program;session._interface_artifact=iface_art;session._interface_bytes=raw
        session._layouts={}
        execution_art=decode(ProviderArtifact,doc['execution']);raw=session.meter.artifact(execution_art,64_000_000);session.meter.charge(decoded=len(raw))
        execution=execution_loads(raw.decode());_need(execution.snapshot==snapshot,'native fragment and catalog snapshots differ')
        links=tuple(decode(NativeDeclarationOccurrence,v)for v in doc['occurrences'])
        _need(len(links)==doc['operation_rows']and len({v.invocation for v in links})==len(links),'native fragment occurrence denominator differs')
        rows=[];shard_no=None
        for link in links:
            _need(link.execution==execution_art and link.snapshot==snapshot,'native occurrence belongs to another fragment')
            original=link.native
            suffix=link.ports.declaration.locator.rsplit('/',1)[-1]
            _need(suffix.isdecimal(),'native port declaration shard selector differs')
            no=int(suffix);_need(shard_no in(None,no),'fragment combines source shards');shard_no=no
            candidates=[r for r in session._ports(no).rows if r.instance==original.instance]
            _need(len(candidates)==1,'original native port row missing or ambiguous');row=candidates[0]
            inst,definition,native,definition_loc=session._source(row)
            _need(native==original and definition_loc==link.definition,'original native/definition locator differs')
            interface=session._interface(row,definition);sig=interface['signature_id']
            _need(interface_doc['interfaces'].get(sig)==interface['signature'],'interface differs from original observed ports/schema')
            source={'reference_profile':PROFILE_V2,'native_scope':inst.id.value.rsplit(':eto:',1)[0],
                'run':session.run.id.value,'pid':session.process.pid,'artifacts':{'eto':encode(session.eto)}}
            scope=ProviderRunScope(session.run.id.value,session.process.pid,
                f'published native source ordinals [{session.index.first_source_ordinal},{session.index.stop_source_ordinal}); completion unselected',
                'retained ETO source records; no inferred execution total order')
            expected,layouts=_build_program([interface],source,iface_art,execution_scope=scope,
                interface_description='observed native boxed interfaces with optional pinned schema declarations')
            expected_ops={r.id:r for r in expected.operations};actual_ops={r.id:r for r in program.operations}
            expected_values={r.id:r for r in expected.values};actual_values={r.id:r for r in program.values}
            actual_regions={r.id:r for r in program.regions};actual_bounds={r.id:r for r in program.native_boundaries}
            _need(all(actual_ops.get(k)==v for k,v in expected_ops.items())
                and all(actual_values.get(k)==v for k,v in expected_values.items())
                and all(actual_regions.get(v.id)==v for v in expected.regions)
                and all(actual_bounds.get(v.id)==v for v in expected.native_boundaries),
                'selected canonical core does not match original native ABI')
            session._layouts.update(layouts);session._row_signatures[row.source_ordinal]=sig;rows.append(row)
        _need(shard_no is not None,'native fragment has no declared operators')
        expected_model,sources=session._construct(rows,shard_no)
        _need(execution==expected_model,'native occurrences/inputs/world or unselected completion differ')
        expected_links=tuple(NativeDeclarationOccurrence(n,d,p,execution_art,snapshot,o,bound,i,out,c)
            for n,d,p,o,bound,i,out,c in sources)
        _need(links==expected_links,'native source-to-core association differs')
        _need(doc['input_ports']==sum(len(l.inputs)for l in links)
            and doc['conditional_output_ports']==sum(len(l.output_sources)for l in links)
            and doc['completion_selected_count']==0 and doc['whole_model_established']is False,
            'native fragment scope/completion claims differ')
        validation=validate(execution,program,prepared_snapshot=session._prepared,
            artifact_bytes={iface_art.sha256:session._interface_bytes})
        _need(validation.valid,'native declaration normal readback failed: '+str(validation.issues[:5]))
        measurement=session.meter.finish();meter.finish()
        return NativeDeclarationView(links,program,execution,validation,measurement)

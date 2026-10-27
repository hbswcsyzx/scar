"""Original ETO containment -> retained dispatch/Python context, not direct calls.

One session reads the existing parent inventory, dispatch bridge and call trace.
Its private maps contain source fields/locators only. No graph, invocation,
CodeID, source version or proof owner is restored or minted by this consumer.
"""
from collections import OrderedDict
from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
import gzip, io, re, time

from scar.analysis.call_trace_reader import scan_call_trace
from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget,NativeDeclarationView,read_native_declaration_fragment
from scar.analysis.native_declaration_resources import _Records
from scar.analysis.tensor_storage_query import _Meter,_need
from scar.ir.execution.coordinates import ExecutionRun
from scar.ir.execution.fragment_relations import Encoding,FragmentLocator,EvidenceInstanceRef,RuntimeScope,InvocationRef
from scar.ir.execution.ids import ProcessInstanceID
from scar.ir.execution.native_declarations import NativeDeclarationOccurrence
from scar.ir.program.call_edges import CallEdgeBudget,CodeCapture,FrameEntry,FrameExit,InvocationKey
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import decode,encode,loads
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.ids import OperationInstanceID
from scar.trace.native_capture_batch import _JSONStream
from scar.trace.native_import import _REVISION


def _same(a,b):return (a.uri,a.sha256,a.size_bytes)==(b.uri,b.sha256,b.size_bytes)


@dataclass(frozen=True,slots=True)
class NativePythonBudget:
    max_input_bytes:int=2_000_000_000
    max_seconds:int=600
    max_nodes:int=500_000
    max_contexts:int=100_000
    max_parent_depth:int=256
    max_connections:int=4096
    def __post_init__(self):
        _need(all(type(getattr(self,f.name))is int and getattr(self,f.name)>0 for f in fields(self)),
              'positive native/Python budgets required')


@dataclass(frozen=True,slots=True)
class NativePythonContext:
    native:NativeDeclarationOccurrence
    control_path:tuple[EvidenceInstanceRef,...]
    parent_sources:tuple[FragmentLocator,...]
    dispatch_context:FragmentLocator
    dispatch_observation:ProviderFactReference
    invocation:InvocationRef|None
    captured_code:CodeCapture|None
    entry:FrameEntry|None
    completion:FrameExit|None
    relationship:str='ENCLOSING_DISPATCH_RETAINED_SOURCE_CONTEXT'
    source_status:str='CAPTURED_CODE_DESCRIPTOR_ONLY_SOURCE_TEXT_AND_COMPILER_MATCH_OPEN'


class _Sink:
    def __init__(self,wanted):self.wanted=wanted;self.entries={};self.exits={}
    def entry(self,value):
        if value.invocation in self.wanted:self.entries[value.invocation]=value
    def exit(self,value):
        if value.invocation in self.wanted:self.exits[value.invocation]=value
    def abort(self):self.entries.clear();self.exits.clear()


class NativeDeclarationPythonSession:
    def __init__(self,batch_report:ProviderArtifact,capture_model:ProviderArtifact,
                 coordinates:ProviderArtifact,*,budget=None):
        self.budget=budget or NativePythonBudget();self.budget.__post_init__()
        self.meter=_Meter(self.budget.max_input_bytes,self.budget.max_seconds)
        self.closed=False;self._table_cache=OrderedDict()
        self.batch_artifact=batch_report;batch=self._doc(batch_report)
        self.model_artifact=capture_model;model=self._doc(capture_model)
        self.coordinates=coordinates;coord=self._doc(coordinates)
        self.run=decode(ExecutionRun,coord['run']);process=decode(ProcessInstanceID,coord['target_process'])
        self.scope=RuntimeScope(self.run.id,process,coordinates)
        self.pid=next(p['pid']for p in coord['processes']if p['id']==encode(process))
        _need(batch['schema']=='scar.native-capture-batch' and batch['schema_version']==2
              and batch['run']==self.run.id.value and model['run']==coord['run'],
              'batch/model/coordinates cross Run or contract')
        self.coord=coord;self.bundle=ProviderArtifact(batch['source_manifest']['path'],
            batch['source_manifest']['physical_sha256'],batch['source_manifest']['physical_bytes'],'scar.partitioned-ir-bundle')
        self.records=_Records(self.bundle,self.meter)
        self.eto=next(decode(ProviderArtifact,m['artifact'])for m in coord['membership']
                      if m['artifact']['schema']=='pytorch.execution-trace.v1')
        _need(any(_same(decode(ProviderArtifact,m['artifact']),self.eto) and m['process']==encode(process)
                  for m in coord['membership']),'ETO process membership differs')
        _need(model['native']['pid']==self.pid and model['native']['provider_revision']==_REVISION,
              'native model provider/process differs')
        self.native_scope=model['native']['scope']
        self.parent_artifact=decode(ProviderArtifact,batch['native_parent_inventory'])
        self.parents_document=self._doc(self.parent_artifact)
        table=self.parents_document
        _need(table['schema']=='scar.native-capture-table-chunks' and table['schema_version']==1
              and table['row_schema_version']==2 and table['role']=='native-parent-closure'
              and table['run']==self.run.id.value and table['process_id']==self.pid
              and table['source_artifact']==encode(self.eto),'parent inventory scope/source differs')
        self.parents={};visited=0
        for no,d in enumerate(table['chunks']):
            lines=self._table_chunk(no)
            for local,raw in enumerate(lines):
                row=loads(raw.decode());ordinal=d['first_row_ordinal']+local
                _need(row['original_ordinal']==ordinal and row['source']=={'artifact':encode(self.eto),'locator':f'#/nodes/{ordinal}'}
                      and row['parent_edge_source']=={'artifact':encode(self.eto),'locator':f'#/nodes/{ordinal}/ctrl_deps'}
                      and row['actor']['process_id']==self.pid,'parent inventory source/ordinal differs')
                node,parent=row['node_id'],row['original_parent']
                _need(type(node)is int and type(parent)is int and node not in self.parents,'parent identities missing/duplicate')
                self.parents[node]=(parent,ordinal);visited+=1
                _need(visited<=self.budget.max_nodes,'parent index node budget exceeded')
        _need(visited==table['rows']==batch['native_parent_nodes'],'parent denominator differs')
        self.parent_denominator=visited
        outputs=[(i,r)for i,r in enumerate(model['outputs'])if r['path'].endswith('/native/dispatch-bridge.json.gz')]
        _need(len(outputs)==1,'no unique declared dispatch bridge')
        output_no,receipt=outputs[0]
        self.bridge=ProviderArtifact(receipt['path'],receipt['stored_sha256'],receipt['stored_bytes'],'scar.dispatch-observation-import')
        self.bridge_declaration=ProviderFactReference(capture_model,f'#/outputs/{output_no}')
        self.spans={};header,decoded_sha,decoded_bytes=self._bridge()
        _need(header.get('schema')=='scar.dispatch-observation-import' and header.get('schema_version')==1
              and header.get('profile')=='scar.dispatch-marker-collector-v1'
              and header.get('production_collector')is True and header.get('capture_membership_verified')is True
              and header.get('direct_python_operator_correspondence_established')is False
              and header['dispatches']==len(self.spans)==batch['declared_dispatch_attempts'],
              'dispatch bridge profile/denominator differs')
        self.bridge_decoded_sha,self.bridge_decoded_bytes=decoded_sha,decoded_bytes
        self.bridge_artifacts={k:decode(ProviderArtifact,v)for k,v in header['artifacts'].items()}
        for a in self.bridge_artifacts.values():self._member(a)
        wanted=set()
        for _,row in self.spans.values():
            context=row['retained_ancestor']
            if context is not None:
                wanted.add(InvocationKey(self.pid,row['python_ident'],context['invocation']))
        _need(len(wanted)<=self.budget.max_contexts,'Python context budget exceeded')
        # Validate the source callback point which the historical bridge does
        # not retain as a scalar. One complete original JSONL read, never per op.
        self.points=self._dispatch_points()
        call_meta=self._member(self.bridge_artifacts['call_meta'])
        meta=self._local_doc(call_meta)
        _need(meta['process_id']==self.pid and meta['schema']=='scar.call-edge-trace','call metadata process differs')
        sink=_Sink(wanted)
        call_files=[self._member(self.bridge_artifacts[k])for k in ('codes','calls','call_meta')]
        # Authenticate physical retention before the ordinary decoder opens it.
        physical_total=0
        for m in call_files:
            p=Path(m['local_path']);physical_total+=p.stat().st_size
            self._verify_physical(m)
        trace=Path(call_meta['local_path']).parent
        existing={p.name for p in trace.iterdir()if re.fullmatch(r'call-(?:codes|events|meta)\.[1-9][0-9]*\.(?:jsonl|json)(?:\.gz)?',p.name)}
        _need(existing=={Path(m['local_path']).name for m in call_files},'call directory has undeclared process/family')
        scan=scan_call_trace(trace,meta['project_root'],CallEdgeBudget(max_raw_bytes=240_000_000,
            max_lines=210_000,max_processes=1,max_codes=4096,max_events=210_000,max_references=8_000_000),sink=sink)
        self.meter.charge(stored=physical_total,decoded=sum(f.raw_bytes for f in scan.files))
        _need(not scan.issues,'normal call trace reports collection issues')
        for f in scan.files:
            a=next(self.bridge_artifacts[k]for k in ('codes','calls','call_meta')if self.bridge_artifacts[k].uri==f.path)
            _need((f.raw_sha256,f.raw_bytes)==(a.sha256,a.size_bytes),'normal call scan differs from exact bridge family')
        self.entries,self.exits=sink.entries,sink.exits
        self.codes={c.code.key:c for c in scan.captures};self.call_scan=scan
        self.initial_measurements=self.meter.finish()

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
    def close(self):
        if not self.closed:
            try:self.meter.finish()
            finally:self.closed=True;self.parents.clear();self.spans.clear();self.entries.clear();self.exits.clear();self.points.clear();self._table_cache.clear()
    def _check(self):_need(not self.closed,'native/Python session is closed');self.meter.charge()
    def _doc(self,a):
        raw=self.meter.artifact(a,16_000_000);self.meter.charge(decoded=len(raw));return loads(raw.decode())
    def _member(self,a):
        matches=[m for m in self.coord['membership']if _same(decode(ProviderArtifact,m['artifact']),a)]
        _need(len(matches)==1 and matches[0]['process']==encode(self.scope.process),'artifact lacks exact same-Run/process membership')
        return matches[0]
    def _verify_physical(self,m):
        p=Path(m['local_path']);a=decode(ProviderArtifact,m['artifact'])
        _need(p.is_absolute() and not p.is_symlink() and p.resolve(strict=True)==p,'unsafe retained source mapping')
        if p.suffix=='.gz':
            archive=self._archive()
            entry=next((r for r in archive['files']if r['actual_path']==str(p) and r['logical_path']==a.uri),None)
            _need(entry is not None and (entry['raw_sha256'],entry['raw_bytes'])==(a.sha256,a.size_bytes),'retained source mapping differs')
            self.meter.artifact(ProviderArtifact(str(p),entry['gzip_sha256'],entry['compressed_bytes'],'gzip.retained-call-source'),32_000_000)
        else:self.meter.artifact(a,16_000_000)
    def _archive(self):
        if not hasattr(self,'_archive_document'):
            p=Path(self.coord['local_root'])/'archive-index.json';raw=p.read_bytes()
            _need(sha256(raw).hexdigest()==self.coord['seed']['archive_sha256'],'archive seed differs')
            a=ProviderArtifact(str(p),sha256(raw).hexdigest(),len(raw),'scar.capture-archive-index')
            self.meter.charge(stored=len(raw));self._archive_document=self._doc(a)
        return self._archive_document
    def _raw_lines(self,a):
        m=self._member(a);self._verify_physical(m);p=Path(m['local_path']);digest=sha256();size=lines=0
        opener=gzip.open if p.suffix=='.gz'else open
        with opener(p,'rb')as f:
            for raw in f:
                _need(raw.endswith(b'\n') and len(raw)<=4_000_000,'retained source record bound/EOF differs')
                size+=len(raw);lines+=1;digest.update(raw);self.meter.charge(decoded=len(raw))
                yield lines,raw
        self.meter.charge(stored=p.stat().st_size)
        _need((digest.hexdigest(),size)==(a.sha256,a.size_bytes),'complete retained source raw SHA/bytes differs')
    def _local_doc(self,m):
        a=decode(ProviderArtifact,m['artifact']);raw=self.meter.artifact(a,4_000_000);self.meter.charge(decoded=len(raw));return loads(raw.decode())
    def _table_chunk(self,no):
        if no not in self._table_cache:
            d=self.parents_document['chunks'][no];a=decode(ProviderArtifact,d['artifact'])
            raw=self.meter.artifact(a,8_000_000);self.meter.charge(decoded=len(raw));lines=tuple(raw.splitlines())
            _need(raw.endswith(b'\n') and len(lines)==d['rows'],'parent inventory chunk EOF/count differs')
            self._table_cache[no]=lines
            if len(self._table_cache)>3:self._table_cache.popitem(last=False)
        self._table_cache.move_to_end(no);return self._table_cache[no]
    def _bridge(self):
        physical=self.meter.artifact(self.bridge,16_000_000);stream=gzip.GzipFile(fileobj=io.BytesIO(physical));digest=sha256();size=0
        session=self
        class Reader:
            def read(self,n):
                nonlocal size
                raw=stream.read(n);size+=len(raw);digest.update(raw);session.meter.charge(decoded=len(raw));return raw
        parser=_JSONStream(Reader(),4_000_000);header={};seen=set();parser.take('{')
        try:
            while parser.peek()!='}':
                key=parser.value();_need(type(key)is str and key not in seen,'duplicate bridge key');seen.add(key);parser.take(':')
                if key in ('observations','paths'):
                    parser.take('[');ordinal=0
                    while parser.peek()!=']':
                        row=parser.value()
                        if key=='observations' and row['phase']=='span':
                            node=row['marker_instance'];_need(node not in self.spans,'duplicate span marker')
                            self.spans[node]=(ordinal,{k:row[k]for k in ('sequence','phase','marker_instance','source_line','retained_ancestor','python_ident','native_tid','native_tid_verified')})
                        ordinal+=1
                        if parser.peek()!=',':break
                        parser.take(',')
                    parser.take(']');header[key+'_count']=ordinal
                else:header[key]=parser.value()
                if parser.peek()!=',':break
                parser.take(',')
            parser.take('}');_need(parser.peek()=='','bridge trailing source bytes')
        finally:stream.close()
        return header,digest.hexdigest(),size
    def _dispatch_points(self):
        a=self.bridge_artifacts['observations'];wanted={row['source_line']:row for _,row in self.spans.values()};result={};count=0
        for number,raw in self._raw_lines(a):
            count+=1
            if number not in wanted:continue
            row=loads(raw.decode());s=wanted[number];o=row['observation']
            _need(row['kind']=='DISPATCH_BEGIN' and row['sequence']==s['sequence'] and row['process_id']==self.pid
                  and o['context']==s['retained_ancestor'] and o['python_ident']==s['python_ident']
                  and o['native_tid']==s['native_tid'],'dispatch bridge differs from original callback row')
            result[number]=(o['call_event_index'],sha256(raw).hexdigest())
        meta=self._local_doc(self._member(self.bridge_artifacts['metadata']))
        _need(count==meta['events']==meta['file']['lines'] and len(result)==len(wanted)
              and meta['dropped_events']==0 and meta['errors']==[] and meta['io_failed']is False,
              'dispatch source/metadata denominator or collection differs')
        self.nonce=meta['nonce'];return result
    def _parent(self,node):
        _need(node in self.parents,'original ETO parent record unavailable')
        parent,ordinal=self.parents[node]
        no=next(i for i,d in enumerate(self.parents_document['chunks'])if d['first_row_ordinal']<=ordinal<=d['last_row_ordinal'])
        d=self.parents_document['chunks'][no];line=ordinal-d['first_row_ordinal']+1
        row=loads(self._table_chunk(no)[line-1].decode())
        _need((row['node_id'],row['original_parent'],row['original_ordinal'])==(node,parent,ordinal),'parent locator changed original fields')
        original,loc=self.records.row('evidence','instances',ordinal);instance=decode(OperationInstance,original['record']);meta=instance.metadata
        _need(instance.id.value==self.native_scope+':eto:'+str(node) and instance.process_id==self.pid
              and meta.get('provider')=='ETO' and meta.get('node_id')==node and meta.get('ctrl_deps')==parent
              and meta.get('parent_basis')=='ETO ctrl_deps collector stack only'
              and meta.get('raw_reference')=='sha256:'+self.eto.sha256+f'#/nodes/{ordinal}'
              and row['actor']['record_function_thread_token']==meta.get('eto_tid',meta.get('raw_tid')),
              'original ETO parent/source/collector-thread fields differ')
        if parent!=node:_need(instance.parent is not None and instance.parent.value==self.native_scope+':eto:'+str(parent),'original ETO parent identity differs')
        a=decode(ProviderArtifact,d['artifact']);tableloc=FragmentLocator(a,a.sha256,a.size_bytes,Encoding.JSONL,line,'#',
            ProviderFactReference(self.parent_artifact,f'#/chunks/{no}'))
        return row,instance,EvidenceInstanceRef(loc,instance.id),tableloc
    def query(self,fragment:ProviderArtifact,*,source_instances=None):
        self._check();view=read_native_declaration_fragment(fragment,budget=NativeDeclarationBudget(
            max_input_bytes=self.budget.max_input_bytes-self.meter.stored-self.meter.decoded,max_seconds=self.budget.max_seconds))
        self.meter.charge(stored=view.measurements['stored_bytes'],decoded=view.measurements['decoded_bytes'])
        return self.query_view(view,source_instances=source_instances)
    def query_view(self,view:NativeDeclarationView,*,source_instances=None):
        self._check();_need(type(view)is NativeDeclarationView,'unchanged live normal native view required')
        if source_instances is not None:_need(type(source_instances)is tuple and all(type(n)is OperationInstanceID for n in source_instances),'typed source instance selectors required')
        before=(self.meter.stored,self.meter.decoded,time.monotonic());connections=[];gaps=[]
        _need(any(r.id==self.scope.run for r in view.execution.runs) and any(p.id==self.scope.process for p in view.execution.processes),'native view crosses Run/process')
        links=view.occurrences if source_instances is None else tuple(n for n in view.occurrences if n.native.instance in source_instances)
        _need(source_instances is None or len(links)==len(set(source_instances)),'selected native absent/ambiguous')
        for native in links:
            _need(native.native.locator.declaration.artifact==self.bundle,'native changes original bundle namespace')
            node_text=native.native.instance.value.removeprefix(self.native_scope+':eto:')
            _need(node_text.isdecimal(),'native is outside original ETO namespace');node=int(node_text)
            path=[];sources=[];seen=set();thread=None;selected=None
            for _ in range(self.budget.max_parent_depth):
                _need(node not in seen,'cyclic original ETO parent path');seen.add(node)
                # The process root is a structural sentinel, not another
                # thread's enclosing control scope or dispatch context.
                if node==1:break
                if node not in self.parents:break
                row,instance,reference,tableloc=self._parent(node)
                if not path:_need(reference==native.native,'canonical native original locator differs')
                token=row['actor']['record_function_thread_token']
                if thread is None:thread=token
                _need(token==thread,'ETO parent path changes collector thread')
                path.append(reference);sources.append(tableloc)
                span=self.spans.get(reference.instance.wire)
                if span is not None:selected=(span,row,instance);break
                if row['original_parent']==node:break
                node=row['original_parent']
            if selected is None:
                gaps.append({'native':native,'kind':'NEAREST_DISPATCH_SPAN_UNAVAILABLE','visited_parent_records':len(path)});continue
            (ordinal,span),marker,marker_instance=selected
            _need(marker['actor']['name']==f"scar-dispatch:{self.nonce}:{self.pid}:{span['sequence']}:span",'nearest original marker/profile differs')
            if span['native_tid_verified']:
                _need(marker_instance.metadata.get('raw_pid')==self.pid and marker_instance.metadata.get('raw_tid')==span['native_tid'],'original marker native-thread correspondence differs')
            invocation=capture=entry=completion=None;context=span['retained_ancestor']
            if context is not None:
                key=InvocationKey(self.pid,span['python_ident'],context['invocation']);entry=self.entries.get(key);completion=self.exits.get(key)
                _need(entry is not None and completion is not None and entry.code==context['code'],'retained source context missing/contradictory in normal call trace')
                capture=self.codes[entry.code];point,_=self.points[span['source_line']]
                _need(context['kind']=='retained ancestor context, not a proven direct caller'
                      and context['source_file']==capture.code.filename and entry.anchor.index<=point<completion.anchor.index,
                      'retained context code/source/active interval differs')
                a=self.bridge_artifacts['calls'];invocation=InvocationRef(self.scope,key,ProviderFactReference(a,f'#/lines/{entry.anchor.line_number}'))
            else:gaps.append({'native':native,'kind':'NEAREST_SPAN_RETAINED_ANCESTOR_MISSING'})
            contextloc=FragmentLocator(self.bridge,self.bridge_decoded_sha,self.bridge_decoded_bytes,Encoding.GZIP_JSON,None,
                f'#/observations/{ordinal}',self.bridge_declaration)
            connections.append(NativePythonContext(native,tuple(path),tuple(sources),contextloc,
                ProviderFactReference(self.bridge_artifacts['observations'],f"#/lines/{span['source_line']}"),
                invocation,capture,entry,completion))
            _need(len(connections)<=self.budget.max_connections,'native/Python connection bound exceeded')
        m=self.meter.finish();stored,decoded=self.meter.stored-before[0],self.meter.decoded-before[1]
        return {'connections':tuple(connections),'gaps':tuple(gaps),'selected_native_occurrences':len(links),
            'parent_inventory_denominator':self.parent_denominator,'dispatch_span_denominator':len(self.spans),
            'call_invocation_denominator':sum(d['invocations']for d in self.call_scan.metadata),
            'captured_code_denominator':len(self.codes),'measurements':m,
            'query_measurements':{'stored_bytes':stored,'decoded_bytes':decoded,'total_bytes':stored+decoded,'elapsed_seconds':time.monotonic()-before[2]},
            'relationship':'ENCLOSING_DISPATCH_RETAINED_SOURCE_CONTEXT','direct_call_established':False,
            'source_text_compiler_match_established':False,'content_state_ready_established':False}

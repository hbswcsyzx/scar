"""Opt-in registration/source facts for one live collector issuer.

This sidecar grants no historical Run, contents, event-loss or mutation closure.
Compiled source matches an observed live CodeType; it is not a loader-read log.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import types
import uuid
import weakref

PROFILE = 'SCAR_COLLECTOR_EXECUTION_WITNESS_V1'
PROCESS_PROFILE = 'SCAR_COLLECTOR_EXECUTION_WITNESS_V2'
SCHEMA = 'scar.collector-execution-witness'


def _wire(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def _artifact(path):
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import encode
    raw=path.read_bytes()
    return encode(ProviderArtifact(str(path),hashlib.sha256(raw).hexdigest(),len(raw),json.loads(raw).get('schema','application/json')))


def _birth():
    try:
        text=Path('/proc/self/stat').read_text()
        return {'status':'OBSERVED','proc_start_ticks':int(text[text.rfind(')')+2:].split()[19]),
                'source':'/proc/self/stat field22 at registration'}
    except (OSError,ValueError,IndexError):
        return {'status':'UNAVAILABLE','proc_start_ticks':None,'source':None}


class CollectorExecutionWitness:
    def __init__(self,recorder):
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        if recorder.pid!=os.getpid() or recorder.closed:
            raise ValueError('collector issuer must be live in the installing process')
        self.recorder=recorder
        self.issuer={'uuid':uuid.uuid4().hex,'generation':1,'process_id':recorder.pid}
        self.root=recorder.out/('collector-witness.'+str(recorder.pid)+'.'+self.issuer['uuid'])
        self.root.mkdir(mode=0o700)
        self.path=self.root/'manifest.json'
        self.profile=PROCESS_PROFILE if os.environ.get('SCAR_PROCESS_IMAGE_RECEIPTS')=='1' else PROFILE
        self.process_images=None
        self.resource_topology=None;self._topology_functions=[]
        if os.environ.get('SCAR_RESOURCE_TOPOLOGY')=='1' and self.profile!=PROCESS_PROFILE:
            raise ValueError('resource topology requires the explicit process-image witness profile')
        self.registry={};self.records=[];self.errors=[];self.closed=False;self.released=False
        self._checking=False
        self._hook_codes={};self._executed=set();self._ready=False
        self.store=CodeWitnessStore(self.root/'code-witnesses',create=True,compile_missing=True,
            budget=CodeWitnessBudget(max_compile_keys=12,max_source_files=12,max_source_bytes=2000000,
                max_archive_bytes=32000000,max_manifest_bytes=1000000),
            producer={'profile':self.profile,'issuer':self.issuer})
        self.context={'process_id':os.getpid(),'parent_process_id':os.getppid(),
            'python_ident':threading.get_ident(),'native_tid':threading.get_native_id(),
            'cwd':os.getcwd(),'argv':list(sys.argv),'python_executable':sys.executable,
            'python_version':sys.version,'optimize':sys.flags.optimize,'birth':_birth(),'run':None,
            'run_binding':'UNBOUND_UNTIL_EXPLICIT_POSTCAPTURE_BINDER'}
        self._record('ISSUER_CREATED')
        recorder.observer_files.add(__file__)
        if self.profile==PROCESS_PROFILE:
            from scar.trace import process_image_receipts as image_module
            recorder.observer_files.add(image_module.__file__)
            self.process_images=image_module.ProcessImageReceipts(self.root/'process-images',self.issuer)
            methods=('snapshot','_backing','_backing_impl','_write','close')
            functions=('incarnation','incarnation_key','_mapping','_lines','_stamp','_wire')
            self._image_functions=[];proofs=[]
            for owner,names in ((self.process_images,methods),(image_module,functions)):
                for name in names:
                    function=getattr(owner,name);function=function.__func__ if type(function)is types.MethodType else function
                    self._image_functions.append((owner,name,function,function.__code__))
                    proofs.append({'attribute':name,**self._code(function.__code__)})
            self._record('PROCESS_IMAGE_HELPER_REGISTERED',callbacks=proofs)
            self.image_boundary('REGISTRATION')
            if os.environ.get('SCAR_RESOURCE_TOPOLOGY')=='1':
                from scar.trace import resource_topology as topology_module
                recorder.observer_files.add(topology_module.__file__)
                proofs=[]
                owners=((topology_module,('capture_resource_topology','_derive','_counts','_text','_names','_mounts','_wire','_json','_need')),
                        (topology_module._Capture,('__init__','_allowed','_fact','_read','_dir','_link')))
                for owner,names in owners:
                    for name in names:
                        function=getattr(owner,name)
                        self._topology_functions.append((owner,name,function,function.__code__))
                        proofs.append({'attribute':name,**self._code(function.__code__)})
                self._record('RESOURCE_TOPOLOGY_HELPER_REGISTERED',callbacks=proofs)
                self.resource_topology=topology_module.capture_resource_topology(self.root/'resource-topology',
                    self.issuer,self.process_images.snapshots[0]['incarnation'])
                self._record('RESOURCE_TOPOLOGY_CAPTURE',boundary='REGISTRATION',artifact=self.resource_topology)

    def image_boundary(self,phase):
        if self.process_images is not None:
            for owner,name,function,code in self._image_functions:
                actual=getattr(owner,name);actual=actual.__func__ if type(actual)is types.MethodType else actual
                if actual is not function or function.__code__ is not code:raise ValueError('registered process-image helper/code changed')
            item=self.process_images.snapshot(phase)
            self._record('PROCESS_IMAGE_BOUNDARY',phase=phase,snapshot_sequence=item['sequence'])

    def process_declaration(self,native_nonce):
        if self.process_images is None:return None
        return {'profile':PROCESS_PROFILE,'requested':True,'manifest':str(self.path),
                'issuer':dict(self.issuer),'native_nonce':native_nonce}

    def _record(self,event,**facts):
        if len(self.records)>=96:raise ValueError('collector registration record budget')
        self.records.append({'sequence':len(self.records),'event':event,
            'monotonic_ns':time.perf_counter_ns(),'issuer':dict(self.issuer),**facts})

    def _code(self,code):
        from scar.trace.code_snapshot import describe_code
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.semantics_v2 import SourceSnapshot
        from scar.ir.record_codec import decode,encode
        # Observe live code before consulting any source bytes.
        captured=decode(CapturedCode,describe_code(code))
        path=Path(captured.filename)
        base=Path(__file__).resolve().parents[2]
        if not path.is_absolute() or not (path.is_relative_to(base/'scar') or path==base/'sitecustomize.py'):
            raise ValueError('only SCAR collector/loader source may be compiled')
        raw=path.read_bytes()
        if len(raw)>500000:raise ValueError('collector source byte budget')
        text=raw.decode('utf-8')
        snapshot=SourceSnapshot(str(path),'sha256:'+hashlib.sha256(text.encode()).hexdigest(),'utf-8',
                                str(sys.version_info.major)+'.'+str(sys.version_info.minor))
        _matched,proof=self.store.resolve(captured,snapshot,(sys.flags.optimize,),allow_compile=True)
        return {'live_descriptor':encode(captured),'source_snapshot':encode(snapshot),
            'source_bytes_at_registration':{'uri':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)},
            'compiler_match':proof,'source_association':'COMPILED_DESCRIPTOR_MATCH_AT_REGISTRATION_NOT_LOADER_READ_PROOF'}

    def _owner(self,role,owner):
        r=self.recorder
        if role=='calls':return owner is r
        if role=='operands':return getattr(owner,'recorder',None) is r and r.operand_observer is owner
        if role=='environments':
            p=r.operand_observer
            return p is not None and getattr(p,'recorder',None) is r and p.environment_observer is owner
        if role=='native_manager':return getattr(owner,'_call_recorder',None) is r and getattr(r,'_collector_native_manager',None) is owner
        if role=='dispatch':return getattr(owner,'recorder',None) is r and getattr(getattr(r,'_collector_native_manager',None),'_dispatch_evidence',None) is owner
        return False

    def register(self,role,owner,names,*,hook=None):
        if self.closed or role in self.registry or not self._owner(role,owner):
            raise ValueError('registration does not select the same live collector issuer')
        callbacks=[];proofs=[]
        for name in names:
            f=getattr(owner,name);function=f.__func__ if type(f) is types.MethodType else f
            if type(function) is not types.FunctionType:raise ValueError('collector callback is not an exact Python function')
            callbacks.append((name,function,function.__code__))
            proofs.append({'attribute':name,**self._code(function.__code__)})
        if hook is not None:
            self._hook_codes[role]=hook.__code__
            proofs.append({'attribute':'registered_hook',**self._code(hook.__code__)})
        self.registry[role]=(owner,tuple(callbacks),hook)
        self._record('REGISTERED',role=role,callbacks=proofs,
            parent_role=None if role=='calls' else 'operands' if role=='environments' else 'native_manager' if role=='dispatch' else 'calls',
            call_event_index=self.recorder.index,
            nonce=getattr(owner,'nonce',None),weak_reference_epoch=self.recorder.epoch)
        self.validate_live()

    def register_profile(self,profile):
        closure={name:cell.cell_contents for name,cell in zip(profile.__code__.co_freevars,profile.__closure__ or ())}
        if closure.get('recorder') is not self.recorder or sys.getprofile() is not profile or threading.getprofile() is not profile:
            raise ValueError('actual installed profile does not bind the same live recorder')
        self._profile_code=profile.__code__
        self.register('calls',self.recorder,('profile','_reference','observe_dispatch'),hook=profile)
        self._record('PROFILE_HOOK_INSTALLED',callback=self._code(profile.__code__))
        self._ready=True

    def register_loader(self,frame):
        self._record('LOADER_FRAME_EXECUTING',callback=self._code(frame.f_code),
                     module=frame.f_globals.get('__name__'),file=frame.f_globals.get('__file__'))

    def _validate_role(self,role):
        owner,callbacks,hook=self.registry[role]
        if not self._owner(role,owner):raise ValueError('registered '+role+' owner changed')
        for name,function,code in callbacks:
            actual=getattr(owner,name)
            actual=actual.__func__ if type(actual) is types.MethodType else actual
            if actual is not function or function.__code__ is not code:
                raise ValueError('registered '+role+' callback/code changed')
        if role=='operands' and not self.released:
            if owner._interfered or owner._monitoring_interfered or sys.monitoring.get_tool(owner.tool_id)!=owner.tool_name:
                raise ValueError('actual monitoring registration changed')
        if hook is not None and hook.__code__ is not self._hook_codes[role]:
            raise ValueError('registered hook CodeType changed')
        if role=='dispatch' and getattr(type(owner._mode),'__torch_dispatch__') is not hook:
            raise ValueError('actual dispatch mode callback changed')
        if role=='calls' and hook is not None and not self.released:
            if sys.getprofile() is not hook or threading.getprofile() is not hook:
                raise ValueError('installed profile hook changed')

    def validate_live(self):
        """Whole-chain check at registration/close or an explicit diagnostic."""
        if os.getpid()!=self.recorder.pid or self.closed:raise ValueError('issuer process/lifetime changed')
        for role in self.registry:self._validate_role(role)

    def guard(self,role,callback_code=None):
        # Existing positive-observation PID guards run before this call. No
        # per-leaf PID syscall, source hashing, compilation or all-role scan.
        if not self._ready or self._checking:return not self.errors
        self._checking=True
        try:
            self._validate_role(role)
            if callback_code is not None:
                owner,callbacks,hook=self.registry[role]
                if not any(callback_code is code for _name,_function,code in callbacks):
                    raise ValueError('guard was not called from its registered callback code')
                if role not in self._executed:
                    self._executed.add(role)
                    self._record('CALLBACK_EXECUTION_POINT',role=role,call_event_index=self.recorder.index)
            return not self.errors
        except (ValueError,AttributeError,TypeError) as error:
            if not self.errors:self.errors.append(str(error));self._record('KNOWN_REGISTRATION_CHANGE',role=role,reason=str(error))
            return False
        finally:self._checking=False

    def before_close(self):
        try:self.validate_live()
        except (ValueError,AttributeError,TypeError) as error:
            self.errors.append(str(error));self._record('KNOWN_REGISTRATION_CHANGE',role='close_boundary',reason=str(error))
        self._record('HOOK_RELEASE_BOUNDARY',weak_reference_epoch=self.recorder.epoch)
        self.released=True

    def close(self):
        if self.closed or os.getpid()!=self.recorder.pid:return
        if not self.released:self.errors.append('hooks were not checked before release')
        for owner,name,function,code in self._topology_functions:
            if getattr(owner,name) is not function or function.__code__ is not code:
                self.errors.append('registered resource-topology helper/code changed')
        closed=[]
        # Called after ordinary collectors close. Never bind open stream bytes.
        paths=[self.recorder.out/('call-meta.'+str(self.recorder.pid)+'.json')]
        for role,(owner,_callbacks,_hook) in self.registry.items():
            if role=='operands':
                if not owner._closed:self.errors.append('operand writer not closed')
                paths.append(owner._metadata_path)
            elif role=='environments':
                if not owner._closed:self.errors.append('environment writer not closed')
                paths.append(owner.metadata_path)
            elif role=='native_manager':
                if not owner._closed:self.errors.append('native manager not closed')
                if owner._manifest_path is not None:paths.append(owner._manifest_path)
            elif role=='dispatch':
                if not owner._closed:self.errors.append('dispatch writer not closed')
                paths.append(owner.meta_path)
        if not self.recorder.closed:self.errors.append('call writer not closed')
        for path in paths:
            if path is None or not path.is_file():self.errors.append('closed metadata unavailable');continue
            closed.append(_artifact(path))
        for role in ('calls','operands','environments','native_manager','dispatch'):
            if role not in self.registry:self.errors.append('MISSING_REGISTRATION:'+role)
        image_receipt=None
        if self.process_images is not None:
            self.image_boundary('COLLECTOR_CLOSE')
            image_receipt=self.process_images.close()
        self._record('CLOSED',weak_reference_epoch=self.recorder.epoch)
        self.closed=True
        doc={'schema':SCHEMA,'schema_version':2 if image_receipt is not None else 1,'profile':self.profile,'issuer':self.issuer,
             'registration_scope':self.context,'records':self.records,'closed_metadata':closed,
             'code_witness_store':self.store.receipt(),'status':'CLOSED' if not self.errors else 'OPEN',
             'errors':self.errors,'continuous_mutation_exclusion_established':False,
             'event_loss_excluded':False,'object_identity_established':False,
             'assumptions':['fixed collector executes the recorded registration checks','no adversarial native alteration of witness state'],
             'frontiers':['REGISTRATION_AND_CLOSE_ARE_NOT_CONTINUOUS_NO_TAMPER_PROOF','RUN_BINDING_REQUIRES_EXPLICIT_COORDINATES']}
        if image_receipt is not None:doc['process_image_receipts']=image_receipt
        if self.resource_topology is not None:
            from scar.trace.resource_topology import PROFILE as TOPOLOGY_PROFILE
            doc['capabilities']=[TOPOLOGY_PROFILE]
            doc['resource_topology']=self.resource_topology
        payload=_wire(doc)
        if len(payload)>1000000:raise ValueError('collector witness manifest budget')
        with self.path.open('xb') as f:f.write(payload)


def read_collector_execution_witness(path,*,expected_sha256):
    """Strict sidecar facts; no restored live owner or qualification from a flag."""
    p=Path(path)
    if p.stat().st_size>1000000:raise ValueError('collector witness manifest budget')
    raw=p.read_bytes()
    if len(raw)>1000000 or hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('collector witness bytes differ')
    d=json.loads(raw)
    pair=(d.get('schema_version'),d.get('profile'))
    if d.get('schema')!=SCHEMA or pair not in ((1,PROFILE),(2,PROCESS_PROFILE)) or d.get('status')!='CLOSED' or d.get('errors'):
        raise ValueError('collector execution witness is not closed/qualified for its profile')
    if d['registration_scope']['run'] is not None:raise ValueError('registration cannot synthesize a future Run')
    if d['issuer'].get('generation')!=1 or d['issuer']['process_id']!=d['registration_scope']['process_id']:
        raise ValueError('collector issuer generation/process mismatch')
    for index,record in enumerate(d['records']):
        if record.get('sequence')!=index or record.get('issuer')!=d['issuer']:
            raise ValueError('registration journal issuer/sequence changed')
    roles=[r.get('role') for r in d['records'] if r.get('event')=='REGISTERED']
    if len(roles)!=5 or set(roles)!=set(('calls','operands','environments','native_manager','dispatch')):
        raise ValueError('collector registration chain missing/duplicate')
    parents={'calls':None,'operands':'calls','environments':'operands','native_manager':'calls','dispatch':'native_manager'}
    for record in d['records']:
        if record.get('event')=='REGISTERED' and record.get('parent_role')!=parents[record['role']]:
            raise ValueError('registration parent chain changed')
    for a in d['closed_metadata']:
        target=Path(a['uri'])
        if target.parent!=p.parent.parent or a['size_bytes']>1000000 or target.stat().st_size>1000000:
            raise ValueError('closed collector metadata path/byte budget differs')
        b=target.read_bytes()
        if len(b)!=a['size_bytes'] or hashlib.sha256(b).hexdigest()!=a['sha256']:raise ValueError('closed collector metadata changed')
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.ir.program.call_edges import CapturedCode
    from scar.ir.semantics_v2 import SourceSnapshot
    from scar.ir.record_codec import decode
    declaration=d['code_witness_store'];store_path=p.parent/'code-witnesses'
    store_raw=(store_path/'manifest.json').read_bytes()
    if str(store_path/'manifest.json')!=declaration['path'] or len(store_raw)!=declaration['bytes'] or hashlib.sha256(store_raw).hexdigest()!=declaration['sha256']:
        raise ValueError('collector CodeWitness root changed')
    store=CodeWitnessStore(store_path,create=False,compile_missing=False)
    if store.document['producer'].get('issuer')!=d['issuer'] or store.document['producer'].get('profile')!=d['profile']:
        raise ValueError('CodeWitness archive belongs to another live issuer')
    for record in d['records']:
        callbacks=record.get('callbacks',[]) or ([record['callback']] if 'callback' in record else [])
        for callback in callbacks:
            snapshot=decode(SourceSnapshot,callback['source_snapshot'])
            captured=decode(CapturedCode,callback['live_descriptor'])
            text=store.text(snapshot)
            source=callback['source_bytes_at_registration']
            if source['uri']!=snapshot.path or 'sha256:'+source['sha256']!=snapshot.fingerprint or source['size_bytes']!=len(text.encode('utf-8')):
                raise ValueError('registered source byte receipt differs from its archived snapshot')
            _code,proof=store.resolve(captured,snapshot,(d['registration_scope']['optimize'],),allow_compile=False)
            if proof!=callback['compiler_match']:raise ValueError('stored source does not match recorded live callback descriptor')
    if pair==(2,PROCESS_PROFILE):
        if type(d['issuer']['generation'])is not int or type(d['issuer']['process_id'])is not int:
            raise ValueError('V2 issuer generation/process must be exact integers')
        from scar.trace.process_image_receipts import read_process_image_receipts
        ref=d['process_image_receipts'];image_path=p.parent/'process-images/manifest.json'
        if ref['uri']!=str(image_path) or ref['schema']!='scar.process-image-receipts':raise ValueError('process-image root/schema differs from registered witness')
        images=read_process_image_receipts(image_path,expected_sha256=ref['sha256'])
        if images['issuer']!=d['issuer'] or image_path.stat().st_size!=ref['size_bytes']:
            raise ValueError('process-image issuer/bytes differ')
        registration=images['snapshots'][0]['incarnation']
        if (registration.get('start_ticks') is not None and d['registration_scope']['birth']['status']=='OBSERVED'
                and registration['start_ticks']!=d['registration_scope']['birth']['proc_start_ticks']):
            raise ValueError('registration process start ticks contradicted')
        if 'resource_topology' in d or 'capabilities' in d:
            from scar.trace.resource_topology import PROFILE as TOPOLOGY_PROFILE,SCHEMA as TOPOLOGY_SCHEMA,read_resource_topology
            if d.get('capabilities')!=[TOPOLOGY_PROFILE] or 'resource_topology' not in d:
                raise ValueError('resource-topology capability/reference must both be explicit')
            ref=d['resource_topology'];target=p.parent/'resource-topology/manifest.json'
            if ref['uri']!=str(target) or ref['schema']!=TOPOLOGY_SCHEMA:
                raise ValueError('resource-topology exact namespace/schema differs')
            topology=read_resource_topology(target,expected_sha256=ref['sha256'])
            if target.stat().st_size!=ref['size_bytes'] or topology['issuer']!=d['issuer'] or topology['incarnation']!=registration:
                raise ValueError('resource topology has different issuer/incarnation/bytes')
            events=[r for r in d['records'] if r['event']=='RESOURCE_TOPOLOGY_CAPTURE']
            if len(events)!=1 or events[0].get('boundary')!='REGISTRATION' or events[0].get('artifact')!=ref:
                raise ValueError('resource topology lacks its unique registration capture record')
    elif 'process_image_receipts' in d:raise ValueError('V1 cannot silently acquire process-image capability')
    if pair==(1,PROFILE) and ('resource_topology' in d or 'capabilities' in d):
        raise ValueError('V1 cannot silently acquire resource topology')
    return d


def collector_witness_members(path,*,expected_sha256):
    """Exact closed declarations only; no glob and no coordinate authority."""
    p=Path(path)
    if p.resolve(strict=True)!=p or p.parent.is_symlink():raise ValueError('collector witness is not its exact retained namespace')
    d=read_collector_execution_witness(p,expected_sha256=expected_sha256)
    if d['profile']!=PROCESS_PROFILE:raise ValueError('ordinary process-image membership requires explicit V2')
    rows=[_artifact(p)];store=p.parent/'code-witnesses'
    rows.append(_artifact(store/'manifest.json'))
    doc=json.loads((store/'manifest.json').read_bytes())
    for family in ('sources','modules'):
        for item in doc[family].values():
            r=item['artifact'];name=Path(r['path'])
            if name.name!=r['path']:raise ValueError('CodeWitness member is not an exact local filename')
            q=store/name
            if q.is_symlink() or not q.is_file() or q.stat().st_size!=r['bytes'] or r['bytes']>32_000_000:
                raise ValueError('CodeWitness member path/size differs')
            data=q.read_bytes()
            if hashlib.sha256(data).hexdigest()!=r['sha256']:raise ValueError('CodeWitness member SHA differs')
            rows.append({'uri':str(q),'sha256':r['sha256'],'size_bytes':r['bytes'],
                'schema':'text/x-python; charset=utf-8' if family=='sources' else 'application/python-marshal'})
    r=d['process_image_receipts'];rows.append(r)
    images=json.loads(Path(r['uri']).read_bytes())
    for a in images['artifacts']:
        rows.append({'uri':str(Path(r['uri']).parent/a['path']),'sha256':a['sha256'],
                     'size_bytes':a['size_bytes'],'schema':a['schema']})
    if 'resource_topology' in d:
        from scar.trace.resource_topology import resource_topology_members
        r=d['resource_topology'];_topology,extra=resource_topology_members(r['uri'],expected_sha256=r['sha256'])
        rows.extend(extra)
    if len({x['uri'] for x in rows})!=len(rows):raise ValueError('duplicate declared collector witness member')
    return d,rows


def bind_collector_execution_witness(path,*,expected_sha256,coordinates):
    """Explicit postcapture join; existing coordinates/Run are never rewritten."""
    from scar.trace.capture_coordinates import CaptureCoordinates
    from scar.ir.record_codec import decode
    from scar.ir.program.providers import ProviderArtifact
    if type(coordinates) is not CaptureCoordinates or hashlib.sha256(coordinates.payload).hexdigest()!=coordinates.artifact.sha256:
        raise ValueError('ordinary bound coordinates required')
    d=read_collector_execution_witness(path,expected_sha256=expected_sha256)
    pid=d['registration_scope']['process_id']
    if coordinates.target_process.pid!=pid or d['issuer']['process_id']!=pid:
        raise ValueError('witness process differs from coordinate target')
    members={x['artifact']['uri']:x['artifact'] for x in coordinates.report['membership']}
    schema_views=[]
    for a in d['closed_metadata']:
        member=members.get(a['uri'])
        if member!=a:
            # Document schema and existing coordinate family schema are two
            # explicit views of the exact same version1 call-meta artifact.
            expected=Path(path).parent.parent/('call-meta.'+str(pid)+'.json')
            declaration=coordinates.report.get('call_collector_declaration',{})
            if (member is None or a['uri']!=str(expected) or a['schema']!='scar.call-edge-trace'
                    or member['schema']!='scar.call-edge-meta.v1'
                    or declaration.get('schema')!='scar.call-edge-trace'
                    or type(declaration.get('schema_version')) is not int or declaration['schema_version']!=1
                    or declaration.get('process_id')!=pid
                    or any(member[k]!=a[k] for k in ('uri','size_bytes','sha256'))):
                raise ValueError('witness closed metadata has no exact target-process coordinate membership')
            schema_views.append({'rule':'SCAR_CALL_META_SCHEMA1_TO_COORDINATE_FAMILY_META_V1',
                'source_schema_version':1,'source_artifact':a,'coordinate_artifact':member,
                'basis':'existing capture_coordinates operand.base_manifest family=meta, exact call-meta path/bytes/PID'})
        if member is None or coordinates.process_for(decode(ProviderArtifact,member),pid)!=coordinates.target_process:
            raise ValueError('witness metadata is not mapped to the exact coordinate target process')
    dispatch=[r for r in d['records'] if r.get('role')=='dispatch' and r['event']=='REGISTERED']
    if len(dispatch)!=1 or not dispatch[0]['nonce']:raise ValueError('native nonce is not bound by a live dispatch registration')
    declaration=coordinates.report.get('dispatch_collector_declaration')
    if not declaration or declaration.get('nonce')!=dispatch[0]['nonce'] or declaration.get('process_id')!=pid:
        raise ValueError('coordinate dispatch nonce/process differs from registered collector')
    if not coordinates.report.get('seed',{}).get('target_birth'):
        raise ValueError('coordinates have no observed target process birth anchor')
    # Do not use an analysis-process birth/nonce value for a missing collector fact.
    birth=d['registration_scope']['birth']
    frontiers=['CONTINUOUS_COLLECTOR_MUTATION_EXCLUSION_UNVERIFIED','PROCESS_BIRTH_JOIN_UNVERIFIED']
    if birth['status']!='OBSERVED':frontiers.append('COLLECTOR_PROCESS_BIRTH_UNAVAILABLE')
    joined=None
    if d['profile']==PROCESS_PROFILE:
        from scar.trace.process_image_receipts import incarnation_key,read_process_image_receipts
        _doc,declared=collector_witness_members(path,expected_sha256=expected_sha256)
        for a in declared:
            member=members.get(a['uri'])
            if member!=a or coordinates.process_for(decode(ProviderArtifact,member),pid)!=coordinates.target_process:
                raise ValueError('V2 witness member has no exact target-process ownership/publication')
        ref=d['process_image_receipts'];images=read_process_image_receipts(ref['uri'],expected_sha256=ref['sha256'])
        keys=[incarnation_key(x['incarnation']) for x in images['snapshots']]
        if keys and all(k is not None and k==keys[0] for k in keys) and images['snapshots'][-1]['phase']=='COLLECTOR_CLOSE':
            frontiers.remove('PROCESS_BIRTH_JOIN_UNVERIFIED')
            joined={'status':'BOUND_VIA_EXACT_OWNED_ARTIFACT_PUBLICATION',
                'qualification':'CONDITIONAL_ON_ORDINARY_COORDINATE_PROCESS_MEMBERSHIP_CONTRACT',
                'incarnation':images['snapshots'][0]['incarnation'],
                'coordinate_birth_anchor':coordinates.report['seed']['target_birth'],
                'basis':'same live issuer boundary facts + exact artifact creation/publication + ordinary process_for',
                'scope':'retained target process only; not global PID reuse or continuous no-tamper proof'}
    result={'profile':d['profile'],'witness':_artifact(Path(path)),'coordinates':coordinates.artifact,
        'run':coordinates.run.id,'process':coordinates.target_process.id,'issuer':d['issuer'],
        'process_birth_fact':birth,'coordinate_birth_anchor':coordinates.report['seed']['target_birth'],'dispatch_nonce':dispatch[0]['nonce'],
        'scope':'registration and closed collector ownership facts only','schema_views':schema_views,'frontiers':frontiers,
        'object_identity_established':False,'pid_reuse_excluded':False,'historical_scope_upgraded':False}
    if d['profile']==PROCESS_PROFILE:result['process_birth_join']=joined
    if 'resource_topology' in d:
        from scar.trace.resource_topology import PROFILE as TOPOLOGY_PROFILE
        result['resource_topology']={'capability':TOPOLOGY_PROFILE,'manifest':d['resource_topology'],
            'scope':'same-issuer registration provider facts with exact ordinary member/process ownership',
            'actual_resource_use_established':False,'allocation_established':False,'resource_readiness_established':False}
    return result

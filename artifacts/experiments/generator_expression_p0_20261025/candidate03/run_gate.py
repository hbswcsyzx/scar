"""Default no-op; root owns one qualified GeneratorExp retained-source window."""
import argparse
import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]

def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def verify_freeze(expected, *, inputs_stat=True):
    data=(BASE/'freeze.json').read_bytes()
    if digest(data)!=expected:raise ValueError('root-approved freeze SHA differs')
    f=json.loads(data);guard_bytes=0
    for row in f['small_frozen_files']+f['candidate_scar_sources']:
        p=Path(row['path']);b=p.read_bytes();guard_bytes+=len(b)
        if p.is_symlink() or len(b)!=row['bytes'] or digest(b)!=row['sha256']:raise ValueError('frozen producer/runner/dependency changed: '+str(p))
    if inputs_stat:
        for r in f['inputs']:
            p=Path(r['path']);s=p.stat()
            if p.is_symlink() or (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(r['size'],r['mtime_ns'],r['ctime_ns'],r['inode'],r['device']):raise ValueError('frozen retained input stat changed: '+str(p))
    return f,guard_bytes

def preload_readers():
    # Import the actual public reader/codec and their lowering validators;
    # no graph, source context, CodeType payload or lowerer is run here.
    import importlib
    import pickle
    import _compat_pickle
    names = ["scar.ir.program.codec", "scar.ir.record_codec", "scar.ir.v2.codec",
        "scar.ir.control_flow_v2", "scar.analysis.program_lowering", "scar.analysis.code_witness",
        "scar.analysis.program_composition", "scar.analysis.inventory_partitions"]
    names.extend("scar.analysis."+p.stem for pattern in ("source_*_lowering.py", "source_*_validation.py")
                 for p in sorted((ROOT/"scar/analysis").glob(pattern)))
    for name in names: importlib.import_module(name)
    return {name:str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
            if name!="__main__" and getattr(module,"__file__",None) and not name.startswith("scar.")}

def worker(expected,attempt):
    start=time.monotonic();deadline=start+600;lock=threading.Lock();stop=threading.Event();state={'phase':'FREEZE','body':None}
    progress=(attempt/'progress.jsonl').open('x');guard=None;store=None;results=[];output_bytes=0;lowerings=0;total_ops=0;selection=None
    def charge(n):
        nonlocal output_bytes
        output_bytes+=n
        if output_bytes>256_000_000:raise ValueError('actual output/roundtrip budget256MB exceeded')
    def event(kind,**extra):
        with lock:
            value={**state,**extra,'event':kind,'elapsed_s':time.monotonic()-start,
                'actual_retained_input_bytes':guard.counts['actual_input_bytes'] if guard else 0,
                'output_accounted_bytes':output_bytes,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            data=raw(value);charge(len(data)*2);progress.write(data.decode());progress.flush();print(data.decode(),end='',flush=True)
    def save(name,value,zipped=False):
        data=raw(value)
        if len(data)>64_000_000:raise ValueError('single record64MB budget exceeded')
        encoded=gzip.compress(data,mtime=0) if zipped else data;charge(len(encoded)+(len(data) if zipped else 0))
        path=attempt/name
        with path.open('xb') as stream:stream.write(encoded)
        return {'path':str(path),'bytes':len(encoded),'sha256':digest(encoded),'decoded_bytes':len(data),'decoded_sha256':digest(data)}
    def heartbeat():
        while not stop.wait(20):event('HEARTBEAT')
    threading.Thread(target=heartbeat,daemon=True).start()
    def expiry(n,f):raise TimeoutError('independent body/worker deadline exceeded')
    signal.signal(signal.SIGALRM,expiry);signal.setitimer(signal.ITIMER_REAL,600)
    signal.signal(signal.SIGTERM,lambda n,f: (_ for _ in ()).throw(SystemExit(128+n)))
    try:
        preload_readers();freeze,first_guard_bytes=verify_freeze(expected)
        selection=json.loads((BASE/'selection.json').read_bytes())
        if len(selection['selected'])!=1 or len(selection['files'])!=1:raise ValueError('exact qualified1body/1file scope differs')
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.inventory_partitions import InventoryPartitions
        from scar.analysis.program_lowering import PreparedSource,SourceProgram,_symbol_tables
        from scar.analysis.source_language import SourceCodeEvidence,SourceLanguageOptions
        from scar.analysis.source_language_validation import validate_language_body
        from scar.analysis.structured_lowering import require_valid_structured_body
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.program.inventory import DefinitionInventory
        from scar.ir.program.functions import BodyLoweringProfile
        from scar.ir.program.source_language import SourceLanguageCapability
        from scar.ir.record_codec import encode,decode
        from gate_guards import GateGuards
        guard=GateGuards(freeze,selection,attempt,approved_freeze_sha256=expected);guard.install();event('BEGIN')
        for pin in selection['qualification_metadata']:
            value=Path(pin['path']).read_bytes()
            if len(value)!=pin['bytes'] or digest(value)!=pin['sha256']:raise ValueError('prior qualified metadata changed')
        state['phase']='CURRENT_INPUT_MEMBERSHIP';event('STAGE_BEGIN')
        report=json.loads(Path(selection['current_report']).read_bytes())
        current=InventoryPartitions(report['inventory']['path'],max_shard_bytes=64_000_000,cache_entries=2)
        receipt=current.manifest_receipt
        if report['inventory']!={'path':str(current.path),'raw_sha256':receipt['physical_sha256'],'raw_bytes':receipt['physical_bytes'],'decoded_bytes':receipt['decoded_bytes']}:
            raise ValueError('current report/inventory accurate receipt mismatch')
        coordinate=json.loads(Path(report['coordinate_binding']['uri']).read_bytes())
        if coordinate['run']!=report['run'] or report['run']!=selection['run']:raise ValueError('current report/coordinate/Run mismatch')
        state['phase']='ONE_ORIGINAL_COMPOSITION';event('STAGE_BEGIN')
        comp=CompositionIndex(selection['compiler_origin_composition'],max_input_bytes=96_000_000,max_record_bytes=64_000_000,cached_files=2)
        if current.code_source_origin()!=comp.original_code_source_origin():raise ValueError('current/original compiler-source inventory origin differs')
        store=CodeWitnessStore(selection['store'],budget=CodeWitnessBudget(max_compile_keys=20,max_module_bytes=64_000_000),create=False,compile_missing=False)
        if store.writable or store.compile_missing:raise ValueError('witness reader gained compilation/write capability')
        for ordinal,item in enumerate(selection['selected'],1):
            state.update(phase='EXACT_QUALIFIED_SUBJECT',body=ordinal);event('STAGE_BEGIN')
            body_started=time.monotonic();signal.setitimer(signal.ITIMER_REAL,max(.001,min(180,deadline-body_started)))
            work=item['work_input'];fi=item['file_index'];file=current.file(fi)
            definitions=[d for d in file['definitions'] if d['id']==work['definition'] and d['source']==work['source']]
            if len(definitions)!=1 or file['snapshot']!=work['snapshot'] or file['context']!=work['context']:
                raise ValueError('qualified subject no longer matches exact current definition/snapshot/context')
            bodies=[b for b in file['bodies'] if b['definition']==work['definition']]
            if len(bodies)!=1 or bodies[0]['status']=='LOWERED_WITH_GAPS':raise ValueError('qualified subject has already been modeled in bound current inventory')
            matching=[i for i,row in enumerate(comp.document['files']) if row['snapshot']==work['snapshot'] and row['context']==work['context']]
            if len(matching)!=1:raise ValueError('original composition source/context not unique')
            cfi=matching[0]
            if sum(d['id']==work['definition'] and d['source']==work['source'] for d in comp.inventory_file(cfi)['definitions'])!=1:
                raise ValueError('original definition inventory membership differs')
            evidence=SourceCodeEvidence(store,comp,decode(CapturedCode,work['captured']))
            if evidence.to_dict()!=item['old_code_witness']:raise ValueError('exact prior CodeWitness/source provenance differs')
            view=comp.source(cfi)
            if encode(view.snapshot)!=work['snapshot'] or encode(view.context)!=work['context']:raise ValueError('source context differs')
            text=store.text(view.snapshot);tree=ast.parse(text,filename=view.snapshot.path)
            if digest(text.encode())!=view.snapshot.fingerprint.removeprefix('sha256:'):raise ValueError('retained UTF8 differs')
            for ref in item['trigger_sources']:
                nodes=[n for n in ast.walk(tree) if isinstance(n,ast.GeneratorExp)
                    and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])]
                if len(nodes)!=1:raise ValueError('original GeneratorExp source is not unique')
                gen=nodes[0]
                parents=[p for p in ast.walk(tree) if gen in tuple(ast.iter_child_nodes(p))]
                if len(parents)!=1 or not isinstance(parents[0],ast.Assign) or len(parents[0].targets)!=1 or not isinstance(parents[0].targets[0],(ast.Tuple,ast.List)):
                    raise ValueError('original fixed-unpack GeneratorExp predicate changed')
            context=PreparedSource(Path(view.snapshot.path),Path(view.context.namespace_root),text,view.semantic,view.semantics,view.control,tree,_symbol_tables(text,view.snapshot.path))
            session=context.seal_for_lowering();definition=decode(DefinitionInventory,definitions[0])
            evidence.require_definition(view.snapshot,definition.id,definition.source)
            capabilities=tuple(SourceLanguageCapability(value) for value in item['requested_capabilities'])
            options=SourceLanguageOptions(capabilities,evidence)
            save(f'body-{ordinal:02d}-inputs.json',{'original_qualified_subject':item,'qualified_definition':definitions[0],
                'source_archive':encode(view.artifact_locator),'code_evidence':evidence.to_dict(),
                'source_mode':'EXACT_RETAINED_AST_OPTIONS_AND_VALIDATOR_SOURCES; not filesystem source replay'})
            state['phase']='LOWER_EXACT_GENEXPR_BODY';event('STAGE_BEGIN');lowerings+=1
            lowered=session.lower(definition.qualname,source=definition.source,max_operations=4000,expand_candidates=False,
                profile=BodyLoweringProfile.STRUCTURED_ENV,language_options=options)
            total_ops+=lowered.operations_emitted
            if total_ops>4000:raise ValueError('qualified one-body4000 operations budget exceeded')
            returned=save(f'body-{ordinal:02d}-returned.json',{'metadata':encode(lowered.metadata),'interface':encode(lowered.interface),
                'structured':encode(lowered.structured),'language':encode(lowered.language),'graph_present':lowered.graph is not None,
                'operations_emitted':lowered.operations_emitted})
            artifact=None;checks={};status='UNSUPPORTED' if lowered.graph is None else 'RECOVERED_WITH_OPEN'
            if lowered.graph is not None:
                state['phase']='PUBLIC_STRUCTURE_AND_INDEPENDENT_CHECKS';event('STAGE_BEGIN')
                program=SourceProgram(lowered.graph,lowered.metadata,context.semantic,context.semantics,context.control,
                    BodyLoweringProfile.STRUCTURED_ENV,lowered.interface,lowered.frame,lowered.structured,lowered.language)
                artifact=save(f'body-{ordinal:02d}-source-program5.json.gz',program.to_dict(),True)
                stored=Path(artifact['path']).read_bytes();charge(len(stored))
                if len(stored)!=artifact['bytes'] or digest(stored)!=artifact['sha256']:raise ValueError('stored program receipt differs')
                with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:payload=stream.read(64_000_001)
                charge(len(payload))
                if len(payload)!=artifact['decoded_bytes'] or digest(payload)!=artifact['decoded_sha256']:raise ValueError('decoded program receipt differs')
                document=json.loads(payload)
                loaded=SourceProgram.read_structure(document,max_operations=4000,source_texts={view.snapshot.path:text})
                if loaded.to_dict()!=document:raise ValueError('public structure roundtrip differs')
                require_valid_structured_body(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,semantic=loaded.semantic,
                    control=loaded.control,language=loaded.language,source_tree=tree,language_options=options)
                checked=validate_language_body(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,loaded.semantic,
                    loaded.language,source_tree=tree,options=options)
                from scar.analysis.source_generator_validation import validate_generator_regions
                generator_ops=validate_generator_regions(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,loaded.semantic,
                    loaded.language,source_tree=tree,options=options)
                generator_evidence={'validated_original_operation_ids':sorted(k.wire for k in generator_ops),
                    'creation_records':len(loaded.graph.resumable_creates),'lazy_body_regions':len(loaded.graph.resumable_bodies),
                    'body_drive_records':len(loaded.graph.body_drives),'close_throw':'OPEN_UNEXPANDED',
                    'runtime_rng_effects':'OPEN','whole_lifetime':'OPEN'}
                checks={'generator_source_code_temporal_partition':generator_evidence,'public_structure_roundtrip_equal':True,'independent_source_and_code':checked,
                    'source_mode':'EXACT_RETAINED_AST_OPTIONS_AND_VALIDATOR_SOURCES','default_filesystem_replay':False,
                    'runtime_instance_verified':False,'whole_lifetime_verified':False,'effects_established':False}
            row={'original_sequence':item['original_sequence'],'original_work_key':item['original_work_key'],'body_key':item['body_key'],
                'definition':work['definition'],'source':work['source'],'status':status,'operations_emitted':lowered.operations_emitted,
                'artifact':artifact,'returned':returned,'checks':checks,'gaps':encode(lowered.metadata.gaps),'elapsed_s':time.monotonic()-body_started,
                'whole_program_established':False,'whole_lifetime_verified':False}
            results.append(row);save(f'body-{ordinal:02d}-result.json',row);event('BODY_END',status=status,operations_emitted=lowered.operations_emitted)
            if artifact is not None:del program,stored,payload,document,loaded,checked
            del context,session,lowered,evidence,tree,text,view,file
            signal.setitimer(signal.ITIMER_REAL,max(.001,deadline-time.monotonic()))
        state['phase']='FINAL_SOURCE_AND_INPUT_CHECK';event('STAGE_BEGIN')
        if any(guard.counts[k] for k in ('source_prepare_attempts','target_executable_compile_attempts','target_exec_attempts')) or store.counts['compile_attempts'] or store.counts['source_bytes_read']:
            raise ValueError('target/compile/prepare zero ceiling violated')
        _freeze,last_guard_bytes=verify_freeze(expected)
        allowed={r['path']:r for r in freeze['candidate_scar_sources']};participants=[]
        for name,module in tuple(sys.modules.items()):
            file=getattr(module,'__file__',None)
            if name.startswith('scar.') and file:
                path=str(Path(file).resolve())
                if path not in allowed:raise ValueError('SCAR dependency escaped isolated freeze')
                participants.append(allowed[path])
        runtime_allowed={r['path']:r for r in freeze['runtime_modules']+freeze['small_frozen_files']}
        if any(path not in runtime_allowed for path in preload_readers().values()):raise ValueError('runtime dependency escaped frozen preflight')
        footer={'schema':'scar.genexpr-qualified-retained-result','schema_version':1,'status':'ONE_QUALIFIED_GENEXPR_FINISHED_OPEN',
            'results':results,'parent_scope':selection['parent_scope'],'prior_failed_results_preserved':True,
            'body_lowerings_started':lowerings,'total_operations_emitted':total_ops,'guard':guard.receipt(),
            'code_witness_activity':dict(store.counts),'participating_producers':participants,'producer_source_guard_bytes':first_guard_bytes+last_guard_bytes,
            'output_accounted_bytes_before_footer':output_bytes,'wall_seconds':time.monotonic()-start,
            'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'whole_program_established':False,
            'publication_performed':False,'current_run_integrated':False,'new_episode':False,'whole_lifetime_verified':False}
        save('result.json',footer);state['phase']='FINISHED_OPEN';event('FINISHED',whole_program='OPEN');return 0
    except BaseException as error:
        state['phase']='FAILED_RETAINED';event('FAILED',exception=type(error).__name__,message=str(error))
        save('failure.json',{'status':'FAILED_RETAINED_NO_RETRY','exception':type(error).__name__,'message':str(error),
            'traceback':traceback.format_exc(),'completed_results':results,'body_lowerings_started':lowerings,
            'known_returned_operations':total_ops,'current_body':state['body'],'parent_scope':selection['parent_scope'] if selection else None,
            'guard':guard.receipt() if guard else None,'code_witness_activity':dict(store.counts) if store else None,
            'wall_seconds':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        traceback.print_exc();return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);stop.set();progress.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--freeze-sha256');p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);p.add_argument('--attempt',help=argparse.SUPPRESS);a=p.parse_args()
    if a.worker:return worker(a.freeze_sha256,Path(a.attempt))
    if not a.execute:
        print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':str(BASE/'freeze.json'),'selection':str(BASE/'selection.json'),'attempt':str(BASE/'attempt01'),'input_streams_opened':False},sort_keys=True));return 0
    if not a.freeze_sha256:raise ValueError('root-approved freeze SHA required')
    freeze,_bytes=verify_freeze(a.freeze_sha256);attempt=Path(freeze['attempt'])
    if attempt!=BASE/'attempt01':raise ValueError('attempt is not fixed fresh directory')
    attempt.mkdir(exist_ok=False);(attempt/'BUILDING.json').write_bytes(raw({'status':'BUILDING','freeze_sha256':a.freeze_sha256,'automatic_retry':False}))
    command=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--freeze-sha256',a.freeze_sha256,'--attempt',str(attempt)]
    started=time.monotonic();env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
    with (attempt/'stdout.log').open('x') as out,(attempt/'stderr.log').open('x') as err:
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=out,stderr=err,start_new_session=True)
        killed=False
        while process.poll() is None:
            if time.monotonic()-started>660 or sum(p.stat().st_size for p in attempt.rglob('*') if p.is_file())>256_000_000:
                os.killpg(process.pid,signal.SIGTERM);killed=True
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                break
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:pass
    footer={'status':'EXIT0_WINDOW_OPEN' if process.returncode==0 else 'FAILED_RETAINED_NO_RETRY','exit_code':process.returncode,'wall_seconds':time.monotonic()-started,'outer_budget_terminated':killed,'automatic_retry':False,'command':command,'attempt':str(attempt),'whole_program_established':False}
    (attempt/'launch-result.json').write_bytes(raw(footer));print(json.dumps(footer,sort_keys=True));return 0 if process.returncode==0 else 1

if __name__=='__main__':raise SystemExit(main())

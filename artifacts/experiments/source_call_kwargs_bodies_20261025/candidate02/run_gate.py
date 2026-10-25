"""Default no-op; root owns the one frozen four-body --execute session."""
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

def worker(expected,attempt):
    start=time.monotonic();deadline=start+600;lock=threading.Lock();stop=threading.Event();state={'phase':'FREEZE','body':None}
    progress=(attempt/'progress.jsonl').open('x');guard=None;store=None;output_bytes=0;results=[];total_ops=0
    def charge_output(n):
        nonlocal output_bytes
        output_bytes+=n
        if output_bytes>256_000_000:raise ValueError('actual output/roundtrip byte accounting exceeds256MB')
    def event(kind,**extra):
        with lock:
            d={**state,**extra,'event':kind,'elapsed_s':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'actual_retained_input_bytes':guard.counts['actual_input_bytes'] if guard is not None else 0,'output_accounted_bytes':output_bytes}
            b=raw(d);charge_output(len(b)*2);progress.write(b.decode());progress.flush();print(b.decode(),end='',flush=True)
    def heartbeat():
        while not stop.wait(20):event('HEARTBEAT')
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    def save(name,value,zipped=False):
        data=raw(value)
        if len(data)>64_000_000:raise ValueError('single output record64MB exceeded')
        stored=gzip.compress(data,mtime=0) if zipped else data
        charge_output(len(stored)+(len(data) if zipped else 0))
        p=attempt/name
        with p.open('xb') as stream:stream.write(stored)
        return {'path':str(p),'sha256':digest(stored),'bytes':len(stored),'decoded_bytes':len(data),'decoded_sha256':digest(data)}
    def expiry(signum,frame):raise TimeoutError('independent body/worker deadline exceeded')
    signal.signal(signal.SIGALRM,expiry);signal.setitimer(signal.ITIMER_REAL,600)
    signal.signal(signal.SIGTERM,lambda n,f: (_ for _ in ()).throw(SystemExit(128+n)))
    try:
        freeze,source_guard_bytes=verify_freeze(expected)
        selection=json.loads((BASE/'selection.json').read_bytes())
        event('BEGIN')
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.inventory_partitions import InventoryPartitions
        from scar.analysis.program_lowering import PreparedSource,SourceProgram,_symbol_tables
        from scar.analysis.source_language import SourceCodeEvidence,SourceLanguageOptions
        from scar.analysis.source_language_validation import validate_language_body
        from scar.analysis.source_call_validation import validate_call_protocols,is_original_call_definition
        from scar.analysis.structured_lowering import require_valid_structured_body
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.program.functions import BodyLoweringProfile
        from scar.ir.program.source_language import SourceLanguageCapability
        from scar.ir.program.inventory import DefinitionInventory
        from scar.ir.record_codec import decode,encode
        from scar.ir.semantics_v2 import Opcode
        from gate_guards import GateGuards
        guard=GateGuards(freeze,selection,attempt);guard.install()
        state['phase']='CURRENT_INPUT_MEMBERSHIP';event('STAGE_BEGIN')
        report=json.loads(Path(selection['current_report']).read_bytes())
        current=InventoryPartitions(selection['current_inventory'],max_shard_bytes=64_000_000,cache_entries=2)
        receipt=current.manifest_receipt
        if report['inventory']!={'path':str(current.path),'raw_sha256':receipt['physical_sha256'],'raw_bytes':receipt['physical_bytes'],'decoded_bytes':receipt['decoded_bytes']}:
            raise ValueError('current report/inventory accurate receipt mismatch')
        coordinate=json.loads(Path(report['coordinate_binding']['uri']).read_bytes())
        if coordinate['run']!=report['run'] or report['run']!=selection['run']:raise ValueError('current coordinate/Run mismatch')
        state['phase']='ORIGINAL_COMPOSITION';event('STAGE_BEGIN')
        comp=CompositionIndex(selection['compiler_origin_composition'],max_input_bytes=96_000_000,max_record_bytes=64_000_000,cached_files=2)
        if current.code_source_origin()!=comp.original_code_source_origin():raise ValueError('current and original compiler-source membership differ')
        store=CodeWitnessStore(selection['store'],budget=CodeWitnessBudget(max_compile_keys=20,max_module_bytes=64_000_000),create=False,compile_missing=False)
        if store.writable or store.compile_missing:raise ValueError('witness reader gained write/compile capability')
        sessions={};views={};source_inputs=[]
        capabilities=tuple(SourceLanguageCapability(value) for value in freeze['capabilities'])
        for ordinal,item in enumerate(selection['selected'],1):
            body_started=time.monotonic()
            signal.setitimer(signal.ITIMER_REAL,max(.001,min(180,deadline-body_started)))
            state.update(phase='EXACT_SOURCE_AND_CODE',body=ordinal);event('STAGE_BEGIN',original_sequence=item['original_sequence'])
            # Whole selected source shard receipts are checked by both public
            # readers; only the two selected file headers/contexts are opened.
            fi=item['file_index'];file=current.file(fi)
            definitions=[d for d in file['definitions'] if d['id']==item['definition']['id'] and d['source']==item['definition']['source']]
            if len(definitions)!=1 or definitions[0]!=item['definition'] or file['snapshot']!=item['snapshot'] or file['context']!=item['context']:
                raise ValueError('current exact source/context/definition membership changed')
            bodies=[b for b in file['bodies'] if b['definition']==item['definition']['id']]
            if len(bodies)!=1 or bodies[0]['status']!='UNSUPPORTED':raise ValueError('body no longer needs this recovery attempt')
            matches=[i for i,row in enumerate(comp.document['files']) if row['snapshot']==item['snapshot'] and row['context']==item['context']]
            if len(matches)!=1:raise ValueError('original composition exact source row is not unique')
            cfi=matches[0]
            original_defs=comp.inventory_file(cfi)['definitions']
            if sum(d['id']==item['definition']['id'] and d['source']==item['definition']['source'] for d in original_defs)!=1:raise ValueError('original compiler inventory definition membership differs')
            captured=decode(CapturedCode,item['captured']);evidence=SourceCodeEvidence(store,comp,captured)
            definition=decode(DefinitionInventory,item['definition'])
            if encode(evidence.source_link)!=item['code_source_link']:raise ValueError('complete original code/source link differs')
            if fi not in sessions:
                view=comp.source(cfi);views[fi]=view
                if encode(view.snapshot)!=item['snapshot'] or encode(view.context)!=item['context']:raise ValueError('source layer context differs')
                text=store.text(view.snapshot)
                if digest(text.encode())!=view.snapshot.fingerprint.removeprefix('sha256:'):raise ValueError('owned archived text differs')
                tree=ast.parse(text,filename=view.snapshot.path)
                context=PreparedSource(Path(view.snapshot.path),Path(view.context.namespace_root),text,view.semantic,view.semantics,view.control,tree,_symbol_tables(text,view.snapshot.path))
                session=context.seal_for_lowering();sessions[fi]=(context,session,tree)
                source_inputs.append({'file_index':fi,'snapshot':encode(view.snapshot),'context':encode(view.context),'artifact_locator':encode(view.artifact_locator)})
            context,session,tree=sessions[fi];view=views[fi]
            evidence.require_definition(view.snapshot,definition.id,definition.source)
            ref=item['frontier']['source'];span=(ref['start_line'],ref['end_line'],ref['start_column'],ref['end_column'])
            nodes=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==span]
            if len(nodes)!=1 or not any(k.arg is None for k in nodes[0].keywords) or any(isinstance(a,ast.Starred) for a in nodes[0].args):raise ValueError('source Call predicate changed')
            call_atoms=[a for a in view.semantic.source_atoms.values() if a.kind=='Call'
                        and a.reference.path==ref['path'] and a.reference.fingerprint==ref['fingerprint']
                        and (a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column)==span]
            if len(call_atoms)!=1:raise ValueError('exact AST Call has no unique original SG Call atom; Expr wrapper is separate')
            call_source=call_atoms[0].reference;atom=call_source.atom_id.wire
            sg=[d for d in view.semantic.definitions.values() if d.code_id==atom and any(a.wire==atom for a in d.source_atoms)
                and is_original_call_definition(view.semantic,d,call_source)]
            if len(sg)!=1:raise ValueError('selected Call has no unique original opaque ast_type Call/output')
            computations=[r for r in view.semantics.operations.values() if r.operation==sg[0].id
                          and r.source==call_source and r.opcode is Opcode.CALL]
            if len(computations)!=1:raise ValueError('original opaque SG Call has no unique computational Opcode.CALL')
            options=SourceLanguageOptions(capabilities,evidence)
            save(f'body-{ordinal:02d}-inputs.json',{'selection':item,'code_evidence':evidence.to_dict(),'source_archive':encode(view.artifact_locator),'selected_call_source':encode(call_source),'source_replay_mode':'ACCURATE_RETAINED_AST_AND_OPTIONS; not default filesystem source replay'})
            state['phase']='LOWER_BODY';event('STAGE_BEGIN')
            result=session.lower(definition.qualname,source=definition.source,max_operations=4000,expand_candidates=False,profile=BodyLoweringProfile.STRUCTURED_ENV,language_options=options)
            total_ops+=result.operations_emitted
            if total_ops>16000:raise ValueError('aggregate16000 emitted operation budget exceeded')
            returned=save(f'body-{ordinal:02d}-returned.json',{'metadata':encode(result.metadata),'interface':encode(result.interface),'structured':encode(result.structured),'language':encode(result.language),'operations_emitted':result.operations_emitted,'graph_present':result.graph is not None})
            checks={};artifact=None;status='UNSUPPORTED' if result.graph is None else 'RECOVERED_WITH_OPEN'
            if result.graph is not None:
                state['phase']='PUBLIC_STRUCTURE_AND_INDEPENDENT_CHECKS';event('STAGE_BEGIN')
                program=SourceProgram(result.graph,result.metadata,context.semantic,context.semantics,context.control,BodyLoweringProfile.STRUCTURED_ENV,result.interface,result.frame,result.structured,result.language)
                artifact=save(f'body-{ordinal:02d}-source-program5.json.gz',program.to_dict(),True)
                stored=Path(artifact['path']).read_bytes();charge_output(len(stored))
                if digest(stored)!=artifact['sha256']:raise ValueError('new stored artifact changed before public readback')
                with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:payload=stream.read(64_000_001)
                charge_output(len(payload))
                if len(payload)>64_000_000 or digest(payload)!=artifact['decoded_sha256']:raise ValueError('new artifact decoded roundtrip differs')
                document=json.loads(payload);loaded=SourceProgram.read_structure(document,max_operations=4000)
                structure_equal=loaded.to_dict()==document
                if not structure_equal:raise ValueError('public sourceProgram5 structure roundtrip differs')
                require_valid_structured_body(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,semantic=loaded.semantic,control=loaded.control,language=loaded.language,source_tree=tree,language_options=options)
                language=validate_language_body(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,loaded.semantic,loaded.language,source_tree=tree,options=options)
                calls=validate_call_protocols(loaded.structured,loaded.graph,loaded.interface,loaded.metadata,loaded.semantic,loaded.language,source_tree=tree,options=options)
                checks={'public_structure':{'roundtrip_equal':structure_equal,'mode':'STRUCTURE_ONLY; not metadata PASS proof'},'independent_source_and_compiler':language,'local_call_pending':calls,'default_filesystem_source_replay_performed':False,'source_mode':'EXACT_RETAINED_AST_OPTIONS','call_cleanup_contract_verified':False,'outer_prefix_verified':False}
            row={'original_sequence':item['original_sequence'],'definition':item['definition']['id'],'source':item['definition']['source'],'status':status,'operations_emitted':result.operations_emitted,'artifact':artifact,'returned':returned,'checks':checks,'gaps':encode(result.metadata.gaps),'whole_lifetime_verified':False,'elapsed_s':time.monotonic()-body_started}
            results.append(row);save(f'body-{ordinal:02d}-result.json',row);event('BODY_END',status=status,operations_emitted=result.operations_emitted)
            signal.setitimer(signal.ITIMER_REAL,max(.001,deadline-time.monotonic()))
        state['phase']='FINAL_SOURCE_AND_INPUT_CHECK';event('STAGE_BEGIN')
        if store.counts['compile_attempts'] or store.counts['source_bytes_read'] or any(guard.counts[k] for k in ('source_prepare_attempts','target_executable_compile_attempts','target_exec_attempts')):raise ValueError('compile/prepare/target zero ceiling violated')
        _freeze,final_guard_bytes=verify_freeze(expected)
        participants=[]
        allowed={row['path']:row for row in freeze['candidate_scar_sources']}
        for name,module in tuple(sys.modules.items()):
            file=getattr(module,'__file__',None)
            if name.startswith('scar.') and file:
                p=Path(file).resolve()
                if not p.is_relative_to(ROOT/'scar') or str(p) not in allowed:raise ValueError('SCAR import escaped frozen isolated source tree')
                participants.append(allowed[str(p)])
        footer={'schema':'scar.kwargs-four-body-gate-result','schema_version':1,'status':'FOUR_BODY_WINDOW_FINISHED_OPEN','results':results,'returned_bodies':len(results),'source_files':len(sessions),'total_operations_emitted':total_ops,'source_inputs':source_inputs,'guard':guard.receipt(),'code_witness_activity':dict(store.counts),'producer_source_guard_bytes':source_guard_bytes+final_guard_bytes,'participating_producers':participants,'output_accounted_bytes_before_footer':output_bytes,'output_accounting':'all saved/printed bytes plus compressed JSON decoded bytes and stored/decoded public roundtrip reads','wall_seconds':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'whole_program_established':False,'publication_performed':False,'current_run_integrated':False,'whole_lifetime_verified':False,'new_episode':False,'default_filesystem_source_replay_performed':False}
        save('result.json',footer);state['phase']='FINISHED_OPEN';event('FINISHED',returned_bodies=len(results),whole_program='OPEN')
        return 0
    except BaseException as error:
        state['phase']='FAILED_RETAINED'
        failure={'status':'FAILED_RETAINED_NO_RETRY','exception':type(error).__name__,'message':str(error),'traceback':traceback.format_exc(),'completed_results':results,'current_body':state['body'],'emitted_cost_for_unreturned_current_body':'UNKNOWN','known_returned_operations':total_ops,'guard':guard.receipt() if guard is not None else None,'code_witness_activity':dict(store.counts) if store is not None else None,'wall_seconds':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'automatic_retry':False}
        # Failure receipt remains even if the ordinary output budget failed.
        with (attempt/'failure.json').open('x') as stream:stream.write(raw(failure).decode())
        event('FAILED',exception=type(error).__name__,message=str(error));traceback.print_exc();return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);stop.set();thread.join(timeout=1);progress.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--freeze-sha256');p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);p.add_argument('--attempt',help=argparse.SUPPRESS);a=p.parse_args()
    if a.worker:return worker(a.freeze_sha256,Path(a.attempt))
    if not a.execute:
        print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':str(BASE/'freeze.json'),'selection':str(BASE/'selection.json'),'attempt':str(BASE/'attempt02'),'input_streams_opened':False},sort_keys=True));return 0
    if not a.freeze_sha256:raise ValueError('root-approved freeze SHA required')
    freeze,_bytes=verify_freeze(a.freeze_sha256);attempt=Path(freeze['attempt'])
    if attempt!=BASE/'attempt02':raise ValueError('attempt is not fixed fresh directory')
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

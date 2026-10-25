"""Root-owned normal-reader postflight. No module construction/retry occurs."""
import argparse
import ast
import gzip
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import pickle
import _compat_pickle
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback
from gate_guards import GateGuards

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]

def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def preload():
    for name in ('scar.analysis.program_lowering','scar.analysis.source_frontend_worklist',
        'scar.analysis.source_module_lowering','scar.analysis.source_module_validation','scar.ir.program.codec',
        'scar.ir.record_codec','scar.analysis.program_composition','scar.analysis.source_layers',
        'scar.analysis.code_witness','scar.analysis.source_language'):importlib.import_module(name)
    return {str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
            if name!='__main__' and getattr(module,'__file__',None) and not name.startswith('scar')}

def verify(expected):
    data=(BASE/'freeze.json').read_bytes()
    if digest(data)!=expected:raise ValueError('root-approved postflight freeze differs')
    f=json.loads(data);checked=0
    if Path(f['attempt'])!=BASE/'attempt01':raise ValueError('postflight attempt differs')
    for row in f['candidate_scar_sources']+f['runtime_sources']+f['small_frozen_files']:
        p=Path(row['path']);data=p.read_bytes();checked+=len(data)
        if p.is_symlink() or len(data)!=row['bytes'] or digest(data)!=row['sha256']:raise ValueError('frozen source/runtime/tool changed: '+str(p))
    if checked>f['limits']['source_runtime_guard_bytes_per_pass']:raise ValueError('source/runtime guard budget')
    for row in f['inputs']:
        p=Path(row['path']);s=p.stat()
        if p.is_symlink() or (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):raise ValueError('frozen input stat changed: '+str(p))
    return f,checked

def worker(expected):
    started=time.monotonic();attempt=BASE/'attempt01';phase={'phase':'START'};stopping=threading.Event();lock=threading.Lock()
    io_guard=None;evidence_store=None;source_guard_bytes=[];lower_attempts={'count':0};output_bytes=0
    progress=(attempt/'progress.jsonl').open('x')
    def event(label,**extra):
        with lock:
            record={**phase,**extra,'event':label,'elapsed_s':time.monotonic()-started,
                    'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            progress.write(raw(record).decode());progress.flush();print(raw(record).decode(),end='',flush=True)
    def heartbeat():
        while not stopping.wait(20):event('HEARTBEAT')
    threading.Thread(target=heartbeat,daemon=True).start()
    signal.signal(signal.SIGALRM,lambda n,f:(_ for _ in ()).throw(TimeoutError('postflight180s')))
    signal.setitimer(signal.ITIMER_REAL,180)
    def save(name,value):
        nonlocal output_bytes
        data=raw(value);output_bytes+=len(data)
        if len(data)>4_000_000 or output_bytes>16_000_000:raise ValueError('postflight output budget')
        with (attempt/name).open('xb') as stream:stream.write(data)
    try:
        preload();freeze,checked=verify(expected);source_guard_bytes.append(checked)
        selection=json.loads((BASE/'selection.json').read_bytes())
        io_guard=GateGuards(freeze,selection,attempt,approved_freeze_sha256=expected);io_guard.install()
        from scar.analysis.program_lowering import SourceProgram,PreparedSource
        import scar.analysis.program_lowering as program_api
        import scar.analysis.source_module_lowering as module_api
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.source_language import SourceCodeEvidence
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.program.module_entries import ModulePrefixOverlay
        from scar.ir.record_codec import decode,encode
        def forbidden_lower(*args,**kwargs):
            lower_attempts['count']+=1;raise RuntimeError('postflight forbids new source lowering')
        # Tooling guards only reject work; they never replace facts/readers.
        PreparedSource.lower=forbidden_lower;PreparedSource.lower_entry=forbidden_lower
        program_api.lower_source=forbidden_lower;program_api._lower_prepared=forbidden_lower
        module_api.lower_module_entry=forbidden_lower
        module_api.ModuleBuilder.run_module=forbidden_lower;module_api.ModulePrefixBuilder.run_module=forbidden_lower
        phase['phase']='ORIGINAL_WINDOW_METADATA';event('BEGIN')
        original=json.loads(Path(selection['original_freeze']).read_bytes())
        if digest(Path(selection['original_freeze']).read_bytes())!=selection['original_freeze_sha256']:raise ValueError('original candidate freeze differs')
        terminal=json.loads(Path(selection['original_result']).read_bytes())
        lines=Path(selection['original_progress']).read_text().splitlines();events=[json.loads(line) for line in lines]
        stderr_text=Path(selection['original_stderr']).read_text()
        if terminal['actual_worker_exit_code']!=1 or "'Operation' object has no attribute 'counts'" not in stderr_text:raise ValueError('original failed window attribution differs')
        phases=[row.get('phase') for row in events]
        observed=('NORMAL_SOURCEPROGRAM7_READBACK','ONE_OLD_SP6_CONSUMPTION_NO_LOWER','FINAL_CODE_INPUT_RUNTIME_CHECK')
        if not all(name in phases for name in observed):raise ValueError('old control-flow observation incomplete')
        if [phases.index(name) for name in observed]!=sorted(phases.index(name) for name in observed):raise ValueError('old observed phase order differs')
        phase['phase']='SP7_RETAINED_ARTIFACT';event('BEGIN')
        declaration=selection['sp7_postflight_measurement']
        stored=Path(declaration['uri']).read_bytes()
        with gzip.GzipFile(fileobj=io.BytesIO(stored),mode='rb') as stream:decoded=stream.read()
        if (len(stored),digest(stored),len(decoded),digest(decoded))!=(declaration['stored_bytes'],declaration['stored_sha256'],declaration['decoded_bytes'],declaration['decoded_sha256']):raise ValueError('SP7 postflight measured bytes/SHA differ')
        document=json.loads(decoded)
        if document['schema_version']!=7:raise ValueError('postflight input is not the stored SP7')
        captured=decode(CapturedCode,document['module']['declaration']['witness']['captured'])
        phase['phase']='NORMAL_COMPOSITION_READONLY_WITNESS';event('BEGIN')
        composition=CompositionIndex(selection['composition'],max_input_bytes=4_000_000,max_record_bytes=4_000_000,cached_files=1)
        evidence_store=CodeWitnessStore(selection['witness_archive'],budget=CodeWitnessBudget(max_compile_keys=4,
            max_source_files=4,max_source_bytes=256000,max_archive_bytes=16_000_000,max_module_bytes=16_000_000,max_manifest_bytes=2_000_000),
            create=False,compile_missing=False)
        root_evidence=SourceCodeEvidence(evidence_store,composition,captured)
        retained_text=Path(selection['archived_source']).read_text(encoding='utf8')
        logical_path=selection['expected_unit']['snapshot']['path']
        phase['phase']='NORMAL_SP7_READBACK_NO_LOWER';event('BEGIN')
        restored=SourceProgram.read_structure(document,max_operations=4000,source_texts={logical_path:retained_text},module_code_evidence=root_evidence)
        if type(restored.module) is not ModulePrefixOverlay or raw(restored.to_dict())!=raw(document):raise ValueError('normal SP7 postflight readback differs')
        if encode(restored.module.declaration.unit)!=selection['expected_unit'] or encode(restored.module.census)!=selection['expected_census']:raise ValueError('original qualified source unit/census differs')
        file_context=composition.document['files'][0]['context']
        if encode(restored.module.remaining.subject.context)!=file_context:raise ValueError('original source-context differs')
        phase['phase']='FINAL_SOURCE_INPUT_RUNTIME_CHECK';event('BEGIN')
        final,checked=verify(expected);source_guard_bytes.append(checked)
        runtime_paths=preload();allowed={row['path'] for row in final['runtime_sources']}
        if not runtime_paths<=allowed:raise ValueError('postflight runtime participant missing from freeze')
        activity=io_guard.receipt()
        if lower_attempts['count'] or any(activity['counts'][key] for key in ('target_executable_compile_attempts','target_exec_attempts','source_prepare_attempts')):raise ValueError('postflight prohibited activity attempted')
        report={'schema':'scar.module-import-prefix-postflight-result','schema_version':1,'status':'NORMAL_READER_POSTFLIGHT_WITH_OPEN',
            'original_window':{'actual_exit_code':1,'freeze_sha256':selection['original_freeze_sha256'],
                'failure':'runner variable shadow in footer and exception receipt; original files unchanged',
                'original_writer_artifact_receipt':'MISSING; this postflight measurement is a new receipt',
                'lost_code_witness_counts':None,'lost_activity_counts':None,'lost_actual_runtime_participant_list':None,
                'lost_evidence_status':'OPEN_NOT_RECONSTRUCTED',
                'SP7_three_negatives_and_SP6_consumer':'CONTROL_FLOW_OBSERVATION_ONLY_NOT_REEXECUTED',
                'observed_phases':observed,'evidence':'exact pinned progress/stderr/original runner; phase order guards reached footer'},
            'postflight':{'normal_SP7_readback':'PASSED','module_lowerings':0,'lower_attempt_guard_count':lower_attempts['count'],
                'code_witness_counts':dict(evidence_store.counts),'activity':activity,'actual_runtime_participant_paths':sorted(runtime_paths),
                'source_runtime_guard_bytes_per_pass':source_guard_bytes,'final_source_input_runtime_checks':'PASSED'},
            'sourceprogram':declaration,'summary':restored.summary(),
            'residual_source_subject':encode(restored.module.remaining.subject),
            'namespace_attempt_addresses':len(restored.graph.state_address_refinements),
            'stored_content_proofs':len(restored.graph.stored_value_writes),
            'source_statement_interfaces_expanded':1,'body_internal_operations_recovered':0,
            'whole_body_complete':False,'whole_program_complete':False,'published':False,'main_changed':False,
            'elapsed_s':time.monotonic()-started,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'production_sources':freeze['production_sources']}
        save('worker-result.json',report);event('FINISHED',status=report['status']);return 0
    except BaseException as error:
        save('failure.json',{'phase':phase['phase'],'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
            'postflight_elapsed_s':time.monotonic()-started,'new_code_witness_counts':dict(evidence_store.counts) if evidence_store is not None else None,
            'new_activity':io_guard.receipt() if io_guard is not None else None,'new_lower_attempts':lower_attempts['count']})
        event('FAILED',error=str(error));return 1
    finally:
        stopping.set();signal.setitimer(signal.ITIMER_REAL,0);progress.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--read-inputs',action='store_true');p.add_argument('--worker',action='store_true');p.add_argument('--approved-freeze-sha256');args=p.parse_args()
    if not args.read_inputs and not args.worker:print('NOT_RUN: root supplies --read-inputs --approved-freeze-sha256');return 0
    if not args.approved_freeze_sha256:raise ValueError('approved freeze required')
    if args.worker:return worker(args.approved_freeze_sha256)
    data=(BASE/'freeze.json').read_bytes();f=json.loads(data)
    if digest(data)!=args.approved_freeze_sha256 or Path(f['attempt'])!=BASE/'attempt01':raise ValueError('approved postflight freeze/attempt differs')
    attempt=Path(f['attempt']);attempt.mkdir(exist_ok=False);started=time.monotonic()
    command=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-freeze-sha256',args.approved_freeze_sha256]
    try:
        with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
            code=subprocess.run(command,stdout=out,stderr=err,timeout=240,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)}).returncode
    except subprocess.TimeoutExpired:code=124
    with (attempt/'result.json').open('xb') as stream:stream.write(raw({'schema':'scar.module-import-postflight-window','schema_version':1,
        'actual_postflight_exit_code':code,'original_window_exit_code':1,'elapsed_s':time.monotonic()-started,
        'freeze_sha256':args.approved_freeze_sha256,'whole_program_complete':False}))
    return code
if __name__=='__main__':raise SystemExit(main())

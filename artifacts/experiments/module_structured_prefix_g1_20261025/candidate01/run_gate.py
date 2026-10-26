"""Root-owned B gate: one retained module prefix and ordinary SP8/7/6 readers."""
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
EXPERIMENT=BASE.parent
ROOT=BASE.parents[3]
sys.path.insert(0,str(EXPERIMENT))

def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def preload():
    for name in ('scar.analysis.program_lowering',
        'scar.analysis.source_module_lowering','scar.analysis.source_module_validation',
        'scar.analysis.program_composition','scar.analysis.code_witness','scar.analysis.source_language',
        'scar.analysis.source_layers','scar.ir.program.codec','scar.ir.record_codec'):
        importlib.import_module(name)
    return {str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
            if name!='__main__' and getattr(module,'__file__',None) and not name.startswith('scar')}

def verify(expected):
    encoded=(BASE/'freeze.json').read_bytes()
    if digest(encoded)!=expected:raise ValueError('root-approved B freeze differs')
    freeze=json.loads(encoded)
    if Path(freeze['attempt'])!=BASE/'attempt01':raise ValueError('B attempt differs')
    checked=0
    for row in freeze['candidate_scar_sources']+freeze['runtime_sources']+freeze['small_frozen_files']:
        path=Path(row['path']);data=path.read_bytes();checked+=len(data)
        if path.is_symlink() or (len(data),digest(data))!=(row['bytes'],row['sha256']):raise ValueError('frozen code/tool changed: '+str(path))
    if checked>freeze['limits']['source_runtime_guard_bytes_per_pass']:raise ValueError('B code guard byte budget')
    for row in freeze['inputs']:
        path=Path(row['path']);stat=path.stat()
        if path.is_symlink() or (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino,stat.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):raise ValueError('B frozen input stat differs: '+str(path))
    return freeze,checked

def worker(expected):
    started=time.monotonic();attempt=BASE/'attempt01';phase={'phase':'START'}
    stopped=threading.Event();lock=threading.Lock();io_guard=None;evidence_store=None
    output_bytes=0;lower_attempts={'count':0};module_lowerings={'count':0};guard_bytes=[]
    progress=(attempt/'progress.jsonl').open('x')
    def event(label,**extra):
        with lock:
            record={**phase,**extra,'event':label,'elapsed_s':time.monotonic()-started,
                    'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            progress.write(raw(record).decode());progress.flush();print(raw(record).decode(),end='',flush=True)
    def heartbeat():
        while not stopped.wait(20):event('HEARTBEAT')
    threading.Thread(target=heartbeat,daemon=True).start()
    signal.signal(signal.SIGALRM,lambda n,f:(_ for _ in ()).throw(TimeoutError('B worker180s')))
    signal.setitimer(signal.ITIMER_REAL,180)
    def save(name,value):
        nonlocal output_bytes
        data=raw(value);output_bytes+=len(data)
        if len(data)>4_000_000 or output_bytes>16_000_000:raise ValueError('B output budget')
        with (attempt/name).open('xb') as stream:stream.write(data)
    try:
        preload();freeze,checked=verify(expected);guard_bytes.append(checked)
        selection=json.loads((BASE/'selection.json').read_bytes())
        io_guard=GateGuards(freeze,selection,attempt,approved_freeze_sha256=expected);io_guard.install()
        from scar.analysis.program_lowering import SourceProgram,PreparedSource
        import scar.analysis.program_lowering as program_api
        import scar.analysis.source_module_lowering as module_api
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.source_language import SourceCodeEvidence
        from scar.ir.program.call_edges import CapturedCode
        from scar.ir.record_codec import decode,encode
        def forbidden_lower(*args,**kwargs):
            lower_attempts['count']+=1;raise RuntimeError('B gate forbids other source lowering')
        PreparedSource.lower=forbidden_lower
        program_api.lower_source=forbidden_lower;program_api._lower_prepared=forbidden_lower
        module_api.ModuleBuilder.run_module=forbidden_lower;module_api.ModulePrefixBuilder.run_module=forbidden_lower
        documents=[]
        for row in selection['old_sourceprograms']:
            stored=Path(row['uri']).read_bytes()
            with gzip.GzipFile(fileobj=io.BytesIO(stored),mode='rb') as stream:decoded=stream.read()
            if (len(stored),digest(stored),len(decoded),digest(decoded))!=(row['stored_bytes'],row['stored_sha256'],row['decoded_bytes'],row['decoded_sha256']):raise ValueError('old SourceProgram exact receipt differs')
            document=json.loads(decoded)
            if document['schema_version']!=row['source_schema_version']:raise ValueError('old source schema differs')
            documents.append((row,document))
        phase['phase']='READONLY_ORIGINAL_COMPILER_ROOT';event('BEGIN')
        composition=CompositionIndex(selection['composition'],max_input_bytes=4_000_000,max_record_bytes=4_000_000,cached_files=1)
        evidence_store=CodeWitnessStore(selection['witness_archive'],budget=CodeWitnessBudget(max_compile_keys=4,
            max_source_files=4,max_source_bytes=256000,max_archive_bytes=16_000_000,max_module_bytes=16_000_000,max_manifest_bytes=2_000_000),
            create=False,compile_missing=False)
        captured=decode(CapturedCode,documents[-1][1]['module']['declaration']['witness']['captured'])
        root_evidence=SourceCodeEvidence(evidence_store,composition,captured)
        source_text=Path(selection['archived_source']).read_text(encoding='utf8')
        logical_path=selection['expected_unit']['snapshot']['path']
        consumers=[]
        for row,document in documents:
            phase['phase']='NORMAL_RETAINED_SP'+str(row['source_schema_version'])+'_READBACK';event('BEGIN')
            restored=SourceProgram.read_structure(document,max_operations=4000,
                source_texts={logical_path:source_text},module_code_evidence=root_evidence)
            if raw(restored.to_dict())!=raw(document):raise ValueError('historical normal reader changed document')
            if restored.graph.frame_roots:raise ValueError('historical reader acquired a new frame root')
            if encode(restored.module.declaration.unit)!=selection['expected_unit']:raise ValueError('old source unit differs')
            consumers.append({'source_schema_version':row['source_schema_version'],'artifact':row,
                'ordinary_readback':'PASSED','summary':restored.summary(),
                'verification':'STRUCTURE_WITH_RETAINED_SOURCE_TEXTS_AND_ORIGINAL_READONLY_ROOT_WITNESS'})
        phase['phase']='ONE_MODULE_B_PREFIX_LOWER';event('BEGIN')
        from scar.ir.program.module_entries import FrameBodyProfile,StructuredFrameBodyOverlay
        from scar.analysis.program_lowering import validate_source_program
        retained=restored
        context=PreparedSource(Path(logical_path),Path(selection['expected_unit']['namespace_root']),source_text,
            retained.semantic,retained.semantics,retained.control,ast.parse(source_text,filename=logical_path),{})
        original_module_lower=module_api.lower_module_entry
        def one_module_lower(prepared,selected,*,code_evidence,max_operations,profile):
            if (prepared is not context or encode(selected)!=selection['expected_unit'] or code_evidence is not root_evidence
                    or profile is not FrameBodyProfile.STRUCTURED_MAPPING_314_V1 or max_operations!=4000
                    or module_lowerings['count']):
                lower_attempts['count']+=1;raise RuntimeError('only this original qualified module/profile may be lowered once')
            module_lowerings['count']+=1
            return original_module_lower(prepared,selected,code_evidence=code_evidence,max_operations=max_operations,profile=profile)
        module_api.lower_module_entry=one_module_lower
        program=context.lower_entry(retained.module.declaration.unit,code_evidence=root_evidence,max_operations=4000,
            profile=FrameBodyProfile.STRUCTURED_MAPPING_314_V1)
        if type(program.module) is not StructuredFrameBodyOverlay:raise ValueError('B did not return its typed source/frame interface')
        document=program.to_dict();encoded=raw(document)
        if len(encoded)>4_000_000:raise ValueError('SP8 record decoded budget')
        stored=gzip.compress(encoded,mtime=0);output_bytes+=len(encoded)+len(stored)
        if output_bytes>16_000_000:raise ValueError('SP8 logical plus stored output budget')
        artifact=attempt/'sourceprogram8.json.gz'
        with artifact.open('xb') as stream:stream.write(stored)
        artifact_receipt={'uri':str(artifact),'stored_bytes':len(stored),'stored_sha256':digest(stored),
            'decoded_bytes':len(encoded),'decoded_sha256':digest(encoded),'receipt_origin':'THIS_B_WRITER'}
        save('sourceprogram8-receipt.json',artifact_receipt)
        phase['phase']='NORMAL_NEW_SP8_FULL_READBACK';event('BEGIN')
        retained_stored=artifact.read_bytes();io_guard.charge(len(retained_stored),'stored_bytes')
        with gzip.GzipFile(fileobj=io.BytesIO(retained_stored),mode='rb') as stream:retained_decoded=stream.read()
        io_guard.charge(len(retained_decoded),'decoded_bytes')
        if (digest(retained_stored),digest(retained_decoded))!=(artifact_receipt['stored_sha256'],artifact_receipt['decoded_sha256']):raise ValueError('owned SP8 EOF readback receipt differs')
        normal=SourceProgram.read_structure(json.loads(retained_decoded),max_operations=4000,
            source_texts={logical_path:source_text},module_code_evidence=root_evidence)
        if raw(normal.to_dict())!=encoded:raise ValueError('ordinary complete SP8 roundtrip differs')
        checked_source=validate_source_program(normal,max_operations=4000,verification='STRUCTURE',
            source_texts={logical_path:source_text},module_code_evidence=root_evidence)
        if not checked_source['valid']:raise ValueError('independent source/code validator rejected B')
        phase['phase']='FINAL_SOURCE_INPUT_RUNTIME_CHECK';event('BEGIN')
        final,checked=verify(expected);guard_bytes.append(checked)
        runtime_paths=preload();allowed={row['path'] for row in final['runtime_sources']}
        if not runtime_paths<=allowed:raise ValueError('B runtime participant missing from freeze: '+repr(sorted(runtime_paths-allowed)))
        activity=io_guard.receipt()
        if module_lowerings['count']!=1 or lower_attempts['count'] or any(activity['counts'][key] for key in ('target_executable_compile_attempts','target_exec_attempts','source_prepare_attempts')):raise ValueError('B prohibited activity attempted')
        report={'schema':'scar.module-structured-prefix-b-result','schema_version':1,'status':'SP8_MODULE_PREFIX_READBACK_WITH_OPEN',
            'scope':'ONE_RETAINED_MODULE_SOURCE_PREFIX_AND_READONLY_OLD_CONSUMERS',
            'module_lowerings':module_lowerings['count'],'sourceprogram':artifact_receipt,'summary':normal.summary(),
            'source_validation':checked_source,'new_normal_reader':'PASSED','root_frame':encode(normal.graph.frame_roots[0]),
            'exact_prefix':encode(normal.module.prefix),'exact_remaining':encode(normal.module.remaining),
            'old_consumers':consumers,'code_witness_counts':dict(evidence_store.counts),'activity':activity,
            'lower_attempt_guard_count':lower_attempts['count'],'source_runtime_guard_bytes_per_pass':guard_bytes,
            'actual_runtime_participant_paths':sorted(runtime_paths),'final_source_input_runtime_checks':'PASSED',
            'new_module_source_prefix_lowered':True,'try_source_producer_implemented':False,
            'synthetic_source_or_runtime_evidence':False,'module_body_complete':False,'whole_program_complete':False,
            'runtime_namespace_or_activation_bound':False,'published':False,'main_changed':False,
            'elapsed_s':time.monotonic()-started,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'production_sources':freeze['production_sources']}
        save('worker-result.json',report);event('FINISHED',status=report['status']);return 0
    except BaseException as error:
        save('failure.json',{'phase':phase['phase'],'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
            'elapsed_s':time.monotonic()-started,'activity':io_guard.receipt() if io_guard is not None else None,
            'new_code_witness_counts':dict(evidence_store.counts) if evidence_store is not None else None,
            'lower_attempt_guard_count':lower_attempts['count']})
        event('FAILED',error=str(error));return 1
    finally:
        stopped.set();signal.setitimer(signal.ITIMER_REAL,0);progress.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--read-inputs',action='store_true');parser.add_argument('--worker',action='store_true');parser.add_argument('--approved-freeze-sha256');args=parser.parse_args()
    if not args.read_inputs and not args.worker:print('NOT_RUN: root supplies --read-inputs --approved-freeze-sha256');return 0
    if not args.approved_freeze_sha256:raise ValueError('approved B freeze required')
    if args.worker:return worker(args.approved_freeze_sha256)
    freeze_bytes=(BASE/'freeze.json').read_bytes();freeze=json.loads(freeze_bytes)
    if digest(freeze_bytes)!=args.approved_freeze_sha256 or Path(freeze['attempt'])!=BASE/'attempt01':raise ValueError('approved B freeze/attempt differs')
    attempt=Path(freeze['attempt']);attempt.mkdir(exist_ok=False);started=time.monotonic()
    command=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-freeze-sha256',args.approved_freeze_sha256]
    try:
        with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
            code=subprocess.run(command,stdout=out,stderr=err,timeout=240,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)}).returncode
    except subprocess.TimeoutExpired:code=124
    with (attempt/'result.json').open('xb') as stream:stream.write(raw({'schema':'scar.module-structured-prefix-b-window','schema_version':1,
        'actual_worker_exit_code':code,'elapsed_s':time.monotonic()-started,'freeze_sha256':args.approved_freeze_sha256,
        'scope':'ONE_MODULE_PREFIX_WITH_OPEN','module_body_complete':False,'whole_program_complete':False}))
    return code
if __name__=='__main__':raise SystemExit(main())

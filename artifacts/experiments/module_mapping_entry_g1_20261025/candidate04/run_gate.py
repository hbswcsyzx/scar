"""Root-owned one-source exec-root entry gate. Default does not read inputs."""
import argparse
import ast
import gzip
import hashlib
import importlib
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
def digest(value):return hashlib.sha256(value).hexdigest()
def preload():
    names=['scar.analysis.program_lowering','scar.analysis.source_frontend_worklist',
        'scar.analysis.source_module_lowering','scar.analysis.source_module_validation',
        'scar.ir.program.codec','scar.ir.record_codec','scar.analysis.program_composition',
        'scar.analysis.source_layers','scar.analysis.code_witness','scar.analysis.source_language']
    for name in names:importlib.import_module(name)
    return {str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
            if name!='__main__' and getattr(module,'__file__',None) and not name.startswith('scar')}

def verify(expected):
    data=(BASE/'freeze.json').read_bytes()
    if digest(data)!=expected:raise ValueError('root-approved freeze SHA differs')
    freeze=json.loads(data);checked=0
    if Path(freeze['attempt'])!=BASE/'attempt01':raise ValueError('actual attempt and freeze differ')
    for row in freeze['candidate_scar_sources']+freeze['runtime_sources']+freeze['small_frozen_files']:
        path=Path(row['path']);value=path.read_bytes();checked+=len(value)
        if path.is_symlink() or len(value)!=row['bytes'] or digest(value)!=row['sha256']:raise ValueError('frozen code/dependency changed: '+str(path))
    if checked>freeze['limits']['source_runtime_guard_bytes_per_pass']:raise ValueError('code/runtime guard budget exceeded')
    for row in freeze['inputs']:
        p=Path(row['path']);s=p.stat()
        if p.is_symlink() or (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev)!=(row['size'],row['mtime_ns'],row['ctime_ns'],row['inode'],row['device']):raise ValueError('frozen original input stat changed: '+str(p))
    return freeze,checked

def worker(expected):
    start=time.monotonic();attempt=BASE/'attempt01';phase={'phase':'START'};stop=threading.Event();lock=threading.Lock()
    guard=store=None;output_bytes=0;completed=False;guard_bytes=[];lowerings=0
    progress=(attempt/'progress.jsonl').open('x')
    def event(event,**extra):
        with lock:
            record={**phase,**extra,'event':event,'elapsed_s':time.monotonic()-start,
                'self_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            progress.write(raw(record).decode());progress.flush();print(raw(record).decode(),end='',flush=True)
    def heartbeat():
        while not stop.wait(20):event('HEARTBEAT')
    threading.Thread(target=heartbeat,daemon=True).start()
    signal.signal(signal.SIGALRM,lambda n,f:(_ for _ in ()).throw(TimeoutError('180s source-only worker budget')))
    signal.setitimer(signal.ITIMER_REAL,180)
    def save(name,value,zipped=False):
        nonlocal output_bytes
        decoded=raw(value);stored=gzip.compress(decoded,mtime=0) if zipped else decoded
        if len(decoded)>4_000_000:raise ValueError('record4MB cap')
        output_bytes+=len(stored)+(len(decoded) if zipped else 0)
        if output_bytes>16_000_000:raise ValueError('output16MB cap')
        path=attempt/name
        with path.open('xb') as stream:stream.write(stored)
        return {'uri':str(path),'stored_bytes':len(stored),'stored_sha256':digest(stored),
                'decoded_bytes':len(decoded),'decoded_sha256':digest(decoded)}
    try:
        preload();freeze,n=verify(expected);guard_bytes.append(n)
        selection=json.loads((BASE/'selection.json').read_bytes())
        guard=GateGuards(freeze,selection,attempt,approved_freeze_sha256=expected);guard.install()
        from scar.analysis.program_composition import CompositionIndex
        from scar.analysis.source_frontend_worklist import module_entry_catalog
        from scar.analysis.program_lowering import PreparedSource,SourceProgram,_symbol_tables
        from scar.analysis.source_module_lowering import module_unit
        from scar.analysis.source_module_validation import module_validation_report
        from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
        from scar.analysis.source_language import SourceCodeEvidence
        from scar.ir.program.call_edges import CapturedCode,CodeCapture,CodeSourceLink,CallLinkStatus
        from scar.ir.program.module_entries import ModuleUnitSource,ModuleEntryProfile
        from scar.ir.record_codec import encode,decode
        phase['phase']='NORMAL_COMPOSITION_AND_CATALOG';event('BEGIN')
        composition=CompositionIndex(selection['composition'],max_input_bytes=4_000_000,max_record_bytes=4_000_000,cached_files=1)
        catalog=module_entry_catalog(composition,max_files=1)
        if len(catalog)!=1 or encode(catalog[0].unit)!=selection['expected_unit']:raise ValueError('mechanical original module unit differs')
        item=catalog[0];view=composition.source(item.file_index)
        text=Path(selection['archived_source']).read_text(encoding='utf8')
        if len(text.encode())>1_000_000:raise ValueError('source1MB cap')
        context=PreparedSource(Path(item.unit.snapshot.path),Path(item.unit.namespace_root),text,
            view.semantic,view.semantics,view.control,ast.parse(text,filename=item.unit.snapshot.path),
            _symbol_tables(text,item.unit.snapshot.path))
        if module_unit(context)!=item.unit:raise ValueError('source archive/qualified module unit mismatch')
        phase['phase']='READONLY_COMPILER_ROOT';event('BEGIN')
        store=CodeWitnessStore(selection['witness_archive'],budget=CodeWitnessBudget(max_compile_keys=4,
            max_source_files=4,max_source_bytes=256000,max_archive_bytes=16_000_000,
            max_module_bytes=16_000_000,max_manifest_bytes=2_000_000),create=False,compile_missing=False)
        model=composition.inventory_component('call_sources')['model']
        captures={decode(CodeCapture,row).code.key:decode(CodeCapture,row).code for row in model['codes']}
        links=[decode(CodeSourceLink,row) for row in model['code_links']]
        candidates=[link for link in links if link.status is CallLinkStatus.VERIFIED and link.snapshot==item.unit.snapshot]
        evidence=[]
        for link in candidates:
            candidate=SourceCodeEvidence(store,composition,captures[link.code])
            if candidate.witness['constant_path']==[]:evidence.append(candidate)
        if len(evidence)!=1:raise ValueError('no unique exact readonly exec-root witness')
        phase['phase']='ONE_MODULE_LOWER';event('BEGIN')
        lowerings+=1
        result=context.lower_entry(item.unit,code_evidence=evidence[0],max_operations=4000)
        if result.graph is None or result.module.unexpanded_body is None:raise ValueError('proved module entry must return a partial body interface, not GraphNone')
        if result.module.unexpanded_body.context!=item.context:raise ValueError('unexpanded body exact source context differs')
        if encode(result.module.census)!=selection['expected_census']:raise ValueError('95atoms/92ops/45CFG/56edges original census differs')
        artifact=save('sourceprogram6.json.gz',result.to_dict(),zipped=True)
        phase['phase']='NORMAL_SOURCEPROGRAM6_READBACK';event('BEGIN')
        path=Path(artifact['uri']);stored=path.read_bytes();decoded=gzip.decompress(stored)
        output_bytes+=len(stored)+len(decoded)
        if output_bytes>16_000_000:raise ValueError('output/readback16MB cap')
        if digest(stored)!=artifact['stored_sha256'] or digest(decoded)!=artifact['decoded_sha256']:raise ValueError('owned output readback SHA differs')
        doc=json.loads(decoded)
        restored=SourceProgram.read_structure(doc,max_operations=4000,
            source_texts={item.unit.snapshot.path:text},module_code_evidence=evidence[0])
        if raw(restored.to_dict())!=raw(doc):raise ValueError('ordinary v6 readback changed document')
        negative=[]
        for kind in ('unknown_field','missing_source_text','historical_version','discharged_expansion'):
            bad=json.loads(decoded)
            try:
                if kind=='unknown_field':bad['module']['caller_verified']=True
                if kind=='historical_version':bad['schema_version']=5
                if kind=='discharged_expansion':bad['module']['unexpanded_body']['required_expansion']='COMPLETE'
                SourceProgram.read_structure(bad,max_operations=4000,
                    source_texts={} if kind=='missing_source_text' else {item.unit.snapshot.path:text})
            except (ValueError,TypeError,KeyError):negative.append(kind)
            else:raise ValueError('strict reader failed negative: '+kind)
        validation=module_validation_report(restored,source_texts={item.unit.snapshot.path:text},
            code_evidence=evidence[0],max_operations=4000)
        if not validation['valid']:raise ValueError(str(validation))
        phase['phase']='FINAL_CODE_INPUT_RUNTIME_CHECK';event('BEGIN')
        final,n=verify(expected);guard_bytes.append(n)
        allowed={row['path'] for row in final['runtime_sources']}
        if not preload()<=allowed:raise ValueError('runtime participant missing from freeze')
        activity=guard.receipt()
        if any(activity['counts'][key] for key in ('target_executable_compile_attempts','target_exec_attempts','source_prepare_attempts')):raise ValueError('forbidden activity attempted')
        report={'schema':'scar.module-mapping-entry-source-only-result','schema_version':1,
            'status':'ENTRY_MODEL_READBACK_WITH_OPEN','qualified_unit':encode(item.unit),
            'original_module_catalog_units':len(catalog),'module_lowerings':lowerings,
            'original_function_class_definitions':sum(len(composition.inventory_file(i)['definitions']) for i in range(composition.inventory_file_count)),
            'original_denominators_unreplayed':selection['original_denominators'],
            'summary':result.summary(),'sourceprogram':artifact,'ordinary_readback':'PASSED',
            'strict_reader_negatives':negative,'validation':validation,'activity':activity,
            'code_witness_counts':store.counts,'producer_guard_bytes_per_pass':guard_bytes,
            'output_and_owned_readback_bytes':output_bytes,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'elapsed_s':time.monotonic()-start,'runtime_namespace_bound':False,'published':False,
            'entry_graph_regions':len(result.graph.regions),'body_statement_lowerings':0,'whole_body_complete':False,'whole_program_complete':False,'source_runtime_unchanged':True,
            'production_sources':freeze['production_sources']}
        save('worker-result.json',report);completed=True;event('FINISHED',status=report['status'])
        return 0
    except BaseException as error:
        save('failure.json',{'phase':phase,'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),
            'actual_module_lowerings':lowerings,'elapsed_s':time.monotonic()-start,
            'activity':guard.receipt() if guard else None,'code_witness_counts':store.counts if store else None})
        event('FAILED',error=str(error));return 1
    finally:
        stop.set();signal.setitimer(signal.ITIMER_REAL,0);progress.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--read-inputs',action='store_true');parser.add_argument('--worker',action='store_true');parser.add_argument('--approved-freeze-sha256');args=parser.parse_args()
    if not args.read_inputs and not args.worker:
        print('NOT_RUN: root must supply --read-inputs --approved-freeze-sha256 SHA');return 0
    if not args.approved_freeze_sha256:raise ValueError('root-approved freeze SHA required')
    if args.worker:return worker(args.approved_freeze_sha256)
    f=json.loads((BASE/'freeze.json').read_bytes())
    if digest((BASE/'freeze.json').read_bytes())!=args.approved_freeze_sha256 or Path(f['attempt'])!=BASE/'attempt01':raise ValueError('approved attempt/freeze differs')
    attempt=Path(f['attempt']);attempt.mkdir(exist_ok=False)
    start=time.monotonic()
    command=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-freeze-sha256',args.approved_freeze_sha256]
    try:
        with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
            proc=subprocess.run(command,stdout=out,stderr=err,timeout=240,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)})
        code=proc.returncode
    except subprocess.TimeoutExpired:code=124
    report={'schema':'scar.module-mapping-entry-window-result','schema_version':1,'actual_worker_exit_code':code,
            'elapsed_s':time.monotonic()-start,'attempt':str(attempt),'freeze_sha256':args.approved_freeze_sha256,
            'status':'FINISHED_WITH_OPEN' if code==0 else 'FAILED_PRESERVED','whole_program_complete':False}
    with (attempt/'result.json').open('xb') as stream:stream.write(raw(report))
    return code
if __name__=='__main__':raise SystemExit(main())

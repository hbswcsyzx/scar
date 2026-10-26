"""Two existing real LeWM bodies through the production storage adapter; no lowering."""
from pathlib import Path
import gzip,hashlib,json,resource,shutil,subprocess,sys,time,traceback,os
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,_EntryProgramArchive
from scar.store.source_fragments import SourceContextSession
from scar.ir.record_codec import decode
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'source_body_fragments_20261026'
started=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
try:
    originals=json.loads((OLD/'attempt03/result.json').read_text())['originals']
    texts=json.loads((OLD/'SOURCE_TEXT_RECEIPT.json').read_text())
    text=(OLD/'source-text-world.py').read_text()
    assert hashlib.sha256(text.encode()).hexdigest()==texts['sha256']
    worker=ROOT/'attempt01/worker';worker.mkdir(parents=True)
    archive=_EntryProgramArchive(worker/'source-fragments',SourceFrontendBudget(
        max_dispatch_bodies=2,max_source_files=1,max_operations_per_body=4000,max_record_bytes=64_000_000,
        max_output_bytes=128_000_000,max_elapsed_seconds=180))
    refs=[];copy_stored=0
    for index,original in enumerate(originals,1):
        a=original['artifact'];original_path=Path(a['uri'])
        folder=worker/f'attempt-{index:05d}';folder.mkdir();fresh=folder/'source-program5.json.gz'
        shutil.copyfile(original_path,fresh);assert sha(fresh)==a['sha256']
        copy_stored+=fresh.stat().st_size
        ref={'uri':str(fresh),'external':True,'representation':'scar.source-program/5',
             'physical_sha256':a['sha256'],'physical_bytes':a['size_bytes'],
             'decoded_sha256':original['decoded_sha256'],'decoded_bytes':original['decoded_bytes']}
        refs.append(archive.publish(ref))
    archive_costs=archive.finish(retire_fresh_originals=True)
    assert all(not (worker/f'attempt-{i:05d}/source-program5.json.gz').exists() for i in (1,2))
    bodies=[];locators=[]
    for ref in refs:
        locators.append(SourceArtifactLocator(ProviderArtifact(ref['uri'],ref['physical_sha256'],ref['physical_bytes'],ref['representation']),
            ref['decoded_sha256'],ref['decoded_bytes'],'gzip-canonical-json'))
    with SourceContextSession(source_texts={texts['logical_source_path']:text}) as session:
        for locator in locators:
            body=session.read(locator,namespace_root='/home/zyf/AAA/le-wm/stable-worldmodel')
            bodies.append({'operations':len(body.body.graph.operations),'context':body.context.payload.artifact.uri,
                'snapshot':body.body.metadata.source.path,'original':body.original.artifact.uri,'fragment':body.artifact.artifact.uri})
        session_costs=session.finish()
    assert [b['operations'] for b in bodies]==[85,217] and len({b['context'] for b in bodies})==1
    query_code='''from scar.analysis.program_region_view import read_source_region
import json,sys
v=read_source_region(sys.argv[1],expected_sha256=sys.argv[2])
print(json.dumps({'core_validated':v['core_validated'],'source_context_replayed':v['source_context_replayed'],
'context_reference_verified':v['context_reference_verified'],'source':v['source']}))
'''
    queries=[]
    for ref in refs:
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='/home/zyf/AAA/scar-worktrees/structured-program-model')
        done=subprocess.run([sys.executable,'-B','-c',query_code,ref['uri'],ref['physical_sha256']],env=env,text=True,capture_output=True)
        assert done.returncode==0,done.stderr
        queries.append(json.loads(done.stdout))
    assert all(q['core_validated'] and not q['source_context_replayed'] and not q['context_reference_verified'] for q in queries)
    assert all(Path(o['artifact']['uri']).is_file() and sha(Path(o['artifact']['uri']))==o['artifact']['sha256'] for o in originals)
    outputs=list((worker/'source-fragments').rglob('*.json.gz'))
    result={'status':'PASS_REAL_TWO_BODY_PRODUCTION_STORAGE_ADAPTER_AND_NORMAL_READBACK',
        'new_source_lower':0,'new_target_exec':0,'original_inputs_unchanged':True,'legacy_sp5_default_changed':False,
        'bodies':bodies,'fragment_references':refs,'stored_contexts':len(list((worker/'source-fragments/contexts').glob('*.gz'))),
        'stored_bodies':len(list((worker/'source-fragments/bodies').glob('*.gz'))),
        'original_stored_bytes':sum(o['artifact']['size_bytes'] for o in originals),
        'original_decoded_bytes':sum(o['decoded_bytes'] for o in originals),
        'shared_stored_bytes':sum(p.stat().st_size for p in outputs),
        'shared_decoded_bytes':sum(len(gzip.decompress(p.read_bytes())) for p in outputs),
        'temporary_sp5_copy_read_and_write_bytes_each':copy_stored,'archive_costs':archive_costs,'session_costs':session_costs,
        'region_queries':queries,'elapsed_seconds':time.monotonic()-started,'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'qualification':'Existing archive/structure source transport only. No new lowering, live owner, CP2 admission, state or runtime proof.',
        'production_worker_shared_branch_actual_lower_exercised':False,
        'source_sha256':{name:sha(Path(name)) for name in ('scar/analysis/source_frontend_worklist.py','scar/analysis/source_entry_run.py','scar/store/source_fragments.py')}}
    (ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
except BaseException as error:
    (ROOT/'failure.json').write_text(json.dumps({'type':type(error).__name__,'error':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started},indent=2)+'\n');raise

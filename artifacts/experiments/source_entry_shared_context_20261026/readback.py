"""Read the two already-published fragments; no publisher/lowerer rerun."""
from pathlib import Path
import gzip,hashlib,json,resource,subprocess,sys,time,os
from scar.store.source_fragments import SourceContextSession
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'source_body_fragments_20261026';start=time.monotonic()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
source=json.loads((OLD/'SOURCE_TEXT_RECEIPT.json').read_text());text=Path(source['retained_utf8']).read_text()
assert hashlib.sha256(text.encode()).hexdigest()==source['sha256']
rows=[]
for path in (ROOT/'attempt01/worker/source-fragments/bodies').glob('*.gz'):
    raw=gzip.decompress(path.read_bytes());doc=json.loads(raw)
    rows.append((doc['original']['artifact']['uri'],path,raw,doc))
rows.sort()
assert len(rows)==2
bodies=[]
with SourceContextSession(source_texts={source['logical_source_path']:text}) as session:
    for original,path,raw,doc in rows:
        locator=SourceArtifactLocator(ProviderArtifact(str(path),sha(path),path.stat().st_size,'scar.source-body-fragment/1'),
            hashlib.sha256(raw).hexdigest(),len(raw),'gzip-canonical-json')
        namespace=doc['context']['context']['namespace_root']
        fragment=session.read(locator,namespace_root=namespace)
        bodies.append({'operations':len(fragment.body.graph.operations),'namespace_root':namespace,
            'fragment':str(path),'stored_sha256':sha(path),'context':fragment.context.payload.artifact.uri,
            'original_receipt':doc['original'],'original_copy_retired':not Path(original).exists()})
    costs=session.finish()
assert [b['operations'] for b in bodies]==[85,217] and len({b['context'] for b in bodies})==1
code='''from scar.analysis.program_region_view import read_source_region
import json,sys
v=read_source_region(sys.argv[1],expected_sha256=sys.argv[2])
print(json.dumps({k:v[k] for k in ('core_validated','source_context_replayed','context_reference_verified','source')}))
'''
queries=[]
for body in bodies:
    done=subprocess.run([sys.executable,'-B','-c',code,body['fragment'],body['stored_sha256']],env=dict(os.environ,
        PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='/home/zyf/AAA/scar-worktrees/structured-program-model'),capture_output=True,text=True)
    assert done.returncode==0,done.stderr
    queries.append(json.loads(done.stdout))
assert all(q['core_validated'] and not q['source_context_replayed'] and not q['context_reference_verified'] for q in queries)
originals=json.loads((OLD/'attempt03/result.json').read_text())['originals']
assert all(sha(Path(o['artifact']['uri']))==o['artifact']['sha256'] for o in originals)
outputs=list((ROOT/'attempt01/worker/source-fragments').rglob('*.gz'))
result={'status':'PASS_TWO_EXISTING_REAL_BODY_PRODUCTION_STORAGE_ADAPTER_AND_NORMAL_READBACK',
    'body_operations':[b['operations'] for b in bodies],'bodies':bodies,
    'stored_contexts':len({b['context'] for b in bodies}),'stored_bodies':len(bodies),
    'original_stored_bytes':sum(o['artifact']['size_bytes'] for o in originals),
    'original_decoded_bytes':sum(o['decoded_bytes'] for o in originals),
    'shared_stored_bytes':sum(p.stat().st_size for p in outputs),
    'shared_decoded_bytes':sum(len(gzip.decompress(p.read_bytes())) for p in outputs),
    'session_costs':costs,'region_queries':queries,'elapsed_seconds':time.monotonic()-start,
    'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'new_source_lower':0,'new_target_exec':0,'original_inputs_unchanged':True,'old_failure_preserved':'failure.json',
    'actual_publisher_cost_counters':'not persisted before the initial harness namespace error; output bytes measured in this readback',
    'production_worker_lower_branch_exercised':False,
    'qualification':'same production archive helper; normal source-context/body reader and core-only region queries. No new source/runtime/CP2 qualification.'}
(ROOT/'readback-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

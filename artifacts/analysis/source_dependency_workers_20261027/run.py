"""The sole normal four-worker consumption of the closed 512-candidate batch."""
import hashlib,json,os,resource,sys,time,traceback
from pathlib import Path
from scar.analysis.source_dependency_workers import build_source_dependency_workers
from scar.analysis.source_return_bindings import SourceReturnBudget

BASE=Path(__file__).resolve().parent
MANIFEST=Path('/home/zyf/AAA/scar-worktrees/retained-call-session/artifacts/analysis/source_call_port_session_20261027/publication/manifest.json')
EXPECTED='118a189761ddefe33d03b548e5ba8c699a1c3fe35baa34f82832ff6519b50c36'

def main():
 from scar.analysis.retained_source_call_publication import read_retained_source_call_publication
 publication=read_retained_source_call_publication(MANIFEST,expected_manifest_sha256=EXPECTED)
 bodies={ns['artifact']['uri']for ref in publication.shard_refs for ns in ref.namespace_refs}
 parent_pid=os.getpid();observed={'parent_body_open_attempts':[],'parent_raw_open_attempts':[],'target_exec':0,'capture':0}
 def audit(event,args):
  if event=='open'and args and isinstance(args[0],(str,bytes,os.PathLike)):
   path=os.fsdecode(args[0]);name=Path(path).name
   if os.getpid()==parent_pid and path in bodies:
    observed['parent_body_open_attempts'].append(path)
    raise AssertionError('parent cannot read body graph: '+path)
   if name.startswith(('call-edges.','call-operands.','python-call-targets.','syscalls.')):
    observed['parent_raw_open_attempts'].append(path)
    raise AssertionError('raw producer replay forbidden: '+path)
  if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
   observed['target_exec']+=1
   raise AssertionError('target execution forbidden')
 sys.addaudithook(audit)
 start=time.monotonic();result={}
 try:
  report=build_source_dependency_workers(MANIFEST,BASE/'attempt01'/'views',expected_manifest_sha256=EXPECTED,
   max_workers=4,max_inflight=8,return_budget=SourceReturnBudget(max_bodies=64),max_bindings=32,
   max_queries=256,max_nodes=128,max_depth=32,max_routes=512,
   max_total_output_bytes=1000000000,progress=lambda row:print(json.dumps(row,sort_keys=True),flush=True))
  accepted=[i for row in report['shards']for i in row['candidate_scope']['accepted_attempt_indices']]
  missing=[i for row in report['shards']for i in row['candidate_scope']['missing_attempt_indices']]
  assert len(accepted)==len(set(accepted))==449 and len(missing)==len(set(missing))==63
  assert set(accepted).isdisjoint(missing)
  assert len(report['shards'])==15 and report['publication_totals']['direct_candidate_pairs_examined']==512
  assert report['candidate_scope']['remaining_direct_candidates_total']==2171
  assert report['status']=='QUERIED_WITH_OPEN'
  assert 1 <= len(report['worker_pids']) <= 4 and parent_pid not in report['worker_pids']
  assert not observed['parent_body_open_attempts']and not observed['parent_raw_open_attempts']and observed['target_exec']==0
  result={'status':'PASS','index':report['index'],'worker_pids':report['worker_pids'],
   'configured_workers':4,'actual_worker_process_count':len(report['worker_pids']),
   'shards':len(report['shards']),'query_count':sum(r['query_count']for r in report['shards']),
   'truncated_query_shards':[r['shard_index']for r in report['shards']if r['query_truncated']],
   'accepted_attempts':len(accepted),'missing_attempts':len(missing),'remaining_direct_candidates':2171,
   'reader_costs':{k:sum(r['body_query_costs'][k]for r in report['shards'])for k in ('stored_bytes','decoded_bytes','body_codec_reads','body_index_builds')},
   'output_stored_bytes_before_index':report['output_stored_bytes_before_index'],
   'total_output_bytes':sum(p.stat().st_size for p in (BASE/'attempt01'/'views').rglob('*')if p.is_file()),
   'parent_report_wall_seconds':report['wall_seconds'],'worker_wall_seconds':[r['wall_seconds']for r in report['shards']],
   'worker_peak_rss_kib':[r['process_peak_rss_kib']for r in report['shards']],
   'whole_program_complete':False,'runtime_occurrence_selected':False,'speedup_measured':False}
 except BaseException as error:
  result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
 finally:
  result.update(wall_seconds=time.monotonic()-start,parent_pid=parent_pid,parent_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
   audit=observed,manifest_path=str(MANIFEST),manifest_sha256=EXPECTED,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
   worker_source_sha256=hashlib.sha256(Path(sys.modules['scar.analysis.source_dependency_workers'].__file__).read_bytes()).hexdigest(),
   separate_metadata_preflight_bytes=MANIFEST.stat().st_size)
  (BASE/'attempt01'/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
  print(json.dumps(result,sort_keys=True,indent=2),flush=True)
  if result['status']!='PASS':sys.exit(1)

if __name__=='__main__':main()

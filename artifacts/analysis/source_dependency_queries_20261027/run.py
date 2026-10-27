"""Retry only original decoded-batch-cap failures, at unchanged byte ceilings."""
import hashlib,json,os,resource,sys,time,traceback
from pathlib import Path
from scar.analysis.source_dependency_workers import build_source_dependency_workers
from scar.analysis.source_return_bindings import SourceReturnBudget

BASE=Path(__file__).resolve().parent
ROOT=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
OLD=ROOT/'artifacts/analysis/source_dependencies_all_20261027/views/index.json'
MANIFEST=ROOT/'artifacts/analysis/source_call_port_all_20261027/publication/manifest.json'
EXPECTED='867a8fa08f97977ccf8aba2add85cd2544691f8aff1c61bcc685dc61160bfb8d'

def main():
 from scar.analysis.retained_source_call_publication import read_retained_source_call_publication
 old_bytes=OLD.read_bytes();old=json.loads(old_bytes)
 selected=tuple(r['shard_index']for r in old['shards']if r['status']=='FAILED_PARTIAL_RETAINED'
   and r.get('failure',{}).get('detail')=='source dependency workers: worker decoded view byte ceiling exceeded')
 assert len(selected)==24 and len(old['shards'])==84
 previous_success=tuple(r['shard_index']for r in old['shards']if r['status']=='QUERIED_WITH_OPEN')
 assert len(previous_success)==60 and set(selected).isdisjoint(previous_success)
 publication=read_retained_source_call_publication(MANIFEST,expected_manifest_sha256=EXPECTED)
 bodies={ns['artifact']['uri']for ref in publication.shard_refs for ns in ref.namespace_refs}
 parent=os.getpid();audit_counts={'parent_body_open_attempts':[],'raw_open_attempts':[],'target_exec':0,'capture':0}
 def audit(event,args):
  if event=='open'and args and isinstance(args[0],(str,bytes,os.PathLike)):
   path=os.fsdecode(args[0]);name=Path(path).name
   if os.getpid()==parent and path in bodies:
    audit_counts['parent_body_open_attempts'].append(path);raise AssertionError('parent cannot read a graph')
   if name.startswith(('call-edges.','call-operands.','python-call-targets.','syscalls.')):
    audit_counts['raw_open_attempts'].append(path);raise AssertionError('raw producer replay forbidden')
  if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
   audit_counts['target_exec']+=1;raise AssertionError('target execution forbidden')
 sys.addaudithook(audit)
 start=time.monotonic();result={}
 try:
  report=build_source_dependency_workers(MANIFEST,BASE/'attempt01'/'views',expected_manifest_sha256=EXPECTED,
   max_workers=4,max_inflight=8,return_budget=SourceReturnBudget(**old['return_budget']),
   **old['query_limits'],max_view_decoded_bytes=old['max_view_decoded_bytes'],
   max_view_stored_bytes=old['max_view_stored_bytes'],max_total_output_bytes=old['max_total_output_bytes'],
   view_layout='queries',shard_indices=selected,
   progress=lambda row:print(json.dumps(row,sort_keys=True),flush=True))
  assert tuple(report['selected_shard_indices'])==selected
  assert len(report['shards'])==24 and len(report['unselected_shards'])==60
  assert {r['shard_index']for r in report['unselected_shards']}==set(previous_success)
  assert all(r['output_stored_bytes']<=64000000 for r in report['shards'])
  failures=[r for r in report['shards']if r['status']!='QUERIED_WITH_OPEN']
  accepted=sum(len(r['candidate_scope']['accepted_attempt_indices'])for r in report['shards'])
  missing=sum(len(r['candidate_scope']['missing_attempt_indices'])for r in report['shards'])
  assert report['publication_totals']['direct_candidate_pairs_examined']==2683
  assert report['publication_totals']['selected_calls']==2672
  assert not report['all_publication_shards_selected']
  assert OLD.read_bytes()==old_bytes
  assert not audit_counts['parent_body_open_attempts']and not audit_counts['raw_open_attempts']and audit_counts['target_exec']==0
  result={'status':'PASS'if not failures else 'PARTIAL_WITH_OPEN','index':report['index'],
   'selected_shard_indices':list(selected),'unselected_success_shards':list(previous_success),
   'failures':[{'shard_index':r['shard_index'],'failure':r.get('failure')}for r in failures],
   'worker_pids':report['worker_pids'],'selected_accepted_attempts':accepted,'selected_missing_attempts':missing,
   'selected_queries':sum(r.get('query_count',0)for r in report['shards']),
   'truncated_query_shards':[r['shard_index']for r in report['shards']if r.get('query_truncated')],
   'query_payload_stored_bytes':sum(r.get('output',{}).get('query_payload_stored_bytes',0)for r in report['shards']),
   'query_payload_decoded_bytes':sum(r.get('output',{}).get('query_payload_decoded_bytes',0)for r in report['shards']),
   'output_stored_bytes_before_index':report['output_stored_bytes_before_index'],
   'total_output_bytes':sum(p.stat().st_size for p in (BASE/'attempt01'/'views').rglob('*')if p.is_file()),
   'reader_costs':{key:sum(r.get('body_query_costs',{}).get(key,0)for r in report['shards'])for key in ('stored_bytes','decoded_bytes','body_codec_reads','body_index_builds')},
   'largest_shard_stored_bytes':max(r['output_stored_bytes']for r in report['shards']),
   'worker_peak_rss_kib':[r.get('process_peak_rss_kib')for r in report['shards']],
   'parent_builder_wall_seconds':report['wall_seconds'],'publication_totals':report['publication_totals'],
   'capture_denominators':report['capture_denominators'],'whole_program_complete':False,'speedup_measured':False}
 except BaseException as error:
  result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
 finally:
  result.update(wall_seconds=time.monotonic()-start,parent_pid=parent,
   parent_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,audit=audit_counts,
   old_index={'uri':str(OLD),'bytes':len(old_bytes),'sha256':hashlib.sha256(old_bytes).hexdigest()},
   manifest_path=str(MANIFEST),manifest_sha256=EXPECTED,
   worker_source_sha256=hashlib.sha256(Path(sys.modules['scar.analysis.source_dependency_workers'].__file__).read_bytes()).hexdigest())
  (BASE/'attempt01'/'RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
  print(json.dumps(result,sort_keys=True,indent=2),flush=True)
  if result['status']!='PASS':sys.exit(1)

if __name__=='__main__':main()

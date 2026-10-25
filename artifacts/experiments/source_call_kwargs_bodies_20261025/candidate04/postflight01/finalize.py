"""Independent postflight only; no old audit hook, lowerer, codecs or root streams."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[3]
APPROVED='26b44d86b573624269b068d20d02e131a7b9237174fd467a307635422c976297'

def raw(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def small(path,limit=1_000_000):
    if path.is_symlink() or path.stat().st_size>limit:raise ValueError('small metadata bound: '+str(path))
    b=path.read_bytes();return json.loads(b),{'path':str(path),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def stored(path):
    if path.is_symlink():raise ValueError('stored artifact symlink')
    h=hashlib.sha256();n=0
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b);n+=len(b)
    return {'path':str(path),'bytes':n,'sha256':h.hexdigest()}

started=time.monotonic()
# Loading the approved runner by runpy does not invoke main/worker or install
# GateGuards; verify_freeze hashes only its fixed small tools/352 sources and
# stats27 retained inputs. No77MB JSON or context is opened.
runner=runpy.run_path(str(BASE/'run_gate.py'),run_name='independent_postflight_only')
freeze,guard_bytes=runner['verify_freeze'](APPROVED)
if len(freeze['inputs'])!=27 or len(freeze['candidate_scar_sources'])!=352:raise ValueError('approved frozen scope differs')
attempt=BASE/'attempt04'
launch,launch_ref=small(attempt/'launch-result.json')
failure,failure_ref=small(attempt/'failure.json')
progress_path=attempt/'progress.jsonl'
if progress_path.stat().st_size>1_000_000:raise ValueError('progress bound')
events=[json.loads(line) for line in progress_path.read_text().splitlines()]
if launch['exit_code']!=1 or failure['exception']!='PermissionError' or failure['message']!='unfrozen isolated retained artifact read':raise ValueError('original terminal is not the reviewed tool failure')
if 'verify_freeze' not in failure['traceback'] or "BASE/'freeze.json'" not in failure['traceback']:raise ValueError('failure did not occur at self-freeze final check')
if events[-1]['event']!='FAILED' or events[-2]['phase']!='FINAL_SOURCE_AND_INPUT_CHECK':raise ValueError('last phase differs')
counts=failure['guard']['counts'];limits=freeze['limits']
if counts['actual_input_bytes']!=counts['stored_bytes']+counts['decoded_bytes'] or counts['actual_input_bytes']!=events[-1]['actual_retained_input_bytes'] or counts['actual_input_bytes']>limits['total_input_bytes']:raise ValueError('actual input budget/counters differ')
if events[-1]['output_accounted_bytes']>limits['total_output_bytes'] or failure['wall_seconds']>limits['worker_seconds'] or launch['wall_seconds']>limits['outer_seconds']:raise ValueError('original wall/output budget exceeded')
for key in ('target_executable_compile_attempts','target_exec_attempts','source_prepare_attempts'):
    if counts[key]!=0:raise ValueError('actual activity guard nonzero: '+key)
wc=failure['code_witness_activity']
if wc['compile_attempts'] or wc['source_bytes_read']:raise ValueError('owned witness compile/source preparation counter nonzero')
results=[];artifact_receipts=[]
for ordinal,expected_seq in ((1,10),(2,12)):
    path=attempt/f'body-{ordinal:02d}-result.json';result,result_ref=small(path)
    matching=[r for r in failure['completed_results'] if r['original_sequence']==expected_seq]
    if len(matching)!=1 or result!=matching[0] or path.read_bytes()!=raw(result):raise ValueError('body result differs from retained terminal machine result')
    if result['status']!='RECOVERED_WITH_OPEN':raise ValueError('returned body status differs')
    artifact=result['artifact'];actual=stored(Path(artifact['path']))
    if actual!={k:artifact[k] for k in ('path','bytes','sha256')}:raise ValueError('stored program SHA/bytes differs')
    c=result['checks'];v=c['independent_source_and_compiler'];pending=c['local_call_pending']
    if not c['public_structure']['roundtrip_equal'] or not v['source_shape_verified'] or not v['code_constant_provenance_verified'] or pending['calls']!=1:raise ValueError('stored finite qualification differs')
    if any(not r['source_code_verified'] or not r['pending']['call_owned_pending_checked'] for r in pending['records']):raise ValueError('local pending/source checks absent')
    if c['call_cleanup_contract_verified'] or c['outer_prefix_verified'] or result['whole_lifetime_verified']:raise ValueError('unproved full qualification was upgraded')
    end=[e for e in events if e['event']=='BODY_END' and e['body']==ordinal]
    if len(end)!=1 or end[0]['operations_emitted']!=result['operations_emitted']:raise ValueError('body phase/emitted counter differs')
    results.append(result);artifact_receipts.append({'subject_sequence':expected_seq,'body_result':result_ref,'stored_program':actual,'program_decoded_replayed_in_postflight':False})
if failure['body_lowerings_started']!=2 or failure['known_returned_operations']!=sum(r['operations_emitted'] for r in results):raise ValueError('new lower/cost counts differ')
selection,selection_ref=small(BASE/'selection.json')
aggregate=failure['aggregate_scope']
if aggregate['scope_subject_count']!=4 or len(aggregate['subjects'])!=4:raise ValueError('four independent subjects lost')
prior=selection['prior_outcomes']
first=prior['4']['result'];second=prior['5']['result']
if first['status']!='REUSED_REVALIDATED_WITH_OPEN' or first['reused_graph_operations']!=92 or second['status']!='UNSUPPORTED' or second['operations_emitted']!=350 or second['artifact'] is not None:raise ValueError('prior retained outcomes changed')
finite=[{'sequence':4,'operations':92,'provenance':'candidate02 artifact + candidate03 independent result','evidence':prior['4']['evidence'],'program':first['artifact'],'qualification_reused_from_exact_prior_receipt':True}]
finite.extend({'sequence':r['original_sequence'],'operations':r['operations_emitted'],'provenance':'candidate04 stored graph + per-body independent checks','program':r['artifact'],'qualification_reused_from_exact_prior_receipt':True} for r in results)
main=Path('/home/zyf/AAA/scar-worktrees/structured-program-model');diffs=[]
for r in freeze['production_sources']:
    relative=r['relative_path'];target=main/relative
    expected=r.get('reviewed_main_source_baseline',r.get('previous_source'))
    if not target.exists():
        state='NEW_FILE' if r['change']=='NEW' else 'MISSING_EXPECTED_MAIN';current=None
    else:
        current=stored(target)
        if current['sha256']==r['sha256']:state='ALREADY_IDENTICAL'
        elif expected is not None and current['sha256']==expected['sha256']:state='BASELINE_MATCH_NARROW_DIFF'
        else:state='MAIN_DIVERGED_REVIEW_REQUIRED'
    diffs.append({'relative_path':relative,'source_sha256':r['sha256'],'main':current,'state':state,'reviewed_baseline':expected})
value={'schema':'scar.kwargs-independent-postflight','schema_version':1,'postflight':{'exit_code':0,'method':'fresh process; approved verify_freeze small SHA/27stat; stored SHA only for2 graphs; machine receipt/last-phase reconciliation','elapsed_s':time.monotonic()-started,'source_tool_guard_bytes':guard_bytes,'frozen_source_count':352,'frozen_input_stats':27,'program_codec_or_decoded_graph_replays':0,'composition_root_stream_reads':0,'body_lowerings':0,'target_executions':0,'file':stored(Path(__file__).resolve())},
       'original_window':{'exit_code':launch['exit_code'],'status':launch['status'],'wall_seconds':launch['wall_seconds'],'failure_type':failure['exception'],'reason':'own approved freeze.json reread omitted from tool allowlist at final verification; independent postflight repairs only that missing check','launch':launch_ref,'failure':failure_ref,'unchanged':True},
       'approved_freeze':APPROVED,'production_sources':freeze['production_sources'],'stored_artifact_checks':artifact_receipts,
       'restored_original_machine_counters':{'guard':counts,'witness':wc,'worker_wall_seconds':failure['wall_seconds'],'launcher_wall_seconds':launch['wall_seconds'],'self_peak_rss_kib':failure['self_peak_rss_kib'],'last_phase':events[-2],'output_before_final_failure':events[-1]['output_accounted_bytes']},
       'finite_artifacts':finite,'seq5':{'sequence':5,'construction_operations':350,'body_status':'UNSUPPORTED_OPEN','last_frontier':second['gaps'][-1],'program':None,'evidence':prior['5']['evidence']},
       'full_scope_subjects':selection['scope_subjects'],'full_scope_subject_count':4,'whole_program_established':False,
       'unwind_verified':False,'outer_prefix_verified':False,'runtime_instance_verified':False,'world_effects_verified':False,
       'main_source_differences':diffs,'main_writes':0,'git_operations':0,'stored_graphs_retained_locally_not_staged':True}
with (HERE/'receipt.json').open('x') as out:json.dump(value,out,ensure_ascii=False,sort_keys=True,indent=2);out.write('\n')
print(json.dumps({'original_exit':1,'postflight_exit':0,'finite_ops':[92,85,217],'seq5':'350 construction / JoinedStr / no graph / OPEN','main_differences':[(r['relative_path'],r['state']) for r in diffs],'receipt_sha256':stored(HERE/'receipt.json')['sha256'],'elapsed_s':value['postflight']['elapsed_s']},sort_keys=True))

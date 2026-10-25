"""Metadata-only terminal freeze; reuse closed artifact SHA, hash missing receipts once."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
import time
B=Path(__file__).resolve().parents[3]
O=Path(__file__).resolve().parent
R=O/'result'
START=time.monotonic();io=Counter();declared={};metadata=[]
def read(p):
 raw=p.read_bytes();io['metadata_read_bytes']+=len(raw);return raw
def file_row(p):
 h=sha256();n=0
 with p.open('rb') as f:
  while raw:=f.read(1024*1024):h.update(raw);n+=len(raw)
 io['streamed_sha_bytes']+=n
 return {'path':str(p.relative_to(B)),'bytes':n,'sha256':h.hexdigest()}
def add_artifacts(value,origin):
 if type(value) is dict:
  if {'uri','sha256','size_bytes'}<=value.keys():
   p=Path(value['uri'])
   if p.is_relative_to(R):
    item={'path':str(p.relative_to(B)),'bytes':value['size_bytes'],'sha256':value['sha256']}
    previous=declared.get(p)
    assert previous is None or {k:previous[k] for k in item}==item,p
    if previous is None:declared[p]={**item,'declared_by':origin}
  for v in value.values():add_artifacts(v,origin)
 elif type(value) is list:
  for v in value:add_artifacts(v,origin)
S=json.loads(read(O/'summary.json'));report=S['batch_report'];N=json.loads(read(O/'negative-checks.json'))
assert S['status']=='PASS_V2_SOURCE_ACCOUNTING_WITH_EXPLICIT_PORT_GAPS'
assert report['source_domain_complete'] and report['structurally_modeled_dispatches']==report['declared_dispatch_attempts']==39796
assert report['unmodeled_frontier_dispatches']==0 and len(report['shards'])==156
assert N['failure_kind']=='NativePortOrderError' and not N['old_scope_hash_rejection_used'] and N['generic_execution_issues']==0
assert len(N['native_only_and_producer_cases'])==9 and all(c['rejected'] and c['failure_kind']=='NativePortOrderError' for c in N['native_only_and_producer_cases'].values())
F=json.loads(read(O/'freeze.json'));pins=F['dependencies']+F['runner_files']+F['read_only_metadata']
for r in pins:
 p=B/r['path'];raw=read(p);assert len(raw)==r['bytes'] and sha256(raw).hexdigest()==r['sha256'],p
assert set(S['actual_imported_SCAR_sources'])<={r['path'] for r in F['dependencies']}
assert not set(S['actual_imported_SCAR_sources'])&set(F['excluded_unrelated_modules'])
add_artifacts(report,'result/report.json via summary.batch_report')
rootraw=read(R/'report.json');assert json.loads(rootraw)==report
seqs=[];totals=Counter();gaps=Counter()
for sh in report['shards']:
 d=Path(sh['execution']['uri']).parent
 raw=read(d/'report.json');assert json.loads(raw)==sh
 validation=json.loads(read(d/'validation.json'));assert validation['valid'] and not validation['issues']
 seqs.extend(sh['sequences'])
 for k in ['actual_activations','native_tensor_ports','held_object_ports','unresolved_object_ports','geometry_qualified_ports','geometry_gap_ports']:totals[k]+=sh[k]
 gaps.update(sh['gap_counts'])
 assert sh['program_snapshot']['artifact']==report['shared_program']
assert seqs==report['actual_sequence_ids'] and len(seqs)==len(set(seqs))==39796
for k in ['native_tensor_ports','held_object_ports','unresolved_object_ports','geometry_qualified_ports','geometry_gap_ports']:assert totals[k]==report[k]
# Only bounded manifests are parsed; qualification/inventory data are not reread.
for p,item in list(declared.items()):
 if p.name=='manifest.json':
  raw=read(p);assert len(raw)==item['bytes'] and sha256(raw).hexdigest()==item['sha256'],p
  doc=json.loads(raw);assert doc['max_chunk_rows']<=1000 and doc['max_chunk_bytes']<=8000000
  assert sum(c['rows'] for c in doc['chunks'])==doc['rows']
  add_artifacts(doc,str(p.relative_to(B)))
public=[];unreferenced_large=[]
for p in sorted(R.rglob('*')):
 if not p.is_file() or 'private' in p.relative_to(R).parts:continue
 if p in declared:
  item=declared[p];assert p.stat().st_size==item['bytes'],p
  public.append({**item,'sha256_basis':('terminal bounded-manifest SHA verified against closed actual-gate artifact receipt' if p.name=='manifest.json' else 'closed actual-gate artifact receipt; current size checked; payload not reread')})
 else:
  if p.stat().st_size>1000000:
   assert p.name in ('source-projection-receipts.json','report.json'),p
   if p.name=='source-projection-receipts.json':unreferenced_large.append(str(p.relative_to(B)))
  public.append({**file_row(p),'sha256_basis':'terminal streaming SHA; no codec or large JSON parse'})
assert len(public)==len({x['path'] for x in public})
private=R/'private/navigation.sqlite';stat=private.stat()
manifest={'status':'ACTUAL_EXIT0_COMPLETE_PUBLIC_OUTPUT_SHA_INVENTORY','files':public,'files_count':len(public),'bytes':sum(x['bytes'] for x in public),
 'sha_reuse_scope':'References retain exact actual-gate artifact provenance. Reused payloads received current byte-size checks only; no independent new SHA pass is claimed.',
 'unreferenced_large_receipts_hashed_once':unreferenced_large,'private_diagnostic_only':{'path':str(private.relative_to(B)),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,'sha256':None,'read':False,'ownership_restorable':False},
 'terminal_review_io':dict(io),'original_raw_reads':0,'archive_chunk_reads':0,'private_index_reads':0,'semantic_codec_calls':0}
(O/'terminal-output-inventory.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
negative={'fresh_order':{'failure_kind':N['failure_kind'],'generic_issues':N['generic_execution_issues'],'old_scope_hash_rejection_used':False,
 'own_snapshot_sha256':N['own_program_snapshot_sha256'],'order_error_counts':dict(Counter(e[0] for e in N['order_errors']))},
 'dynamic_cases':{k:{x:c[x] for x in ['rejected','failure_kind','generic_issue_count']} for k,c in N['native_only_and_producer_cases'].items()},
 'legacy_gap_retained':N['legacy_gap_retained'],'wrong_run_rejected':N['wrong_run_rejected']}
terminal={'status':'ACTUAL_EXIT0_SOURCE_ACCOUNTING_NATIVE_PORTS_PASS_MODEL_OPEN','root_session':38088,'actual_exit':0,
 'actual_exit_source':'root-owned session38088 terminal confirmation and GNU time exit0','summary_seconds':S['wall_seconds'],'gnu_whole_seconds':1721.75,'batch_seconds':report['wall_seconds'],'max_rss_kib':S['max_rss_kib'],
 'declared_dispatch_attempts':39796,'actual_dispatch_groups':39796,'modeled_dispatches':39796,'frontier_dispatches':0,'static_interfaces':127,'execution_shards':156,
 'B_complete_dispatches':report['modeled_complete_reference_dispatches'],'B_partial_dispatches':report['modeled_partial_reference_dispatches'],
 'native_tensor_ports':report['native_tensor_ports'],'B_held_ports':report['held_object_ports'],'B_unresolved_ports':report['unresolved_object_ports'],'C_qualified_ports':report['geometry_qualified_ports'],'C_gap_ports':report['geometry_gap_ports'],
 'qualified_shard_totals':dict(totals),'validation_gap_counts':dict(gaps),'critical_negatives':negative,
 'raw_receipts':report['raw_reads'],'archive_receipts':report['archive_reads'],'native_raw_bytes_once':report['native_raw_bytes_returned'],
 'shared_program':report['shared_program'],'shared_interface':report['shared_interface'],'dispatch_inventory':report['dispatch_inventory'],'observed_dispatch_inventory':report['observed_dispatch_inventory'],
 'source_raw_acquisitions':1,'coordinate_binds_inside_batch':0,'actual_imported_frozen_SCAR_sources':len(S['actual_imported_SCAR_sources']),
 'frozen_dependencies_match':269,'frozen_runners_match':2,'readonly_metadata_match':6,'published_bytes_before_report':report['published_bytes_before_report'],
 'private_index_bytes':stat.st_size,'whole_model_established':False,'logical_contents_established':False,'state_effects_established':False,'ready_established':False,'transformation_authorized':False,
 'observed_execution_instrumented':True,'target_observer_attribution_established':False,'clean_benchmark_established':False,'custom_implementation_code_identity_established':False,
 'target_executions':0,'fullgate_rerun_by_auditor':False,'terminal_review_original_raw_or_DB_reads':0,'output_inventory':file_row(O/'terminal-output-inventory.json'),
 'timing_interpretation':'1720.892597s summary vs1721.75s GNU whole vs1668.115264s batch; attempt02 interrupted duration is not a target speedup baseline'}
(O/'terminal-result.json').write_text(json.dumps(terminal,indent=2,sort_keys=True)+'\n')
(O/'RESULT.md').write_text(f'''# Attempt03 actual result

Root-owned session38088 completed **exit0**. Native source accounting and observed port modeling PASS; logical content/state/ready/full model remain **OPEN**. Whole summary1720.892597s, GNU whole1721.75s, batch1668.115264s; maxRSS1,091,472KiB. No budget was raised. Attempt02's root-interrupted duration is not a target-program speedup baseline.

All39,796 declared and actually enumerated dispatches modeled, frontier0,127 shared static interfaces and156 execution shards. B-complete calls37,895; B-partial calls1,901. Native Tensor ports111,189 =109,288 exact held-object identities +1,901 explicit Unknown identities. C geometry107,483 qualified +3,706 gaps; missing C did not erase B or authorize alias/ready. B/C remain dynamic per-port, outside the static signature. This is instrumented observed execution; observer versus target work, clean benchmarking and custom implementation CodeIdentity/effects remain unproved.

All3 raw source SHA/bytes/semantic scans and4 archive tables/95 chunks completed in one new owned acquisition; coordinates were bound once outside the batch and never rebound per shard. The final actual gate checked every transport inventory row and every per-port row, original sequence/locators, shared Snapshot and independent static/dynamic ABI/source joins. Fresh same-Run wrongprogram used the live first lease's prepared catalog, sealed its own candidate Snapshot, remained generic-valid, and raised NativePortOrderError with static and actual order errors rather than old scope-hash refusal. All9 same-program Unknown/producer modified candidates used the genuine prepared branch and rejected; known-to-Unknown, borrowed ObjectID, erased/misbound producer evidence and missing denotation stayed forbidden. V1/default APIs retained their earlier checks.

Terminal metadata audit rechecked all277 frozen source/runner/input-metadata pins,156 small shard reports/validation records and bounded manifests, plus frozen membership of154 actually imported SCAR files. No raw/archive chunk/private DB or semantic codec was reread/run. `terminal-output-inventory.json` lists every public output and SHA: existing closed artifact SHA reused with provenance/current-size checks; only unreferenced projection-receipt files were stream-hashed once, never parsed. This is not a claimed independent SHA re-read of4.337GB. The3,973,341,184-byte private SQLite stays local diagnostic data, stat-only and unable to restore owner.

`staging-paths-v2.txt` is the explicit <=1MB small delivery list, with stageable result/report/validation/manifests/receipts and all4 reviewed producers. Large program/projection/execution/qualification/inventory payloads and private DB remain local; their complete public output receipts are stageable. Earlier failed/stopped attempts, production/runner/freeze bytes and their receipts remain unchanged. Joint-recapture source/issuer/native-physical/OS field note is separate design-only work. No Git operation or further run was performed by this agent.
''')
print(json.dumps({'status':'TERMINAL_RESULT_AND_OUTPUT_SHA_INVENTORY_WRITTEN','public_files':len(public),'public_bytes':manifest['bytes'],'reuse_files':len(declared),'unreferenced_large_receipts':len(unreferenced_large),'terminal_review_io':dict(io),'seconds':time.monotonic()-START},indent=2),flush=True)

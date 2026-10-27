"""Declaration-only deterministic file batches; no owner, graph or CodeType loading."""
from collections import OrderedDict,Counter
import hashlib,json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)
def receipt(p):
 p=Path(p);raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,x):
 with(HERE/name).open('xb')as s:s.write(canonical(x)+b'\n')

def main():
 previous=json.loads((HERE/'result.json').read_bytes());data=json.loads((HERE/'remaining-ready.json').read_bytes())
 need(receipt(HERE/'remaining-ready.json')==previous['remaining_ready'],'original209 metadata changed')
 entries=data['entries'];need(len(entries)==209 and len({r['entry_key']for r in entries})==209,'remaining209 set differs')
 need(entries==sorted(entries,key=lambda r:(-r['calls'],r['entry_key'])),'original metadata call-weight priority differs')
 old={r['entry_key']:r for r in data['old_excluded']}
 need(len(old)==33 and Counter(r['status']for r in old.values())==Counter({'SUCCEEDED':26,'UNSUPPORTED':7}),'old33 classifications differ')
 manifests=[];source_records={}
 for ref in previous['original_archive_manifests']:
  need(receipt(ref['path'])==ref,'original archive manifest changed')
  doc=json.loads(Path(ref['path']).read_bytes());manifests.append(ref)
  for key,row in doc['sources'].items():
   identity=canonical(row['snapshot']);item={'normalized_bytes':row['artifact']['bytes'],'normalized_sha256':row['artifact']['sha256'],'archive_manifest':ref,'source_record_pointer':'#/sources/'+key}
   if identity in source_records:
    need(all(source_records[identity][f]==item[f]for f in ('normalized_bytes','normalized_sha256')),'conflicting same-snapshot declarations')
   else:source_records[identity]=item
 declarations={r['source_path']:r for r in data['source_graph_declarations']}
 grouped=OrderedDict()
 for ordinal,row in enumerate(entries):
  file_key=row['file_key'];snapshot=row['basis']['source_snapshot'];path=snapshot['path']
  if file_key not in grouped:
   need(path in declarations and canonical(snapshot)in source_records,'source metadata declaration absent')
   grouped[file_key]={'file_key':file_key,'source_snapshot':snapshot,'first_priority_rank':ordinal,
    'entry_keys':[],'historical_call_weight':0,'source_text':source_records[canonical(snapshot)],
    'source_graph':declarations[path]}
  item=grouped[file_key];need(item['source_snapshot']==snapshot,'one file_key names different snapshot')
  item['entry_keys'].append(row['entry_key']);item['historical_call_weight']+=row['calls']
 need(len(grouped)==99,'original99 remaining file groups differ')
 batches=[];frontiers=[];current=[]
 def summary(files):
  unique={(r['source_graph']['path'],r['source_graph']['declaration']['canonical_sha256']):r['source_graph']['declaration']for r in files}
  count=sum(len(r['entry_keys'])for r in files)
  sp5=sum(len(r['entry_keys'])*r['source_graph']['declaration']['canonical_bytes']for r in files)
  graphs=sum(d['canonical_bytes']for d in unique.values())
  return {'entry_keys':[key for r in files for key in r['entry_keys']],'entries':count,'files':len(files),
   'normalized_source_bytes_declared':sum(r['source_text']['normalized_bytes']for r in files),
   'unique_graph_stored_bytes_declared':sum(d['compressed_bytes']for d in unique.values()),
   'unique_graph_decoded_bytes_declared':graphs,'historical_call_weight':sum(r['historical_call_weight']for r in files),
   'SP5_context_records_proxy_all_success':count,'SP5_context_decoded_bytes_proxy_all_success':sp5,
   'SP5_repeated_context_bytes_proxy_beyond_unique':sp5-graphs}
 def finish():
  if current:batches.append({'batch':len(batches)+1,**summary(current),'file_groups':list(current)});current.clear()
 for item in grouped.values():
  d=item['source_graph']['declaration'];n=len(item['entry_keys'])
  reasons=[]
  if d['canonical_bytes']>300_000_000:reasons.append('SINGLE_FILE_GRAPH_DECODE_EXCEEDS_300MB')
  if n>64:reasons.append('SAME_FILE_ENTRIES_EXCEED_64_ENTRY_LIMIT')
  if reasons:
   frontiers.append({'frontiers':reasons,'file_group':item});continue
  proposed=summary(current+[item])
  if current and (proposed['files']>8 or proposed['entries']>64 or proposed['unique_graph_decoded_bytes_declared']>300_000_000):finish()
  current.append(item)
 finish()
 allkeys={r['entry_key']for r in entries};scheduled=[key for b in batches for key in b['entry_keys']]
 blocked=[key for r in frontiers for key in r['file_group']['entry_keys']]
 need(len(scheduled)==len(set(scheduled))and not(set(scheduled)&set(blocked))and set(scheduled)|set(blocked)==allkeys,'remaining209 coverage/uniqueness failed')
 need(not(set(scheduled)&set(old))and all(b['files']<=8 and b['entries']<=64 and b['unique_graph_decoded_bytes_declared']<=300_000_000 for b in batches),'batch constraint or old-terminal repetition')
 result={'schema':'scar.external-entry-declaration-read-plan/1','qualification':'DECLARATION_SCHEDULE_ONLY_NOT_SOURCE_ENTRY_FRONTEND_PLAN',
  'policy':'take original ready entries in calls-desc/key order, group whole file by first appearance, keep within-file original order, greedily close current batch before next whole file exceeds limits; no easier-case/name selection',
  'limits':{'files_per_batch':8,'entries_per_batch':64,'unique_graph_decoded_bytes_per_batch':300_000_000,'same_file_never_split':True},
  'source_catalog':previous['catalog'],'remaining_metadata':previous['remaining_ready'],'four_archive_manifests':manifests,
  'denominators':{'original_groups':817,'original_calls':100438,'source_verified_candidates':243,'metadata_ready':242,'remaining_ready':209,'old_terminals':33,'old_success':26,'old_unsupported':7,'resumable_frontier':1},
  'old_terminal_outcomes_retained':data['old_excluded'],'old_producer_and_capabilities':data['old_producer_and_capabilities'],
  'resumable_frontiers':previous['resumable_frontiers'],'batches':batches,'oversized_or_unschedulable_files':frontiers,
  'totals':{'batches':len(batches),'scheduled_entries':len(scheduled),'unschedulable_entries':len(blocked),'unique_files':len(grouped),
   'normalized_source_bytes_declared':sum(r['source_text']['normalized_bytes']for r in grouped.values()),
   'unique_graph_stored_bytes_declared':sum(r['source_graph']['declaration']['compressed_bytes']for r in grouped.values()),
   'unique_graph_decoded_bytes_declared':sum(r['source_graph']['declaration']['canonical_bytes']for r in grouped.values()),
   'historical_call_weight':sum(r['calls']for r in entries),
   'SP5_context_decoded_bytes_proxy_all_success':sum(b['SP5_context_decoded_bytes_proxy_all_success']for b in batches)},
  'SP5_proxy_scope':'multiply each source-graph canonical envelope size by entries assuming all succeed; envelope/body differences, early failures, actual compression and future reader costs are unknown; not actual SP5 bytes or a hard I/O bound',
  'graph_limit_scope':'300MB unique source-graph declarations only; ordinary owner also charges13890260 auxiliary canonical bytes, plus repeated manifest/archive checks and SP5 readback require separate real budgets',
  'execution_requirement':'after Root validation producer is stable, normally reconstruct four readonly archives/catalog/plan, derive same keys from original33 terminal receipts, compare batch keysets/full denominators and enforce independent worker budgets; do not restore owner or edit internal plan dispatch',
  'owner_restored':False,'graph_CodeType_compile_lower_target':False,'producer_freeze':'NOT_PREPARED','real_worker_run':False,'whole_first_stage_complete':False}
 save('BATCH_READ_PLAN.json',result)
 print(json.dumps({'totals':result['totals'],'frontiers':len(frontiers),'batches':[{k:b[k]for k in ('batch','entries','files','normalized_source_bytes_declared','unique_graph_stored_bytes_declared','unique_graph_decoded_bytes_declared','historical_call_weight','SP5_context_decoded_bytes_proxy_all_success')}for b in batches],'output':receipt(HERE/'BATCH_READ_PLAN.json')},sort_keys=True))

if __name__=='__main__':main()

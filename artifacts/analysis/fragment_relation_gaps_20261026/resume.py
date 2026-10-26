"""Resume declaration audit after the last fully classified ordinal; no producer."""
from pathlib import Path
from collections import Counter
import gzip,hashlib,io,json,resource,signal,sqlite3,time,traceback
from scar.ir.execution.fragment_relations_codec import from_dict
from scar.ir.execution.fragment_relations import stable_key
from scar.ir.record_codec import encode

ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'artifacts/experiments/fragment_relations_implementation_20261026'
MANIFEST=BASE/'candidate02/attempt01/result/manifest.json'
START=16086;LIMIT=1_500_000_000;SECONDS=180
started=time.monotonic();usage=Counter();status='BUILDING';error=None
result={};examples={};seen=set();node_cache={}
def write(name,value):
 (OUT/name).write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
def charge(stored=0,decoded=0):
 if usage['stored_bytes']+usage['decoded_bytes']+stored+decoded>LIMIT:raise ValueError('resume 1.5GB input budget')
 usage.update(stored_bytes=stored,decoded_bytes=decoded)
def small(p):
 b=p.read_bytes();charge(stored=len(b),decoded=len(b));return json.loads(b)
def kind(x):return 'UNREPORTED' if x is None else 'INTEGER' if type(x) is int else type(x).__name__.upper()
signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('resume180s')))
signal.setitimer(signal.ITIMER_REAL,SECONDS)
try:
 old=small(OUT/'AUDIT.json')
 assert old['error']['type']=='TimeoutError' and old['counts']['work_records']==START+1
 assert 'observed.append' in old['error']['traceback']
 raw=MANIFEST.read_bytes();charge(stored=len(raw),decoded=len(raw))
 assert hashlib.sha256(raw).hexdigest()=='98faaa2fe721ccd1377dcfdea0ed28278f4577f4a244099d23fe077ec9df91d7'
 manifest=json.loads(raw)
 for name,digest in old['codec_source_checks'].items():
  code=(ROOT/name).read_bytes();charge(stored=len(code));assert hashlib.sha256(code).hexdigest()==digest
 dbpath=Path(old['sqlite_new_measurement']['path']);before=dbpath.stat()
 data=dbpath.read_bytes();charge(stored=len(data));dbsha=hashlib.sha256(data).hexdigest()
 assert dbsha==old['sqlite_new_measurement']['sha256'] and len(data)==before.st_size
 db=sqlite3.connect(':memory:');db.deserialize(data);del data
 db.execute('PRAGMA query_only=ON');db.execute('PRAGMA temp_store=MEMORY')
 native_counts=dict(db.execute('SELECT instance,count(*) FROM native GROUP BY instance'))
 def node(host):
  key=host.instance.wire
  if key not in node_cache:
   row=db.execute('SELECT ordinal,process,thread,parent,rawref,category,correlation,external_id FROM nodes WHERE id=?',(key,)).fetchone()
   assert row is not None
   node_cache[key]={'instance':key,'ordinal':row[0],'process':json.loads(row[1]),'thread':json.loads(row[2]),'parent':row[3],'raw_reference':row[4],'category':row[5],'correlation':json.loads(row[6]),'external_id':json.loads(row[7]),'native_exact_id_join_count':int(key in native_counts),'source_qualification':'DERIVED_OLD_INDEX_ROW; ORIGINAL_EEG_NOT_REPLAYED'}
  return node_cache[key]
 def contribution(record):
  cc=Counter(work_records=1);dd={k:Counter() for k in old['distributions']}
  dd['gaps'].update(g.code for g in record.gaps);dd['host_kinds'].update(h.kind.value for h in record.hosts)
  dd['host_relation_count'][str(len(record.hosts))]+=1
  dd['distinct_host_count'][str(len({stable_key(h.host) for h in record.hosts}))]+=1
  hn=any(h.native is not None for h in record.hosts);hs=bool(record.source_contexts);hb=bool(record.static_bindings)
  dd['missing_combinations'][f'native={int(hn)},source={int(hs)},static={int(hb)}']+=1
  cc['native_linked_work']+=hn;cc['source_linked_work']+=hs
  reason=None
  if not hn:
   cc['native_missing_work']+=1;scope_hosts={}
   for h in record.hosts:
    n=node(h.host);family='ETO' if ':eto:' in h.host.instance.value else 'KINETO' if ':kineto:' in h.host.instance.value else 'OTHER'
    assert not n['native_exact_id_join_count']
    dd['host_index_classification'][str((h.kind.value,family,n['category'],0))]+=1
    dd['host_category_native_presence'][f"{n['category']}|native=0"]+=1
    dd['pid_class'][kind(n['process'])]+=1;dd['tid_class'][kind(n['thread'])]+=1
    raw_kind='ETO_NODE_REFERENCE' if n['raw_reference'] and '#/nodes/' in n['raw_reference'] else 'KINETO_EVENT_REFERENCE' if n['raw_reference'] and '#/traceEvents/' in n['raw_reference'] else 'OTHER_OR_MISSING'
    dd['raw_reference_class'][raw_kind]+=1;dd['external_id_class'][kind(n['external_id'])]+=1
    if h.kind.value=='PROVIDER_SCOPE_CONTEXT':scope_hosts[h.host.instance.wire]=family
   families=set(scope_hosts.values());dd['provider_scope_host_namespace']['+'.join(sorted(families))]+=1
   reason='NO_PROVIDER_SCOPE_HOST' if not scope_hosts else 'PROVIDER_CPU_SCOPE_IS_KINETO_INSTANCE_NO_EXACT_NATIVE_ID' if families=={'KINETO'} else 'PROVIDER_CPU_SCOPE_ETO_INSTANCE_OUTSIDE_CANONICAL_NATIVE_SET' if 'ETO' in families else 'OTHER_PROVIDER_HOST_NAMESPACE_WITHOUT_NATIVE_ID'
   dd['missing_work_reason'][reason]+=1
  return cc,dd,reason
 counts=Counter(old['counts']);distributions={k:Counter(v) for k,v in old['distributions'].items()}
 examples.update(old['typical_examples_selected_by_minimum_relation_id'])
 ordinal=0;resumed=0;rolled_back=False;first=None;last=None
 for ci,descriptor in enumerate(manifest['work']):
  end=ordinal+descriptor['rows']
  if end<=START:ordinal=end;continue
  p=MANIFEST.parent/descriptor['uri'];stored=p.read_bytes();charge(stored=len(stored))
  assert len(stored)==descriptor['stored_bytes'] and hashlib.sha256(stored).hexdigest()==descriptor['stored_sha256']
  digest=hashlib.sha256();decoded=rows=0
  with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
   while True:
    line=stream.readline(4_000_001)
    if not line:break
    charge(decoded=len(line));assert len(line)<=4_000_000 and line.endswith(b'\n')
    digest.update(line);decoded+=len(line);rows+=1
    current=ordinal+rows-1
    if current<START:continue
    record=from_dict(json.loads(line));assert record.id not in seen;seen.add(record.id)
    cc,dd,reason=contribution(record)
    if not rolled_back:
     # The saved stack is after all host counters, before scope/reason counters.
     assert current==START and reason is not None
     for key,value in cc.items():counts[key]-=value;assert counts[key]>=0
     for group,values in dd.items():
      if group in ('provider_scope_host_namespace','missing_work_reason'):continue
      for key,value in values.items():distributions[group][key]-=value;assert distributions[group][key]>=0
     assert counts['work_records']==START
     result['rollback']={'last_fully_classified_ordinal_1based':START,'interrupted_ordinal_1based':START+1,'interrupted_record_id':record.id,'basis':'saved traceback observed.append after all three host deltas; scope/reason delta not yet applied','removed_and_recomputed_once':True}
     rolled_back=True;first=current
    counts.update(cc)
    for key,values in dd.items():distributions[key].update(values)
    if reason is not None and (reason not in examples or record.id<examples[reason]['record_id']):
     examples[reason]={'record_id':record.id,'work':encode(record.projection.work),'scope':encode(record.projection.scope),'gaps':encode(record.gaps),'hosts':[{'kind':h.kind.value,'host':encode(h.host),'index':node(h.host),'path_relations':[e.relation for e in h.evidence_path]} for h in record.hosts]}
    resumed+=1;last=current
  assert (rows,decoded,digest.hexdigest())==(descriptor['rows'],descriptor['decoded_bytes'],descriptor['decoded_sha256'])
  counts['chunks_verified']+=1;ordinal=end
  if ci%5==0:print(json.dumps({'phase':'STRICT_SUFFIX','combined_rows':counts['work_records'],'resumed_rows':resumed,'elapsed_s':time.monotonic()-started,'input_bytes':sum(usage.values())}),flush=True)
 assert rolled_back and first==START and last==24081 and resumed==24082-START
 assert counts['work_records']==24082 and counts['chunks_verified']==115
 assert counts['native_missing_work']==12541 and counts['native_linked_work']==11541
 assert dict(+distributions['gaps'])==manifest['report']['missing_relations']
 result.update(counts=dict(counts),distributions={k:dict(+v) for k,v in distributions.items()},examples=examples,coverage={'prefix_ordinal_1based':[1,START],'suffix_ordinal_1based':[START+1,last+1],'suffix_rows':resumed,'ordinal_overlap_or_omission':False,'all_work_chunks_eof_verified_across_two_runs':True,'global_id_uniqueness_not_replayed':True})
 # Independent exact-ID SQL population: original GPU physical category nodes.
 print(json.dumps({'phase':'ANCESTOR_CANDIDATES','elapsed_s':time.monotonic()-started}),flush=True)
 physical={r[0]:r[1] for r in db.execute("SELECT id,category FROM nodes WHERE category IN ('kernel','gpu_memcpy','gpu_memset')")}
 assert len(physical)==24082
 scope_pairs=db.execute("SELECT e.target,e.source FROM edges e JOIN nodes n ON n.id=e.target WHERE e.relation='provider_scope_association' AND n.category IN ('kernel','gpu_memcpy','gpu_memset') ORDER BY e.target,e.source").fetchall()
 assert len(scope_pairs)==24082 and len({p[0] for p in scope_pairs})==24082
 missing_pairs=[(work,host) for work,host in scope_pairs if host not in native_counts]
 assert len(missing_pairs)==12541
 cache={};ancestor_counts=Counter();host_counts=Counter();depth_counts=Counter();ancestor_examples={}
 def ancestry(host):
  if host in cache:return cache[host]
  current=host;visited=set();path=[];terminal=None;depth=0
  while True:
   if current in visited:terminal='CYCLE';break
   visited.add(current)
   row=db.execute('SELECT parent,process,thread,rawref,category FROM nodes WHERE id=?',(current,)).fetchone()
   if row is None:terminal='NODE_ABSENT';break
   path.append({'instance':current,'parent':row[0],'process':json.loads(row[1]),'thread':json.loads(row[2]),'raw_reference':row[3],'category':row[4]})
   if depth and current in native_counts:terminal='CANONICAL_NATIVE_ANCESTOR';break
   if row[0] is None:terminal='NO_PARENT_BEFORE_NATIVE';break
   current=row[0];depth+=1
  value={'status':terminal,'depth':depth,'candidate':current if terminal=='CANONICAL_NATIVE_ANCESTOR' else None,'candidate_native_row_count':native_counts.get(current,0) if terminal=='CANONICAL_NATIVE_ANCESTOR' else 0,'path':path}
  cache[host]=value;return value
 for work,host in missing_pairs:
  value=ancestry(host);label=value['status'];ancestor_counts[label]+=1
  if label=='CANONICAL_NATIVE_ANCESTOR':depth_counts[str(value['depth'])]+=1
  if label not in ancestor_examples or (work,host)<tuple(ancestor_examples[label]['selection']):ancestor_examples[label]={'selection':[work,host],'ancestry':value}
 for value in cache.values():host_counts[value['status']]+=1
 result['ancestor_candidates']={'population':'derived original-index physical GPU targets with their direct provider_scope_association host; complete index count matches retained work denominator, not an independently replayed EEG','physical_categories':dict(Counter(physical.values())),'physical_target_count':len(physical),'unique_scope_host_per_target':True,'missing_work_count':len(missing_pairs),'unique_missing_host_count':len(cache),'work_weighted_status':dict(ancestor_counts),'unique_host_status':dict(host_counts),'work_weighted_first_canonical_depth':dict(depth_counts),'mechanically_minimum_qualified_ids_by_status':ancestor_examples,'authority':'candidate ancestry only; no direct-call, invocation, Tensor/world ports, ordering or effects claim','parent_basis_required_proof':'index stores OperationInstance.parent; original per-node parent_basis/ctrl_deps not retained in this SQL schema and not replayed here'}
 after=dbpath.stat();assert tuple(getattr(before,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))==tuple(getattr(after,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))
 result['sqlite']={'sha256':dbsha,'bytes':before.st_size,'same_as_first_audit_new_measurement':True,'final_stat_unchanged':True}
 status='COMPLETE_DECLARATION_AUDIT_WITH_DERIVED_ANCESTOR_CANDIDATES'
except BaseException as exc:
 error={'type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc()}
finally:
 signal.setitimer(signal.ITIMER_REAL,0)
 result.update(status=status,error=error,elapsed_s=time.monotonic()-started,rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,io={**dict(usage),'actual_input_bytes':sum(usage.values()),'limit':LIMIT},normal_producer_qualification_regranted=False,originals_or_main_modified=False)
 write('RESUME.json',result)
 print(json.dumps({k:result.get(k) for k in ('status','error','elapsed_s','counts','io','ancestor_candidates')},ensure_ascii=False),flush=True)
 if error:raise SystemExit(1)

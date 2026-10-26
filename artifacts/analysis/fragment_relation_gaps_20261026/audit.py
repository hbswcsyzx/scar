"""Bounded declaration/derived-index audit; never the normal producer guard."""
from pathlib import Path
from collections import Counter
import gzip,hashlib,io,json,resource,signal,sqlite3,time,traceback
from scar.ir.execution.fragment_relations_codec import from_dict
from scar.ir.execution.fragment_relations import canonical,stable_key
from scar.ir.record_codec import encode
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
BASE=ROOT/'artifacts/experiments/fragment_relations_implementation_20261026'
MANIFEST=BASE/'candidate02/attempt01/result/manifest.json'
started=time.monotonic();counts=Counter();counters={name:Counter() for name in ('gaps','host_kinds','host_relation_count','distinct_host_count','missing_combinations','missing_work_reason','host_index_classification','host_category_native_presence','provider_scope_host_namespace','pid_class','tid_class','raw_reference_class','external_id_class')}
examples={};node_cache={};membership=set();io_counts={'stored_bytes':0,'decoded_bytes':0};checks={};status='BUILDING';error=None
IO_LIMIT=2_000_000_000
(OUT/'BUILDING.json').write_text('{"scope":"DECLARATION_AND_DERIVED_INDEX_AUDIT_ONLY","status":"BUILDING"}\n')
def charge(stored=0,decoded=0):
 if io_counts['stored_bytes']+stored+io_counts['decoded_bytes']+decoded>IO_LIMIT:raise ValueError('2GB audit limit')
 io_counts['stored_bytes']+=stored;io_counts['decoded_bytes']+=decoded
 if time.monotonic()-started>180:raise TimeoutError('audit180s')
def loadsmall(path):
 b=path.read_bytes();charge(stored=len(b),decoded=len(b));return json.loads(b)
def kind(value):
 if value is None:return 'UNREPORTED'
 if type(value) is int:return 'INTEGER'
 return type(value).__name__.upper()
def dump(path,value):path.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('audit180s')));signal.setitimer(signal.ITIMER_REAL,180)
try:
 artifact=loadsmall(BASE/'RELATION_ARTIFACTS.json')['manifest'];raw=MANIFEST.read_bytes();charge(stored=len(raw),decoded=len(raw));assert hashlib.sha256(raw).hexdigest()==artifact['sha256'];manifest=json.loads(raw)
 old=json.loads((BASE/'candidate02/PREPARATION_RECEIPT.json').read_bytes());expected={r['path']:r['sha256'] for r in old['production_sources']}
 for name in ('scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py','scar/store/fragment_relations.py','scar/analysis/source_native_composition.py'):
  p=ROOT/name;v=p.read_bytes();assert hashlib.sha256(v).hexdigest()==expected[str(p)]
  checks[name]=hashlib.sha256(v).hexdigest()
 # The historical retention did not supply a SQLite SHA. This current hash is
 # a NEW measurement, never retroactive producer validation of its contents.
 path=MANIFEST.parent/'locator.sqlite';before=path.stat();charge(stored=before.st_size)
 data=path.read_bytes();db_sha=hashlib.sha256(data).hexdigest();assert len(data)==before.st_size
 db=sqlite3.connect(':memory:');db.deserialize(data);del data
 db.execute('PRAGMA query_only=ON');db.execute('PRAGMA temp_store=MEMORY')
 schema=db.execute("SELECT name,sql FROM sqlite_schema WHERE type IN ('table','index') ORDER BY name").fetchall()
 native_ids={r[0] for r in db.execute('SELECT DISTINCT instance FROM native')}
 db_counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('nodes','edges','native','source')}
 def node(host):
  key=host.instance.wire
  if key not in node_cache:
   r=db.execute('SELECT ordinal,process,thread,parent,rawref,category,correlation,external_id FROM nodes WHERE id=?',(key,)).fetchone()
   assert r is not None
   node_cache[key]={'instance':key,'ordinal':r[0],'process':json.loads(r[1]),'thread':json.loads(r[2]),'parent':r[3],'raw_reference':r[4],'category':r[5],'correlation':json.loads(r[6]),'external_id':json.loads(r[7]),'native_exact_id_join_count':int(key in native_ids),'source_qualification':'DERIVED_OLD_INDEX_ROW; ORIGINAL_EEG_NOT_REPLAYED'}
  return node_cache[key]
 namespace=None
 for chunk_number,d in enumerate(manifest['work']):
  p=MANIFEST.parent/d['uri'];s=p.stat();assert s.st_size==d['stored_bytes'];charge(stored=s.st_size);stored=p.read_bytes();assert hashlib.sha256(stored).hexdigest()==d['stored_sha256']
  digest=hashlib.sha256();rows=decoded=0
  with gzip.GzipFile(fileobj=io.BytesIO(stored),mode='rb') as z:
   while True:
    line=z.readline(4_000_001)
    if not line:break
    assert len(line)<=4_000_000 and line.endswith(b'\n');charge(decoded=len(line));digest.update(line);decoded+=len(line);rows+=1
    record=from_dict(json.loads(line));assert record.id not in membership;membership.add(record.id)
    counts['work_records']+=1;counters['gaps'].update(g.code for g in record.gaps);counters['host_kinds'].update(h.kind.value for h in record.hosts)
    counters['host_relation_count'][str(len(record.hosts))]+=1
    hosts={stable_key(h.host):h.host for h in record.hosts};counters['distinct_host_count'][str(len(hosts))]+=1
    has_native=any(h.native is not None for h in record.hosts);has_source=bool(record.source_contexts);has_static=bool(record.static_bindings)
    counters['missing_combinations'][f'native={int(has_native)},source={int(has_source)},static={int(has_static)}']+=1
    counts['native_linked_work']+=has_native;counts['source_linked_work']+=has_source
    if not has_native:
     counts['native_missing_work']+=1
     observed=[];scope_hosts={}
     for h in record.hosts:
      n=node(h.host);family='ETO' if ':eto:' in h.host.instance.value else 'KINETO' if ':kineto:' in h.host.instance.value else 'OTHER'
      label=(h.kind.value,family,n['category'],n['native_exact_id_join_count']);counters['host_index_classification'][str(label)]+=1
      counters['host_category_native_presence'][f"{n['category']}|native={n['native_exact_id_join_count']}"]+=1
      counters['pid_class'][kind(n['process'])]+=1;counters['tid_class'][kind(n['thread'])]+=1
      raw_kind='ETO_NODE_REFERENCE' if n['raw_reference'] and '#/nodes/' in n['raw_reference'] else 'KINETO_EVENT_REFERENCE' if n['raw_reference'] and '#/traceEvents/' in n['raw_reference'] else 'OTHER_OR_MISSING'
      counters['raw_reference_class'][raw_kind]+=1;counters['external_id_class'][kind(n['external_id'])]+=1
      if h.kind.value=='PROVIDER_SCOPE_CONTEXT':scope_hosts[h.host.instance.wire]=(family,n)
      if n['native_exact_id_join_count']:raise ValueError('old index contradicts missing native association')
      observed.append({'kind':h.kind.value,'host':encode(h.host),'index':n,'path_relations':[e.relation for e in h.evidence_path]})
     families={v[0] for v in scope_hosts.values()};counters['provider_scope_host_namespace']['+'.join(sorted(families))]+=1
     if not scope_hosts:reason='NO_PROVIDER_SCOPE_HOST'
     elif families=={'KINETO'}:reason='PROVIDER_CPU_SCOPE_IS_KINETO_INSTANCE_NO_EXACT_NATIVE_ID'
     elif 'ETO' in families:reason='PROVIDER_CPU_SCOPE_ETO_INSTANCE_OUTSIDE_CANONICAL_NATIVE_SET'
     else:reason='OTHER_PROVIDER_HOST_NAMESPACE_WITHOUT_NATIVE_ID'
     counters['missing_work_reason'][reason]+=1
     example={'record_id':record.id,'work':encode(record.projection.work),'scope':encode(record.projection.scope),'gaps':encode(record.gaps),'hosts':observed}
     if reason not in examples or record.id<examples[reason]['record_id']:examples[reason]=example
  assert (rows,decoded,digest.hexdigest())==(d['rows'],d['decoded_bytes'],d['decoded_sha256']);assert p.stat().st_size==s.st_size
  counts['chunks_verified']+=1
  if chunk_number%10==0:print(json.dumps({'phase':'STRICT_DECLARATION_STREAM','rows':counts['work_records'],'chunks':counts['chunks_verified'],'elapsed_s':time.monotonic()-started,'input_bytes':sum(io_counts.values())}),flush=True)
 assert counts['work_records']==manifest['report']['declared_work_count']==24082
 assert counts['native_missing_work']==12541 and counts['native_linked_work']==11541
 assert dict(counters['gaps'])==manifest['report']['missing_relations']
 after=path.stat();assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
 status='COMPLETE_DECLARATION_AUDIT_WITH_OPEN_ORIGINAL_PROOF'
except BaseException as e:
 error={'type':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()}
finally:
 signal.setitimer(signal.ITIMER_REAL,0)
 result={'status':status,'counts':dict(counts),'distributions':{k:dict(v) for k,v in counters.items()},'typical_examples_selected_by_minimum_relation_id':examples,'codec_source_checks':checks,'io':{**io_counts,'actual_input_bytes':sum(io_counts.values()),'limit':IO_LIMIT,'sqlite_read_once_then_readonly_memory_queries':True},'elapsed_s':time.monotonic()-started,'rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'error':error,'qualification':'NORMATIVE_DECLARATIONS_STRICT_CODEC_CHECKED; SQLITE_ROWS_DERIVED_AND_NOT_ORIGINAL_EEG_PROOF','normal_producer_guard_not_bypassed_or_claimed':True,'original_graph_raw_or_native_models_read':False,'main_changed':False}
 if 'db_sha' in globals():result['sqlite_new_measurement']={'path':str(path),'sha256':db_sha,'bytes':before.st_size,'historical_sha_receipt_existed':False,'schema':schema,'counts':db_counts}
 dump(OUT/'AUDIT.json',result)
 print(json.dumps({'status':status,'counts':dict(counts),'elapsed_s':result['elapsed_s'],'io':result['io'],'error':error},sort_keys=True),flush=True)
 if error:raise SystemExit(1)

"""Owned CPU transport checks and one identical-row producer measurement."""
from hashlib import sha256
import json,marshal,os,resource,sys,threading,time,traceback,warnings
from pathlib import Path
from scar.trace.snapshot_journal import SnapshotJournal,is_journal_writer_thread
from scar.analysis.snapshot_journal import materialize_snapshot_journal
BASE=Path(__file__).resolve().parent

def save(name,value):
 (BASE/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')

def own_function(index):
 return {'event':'OWN_FUNCTION','index':index,'values':[index,0.25,None,True,'λ'],'shape':(2,3)}

def actual_checks():
 j=SnapshotJournal(BASE/'thread-fork.journal')
 first=own_function(0);refs=sys.getrefcount(first)
 assert j.append(first)and sys.getrefcount(first)==refs
 first['values'][0]='MUTATED_AFTER_APPEND'
 def caller(label):
  for n in range(4):assert j.append({'event':'OWN_THREAD','thread':label,'index':n})
 threads=[threading.Thread(target=caller,args=(label,))for label in ('a','b')]
 for t in threads:t.start()
 for t in threads:t.join()
 read_fd,write_fd=os.pipe()
 with warnings.catch_warnings():
  warnings.simplefilter('ignore',DeprecationWarning)
  pid=os.fork()
 if pid==0:
  os.close(read_fd)
  accepted=j.append({'event':'CHILD_MUST_NOT_FLUSH'})
  child=j.close()
  os.write(write_fd,json.dumps({'accepted':accepted,'close':child,'is_writer':is_journal_writer_thread()}).encode())
  os.close(write_fd);os._exit(0)
 os.close(write_fd);child=json.loads(os.read(read_fd,65536));os.close(read_fd)
 waited,status=os.waitpid(pid,0);assert waited==pid and status==0
 assert not child['accepted']and not child['close']['complete']and not child['close']['parent_buffer_flushed']
 assert j.append(own_function(1))
 close=j.close();assert close['complete']and close['counts']['accepted_records']==10
 material=materialize_snapshot_journal(BASE/'thread-fork.journal',BASE/'thread-fork.jsonl',expected_sha256=close['source']['sha256'])
 assert material['complete']and material['output']['lines']==10
 rows=[json.loads(line)for line in (BASE/'thread-fork.jsonl').read_text().splitlines()]
 assert rows[0]['values'][0]==0 and rows[-1]['index']==1
 for label in ('a','b'):assert [r['index']for r in rows if r.get('thread')==label]==list(range(4))
 assert not any(r['event']=='CHILD_MUST_NOT_FLUSH'for r in rows)
 save('THREAD_FORK.json',{'close':close,'materialize':material,'child':child,'row_references_retained':False})
 # A frame larger than the independent queue capacity is deterministically
 # rejected, rather than timing a writer race or sleeping in production IO.
 q=SnapshotJournal(BASE/'queue-rejected.journal',max_queue_bytes=64)
 assert not q.append({'payload':'x'*512})and q.last_record_bytes==0
 qc=q.close();assert not qc['complete']and qc['counts']['rejected']['queue_full']==1
 qm=materialize_snapshot_journal(BASE/'queue-rejected.journal',BASE/'queue-rejected.jsonl',expected_sha256=qc['source']['sha256'])
 assert not qm['complete']and not qm['output']['published']
 save('QUEUE_REJECTION.json',{'close':qc,'materialize':qm})
 # Strict validation is offline: marshal accepts this plain snapshot NaN,
 # while the legacy JSONL materializer must refuse it.
 n=SnapshotJournal(BASE/'nonfinite.journal');assert n.append({'value':float('nan')})
 nc=n.close();assert nc['complete']and not nc['rows_validated']
 nm=materialize_snapshot_journal(BASE/'nonfinite.journal',BASE/'nonfinite.jsonl',expected_sha256=nc['source']['sha256'])
 assert not nm['complete']and not nm['output']['published'];save('OFFLINE_VALIDATION.json',nm)
 limited=materialize_snapshot_journal(BASE/'thread-fork.journal',BASE/'line-cap.jsonl',
  expected_sha256=close['source']['sha256'],max_output_line_bytes=8)
 assert not limited['complete']and not limited['output']['published']and limited['output']['raw_bytes']==0
 save('LINE_CAP.json',limited)
 mismatch=materialize_snapshot_journal(BASE/'thread-fork.journal',BASE/'wrong-sha.jsonl',expected_sha256='0'*64)
 assert not mismatch['complete']and not mismatch['output']['published'];save('WRONG_SHA.json',mismatch)
 # This is a separate retained prefix, not a mutation of the valid journal.
 (BASE/'truncated.journal').write_bytes((BASE/'thread-fork.journal').read_bytes()[:-7])
 partial=materialize_snapshot_journal(BASE/'truncated.journal',BASE/'truncated.jsonl')
 assert not partial['complete']and not partial['output']['published'];save('PARTIAL.json',partial)
 hits=[]
 class App:
  def __repr__(self):hits.append('repr');raise AssertionError('hook')
  def __iter__(self):hits.append('iter');raise AssertionError('hook')
  def __reduce__(self):hits.append('reduce');raise AssertionError('hook')
 class DictSubclass(dict):
  def items(self):hits.append('items');raise AssertionError('hook')
 class ListSubclass(list):
  def __iter__(self):hits.append('list.iter');raise AssertionError('hook')
 probe=[]
 for label,value in [('app',App()),('dict-subclass',DictSubclass(x=1)),('list-subclass',ListSubclass([1])),('code',own_function.__code__)]:
  try:marshal.dumps({'value':value},marshal.version,allow_code=False)
  except ValueError:probe.append({'kind':label,'rejected':True})
  else:raise AssertionError('unsupported snapshot accepted')
 assert hits==[];save('MARSHAL_HOOK_PROBE.json',{'runtime':sys.version,'marshal_version':marshal.version,'probes':probe,'application_hooks':hits})
 return {'normal_rows':10,'thread_count':2,'fork_child':pid,'checks':'snapshot frozen/no application reference held; child never flushes; incomplete/line/SHA/partial never publish'}

def measurement():
 rows=[{'event':'FRAME_ENTRY','index':i,'code':'pycode-v2:'+('a'*64),
  'process_id':1234,'thread_id':17,'parent':i-1,'arguments':['weak:1234:'+str(i+j)for j in range(4)],
  'locals':{f'local_{j}':{'reference':'weak:1234:'+str(i+j),'type':'builtins.object','shape':[2,3]}for j in range(8)},
  'flags':[True,False,None,0.25],'label':'own λ snapshot'}for i in range(5000)]
 baseline=BASE/'baseline.jsonl';start=time.perf_counter()
 with baseline.open('xb')as stream:
  pending=bytearray()
  for row in rows:
   pending.extend(json.dumps(row,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')+b'\n')
   if len(pending)>=65536:stream.write(pending);pending.clear()
  if pending:stream.write(pending)
 json_seconds=time.perf_counter()-start
 j=SnapshotJournal(BASE/'measured.journal');start=time.perf_counter()
 for row in rows:assert j.append(row)
 journal_seconds=time.perf_counter()-start
 start=time.perf_counter();closed=j.close();close_seconds=time.perf_counter()-start
 assert closed['complete']and closed['counts']['accepted_records']==len(rows)
 start=time.perf_counter();converted=materialize_snapshot_journal(BASE/'measured.journal',BASE/'measured.jsonl',
  expected_sha256=closed['source']['sha256'],max_output_line_bytes=2000000)
 offline_seconds=time.perf_counter()-start
 assert converted['complete']and converted['output']['published']
 raw=baseline.read_bytes();assert sha256(raw).hexdigest()==converted['output']['sha256']
 result={'rows':len(rows),'preconstructed_identical_rows':True,'json_producer_with_64KiB_buffer_seconds':json_seconds,
  'journal_append_producer_seconds':journal_seconds,'journal_close_SHA_seconds':close_seconds,
  'offline_validation_JSON_seconds':offline_seconds,'json_raw_bytes':len(raw),'journal_raw_bytes':closed['source']['raw_bytes'],
  'accepted_marshal_payload_bytes':closed['counts']['accepted_bytes'],'queue_highwater_bytes':closed['counts']['queue_highwater_bytes'],
  'inflight_highwater_bytes':closed['counts']['inflight_highwater_bytes'],'output_byte_for_byte_equal':True,
  'closed':closed,'materialized':converted,'no_target_or_collector_speedup_claim':True,
  'measurement_scope':'single local prebuilt-row transport measurement; not threaded CPU acceleration or workload benchmark'}
 save('MEASUREMENT.json',result);return {k:v for k,v in result.items()if k not in ('closed','materialized')}

if __name__=='__main__':
 start=time.monotonic();result={}
 try:result={'status':'PASS','actual_checks':actual_checks(),'measurement':measurement()}
 except BaseException as error:result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
 finally:
  result.update(wall_seconds=time.monotonic()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
   runtime=sys.version,source_sha256={name:sha256(Path(name).read_bytes()).hexdigest()for name in ('scar/trace/snapshot_journal.py','scar/analysis/snapshot_journal.py')})
  save('RESULT.json',result);print(json.dumps(result,indent=2,sort_keys=True))
  if result['status']!='PASS':sys.exit(1)

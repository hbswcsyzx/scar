"""One bounded original event stream audit; no target or owner reconstruction."""
from pathlib import Path
from collections import Counter,defaultdict
import gzip,hashlib,json,time
HERE=Path(__file__).resolve().parent
CAPTURE=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_physical_20261023')
MAX=128_000_000
READ=0
start=time.monotonic()
archive=json.loads((CAPTURE/'archive-index.json').read_bytes());entries={x['logical_path']:x for x in archive['files']}
meta=json.loads((CAPTURE/'trace/call-operand-meta.369749.json').read_bytes());root=meta['project_root'];prefix=root.rstrip('/')+'/'
receipts=[]
def stream(name):
 global READ
 logical=str(CAPTURE/'trace'/name);e=entries[logical];p=Path(e['actual_path'])
 raw=p.read_bytes();READ+=len(raw)
 if (len(raw),hashlib.sha256(raw).hexdigest())!=(e['compressed_bytes'],e['gzip_sha256']):raise ValueError('original compressed receipt '+str(p))
 d=hashlib.sha256();n=rows=0
 with gzip.open(p,'rb') as f:
  while b:=f.readline(2_000_001):
   n+=len(b);READ+=len(b);rows+=1
   if len(b)>2_000_000 or READ>MAX:raise ValueError('bounded original audit ceiling')
   d.update(b);yield rows,json.loads(b),hashlib.sha256(b).hexdigest()
 if (n,d.hexdigest())!=(e['raw_bytes'],e['raw_sha256']):raise ValueError('original raw EOF/SHA '+logical)
 receipts.append({'logical_uri':logical,'physical_uri':str(p),'stored_bytes':e['compressed_bytes'],'stored_sha256':e['gzip_sha256'],'decoded_bytes':n,'decoded_sha256':d.hexdigest(),'rows':rows})
codes={}
for _,r,_ in stream('call-codes.369749.jsonl'):
 if r['key'] in codes and codes[r['key']]!=r:raise ValueError('conflicting actual code descriptor')
 codes[r['key']]=r
attempts={};handshakes=defaultdict(list);events=Counter()
for line,r,line_sha in stream('call-operands.369749.jsonl'):
 events[r['kind']]+=1
 if r['kind']=='CALL_ATTEMPT':
  key=r['process_id'],r['index']
  if key in attempts:raise ValueError('duplicate actual attempt')
  attempts[key]={'dispatch':r['dispatch'],'arg0_missing':r['arg0_missing'],'invocation_id':r['invocation_id'],'site':r['site'],'thread_id':r['thread_id'],'line_number':line,'line_sha256':line_sha}
 elif r['kind']=='ENTRY_HANDSHAKE':handshakes[r['process_id'],r['attempt_index']].append(r)
if len(attempts)!=100550 or sum(map(len,handshakes.values()))!=4069:raise ValueError('original attempt/handshake denominator differs')
kind=Counter();cross=Counter();samples={};code_coverage=Counter()
for key,r in attempts.items():
 d=r['dispatch'];k=d['kind'];kind[k]+=1
 c=codes.get(d['code']) if d['code'] is not None else None
 if c is None:scope='CODE_NOT_RECORDED_FOR_KIND' if d['code'] is None else 'CODE_KEY_PRESENT_DESCRIPTOR_UNAVAILABLE'
 elif not Path(c['filename']).is_absolute():scope='RECORDED_NONFILESYSTEM_CODE_FILENAME'
 elif c['filename']==root or c['filename'].startswith(prefix):scope='RECORDED_PROJECT_PYTHON_CODE'
 else:scope='RECORDED_OUTSIDE_PROJECT_PYTHON_CODE'
 code_coverage[scope]+=1
 h=len(handshakes.get(key,()))
 label=(k,scope,'UNIQUE_HANDSHAKE' if h==1 else 'NO_HANDSHAKE' if h==0 else 'MULTIPLE_HANDSHAKES')
 cross[label]+=1
 samples.setdefault(label,{'process_id':key[0],'attempt_index':key[1],**r,'callee_code_descriptor':c,'handshakes':handshakes.get(key,())})
result={'schema':'scar.original-python-call-boundary-audit/1','status':'OBSERVED_ORIGINAL_CAPTURE_COUNTS_ONLY','project_root':root,'attempts':len(attempts),'handshake_events':sum(map(len,handshakes.values())),'unique_handshake_attempts':sum(len(v)==1 for v in handshakes.values()),'kinds':dict(kind),'code_scope_availability':dict(code_coverage),'cross_counts':[{'kind':k,'scope':s,'handshake':h,'attempts':n,'sample':samples[k,s,h]} for (k,s,h),n in sorted(cross.items())],'events':dict(events),'input_receipts':receipts,'actual_stored_plus_decoded_bytes':READ,'input_ceiling':MAX,'elapsed_s':time.monotonic()-start,'limits':['OTHER has no code/type/slot target fields: cannot split C/native vs Python callable objects/classes from this v1 artifact','EXACT_METHOD omits underlying function/code/receiver: cannot infer callee project scope or bound receiver','monitoring arg0 is first argument, not a receiver discriminator','outside-project label is from an original recorded Code filename only; no time/PID/name-pattern inference'],'target_or_new_episode_executed':False,'current_collector_behavior_inferred_from_code_not_requalified_historical_capture':True}
with (HERE/'RESULT.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({k:result[k] for k in ('attempts','handshake_events','kinds','code_scope_availability','actual_stored_plus_decoded_bytes','elapsed_s')},indent=2))

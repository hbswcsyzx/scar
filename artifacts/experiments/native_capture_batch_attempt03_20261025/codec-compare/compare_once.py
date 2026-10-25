"""One bounded static reuse comparison; saved public data grants no native proof."""
from pathlib import Path
from dataclasses import replace
from hashlib import sha256
import cProfile
import json
import pstats
import signal
import time
import traceback
B=Path(__file__).resolve().parents[4]
O=Path(__file__).resolve().parent
R=B/'artifacts/experiments/native_capture_batch_attempt02_20261025/result'
START=time.monotonic()
profiler=cProfile.Profile()
rows=[]; reads=[]; error=None
calls={}
def alarm(*_):raise TimeoutError('one codec comparison whole60s cap')
signal.signal(signal.SIGALRM,alarm);signal.alarm(60)
def read(p):
 raw=p.read_bytes();reads.append({'path':str(p.relative_to(B)),'bytes':len(raw),'sha256':sha256(raw).hexdigest()});return raw.decode()
def measure(name,fn):
 before=time.monotonic();profiler.clear();profiler.enable()
 try:value=fn()
 finally:
  profiler.disable()
  total=sum(v[0] for k,v in pstats.Stats(profiler).stats.items() if k[2]=='dumps' and k[0].endswith('/program/codec.py'))
  calls[name]=total;rows.append({'stage':name,'profiled_seconds':time.monotonic()-before,'program_codec_dumps_calls':total})
 return value
try:
 from scar.ir.program.codec import loads as p_loads
 from scar.ir.execution.codec import loads as e_loads
 from scar.ir.v2.codec import values_from_dict,evidence_from_dict
 from scar.ir.execution.validation import validate,prepare_program_snapshot
 p_text=read(R/'program.json');e_text=read(R/'shards/000000/execution.json')
 v_text=read(R/'shards/000000/source-values.json');g_text=read(R/'shards/000000/source-evidence.json')
 report=json.loads(read(R/'shards/000000/report.json'))
 program=p_loads(p_text);execution=e_loads(e_text)
 values=values_from_dict(json.loads(v_text));evidence=evidence_from_dict(json.loads(g_text))
 catalogs={'value_graphs':{report['values_projection']['sha256']:values},'evidence_graphs':{report['evidence_projection']['sha256']:evidence}}
 token=measure('prepare_static_once',lambda:prepare_program_snapshot(program))
 assert token.canonical_bytes(program)==p_text.encode()
 old=measure('default_generic_validation_without_native',lambda:validate(execution,program,**catalogs))
 prepared=measure('prepared_generic_validation_without_native',lambda:validate(execution,program,prepared_snapshot=token,**catalogs))
 assert old==prepared and old.valid
 assert calls=={'prepare_static_once':1,'default_generic_validation_without_native':1,'prepared_generic_validation_without_native':0}
 fresh=replace(program)
 try:token.canonical_bytes(fresh)
 except ValueError:pass
 else:raise AssertionError('old prepared token accepted another program object')
 rejection=validate(execution,fresh,prepared_snapshot=token,**catalogs)
 assert not rejection.valid and any(i.code=='record_or_program' for i in rejection.issues)
 checks={'canonical_bytes_equal':True,'default_prepared_reports_identical':True,'fresh_equal_program_old_token_rejected':True,
  'generic_valid':old.valid,'generic_gaps':len(old.gaps),'native_evidence_used':False}
except BaseException as exc:error={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
finally:
 profiler.disable();signal.alarm(0)
 result={'status':'BOUNDED_CODEC_COMPARE_PASS' if error is None else 'BOUNDED_CODEC_COMPARE_FAILED','whole_seconds':time.monotonic()-START,
  'cap_seconds':60,'stages':rows,'checks':locals().get('checks'),'reads':reads,'bytes_read':sum(r['bytes'] for r in reads),'error':error,
  'raw_reads':0,'private_index_reads':0,'later_shard_reads':0,'owned_authority_restored':False,
  'scope':'Codec/static-snapshot reuse only; not fullbatch timing share, source proof or freshfull gate qualification'}
 with (O/'summary.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
 print(json.dumps(result),flush=True)

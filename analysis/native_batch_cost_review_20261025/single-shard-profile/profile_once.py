"""One <=60s codec-only profile; no owned authority or raw/private input."""
from pathlib import Path
from hashlib import sha256
import cProfile
import io
import json
import pstats
import signal
import time
import traceback
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'artifacts/experiments/native_capture_batch_attempt02_20261025/result'
SHARD = SOURCE / 'shards/000000'
START = time.monotonic()
rows, reads = [], []
profiler = cProfile.Profile()
def alarm(*_):
    raise TimeoutError('one codec diagnostic whole60s cap')
signal.signal(signal.SIGALRM, alarm)
signal.alarm(60)
def read(path):
    raw = path.read_bytes()
    reads.append({'path':str(path.relative_to(ROOT)), 'bytes':len(raw), 'sha256':sha256(raw).hexdigest()})
    return raw.decode()
def measure(name, fn):
    before=time.monotonic()
    profiler.enable()
    try:
        value=fn()
    finally:
        profiler.disable()
        rows.append({'stage':name,'profiled_wall_seconds':time.monotonic()-before})
    return value
error=None
try:
    from scar.ir.program.codec import loads as p_loads, dumps as p_dumps
    from scar.ir.execution.codec import loads as e_loads, dumps as e_dumps
    from scar.ir.v2.codec import values_from_dict, evidence_from_dict
    from scar.ir.execution.validation import validate
    p_text=read(SOURCE/'program.json')
    e_text=read(SHARD/'execution.json')
    v_text=read(SHARD/'source-values.json')
    g_text=read(SHARD/'source-evidence.json')
    report=json.loads(read(SHARD/'report.json'))
    program=measure('program_loads',lambda:p_loads(p_text))
    encoded=measure('program_dumps',lambda:p_dumps(program))
    assert encoded==p_text
    values=measure('values_json_and_decode',lambda:values_from_dict(json.loads(v_text)))
    evidence=measure('evidence_json_and_decode',lambda:evidence_from_dict(json.loads(g_text)))
    execution=measure('execution_loads',lambda:e_loads(e_text))
    encoded=measure('execution_dumps',lambda:e_dumps(execution))
    assert encoded==e_text
    validation=measure('generic_validate_without_native_evidence',lambda:validate(execution,program,
        value_graphs={report['values_projection']['sha256']:values},
        evidence_graphs={report['evidence_projection']['sha256']:evidence}))
    assert validation.valid,validation.issues
    validation_info={'valid':validation.valid,'issues':len(validation.issues),'gaps':len(validation.gaps),
        'native_owned_evidence_used':False,'no_native_qualification_granted':True}
except BaseException as exc:
    error={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
finally:
    profiler.disable()
    signal.alarm(0)
    profiler.dump_stats(str(OUT/'codec-profile.pstats'))
    stream=io.StringIO()
    pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(45)
    (OUT/'cumulative.txt').write_text(stream.getvalue())
    result={'status':'ONE_CODEC_PROFILE_PASS' if error is None else 'ONE_CODEC_PROFILE_INCOMPLETE',
        'scope':'Only published shard000000 codecs/validator costs under cProfile; not a timing share of full batch, not a native evidence or freshfull gate result',
        'whole_seconds':time.monotonic()-START,'cap_seconds':60,'stages':rows,'reads':reads,
        'bytes_read':sum(r['bytes'] for r in reads),'error':error,
        'raw_reads':0,'private_index_reads':0,'later_shard_reads':0,'owned_authority_restored':False,
        'validation':locals().get('validation_info')}
    with (OUT/'result.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result,sort_keys=True),flush=True)

"""One owned bounded Python-only diagnostic; no production-source edits."""
from hashlib import sha256
import json, os, signal, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'collector-source'
MAIN = Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
LEWM = Path('/home/zyf/AAA/le-wm')
OLD = MAIN / 'artifacts/experiments/lewm_snapshot_ports_20261027/INPUTS.json'
TRACE = ROOT / 'trace'

def write(name, doc):
    (ROOT/name).write_text(json.dumps(doc, indent=2)+'\n')

def identity(pid):
    try:
        parts = (Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()
        return dict(pid=pid, state=parts[0], parent_pid=int(parts[1]), process_group=int(parts[2]),
                    session=int(parts[3]), start_ticks=int(parts[19]))
    except (OSError, ValueError, IndexError):
        return None

def same_live(original):
    current = identity(original['pid']) if original is not None else None
    return current is not None and current['start_ticks'] == original['start_ticks'] and current['state'] not in ('Z','X')

def source_receipt():
    rows = []
    for path in sorted(SOURCE.rglob('*.py')):
        raw = path.read_bytes()
        rows.append(dict(path=str(path.relative_to(SOURCE)), sha256=sha256(raw).hexdigest(), bytes=len(raw)))
    return dict(git_source='312ab664', files=rows, bytes=sum(r['bytes'] for r in rows),
                sha256=sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest())

cfg = json.loads(OLD.read_text())
old_argv = cfg['command']
target = old_argv[old_argv.index('--')+1:]
target[1:1] = ['-u']
command = [sys.executable,'-B','-m','scar.cli','trace',
    '--capture-profile','process-ports','--capture-transport','snapshot',
    '--snapshot-buffer-bytes','8388608','--out',str(TRACE),'--project-root',str(LEWM),
    '--max-call-events','100000','--max-call-bytes','32000000','--max-call-codes','8192',
    '--max-call-references','65536','--max-operand-events','200000','--max-operand-bytes','64000000',
    '--max-source-files','256','--max-source-file-bytes','2000000','--max-source-bytes','16000000',
    '--',*target]
env = {k:v for k,v in os.environ.items() if not k.startswith('SCAR_')}
env.update({k:v for k,v in cfg['environment'].items() if k.startswith('LEWM_')})
env.update(PYTHONPATH=str(SOURCE),PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',
    LEWM_OUTPUT_ROOT=str(ROOT/'lewm-output'),LEWM_RUN_NAME='python-only-diagnostic-20261027')
before = source_receipt()
lewm_before = dict(head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=LEWM,text=True).strip(),
    status=subprocess.check_output(['git','status','--porcelain'],cwd=LEWM,text=True))
write('SOURCE.json',before)
write('INPUTS.json',dict(command=command,cwd=str(LEWM),source=before['sha256'],
    original_input=dict(uri=str(OLD),sha256=sha256(OLD.read_bytes()).hexdigest()),
    environment={k:v for k,v in env.items() if k.startswith(('SCAR_','LEWM_','PYTHON'))},
    recording_seconds=120,total_seconds=240,native_OS_witness_resources=False,
    baseline_not_repeated=True,reference_times_are_instrumented=[104.85,302.0469],lewm_before=lewm_before))
assert not TRACE.exists(), 'fresh diagnostic trace required'
started = time.monotonic()
target_identity = None
signals = []
hard_stop = False
with (ROOT/'stdout.txt').open('xb') as stdout, (ROOT/'stderr.txt').open('xb') as stderr:
    process = subprocess.Popen(command,cwd=LEWM,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
    write('RUNNING.json',dict(cli_pid=process.pid,process_group=process.pid,started_monotonic=started))
    while True:
        elapsed = time.monotonic()-started
        if target_identity is None and process.poll() is None:
            try:
                children = (Path('/proc')/str(process.pid)/'task'/str(process.pid)/'children').read_text().split()
            except OSError:
                children = []
            for raw_pid in children:
                candidate = identity(int(raw_pid))
                if candidate is not None and candidate['parent_pid']==process.pid and candidate['process_group']==process.pid:
                    target_identity = candidate
                    write('TARGET.json',candidate)
                    break
        if elapsed>=120 and not signals:
            if target_identity is not None and same_live(target_identity):
                current = identity(target_identity['pid'])
                if current['parent_pid']==process.pid and current['process_group']==process.pid:
                    os.kill(target_identity['pid'],signal.SIGINT)
                    signals.append(dict(signal='SIGINT',pid=target_identity['pid'],elapsed_seconds=elapsed,
                                        identity=current,reason='RECORDING_DIAGNOSTIC_LIMIT'))
                    write('SIGNALS.json',signals)
            else:
                signals.append(dict(signal='NO_LIVE_TARGET_AT_RECORDING_LIMIT',elapsed_seconds=elapsed))
        if process.poll() is not None and not same_live(target_identity):
            break
        if elapsed>=240:
            hard_stop = True
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            signals.append(dict(signal='SIGKILL',process_group=process.pid,elapsed_seconds=elapsed,
                                reason='OWNED_DIAGNOSTIC_TOTAL_LIMIT'))
            write('SIGNALS.json',signals)
            break
        time.sleep(.1)
    returncode = process.wait()
# Any detached backend not joining its target is outside this diagnostic's completion claim.
lewm_after = dict(head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=LEWM,text=True).strip(),
    status=subprocess.check_output(['git','status','--porcelain'],cwd=LEWM,text=True))
after = source_receipt()
result = dict(status='DIAGNOSTIC_TERMINAL',cli_returncode=returncode,elapsed_seconds=time.monotonic()-started,
    hard_total_limit=hard_stop,signals=signals,target=target_identity,
    source_unchanged=after==before,lewm_unchanged=lewm_before==lewm_after,
    model_complete=False,clean_baseline_or_speedup=False)
write('ACTUAL_TERMINAL.json',result)
print(json.dumps(result),flush=True)

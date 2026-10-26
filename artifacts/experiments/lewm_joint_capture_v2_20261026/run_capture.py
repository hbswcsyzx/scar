"""One ordinary main CLI capture. No retry, source lowering or native import."""
from pathlib import Path
import hashlib,json,os,resource,signal,subprocess,time

CONTROL=Path(__file__).resolve().parent
command=json.loads((CONTROL/'COMMAND.json').read_text())
assert resource.getrlimit(resource.RLIMIT_AS)==(resource.RLIM_INFINITY,resource.RLIM_INFINITY), 'finite RLIMIT_AS forbidden'
payload=Path(command['payload_directory'])
assert not payload.exists(), 'unique capture output already exists; never relaunch'
assert not (CONTROL/'STARTED.json').exists(), 'this command was already launched'
for item in command['source_receipts']:
    path=Path(item['path'])
    assert path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],path
env={k:v for k,v in os.environ.items() if not k.startswith('SCAR_')}
env.update(command['environment'])
assert 'SCAR_RESOURCE_SAMPLER' not in env and '--resources' not in command['cli_argv']
payload.mkdir()
started=time.monotonic()
with (CONTROL/'stdout.txt').open('xb') as stdout,(CONTROL/'stderr.txt').open('xb') as stderr:
    child=subprocess.Popen(command['cli_argv'],cwd=command['cwd'],env=env,stdout=stdout,stderr=stderr,start_new_session=True)
    record={'wrapper_pid':os.getpid(),'cli_pid':child.pid,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'cwd':command['cwd'],'rlimit_as':list(resource.getrlimit(resource.RLIMIT_AS)),'automatic_retries':0}
    (CONTROL/'STARTED.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'stage':'CLI_STARTED',**record}),flush=True)
    timed_out=False
    while True:
        try:
            code=child.wait(timeout=20)
            break
        except subprocess.TimeoutExpired:
            elapsed=time.monotonic()-started
            progress={'stage':'ORDINARY_CLI_RUNNING','cli_pid':child.pid,'elapsed_s':elapsed}
            with (CONTROL/'progress.jsonl').open('a') as stream:stream.write(json.dumps(progress)+'\n')
            print(json.dumps(progress),flush=True)
            if elapsed>command['outer_seconds']:
                timed_out=True
                os.killpg(child.pid,signal.SIGTERM)
                try:code=child.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);code=child.wait()
                break
changed=[]
for item in command['source_receipts']:
    path=Path(item['path'])
    if path.stat().st_size!=item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:changed.append(str(path))
result={'status':'ACTUAL_CLI_EXITED','cli_returncode':code,'cli_pid':child.pid,
    'elapsed_seconds':time.monotonic()-started,'outer_timeout':timed_out,'source_receipt_changes':changed,
    'automatic_retries':0,'whole_model_complete':False,'payload_directory':str(payload)}
(CONTROL/'ACTUAL_TERMINAL.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(code if not changed else 1)

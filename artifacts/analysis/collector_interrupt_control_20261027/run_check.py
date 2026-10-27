import json,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sources=[('before',Path('/home/zyf/AAA/scar-worktrees/os-postprocessing-roles/artifacts/experiments/lewm_collector_helper_timing_20261027/diagnostic-source')),
         ('after',Path(__file__).resolve().parents[3])]
rows=[]
for label,source in sources:
    root=HERE/('attempt02-'+label);root.mkdir()
    environment={k:v for k,v in os.environ.items()if not k.startswith('SCAR_')}
    environment.update(PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1')
    start=time.monotonic()
    with (root/'stdout.txt').open('xb')as out,(root/'stderr.txt').open('xb')as err:
        process=subprocess.run([sys.executable,'-B',str(HERE/'signal_loop.py'),str(root)],
            env=environment,stdout=out,stderr=err,timeout=10)
    result=json.loads((root/'RESULT.json').read_text())
    rows.append(dict(label=label,exit_code=process.returncode,elapsed_seconds=time.monotonic()-start,result=result))
assert rows[0]['exit_code']==0 and rows[0]['result']['sigint_sent'] and rows[0]['result']['loop_completed']
assert rows[1]['exit_code']==-2 and rows[1]['result']['sigint_sent'] and rows[1]['result']['keyboard_interrupt_reached_program']
assert not rows[1]['result']['loop_completed']
(HERE/'COMPARISON.json').write_text(json.dumps({'status':'PASS','runs':rows},indent=2)+'\n')
print(json.dumps({'status':'PASS','runs':rows}))

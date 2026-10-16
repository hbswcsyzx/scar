from __future__ import annotations
import hashlib,json,os
from pathlib import Path
import subprocess,sys,time
BASE=Path(__file__).resolve().parent
ROOT=Path('/tmp/scar-call-operands-fe9ytsud')
env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
for key in tuple(env):
 if key.startswith('SCAR_'): env.pop(key)
commands=[]
for case in ('loop','exception','handler','callback','generator','method','perf'):
 for mode,masks in ((('dense','keep'),('sparse','keep'),('sparse','toggle')) if case=='perf' else (('sparse','keep'),)):
  args=[sys.executable,str(BASE/'probe.py'),case,mode,masks]
  start=time.perf_counter(); p=subprocess.run(args,cwd=BASE,env=env,capture_output=True,timeout=30)
  stem=case+'-'+mode+'-'+masks
  (BASE/(stem+'.stdout')).write_bytes(p.stdout);(BASE/(stem+'.stderr')).write_bytes(p.stderr)
  record={'argv':args,'cwd':str(BASE),'returncode':p.returncode,'elapsed_seconds':time.perf_counter()-start,'stdout':stem+'.stdout','stderr':stem+'.stderr'}
  if p.returncode==0:
   result=json.loads(p.stdout)
   (BASE/(stem+'.json')).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
   record.update({key:result[key] for key in ('case','mode','mask_lifecycle','instruction_callback_count','disable_returns','selected_instruction_callback_count','missing_owner','spliced_accepted_windows')})
   record['windows']=len(result['windows']);record['all_sparse_windows_complete']=all(x['sparse_match'] for x in result['windows'])
   record['all_oracle_windows_contiguous']=all(x['oracle_match'] is not False for x in result['windows'])
  commands.append(record)
  (BASE/'result.commands.json').write_text(json.dumps(commands,indent=2,sort_keys=True)+'\n')
  print(json.dumps(record),flush=True)

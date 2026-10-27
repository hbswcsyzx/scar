"""Two owned CPU lifecycle checks; no Torch/LeWM or graph construction."""
import json,os,sys,time
from pathlib import Path
from scar.trace.os_capture_launch import OSCaptureBudgets,launch_os_capture

ROOT=Path(__file__).resolve().parent
TREE=ROOT.parents[2]
results=[]
for name in ('converting','manual_close'):
    capture=ROOT/name/'capture';(capture/'trace').mkdir(parents=True)
    env={k:v for k,v in os.environ.items()if not k.startswith('SCAR_')}
    env.update(PYTHONPATH=str(TREE),PYTHONDONTWRITEBYTECODE='1',
        SCAR_TRACE_DIR=str(capture/'trace'),SCAR_TRACE_CALL_EDGES='1',
        SCAR_CALL_PROJECT_ROOT=str(ROOT/'programs'),SCAR_EXECUTION_EVIDENCE='1',
        SCAR_CAPTURE_TRANSPORT='snapshot',SCAR_CALL_MAX_EVENTS='20000',SCAR_CALL_MAX_BYTES='8000000')
    budget=OSCaptureBudgets(max_os_bytes=16000000,max_raw_bytes=32000000,
        max_stored_bytes=16000000,max_os_lines=100000,max_files=128,max_seconds=3)
    started=time.monotonic()
    result,receipt=launch_os_capture([sys.executable,'-B',str(ROOT/'programs'/(name+'.py'))],
        env=env,capture_root=capture,budgets=budget,selection_profile='program-interfaces',postprocess_seconds=8)
    launch=json.loads(Path(receipt['uri']).read_text())
    row={'case':name,'returncode':result.returncode,'elapsed_seconds':time.monotonic()-started,
        'budget_stop':launch['budget_stop'],'phase_tracking':launch['phase_tracking'],'launch':receipt}
    results.append(row)
    (ROOT/(name+'-result.json')).write_text(json.dumps(row,indent=2)+'\n')
assert results[0]['returncode']==0 and results[0]['elapsed_seconds']>3 and results[0]['budget_stop']is None
assert results[0]['phase_tracking']['qualified_atexit'] and 'CONVERTING'in results[0]['phase_tracking']['events']
assert results[1]['returncode']!=0 and results[1]['budget_stop']=='RECORDING_SECONDS'
assert not results[1]['phase_tracking']['qualified_atexit']
(ROOT/'RESULT.json').write_text(json.dumps({'status':'PASS','cases':results,
    'recording_seconds':3,'postprocess_seconds':8,'LeWM_or_Torch':False,
    'whole_program_model_complete':False},indent=2)+'\n')
print(json.dumps({'status':'PASS','results':results}),flush=True)

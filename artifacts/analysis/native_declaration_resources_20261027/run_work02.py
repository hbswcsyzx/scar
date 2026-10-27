import hashlib,json,pathlib,threading,time,traceback
from scar.trace.native_work_bridge import acquire_native_activity_work,NativeWorkBudget
BASE=pathlib.Path(__file__).resolve().parent
MAIN=pathlib.Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
started=time.monotonic();stop=threading.Event()
def heartbeat():
 while not stop.wait(20):print(json.dumps({'stage':'ACQUIRE_WORK_LIVE','elapsed_s':time.monotonic()-started}),flush=True)
threading.Thread(target=heartbeat,daemon=True).start()
try:
 result=acquire_native_activity_work(MAIN/'artifacts/experiments/lewm_joint_capture_20261026/capture',MAIN/'artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions/manifest.json',BASE/'work-attempt02',budgets=NativeWorkBudget(max_input_bytes=8_000_000_000,max_os_lines=3_200_000))
 (BASE/'WORK_RESULT02.json').write_text(json.dumps({'actual_status':'RETURNED','elapsed_s':time.monotonic()-started,'result':result},indent=2)+'\n')
 print(json.dumps({'status':'RETURNED','qualified':result['qualified_single_activities'],'candidates':result['all_gpu_candidates'],'io':result['io']}),flush=True)
except BaseException as e:
 (BASE/'WORK_TERMINAL_FAILURE02.json').write_text(json.dumps({'actual_status':'FAILED','elapsed_s':time.monotonic()-started,'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()},indent=2)+'\n');raise
finally:stop.set()

from pathlib import Path
import json,time,sys,traceback
from scar.trace.capture_import import import_capture
D=Path(__file__).resolve().parent
t=time.monotonic()
try:
 r=import_capture('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_joint_capture_20261026/capture',D/'native-import',max_bytes=4000000000,max_lines=6000000,schema_contracts=True,bundle_partitions=True,components=('native',),progress=lambda v:print(json.dumps(v),flush=True))
 (D/'import-result.json').write_text(json.dumps({'status':'ACTUAL_NATIVE_COMPONENT_IMPORTED_WITH_OPEN','elapsed_seconds':time.monotonic()-t,'capture_model':str(D/'native-import/capture-model.json'),'component_scope':r['component_scope'],'native':r['native'],'whole_model_established':False,'new_target_runs':0},indent=2)+'\n')
except BaseException as e:
 (D/'import-FAILURE.json').write_text(json.dumps({'error':str(e),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-t},indent=2)+'\n');raise

from pathlib import Path
import json,time,hashlib,copy,traceback,sys
from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.trace.native_capture_batch import NativeCaptureBatchBudget,bind_native_capture_batches
from scar.trace.native_input_index import NativeInputIndexBudget,query_native_input_associations
D=Path(__file__).resolve().parent
C=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_joint_capture_20261026/capture')
t=time.monotonic();negative={}
def progress(v):
 if v.get('stage')=='actual_group' and v.get('visited_actual_groups',0)%1000:return
 (D/'bind-progress.json').write_text(json.dumps(dict(v,whole_seconds=time.monotonic()-t),indent=2)+'\n')
def checked(shard,session,associations):
 if not negative and len(associations)>=2:
  wrong=copy.deepcopy(associations);wrong[0]['original_input']=copy.deepcopy(associations[1]['original_input'])
  try:session.check(shard,wrong)
  except ValueError as e:negative.update(status='REJECTED_BY_INDEPENDENT_SOURCE_SLOT_CHECK',error=str(e),original=associations[0]['original_input'],replacement=associations[1]['original_input'])
  else:raise AssertionError('actual wrong input source accepted')
  (D/'negative.json').write_text(json.dumps(negative,indent=2)+'\n')
try:
 progress({'phase':'GENUINE_PUBLIC_BINDER'})
 coordinates=bind_capture_coordinates(C,max_bytes=4000000000,max_lines=6000000,profile_uri=str(C/'capture-coordinates.json'))
 model=D/'native-import/capture-model.json';doc=json.loads(model.read_bytes());part=Path(doc['native_bundle_storage']['manifest'])
 result=bind_native_capture_batches(coordinates,C,part,D/'native-input-connections',expected_manifest_sha256=hashlib.sha256(part.read_bytes()).hexdigest(),capture_model_path=model,expected_capture_model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),budget=NativeCaptureBatchBudget(max_wall_seconds=2400),input_metadata_budget=NativeInputIndexBudget(),progress=progress,on_verified_input_shard=checked)
 association=result.report['native_input_metadata'];manifest=association['artifact']
 q=query_native_input_associations(manifest['uri'],expected_sha256=manifest['sha256'],limit=3,associations=True)
 (D/'association-query.local-only.json').write_text(json.dumps(q,indent=2)+'\n')
 summary={'status':'ACTUAL_FULL_NATIVE_INPUT_ASSOCIATIONS_WITH_OPEN','native':{k:v for k,v in result.report.items() if k not in ('shards','actual_sequence_ids')},'associations':association,'negative':negative,'whole_elapsed_seconds':time.monotonic()-t,'target_runs_added':0,'whole_model_established':False}
 (D/'result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'status':summary['status'],'association_counts':association['counts'],'whole_elapsed_seconds':summary['whole_elapsed_seconds']}))
except BaseException as e:
 (D/'bind-FAILURE.json').write_text(json.dumps({'type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-t},indent=2)+'\n');raise

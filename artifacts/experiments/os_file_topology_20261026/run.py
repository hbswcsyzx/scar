from pathlib import Path
import json,time,traceback,hashlib,sys,gzip
from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.analysis.os_file_topology import connect_os_file_topology,query_os_file_topology
from scar.ir.record_codec import decode
from scar.ir.execution.resources import ResourceInstance,HandleBinding,ProviderResourceAccess
from scar.ir.execution.work import WorkSubmission,ResourceOutcome
D=Path(__file__).resolve().parent
C=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_joint_capture_20261026/capture')
t=time.monotonic()
def progress(value):
 (D/'progress.json').write_text(json.dumps(dict(value,elapsed_seconds=time.monotonic()-t),indent=2)+'\n')
try:
 progress({'phase':'GENUINE_PUBLIC_BINDER'})
 coordinates=bind_capture_coordinates(C,max_bytes=4000000000,max_lines=6000000,profile_uri=str(C/'capture-coordinates.json'))
 built=connect_os_file_topology(coordinates,C,D/'connections',progress=progress)
 results={}
 for key,path in [('checkpoint','checkpoints/pusht/weights.pt'),('dataset','pusht_expert_train.h5'),('outputs','lewm-output'),('complete',None)]:
  q=query_os_file_topology(built['artifact']['uri'],path=path,limit=3 if path else 1000)
  if path is None:
   complete=[r for r in q['matches'] if r['resource_path']]
   q['matches']=complete[:3];q['sample_filter']='first1000selected normalized file uses, then complete backing paths'
  results[key]=q
 (D/'queries.local-only.json').write_text(json.dumps(results,indent=2)+'\n')
 m=json.loads(Path(built['artifact']['uri']).read_bytes());types={'resources':ResourceInstance,'handles':HandleBinding,'submissions':WorkSubmission,'outcomes':ResourceOutcome,'provider_accesses':ProviderResourceAccess};checked=[]
 for table,cls in types.items():
  chunks=m['tables'][table]['chunks']
  if chunks:
   p=Path(built['artifact']['uri']).parent/'records'/chunks[0]['path'];row=json.loads(gzip.decompress(p.read_bytes()).splitlines()[0]);decode(cls,row['record']);checked.append(table)
 summary=dict(built,whole_elapsed_seconds=time.monotonic()-t,typed_decode_tables=checked,Torch_imported='torch' in sys.modules,target_runs_added=0,queries={k:{'matches':len(v['matches']),'statuses':[r['status'] for r in v['matches']],'source_work_ids':[r['observation'].get('work_ticket') for r in v['matches']]} for k,v in results.items()},producer_sources=[{'uri':str(Path(sys.modules[n].__file__)),'sha256':hashlib.sha256(Path(sys.modules[n].__file__).read_bytes()).hexdigest()} for n in ('scar.trace.os_resources','scar.analysis.os_file_topology')])
 (D/'result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
except BaseException as e:
 (D/'FAILURE.json').write_text(json.dumps({'type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-t},indent=2)+'\n');raise

"""One retained real native-input endpoint; no raw scan/target/body batch."""
from hashlib import sha256
import json,os,resource,sys,time,traceback
from pathlib import Path
from scar.analysis.native_input_storage_bridge import query_native_input_allocation
from scar.ir.program.providers import ProviderArtifact
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.record_codec import decode
BASE=Path(__file__).resolve().parent
original=json.loads((BASE/'attempt01'/'QUERY.json').read_text())
selected_execution=decode(ProviderArtifact,original['canonical_parent']['execution'])
selected_occurrence=decode(ValueOccurrenceID,original['value_occurrence'])
NAV=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/native_inputs_full_20261026/attempt05/port-navigation/manifest.json')
INDEX=Path('/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/tensor_gpu_reference_query_20261026/locator-index/manifest.json')
nav=ProviderArtifact(str(NAV),'4436b171be0dec2782e7843bc097227d675efa5e33155a6e8a2bf2408b4b6f72',146783,'scar.native-input-port-navigation')
index=ProviderArtifact(str(INDEX),'d127c95a2ff1b1d848288c83ef3cb3785f55f0f2c68d0918f3ef7d280b1de7c2',499687,'scar.tensor-storage-locator-index')
counts={'raw_capture_opens':[],'live_source_opens':[],'target_exec':0,'capture':0}
def audit(event,args):
 if event=='open'and args and isinstance(args[0],(str,bytes,os.PathLike)):
  p=os.fsdecode(args[0]);name=Path(p).name
  if '/capture/trace/'in p or '/capture/os/'in p:
   counts['raw_capture_opens'].append(p);raise AssertionError('raw replay forbidden')
  if p.startswith('/home/zyf/AAA/le-wm/'):
   counts['live_source_opens'].append(p);raise AssertionError('live target source forbidden')
 if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
  counts['target_exec']+=1;raise AssertionError('target exec forbidden')
sys.addaudithook(audit)
started=time.monotonic();result={}
try:
 view=query_native_input_allocation(nav,index,value_occurrence=selected_occurrence,execution=selected_execution,derive_region=True,max_input_bytes=256000000,max_seconds=60)
 assert view['geometry']['status']=='DERIVED_UNIQUE_OFFSET_UNDER_VALID_TENSOR_PROTOCOL'
 assert view['geometry']['region']['offset']==0
 assert view['geometry']['constraints']['bounding_span_bytes']==view['geometry']['constraints']['allocation_extent_bytes']==4
 assert view['observed_metadata']['storage_offset'] is None
 assert not view['geometry']['offset_observed']
 assert view['selector']['row']==21 and view['selector']['path']==[0]
 assert view['allocation']['metadata']['provider_allocation_id']==1
 assert view['new_graph_nodes']==0 and not view['logical_version_established']
 assert not counts['raw_capture_opens']and not counts['live_source_opens']and counts['target_exec']==0
 raw=json.dumps(view,sort_keys=True,indent=2,ensure_ascii=False).encode()+b'\n'
 (BASE/'region01/QUERY.json').write_bytes(raw)
 result={'status':'PASS','query':{'uri':str(BASE/'region01/QUERY.json'),'bytes':len(raw),'sha256':sha256(raw).hexdigest()},
  'measurements':view['measurements'],'row':view['selector'],'run':view['run'],'process':view['process'],
  'allocation':view['allocation_target'],'device':view['allocation']['device'],'nbytes':view['allocation']['nbytes'],
  'geometry':view['geometry'],
  'graph_nodes_created':0,'logical_version_established':False,'materialization':None}
except BaseException as error:
 result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 result.update(audit=counts,wall_seconds=time.monotonic()-started,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
  source_sha256=sha256(Path('scar/analysis/native_input_storage_bridge.py').read_bytes()).hexdigest())
 (BASE/'region01/RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps(result,sort_keys=True,indent=2))
 if result['status']!='PASS':sys.exit(1)

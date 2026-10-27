from pathlib import Path
from hashlib import sha256
import json,os,resource,sys,time,traceback
from scar.analysis.native_tensor_reads import build_native_tensor_read, read_native_tensor_read
from scar.ir.record_codec import decode, encode
from scar.ir.program.providers import ProviderArtifact
B=Path(__file__).resolve().parent
inputs=json.loads(Path('/home/zyf/AAA/scar-worktrees/native-input-storage-bridge/artifacts/analysis/native_input_storage_bridge_20261027/INPUTS.json').read_bytes())
nav=decode(ProviderArtifact,inputs['navigation']);index=decode(ProviderArtifact,inputs['storage_index'])
checks={'raw_opens':[],'live_source_opens':[],'target_exec':0}
def audit(event,args):
 if event=='open'and args and isinstance(args[0],(str,bytes,os.PathLike)):
  p=os.fsdecode(args[0])
  if '/capture/trace/'in p or '/capture/os/'in p:checks['raw_opens'].append(p);raise AssertionError('raw replay forbidden')
  if p.startswith('/home/zyf/AAA/le-wm/'):checks['live_source_opens'].append(p);raise AssertionError('live target source forbidden')
 if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
  checks['target_exec']+=1;raise AssertionError('target exec forbidden')
sys.addaudithook(audit);start=time.monotonic();result={}
try:
 artifact=build_native_tensor_read(nav,index,B/'attempt02/read',row=53,path=(1,),max_input_bytes=256_000_000,max_seconds=60)
 record,values,read_measurements=read_native_tensor_read(artifact,max_input_bytes=256_000_000,max_seconds=60)
 assert record.read.basis.position==1 and len(record.read.support)==1
 assert record.result.version in values.versions and len(values.versions)==1
 assert not values.materializations and not values.allocations
 assert len(values.provenance)==1
 assert record.read.effect.post.formal.value.endswith(':9:outputs:1')
 assert record.read.support[0].value.endswith(':9:inputs:3')
 assert not checks['raw_opens']and not checks['live_source_opens']and not checks['target_exec']
 result={'status':'PASS','artifact':encode(artifact),'read':encode(record),'values_counts':values.validate()['counts'],
 'reader_measurements':read_measurements,
 'numeric_values_stored':False,'actual_memory_read_observed':False,'qualification':'CONDITIONAL_READ_RESULT'}
except BaseException as error:
 result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 result.update(wall_seconds=time.monotonic()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,audit=checks,
 source_sha256={str(p):sha256(p.read_bytes()).hexdigest()for p in (Path('scar/analysis/native_tensor_reads.py'),Path('scar/ir/execution/native_tensor_reads.py'))})
 (B/'attempt02/RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result,sort_keys=True,indent=2))
 if result['status']!='PASS':sys.exit(1)

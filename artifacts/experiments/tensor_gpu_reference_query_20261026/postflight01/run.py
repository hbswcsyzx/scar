from pathlib import Path
from hashlib import sha256
import importlib.util,sys,json,time,resource,traceback,threading
import scar.analysis
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project');MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
spec=importlib.util.spec_from_file_location('scar.analysis.tensor_storage_index',ISO/'scar/analysis/tensor_storage_index.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode,decode
ROOT=Path(__file__).resolve().parent
fragment=Path('/home/zyf/AAA/scar-worktrees/frame-entry-routing/artifacts/analysis/native_operator_value_interface_20261026/publication-v3/operator-values.json')
f=json.loads(fragment.read_text())['fragment'];bundle=decode(ProviderArtifact,f['bundle_manifest']);eto=decode(ProviderArtifact,f['eto_source'])
capture=MAIN/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-model.json';capture=ProviderArtifact(str(capture),sha256(capture.read_bytes()).hexdigest(),capture.stat().st_size,'scar.capture-model')
start=time.monotonic();phase='normal-indexed-query-only';done=threading.Event()
def beat():
 while not done.wait(20):print(json.dumps({'phase':phase,'elapsed_s':time.monotonic()-start}),flush=True)
threading.Thread(target=beat,daemon=True).start()
source_files=[Path(module.__file__)]+[Path(sys.modules[n].__file__) for n in ('scar.analysis.tensor_storage_query','scar.store.bundle_partitions','scar.ir.record_codec','scar.ir.v2.evidence','scar.ir.v2.values')]
source_shas={str(p):sha256(p.read_bytes()).hexdigest() for p in source_files}
(ROOT/'INPUTS.json').write_text(json.dumps({'bundle':encode(bundle),'capture_model':encode(capture),'eto_source_namespace_only':encode(eto),'index_input_bytes':2_050_000_000,'index_seconds':180,'index_output_bytes':200_000_000,'query_input_bytes':180_000_000,'query_seconds':60,'source_shas':source_shas,'no_capture_target_or_EO_read':True},indent=2)+'\n')
try:
 index_path=Path('/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/tensor_gpu_reference_query_20261026/locator-index/manifest.json')
 index=ProviderArtifact(str(index_path),sha256(index_path.read_bytes()).hexdigest(),index_path.stat().st_size,'scar.tensor-storage-locator-index')
 phase='mechanical-cuda-query'
 result=module.query_tensor_storage_source(index)
 assert result['storage_region']['device'].split(':')[0]=='cuda'
 assert source_shas=={str(p):sha256(p.read_bytes()).hexdigest() for p in source_files}
 (ROOT/'QUERY.json').write_text(json.dumps(result,indent=2)+'\n')
 (ROOT/'RESULT.json').write_text(json.dumps({'status':'PASS_ORIGINAL_LEWM_CUDA_STORAGE_QUERY','index':encode(index),'query_measurements':result['measurements'],'device':result['storage_region']['device'],'shape':result['storage_region']['shape'],'allocation_bytes':result['allocation']['nbytes'],'run':result['run'],'materialization':None,'new_value_nodes':0,'new_capture_target_or_EO_import':0,'elapsed_seconds':time.monotonic()-start,'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},indent=2)+'\n')
 print((ROOT/'RESULT.json').read_text(),flush=True)
except BaseException as error:
 (ROOT/'FAILURE.json').write_text(json.dumps({'phase':phase,'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-start},indent=2)+'\n');raise
finally:done.set()

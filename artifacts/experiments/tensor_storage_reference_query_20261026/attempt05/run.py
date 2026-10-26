from pathlib import Path
from hashlib import sha256
import importlib.util,sys,time,json,traceback,resource
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project')
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
import scar.analysis
spec=importlib.util.spec_from_file_location('scar.analysis.tensor_storage_query',ISO/'scar/analysis/tensor_storage_query.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode
ROOT=Path(__file__).resolve().parent
fragment=Path('/home/zyf/AAA/scar-worktrees/frame-entry-routing/artifacts/analysis/native_operator_value_interface_20261026/publication-v3/operator-values.json')
capture=MAIN/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-model.json'
def artifact(p,schema):return ProviderArtifact(str(p),sha256(p.read_bytes()).hexdigest(),p.stat().st_size,schema)
start=time.monotonic()
needed=[Path(module.__file__)]+[Path(sys.modules[name].__file__) for name in ('scar.trace.native_operator_value_interface','scar.trace.native_port_sidecar','scar.trace.native_reference_flow','scar.trace.native_capture_batch','scar.store.bundle_partitions','scar.ir.record_codec')]
before={str(p):sha256(p.read_bytes()).hexdigest() for p in needed}
(ROOT/'INPUTS.json').write_text(json.dumps({'fragment':encode(artifact(fragment,'scar.native-operator-value-interface')),'capture_model':encode(artifact(capture,'scar.capture-model')),'candidate_index':0,'max_stored_plus_decoded_bytes':512_000_000,'max_seconds':180,'source_shas':before,'no_new_graphs':True,'no_raw_EO_or_target':True},indent=2)+'\n')
try:
 result=module.query_tensor_storage_observation(artifact(fragment,'scar.native-operator-value-interface'),artifact(capture,'scar.capture-model'))
 assert before=={str(p):sha256(p.read_bytes()).hexdigest() for p in needed}
 (ROOT/'QUERY.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 (ROOT/'RESULT.json').write_text(json.dumps({'status':'PASS_ORIGINAL_LEWM_OBSERVATION_REFERENCE_STORAGE_QUERY','new_value_nodes':0,'new_materializations':0,'target_executions':0,'raw_sources_read':False,'elapsed_seconds':time.monotonic()-start,'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'measurements':result['measurements'],'run':result['binding']['run'],'process':result['binding']['process'],'marker':result['marker_instance']['id'],'storage_region':result['storage_region']['id'],'allocation':result['allocation']['id']},indent=2)+'\n')
 print((ROOT/'RESULT.json').read_text())
except BaseException as error:
 (ROOT/'FAILURE.json').write_text(json.dumps({'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-start},indent=2)+'\n');raise

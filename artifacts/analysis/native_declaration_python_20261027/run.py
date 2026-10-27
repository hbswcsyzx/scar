from pathlib import Path
import hashlib,json,threading,time,traceback
from scar.analysis.native_declaration_interfaces import read_native_declaration_fragment,NativeDeclarationBudget
from scar.analysis.native_declaration_python import NativeDeclarationPythonSession,NativePythonBudget
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode,encode,loads
from scar.ir.v2.ids import OperationInstanceID
B=Path(__file__).resolve().parent;OLD=B.parent/'native_declaration_resources_20261027';M=Path('/home/zyf/AAA/scar-worktrees/structured-program-model');start=time.monotonic();stop=threading.Event()
def artifact(p,s):
 raw=p.read_bytes();return ProviderArtifact(str(p),hashlib.sha256(raw).hexdigest(),len(raw),s)
def beat():
 while not stop.wait(20):print(json.dumps({'phase':'SOURCE_INDEX_OR_QUERY_LIVE','elapsed_s':time.monotonic()-start}),flush=True)
threading.Thread(target=beat,daemon=True).start()
try:
 p=Path('scar/analysis/native_declaration_python.py').resolve();source=p.read_bytes()
 prior=loads((OLD/'CONNECTION_RESULT04.json').read_text())
 view=read_native_declaration_fragment(decode(ProviderArtifact,prior['native_fragment']),budget=NativeDeclarationBudget(max_input_bytes=512_000_000,max_seconds=180))
 report=artifact(M/'artifacts/experiments/native_inputs_full_20261026/attempt05/native-input-connections/report.json','scar.native-capture-batch')
 model=artifact(M/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-model.json','scar.capture-model')
 coords=decode(ProviderArtifact,prior['coordinates'])
 with NativeDeclarationPythonSession(report,model,coords,budget=NativePythonBudget())as session:
  result=session.query_view(view,source_instances=(decode(OperationInstanceID,prior['selected_native_instance']),))
  assert len(result['connections'])==1 and result['connections'][0].invocation is not None and result['connections'][0].captured_code is not None,'real native did not resolve to retained Python code context'
  payload=(json.dumps(encode(result),indent=2)+'\n').encode();(B/'CONNECTION.json').write_bytes(payload)
  c=result['connections'][0]
  summary={'actual_status':'SAME_RUN_ENCLOSING_PYTHON_CONTEXT','elapsed_s':time.monotonic()-start,'native_reader_measurements':view.measurements,
   'source_session_initial_measurements':session.initial_measurements,'source_session_measurements':result['measurements'],'query_measurements':result['query_measurements'],
   'native':encode(c.native.native),'canonical_invocation':encode(c.native.invocation),'parent_path_length':len(c.control_path),
   'dispatch_context':encode(c.dispatch_context),'python_invocation':encode(c.invocation),'captured_code':encode(c.captured_code),
   'parent_denominator':result['parent_inventory_denominator'],'dispatch_span_denominator':result['dispatch_span_denominator'],'call_invocation_denominator':result['call_invocation_denominator'],'captured_code_denominator':result['captured_code_denominator'],
   'source':{'path':str(p),'bytes':len(source),'sha256':hashlib.sha256(source).hexdigest()},'inputs':{'batch':encode(report),'capture_model':encode(model),'coordinates':encode(coords),'native_fragment':prior['native_fragment']},
   'connection_bytes':len(payload),'connection_sha256':hashlib.sha256(payload).hexdigest(),'direct_call_established':False,'source_text_compiler_match_established':False,'whole_model_established':False}
  assert p.read_bytes()==source,'producer source changed during real reader'
 (B/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
except BaseException as e:
 (B/'FAILURE.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_s':time.monotonic()-start},indent=2)+'\n');raise
finally:stop.set()

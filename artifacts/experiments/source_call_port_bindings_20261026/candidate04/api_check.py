from pathlib import Path
import ast,inspect,json
from scar.analysis.current_source_evidence import connect_current_capture
from scar.analysis.call_operands import link_call_operands,_link_call_operands_owned
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_body_access import SourceBodyAccess
from scar.analysis.code_witness import CodeWitnessStore
from scar.ir.program.source_call_bindings import SourceCallPortModel
from port_consumer import PortConsumer
import pickle,_compat_pickle,uuid,_uuid
p=Path(__file__).resolve().parent
for f in p.glob('*.py'):ast.parse(f.read_bytes(),filename=str(f))
for function in (connect_current_capture,link_call_operands):
 s=inspect.signature(function)
 for name in ('source_port_consumer','source_port_budget'):
  assert s.parameters[name].default is None and s.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
for name in ('original_code_source_origin','require_source_membership_ancestor','source_membership_query_counts'):
 assert callable(getattr(CompositionIndex,name))
result={'status':'PASS_REQUIRED_PUBLIC_OWNED_API_AND_RUNNER_IMPORTS_NO_INPUTS','new_forward_parameters':'keyword-only default None','composition_apis':['original_code_source_origin','require_source_membership_ancestor','source_membership_query_counts'],'normal_readers_imported':True,'graphs_opened':False,'raw_read':False,'target_exec':False,'source_prepare':False,'compile_calls':0}
with (p/'API_CHECK.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(result))

"""Actual retained models only; no capture/raw replay or source lowering."""
from pathlib import Path
import gzip,hashlib,json,time
from scar.analysis.call_port_query import query_call_ports
from scar.ir.program.python_call_targets import PythonSourcePortModel

ROOT=Path(__file__).resolve().parent
WORK=Path(__file__).resolve().parents[3]
started=time.monotonic()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):(ROOT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
v2=WORK/'artifacts/experiments/python_call_targets_owned_20261026/case01/model.json'
raw=v2.read_bytes();model=PythonSourcePortModel.loads(raw.decode())
method=next(b for b in model.bindings if b.receiver is not None)
selection={'invocation':method.entry.caller,'actual_index':0,'limit':20}
plain=query_call_ports(v2,expected_sha256=sha(v2),**selection)
assert plain['schema_version']==2 and plain['matched_bindings']==4
assert plain['matching_caller_issues']==3 and all('observed_target' in i for i in plain['issues'])
methods=[b for b in plain['bindings'] if b['receiver'] is not None]
assert len(methods)==2 and all('index' not in b['receiver'] for b in methods)
assert all(b['arguments'][0]['index']==0 and b['receiver']['formal_name']=='receiver'
    and b['arguments'][0]['formal_name']=='value' for b in methods)
archive=ROOT/'model-v2.json.gz'
with archive.open('xb') as stream:
    with gzip.GzipFile(filename='',fileobj=stream,mode='wb',mtime=0) as zipped:zipped.write(raw)
compressed=query_call_ports(archive,expected_sha256=sha(archive),**selection)
for field in ('bindings','issues','summary','matched_bindings','matching_caller_issues','selector'):
    assert plain[field]==compressed[field],field
write('v2-plain-query.json',plain);write('v2-gzip-query.json',compressed)
rejections={}
def reject(label,callback,detail):
    try:callback()
    except ValueError as error:
        assert detail in str(error),(label,str(error));rejections[label]=str(error)
    else:raise AssertionError(label+' accepted')
reject('wrong_stored_sha',lambda:query_call_ports(v2,expected_sha256='0'*64),'stored receipt differs')
invalid=ROOT/'invalid-schema.json'
document=json.loads(raw);document['schema']='scar.source-call-port-bindings'
invalid.write_text(json.dumps(document))
reject('illegal_schema_version_pair',lambda:query_call_ports(invalid,expected_sha256=sha(invalid)),'schema/version')
reject('gzip_decode_ceiling',lambda:query_call_ports(archive,expected_sha256=sha(archive),max_decoded_bytes=len(raw)-1),'decoded byte limit')
v1=WORK/'artifacts/experiments/source_call_port_bindings_20261026/candidate04/result/source-ports/model.json.gz'
legacy=query_call_ports(v1,expected_sha256=sha(v1),limit=1)
assert legacy['schema_version']==1 and legacy['matched_bindings']==2516
assert legacy['summary']['attempts']==100550 and legacy['summary']['argument_ports']==6805
assert legacy['qualification']=='RETAINED_CONDITIONAL_SOURCE_USE_TO_FORMAL_PORTS'
assert 'ports' in legacy['bindings'][0] and 'arguments' not in legacy['bindings'][0] and 'receiver' not in legacy['bindings'][0]
assert 'model_transport' not in legacy and 'actual_index_role' not in legacy['selector']
assert not any(legacy[k] for k in ('producer_inputs_replayed','reference_identity_established',
    'contents_state_ready_established','return_routes_implied','whole_program_complete'))
write('v1-query.json',legacy)
result={'status':'PASS','elapsed_seconds':time.monotonic()-started,'v1':{'path':str(v1),'sha256':sha(v1),
    'matched_bindings':legacy['matched_bindings'],'format_unchanged':True},
    'v2':{'path':str(v2),'sha256':sha(v2),'matched_caller_argument0_bindings':plain['matched_bindings'],
    'receiver_records':len(methods),'plain_gzip_equal':True,'caller_issues':plain['matching_caller_issues']},
    'rejections':rejections,'query_source_sha256':sha(WORK/'scar/analysis/call_port_query.py'),
    'producer_inputs_replayed':False,'target_executed':False}
write('RESULT.json',result);print(json.dumps(result,indent=2))

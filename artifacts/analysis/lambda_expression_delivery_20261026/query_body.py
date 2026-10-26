"""Bounded body-only query of the already normally verified original SP5."""
from pathlib import Path
from hashlib import sha256
import gzip,json
from scar.ir.program.codec import loads as graph_loads
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.native import ExitPortRef
from scar.ir.program.model import ReferenceValue,StateVersionValue
from scar.ir.program.source_language import decode_language_overlay,encode_language_overlay
from scar.ir.record_codec import encode
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
run=BASE/'lambda_expression_entry_resume01_20261026'
terminal=run/'worker/attempt-00001/result.json';result=json.loads(terminal.read_bytes());ref=result['program']
path=Path(ref['uri']);stored=path.read_bytes();assert len(stored)==ref['physical_bytes'] and sha256(stored).hexdigest()==ref['physical_sha256']
with gzip.open(path,'rb')as stream:raw=stream.read(64_000_001)
assert len(raw)==ref['decoded_bytes'] and sha256(raw).hexdigest()==ref['decoded_sha256'] and len(raw)<=64_000_000
program=json.loads(raw);graph=graph_loads(json.dumps(program['graph']));index=ProgramIndex(graph)
language=decode_language_overlay(program['language']);assert len(language.lambda_bodies)==1
body=language.lambda_bodies[0];normal=index.exit_port_uses(ExitPortRef(body.body.region,'normal',0));world=index.exit_port_uses(ExitPortRef(body.body.region,'normal',1))
assert len(normal)==len(world)==1 and normal[0].operation==world[0].operation
assert type(index.values[normal[0].use.value])is ReferenceValue and type(index.values[world[0].use.value])is StateVersionValue
creation=index.operations[body.creation];assert creation.callee is None and len(creation.completions[0].types)==2
old=BASE/'set_display_entries_resume01_20261026/worker/attempt-00001/lowered-return.json'
legacy=json.loads(old.read_bytes())['language'];assert 'lambda_bodies'not in legacy
loaded=decode_language_overlay(legacy);encoded=encode_language_overlay(loaded);assert encoded==legacy
records={'status':'ORIGINAL_BODY_ONLY_NORMAL_INDEX_QUERY_WITH_OPEN','program':ref,'normal_reader_terminal':str(terminal),
 'body':encode(body),'normal_payload':encode(normal[0]),'normal_world':encode(world[0]),
 'graph_regions':len(graph.regions),'deferred_body_operations':sum(len(b.operations)for b in index.regions[body.body.region].blocks),
 'creation_python_payload_results':1,'creation_callee':None,'target_field_read_operations':0,
 'original_V1_language_wire_equal':True,'old_language_reference':{'path':str(old),'sha256':sha256(old.read_bytes()).hexdigest()},
 'stored_read_bytes':len(stored),'decoded_read_bytes':len(raw),'source_context_revalidated':False,
 'compile':0,'lower':0,'target':0,'publication':0,'currentRun_binding':0}
(HERE/'BODY_QUERY.json').write_text(json.dumps(records,sort_keys=True,separators=(',',':'))+'\n')
print(json.dumps({k:records[k]for k in('status','graph_regions','deferred_body_operations','creation_python_payload_results','original_V1_language_wire_equal')},sort_keys=True))

OUTPUT='/tmp/scar-structured-model-280qf4mi/tests/fixtures/program_graph_v16_frozen.json'
PROOF='/tmp/scar-structured-model-280qf4mi/tests/fixtures/program_graph_v16_frozen.proof.json'
REVISION='85aee70dd6217e61c03df54ef4ee154b0d662328'

import hashlib,json
from pathlib import Path
import scar.ir.program.codec as codec
import tests.fixtures.program_literals as fixture
root=Path.cwd().resolve()
assert codec.SCHEMA_VERSION == 16
assert Path(codec.__file__).resolve().is_relative_to(root)
assert Path(fixture.__file__).resolve().is_relative_to(root)
graph,_=fixture.literal_program(payload=(1,b"bytes",None,complex(-0.0,2),"\ud800\udc00"))
wire=codec.dumps(graph).encode('utf8')
assert json.loads(wire)['schema_version']==16
assert codec.loads(wire.decode())==graph
Path(OUTPUT).write_bytes(wire)
proof={'source_revision':REVISION,'schema_version':16,'codec_path':'scar/ir/program/codec.py',
 'codec_sha256':hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
 'fixture_source_path':'tests/fixtures/program_literals.py',
 'fixture_source_sha256':hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
 'fixture_factory':'literal_program(payload=(1,b"bytes",None,complex(-0.0,2),"\\ud800\\udc00"))',
 'fixture_bytes':len(wire),'fixture_sha256':hashlib.sha256(wire).hexdigest(),
 'isolation':'immutable git archive; child cwd and PYTHONPATH both archive; assert codec16 and module paths',
 'child_cwd':str(root),'codec_actual_file':str(Path(codec.__file__).resolve()),
 'fixture_actual_file':str(Path(fixture.__file__).resolve()),
 'note':'Historical meaningful literal graph, no F protocol fields. No workload/torch/test execution.'}
Path(PROOF).write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))

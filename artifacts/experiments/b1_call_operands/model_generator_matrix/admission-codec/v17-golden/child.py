OUTPUT='/tmp/scar-structured-model-280qf4mi/tests/fixtures/program_graph_v17_frozen.json'
PROOF='/tmp/scar-structured-model-280qf4mi/tests/fixtures/program_graph_v17_frozen.proof.json'
REVISION='b88670b8720875175550bbb60df42e6089960eca'

import hashlib,json
from pathlib import Path
import scar.ir.program.codec as codec
import tests.fixtures.program_protocol_graphs as fixture
archive=Path.cwd().resolve()
assert codec.SCHEMA_VERSION == 17
assert Path(codec.__file__).resolve().is_relative_to(archive)
assert Path(fixture.__file__).resolve().is_relative_to(archive)
graph,_=fixture.generator_protocol_program(target='value')
wire=codec.dumps(graph).encode('utf8')
assert json.loads(wire)['schema_version']==17
assert codec.loads(wire.decode())==graph
Path(OUTPUT).write_bytes(wire)
proof={
 'source_revision':REVISION,'schema_version':17,
 'codec_path':'scar/ir/program/codec.py',
 'codec_sha256':hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
 'fixture_source_path':'tests/fixtures/program_protocol_graphs.py',
 'fixture_source_sha256':hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
 'fixture_factory':"generator_protocol_program(target='value')",
 'fixture_bytes':len(wire),'fixture_sha256':hashlib.sha256(wire).hexdigest(),
 'isolation':'immutable git archive; child cwd/PYTHONPATH inside archive; assert codec max17 and module paths',
 'child_cwd':str(archive),'codec_actual_file':str(Path(codec.__file__).resolve()),
 'fixture_actual_file':str(Path(fixture.__file__).resolve()),
 'note':'Meaningful original SEND/body Return/StopIteration adapter N/R graph; no admission variant.'}
Path(PROOF).write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))

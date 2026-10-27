"""Generate historical wire from immutable archive, never current product code."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
REVISION = '85aee70dd6217e61c03df54ef4ee154b0d662328'
owned = Path(tempfile.mkdtemp(prefix='scar-protocol-v16-archive-'))
command = ['git', 'archive', REVISION, 'scar', 'tests/fixtures']
(HERE / 'command.json').write_text(json.dumps({'archive': command, 'revision': REVISION,
    'parent_python': sys.executable, 'parent_version': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'owned_archive_directory': str(owned)}, indent=2) + '\n')
try:
    archive = subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(owned, filter='data')
    child = r'''
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
'''
    target = ROOT / 'tests/fixtures/program_graph_v16_frozen.json'
    proof = ROOT / 'tests/fixtures/program_graph_v16_frozen.proof.json'
    assert not target.exists() and not proof.exists()
    prefix = 'OUTPUT=' + repr(str(target)) + '\nPROOF=' + repr(str(proof)) + '\nREVISION=' + repr(REVISION) + '\n'
    full = prefix + child
    (HERE / 'child.py').write_text(full)
    child_command = [sys.executable, '-c', full]
    environment = dict(os.environ, PYTHONPATH=str(owned), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run(child_command, cwd=owned, env=environment, capture_output=True, text=True)
    (HERE / 'stdout.log').write_text(result.stdout)
    (HERE / 'stderr.log').write_text(result.stderr)
    (HERE / 'result.json').write_text(json.dumps({'returncode':result.returncode,
        'archive_sha256':hashlib.sha256(archive).hexdigest(), 'child_python':sys.executable,
        'child_cwd':str(owned), 'child_PYTHONPATH':str(owned), 'command_source':'child.py',
        'owned_directory_removed_after_child_exit':str(owned)},indent=2)+'\n')
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)
finally:
    shutil.rmtree(owned)

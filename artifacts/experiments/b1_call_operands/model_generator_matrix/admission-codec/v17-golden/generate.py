"""Historical codec17 bytes, generated only from immutable archived source."""
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

root = Path.cwd()
here = Path(__file__).resolve().parent
revision = subprocess.check_output(['git', 'rev-parse', 'b88670b'], cwd=root, text=True).strip()
owned = Path(tempfile.mkdtemp(prefix='scar-admission-v17-archive-'))
command = ['git', 'archive', revision, 'scar', 'tests/fixtures']
(here / 'command.json').write_text(json.dumps({
    'archive': command, 'source_revision': revision, 'python': sys.executable,
    'python_version': sys.version, 'owned_archive_directory': str(owned),
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'PYTHONDONTWRITEBYTECODE': '1',
}, indent=2) + '\n')
try:
    archive = subprocess.run(command, cwd=root, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(owned, filter='data')
    child = '''
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
Path(PROOF).write_text(json.dumps(proof,indent=2)+'\\n')
print(json.dumps(proof,indent=2))
'''
    target = root / 'tests/fixtures/program_graph_v17_frozen.json'
    proof = root / 'tests/fixtures/program_graph_v17_frozen.proof.json'
    assert not target.exists() and not proof.exists()
    full = ('OUTPUT=' + repr(str(target)) + '\nPROOF=' + repr(str(proof))
            + '\nREVISION=' + repr(revision) + '\n' + child)
    (here / 'child.py').write_text(full)
    environment = dict(os.environ, PYTHONPATH=str(owned), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-c', full], cwd=owned, env=environment,
                            capture_output=True, text=True)
    (here / 'stdout.log').write_text(result.stdout)
    (here / 'stderr.log').write_text(result.stderr)
    (here / 'result.json').write_text(json.dumps({
        'returncode': result.returncode, 'archive_sha256': hashlib.sha256(archive).hexdigest(),
        'child_cwd': str(owned), 'child_PYTHONPATH': str(owned),
        'child_source': 'child.py', 'owned_directory_removed_after_child_exit': str(owned),
    }, indent=2) + '\n')
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)
finally:
    shutil.rmtree(owned)

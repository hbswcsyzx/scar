"""Freeze codec-only v6 bytes from exact, on-demand immutable source blobs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
REVISION = '348d18277b963bc183fb420bf173f05594d667d8'
FIXTURE = 'tests/fixtures/execution_validity_records.py'

CHILD = '''from hashlib import sha256
import importlib.abc
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

repository, revision = sys.argv[1:3]
root = Path.cwd().resolve()
available = set(json.loads(Path('available_paths.json').read_text()))
materialized = {}

def export(relative):
    path = root / relative
    if relative not in materialized:
        data = subprocess.check_output(['git', 'show', revision + ':' + relative], cwd=repository)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        materialized[relative] = sha256(data).hexdigest()
    return path

class ImmutableScar(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'scar' and not fullname.startswith('scar.'):
            return None
        stem = fullname.replace('.', '/')
        for relative, package in ((stem + '/__init__.py', True), (stem + '.py', False)):
            if relative in available:
                original = export(relative)
                return importlib.util.spec_from_file_location(fullname, original,
                    submodule_search_locations=[str(original.parent)] if package else None)
        return None

sys.meta_path.insert(0, ImmutableScar())
fixture_file = export('tests/fixtures/execution_validity_records.py')
export('tests/fixtures/execution_v5_frozen.json')
spec = importlib.util.spec_from_file_location('immutable_validity_fixture', fixture_file)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
import scar.ir.execution.codec as codec
assert codec.SCHEMA_VERSION == 6
model = fixture.validity_record_model()
payload = codec.dumps(model).encode('utf-8')
assert codec.loads(payload.decode('utf-8')) == model
assert json.loads(payload)['schema_version'] == 6
for name, module in tuple(sys.modules.items()):
    if name == 'scar' or name.startswith('scar.'):
        location = getattr(module, '__file__', None)
        if location is not None:
            assert Path(location).resolve().is_relative_to(root), (name, location)
assert not hasattr(model, 'call_activations')
Path('execution_v6_frozen.json').write_bytes(payload)
print(json.dumps({'revision':revision, 'schema_version':6,
    'codec_sha256':materialized['scar/ir/execution/codec.py'],
    'fixture_sha256':materialized['tests/fixtures/execution_validity_records.py'],
    'fixture_source':'tests/fixtures/execution_validity_records.py',
    'payload_sha256':sha256(payload).hexdigest(), 'payload_bytes':len(payload),
    'validity_table_counts':{key:len(getattr(model,key)) for key in
        ('established_productions','target_lifetime_events','order_associations','contribution_supports')},
    'immutable_blobs':materialized,
    'isolation':'All imported scar modules and original fixture exported byte-exact from this revision; no current checkout module on import path',
    'fixture_scope':'old codec-only rich validity declaration; not a validated physical execution'}, sort_keys=True))
'''


def main():
    attempt = next(OUT / f'attempt{number:03d}' for number in range(1, 1000)
                   if not (OUT / f'attempt{number:03d}').exists())
    attempt.mkdir(parents=True)
    owned = Path(tempfile.mkdtemp(prefix='scar-v6-blobs-'))
    started = time.perf_counter()
    success = False
    try:
        command = ['git', 'ls-tree', '-r', '--name-only', REVISION, 'scar', FIXTURE,
                   'tests/fixtures/execution_v5_frozen.json']
        (attempt / 'tree-command.json').write_text(json.dumps(command, indent=2) + '\n')
        tree = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (attempt / 'tree-stdout.log').write_text(tree.stdout)
        (attempt / 'tree-stderr.log').write_text(tree.stderr)
        if tree.returncode:
            raise RuntimeError('immutable tree lookup failed')
        (owned / 'available_paths.json').write_text(json.dumps(tree.stdout.splitlines()))
        (attempt / 'child.py').write_text(CHILD)
        environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'CONDA_PREFIX') if key in os.environ}
        environment.update(PYTHONPATH=str(owned), PYTHONDONTWRITEBYTECODE='1')
        child_command = [sys.executable, '-c', CHILD, str(ROOT), REVISION]
        (attempt / 'command.json').write_text(json.dumps({'command':child_command,
            'cwd':str(owned), 'python':sys.version, 'environment':{
                'PYTHONPATH':str(owned), 'PYTHONDONTWRITEBYTECODE':'1'},
            'activation':'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
            'generator_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n')
        result = subprocess.run(child_command, cwd=owned, env=environment, capture_output=True, text=True)
        (attempt / 'stdout.log').write_text(result.stdout)
        (attempt / 'stderr.log').write_text(result.stderr)
        (attempt / 'exit.txt').write_text(str(result.returncode) + '\n')
        if result.returncode:
            raise RuntimeError('old v6 generation failed; original logs retained')
        proof = json.loads(result.stdout)
        payload = (owned / 'execution_v6_frozen.json').read_bytes()
        assert sha256(payload).hexdigest() == proof['payload_sha256']
        proof['generator_sha256'] = sha256(Path(__file__).read_bytes()).hexdigest()
        destination = ROOT / 'tests/fixtures/execution_v6_frozen.json'
        proof_path = destination.with_name(destination.name + '.proof.json')
        if destination.exists() or proof_path.exists():
            raise RuntimeError('refusing to overwrite an existing golden or proof')
        destination.write_bytes(payload)
        proof_path.write_text(json.dumps(proof, indent=2) + '\n')
        (attempt / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        success = True
        print(json.dumps({key:proof[key] for key in ('revision','schema_version','payload_sha256',
                                                  'payload_bytes','validity_table_counts')}))
    finally:
        shutil.rmtree(owned)
        (attempt / 'receipt.json').write_text(json.dumps({'success':success,
            'duration_seconds':time.perf_counter()-started, 'owned_temp_removed':str(owned),
            'no_current_source_used':True, 'read_only_git_blobs':True}, indent=2) + '\n')


if __name__ == '__main__':
    main()

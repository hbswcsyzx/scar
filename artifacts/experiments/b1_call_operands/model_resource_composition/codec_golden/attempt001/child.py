from hashlib import sha256
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

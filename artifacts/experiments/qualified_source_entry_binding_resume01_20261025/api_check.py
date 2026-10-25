"""One stored small monolith structural consumption; no source/runtime proof."""
import ast
import gzip
import hashlib
import inspect
import json
from pathlib import Path
from scar.analysis.program_composition import _InventorySource
from scar.analysis.source_invocations import bind_source_invocations
from scar.ir.program.codec import loads

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
path = ROOT / 'artifacts/experiments/b1_call_operands/generic_gpu/reports/inventory.json.gz'
for name in ('program_composition.py', 'source_invocations.py'):
    ast.parse((ROOT / 'scar/analysis' / name).read_text())
assert path.stat().st_size <= 2_000_000
inventory = _InventorySource(path, max_input_bytes=2_000_000, max_record_bytes=2_000_000)
selected = next((fi, bi, body) for fi in range(inventory.file_count)
                for bi, body in enumerate(inventory.file(fi)['bodies']) if body['graph'] is not None)
fi, bi, body = selected
graph = loads(json.dumps(body['graph'], ensure_ascii=False, allow_nan=False))
legacy_before = inventory.body_locators(fi, bi, body['graph'])
qualified = inventory.qualified_body_locators(fi, bi, body['graph'])
assert legacy_before == inventory.body_locators(fi, bi, body['graph']) and legacy_before['namespace'] is None
with gzip.open(path, 'rb') as stream:
    decoded = stream.read(2_000_001)
assert len(decoded) <= 2_000_000
assert qualified['namespace']['artifact']['uri'] == str(path)
assert qualified['namespace']['artifact']['decoded_sha256'] == hashlib.sha256(decoded).hexdigest()
assert qualified['namespace']['record_pointer'] == f'#/files/{fi}/bodies/{bi}/graph'
assert qualified['graph_locator']['pointer'] == legacy_before['graph_locator']['pointer']
assert qualified['metadata_locator']['pointer'] == legacy_before['metadata_locator']['pointer']
assert graph.root.wire == body['graph']['root']['wire']
result = {'status': 'PASS', 'scope': 'one actual existing small inventory; core/namespace structural consumption only',
    'input': {'uri': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'stored_bytes': path.stat().st_size,
              'decoded_bytes': len(decoded), 'decoded_sha256': hashlib.sha256(decoded).hexdigest()},
    'selected_original_body': {'file_index': fi, 'body_index': bi, 'root': graph.root.wire},
    'locators': qualified, 'legacy_locator_unchanged': True,
    'binder_signature': str(inspect.signature(bind_source_invocations)),
    'raw_lower_compile_target': 0, 'LeWM_runtime_qualification': False, 'full_mixed_binder_verified': False}
with (HERE / 'api-check.json').open('x') as stream:
    json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps({'status': result['status'], 'input': result['input'], 'root': graph.root.wire}))

"""Structural compatibility only; this does not restore native evidence ownership."""
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ISO = ROOT.parent / 'native-scalar-model'
started = time.monotonic()
application = json.loads((HERE / 'APPLICATION.json').read_text())
for row in application['files']:
    assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['after_sha256']
    importlib.import_module(row['path'].removesuffix('.py').replace('/', '.'))

gate = ISO / 'artifacts/experiments/native_scalar_provenance_20261025/attempt01'
observed = json.loads((gate / 'result.json').read_text())
ref = observed['observations'][0]['version']['artifact']
path = Path(ref['uri'])
assert path.stat().st_size == ref['size_bytes'] <= 4_000_000
with path.open('rb') as stream:
    stored = stream.read(4_000_001)
assert len(stored) == ref['size_bytes'] and hashlib.sha256(stored).hexdigest() == ref['sha256']
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2.values import ProvenanceRelation
document = json.loads(stored)
graph = values_from_dict(document)
checked = graph.validate()
assert checked['valid'], checked
assert graph.to_dict() == document
assert len(graph.logical_values) == len(graph.versions) == len(graph.provenance) == 4
assert all(row.relation is ProvenanceRelation.ORIGIN and row.producer is None
           for row in graph.provenance.values())
from scar.ir.execution.native_port_protocol import NativePortEvidence
from scar.trace.native_capture_batch import bind_native_capture_model_batches
assert callable(NativePortEvidence.scalar_values)
assert inspect.signature(bind_native_capture_model_batches).parameters['scalar_input_profile'].default is None
result = {'schema': 'scar.native-scalar-main-structural-readback/1', 'status': 'PASSED_WITH_OPEN',
    'four_source_hashes': True, 'ordinary_typed_value_reader': True,
    'logical_values': len(graph.logical_values), 'versions': len(graph.versions),
    'origin_records': len(graph.provenance), 'origin_producers_are_unknown': True,
    'default_scalar_capability': None, 'batch_typed_query_available': True,
    'projection_receipt': ref, 'direct_projection_bytes_read': len(stored),
    'Torch_imported': 'torch' in sys.modules, 'owner_restored': False,
    'new_scalar_qualification': False, 'new_native_batch_or_target_run': False,
    'whole_model': 'OPEN', 'wall_seconds': time.monotonic() - started}
text = json.dumps(result, sort_keys=True, indent=2) + '\n'
with (HERE / 'RESULT.json').open('x') as stream:
    stream.write(text)
print(text)

"""One real retained-bundle storage round trip; no target execution."""
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.trace.native_import import import_native_evidence
from scar.trace.dispatch_import import import_dispatch_bridge
from scar.trace.tensor_physical_import import import_tensor_physical
from scar.store.bundle_partitions import BundlePartitions, TABLES, publish_bundle

ROOT = Path(__file__).resolve().parent
RAW = ROOT.parent / 'first_stage_tensor_physical_20261023' / 'trace'
REPO = ROOT.parents[2]
one = lambda pattern: next(RAW.glob(pattern))
started = time.perf_counter()
modules = ('scar/store/bundle_partitions.py', 'scar/trace/native_import.py',
           'scar/trace/dispatch_import.py', 'scar/trace/tensor_physical_import.py')
(ROOT / 'modules.json').write_text(json.dumps({name: sha256((REPO / name).read_bytes()).hexdigest()
                                             for name in modules}, indent=2) + '\n')
meta = json.loads(one('tensor-physical-meta.*.json').read_bytes())
native = import_native_evidence(one('execution-trace.*.json'), one('kineto.*.json'),
                               provider_revision=meta['provider_revision'])
import_dispatch_bridge(native, one('dispatch-observations.*.jsonl'), one('dispatch-meta.*.json'),
    one('call-events.*.jsonl'), one('call-codes.*.jsonl'), one('call-meta.*.json'),
    native_manifest_path=one('execution-evidence.*.json'))
physical = import_tensor_physical(native, one('tensor-physical.*.jsonl'), one('tensor-physical-meta.*.json'))

with (ROOT / 'progress.jsonl').open('x') as progress:
    def emit(row):
        row = {'elapsed_s': time.perf_counter() - started, **row}
        progress.write(json.dumps(row, sort_keys=True) + '\n')
        progress.flush()
        print(json.dumps(row, sort_keys=True), flush=True)
    publication = publish_bundle(native.bundle, ROOT / 'result', progress=emit)

archive = BundlePartitions(ROOT / 'result' / 'manifest.json')
checked = {}
for graph_name, tables in TABLES.items():
    graph = getattr(native.bundle, graph_name)
    if graph is None:
        assert archive.manifest['graphs'][graph_name] is None
        continue
    for table in tables:
        collection = getattr(graph, table)
        if graph_name == 'evidence' and table == 'control_events':
            expected = iter(collection)
        elif graph_name == 'evidence' and table == 'external_references':
            expected = ({'kind': kind.value, 'wire': wire} for kind, wire in collection)
        else:
            expected = (row.as_dict() for row in (collection.values() if isinstance(collection, dict) else collection))
        count, digest = 0, sha256()
        for original, restored in zip(expected, archive.iter_records(graph_name, table), strict=True):
            assert restored['record'] == original and restored['ordinal'] == count
            assert restored['locator']['line'] > 0
            assert restored['verification']['whole_chunk_stored_sha_verified'] is True
            assert restored['verification']['whole_chunk_decoded_sha_verified'] is True
            encoded = json.dumps(original, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                 separators=(',', ':')).encode('utf-8') + b'\n'
            digest.update(encoded)
            count += 1
        assert count == len(collection) == archive.manifest['graphs'][graph_name]['counts'][table]
        checked[graph_name + '/' + table] = {'records': count, 'ordered_record_sha256': digest.hexdigest()}

report = {'schema': 'scar.real-bundle-partitions-audit', 'status': 'PASS',
          'source': str(RAW), 'target_executed': False,
          'manifest_receipt': publication['manifest_receipt'], 'totals': publication['totals'],
          'tables': checked, 'all_original_records_and_order_equal': True,
          'physical_slots': physical['physical_slot_associations'],
          'elapsed_s': time.perf_counter() - started,
          'whole_model_established': False, 'transformation_authorized': False}
(ROOT / 'audit-result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, sort_keys=True), flush=True)

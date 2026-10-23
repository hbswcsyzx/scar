"""One actual raw-artifact and native/value-IR audit; no target re-execution."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from scar.trace.native_import import import_native_evidence
from scar.trace.dispatch_import import import_dispatch_bridge
from scar.trace.tensor_physical_import import import_tensor_physical

root = Path(__file__).resolve().parent
raw = root / 'trace'
one = lambda pattern: next(raw.glob(pattern))
meta = json.loads(one('tensor-physical-meta.*.json').read_bytes())
data = one('tensor-physical.*.jsonl').read_bytes()
assert len(data) == meta['file']['raw_bytes']
assert sha256(data).hexdigest() == meta['file']['raw_sha256']
rows = [json.loads(line) for line in data.splitlines()]
assert len(rows) == meta['file']['lines']
for declaration in meta['inputs'].values():
    path = Path(declaration['path'])
    assert path.parent == raw and path.is_file()
    payload = path.read_bytes()
    assert sha256(payload).hexdigest() == declaration['raw_sha256']
    assert len(payload) == declaration['raw_bytes']
dispatch = {row['marker']: row for row in map(json.loads,
    one('dispatch-observations.*.jsonl').read_bytes().splitlines()) if row['kind'] != 'DISPATCH_END'}
eto = json.loads(one('execution-trace.*.json').read_bytes())
markers = {node['name']: node for node in eto['nodes'] if node['name'].startswith('scar-dispatch:')}
physical = {row['marker']: row for row in rows if row['kind'] == 'MARKER'}
assert len(physical) == sum(row['kind'] == 'MARKER' for row in rows)
assert set(physical) == set(markers) == set(dispatch)
epochs = {}
for row in rows:
    if row['kind'] == 'ALLOCATION':
        epoch = row['device']['text'], row['provider_allocation_id']
        epochs.setdefault(epoch, []).append(row)
checked = duplicates = views = 0
for name, row in physical.items():
    node, source = markers[name], dispatch[name]
    references = source['observation']['tensor_references']
    assert len(row['arguments']) == len(node['inputs']['values']) == len(references)
    seen = {}
    for ordinal, (argument, value, shape, stride, reference) in enumerate(zip(row['arguments'],
            node['inputs']['values'], node['inputs']['shapes'], node['inputs']['strides'], references, strict=True)):
        tensor = argument['metadata']
        assert argument['argument_ordinal'] == argument['dispatch_reference_ordinal'] == ordinal
        assert tensor['sizes'] == shape and tensor['strides'] == stride
        assert tensor['device']['text'] == value[5]
        epoch = tensor['device']['text'], tensor['provider_allocation_id']
        assert epoch in epochs
        assert all(receipt['ptr'] == tensor['storage_data_ptr'] for receipt in epochs[epoch])
        if reference['ref'] in seen:
            duplicates += 1
            assert seen[reference['ref']] == (value, epoch, tensor['impl_ptr'])
        seen[reference['ref']] = value, epoch, tensor['impl_ptr']
        views += tensor['sizes'] == [2, 2]
        checked += 1
assert duplicates > 0 and views > 0

native = import_native_evidence(one('execution-trace.*.json'), one('kineto.*.json'),
    provider_revision=meta['provider_revision'])
import_dispatch_bridge(native, one('dispatch-observations.*.jsonl'), one('dispatch-meta.*.json'),
    one('call-events.*.jsonl'), one('call-codes.*.jsonl'), one('call-meta.*.json'),
    native_manifest_path=one('execution-evidence.*.json'))
old_instances = set(native.bundle.evidence.instances)
old_versions = set(native.bundle.values.versions)
report = import_tensor_physical(native, one('tensor-physical.*.jsonl'), one('tensor-physical-meta.*.json'))
assert set(native.bundle.evidence.instances) == old_instances
assert set(native.bundle.values.versions) == old_versions
assert report['physical_slot_associations'] == checked
assert report['gaps'] == {}
native.bundle.assert_valid()
(root / 'physical-import.json').write_text(json.dumps(report, indent=2) + '\n')
audit = {'schema': 'scar.tensor-physical-independent-audit', 'status': 'PASS',
    'capture_exit': json.loads((raw / 'run.json').read_bytes())['returncode'],
    'markers': len(physical), 'slots_checked': checked, 'duplicate_slots': duplicates,
    'view_slots': views, 'allocation_receipts': sum(row['kind'] == 'ALLOCATION' for row in rows),
    'receipt_roles': dict(Counter(row['receipt_kind'] for row in rows if row['kind'] == 'ALLOCATION')),
    'provider_epochs': len(epochs), 'imported_epochs': report['allocation_epochs'],
    'imported_physical_regions': report['physical_slot_associations'],
    'original_operation_instances_unchanged': True, 'logical_versions_unchanged': True,
    'whole_model_established': False, 'transformation_authorized': False,
    'limits': ['CPU case only', 'no OS process membership receipt',
        'no legacy Kineto per-allocation correspondence', 'no logical content/ready/state proof']}
(root / 'audit-result.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps(audit))

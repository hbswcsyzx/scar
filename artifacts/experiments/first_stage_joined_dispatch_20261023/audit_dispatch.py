"""Independently check every production marker slot against actual raw ETO."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
result = HERE / 'result'
model = json.loads((result / 'capture-model.json').read_text())
capture = Path(model['capture'])
trace = capture / 'trace'
one = lambda pattern: next(trace.glob(pattern))


def read(path):
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def original(path):
    if path.exists():
        return path
    index = read(capture / 'archive-index.json')
    return Path(next(row['actual_path'] for row in index['files'] if row['logical_path'] == str(path)))


meta = read(one('dispatch-meta.*.json'))
payload_path = original(Path(meta['file']['path']))
with (gzip.open(payload_path, 'rb') if payload_path.suffix == '.gz' else payload_path.open('rb')) as stream:
    payload = stream.read()
assert sha256(payload).hexdigest() == meta['file']['raw_sha256']
assert len(payload) == meta['file']['raw_bytes'] == meta['bytes']
rows = [json.loads(line) for line in payload.splitlines()]
del payload
assert len(rows) == meta['file']['lines'] == meta['events']
native_meta = read(one('execution-evidence.*.json'))
eto = read(original(Path(native_meta['artifacts']['execution_trace']['path'])))
nodes = {node['id']: node for node in eto['nodes']}
markers = {node['name']: node for node in eto['nodes'] if node['name'].startswith('scar-dispatch:' + meta['nonce'] + ':')}
del eto
bridge = read(result / 'native/dispatch-bridge.json.gz')
observations = {(row['sequence'], row['phase']): row for row in bridge['observations']}
actual_paths = {}
for path in bridge['paths']:
    key = path['sequence'], path['phase'], path['provider_argument_ordinal']
    assert key not in actual_paths
    actual_paths[key] = path
groups, counts = {}, Counter()
for index, row in enumerate(rows, 1):
    assert row['index'] == index
    sequence = row['sequence']
    group = groups.setdefault(sequence, {})
    assert row['kind'] not in group
    group[row['kind']] = row
    if row['kind'] == 'DISPATCH_END':
        continue
    phase = 'span' if row['kind'] == 'DISPATCH_BEGIN' else 'output'
    marker = markers[row['marker']]
    observed = observations[sequence, phase]
    assert observed['native_tid_verified'] is True
    assert observed['retained_ancestor'] == row['observation']['context']
    assert observed['native_tid'] == row['observation']['native_tid']
    assert observed['python_ident'] == row['observation']['python_ident']
    assert marker['outputs']['values'] == []
    leaves = row['observation']['tensor_references']
    assert len(marker['inputs']['values']) == len(leaves)
    previous = {}
    for ordinal, (leaf, descriptor) in enumerate(zip(leaves, marker['inputs']['values'], strict=True)):
        assert leaf['identity_qualified'] is True and leaf['ref'].startswith(f"weak:{meta['process_id']}:")
        path = actual_paths.pop((sequence, phase, ordinal))
        assert path['original_payload_path'] == leaf['path']
        assert path['marker_instance'] == observed['marker_instance']
        assert path['provider_role'] == 'inputs'
        if leaf['ref'] in previous:
            assert previous[leaf['ref']] == descriptor
            counts['repeated_tensor_slots_preserved'] += 1
        previous[leaf['ref']] = descriptor
        counts['exact_slot_associations'] += 1
    cursor = marker
    for ancestor in observed['actual_provider_ancestry']:
        assert ancestor['node_id'] == cursor['id'] and ancestor['ctrl_deps'] == cursor['ctrl_deps']
        if cursor['ctrl_deps'] != cursor['id'] and cursor['ctrl_deps'] in nodes:
            cursor = nodes[cursor['ctrl_deps']]
    counts['marker_observations'] += 1
    counts['retained_ancestor_missing'] += row['observation']['context'] is None
    counts['unqualified_payload_slots'] += len(row['slot_gaps'])
assert not actual_paths
outcomes = Counter()
for sequence, group in groups.items():
    end = group['DISPATCH_END']
    outcomes[end['outcome']] += 1
    if end['outcome'] == 'RETURNED':
        span = markers[group['DISPATCH_BEGIN']['marker']]
        output = markers[group['DISPATCH_OUTPUT']['marker']]
        assert output['ctrl_deps'] == span['id']
    else:
        assert end['outcome'] == 'RAISED' and 'DISPATCH_OUTPUT' not in group and end['output_marker'] is None
assert len(groups) == meta['dispatch_attempts'] == bridge['dispatches']
assert counts['exact_slot_associations'] == bridge['slot_associations']
assert counts['retained_ancestor_missing'] == bridge['gaps'].get('retained_ancestor_missing', 0)
assert counts['unqualified_payload_slots'] == bridge['gaps'].get('unqualified_payload_slots', 0)
assert meta['dropped_events'] == 0 and meta['errors'] == [] and meta['gaps'] == [] and meta['mode_popped'] is True
assert bridge['capture_membership_verified'] is True
assert bridge['whole_model_established'] is False and bridge['logical_versions_established'] is False
report = {'status': 'PASS', 'scope': 'all actual production dispatch marker slots and retained raw ancestry',
          'dispatches': len(groups), 'outcomes': dict(outcomes), **counts,
          'whole_program_verified': False, 'state_versions_or_ready_verified': False}
(HERE / 'audit-dispatch.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))

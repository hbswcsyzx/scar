"""Count independent port qualifications in the retained 20-shard prefix.

Read published qualification rows only; no raw acquisition or native authority.
"""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import time

START = time.monotonic()
HERE = Path(__file__).resolve().parent
ROOT = Path('/home/zyf/AAA/scar-worktrees/native-scalar-model/artifacts/experiments/native_capture_batch_attempt02_20261025')
receipts, stored = [], 0


def read(path, descriptor=None):
    global stored
    size = path.stat().st_size
    if stored + size > 64_000_000:
        raise ValueError('qualification-only query exceeds 64 MB budget')
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    if descriptor is not None:
        assert digest == descriptor['sha256'] and len(raw) == descriptor['size_bytes']
    receipts.append({'uri': str(path), 'size_bytes': len(raw), 'sha256': digest})
    stored += len(raw)
    return raw


reports = [json.loads(read(p)) for p in sorted((ROOT / 'result/shards').glob('*/report.json'))]
assert len(reports) == 20
counts, geometry_gaps, joint = Counter(), Counter(), Counter()
for report in reports:
    expected = report['port_qualifications']
    manifest = json.loads(read(Path(expected['uri']), expected))
    seen = 0
    for chunk in manifest['chunks']:
        raw = read(Path(chunk['artifact']['uri']), chunk['artifact'])
        rows = raw.splitlines()
        assert len(rows) == chunk['rows']
        for line in rows:
            row = json.loads(line)
            assert row['A'] == 'QUALIFIED_NATIVE_PORT'
            assert row['D'] == 'CONTENT_STATE_READY_UNPROVED'
            b, c = row['B'], row['C']['status']
            counts['native_ports'] += 1
            counts[b] += 1
            counts['geometry_' + c] += 1
            joint[b + '/' + c] += 1
            if c != 'QUALIFIED':
                geometry_gaps[row['C'].get('reason', 'reason_not_recorded')] += 1
            seen += 1
    assert seen == manifest['rows'] == report['native_tensor_ports']
assert counts['native_ports'] == 11430
result = {'schema': 'scar.retained-native-prefix-plane-query', 'schema_version': 1,
          'scope': '20 completed execution shards only; sequence 1..5120 of 39796',
          'qualification_counts': dict(counts), 'joint_counts': dict(joint),
          'geometry_gap_reasons': dict(geometry_gaps), 'stored_bytes_read': stored,
          'files_read': len(receipts), 'wall_seconds': time.monotonic() - START,
          'receipts': receipts, 'raw_reads': 0, 'private_database_reads': 0,
          'native_owned_session_restored': False, 'whole_program_model': 'OPEN',
          'limits': 'Counts of retained qualification claims; not a replay of the full native proof or full-domain coverage.'}
with (HERE / 'result.json').open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({k: v for k, v in result.items() if k != 'receipts'}, sort_keys=True))

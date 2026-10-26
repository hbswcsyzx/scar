"""Classify every retained source858 routing issue without rerunning a linker."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = Path('/home/zyf/AAA/scar-worktrees/source858-runtime')
MANIFEST = ROOT / 'artifacts/experiments/first_stage_source858_current_20261026/result/analysis/manifest.json'
MAX_INPUT = 96_000_000
MAX_CHUNK = 16_000_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    meter = {'stored_bytes': 0, 'decoded_bytes': 0}
    reads = []

    def read(path, declaration=None, compressed=False):
        path = Path(path)
        before = path.stat()
        if before.st_size > MAX_CHUNK:
            raise ValueError('single stored input exceeds finite audit budget')
        raw = path.read_bytes()
        meter['stored_bytes'] += len(raw)
        if declaration is not None:
            if (len(raw), digest(raw)) != (declaration['bytes'], declaration['sha256']):
                raise ValueError('original stored chunk differs: ' + str(path))
        decoded = gzip.decompress(raw) if compressed else raw
        if len(decoded) > MAX_CHUNK:
            raise ValueError('single decoded input exceeds finite audit budget')
        meter['decoded_bytes'] += len(decoded)
        if sum(meter.values()) > MAX_INPUT:
            raise ValueError('cumulative audit input budget exceeded')
        if declaration is not None and (len(decoded), digest(decoded)) != (
                declaration['decoded_bytes'], declaration['decoded_sha256']):
            raise ValueError('original decoded chunk differs: ' + str(path))
        after = path.stat()
        stable = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if stable(before) != stable(after):
            raise ValueError('original input changed during audit: ' + str(path))
        reads.append({'path': str(path), 'bytes': len(raw), 'sha256': digest(raw),
                      'decoded_bytes': len(decoded), 'decoded_sha256': digest(decoded)})
        return decoded

    raw_manifest = read(MANIFEST)
    manifest = json.loads(raw_manifest)
    if (manifest['schema'], manifest['schema_version'], manifest['original_schema']) != (
            'scar.partitioned-call-operand-links', 1, 'scar.call-operand-links'):
        raise ValueError('unexpected normal operand partition manifest')
    table = manifest['tables']['routing.issues']
    grouped, kinds, samples = Counter(), Counter(), defaultdict(list)
    invocations, anchors = set(), set()
    for chunk in table['chunks']:
        rows = read(chunk['path'], chunk, compressed=True).splitlines()
        if len(rows) != chunk['rows']:
            raise ValueError('original chunk row denominator differs')
        for raw in rows:
            row = json.loads(raw)
            key = row['kind'], row['detail']
            grouped[key] += 1
            kinds[row['kind']] += 1
            if row.get('invocation') is not None:
                invocations.add(json.dumps(row['invocation'], sort_keys=True))
            if row.get('anchor') is not None:
                anchors.add(json.dumps(row['anchor'], sort_keys=True))
            if len(samples[key]) < 2:
                samples[key].append(row)
    if sum(grouped.values()) != table['rows']:
        raise ValueError('complete issue denominator differs')
    if MANIFEST.read_bytes() != raw_manifest:
        raise ValueError('normal manifest changed during audit')
    # Charge the final independent manifest read as well.
    meter['stored_bytes'] += len(raw_manifest)
    result = {
        'status': 'VERIFIED_RETAINED_ISSUE_CLASSIFICATION',
        'manifest': {'path': str(MANIFEST), 'sha256': digest(raw_manifest)},
        'issues': table['rows'], 'unique_issue_invocations': len(invocations),
        'unique_issue_anchors': len(anchors), 'kinds': dict(kinds),
        'groups': [{'kind': k[0], 'detail': k[1], 'count': n, 'samples': samples[k]}
                   for k, n in grouped.most_common()],
        'input_io': {**meter, 'total_bytes': sum(meter.values()), 'cap_bytes': MAX_INPUT},
        'reads': reads,
        'raw_frame_or_operand_read': False, 'target_executed': False,
        'source_or_graph_rebuilt': False, 'routing_qualification_changed': False,
        'scope': 'Original issue facts only; a missing handshake does not identify its runtime cause.',
        'first_stage_complete': False,
    }
    with (BASE / 'RESULT.json').open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'issues', 'kinds', 'input_io')}))
    print(json.dumps([{k: v for k, v in g.items() if k != 'samples'} for g in result['groups']], ensure_ascii=False))


if __name__ == '__main__':
    main()

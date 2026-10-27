"""Small source/control freeze for ordinary bootstrap/dependency CLI phases."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    h, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            h.update(block); size += len(block)
    return {'uri': str(path), 'sha256': h.hexdigest(), 'size_bytes': size}


parser = argparse.ArgumentParser()
parser.add_argument('--prepare', action='store_true')
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
path = HERE / 'bootstrap-dependencies-freeze.afterB.json'
if args.prepare:
    assert not path.exists() and not (HERE / 'offline').exists()
    captured = json.loads((HERE / 'capture-result.json').read_bytes())
    assert captured['status'] == 'CAPTURED_OFFLINE_PAUSED' and captured['actual_cli_exit'] == 0
    doc = {'schema': 'scar.project-dependency-offline-source-freeze/1',
        'capture_producer_freeze': sha(HERE / 'capture-freeze.json'), 'capture_result': sha(HERE / 'capture-result.json'),
        'source': [sha(p) for p in sorted((ROOT / 'scar').rglob('*.py'))],
        'entry': [sha(HERE / 'bootstrap-dependencies.sh'), sha(Path(__file__).resolve())],
        'capture_roots': [captured['archive_root'], captured['coordinate_root']],
        'scope': 'ordinary bootstrap then dependency CLI only; stop before source-entry/publication',
        'previous_prepared_not_run_freeze': sha(HERE / 'bootstrap-dependencies-freeze.json'),
        'budgets': {'each_phase_seconds': 180, 'bootstrap_explicit_max_calls': 512,
                    'all_other_bootstrap_dependency_fields': 'original distinct public defaults'},
        'capture_repeated': False, 'target_executed': False, 'runtime_binary_freeze': 'OPEN'}
    with path.open('x') as f:json.dump(doc, f, sort_keys=True, indent=2);f.write('\n')
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(path), 'sources': len(doc['source'])}))
elif args.check:
    doc = json.loads(path.read_bytes())
    assert sorted(str(p) for p in (ROOT / 'scar').rglob('*.py')) == sorted(r['uri'] for r in doc['source'])
    for ref in [*doc['source'], *doc['entry'], *doc['capture_roots'], doc['capture_producer_freeze'], doc['capture_result']]:
        assert sha(Path(ref['uri'])) == ref, 'frozen bytes changed: ' + ref['uri']
    print(json.dumps({'status': 'FROZEN_BYTES_MATCH', 'sources': len(doc['source'])}), flush=True)
else:
    parser.error('choose --prepare or --check')

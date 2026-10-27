"""Source-entry/publication consumer freeze; prepare only after dependencies stop."""
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
path = HERE / 'entries-bindings-freeze.json'
if args.prepare:
    assert not path.exists() and not (HERE / 'offline/entries').exists() and not (HERE / 'offline/bindings').exists()
    source = HERE / 'offline/dependencies/model-run.json'
    root = json.loads(source.read_bytes())
    terminal = root['terminal']
    assert sha(Path(terminal['uri'])) == {key: terminal[key] for key in ('uri', 'sha256', 'size_bytes')}
    doc = {'schema': 'scar.project-dependency-late-source-freeze/1',
        'source': [sha(p) for p in sorted((ROOT / 'scar').rglob('*.py'))],
        'entry': [sha(HERE / 'entries-bindings.sh'), sha(Path(__file__).resolve())],
        'dependency_navigation': sha(source), 'dependency_terminal': terminal,
        'capture_producer_freeze': sha(HERE / 'capture-freeze.json'), 'capture_result': sha(HERE / 'capture-result.json'),
        'scope': 'ordinary source-entries then source-entry-bindings CLI only; no recapture',
        'budgets': {'each_seconds': 180, 'entry_dispatch': 16, 'entry_source_files': 6, 'entry_total_operations': 16000,
                    'entry_body_operations': 4000, 'binding_programs': 16, 'catalog_groups_entries': 32,
                    'all_other_fields': 'independent public profile defaults'},
        'capture_repeated': False, 'runtime_binary_freeze': 'OPEN'}
    with path.open('x') as f:json.dump(doc, f, sort_keys=True, indent=2);f.write('\n')
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(path), 'sources': len(doc['source'])}))
elif args.check:
    doc = json.loads(path.read_bytes())
    assert sorted(str(p) for p in (ROOT / 'scar').rglob('*.py')) == sorted(r['uri'] for r in doc['source'])
    for ref in [*doc['source'], *doc['entry'], doc['dependency_navigation'], doc['dependency_terminal'],
                doc['capture_producer_freeze'], doc['capture_result']]:
        assert sha(Path(ref['uri'])) == {key: ref[key] for key in ('uri', 'sha256', 'size_bytes')}, 'frozen bytes changed: ' + ref['uri']
    print(json.dumps({'status': 'FROZEN_BYTES_MATCH', 'sources': len(doc['source'])}), flush=True)
else:
    parser.error('choose --prepare or --check')

"""One root-owned generic CLI source-entry gate; prepare never runs modeling."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEPENDENCY = ROOT / 'artifacts/experiments/model_run_dependency_gate_20261025/model/model-run.json'


def sha(path):
    value, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            size += len(block); value.update(block)
    return {'uri': str(path), 'sha256': value.hexdigest(), 'size_bytes': size}


def small(path):
    assert path.stat().st_size <= 2_000_000
    return json.loads(path.read_bytes())


def put(path, document):
    with path.open('x') as stream:
        json.dump(document, stream, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def prepare(label):
    assert not (HERE / 'freeze.json').exists()
    dependency = small(DEPENDENCY)
    prior = small(ROOT / 'artifacts/experiments/source_entry_catalog_gate_20261025/freeze.json')
    inputs = {ref['uri']: {k: ref[k] for k in ('uri', 'sha256', 'size_bytes')} for ref in prior['inputs']}
    terminal = dependency['terminal']
    inputs[terminal['uri']] = terminal
    original = small(Path(dependency['input_terminal']['uri']))
    inputs[dependency['input_terminal']['uri']] = {k: dependency['input_terminal'][k] for k in ('uri', 'sha256', 'size_bytes')}
    for name in ('source_composition', 'source_inventory', 'source_layers', 'workload_witness'):
        ref = original['products'][name]
        inputs[ref['uri']] = {k: ref[k] for k in ('uri', 'sha256', 'size_bytes')}
    # Bootstrap raw/source headers needed for scope conservation; no raw stream.
    for name in ('source_seeds', 'source_bindings'):
        ref = original['products'][name]
        inputs[ref['uri']] = {k: ref[k] for k in ('uri', 'sha256', 'size_bytes')}
    archive_ref = original['products']['workload_witness']
    archive = small(Path(archive_ref['uri']))
    for kind in ('sources', 'modules'):
        for row in archive[kind].values():
            artifact = row['artifact']; path = Path(archive_ref['uri']).parent / artifact['path']
            inputs[str(path)] = {'uri': str(path), 'sha256': artifact['sha256'], 'size_bytes': artifact['bytes']}
    sources = [sha(path) for path in sorted((ROOT / 'scar').rglob('*.py'))]
    put(HERE / 'freeze.json', {'schema': 'scar.model-run-source-entry-freeze/1', 'head_label': label,
        'entry': sha(Path(__file__).resolve()), 'sources': sources, 'inputs': list(inputs.values()),
        'dependency_terminal': terminal, 'entry_stage': 'source-entries',
        'native_OS_dependency_replay': False, 'source_payload_copies': 0,
        'graph_decode_during_prepare': 0, 'runtime_binary_freeze': 'OPEN',
        'budget': {'entry_profile_defaults': True, 'window': 1, 'files': 1, 'total_ops': 4000,
                   'selecteddecode': 128_000_000, 'record': 64_000_000, 'output': 128_000_000, 'external_seconds': 180}})
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(HERE / 'freeze.json'), 'sources': len(sources)}))


def verify(freeze):
    assert sorted(str(x) for x in (ROOT / 'scar').rglob('*.py')) == sorted(x['uri'] for x in freeze['sources'])
    count = 0
    for ref in [freeze['entry'], *freeze['sources'], *freeze['inputs']]:
        actual = sha(Path(ref['uri']))
        assert actual == {k: ref[k] for k in actual}, 'frozen bytes changed: ' + ref['uri']
        count += actual['size_bytes']
    return count


def run():
    freeze = small(HERE / 'freeze.json')
    result = {'schema': 'scar.model-run-source-entry-gate/1', 'status': 'RUNNING', 'whole_model': 'OPEN'}
    started = time.monotonic()
    assert not (HERE / 'model').exists()
    try:
        result['precheck_stored_bytes_read'] = verify(freeze)
        from scar.cli import main
        result['cli_exit'] = main(['model-run', '--from-model-run', freeze['dependency_terminal']['uri'],
                                  '--stage', 'source-entries', '--out', str(HERE / 'model')])
        document = small(HERE / 'model/model-run.json')
        result['model_root'] = sha(HERE / 'model/model-run.json')
        result['workflow_status'] = document['status']
        result['workflow_attempt'] = document.get('attempt')
        result['workflow_terminal'] = document.get('terminal')
        result['workflow_failure'] = document.get('failure')
        result['original_denominators'] = document.get('original_denominators')
        result['worker'] = document.get('worker')
        result['readonly_activity'] = document.get('readonly_activity')
        result['project_frontiers'] = document.get('project_entry_frontiers')
        result['postcheck_stored_bytes_read'] = verify(freeze)
        result['status'] = 'ACTUAL_CLI_SOURCE_ENTRY_WITH_OPEN' if result['cli_exit'] == 0 else 'FAILED'
    except BaseException as error:
        result.update(status='FAILED', failure={'type': type(error).__name__, 'detail': str(error)})
    result['wall_seconds'] = time.monotonic() - started
    put(HERE / 'result.json', result)
    print(json.dumps({'status': result['status'], 'wall_seconds': result['wall_seconds']}), flush=True)
    return 1 if result['status'] == 'FAILED' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--head-label', default='root supplied; actual source bytes independently pinned')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.head_label)
    else:
        raise SystemExit(run())

"""One ordinary public collector capture; stop before all offline modeling."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROJECT = HERE / 'project'
CAPTURE = HERE / 'capture'


def sha(path):
    h, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            h.update(block); size += len(block)
    return {'uri': str(path), 'sha256': h.hexdigest(), 'size_bytes': size}


def put(path, doc):
    with path.open('x') as stream:
        json.dump(doc, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write('\n')


def prepare(label):
    assert not (HERE / 'capture-freeze.json').exists() and not CAPTURE.exists()
    put(HERE / 'capture-freeze.json', {'schema': 'scar.project-dependency-capture-freeze/1', 'head_label': label,
        'sources': [sha(path) for path in sorted((ROOT / 'scar').rglob('*.py'))],
        'entry': [sha(HERE / 'capture.py'), sha(HERE / 'run.sh'), sha(PROJECT / 'probe.py')],
        'scope': 'one new CPU capture only; offline modeling explicitly paused',
        'capture_budget': {'call_events': 4096, 'call_bytes': 2_000_000, 'operand_events': 12000,
            'operand_bytes': 4_000_000, 'OS_bytes': 64_000_000, 'capture_bytes': 64_000_000,
            'archive_bytes': 32_000_000, 'provider_seconds': 120, 'outer_seconds': 180},
        'CUDA_VISIBLE_DEVICES': '', 'SCAR_NATIVE_TENSOR_INPUTS': '1', 'runtime_binary_freeze': 'OPEN'})
    print(json.dumps({'status': 'PREPARED_NOT_CAPTURED', 'freeze': sha(HERE / 'capture-freeze.json')}), flush=True)


def verify(freeze):
    assert sorted(str(path) for path in (ROOT / 'scar').rglob('*.py')) == sorted(row['uri'] for row in freeze['sources'])
    total = 0
    for old in (*freeze['entry'], *freeze['sources']):
        assert sha(Path(old['uri'])) == old, 'frozen bytes changed: ' + old['uri']
        total += old['size_bytes']
    return total


def run():
    freeze = json.loads((HERE / 'capture-freeze.json').read_bytes())
    assert not CAPTURE.exists() and not (HERE / 'capture-result.json').exists()
    started = time.monotonic()
    result = {'schema': 'scar.project-dependency-capture/1', 'status': 'RUNNING',
              'capture_attempts': 1, 'offline_modeling': 'NOT_RUN', 'whole_model': 'OPEN'}
    command = [sys.executable, '-B', '-m', 'scar.cli', 'trace', '--call-operands', '--execution-evidence',
        '--tensor-physical', '--project-root', str(PROJECT), '--os-capture-root', str(CAPTURE),
        '--out', str(CAPTURE / 'trace'), '--max-call-events', '4096', '--max-call-bytes', '2000000',
        '--max-operand-events', '12000', '--max-operand-bytes', '4000000', '--max-os-bytes', '64000000',
        '--max-capture-bytes', '64000000', '--max-archive-bytes', '32000000', '--os-timeout', '120',
        '--', sys.executable, '-B', str(PROJECT / 'probe.py')]
    result.update(command=command, cwd=str(PROJECT))
    try:
        result['precheck_source_stored_bytes'] = verify(freeze)
        env = dict(os.environ, SCAR_NATIVE_TENSOR_INPUTS='1', CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT))
        with (HERE / 'target.stdout.txt').open('x') as stdout, (HERE / 'target.stderr.txt').open('x') as stderr:
            completed = subprocess.run(command, cwd=PROJECT, env=env, stdout=stdout, stderr=stderr)
        result['actual_cli_exit'] = completed.returncode
        result['postcheck_source_stored_bytes'] = verify(freeze)
        result['status'] = 'CAPTURED_OFFLINE_PAUSED' if completed.returncode == 0 else 'FAILED_PARTIAL_RETAINED'
        if (CAPTURE / 'archive-index.json').is_file():
            result['archive_root'] = sha(CAPTURE / 'archive-index.json')
        if (CAPTURE / 'capture-coordinates.json').is_file():
            result['coordinate_root'] = sha(CAPTURE / 'capture-coordinates.json')
    except BaseException as error:
        result.update(status='FAILED_PARTIAL_RETAINED', failure={'type': type(error).__name__, 'detail': str(error),
                                                               'traceback': traceback.format_exc()})
    result['wall_seconds'] = time.monotonic() - started
    put(HERE / 'capture-result.json', result)
    print(json.dumps({'status': result['status'], 'actual_cli_exit': result.get('actual_cli_exit'),
                      'wall_seconds': result['wall_seconds'], 'offline_modeling': 'NOT_RUN'}), flush=True)
    return int(result['status'] != 'CAPTURED_OFFLINE_PAUSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--head-label', default='root supplied; actual source bytes pinned')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.head_label)
    else:
        raise SystemExit(run())

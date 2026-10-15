"""Generic runtime-source bridge acceptance runner; never executes target."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import tokenize


def git(*args, cwd):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('entry', type=Path)
    p.add_argument('--project-root', type=Path, required=True)
    p.add_argument('--prefix', type=Path, required=True)
    p.add_argument('--max-files', type=int, default=256)
    p.add_argument('--trace', type=Path, required=True)
    args = p.parse_args()
    root = Path.cwd()
    sys.path.insert(0, str(root))
    prefix = args.prefix.resolve()
    inventory = Path(str(prefix) + '-inventory.json.gz')
    from scripts.run_gate import fingerprint
    initial_hash, _ = fingerprint()
    receipt = {
        'schema': 'scar.source-pressure', 'revision': git('rev-parse', 'HEAD', cwd=root),
        'source_sha256': initial_hash, 'initial_worktree': git('status', '--porcelain', cwd=root),
        'target_head': git('rev-parse', 'HEAD', cwd=args.project_root),
        'target_status_before': git('status', '--porcelain', cwd=args.project_root),
        'target_executed': False, 'python': sys.version, 'stages': [],
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    from scar.trace.files import resolve
    trace_file = resolve(args.trace.resolve(), default_name='events.jsonl')
    receipt['trace_file_sha256_before'] = hashlib.sha256(trace_file.read_bytes()).hexdigest()
    commands = (
        ('analysis', [sys.executable, '-m', 'scar.cli', 'inventory-program', str(args.entry.resolve()),
                      '--project-root', str(args.project_root.resolve()), '--max-files', str(args.max_files),
                      '--out', str(inventory)]),
        ('replay', [sys.executable, '-m', 'scar.cli', 'check-inventory', str(inventory),
                    '--max-files', str(args.max_files)]),
    )
    commands[0][1].extend(['--trace', str(args.trace.resolve())])
    for name, command in commands:
        time_file = Path(str(prefix) + '-' + name + '.time.txt')
        timed = ['/usr/bin/time', '-v', '-o', str(time_file), *command]
        started = time.perf_counter()
        run = subprocess.run(timed, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        for stream in ('stdout', 'stderr'):
            Path(str(prefix) + '-' + name + '.' + stream + '.txt').write_text(getattr(run, stream))
        stage = {'name': name, 'command': command, 'returncode': run.returncode,
                 'wall_seconds': elapsed, 'time_file': str(time_file),
                 'stdout': run.stdout, 'stderr': run.stderr}
        receipt['stages'].append(stage)
        Path(str(prefix) + '-progress.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'stage': name, 'seconds': elapsed, 'returncode': run.returncode,
                          'stdout': run.stdout}), flush=True)
        if run.returncode != 0:
            break
    receipt['source_unchanged'] = fingerprint()[0] == initial_hash
    receipt['target_status_after'] = git('status', '--porcelain', cwd=args.project_root)
    receipt['target_unchanged'] = (receipt['target_status_before'] == receipt['target_status_after']
                                 and git('rev-parse', 'HEAD', cwd=args.project_root) == receipt['target_head'])
    if inventory.exists():
        with gzip.open(inventory, 'rt') as stream:
            doc = json.load(stream)
        receipt['runtime_trace_manifest'] = doc['runtime_scope']['trace']['manifest']
        receipt['trace_file_sha256_after'] = hashlib.sha256(trace_file.read_bytes()).hexdigest()
        receipt['trace_unchanged'] = receipt['trace_file_sha256_before'] == receipt['trace_file_sha256_after']
        receipt['summary'] = doc['summary']
        receipt['source_roots'] = doc['discovery']['source_roots']
        receipt['discovery_gaps'] = dict(Counter(g['kind'] for g in doc['discovery']['gaps']))
        receipt['file_preparation_issues'] = [g for file in doc['files'] for g in file['gaps']
                                             if g['detail'].startswith('file preparation/inventory failed')]
        receipt['source_fingerprints'] = []
        for file in doc['discovery']['files']:
            snapshot = file['snapshot']
            with tokenize.open(snapshot['path']) as stream:
                current = 'sha256:' + hashlib.sha256(stream.read().encode('utf-8')).hexdigest()
            receipt['source_fingerprints'].append({'path': snapshot['path'],
                                                    'unchanged': current == snapshot['fingerprint']})
        receipt['all_read_sources_unchanged'] = all(f['unchanged'] for f in receipt['source_fingerprints'])
        receipt['compressed_bytes'] = inventory.stat().st_size
        receipt['artifact_sha256'] = hashlib.sha256(inventory.read_bytes()).hexdigest()
    receipt['status'] = ('PASS_RUNTIME_SOURCE_BRIDGE' if len(receipt['stages']) == 2
        and all(s['returncode'] == 0 for s in receipt['stages']) and receipt['source_unchanged']
        and receipt['target_unchanged'] and receipt.get('all_read_sources_unchanged') and receipt.get('trace_unchanged') else 'INCOMPLETE')
    receipt['whole_program_model_established'] = False
    receipt['optimization_verified'] = False
    Path(str(prefix) + '-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('stages', 'source_fingerprints')}), flush=True)
    return 0 if receipt['status'] == 'PASS_RUNTIME_SOURCE_BRIDGE' else 1


if __name__ == '__main__':
    raise SystemExit(main())

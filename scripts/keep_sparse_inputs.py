"""Preserve materialized tracked files while restoring exact artifact pins.

Development workspace tool; never changes existing different bytes or restores
source code. Pin files contain rows {path, bytes, sha256} under an explicit key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def check(path, row):
    if path.is_symlink() or not path.is_file():
        raise ValueError('pin must be a regular non-symlink file: ' + str(path))
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while data := stream.read(1_048_576):
            size += len(data)
            digest.update(data)
    if (size, digest.hexdigest()) != (row['bytes'], row['sha256']):
        raise ValueError('existing bytes differ; refusing overwrite: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--key', default='inputs')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError('fresh recovery report required')
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    document = args.pins.read_bytes()
    rows = json.loads(document)[args.key]
    if type(rows) is not list or not rows:
        raise ValueError('explicit nonempty pin list required')
    paths = set()
    missing = []
    for row in rows:
        path = Path(row['path'])
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('canonical absolute pin path required')
        if path.exists():
            check(path, row)
        elif path.is_relative_to(root / 'artifacts'):
            missing.append(str(path))
        else:
            raise ValueError('only missing own artifact files may be restored: ' + str(path))
        if path.is_relative_to(root):
            paths.add(path.relative_to(root).as_posix())
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    kept = {name for name in tracked if name and (root / name).is_file()}
    selected = sorted(kept | paths)
    escape = lambda text: ''.join('\\' + c if c in '*?[]\\' else c for c in text)
    patterns = '\n'.join('/' + escape(name) for name in selected) + '\n'
    mode = subprocess.run(['git', 'config', '--bool', 'core.sparseCheckoutCone'],
                          cwd=root, text=True, capture_output=True)
    if mode.stdout.strip() != 'false':
        raise ValueError('this recovery tool requires an existing non-cone sparse checkout')
    subprocess.run(['git', 'sparse-checkout', 'add', '--stdin'],
                   cwd=root, input=patterns, text=True, check=True)
    lost = [name for name in kept if not (root / name).is_file()]
    if lost:
        raise ValueError('previously materialized files lost: ' + repr(lost))
    for row in rows:
        check(Path(row['path']), row)
    result = {'pins': str(args.pins.absolute()), 'pin_document_sha256': hashlib.sha256(document).hexdigest(),
              'verified_pins': len(rows), 'pin_bytes_per_hash_pass': sum(r['bytes'] for r in rows),
              'previously_materialized_tracked_files_preserved': len(kept),
              'exact_patterns_added': len(selected), 'restored_missing': missing,
              'existing_different_bytes_overwritten': False, 'old_gate_status_changed': False,
              'graph_or_trace_decoded': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'restored_missing'}))


if __name__ == '__main__':
    main()

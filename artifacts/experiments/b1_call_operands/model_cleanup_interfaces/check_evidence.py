"""Check archived C1 receipts and hashes without rerunning tests or workloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    for relative, expected in manifest['files'].items():
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise ValueError(f'Archive path escapes: {relative}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'Archive hash mismatch: {relative}')
    component = json.loads((root / 'component-final.json').read_text())
    full = json.loads((root / 'full/report.json').read_text())
    before = json.loads((root / 'full/source.before.json').read_text())
    after = json.loads((root / 'full/source.after.json').read_text())
    expected_revision = '0ea05e6b57a03a6d717c5be5008d0541aa3f4975'
    expected_source = '9e717dc3acfa0701e710bd0f8c6dc76ebd3ced2530af43470bc3cff797e768c7'
    if component['status'] != 'PASS' or component['returncode'] != 0:
        raise ValueError('Component did not pass')
    if (not component['source_unchanged_during_test']
            or component['source_sha256'] != expected_source
            or len(component['tested_files']) != 391
            or len(component['criteria']) != 6
            or any(row['status'] != 'PASS' for row in component['criteria'])):
        raise ValueError('Component identity or criteria mismatch')
    component_cases = {(case['class'], case['name'])
                       for row in component['criteria'] for item in row['evidence']
                       for case in item['cases']}
    if len(component_cases) != 243:
        raise ValueError('Mapped component case count mismatch')
    if (full['status'] != 'PASS' or full['returncode'] != 0
            or not full['source_unchanged_during_test']
            or full['nonpassing_cases'] or full['driver_errors']
            or any(full['counts'][key] for key in ('failed', 'error', 'skipped'))
            or full['counts']['total'] <= 3215):
        raise ValueError('Full run did not meet acceptance')
    if before != after:
        raise ValueError('Frozen snapshots changed')
    if (before['revision'] != expected_revision or before['worktree_status']
            or before['source_sha256'] != expected_source
            or before['source_file_count'] != 391
            or before['files'] != component['tested_files']):
        raise ValueError('Frozen identity mismatch')
    if full['basetemp_cleanup'] != 'removed exclusively owned basetemp after child termination':
        raise ValueError('Owned temporary directory cleanup failed')
    print(json.dumps({'status': 'PASS', 'scope': 'archived receipts and file hashes only',
                      'archive_files': len(manifest['files']),
                      'implementation': expected_revision,
                      'component_cases': len(component_cases), 'full_counts': full['counts'],
                      'fixture_files': len(before['fixture_sha256'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()

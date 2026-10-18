"""Verify the bounded D1 archive; do not execute tests or a workload."""
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('manifest.json')
    for name, receipt in manifest['files'].items():
        path = (BASE / name).resolve()
        assert BASE in path.parents, name
        raw = path.read_bytes()
        assert len(raw) == receipt['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == receipt['sha256'], name
    acceptance = read('acceptance.json')
    component, full = read('component/final.json'), read('full/report.json')
    before, after = read('full/source.before.json'), read('full/source.after.json')
    assert acceptance['status'] == component['status'] == full['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    assert before['revision'] == full['revision_before'] == full['revision_after'] == acceptance['implementation_revision']
    assert acceptance['source_sha256'] == component['source_sha256'] == before['source_sha256']
    assert component['tested_files'] == before['files']
    assert len(before['files']) == acceptance['source_file_count'] == 415
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    cases = {(case['class'], case['name']) for row in component['criteria']
             for evidence in row['evidence'] for case in evidence['cases']}
    assert len(component['criteria']) == 13 and all(row['status'] == 'PASS' for row in component['criteria'])
    assert len(cases) == acceptance['component_checks'] == 671
    assert component['returncode'] == full['returncode'] == 0
    assert full['counts'] == acceptance['full_counts']
    assert not any(full['counts'][k] for k in ('failed', 'error', 'skipped'))
    assert len(before['fixture_sha256']) == acceptance['fixture_file_count'] == 29
    previous = read('../model_driver_interfaces/full/source.after.json')
    assert all(before['fixture_sha256'][name] == digest for name, digest in previous['fixture_sha256'].items())
    assert len(previous['fixture_sha256']) == 26
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    assert acceptance['d1_static_structure_verified'] is True
    assert all(acceptance[name] is False for name in (
        'full_first_stage_complete', 'full_c2_complete', 'driver_lifecycle_verified',
        'source_recovery_verified', 'runtime_resumption_verified',
        'transformation_verified', 'lewm_speedup_measured'))
    protected = read('protected-checkouts.json')['checkouts']
    assert all(not row['worktree_status'] for row in protected.values())
    print(json.dumps({'status': 'PASS', 'files': len(manifest['files']),
        'component_checks': len(cases), 'full_counts': full['counts'],
        'd1_static_structure_verified': True, 'source_unchanged': True,
        'driver_lifecycle_verified': False}))


if __name__ == '__main__':
    main()

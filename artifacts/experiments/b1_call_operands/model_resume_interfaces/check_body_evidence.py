"""Verify the supplemental C2B archive without rerunning tests or workloads."""
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('body-manifest.json')
    for name, expected in manifest['files'].items():
        path = BASE / name
        if path.resolve().parent != BASE and BASE not in path.resolve().parents:
            raise ValueError('archive path escapes its directory')
        raw = path.read_bytes()
        assert len(raw) == expected['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == expected['sha256'], name
    acceptance = read('body-acceptance.json')
    component, full = read('body-component/final.json'), read('body-full/report.json')
    before, after = read('body-full/source.before.json'), read('body-full/source.after.json')
    assert acceptance['status'] == component['status'] == full['status'] == 'PASS'
    assert before == after
    assert full['revision_before'] == full['revision_after'] == acceptance['implementation_revision']
    assert not before['worktree_status'] and not after['worktree_status']
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    assert (component['source_sha256'] == before['source_sha256'] == after['source_sha256']
            == acceptance['source_sha256'])
    assert len(component['tested_files']) == len(before['files']) == acceptance['source_file_count']
    assert component['tested_files'] == before['files']
    assert len(component['criteria']) == 7 and all(row['status'] == 'PASS' for row in component['criteria'])
    cases = {(case['class'], case['name'])
             for criterion in component['criteria'] for evidence in criterion['evidence']
             for case in evidence['cases']}
    assert acceptance['component_checks'] == len(cases) == 499
    assert full['returncode'] == component['returncode'] == 0
    assert full['counts'] == acceptance['full_counts']
    assert not any(full['counts'][kind] for kind in ('failed', 'error', 'skipped'))
    assert len(before['fixture_sha256']) == acceptance['fixture_file_count']
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    assert all(acceptance[name] is False for name in (
        'full_first_stage_complete', 'full_c2_complete', 'source_recovery_verified',
        'driver_verified', 'runtime_resumption_verified', 'transformation_verified',
        'lewm_speedup_measured'))
    print(json.dumps({'status': 'PASS', 'files': len(manifest['files']),
        'implementation_revision': acceptance['implementation_revision'],
        'component_checks': acceptance['component_checks'], 'full_counts': full['counts'],
        'source_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Read-only saved D2.4 evidence verification; starts no tests or workloads."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def identities(cases):
    return {(case['class'], case['name']) for case in cases}


def main():
    manifest = read('manifest.json')['files']
    actual = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
              if path.is_file() and path != BASE / 'manifest.json'}
    assert actual == set(manifest)
    for name, item in manifest.items():
        path = (BASE / name).resolve()
        assert BASE in path.parents and not (BASE / name).is_symlink(), name
        raw = path.read_bytes()
        assert len(raw) == item['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == item['sha256'], name
    accepted, component, full = (read(name) for name in (
        'acceptance.json', 'component/report.json', 'full/report.json'))
    before, after = read('full/source.before.json'), read('full/source.after.json')
    assert accepted['status'] == component['status'] == full['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    assert before['revision'] == full['revision_before'] == full['revision_after'] == accepted['implementation_revision']
    assert accepted['source_sha256'] == component['source_sha256'] == before['source_sha256']
    assert component['tested_files'] == before['files']
    assert len(before['files']) == accepted['source_file_count'] == 451
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    cases = read('full/cases.json')
    full_ids = identities(cases)
    assert len(full_ids) == len(cases) == full['counts']['total'] == 4050
    assert full['counts'] == accepted['full_counts']
    assert not any(full['counts'][key] for key in ('failed', 'error', 'skipped'))
    component_ids = identities([case for criterion in component['criteria']
        for evidence in criterion['evidence'] for case in evidence['cases']])
    assert len(component['criteria']) == accepted['component_criteria'] == 32
    assert len(component_ids) == accepted['component_checks'] == 1015
    assert all(criterion['status'] == 'PASS' for criterion in component['criteria'])
    assert all(case['status'] == 'PASS' for criterion in component['criteria']
               for evidence in criterion['evidence'] for case in evidence['cases'])
    assert component_ids <= full_ids and component['returncode'] == full['returncode'] == 0
    prior_ids = identities(read('../model_session_release/full/cases.json'))
    assert len(prior_ids) == 4009 and prior_ids <= full_ids
    assert len(full_ids - prior_ids) == accepted['new_full_cases'] == 41
    fixtures = before['fixture_sha256']
    previous = read('../model_session_release/full/source.after.json')['fixture_sha256']
    assert len(previous) == accepted['prior_fixture_file_count'] == 38
    assert all(fixtures[name] == digest for name, digest in previous.items())
    assert accepted['prior_fixtures_unchanged'] and len(fixtures) == accepted['fixture_file_count'] == 42
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    protected = read('protected-checkouts.json')['checkouts']
    assert all(not row['worktree_status'] and row['revision'] == row['expected_revision']
               for row in protected.values())
    assert read('historical/result.json')['returncode'] == 0
    assert all(accepted[key] is True for key in (
        'lifecycle_composition_verified', 'conditional_public_scope_implemented'))
    assert all(accepted[key] is False for key in (
        'full_first_stage_complete', 'full_c2_complete', 'source_runtime_verified',
        'native_applicability_verified', 'physical_release_or_ready_verified',
        'transformation_verified', 'lewm_speedup_measured'))
    print(json.dumps({'archive_integrity': 'PASS', 'files': len(manifest),
        'component_checks': len(component_ids), 'full_counts': full['counts'],
        'source_unchanged': True, 'lifecycle_composition_verified': True,
        'full_first_stage_complete': False}))


if __name__ == '__main__':
    main()

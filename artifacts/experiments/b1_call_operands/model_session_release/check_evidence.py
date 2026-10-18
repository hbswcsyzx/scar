"""Verify saved D2.3 evidence only; no tests, probes or workload execution."""
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
    acceptance = read('acceptance.json')
    component, full = read('component/final.json'), read('full/report.json')
    before, after = read('full/source.before.json'), read('full/source.after.json')
    assert acceptance['status'] == component['status'] == full['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    assert before['revision'] == full['revision_before'] == full['revision_after'] == acceptance['implementation_revision']
    assert acceptance['source_sha256'] == component['source_sha256'] == before['source_sha256']
    assert component['tested_files'] == before['files']
    assert len(before['files']) == acceptance['source_file_count'] == 443
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    component_cases = identities([case for criterion in component['criteria']
        for evidence in criterion['evidence'] for case in evidence['cases']])
    assert len(component['criteria']) == acceptance['component_criteria'] == 27
    assert all(criterion['status'] == 'PASS' for criterion in component['criteria'])
    assert len(component_cases) == acceptance['component_checks'] == 974
    assert component['returncode'] == full['returncode'] == 0
    assert full['counts'] == acceptance['full_counts']
    assert not any(full['counts'][key] for key in ('failed', 'error', 'skipped'))
    cases = read('full/cases.json')
    full_cases = identities(cases)
    assert len(full_cases) == len(cases) == full['counts']['total'] == 4009
    assert component_cases <= full_cases
    previous_cases = identities(read('../model_no_body/full/cases.json'))
    assert len(previous_cases) == 3871 and previous_cases <= full_cases
    assert len(full_cases - previous_cases) == acceptance['new_full_cases'] == 138
    fixtures = before['fixture_sha256']
    previous = read('../model_no_body/full/source.after.json')['fixture_sha256']
    assert len(previous) == acceptance['prior_fixture_file_count'] == 35
    assert all(fixtures[name] == digest for name, digest in previous.items())
    assert acceptance['prior_fixtures_unchanged'] and len(fixtures) == acceptance['fixture_file_count'] == 38
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    assert all(acceptance[key] is True for key in (
        'session_release_declaration_verified', 'terminal_ef_t_product_implemented',
        'current_session_p_product_implemented'))
    assert all(acceptance[key] is False for key in (
        'full_first_stage_complete', 'full_c2_complete', 'full_d2_complete',
        'source_runtime_verified', 'native_applicability_verified',
        'physical_release_or_ready_verified', 'transformation_verified', 'lewm_speedup_measured'))
    protected = read('protected-checkouts.json')['checkouts']
    assert all(not row['worktree_status'] and row['revision'] == row['expected_revision']
               for row in protected.values())
    history = read('historical/result.json')
    assert history['returncode'] == 0 and history['output_exists'] and history['proof_exists']
    print(json.dumps({'archive_integrity': 'PASS', 'files': len(manifest),
        'component_checks': len(component_cases), 'full_counts': full['counts'],
        'source_unchanged': True, 'session_release_declaration_verified': True,
        'terminal_ef_t_product_implemented': True, 'current_session_p_product_implemented': True,
        'full_d2_complete': False}))


if __name__ == '__main__':
    main()

"""Verify saved publication acceptance; never run a test, probe or workload."""
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
    assert len(before['files']) == acceptance['source_file_count'] == 423
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    component_cases = identities([case for criterion in component['criteria']
        for evidence in criterion['evidence'] for case in evidence['cases']])
    assert len(component['criteria']) == 17
    assert all(criterion['status'] == 'PASS' for criterion in component['criteria'])
    assert len(component_cases) == acceptance['component_checks'] == 741
    assert component['returncode'] == full['returncode'] == 0
    assert full['counts'] == acceptance['full_counts']
    assert not any(full['counts'][key] for key in ('failed', 'error', 'skipped'))
    current_cases = read('full/cases.json')
    full_cases = identities(current_cases)
    assert len(full_cases) == len(current_cases) == full['counts']['total']
    assert component_cases <= full_cases
    previous_cases = identities(read('../model_driver_implementation/full/cases.json'))
    assert len(previous_cases) == 3706 and previous_cases <= full_cases
    assert len(full_cases - previous_cases) == acceptance['new_full_cases'] == 70
    fixtures = before['fixture_sha256']
    assert len(fixtures) == acceptance['fixture_file_count'] == 32
    previous = read('../model_driver_implementation/full/source.after.json')
    assert len(previous['fixture_sha256']) == 29
    assert all(fixtures[name] == digest for name, digest in previous['fixture_sha256'].items())
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    assert acceptance['body_publication_declaration_verified'] is True
    assert all(acceptance[key] is False for key in (
        'full_first_stage_complete', 'full_c2_complete', 'full_d2_complete',
        'no_body_product_implemented', 'session_release_product_implemented',
        'efp_product_analysis_implemented', 'source_runtime_verified',
        'transformation_verified', 'lewm_speedup_measured'))
    protected = read('protected-checkouts.json')['checkouts']
    assert all(not row['worktree_status'] and row['revision'] == row['expected_revision']
               for row in protected.values())
    history = read('historical/result.json')
    assert history['returncode'] == 0 and history['output_exists'] and history['proof_exists']
    assert read('historical/attempt-001/result.json')['fixture_created'] is False
    print(json.dumps({'archive_integrity': 'PASS', 'files': len(manifest),
        'component_checks': len(component_cases), 'full_counts': full['counts'],
        'new_full_cases': 70, 'source_unchanged': True,
        'body_publication_declaration_verified': True, 'full_d2_complete': False}))


if __name__ == '__main__':
    main()

"""Read-only generator-matrix receipt check; starts zero tests/workloads."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_protocol_implementation'


def read(path):
    return json.loads(path.read_text())


def main():
    files = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == files
    closure = read(HERE / 'closure.json')
    component = read(HERE / closure['component'] / 'report.json')
    final_full = HERE / closure['full']
    full = read(final_full / 'report.json')
    before, after = (read(final_full / f'source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert component['returncode'] == full['returncode'] == 0
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    assert before == after and not before['worktree_status']
    assert before['revision'] == closure['implementation_revision']
    subprocess.run(['git', 'merge-base', '--is-ancestor', before['revision'], 'HEAD'], cwd=ROOT, check=True)
    assert before['files'] == component['tested_files']
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert len(before['files']) == closure['source_files']
    assert len(component['criteria']) == closure['criteria']
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    component_cases = {(case['class'], case['name']) for criterion in component['criteria']
                       for item in criterion['evidence'] for case in item['cases']}
    assert len(component_cases) == closure['component_cases']
    assert hashlib.sha256((final_full / 'driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert not full['driver_errors']
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for directory in ('full', closure['full']):
        for path, expected in read(HERE / directory / 'manifest.json')['files'].items():
            assert files[directory + '/' + path] == expected
    # The initial failed full is evidence, not a replaced or successful attempt.
    failed = read(HERE / 'full/report.json')
    failed_before = read(HERE / 'full/source.before.json')
    assert failed['status'] == 'FAIL' and failed['returncode'] == 1
    assert failed['counts'] == {'passed': 5672, 'failed': 1, 'error': 0, 'skipped': 0, 'total': 5673}
    assert failed['expected_revision'] == '44d56af52d65cd3440f4600fa05ea34fd03ad7f1'
    assert failed['source_unchanged_during_test']
    assert failed_before == read(HERE / 'full/source.after.json')
    assert failed_before['source_file_count'] == 646
    assert failed_before['source_sha256'] == 'fc6ebabbd4fd670dbe497cfcb61c53e9db83fbf198b3081055134b9da93e0ef0'
    assert len(failed['nonpassing_cases']) == 1
    assert failed['nonpassing_cases'][0]['name'] == (
        'test_created_close_derived_obligation_keeps_exact_test_finish_and_none_host_consumer')
    assert read(HERE / 'full-preflight/receipt.json')['pytest_process_started'] is False
    assert read(HERE / 'repair/red/attempt001/result.json')['returncode'] == 1
    assert read(HERE / 'repair/focused/attempt001/result.json')['returncode'] == 0
    previous = read(PRIOR / 'full/source.before.json')
    assert len(previous['files']) == 617 and set(previous['files']) <= before['files'].keys()
    assert len(previous['fixture_sha256']) == 82
    assert all(before['fixture_sha256'].get(path) == sha for path, sha in previous['fixture_sha256'].items())
    fixtures = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / 'tests/fixtures').rglob('*'))
        if path.is_file() and '__pycache__' not in path.parts}
    assert fixtures == before['fixture_sha256']
    old_cases, cases = read(PRIOR / 'full/cases.json'), read(final_full / 'cases.json')
    identity = lambda case: (case['class'], case['name'])
    old_set, case_set = ({identity(case) for case in rows} for rows in (old_cases, cases))
    assert len(old_set) == len(old_cases) == 5401 and old_set <= case_set
    failed_cases = read(HERE / 'full/cases.json')
    failed_set = {identity(case) for case in failed_cases}
    assert len(failed_set) == len(failed_cases) == 5673 and failed_set <= case_set
    assert len(case_set) == len(cases) == closure['full_cases']
    assert component_cases <= case_set
    assert full['counts'] == {'passed': len(cases), 'failed': 0, 'error': 0, 'skipped': 0, 'total': len(cases)}
    preservation = read(HERE / 'preservation.json')
    assert preservation['preserved_previous_cases'] == 5401
    assert preservation['preserved_initial_full_cases'] == 5673
    assert preservation['missing_cases'] == preservation['removed_source_files'] == preservation['changed_previous_fixtures'] == []
    protected_before, protected_after = (read(HERE / f'protected.{phase}.json') for phase in ('before', 'after'))
    assert protected_before == protected_after and all(not row['status'] for row in protected_after.values())
    for row in protected_after.values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip() == row['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip() == row['status']
    assert closure['status'] == 'PASS_WITH_SCOPE_P2_DECLARED_MATRIX'
    assert closure['p2_declared_matrix_complete'] is True
    assert not any(closure[key] for key in ('d3_complete', 'm0_m2_complete',
        'scope_inventory_complete', 'source_runtime_verified', 'value_identity_verified',
        'transformation_authorized', 'new_lewm_speedup_measurement'))
    for path, sha in closure['documents'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    digest, current = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert digest == closure['source_sha256'] and current == before['files']
    focused = read(HERE / closure['final_focused'] / 'result.json')
    assert focused['returncode'] == 0 and focused['source_unchanged']
    assert read(HERE / closure['final_focused'] / 'sources.before.json') == before['files']
    assert read(HERE / closure['final_focused'] / 'sources.after.json') == before['files']
    assert focused['source_sha256_before'] == closure['source_sha256']
    assert focused['source_sha256_after'] == closure['source_sha256']
    print(json.dumps({'status': 'PASS', 'scope': closure['status'], 'archived_files': len(files),
        'criteria': closure['criteria'], 'component_cases': len(component_cases), 'full_cases': len(cases),
        'preserved_previous_cases': len(old_set), 'preserved_initial_full_cases': len(failed_set),
        'initial_full_status': failed['status'], 'source_files': len(current), 'fixtures': len(fixtures),
        'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

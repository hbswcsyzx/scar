"""Read-only R3.1 evidence check; starts zero tests, profilers or workloads."""
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_validity'


def read(path):
    return json.loads(path.read_text())


def main():
    files = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE/'manifest.json'}
    assert read(HERE/'manifest.json')['files'] == files
    closure = read(HERE/'closure.json')
    component, full = (read(HERE/path) for path in ('component/final/report.json', 'full/report.json'))
    before, after = (read(HERE/f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert component['returncode'] == full['returncode'] == 0
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    assert before == after and not before['worktree_status']
    assert before['revision'] == closure['implementation_revision']
    assert before['files'] == component['tested_files']
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert len(before['files']) == closure['source_files']
    assert len(component['criteria']) == closure['criteria'] == 8
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    component_cases = {(case['class'], case['name']) for criterion in component['criteria']
                       for item in criterion['evidence'] for case in item['cases']}
    assert len(component_cases) == closure['component_cases']
    assert hashlib.sha256((HERE/'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert not full['driver_errors']
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for path, expected in read(HERE/'full/manifest.json')['files'].items():
        assert files['full/'+path] == expected
    previous = read(PRIOR/'full/source.before.json')
    assert len(previous['files']) == 544 and set(previous['files']) <= before['files'].keys()
    assert len(previous['fixture_sha256']) == 65
    assert all(before['fixture_sha256'].get(p) == sha for p, sha in previous['fixture_sha256'].items())
    old_cases, cases = (read(base/'full/cases.json') for base in (PRIOR, HERE))
    identity = lambda case: (case['class'], case['name'])
    old_set, case_set = ({identity(case) for case in rows} for rows in (old_cases, cases))
    assert len(old_set) == len(old_cases) == 4826 and old_set <= case_set
    assert len(case_set) == len(cases) == closure['full_cases']
    assert full['counts'] == {'passed': len(cases), 'failed': 0, 'error': 0, 'skipped': 0, 'total': len(cases)}
    preservation = read(HERE/'preservation.json')
    assert preservation['preserved_previous_cases'] == 4826
    assert preservation['missing_cases'] == preservation['removed_source_files'] == preservation['changed_previous_fixtures'] == []
    protected_before, protected_after = (read(HERE/f'protected.{phase}.json') for phase in ('before', 'after'))
    assert protected_before == protected_after and all(not row['status'] for row in protected_after.values())
    golden = ROOT/'tests/fixtures/execution_v6_frozen.json'
    proof = read(golden.with_suffix('.json.proof.json'))
    assert hashlib.sha256(golden.read_bytes()).hexdigest() == proof['payload_sha256']
    assert golden.stat().st_size == proof['payload_bytes']
    assert proof['revision'] == '348d18277b963bc183fb420bf173f05594d667d8'
    initial = read(HERE/'root_mat_before/attempt001/report.json')
    assert initial['returncode'] == 1
    assert (HERE/'root_mat_before/attempt001/junit.xml').is_file()
    assert not closure['source_runtime_verified'] and not closure['value_identity_verified']
    assert not closure['transformation_authorized'] and not closure['new_lewm_speedup_measurement']
    for path, sha in closure['documents'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == sha
    digest, current = runpy.run_path(str(ROOT/'scripts/run_gate.py'))['fingerprint']()
    assert digest == closure['source_sha256'] and current == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(files), 'criteria': closure['criteria'],
        'component_cases': len(component_cases), 'full_cases': len(cases),
        'preserved_previous_cases': len(old_set), 'source_files': len(current),
        'fixtures': len(before['fixture_sha256']), 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

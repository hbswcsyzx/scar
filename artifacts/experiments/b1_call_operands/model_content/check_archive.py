"""Read D evidence only. This checker starts no tests, providers or workloads."""
from pathlib import Path
import hashlib
import json
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'model_resource_ready'


def read(path):
    return json.loads(path.read_text())


def main():
    actual = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == actual
    closure = read(HERE / 'closure.json')
    component = read(HERE / 'component/final/report.json')
    full = read(HERE / 'full/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == 'PASS' and component['returncode'] == 0
    assert component['source_unchanged_during_test']
    assert len(component['criteria']) == 7
    cases = {(case['class'], case['name']) for criterion in component['criteria']
             for node in criterion['evidence'] for case in node['cases']}
    assert len(cases) == closure['component_cases']
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test'] and before == after
    assert before['revision'] == closure['implementation_revision']
    assert before['worktree_status'] == ''
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert before['files'] == component['tested_files']
    assert before['source_file_count'] == len(before['files']) == closure['source_files']
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for name, value in read(HERE / 'full/manifest.json')['files'].items():
        assert actual['full/' + name] == value
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 493 and set(old['files']) <= before['files'].keys()
    assert len(old['fixture_sha256']) == 50
    assert all(before['fixture_sha256'].get(p) == h for p, h in old['fixture_sha256'].items())
    old_cases, new_cases = (read(path / 'full/cases.json') for path in (PREVIOUS, HERE))
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in rows} for rows in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4427 and old_set <= new_set
    assert len(new_set) == len(new_cases) == closure['full_cases']
    assert full['counts'] == {'passed': len(new_set), 'failed': 0, 'error': 0, 'skipped': 0, 'total': len(new_set)}
    preservation = read(HERE / 'preservation.json')
    assert preservation['preserved_previous_cases'] == 4427
    assert preservation['missing_cases'] == [] and preservation['changed_previous_fixtures'] == []
    assert read(HERE / 'protected.before.json') == read(HERE / 'protected.after.json')
    assert all(not row['status'] for row in read(HERE / 'protected.after.json').values())
    proof = read(ROOT / 'tests/fixtures/execution_v3_frozen.proof.json')
    payload = (ROOT / 'tests/fixtures/execution_v3_frozen.json').read_bytes()
    assert hashlib.sha256(payload).hexdigest() == '8551cd9043cf0d13d20da40a41a7541b5781d4896fa8ed8ee473058006184b3f'
    assert len(payload) == 117878
    assert proof['source_revision'] == '6efbe272bceb1036eba3725f11c47960fd5dd301'
    # Original failed query attempt is retained, not overwritten by passing runs.
    assert read(HERE / 'queries/attempt001/run.json')['returncode'] == 1
    assert read(HERE / 'queries/attempt002/run.json')['returncode'] == 0
    assert read(HERE / 'queries/attempt003/run.json')['returncode'] == 0
    for path, digest in closure['documents'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == closure['source_sha256'] and files == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(actual), 'criteria': 7,
        'component_cases': len(cases), 'full_cases': len(new_set),
        'preserved_previous_cases': len(old_set), 'source_files': len(files),
        'fixtures': len(before['fixture_sha256']), 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

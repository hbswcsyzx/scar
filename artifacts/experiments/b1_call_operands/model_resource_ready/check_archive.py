"""Read R2.3-G evidence only, without starting tests, providers or workloads."""
from pathlib import Path
import hashlib
import json
import runpy

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
PREVIOUS = HERE.parent / 'model_resource_order'
FROZEN = 'aa2b9178e7a23ccfd86695b68524bf3817fe1673'
SOURCE = 'b2e1bcdb11b4d1df31832f4b7c2a77aa6d3d3b0f2ef45afb77df6db717460e48'


def read(path):
    return json.loads(path.read_text())


def main():
    actual = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == actual
    component = read(HERE / 'component/final/report.json')
    assert component['status'] == 'PASS' and component['returncode'] == 0
    assert component['source_unchanged_during_test'] and component['source_sha256'] == SOURCE
    assert len(component['tested_files']) == 493 and len(component['criteria']) == 6
    cases = {(case['class'], case['name']) for criterion in component['criteria']
             for node in criterion['evidence'] for case in node['cases']}
    assert len(cases) == 432 and all(row['status'] == 'PASS' for row in component['criteria'])
    full = read(HERE / 'full/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test'] and before == after
    assert before['revision'] == FROZEN and before['worktree_status'] == ''
    assert before['source_sha256'] == SOURCE and before['source_file_count'] == 493
    assert component['tested_files'] == before['files']
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 489 and set(old['files']) <= before['files'].keys()
    changed = {p for p, digest in old['files'].items() if before['files'][p] != digest}
    assert changed == {'scar/ir/execution/query.py'}
    assert before['fixture_sha256'] == old['fixture_sha256'] and len(before['fixture_sha256']) == 50
    old_cases, new_cases = (read(path / 'full/cases.json') for path in (PREVIOUS, HERE))
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in cases} for cases in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4387 and old_set <= new_set
    assert len(new_set) == len(new_cases) == 4427 and len(new_set - old_set) == 40
    assert all(cls in ('tests.unit.test_execution_coverage',
        'tests.unit.test_execution_materialization_coverage') for cls, _ in new_set - old_set)
    assert full['counts'] == {'passed': 4427, 'failed': 0, 'error': 0, 'skipped': 0, 'total': 4427}
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    for name, value in read(HERE / 'full/manifest.json')['files'].items():
        assert actual['full/' + name] == value
    witness = read(HERE / 'witnesses/attempt001/result.json')
    assert witness['status'] == 'PASS' and witness['passed'] == witness['total'] == 3
    assert all(row['status'] == 'PASS' for row in witness['witnesses'])
    assert actual['witnesses/attempt001/witnesses.py']['sha256'] == (
        '542a80628e5c1046a06e23970bbd387f5f7f00a0e95a8a873510330e887f56da')
    assert actual['review/final-closure.md']['sha256'] == (
        '375c7973b2d1bc07e5010705bed0238290068af23cd216c15559135ab25ef3ac')
    assert actual['design/contract-consumer-closure.md']['sha256'] == (
        '603f81808a32dafd65e858f16c84b934fb96e57303b15d5904a3ef84082e44d9')
    assert read(HERE / 'protected.before.json') == read(HERE / 'protected.after.json')
    assert all(not row['status'] for row in read(HERE / 'protected.after.json').values())
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == SOURCE and files == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(actual),
        'component_cases': 432, 'criteria': 6, 'full_cases': 4427,
        'preserved_previous_cases': 4387, 'new_cases': 40,
        'source_files': 493, 'fixtures': 50, 'real_cpu_os_witnesses': 3,
        'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

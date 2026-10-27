"""Check archived receipts and hashes only; never start tests or providers."""
from pathlib import Path
import hashlib
import json
import runpy

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / 'model_lifecycle_composition'
FROZEN = '6fcac0f778d56d7fe4fdb90e546b23e545f86f96'
SOURCE = '131fa88c62901a016b88778ea975b3a63a6e59497d49740968bd3d49df190e3b'


def read(path):
    return json.loads(path.read_text())


def main():
    manifest = read(HERE / 'manifest.json')
    actual = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}
    assert manifest['files'] == actual, 'archive files differ from root manifest'
    component = read(HERE / 'component/report.json')
    assert component['status'] == 'PASS' and component['returncode'] == 0
    assert component['source_unchanged_during_test'] is True
    assert component['source_sha256'] == SOURCE
    assert len(component['tested_files']) == 472 and len(component['criteria']) == 14
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    full = read(HERE / 'full/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test'] is True
    for receipt in (before, after):
        assert receipt['revision'] == FROZEN and receipt['worktree_status'] == ''
        assert receipt['source_sha256'] == SOURCE and receipt['source_file_count'] == 472
    assert before == after, 'frozen run changed HEAD, source or fixture hashes'
    assert component['tested_files'] == before['files']
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 451 and len(old['fixture_sha256']) == 42
    assert all(before['files'][path] == digest for path, digest in old['files'].items())
    assert all(before['fixture_sha256'][path] == digest for path, digest in old['fixture_sha256'].items())
    assert len(before['fixture_sha256']) == 44
    old_cases = read(PREVIOUS / 'full/cases.json')
    new_cases = read(HERE / 'full/cases.json')
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in cases} for cases in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4050
    assert old_set <= new_set, 'an accepted test identity disappeared'
    assert all('.test_execution_' in cls for cls, _ in new_set - old_set)
    assert len(new_set - old_set) == 142 and len(new_cases) == len(new_set) == 4192
    assert full['counts'] == {'passed': 4192, 'failed': 0, 'error': 0, 'skipped': 0, 'total': 4192}
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination', 'owned test directory was not removed'
    driver = HERE / 'full/driver.py'
    assert hashlib.sha256(driver.read_bytes()).hexdigest() == '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28'
    nested = read(HERE / 'full/manifest.json')['files']
    assert all(actual['full/' + name] == value for name, value in nested.items())
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == SOURCE and files == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(actual),
        'component_cases': 302, 'component_criteria': 14,
        'full_cases': 4192, 'preserved_previous_cases': 4050,
        'new_execution_cases': 142, 'source_files': 472,
        'fixtures': 44, 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

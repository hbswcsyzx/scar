"""Read archived R2.1 receipts only. Starts no tests, providers or workloads."""
from pathlib import Path
import hashlib
import json
import runpy

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
PREVIOUS = HERE.parent / 'model_resource_identity'
FROZEN = 'bb1b402b498e9ce80a701658a59c1471e8ec32ce'
SOURCE = 'f26bb51ad783f85c43de3a8d75999d9943f915973c629411c0b27b264d57487c'
CHANGED = {'scar/ir/execution/codec.py', 'scar/ir/execution/ids.py', 'scar/ir/execution/model.py',
           'scar/ir/execution/query.py', 'scar/ir/execution/validation.py', 'tests/unit/test_execution_codec.py'}


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
    assert len(component['tested_files']) == 480 and len(component['criteria']) == 9
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    full = read(HERE / 'full/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test']
    assert before == after
    assert before['revision'] == FROZEN and before['worktree_status'] == ''
    assert before['source_sha256'] == SOURCE and before['source_file_count'] == 480
    assert component['tested_files'] == before['files']
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 472 and set(old['files']) <= before['files'].keys()
    changed = {path for path, digest in old['files'].items() if before['files'][path] != digest}
    assert changed == CHANGED
    assert len(old['fixture_sha256']) == 44 and len(before['fixture_sha256']) == 47
    assert all(before['fixture_sha256'][path] == digest for path, digest in old['fixture_sha256'].items())
    old_cases, new_cases = read(PREVIOUS / 'full/cases.json'), read(HERE / 'full/cases.json')
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in cases} for cases in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4192 and old_set <= new_set
    assert len(new_set - old_set) == 105 and all('.test_execution_work_' in cls for cls, _ in new_set - old_set)
    assert len(new_set) == len(new_cases) == 4297
    assert full['counts'] == {'passed': 4297, 'failed': 0, 'error': 0, 'skipped': 0, 'total': 4297}
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28'
    for name, value in read(HERE / 'full/manifest.json')['files'].items():
        assert actual['full/' + name] == value
    proof = read(ROOT / 'tests/fixtures/execution_v1_frozen.proof.json')
    golden = (ROOT / 'tests/fixtures/execution_v1_frozen.json').read_bytes()
    assert proof['source_revision'] == '6fcac0f778d56d7fe4fdb90e546b23e545f86f96'
    assert len(golden) == proof['payload_size_bytes'] == 88521
    assert hashlib.sha256(golden).hexdigest() == proof['payload_sha256'] == '66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391'
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == SOURCE and files == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(actual), 'component_cases': 407,
        'criteria': 9, 'full_cases': 4297, 'preserved_previous_cases': 4192,
        'new_work_cases': 105, 'source_files': 480, 'changed_prior_sources': sorted(CHANGED),
        'fixtures': 47, 'historical_v1_bytes': len(golden), 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

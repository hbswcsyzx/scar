"""Read archived R2.2 evidence only; start no tests, providers or workloads."""
from pathlib import Path
import hashlib
import json
import runpy

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
PREVIOUS = HERE.parent / 'model_resource_work'
FROZEN = 'e8121f077c93286e7903e54aeb1729e250bfcb44'
SOURCE = '10e12c818eb8c8adaeb3a4e0e4cf4dd4927137f568da590b02f648e013c4a3e5'
CHANGED = {'scar/ir/execution/codec.py', 'scar/ir/execution/ids.py',
           'scar/ir/execution/model.py', 'scar/ir/execution/query.py',
           'scar/ir/execution/validation.py', 'tests/unit/test_execution_codec.py',
           'tests/unit/test_execution_work_codec.py'}


def read(path):
    return json.loads(path.read_text())


def main():
    actual = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size,
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
              for path in sorted(HERE.rglob('*'))
              if path.is_file() and path != HERE / 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == actual
    component = read(HERE / 'component/final/report.json')
    assert component['status'] == 'PASS' and component['returncode'] == 0
    assert component['source_unchanged_during_test'] and component['source_sha256'] == SOURCE
    assert len(component['tested_files']) == 489 and len(component['criteria']) == 7
    cases = {(case['class'], case['name']) for criterion in component['criteria']
             for node in criterion['evidence'] for case in node['cases']}
    assert len(cases) == 497 and all(row['status'] == 'PASS' for row in component['criteria'])
    full = read(HERE / 'full/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test'] and before == after
    assert before['revision'] == FROZEN and before['worktree_status'] == ''
    assert before['source_sha256'] == SOURCE and before['source_file_count'] == 489
    assert component['tested_files'] == before['files']
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 480 and set(old['files']) <= before['files'].keys()
    changed = {p for p, digest in old['files'].items() if before['files'][p] != digest}
    assert changed == CHANGED
    assert len(old['fixture_sha256']) == 47 and len(before['fixture_sha256']) == 50
    assert all(before['fixture_sha256'][p] == digest for p, digest in old['fixture_sha256'].items())
    old_cases, new_cases = (read(path / 'full/cases.json') for path in (PREVIOUS, HERE))
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in cases} for cases in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4297 and old_set <= new_set
    assert len(new_set) == len(new_cases) == 4387 and len(new_set - old_set) == 90
    assert all('.test_execution_order_' in cls or (
        cls == 'tests.unit.test_execution_work_codec'
        and name == 'test_schema_versions_are_exact_supported_integers[4]')
        for cls, name in new_set - old_set)
    assert full['counts'] == {'passed': 4387, 'failed': 0, 'error': 0, 'skipped': 0, 'total': 4387}
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    for name, value in read(HERE / 'full/manifest.json')['files'].items():
        assert actual['full/' + name] == value
    for version, revision, size, digest in (
        (1, '6fcac0f778d56d7fe4fdb90e546b23e545f86f96', 88521,
         '66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391'),
        (2, 'bb1b402b498e9ce80a701658a59c1471e8ec32ce', 56435,
         'b03a304a582a662d71ebdbe4685776aef9ec4fc357142f0fa2e6656cdae03234')):
        proof = read(ROOT / f'tests/fixtures/execution_v{version}_frozen.proof.json')
        payload = (ROOT / f'tests/fixtures/execution_v{version}_frozen.json').read_bytes()
        assert proof['source_revision'] == revision and proof['payload_size_bytes'] == len(payload) == size
        assert hashlib.sha256(payload).hexdigest() == proof['payload_sha256'] == digest
    assert actual['review/composition.md']['sha256'] == '75d2d9466a3cd771c9e4d84180785c804f6fb715a49075e9ce41a60b02464de0'
    assert actual['review/final-closure.md']['sha256'] == '298b3062e961607e0bc65ee145efd29ed180a89d202c767a0451c007674c2600'
    assert read(HERE / 'protected.before.json') == read(HERE / 'protected.after.json')
    assert all(not row['status'] for row in read(HERE / 'protected.after.json').values())
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == SOURCE and files == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(actual), 'component_cases': 497,
        'criteria': 7, 'full_cases': 4387, 'preserved_previous_cases': 4297,
        'new_cases': 90, 'source_files': 489, 'fixtures': 50,
        'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

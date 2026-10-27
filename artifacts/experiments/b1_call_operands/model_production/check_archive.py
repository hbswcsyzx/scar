"""Read P evidence only; start no tests, provider or workload."""
from pathlib import Path
import hashlib
import json
import runpy
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'model_content'


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
    assert component['source_unchanged_during_test'] and len(component['criteria']) == 8
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    cases = {(case['class'], case['name']) for criterion in component['criteria']
             for node in criterion['evidence'] for case in node['cases']}
    assert len(cases) == closure['component_cases'] == 477
    assert full['status'] == 'PASS' and full['returncode'] == 0 and not full['driver_errors']
    assert full['source_unchanged_during_test'] and before == after
    assert before['revision'] == closure['implementation_revision'] and before['worktree_status'] == ''
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert before['files'] == component['tested_files'] and len(before['files']) == closure['source_files']
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for path, expected in read(HERE / 'full/manifest.json')['files'].items():
        assert actual['full/' + path] == expected
    old = read(PREVIOUS / 'full/source.before.json')
    assert len(old['files']) == 506 and set(old['files']) <= before['files'].keys()
    assert len(old['fixture_sha256']) == 54
    assert all(before['fixture_sha256'].get(p) == h for p, h in old['fixture_sha256'].items())
    old_cases, new_cases = (read(path / 'full/cases.json') for path in (PREVIOUS, HERE))
    identity = lambda row: (row['class'], row['name'])
    old_set, new_set = ({identity(row) for row in rows} for rows in (old_cases, new_cases))
    assert len(old_set) == len(old_cases) == 4568 and old_set <= new_set
    assert len(new_set) == len(new_cases) == closure['full_cases']
    assert full['counts'] == {'passed':len(new_set), 'failed':0, 'error':0, 'skipped':0, 'total':len(new_set)}
    preservation = read(HERE / 'preservation.json')
    assert preservation['preserved_previous_cases'] == 4568
    assert preservation['missing_cases'] == [] and preservation['changed_previous_fixtures'] == []
    assert read(HERE / 'protected.before.json') == read(HERE / 'protected.after.json')
    assert all(not row['status'] for row in read(HERE / 'protected.after.json').values())
    payload = (ROOT / 'tests/fixtures/execution_v4_frozen.json').read_bytes()
    proof = read(ROOT / 'tests/fixtures/execution_v4_frozen.json.proof.json')
    assert hashlib.sha256(payload).hexdigest() == '55ed3e05850fbcb30c44c1894feb81062fc8aaba6976b8d4b0048d44da4735af'
    assert len(payload) == 29951 and proof['payload_size_bytes'] == 29951
    assert proof['codec_schema_version'] == proof['wire_schema_version'] == 4
    assert proof['source_revision'] == '5ab22f8d8fcbabbc59d494b571651d480468f3d5'
    witness = next(case for case in ET.parse(HERE / 'full/results.xml').iter('testcase')
        if case.get('name') == 'test_real_native_write_then_wrapper_raise_keeps_actual_request_distinct_from_desired_output')
    properties = {item.get('name'):item.get('value') for item in witness.iter('property')}
    assert properties == {'desired_output_bytes':'8', 'native_requested_bytes':'4',
        'native_returned_bytes':'4', 'actual_file_hex':'616263642e2e2e2e',
        'host_completion':'RAISE', 'native_outcome':'COMPLETED'}
    for path, digest in closure['documents'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    current, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current == closure['source_sha256'] and files == before['files']
    print(json.dumps({'status':'PASS','archived_files':len(actual),'criteria':8,
        'component_cases':len(cases),'full_cases':len(new_set),'preserved_previous_cases':len(old_set),
        'source_files':len(files),'fixtures':len(before['fixture_sha256']),'tests_started_by_checker':0}))


if __name__ == '__main__':
    main()

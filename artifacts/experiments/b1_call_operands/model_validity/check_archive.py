"""Check V evidence read-only: start no tests, provider, profiler or workload."""
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'model_production'


def read(path):
    return json.loads(path.read_text())


def main():
    files = {str(path.relative_to(HERE)):{'bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE/'manifest.json'}
    assert read(HERE/'manifest.json')['files'] == files
    closure = read(HERE/'closure.json')
    component, full = (read(HERE/path) for path in ('component/final/report.json','full/report.json'))
    before, after = (read(HERE/f'full/source.{phase}.json') for phase in ('before','after'))
    assert component['status'] == full['status'] == 'PASS'
    assert component['returncode'] == full['returncode'] == 0
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    assert before == after and not before['worktree_status']
    assert before['revision'] == closure['implementation_revision']
    assert before['files'] == component['tested_files']
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert len(before['files']) == closure['source_files']
    assert len(component['criteria']) == closure['criteria'] == 11
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    component_cases = {(case['class'],case['name']) for criterion in component['criteria']
                       for node in criterion['evidence'] for case in node['cases']}
    assert len(component_cases) == closure['component_cases']
    assert hashlib.sha256((HERE/'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert not full['driver_errors']
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for path, expected in read(HERE/'full/manifest.json')['files'].items():
        assert files['full/'+path] == expected
    prior = read(PREVIOUS/'full/source.before.json')
    assert len(prior['files']) == 521 and set(prior['files']) <= before['files'].keys()
    assert len(prior['fixture_sha256']) == 59
    assert all(before['fixture_sha256'].get(p) == h for p,h in prior['fixture_sha256'].items())
    old_cases, current_cases = (read(base/'full/cases.json') for base in (PREVIOUS,HERE))
    identity = lambda row:(row['class'],row['name'])
    old_set,current_set = ({identity(row) for row in rows} for rows in (old_cases,current_cases))
    assert len(old_set) == len(old_cases) == 4713 and old_set <= current_set
    assert len(current_set) == len(current_cases) == closure['full_cases']
    assert full['counts'] == {'passed':len(current_set),'failed':0,'error':0,'skipped':0,'total':len(current_set)}
    preservation = read(HERE/'preservation.json')
    assert preservation['preserved_previous_cases'] == 4713
    assert preservation['missing_cases'] == preservation['removed_source_files'] == preservation['changed_previous_fixtures'] == []
    prior_protected = read(HERE/'protected.before.json')
    after_protected = read(HERE/'protected.after.json')
    assert all(prior_protected[k] == row and not row['status'] for k,row in after_protected.items())
    payload = (ROOT/'tests/fixtures/execution_v5_frozen.json').read_bytes()
    proof = read(ROOT/'tests/fixtures/execution_v5_frozen.json.proof.json')
    assert len(payload) == proof['payload_bytes'] == 64321
    assert hashlib.sha256(payload).hexdigest() == proof['payload_sha256'] == (
        '3b6b736632012e17620c4f6233c8520f70db527d1391df67d7f3ef5cc2bef708')
    assert proof['revision'] == 'f2b4672d9555348dcd05da62a8cd126711ef22f9'
    assert proof['codec_sha256'] == '981ce8adbae591a9fea25534d9987923c901db8a2fb4861e20a52b5755057dc7'
    witness = read(HERE/'os_witness/attempt002/report.json')
    assert witness['returncode'] == 0
    observed = next(json.loads(line) for line in (HERE/'os_witness/attempt002/stdout.log').read_text().splitlines()
                    if line.startswith('{"limitation":'))
    assert 0 < observed['observed']['returned_bytes'] < observed['observed']['requested_bytes']
    assert observed['observed']['returned_bytes'] == observed['observed']['received_bytes']
    assert observed['verified_model_guard']['known_coverage'] == 'INCOMPLETE'
    for path,digest in closure['documents'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest
    fingerprint, current_files = runpy.run_path(str(ROOT/'scripts/run_gate.py'))['fingerprint']()
    assert fingerprint == closure['source_sha256'] and current_files == before['files']
    print(json.dumps({'status':'PASS','archived_files':len(files),'criteria':closure['criteria'],
        'component_cases':len(component_cases),'full_cases':len(current_set),
        'preserved_previous_cases':len(old_set),'source_files':len(current_files),
        'fixtures':len(before['fixture_sha256']),'tests_started_by_checker':0}))


if __name__ == '__main__':
    main()

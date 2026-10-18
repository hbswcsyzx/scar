"""Archive/check a completed P3 gate; never starts tests or edits old evidence."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_generator_matrix'
DRIVER_SHA = '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    assert not path.exists(), f'Never overwrite archive evidence: {path}'
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def files():
    return {str(path.relative_to(HERE)): {'bytes': path.stat().st_size, 'sha256': digest(path)}
            for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}


def protected():
    result = {}
    for name, row in read(HERE / 'protected.before.json').items():
        result[name] = {'path': row['path'],
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip(),
            'status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip()}
    return result


def case_ids(rows):
    return {(row['class'], row['name']) for row in rows}


def assemble():
    full = read(HERE / 'full/report.json')
    component = read(HERE / 'component/attempt003/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == component['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    previous = read(PRIOR / 'repair/full/source.before.json')
    old_cases = read(PRIOR / 'repair/full/cases.json')
    cases = read(HERE / 'full/cases.json')
    component_cases = {tuple((row['class'], row['name'])) for criterion in component['criteria']
                       for evidence in criterion['evidence'] for row in evidence['cases']}
    missing = sorted(case_ids(old_cases) - case_ids(cases))
    removed = sorted(previous['files'].keys() - before['files'].keys())
    changed = sorted(path for path, sha in previous['fixture_sha256'].items()
                     if before['fixture_sha256'].get(path) != sha)
    assert not missing and not removed and not changed
    dump(HERE / 'preservation.json', {'preserved_previous_cases': len(old_cases),
        'missing_cases': missing, 'removed_source_files': removed, 'changed_previous_fixtures': changed,
        'previous_fixtures': len(previous['fixture_sha256']), 'current_fixtures': len(before['fixture_sha256'])})
    current = protected()
    assert current == read(HERE / 'protected.before.json')
    dump(HERE / 'protected.after.json', current)
    docs = ('M1_BODY_OCCURRENCE_PLAN', 'M1_BODY_OCCURRENCE_API', 'M1_BODY_OCCURRENCE_PROGRESS',
            'M1_BODY_OCCURRENCE_ACCEPTANCE', 'M1_PROTOCOL_CONTRACT', 'M1_PROTOCOL_FAMILY_PLAN',
            'STATUS', 'ROADMAP', 'WHOLE_PROGRAM_MODEL_PLAN', 'FIRST_STAGE_COMPLETION_MATRIX',
            'MODELING_REUSE_DECISION')
    dump(HERE / 'closure.json', {'status': 'PASS_WITH_SCOPE_P3_BODY_OCCURRENCE',
        'implementation_revision': before['revision'], 'source_sha256': before['source_sha256'],
        'source_files': before['source_file_count'], 'criteria': len(component['criteria']),
        'component_cases': len(component_cases), 'focused_cases': 166, 'full_cases': len(cases),
        'previous_cases': len(old_cases), 'p3_declared_occurrence_complete': True,
        'd3_complete': False, 'm0_m2_complete': False, 'scope_inventory_complete': False,
        'source_runtime_verified': False, 'value_identity_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup_measurement': False,
        'documents': {f'docs/{name}.md': digest(ROOT / f'docs/{name}.md') for name in docs},
        'tests_started_by_archiver': 0})
    dump(HERE / 'manifest.json', {'schema': 'scar.body-occurrence-archive', 'schema_version': 1, 'files': files()})


def check():
    listing = files()
    assert listing == read(HERE / 'manifest.json')['files']
    closure = read(HERE / 'closure.json')
    full, component = read(HERE / 'full/report.json'), read(HERE / 'component/attempt003/report.json')
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert full['status'] == component['status'] == 'PASS'
    assert full['returncode'] == component['returncode'] == 0
    assert full['source_unchanged_during_test'] and component['source_unchanged_during_test']
    assert before == after and not before['worktree_status']
    assert before['revision'] == closure['implementation_revision']
    subprocess.run(['git', 'merge-base', '--is-ancestor', before['revision'], 'HEAD'], cwd=ROOT, check=True)
    assert before['files'] == component['tested_files']
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert len(before['files']) == closure['source_files'] == 668
    assert len(component['criteria']) == closure['criteria'] == 18
    assert [row['id'].split('-')[0] for row in component['criteria'][:16]] == [f'O{number:02}' for number in range(1, 17)]
    assert all(row['status'] == 'PASS' for row in component['criteria'])
    component_cases = {(row['class'], row['name']) for criterion in component['criteria']
                       for evidence in criterion['evidence'] for row in evidence['cases']}
    assert len(component_cases) == closure['component_cases']
    assert digest(HERE / 'full/driver.py') == DRIVER_SHA
    assert not full['driver_errors']
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for path, row in read(HERE / 'full/manifest.json')['files'].items():
        assert listing['full/' + path] == row
    previous = read(PRIOR / 'repair/full/source.before.json')
    assert len(previous['files']) == 647 and previous['files'].keys() <= before['files'].keys()
    assert len(previous['fixture_sha256']) == 92
    assert all(before['fixture_sha256'].get(path) == sha for path, sha in previous['fixture_sha256'].items())
    current_fixtures = {str(path.relative_to(ROOT)): digest(path)
        for path in sorted((ROOT / 'tests/fixtures').rglob('*')) if path.is_file() and '__pycache__' not in path.parts}
    assert current_fixtures == before['fixture_sha256'] and len(current_fixtures) == 99
    old, cases = read(PRIOR / 'repair/full/cases.json'), read(HERE / 'full/cases.json')
    assert len(case_ids(old)) == len(old) == closure['previous_cases'] == 5676
    assert len(case_ids(cases)) == len(cases) == closure['full_cases'] == 5822
    assert case_ids(old) <= case_ids(cases) and component_cases <= case_ids(cases)
    assert full['counts'] == {'passed': 5822, 'failed': 0, 'error': 0, 'skipped': 0, 'total': 5822}
    conservation = read(HERE / 'preservation.json')
    assert conservation['missing_cases'] == conservation['removed_source_files'] == conservation['changed_previous_fixtures'] == []
    assert protected() == read(HERE / 'protected.after.json') == read(HERE / 'protected.before.json')
    assert closure['status'] == 'PASS_WITH_SCOPE_P3_BODY_OCCURRENCE' and closure['p3_declared_occurrence_complete']
    assert not any(closure[name] for name in ('d3_complete', 'm0_m2_complete', 'scope_inventory_complete',
        'source_runtime_verified', 'value_identity_verified', 'transformation_authorized', 'new_lewm_speedup_measurement'))
    for path, sha in closure['documents'].items():
        assert digest(ROOT / path) == sha
    assert digest(ROOT / 'docs/M1_PROTOCOL_CONTRACT.md') == '2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac'
    sha, current = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert sha == closure['source_sha256'] and current == before['files']
    focused_dir = HERE / 'final-focused/attempt005'
    focused = read(focused_dir / 'result.json')
    assert focused['returncode'] == 0 and focused['source_unchanged']
    assert read(focused_dir / 'sources.before.json') == read(focused_dir / 'sources.after.json') == current
    assert len(list(ET.parse(focused_dir / 'junit.xml').iter('testcase'))) == closure['focused_cases'] == 166
    assert read(HERE / 'port-review/red001/result.json')['returncode'] == 1
    assert read(HERE / 'port-review/unassociated-create/red001/result.json')['returncode'] == 1
    assert read(HERE / 'legacy-version/red001/result.json')['returncode'] == 1
    assert read(HERE / 'component/attempt001/report.json')['status'] == 'FAIL'
    print(json.dumps({'status': 'PASS', 'scope': closure['status'], 'archived_files': len(listing),
        'source_files': len(current), 'fixtures': len(current_fixtures), 'criteria': 18,
        'focused_cases': 166, 'component_cases': len(component_cases), 'full_cases': len(cases),
        'preserved_previous_cases': len(old), 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--assemble']:
        assemble()
    elif sys.argv[1:] == ['--check']:
        check()
    else:
        raise SystemExit('use --assemble once after PASS, or --check for read-only verification')

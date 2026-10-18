"""Archive the completed P2 repair; never starts a test or edits prior evidence."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_protocol_implementation'


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    assert not path.exists(), f'Archive target already exists: {path}'
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(case):
    return case['class'], case['name']


def main():
    component_path, full_path = 'repair/component/attempt001', 'repair/full'
    focused_path = 'repair/final-focused/attempt001'
    component = read(HERE / component_path / 'report.json')
    full = read(HERE / full_path / 'report.json')
    before, after = (read(HERE / full_path / f'source.{phase}.json')
                     for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert component['returncode'] == full['returncode'] == 0
    assert before == after and not before['worktree_status']
    assert before['revision'] == 'bd673cd81938d7b8af2692645685123e85cc6965'
    assert before['source_file_count'] == 647
    current_sha, current_files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert current_sha == before['source_sha256'] == component['source_sha256']
    assert current_files == before['files'] == component['tested_files']
    assert digest(ROOT / 'docs/M1_PROTOCOL_CONTRACT.md') == (
        '2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac')

    old_source = read(PRIOR / 'full/source.before.json')
    initial_source = read(HERE / 'full/source.before.json')
    cases = read(HERE / full_path / 'cases.json')
    old_cases = read(PRIOR / 'full/cases.json')
    initial_cases = read(HERE / 'full/cases.json')
    old_set, initial_set, current_set = ({identity(row) for row in rows}
                                       for rows in (old_cases, initial_cases, cases))
    assert len(current_set) == len(cases) == 5676
    assert len(old_set) == 5401 and len(initial_set) == 5673
    missing = sorted((old_set | initial_set) - current_set)
    removed = sorted((old_source['files'].keys() | initial_source['files'].keys()) - current_files.keys())
    changed = sorted(path for path, sha in old_source['fixture_sha256'].items()
                     if before['fixture_sha256'].get(path) != sha)
    assert not missing and not removed and not changed
    assert before['fixture_sha256'] == initial_source['fixture_sha256']
    assert len(before['fixture_sha256']) == 92
    assert all(row['outcome'] == 'passed' for row in cases)
    component_cases = {identity(case) for criterion in component['criteria']
                       for row in criterion['evidence'] for case in row['cases']}
    assert len(component_cases) == 660 and component_cases <= current_set
    assert len(component['criteria']) == 37
    focused_cases = list(ET.parse(HERE / focused_path / 'junit.xml').iter('testcase'))
    assert len(focused_cases) == 275 and all(not list(row) for row in focused_cases)

    protected = {}
    for name, row in read(HERE / 'protected.before.json').items():
        protected[name] = {
            'path': row['path'],
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip(),
            'status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip(),
        }
    assert protected == read(HERE / 'protected.before.json')
    dump(HERE / 'protected.after.json', protected)
    dump(HERE / 'preservation.json', {
        'preserved_previous_cases': len(old_set),
        'preserved_initial_full_cases': len(initial_set),
        'missing_cases': missing, 'removed_source_files': removed,
        'changed_previous_fixtures': changed, 'previous_fixtures': 82,
        'initial_full_fixtures': 92, 'current_fixtures': 92,
        'initial_full_status': 'FAIL', 'final_full_status': 'PASS',
    })
    documents = (
        'docs/M1_GENERATOR_MATRIX_PLAN.md', 'docs/M1_GENERATOR_MATRIX_PROGRESS.md',
        'docs/M1_GENERATOR_MATRIX_REPAIR.md', 'docs/M1_GENERATOR_MATRIX_ACCEPTANCE.md',
        'docs/M1_ADMISSION_PREDICATE_CONTRACT.md', 'docs/M1_INVOKE_COMPLETION_AMENDMENT.md',
        'docs/M1_PROTOCOL_CONTRACT.md', 'docs/M1_PROTOCOL_FAMILY_PLAN.md',
        'docs/STATUS.md', 'docs/ROADMAP.md', 'docs/WHOLE_PROGRAM_MODEL_PLAN.md',
        'docs/FIRST_STAGE_COMPLETION_MATRIX.md', 'docs/MODELING_REUSE_DECISION.md',
    )
    dump(HERE / 'closure.json', {
        'status': 'PASS_WITH_SCOPE_P2_DECLARED_MATRIX',
        'implementation_revision': before['revision'],
        'initial_failed_revision': initial_source['revision'],
        'source_sha256': current_sha, 'source_files': len(current_files),
        'criteria': 37, 'component_cases': 660, 'focused_cases': 275, 'full_cases': len(cases),
        'component': component_path, 'full': full_path, 'final_focused': focused_path,
        'p2_declared_matrix_complete': True,
        'd3_complete': False, 'm0_m2_complete': False, 'scope_inventory_complete': False,
        'source_runtime_verified': False, 'value_identity_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup_measurement': False,
        'documents': {path: digest(ROOT / path) for path in documents},
        'tests_started_by_archiver': 0,
    })
    files = {str(path.relative_to(HERE)): {'bytes': path.stat().st_size, 'sha256': digest(path)}
             for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE / 'manifest.json'}
    dump(HERE / 'manifest.json', {'schema': 'scar.generator-matrix-archive',
                                'schema_version': 1, 'files': files})
    print(json.dumps({'status': 'ARCHIVED', 'files': len(files), 'tests_started': 0}))


if __name__ == '__main__':
    main()

"""Seal completed V evidence without starting a test, provider or workload."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'model_production'


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    component, full = (read(HERE / path) for path in ('component/final/report.json', 'full/report.json'))
    assert component['status'] == full['status'] == 'PASS'
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert before == after and not before['worktree_status']
    assert before['files'] == component['tested_files']
    old = read(PREVIOUS / 'full/source.before.json')
    old_cases, cases = (read(base / 'full/cases.json') for base in (PREVIOUS, HERE))
    identity = lambda case: (case['class'], case['name'])
    old_set, current_set = ({identity(row) for row in rows} for rows in (old_cases, cases))
    added = [row for row in cases if identity(row) not in old_set]
    preservation = {'preserved_previous_cases': len(old_set & current_set),
        'missing_cases': sorted(old_set - current_set), 'new_cases': added,
        'new_cases_by_class': dict(sorted(Counter(row['class'] for row in added).items())),
        'previous_source_files': len(old['files']),
        'new_source_files': sorted(set(before['files']) - set(old['files'])),
        'removed_source_files': sorted(set(old['files']) - set(before['files'])),
        'changed_previous_source_files': [p for p,h in old['files'].items() if before['files'].get(p) != h],
        'unchanged_previous_source_files': sum(before['files'].get(p) == h for p,h in old['files'].items()),
        'previous_fixtures': len(old['fixture_sha256']), 'current_fixtures': len(before['fixture_sha256']),
        'changed_previous_fixtures': [p for p,h in old['fixture_sha256'].items() if before['fixture_sha256'].get(p) != h],
        'current_fixtures_unchanged': before['fixture_sha256'] == after['fixture_sha256']}
    assert not preservation['missing_cases'] and not preservation['changed_previous_fixtures']
    assert not preservation['removed_source_files']
    dump(HERE / 'preservation.json', preservation)
    protected = {}
    for label, path in [('lewm','/home/zyf/AAA/le-wm'), ('scar_main','/home/zyf/AAA/scar')]:
        protected[label] = {'path': path, 'revision':subprocess.check_output(
            ['git','rev-parse','HEAD'], cwd=path, text=True).strip(), 'status':subprocess.check_output(
            ['git','status','--porcelain=v1'], cwd=path, text=True)}
    dump(HERE / 'protected.after.json', protected)
    prior = read(HERE / 'protected.before.json')
    assert all(protected[key] == prior[key] and not protected[key]['status'] for key in protected)
    component_cases = {(row['class'],row['name']) for criterion in component['criteria']
                       for node in criterion['evidence'] for row in node['cases']}
    documents = ['README.md','docs/STATUS.md','docs/ROADMAP.md','docs/FIRST_STAGE_COMPLETION_MATRIX.md',
        'docs/WHOLE_PROGRAM_MODEL_PLAN.md','docs/M1_VALIDITY_PLAN.md','docs/M1_VALIDITY_API.md',
        'docs/M1_VALIDITY_ACCEPTANCE.md']
    dump(HERE / 'closure.json', {'scope':'V declared content validity/support interfaces; endpoint protocol parsing, native capture, R3 and full M0-M2 remain open',
        'implementation_revision': before['revision'], 'source_sha256': before['source_sha256'],
        'source_files':len(before['files']), 'component_cases':len(component_cases),
        'criteria':len(component['criteria']), 'full_cases':len(cases),
        'component_seconds':component['duration_seconds'], 'full_seconds':full['duration_seconds'],
        'source_runtime_verified':False,'runtime_visibility_verified':False,'transformation_authorized':False,
        'documents':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in documents}})
    files = {str(path.relative_to(HERE)):{'bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(HERE.rglob('*')) if path.is_file() and path != HERE/'manifest.json'}
    dump(HERE/'manifest.json', {'schema':'scar.content-validity-interface-archive','schema_version':1,'files':files})
    print(json.dumps({'archived_files':len(files),'component_cases':len(component_cases),
        'full_cases':len(cases),'preserved_previous_cases':len(old_set & current_set),
        'source_files':len(before['files']),'fixtures':len(before['fixture_sha256'])}))


if __name__ == '__main__':
    main()

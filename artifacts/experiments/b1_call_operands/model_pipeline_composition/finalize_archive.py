"""Archive R3.2 evidence; starts zero tests, workloads or profilers."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_resource_composition'


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    component, full = (read(HERE / p) for p in ('component/final/report.json', 'full/report.json'))
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    assert before['files'] == component['tested_files']
    previous = read(PRIOR / 'full/source.before.json')
    old_cases, cases = (read(base / 'full/cases.json') for base in (PRIOR, HERE))
    identity = lambda case: (case['class'], case['name'])
    old_set, case_set = ({identity(case) for case in rows} for rows in (old_cases, cases))
    assert len(old_cases) == len(old_set) == 4951 and old_set <= case_set
    missing_sources = sorted(set(previous['files']) - set(before['files']))
    changed_fixtures = [p for p, sha in previous['fixture_sha256'].items()
                        if before['fixture_sha256'].get(p) != sha]
    assert not missing_sources and not changed_fixtures
    dump(HERE / 'preservation.json', {
        'previous_cases': len(old_set), 'preserved_previous_cases': len(old_set & case_set),
        'missing_cases': sorted(old_set - case_set), 'new_cases': sorted(case_set - old_set),
        'previous_source_files': len(previous['files']), 'current_source_files': len(before['files']),
        'removed_source_files': missing_sources,
        'unchanged_previous_source_files': sum(before['files'][p] == sha for p, sha in previous['files'].items()),
        'extended_previous_source_files': sorted(p for p, sha in previous['files'].items() if before['files'][p] != sha),
        'new_source_files': sorted(set(before['files']) - set(previous['files'])),
        'previous_fixtures': len(previous['fixture_sha256']), 'current_fixtures': len(before['fixture_sha256']),
        'changed_previous_fixtures': changed_fixtures,
    })
    documents = ['README.md', 'docs/STATUS.md', 'docs/ROADMAP.md',
        'docs/FIRST_STAGE_COMPLETION_MATRIX.md', 'docs/WHOLE_PROGRAM_MODEL_PLAN.md',
        'docs/M1_RESOURCE_COMPOSITION_PLAN.md', 'docs/M1_PIPELINE_COMPOSITION_PLAN.md',
        'docs/M1_PIPELINE_COMPOSITION_API.md', 'docs/M1_PIPELINE_COMPOSITION_ACCEPTANCE.md']
    component_cases = {(case['class'], case['name']) for criterion in component['criteria']
                       for item in criterion['evidence'] for case in item['cases']}
    dump(HERE / 'closure.json', {
        'scope': 'R3.2 supplied-model composition under explicit Q scopes; R3.3 and full M0-M2 remain open',
        'implementation_revision': before['revision'], 'source_sha256': before['source_sha256'],
        'source_files': len(before['files']), 'criteria': len(component['criteria']),
        'component_cases': len(component_cases), 'full_cases': len(cases),
        'component_seconds': component['duration_seconds'], 'full_seconds': full['duration_seconds'],
        'scope_inventory_complete': False, 'source_runtime_verified': False,
        'value_identity_verified': False, 'transformation_authorized': False,
        'new_lewm_speedup_measurement': False,
        'documents': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in documents},
    })
    files = {str(p.relative_to(HERE)): {'bytes': p.stat().st_size,
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p != HERE / 'manifest.json'}
    dump(HERE / 'manifest.json', {'schema': 'scar.pipeline-composition-archive', 'schema_version': 1, 'files': files})
    print(json.dumps({'archived_files': len(files), 'component_cases': len(component_cases),
                     'full_cases': len(cases), 'preserved_previous_cases': len(old_set)}))


if __name__ == '__main__':
    main()

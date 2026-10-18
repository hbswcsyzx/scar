"""Read-only R3.3 receipt check; starts zero tests, profilers or workloads."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_pipeline_composition'


def read(path):
    return json.loads(path.read_text())


def main():
    files = {str(p.relative_to(HERE)): {'bytes': p.stat().st_size,
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p != HERE / 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == files
    closure = read(HERE / 'closure.json')
    component, full = (read(HERE / p) for p in ('component/final/report.json', 'full/report.json'))
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert component['returncode'] == full['returncode'] == 0
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    assert before == after and not before['worktree_status']
    assert before['revision'] == closure['implementation_revision']
    subprocess.run(['git', 'merge-base', '--is-ancestor', before['revision'], 'HEAD'], cwd=ROOT, check=True)
    assert before['files'] == component['tested_files']
    assert before['source_sha256'] == component['source_sha256'] == closure['source_sha256']
    assert len(before['files']) == closure['source_files']
    assert len(component['criteria']) == closure['criteria'] == 17
    assert all(c['status'] == 'PASS' for c in component['criteria'])
    component_cases = {(case['class'], case['name']) for criterion in component['criteria']
                       for item in criterion['evidence'] for case in item['cases']}
    assert len(component_cases) == closure['component_cases']
    assert hashlib.sha256((HERE / 'full/driver.py').read_bytes()).hexdigest() == (
        '9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28')
    assert not full['driver_errors']
    assert full['basetemp_cleanup'] == 'removed exclusively owned basetemp after child termination'
    assert not Path(full['basetemp']).exists()
    for p, expected in read(HERE / 'full/manifest.json')['files'].items():
        assert files['full/' + p] == expected
    previous = read(PRIOR / 'full/source.before.json')
    assert len(previous['files']) == 567 and set(previous['files']) <= before['files'].keys()
    assert len(previous['fixture_sha256']) == 69
    assert all(before['fixture_sha256'].get(p) == sha for p, sha in previous['fixture_sha256'].items())
    old_cases, cases = (read(base / 'full/cases.json') for base in (PRIOR, HERE))
    identity = lambda case: (case['class'], case['name'])
    old_set, case_set = ({identity(case) for case in rows} for rows in (old_cases, cases))
    assert len(old_set) == len(old_cases) == 5011 and old_set <= case_set
    assert len(case_set) == len(cases) == closure['full_cases']
    assert full['counts'] == {'passed': len(cases), 'failed': 0, 'error': 0, 'skipped': 0, 'total': len(cases)}
    preservation = read(HERE / 'preservation.json')
    assert preservation['preserved_previous_cases'] == 5011
    assert preservation['missing_cases'] == preservation['removed_source_files'] == preservation['changed_previous_fixtures'] == []
    protected_before, protected_after = (read(HERE / f'protected.{phase}.json') for phase in ('before', 'after'))
    assert protected_before == protected_after and all(not r['status'] for r in protected_after.values())
    assert not any(closure[k] for k in ('scope_inventory_complete', 'source_runtime_verified',
        'value_identity_verified', 'transformation_authorized', 'new_lewm_speedup_measurement'))
    archive_helpers = runpy.run_path(str(HERE / 'finalize_archive.py'))
    assert read(HERE / 'witness-summary.json') == archive_helpers['witness_summary']()
    assert read(HERE / 'pipeline-budget.final.json') == archive_helpers['final_pipeline_budget']()
    for p, sha in closure['documents'].items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
    digest, current = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert digest == closure['source_sha256'] and current == before['files']
    print(json.dumps({'status': 'PASS', 'archived_files': len(files), 'criteria': closure['criteria'],
        'component_cases': len(component_cases), 'full_cases': len(cases),
        'preserved_previous_cases': len(old_set), 'source_files': len(current),
        'fixtures': len(before['fixture_sha256']), 'tests_started_by_checker': 0}))


if __name__ == '__main__':
    main()

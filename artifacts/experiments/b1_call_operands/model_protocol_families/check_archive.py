"""Read-only audit receipt check; no tests or original witnesses are executed."""
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    actual = {str(p.relative_to(HERE)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    assert read(HERE / 'manifest.json')['files'] == actual
    closure, source = read(HERE / 'closure.json'), read(HERE / 'source.json')
    assert closure['status'] == 'AUDITED_FIELDS_OPEN'
    assert closure['baseline_revision'] == '08c4cbfc6b675919ab15e8654567889727f3c466'
    subprocess.run(['git', 'merge-base', '--is-ancestor', closure['baseline_revision'], 'HEAD'],
                   cwd=ROOT, check=True)
    assert not any(closure[key] for key in ('scope_inventory_complete', 'fields_frozen',
        'protocol_implementation_complete', 'source_runtime_verified',
        'transformation_authorized', 'new_lewm_speedup_measurement', 'new_pytest_runs', 'new_full_runs'))
    digest, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert digest == source['source_sha256'] == closure['source_sha256']
    assert files == source['files'] and len(files) == closure['source_files'] == 603
    fixtures = {str(p.relative_to(ROOT)): sha(p)
        for p in sorted((ROOT / 'tests/fixtures').rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}
    assert fixtures == source['fixtures'] and len(fixtures) == closure['fixtures'] == 78
    for path, expected in closure['documents'].items():
        assert sha(ROOT / path) == expected
    assert len(closure['review_reports']) == 3
    for path, expected in closure['review_reports'].items():
        assert sha(HERE / path) == expected
    plan = (ROOT / 'docs/M1_PROTOCOL_FAMILY_PLAN.md').read_text()
    groups = set(re.findall(r'^\| ((?:F|X)\d\d) \|', plan, re.M))
    assert groups == {f'F{i:02}' for i in range(1, 25)} | {f'X{i:02}' for i in range(25, 29)}
    assert len(groups) == closure['obligation_groups'] == 28
    prior = ROOT / closure['prior_full']['path']
    assert sha(prior) == closure['prior_full']['sha256']
    prior_report = read(prior)
    assert prior_report['status'] == 'PASS' and prior_report['counts']['passed'] == 5294
    assert prior_report['expected_revision'] == closure['prior_full']['implementation_revision']
    assert prior_report['expected_source_sha256'] == digest
    core = read(HERE / 'current_core_probe.json')
    assert core['revision'] == closure['baseline_revision'] and core['source_sha256'] == digest
    assert core['source_files'] == 603 and core['source_unchanged']
    assert core['script_sha256'] == sha(HERE / 'current_core_probe.py')
    assert len(core['cases']) == 4 and all(not row['structural_issues'] for row in core['cases'])
    assert core['existing_wrong_flavor_guard'] == ['resumption_flavor']
    assert not core['family_protocol_complete'] and not core['transformation_authorized']
    assert closure['old_ir_observations'] == 5
    assert closure['native_observations'] == 6 and closure['native_witness_executions'] == 1
    assert closure['original_native_witness_exit_code'] == 1
    runpy.run_path(str(HERE / 'check_created_throw_observation.py'))['main']()
    before, after = (read(HERE / f'protected.{name}.json') for name in ('before', 'after'))
    assert before == after and all(not row['status'] for row in before.values())
    for row in after.values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip() == row['revision']
        assert not subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip()
    print(json.dumps({'status': 'AUDIT_RECORDS_VALID', 'archived_files': len(actual),
        'source_files': len(files), 'fixtures': len(fixtures), 'obligation_groups': len(groups),
        'tests_started_by_checker': 0, 'witnesses_started_by_checker': 0,
        'fields_frozen': False, 'protocol_implementation_complete': False}))


if __name__ == '__main__':
    main()

"""Check saved R0 design evidence only; no tests, probes or workloads."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('manifest.json')['files']
    actual = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
              if path.is_file() and path != BASE / 'manifest.json'}
    assert actual == set(manifest)
    for name, item in manifest.items():
        path = (BASE / name).resolve()
        assert BASE in path.parents and not (BASE / name).is_symlink(), name
        raw = path.read_bytes()
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'], name
    accepted = read('acceptance.json')
    assert accepted['status'] == 'PASS_RELATION_DESIGN'
    contract_sha = hashlib.sha256((BASE / 'contract.md').read_bytes()).hexdigest()
    assert contract_sha == accepted['contract_sha256']
    assert hashlib.sha256((BASE / 'plan.md').read_bytes()).hexdigest() == accepted['plan_sha256']
    for name in ('reuse', 'identity', 'work-ready'):
        report = BASE / f'review/final-{name}.md'
        assert contract_sha in report.read_text()
        assert hashlib.sha256(report.read_bytes()).hexdigest() == accepted['final_review_sha256'][name]
    receipt = read('witnesses/command.json')
    assert receipt['returncode'] == 0
    script = BASE / 'witnesses/runtime_witnesses.py'
    assert hashlib.sha256(script.read_bytes()).hexdigest() == receipt['script_sha256']
    observed = read('witnesses/run.log')
    assert observed['status'] == 'PASS' and observed['owned_temporary_removed']
    assert len(observed['cases']) == accepted['witness_case_count'] == 6
    assert len({case['case'] for case in observed['cases']}) == 6
    assert all(case['status'] == 'PASS' for case in observed['cases'])
    continuity = read('source-continuity.json')
    prior = read('../model_lifecycle_composition/full/source.after.json')
    assert continuity['source_sha256'] == prior['source_sha256'] == accepted['registered_source_sha256']
    assert continuity['files'] == prior['files']
    assert len(continuity['files']) == accepted['registered_source_files'] == 451
    assert continuity['prior_frozen_revision'] == prior['revision']
    assert continuity['same_as_D2_4_frozen_source']
    assert all(accepted[key] is False for key in (
        'r1_product_implemented', 'r2_product_implemented', 'full_first_stage_complete',
        'new_full_regression_run', 'gpu_witness_run', 'source_runtime_verified',
        'resource_ready_verified', 'transformation_verified', 'lewm_speedup_measured'))
    assert read('research/sources.json')['cudart_version_macro'] == 13020
    assert all(not row['worktree_status'] and row['revision'] == row['expected_revision']
               for row in read('protected-checkouts.json')['checkouts'].values())
    print(json.dumps({'archive_integrity': 'PASS', 'files': len(manifest),
        'relation_design': 'PASS', 'real_stdlib_witnesses': 6,
        'registered_source_unchanged': True, 'r1_r2_product_implemented': False}))


if __name__ == '__main__':
    main()

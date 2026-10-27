"""Bind/recheck saved design evidence; never start a test, witness or workload."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = 'f9a568182e1672541261020bb9f919609179bb05'
PRIOR = HERE.parent / 'model_protocol_families'
DOCUMENTS = ('docs/M1_PROTOCOL_CONTRACT.md', 'docs/M1_PROTOCOL_FAMILY_PLAN.md',
             'docs/STATUS.md', 'docs/FIRST_STAGE_COMPLETION_MATRIX.md',
             'README.md', 'docs/ROADMAP.md', 'docs/WHOLE_PROGRAM_MODEL_PLAN.md',
             'docs/MODELING_REUSE_DECISION.md')
SOURCE_SHA = '7d3187f36f6cca07e0714a49ac20dbe1c0634601568f2986ef8f0c178431f7a9'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def protected():
    return {key: {'path': row['path'],
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip(),
        'status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip()}
        for key, row in read(PRIOR / 'protected.after.json').items()}


def source():
    digest, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    saved = read(PRIOR / 'source.json')
    assert digest == saved['source_sha256'] == SOURCE_SHA
    assert files == saved['files'] and len(files) == 603
    fixtures = {str(p.relative_to(ROOT)): sha(p)
        for p in sorted((ROOT / 'tests/fixtures').rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}
    assert fixtures == saved['fixtures'] and len(fixtures) == 78
    return digest, files, fixtures


def manifest_files():
    return {str(p.relative_to(HERE)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'manifest.json'}


def finalize():
    digest, files, fixtures = source()
    before, after = read(HERE / 'protected.before.json'), protected()
    assert before == after == read(PRIOR / 'protected.after.json')
    assert all(not row['status'] for row in after.values())
    review = read(HERE / 'review.json')
    assert review['status'] == 'PASS_WITH_SCOPE'
    assert not review['unresolved_design_blockers']
    for path, expected in review['reviewed_files'].items():
        assert sha(ROOT / path) == expected
    dump(HERE / 'protected.after.json', after)
    prior_full = read(PRIOR / 'closure.json')['prior_full']
    dump(HERE / 'closure.json', {
        'status': 'P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN',
        'baseline_revision': BASE, 'source_sha256': digest,
        'source_files': len(files), 'fixtures': len(fixtures),
        'fields_frozen': True, 'protocol_implementation_complete': False,
        'scope_inventory_complete': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup_measurement': False,
        'obligation_groups': 28, 'design_blueprint_executions': 1,
        'new_native_witness_runs': 0, 'new_pytest_runs': 0, 'new_full_runs': 0,
        'prior_source': {'path': str((PRIOR / 'source.json').relative_to(ROOT)),
                         'sha256': sha(PRIOR / 'source.json')},
        'prior_audit_manifest': {'path': str((PRIOR / 'manifest.json').relative_to(ROOT)),
                                'sha256': sha(PRIOR / 'manifest.json')},
        'prior_full': prior_full,
        'documents': {path: sha(ROOT / path) for path in DOCUMENTS},
        'reviews': {str(p.relative_to(HERE)): sha(p)
                    for p in sorted((HERE / 'design').glob('*.md'))},
    })
    files = manifest_files()
    dump(HERE / 'manifest.json', {'schema': 'scar.protocol-contract-design-archive',
                                'schema_version': 1, 'files': files})
    print(json.dumps({'status': 'P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN',
                      'archived_files': len(files), 'source_files': 603, 'fixtures': 78}))


def check():
    assert read(HERE / 'manifest.json')['files'] == manifest_files()
    closure, review = read(HERE / 'closure.json'), read(HERE / 'review.json')
    assert closure['status'] == 'P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN'
    assert closure['baseline_revision'] == BASE and closure['fields_frozen']
    assert review['status'] == 'PASS_WITH_SCOPE' and not review['unresolved_design_blockers']
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=ROOT, check=True)
    assert not any(closure[key] for key in (
        'protocol_implementation_complete', 'scope_inventory_complete',
        'source_runtime_verified', 'transformation_authorized',
        'new_lewm_speedup_measurement', 'new_native_witness_runs',
        'new_pytest_runs', 'new_full_runs'))
    digest, files, fixtures = source()
    assert digest == closure['source_sha256']
    assert len(files) == closure['source_files'] == 603
    assert len(fixtures) == closure['fixtures'] == 78
    for path, expected in closure['documents'].items():
        assert sha(ROOT / path) == expected
    for path, expected in closure['reviews'].items():
        assert sha(HERE / path) == expected
    for path, expected in review['reviewed_files'].items():
        assert sha(ROOT / path) == expected
    groups = set(re.findall(r'^\| ((?:F|X)\d\d) \|',
        (ROOT / 'docs/M1_PROTOCOL_FAMILY_PLAN.md').read_text(), re.M))
    assert groups == {f'F{i:02}' for i in range(1, 25)} | {f'X{i:02}' for i in range(25, 29)}
    assert len(groups) == closure['obligation_groups'] == 28
    for name in ('prior_source', 'prior_audit_manifest', 'prior_full'):
        assert sha(ROOT / closure[name]['path']) == closure[name]['sha256']
    # Historical P0 document receipts remain relative to their frozen revision.
    prior_closure = read(PRIOR / 'closure.json')
    for path, expected in prior_closure['documents'].items():
        frozen = subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=ROOT)
        assert hashlib.sha256(frozen).hexdigest() == expected
    full = read(ROOT / closure['prior_full']['path'])
    assert full['status'] == 'PASS' and full['counts']['passed'] == 5294
    assert full['expected_source_sha256'] == digest
    assert full['expected_revision'] == closure['prior_full']['implementation_revision']
    blueprint = read(HERE / 'port-blueprint-attempt001.json')
    assert blueprint['revision'] == BASE and blueprint['source_sha256'] == digest
    assert blueprint['source_unchanged'] and blueprint['source_files'] == 603
    assert blueprint['status'] == 'DESIGN_PORTS_CONNECTED'
    assert blueprint['script_sha256'] == sha(HERE / 'port_blueprint.py')
    assert not any(blueprint[key] for key in ('new_product_capability', 'new_pytest_run',
                                            'source_runtime_verified', 'transformation_authorized'))
    assert not blueprint['existing_execution_issues']
    start, resume = blueprint['rows']
    assert start['activation'] == resume['activation']
    assert start['derived_segment'] != resume['derived_segment']
    assert [len(row['inputs']) for row in (start, resume)] == [8, 5]
    assert all(len(row['outputs']) == 3 for row in (start, resume))
    assert sum(row['kind'] == 'INSTANCE_CAPTURE_UNRESOLVED' for row in start['inputs']) == 6
    assert closure['design_blueprint_executions'] == 1
    assert sha(HERE / 'design/f-static.initial.md') == '02bda9999214771ad3c2c4f46aa98ff594fb134e8e21b5560cc416533585ba32'
    before, after = read(HERE / 'protected.before.json'), read(HERE / 'protected.after.json')
    assert before == after == protected() and all(not row['status'] for row in after.values())
    print(json.dumps({'status': 'CONTRACT_DESIGN_RECORDS_VALID', 'source_files': 603,
        'fixtures': 78, 'obligation_groups': 28, 'tests_started_by_checker': 0,
        'witnesses_started_by_checker': 0, 'implementation_complete': False}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('snapshot-before', 'finalize', 'check'))
    action = parser.parse_args().action
    if action == 'snapshot-before':
        assert not (HERE / 'protected.before.json').exists()
        actual = protected()
        assert actual == read(PRIOR / 'protected.after.json')
        dump(HERE / 'protected.before.json', actual)
        print(json.dumps({'status': 'PROTECTED_BASELINE_SAVED'}))
    elif action == 'finalize':
        finalize()
    else:
        check()


if __name__ == '__main__':
    main()

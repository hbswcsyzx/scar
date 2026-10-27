"""Bind this design audit; start no test, witness, profiler or workload."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = '08c4cbfc6b675919ab15e8654567889727f3c466'
PRIOR = HERE.parent / 'model_literals'
DOCUMENTS = ('README.md', 'docs/STATUS.md', 'docs/ROADMAP.md',
    'docs/FIRST_STAGE_COMPLETION_MATRIX.md', 'docs/WHOLE_PROGRAM_MODEL_PLAN.md',
    'docs/WHOLE_PROGRAM_MODEL.md', 'docs/MODELING_REUSE_DECISION.md',
    'docs/M1_RESUMPTION_INTERFACES.md', 'docs/M1_DRIVER_CONTRACT_V2.md',
    'docs/model/PYTHON_CONTROL_PROTOCOLS.md', 'docs/M1_PROTOCOL_FAMILY_AUDIT.md',
    'docs/M1_PROTOCOL_FAMILY_PLAN.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    digest, files = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    old = json.loads((PRIOR / 'full/source.before.json').read_text())
    assert files == old['files'] and digest == old['source_sha256']
    fixtures = {str(p.relative_to(ROOT)): sha(p)
        for p in sorted((ROOT / 'tests/fixtures').rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}
    assert fixtures == old['fixture_sha256']
    before = json.loads((HERE / 'protected.before.json').read_text())
    after = {key: {'path': row['path'],
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip(),
        'status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True).strip()}
        for key, row in before.items()}
    assert after == before and all(not row['status'] for row in after.values())
    dump(HERE / 'protected.after.json', after)
    dump(HERE / 'source.json', {'source_sha256': digest, 'files': files, 'fixtures': fixtures})
    dump(HERE / 'closure.json', {'status': 'AUDITED_FIELDS_OPEN', 'baseline_revision': BASE,
        'source_sha256': digest, 'source_files': len(files), 'fixtures': len(fixtures),
        'scope_inventory_complete': False, 'fields_frozen': False,
        'protocol_implementation_complete': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup_measurement': False,
        'obligation_groups': 28, 'old_ir_observations': 5, 'native_observations': 6,
        'native_witness_executions': 1, 'original_native_witness_exit_code': 1,
        'new_pytest_runs': 0, 'new_full_runs': 0,
        'prior_full': {'path': str((PRIOR / 'full/report.json').relative_to(ROOT)),
                       'sha256': sha(PRIOR / 'full/report.json'),
                       'implementation_revision': old['revision'], 'cases': 5294},
        'documents': {p: sha(ROOT / p) for p in DOCUMENTS},
        'review_reports': {str(p.relative_to(HERE)): sha(p) for p in sorted((HERE / 'design').glob('*.md'))}})
    files = {str(p.relative_to(HERE)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    dump(HERE / 'manifest.json', {'schema': 'scar.protocol-family-audit-archive',
                                'schema_version': 1, 'files': files})
    print(json.dumps({'archived_files': len(files), 'source_files': len(old['files']),
                      'fixtures': len(fixtures), 'status': 'AUDITED_FIELDS_OPEN'}))


if __name__ == '__main__':
    main()

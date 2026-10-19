"""Freeze current original scope before any source edits; start no tests."""
import hashlib
import json
from pathlib import Path
import subprocess

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_session_ownership'
BASE = '51a6eb3354eb05f7c02c9ff189239166f2cd4081'
PLAN = 'docs/M1_CALL_EFFECT_EXPANSION_PLAN.md'
MIGRATION = 'docs/M1_CALL_EFFECT_EXPANSION_CODEC_MIGRATION.md'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert not (HERE / 'design-baseline.json').exists()
previous = read(PRIOR / 'checkpoint.json')
before, sources = fingerprint()
assert before == previous['source_sha256'] and len(sources) == 878
assert sources == read(PRIOR / 'verified-final/sources.after.json')
for row in previous['protected'].values():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=row['path'], text=True).strip() == row['head']
    assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=row['path'], text=True) == row['status']
for name in ('original-obligations.json', 'family-obligations.json'):
    (HERE / name).write_bytes((PRIOR / name).read_bytes())
selection = read(PRIOR / 'focused-selection.json')
selection['scope'] = 'Affected focused only; all1956 previous obligations retained with5 explicit future-version migrations; not component/full/automatic source or LeWM proof.'
selection['selectors'].extend([
    'tests/unit/test_program_call_effect_expansion.py',
    'tests/unit/test_program_call_effect_expansion_codec.py',
    'tests/unit/test_execution_call_effect_expansion.py'])
(HERE / 'focused-selection.json').write_text(json.dumps(selection, indent=2) + '\n')
design = {'base_revision': BASE,
    'previous_turn': 'VERIFIED_PROGRESS;1956 affected focused;all1907 obligations retained;878 stable sources;commit/push exact remote SHA and clean verified',
    'scope_plan': PLAN, 'plan_sha256': sha(PLAN),
    'codec_migration': MIGRATION, 'codec_migration_sha256': sha(MIGRATION),
    'prior_checkpoint_sha256': sha(PRIOR / 'checkpoint.json'),
    'previous_focused_cases': 1956, 'previous_source_sha256': before,
    'previous_source_count': len(sources), 'protected': previous['protected'],
    'obligation_groups': previous['obligation_groups'],
    'completed_obligation_groups': previous['completed_obligation_groups'],
    'previous_closed_A_H': previous['closed_original_A_H_structural_obligations'],
    'm2_original_constructs': 113, 'm2_original_fields': 196,
    'p4_complete': False, 'p5_complete': False, 'm0_m2_complete': False,
    'new_backend': False, 'new_lewm_speedup': False, 'tests_started_by_prepare': 0}
(HERE / 'design-baseline.json').write_text(json.dumps(design, indent=2) + '\n')
print(json.dumps({'status': 'BASELINE_BOUND', 'source_sha256': before,
                  'source_count': len(sources), 'previous_cases': 1956, 'tests_started': 0}))

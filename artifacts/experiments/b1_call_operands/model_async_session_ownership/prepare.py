"""Freeze the original scope before authors change sources; no tests."""
import hashlib
import json
from pathlib import Path
import subprocess

from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_native_coroutine_connections'
BASE = 'f22d64196d2f706c66e99f7acb4bcffa8373a98c'
PLAN = 'docs/M1_ASYNC_SESSION_OWNERSHIP_PLAN.md'
PLAN_SHA = 'af6813d044e0ab85868f9bcaae9b2c28494b12be13a9e9e3026abbff5b95355c'
NEW_TESTS = ['tests/unit/test_program_session_occupancy.py',
             'tests/unit/test_program_session_occupancy_codec.py',
             'tests/unit/test_execution_async_competition.py',
             'tests/unit/test_execution_session_occupancy.py']


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert sha(Path(PLAN)) == PLAN_SHA
previous, design = read(PRIOR / 'checkpoint.json'), read(PRIOR / 'design-baseline.json')
for path, digest in previous['files'].items():
    assert sha(Path(path)) == digest, path
source_digest, sources = fingerprint()
assert source_digest == previous['source_sha256'] and len(sources) == 870
assert sources == read(PRIOR / 'verified-final/sources.after.json')
for state in design['protected'].values():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
    assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
record = {**design, 'base_revision': BASE, 'scope_plan': PLAN, 'plan_sha256': PLAN_SHA,
    'prior_checkpoint_sha256': sha(PRIOR / 'checkpoint.json'),
    'previous_turn': 'VERIFIED_PROGRESS: native F14 conditional structural acceptance;1907 focused/all1890 retained;870 stable sources;commit exact remote SHA and clean verified.',
    'previous_focused_cases': 1907, 'completed_obligation_groups': previous['completed_obligation_groups'],
    'previous_source_sha256': source_digest, 'previous_source_count': len(sources),
    'contract_review': 'Separate frame phase/session occupancy/request initial/completion; new thin typed subject Program24, no extra canonical state; original full F16 still required.',
    'tests_started_by_prepare': 0}
assert not (HERE / 'design-baseline.json').exists()
(HERE / 'design-baseline.json').write_text(json.dumps(record, indent=2) + '\n')
selection = read(PRIOR / 'focused-selection.json')
selection.update(selectors=selection['selectors'] + NEW_TESTS,
    scope='Affected focused only; all original1907 identities retained; not component/full/automatic source or LeWM proof.',
    previous_focused_cases=1907,
    reason='Original F16 two-R competition, typed occupancy read, precise preservation and source/control joins.')
(HERE / 'focused-selection.json').write_text(json.dumps(selection, indent=2) + '\n')
for name in ('original-obligations.json', 'family-obligations.json'):
    (HERE / name).write_bytes((PRIOR / name).read_bytes())
print(json.dumps({'status': 'FROZEN_ASYNC_SESSION_OWNERSHIP_PLAN',
    'previous_focused_cases': 1907, 'previous_source_files': len(sources),
    'new_test_modules': NEW_TESTS, 'tests_started': 0}))

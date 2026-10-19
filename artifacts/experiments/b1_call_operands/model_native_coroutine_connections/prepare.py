"""Freeze original scope before serial supplied-model testing; no tests here."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_state_fact_continuations'
BASE = 'f26829c126f519043943af85c0faa62a9c76dd3b'
PLAN = 'docs/M1_NATIVE_COROUTINE_PLAN.md'
EXPECTED_PLAN = 'ef2f9800295c5fa23d26140711fdd8852bad2a19e210fb22a40440ea0d288167'
NEW_TESTS = ['tests/unit/test_execution_coroutine_running.py',
             'tests/unit/test_execution_coroutine_closed.py',
             'tests/unit/test_execution_coroutine_packets.py']


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert sha(Path(PLAN)) == EXPECTED_PLAN
previous, design = read(PRIOR / 'checkpoint.json'), read(PRIOR / 'design-baseline.json')
for path, digest in previous['files'].items():
    assert sha(Path(path)) == digest, path
protected = design['protected']
for state in protected.values():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
    assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
record = {**design, 'base_revision': BASE,
    'previous_turn': 'VERIFIED_PROGRESS;1890 pass,all1865 retained,862 stable sources; exact remote SHA and clean protected repositories checked; checkpoint rechecked this turn.',
    'scope_plan': PLAN, 'plan_sha256': EXPECTED_PLAN,
    'prior_checkpoint_sha256': sha(PRIOR / 'checkpoint.json'),
    'previous_focused_cases': 1890,
    'contract_review': 'Original active-Drive interval versus original explicit terminal F/no-reset history; mutable content and current P are separate. Exact native two-AWAIT and current packet ports. No new schema/backend/LeWM rule.',
    'tests_started_by_prepare': 0}
assert not (HERE / 'design-baseline.json').exists()
(HERE / 'design-baseline.json').write_text(json.dumps(record, indent=2) + '\n')
selection = read(PRIOR / 'focused-selection.json')
selection.update(selectors=selection['selectors'] + NEW_TESTS,
    scope='Affected focused only; retain all original1890 identities; not component/full/native or LeWM proof.',
    previous_focused_cases=1890,
    reason='Original native coroutine running/closed/current packet/control connections and derived body-state history.')
(HERE / 'focused-selection.json').write_text(json.dumps(selection, indent=2) + '\n')
for name in ('original-obligations.json', 'family-obligations.json'):
    (HERE / name).write_bytes((PRIOR / name).read_bytes())
print(json.dumps({'status': 'FROZEN_NATIVE_COROUTINE_PLAN', 'previous_focused_cases': 1890,
                  'new_test_modules': NEW_TESTS, 'tests_started': 0}))

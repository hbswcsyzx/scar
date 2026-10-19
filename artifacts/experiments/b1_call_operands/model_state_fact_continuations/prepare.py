"""Freeze scope and the original acceptance denominator before interpreter tests."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
PRIOR = HERE.parent / 'model_current_async_packet'
BASE = 'fa7b769e34adf5ef39c27103c11b6cb75f796f7b'
PLAN = 'docs/M1_STATE_FACT_CONTINUATION_PLAN.md'
PLAN_SHA = '7f3d1834d990dbc6dec3e2edc95f861480b30cbe653939abb4cd735acdca8f0e'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, row):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(row, indent=2) + '\n')

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert sha(ROOT / PLAN) == PLAN_SHA
previous = json.loads((PRIOR / 'checkpoint.json').read_text())
assert previous['focused_cases'] == 1865 and previous['previous_focused_obligations_retained'] == 1854
assert previous['source_sha256'] == '1855d15c876ec76e2992abe27dfe8bcc58de2852c5f0b57692d278952f47047b'
design = json.loads((PRIOR / 'design-baseline.json').read_text())
design.update(base_revision=BASE, previous_focused_cases=1865,
    previous_turn='VERIFIED_PROGRESS: model source bridge and budget repair,1865 pass, all1854 retained,858 stable sources; post-commit checkpoint and exact remote SHA verified. Prior checkpoint rechecked at this turn start.',
    scope_plan=PLAN, plan_sha256=PLAN_SHA,
    prior_checkpoint_sha256=sha(PRIOR / 'checkpoint.json'),
    contract_review='Original state facts, complete support union, exact actual interval/call/effect receipts. Distinct LocationID is not isolation; known callee expansion does not exempt outer incomplete. Original R3 remains blocked; no F14/F16 full acceptance.')
write('design-baseline.json', design)
selection = json.loads((PRIOR / 'focused-selection.json').read_text())
selection.update(previous_focused_cases=1865,
    scope='Affected focused only; preserve exact original1865. No component/full, native or LeWM proof.',
    reason='Generic exact state-content preservation and derived original SessionUpdate to RequestStateCondition history.',
    case_identity_migration='none; old tests/fixtures unchanged')
selection['selectors'] += ['tests/unit/test_execution_state_preservation.py',
                            'tests/unit/test_execution_request_state_history.py']
write('focused-selection.json', selection)
for name in ('original-obligations.json', 'family-obligations.json'):
    write(name, json.loads((PRIOR / name).read_text()))
print(json.dumps({'base': BASE, 'prior_focused': 1865, 'plan_sha256': PLAN_SHA,
                  'previous_turn': 'VERIFIED_PROGRESS', 'tests_started': 0}))

"""Freeze this finite gate's starting evidence, before source authorship."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_await_reevaluation'
BASE = '7aee713c1b700f504ba3ebb8606fa2a4456c4e1c'
PLAN = 'docs/M1_DIRECT_QUALIFICATION_AND_RESULT_PLAN.md'
PLAN_SHA = '10c6d970c8b60509af4f7d23282c6d0f60309b27219e175c086541067f6534b6'

def write(name, value):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2) + '\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert sha(ROOT / PLAN) == PLAN_SHA
previous = json.loads((PRIOR / 'checkpoint.json').read_text())
assert previous['focused_cases'] == 1845 and previous['previous_focused_obligations_retained'] == 1807
assert previous['closed_original_A_H_structural_obligations'] == ['E', 'G', 'H']
assert previous['completed_obligation_groups'] == ['F17', 'F21', 'F23']
assert previous['source_sha256'] == '908182cfa79d2fb0609c6747fb4b96fe83a202949af3cb5dbd3e940a1b97da92'
design = json.loads((PRIOR / 'design-baseline.json').read_text())
design.update(base_revision=BASE,
    previous_turn='verified progress:1845 affected focused, original1807 retained, E/G/H and F17/F21/F23 conditional structural acceptance; checkpoint before/after commit, exact remote SHA and clean protected repositories verified. Prior checkpoint rerun at this turn start.',
    prior_checkpoint_sha256=sha(PRIOR / 'checkpoint.json'),
    previous_focused_cases=1845,
    scope_plan=PLAN, plan_sha256=PLAN_SHA,
    previous_closed_A_H=['E', 'G', 'H'],
    completed_obligation_groups=['F17', 'F21', 'F23'],
    contract_review='Finite F15 exact negatives; ordinary GENERATOR direct/self await qualification and an actual other-Drive adapter result, not reversed general-return, wrong O association or helper results. Independent original F12/F13 read audit; no product changes without a real public failure.')
write('design-baseline.json', design)
selection = json.loads((PRIOR / 'focused-selection.json').read_text())
selection.update(previous_focused_cases=1845,
    scope='Affected focused only; preserve exact previous1845 and original E/G/H/F17/F21/F23 acceptance. No component/full or LeWM benchmark claim.',
    case_identity_migration='none; all prior tests and fixtures unchanged from7aee713',
    reason='Two precise F15 negative obligations, with only necessary valid controls; no all-source/cut Cartesian expansion.')
selection['selectors'] += [
    'tests/unit/test_program_await_direct_qualification.py',
    'tests/unit/test_program_await_foreign_drive_result.py']
write('focused-selection.json', selection)
for name in ('original-obligations.json', 'family-obligations.json'):
    write(name, json.loads((PRIOR / name).read_text()))
print(json.dumps({'base': BASE, 'plan_sha256': PLAN_SHA, 'prior_focused': 1845,
    'previous_A_H_closed': design['previous_closed_A_H'],
    'remaining_family_count': 13, 'tests_started': 0}))

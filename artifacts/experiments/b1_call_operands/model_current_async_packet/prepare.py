"""Bind the finite plan and preceding acceptance without starting tests."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_direct_qualification_and_foreign_result'
BASE = '9293836d75e9c1d9a64849749d1b8b92529908b1'
PLAN = 'docs/M1_CURRENT_ASYNC_PACKET_PLAN.md'
PLAN_SHA = '2e3cfeb4084454938d3ef58e6880448601b71c0cc0fcb35d6e342c61e95ff10e'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, row):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(row, indent=2) + '\n')

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
assert sha(ROOT / PLAN) == PLAN_SHA
previous = json.loads((PRIOR / 'checkpoint.json').read_text())
assert previous['focused_cases'] == 1854
assert previous['closed_original_A_H_structural_obligations'] == list('ABCDEFGH')
assert previous['completed_obligation_groups'] == ['F12', 'F13', 'F15', 'F17', 'F21', 'F23']
design = json.loads((PRIOR / 'design-baseline.json').read_text())
design.update(base_revision=BASE, previous_turn='VERIFIED_PROGRESS: prior checkpoint checked at turn start;1854 affected focused, original1845 retained; exact remote SHA and protected repos clean.',
    prior_checkpoint_sha256=sha(PRIOR / 'checkpoint.json'), previous_focused_cases=1854,
    scope_plan=PLAN, plan_sha256=PLAN_SHA, previous_closed_A_H=list('ABCDEFGH'),
    completed_obligation_groups=previous['completed_obligation_groups'],
    contract_review='Current scheduler THROW/CLOSE own NORMAL packet source, exact wrong latent input and missing attachment; same R actual completed-reuse chain only if complete supplied activations. F14/F16 not closed by this subset.')
write('design-baseline.json', design)
selection = json.loads((PRIOR / 'focused-selection-f12.json').read_text())
selection.pop('amendment', None)
selection.update(previous_focused_cases=1854,
    scope='Affected focused only, preserve exact1854; not component/full or actual native/LeWM proof.',
    reason='One previously unconditional scheduler packet gap and the actual same-request reuse seam.',
    case_identity_migration='none; prior test/fixture bytes preserved')
selection['selectors'] += ['tests/unit/test_program_async_scheduler_packets.py',
                            'tests/unit/test_program_async_completed_reuse.py']
write('focused-selection.json', selection)
for name in ('original-obligations.json', 'family-obligations.json'):
    write(name, json.loads((PRIOR / name).read_text()))
print(json.dumps({'base': BASE, 'plan_sha256': PLAN_SHA, 'prior_focused': 1854,
    'accepted_families_retained': previous['completed_obligation_groups'], 'tests_started': 0}))

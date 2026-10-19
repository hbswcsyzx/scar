"""One-time gate record preparation; no tests or workloads."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_delegate_close_continuations'
ROOT = Path.cwd()


def write(name, value):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2) + '\n')


design = json.loads((PRIOR / 'design-baseline.json').read_text())
design.update(base_revision='2dd97caad70884a8224427aed15614b71d6491c7',
    previous_turn='verified progress:1807 affected focused, original1793 retained, G/F17/F21/F23 conditional structural acceptance, immutable archive before/after commit and exact remote verified; initially clean',
    previous_focused_cases=1807,
    scope_plan='docs/M1_AWAIT_REEVALUATION_PLAN.md',
    plan_sha256=hashlib.sha256((ROOT / 'docs/M1_AWAIT_REEVALUATION_PLAN.md').read_bytes()).hexdigest(),
    completed_obligation_groups=['F17', 'F21', 'F23'],
    contract_review='Three finite read reviews found no wire blocker. Preserve original E/H scope, earlier carrier versus own-result slots, genuine same-caller pipeline backedge and distinct per-round B. Real tests precede fixes; known-source forms are not permission to select by time or root.')
assert design['plan_sha256'] == 'ac705fa754012e4c42422503cbe19d9701899a4bc8fd885af6051a6762dfc46a'
write('design-baseline.json', design)
selection = json.loads((PRIOR / 'focused-selection.json').read_text())
selection.update(previous_focused_cases=1807,
    scope='Affected focused only; preserve G/F17/F21/F23 acceptance and original remaining matrix, not component/full or LeWM benchmark',
    case_identity_migration='none; all prior tests and fixtures unchanged from2dd97ca',
    reason='Preserve original1807 exact identities. Test same static source multiple own-result occurrences and real same-caller Create/Get/pipeline backedges. Original E/H and remaining13 families/P5/M2 retain full scope.')
selection['selectors'] += ['tests/unit/test_execution_await_source_visits.py',
                         'tests/unit/test_execution_await_pipeline_reexecution.py']
write('focused-selection.json', selection)

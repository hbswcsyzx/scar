"""Create this gate's records once; no tests, collectors, or workloads."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_delegate_edges'
ROOT = Path.cwd()


def write(name, value):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2) + '\n')


previous = json.loads((PRIOR / 'design-baseline.json').read_text())
previous.update(base_revision='4ac61ec63161dfdb9e66fc5a51ce2df02453b5ea',
    previous_turn='progress:1793 affected focused green, original1780 retained, F17/F21 and G conditional structural closed, archive checked before/after commit, exact remote and initial clean worktree verified',
    previous_focused_cases=1793,
    scope_plan='docs/M1_DELEGATE_CLOSE_PLAN.md',
    plan_sha256=hashlib.sha256((ROOT / 'docs/M1_DELEGATE_CLOSE_PLAN.md').read_bytes()).hexdigest(),
    completed_obligation_groups=['F17', 'F21'],
    contract_review='Three read reviews confirm original N3 close/C1 inventory and exact actual continuation scope. Actual CFG review corrected an initial shared-block name inference; both selected close completions cross the second cut. No wire blocker identified; real tests precede product fixes.')
assert previous['plan_sha256'] == '7a7d9411d23e00070ce51164e1511a416277bb5296b9b22820ea5175ef700706'
write('design-baseline.json', previous)
selection = json.loads((PRIOR / 'focused-selection.json').read_text())
selection.update(previous_focused_cases=1793,
    scope='Affected focused only; F17/F21 and G structural acceptance retained, other original obligations remain; not component/full/LeWM benchmark',
    case_identity_migration='none; all existing tests and fixtures unchanged from4ac61ec',
    reason='Preserve old1793 exact case identities and closed G/F17/F21. Validate original N3 close/C1 whole-attachment deletion and precise per-instance dynamic continuations; other original families/P5/M2 remain required.')
selection['selectors'] += [
    'tests/unit/test_program_delegate_close_inventory.py',
    'tests/unit/test_execution_delegate_close_continuations.py']
write('focused-selection.json', selection)
families = json.loads((PRIOR / 'family-obligations.json').read_text())
families['scope'] = 'Original F12-F24/X25-X27; F17/F21 retained, N3/F23 and its X27 intersection assessed here'
families['reviewed'].append({'id': 'F23', 'existing_selectors': [
    'tests/unit/test_program_continuation_connections.py::test_close_normal_continues_old_injection_but_raise_overrides_with_own_packet',
    'tests/unit/test_program_continuation_connections.py::test_shared_cleanup_pending_cannot_use_close_none_or_lose_the_new_close_exception',
    'tests/unit/test_program_packet_continuations.py::test_close_selected_normal_and_raise_continue_through_real_c1_to_the_host_packet',
    'tests/unit/test_program_continuation_connections.py::test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace',
    'tests/unit/test_program_continuation_connections.py::test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct',
    'tests/unit/test_resumption_cleanup.py::test_resumed_cleanup_invoke_normal_resumes_and_new_raise_replaces_pending',
    'tests/unit/test_resumption_cleanup.py::test_resumed_cleanup_invoke_rejects_old_pre_attach_or_pre_failure_states',
    'tests/unit/test_program_packet_continuations.py::test_close_route_does_not_stop_successfully_at_c1_before_a_later_opaque_operation',
    'tests/unit/test_program_packet_continuations.py::test_a_truncated_full_continuation_retains_a_cursor_and_cannot_close_its_consumer_inventory',
    'tests/unit/test_program_packet_continuation_edges.py::test_known_packet_helper_copy_does_not_hide_an_opaque_operation_inside_the_callee'],
    'remaining': 'N3 static deletion and exact actual continuation evidence pending'})
write('family-obligations.json', families)

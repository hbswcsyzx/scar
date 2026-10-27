"""Create the finite original-clause review only after the real final run."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
final = json.loads((HERE / 'verified-final/result.json').read_text())
source, _ = fingerprint()
assert final['returncode'] == 0 and final['source_unchanged']
assert source == final['source_sha256_before'] == final['source_sha256_after']
rows = tuple(ET.parse(HERE / 'verified-final/junit.xml').iter('testcase'))
assert len(rows) == 2058
assert not any(row.find(tag) is not None for row in rows for tag in ('failure', 'error', 'skipped'))
family = json.loads((HERE / 'family-obligations.json').read_text())
clauses = [
    ('four request origins and independent association', [
        'test_program_async_connections::test_request_origin_projects_its_exact_create_body_and_latent_not_scheduler',
        'test_program_async_connections::test_same_typed_external_body_cannot_replace_the_exact_request_projection',
        'test_program_async_connections::test_attached_association_cannot_swap_its_two_exact_normal_results']),
    ('initial and current scheduler delivery, original ordinals and own N/R', [
        'test_program_async_connections::test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state',
        'test_program_async_connections::test_later_request_step_uses_current_scheduler_not_latent_payload',
        'test_program_async_scheduler_packets::test_later_scheduler_packet_uses_s_normalization_own_normal_and_separate_raise_states',
        'test_program_async_scheduler_packets::test_later_scheduler_normalizer_cannot_take_same_kind_latent_l_instead']),
    ('initial R, Created B and exact effective ordinal jointly reach Start/Resume/reject', [
        'test_program_async_initial_control::test_initial_asend_joint_control_keeps_real_sources_targets_and_all_ports',
        'test_execution_async_initial_control::test_actual_initial_control_has_exact_request_body_current_states_and_continuation',
        'test_program_async_initial_control::test_independent_roles_and_bool_are_not_joint_initial_control']),
    ('known S override, unknown S and caller/source coverage', [
        'test_program_async_initial_selection::test_initial_nonNone_scheduler_cannot_be_replaced_with_stored_none_latent',
        'test_program_async_initial_selection::test_initial_nonNone_scheduler_supplies_the_original_resume_input',
        'test_program_async_initial_selection::test_unknown_first_scheduler_never_authorizes_unconditional_latent_reuse',
        'test_program_async_initial_selection::test_unknown_effective_input_cannot_become_a_created_start_proof',
        'test_program_async_initial_selection::test_association_state_change_cannot_be_dropped_from_the_joint_body_proof',
        'test_program_async_initial_selection::test_mixed_known_and_opaque_scheduler_recipes_keep_the_unclassified_source']),
    ('same completed R reuse and independent R2 competition for the original B', [
        'test_program_async_completed_reuse::test_completed_request_reuses_exact_r_and_latest_states_then_rejects_without_a_second_drive',
        'test_execution_async_competition::test_two_requests_reject_only_r2_then_resume_the_original_body_and_r1']),
    ('historical/current distinction, deleted rows, necessary capture and budget', [
        'test_program_async_initial_control::test_callback_keeps_historical_bool_legal_but_current_phase_support_unknown',
        'test_program_async_initial_control::test_missing_none_attachment_retains_original_bool_branch_helper_and_gates',
        'test_program_async_initial_control::test_created_start_cannot_reuse_latent_none_when_first_scheduler_is_nonNone',
        'test_program_async_initial_control::test_tiny_budget_preserves_whole_joint_inventory_and_never_grants_a_prefix',
        'test_execution_async_initial_control::test_missing_current_initial_input_or_transfer_cannot_borrow_complete_sibling',
        'test_execution_async_initial_control::test_budget_one_retains_each_actual_drive_port_and_session_target_without_true_prefix',
        'test_execution_async_initial_control::test_missing_fourth_return_adapter_input_cannot_borrow_earlier_item_or_sibling'])]
review = {
    'status': 'CONDITIONAL_SUPPLIED_MODEL_ACCEPTANCE', 'source_sha256': source,
    'original_requirements': ['docs/M1_PROTOCOL_FAMILY_PLAN.md:F16',
                              'docs/M1_REMAINING_PROTOCOL_PLAN.md:F16'],
    'closed_before': family['closed'], 'newly_closed': ['F16'],
    'closed_after': sorted((*family['closed'], 'F16')),
    'remaining_families': {key: value for key, value in family['remaining_other_families'].items() if key != 'F16'},
    'clauses': [{'condition': title, 'existing_selectors': [
        'tests/unit/' + item.split('::')[0] + '.py::' + item.split('::')[1]
        for item in selectors]} for title, selectors in clauses],
    'historical_family_ledger': 'family-obligations.json; exact prior bytes retained',
    'retained_unknown_boundaries': [
        'R3 exact COMPLETE/same R but four real opaque/write preservation blockers',
        'Main HOLD provenance and same B do not prove current occupancy content across unknown effects'],
    'not_new_requirements': 'No arbitrary native/source reconstruction and no F18/F19 closure inferred from a finite natural-Return host repair',
    'independent_review': 'independent-review.json',
    'acceptance_document': 'docs/M1_ASYNC_INITIAL_CONTROL_ACCEPTANCE.md',
    'automatic_source_recovery': False, 'source_runtime_verified': False,
    'transformation_authorized': False, 'p4_complete': False, 'p5_complete': False,
    'm0_m2_complete': False, 'tests_started': 0}
target = HERE / 'f16-review.json'
assert not target.exists()
target.write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps({'newly_closed': review['newly_closed'], 'closed_after': review['closed_after'],
                  'remaining': list(review['remaining_families']), 'source_sha256': source}))

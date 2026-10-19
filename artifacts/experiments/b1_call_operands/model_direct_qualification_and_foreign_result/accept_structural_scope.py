"""Match original structural clauses to the actual same-source final JUnit.

This script collects proof receipts, never executes tests or grants runtime
identity, source recovery, transformation permission or performance claims.
"""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
PRIOR = HERE.parent / 'model_await_reevaluation'

def S(module, name):
    return 'tests/unit/' + module + '.py::' + name

requirements = {
    'B': {
        'exact_lookup_call_qualification_and_all_failure_prefixes': [
            S('test_program_await_general', 'test_general_await_expands_real_lookup_call_qualification_and_iterator_return'),
            S('test_program_await_outcome_failures', 'test_lookup_call_and_bool_rejection_failures_keep_distinct_prefixes_and_slots'),
            S('test_execution_await_outcome_failures', 'test_expanded_failure_uses_exact_helper_completion_parent_raise_and_consumers')],
        'wrong_receiver_bool_path_and_parent_slot_rejected': [
            S('test_program_continuation_connections', 'test_await_call_cannot_use_same_typed_root_instead_of_its_lookup_result'),
            S('test_program_await_qualification_flow', 'test_an_unrelated_bool_cannot_supply_the_qualification_branch'),
            S('test_program_await_qualification_flow', 'test_a_side_check_cannot_qualify_the_path_that_bypasses_it'),
            S('test_execution_await_qualification_flow', 'test_captured_acceptance_of_known_bad_candidate_is_a_protocol_contradiction'),
            S('test_program_await_outcome_failures', 'test_parent_raise_packet_cannot_be_declared_from_a_state_completion_slot')],
        'missing_deletion_and_shared_budget_keep_original_obligations': [
            S('test_execution_await_failure_cleanup', 'test_missing_one_instances_bridge_never_uses_the_siblings_helper_or_current_packet'),
            S('test_execution_await_outcome_failures', 'test_deleted_source_raise_row_and_receipt_do_not_delete_its_dynamic_obligation'),
            S('test_execution_await_outcome_failures', 'test_budget_cut_keeps_static_failure_denominator_and_cursor')],
    },
    'C': {
        'zero_cut_own_normal_raise_packet_state_and_consumer': [
            S('test_program_await_outcomes', 'test_conversion_and_extraction_keep_own_normal_and_raised_payloads_separate'),
            S('test_execution_await_outcomes', 'test_actual_completion_packet_and_final_value_stay_in_their_exact_instance'),
            S('test_execution_await_outcomes', 'test_actual_extractor_raise_uses_its_own_packet_after_the_selected_constructor_leg')],
        'wrong_result_missing_use_and_metadata_deletion': [
            S('test_program_await_outcomes', 'test_same_typed_entry_reference_cannot_replace_the_final_extractors_own_result'),
            S('test_execution_await_outcomes', 'test_missing_exact_extractor_use_does_not_borrow_the_sibling_instance'),
            S('test_execution_await_outcomes', 'test_deleting_final_metadata_keeps_captured_consumer_and_its_static_outcome_key'),
            S('test_program_await_outcomes', 'test_budget_one_preserves_all_original_drive_successors_and_unknown_job_total')],
    },
    'D': {
        'handoff_persistent_body_exact_resume_and_final_normal_raise': [
            S('test_program_await_outcomes', 'test_two_cut_handoff_keeps_its_original_export_without_final_extraction'),
            S('test_execution_await_general_final', 'test_general_acquisition_before_start_owns_the_persistent_body_and_real_final_chain'),
            S('test_execution_await_pipeline_reexecution', 'test_two_round_pipeline_keeps_source_body_kind_fullslots_and_current_consumer'),
            S('test_program_continuation_connections', 'test_parent_resume_binds_the_actual_non_state_slot_without_guessing_from_flavor')],
        'old_resume_state_and_other_child_slots_rejected': [
            S('test_execution_await_resume', 'test_old_cut_cannot_be_used_as_the_second_resume_ingress'),
            S('test_execution_resumable_links', 'test_old_state_incarnation_cannot_replace_the_new_resume_formal'),
            S('test_program_await_shared_final', 'test_exact_left_result_slot_cannot_supply_the_right_callers_private_output')],
        'missing_transfer_child_and_budget': [
            S('test_execution_resumable_links', 'test_missing_temporal_transfer_keeps_saved_sources_and_the_exact_missing_ingress_gap'),
            S('test_execution_await_final_regions', 'test_missing_nested_child_call_keeps_its_frame_and_does_not_borrow_sibling_instance'),
            S('test_program_await_outcomes', 'test_budget_one_preserves_all_original_drive_successors_and_unknown_job_total')],
    },
    'F': {
        'wrapper_constructor_getter_held_body_distinctness_and_complete_final_slots': [
            S('test_program_await_wrapper', 'test_native_wrapper_has_real_constructor_getter_and_nested_driver_ports'),
            S('test_execution_await_wrapper', 'test_explicit_native_wrapper_routes_distinct_w_to_held_b_without_copy_union'),
            S('test_execution_await_wrapper_final', 'test_native_wrapper_two_instances_reach_their_own_current_final_ports')],
        'wrong_scoped_identity_expected_body_constructor_and_state': [
            S('test_execution_await_wrapper', 'test_native_wrapper_cannot_declare_w_and_b_the_same_scoped_object'),
            S('test_execution_await_wrapper', 'test_another_true_create_of_the_same_body_cannot_replace_wrappers_expected_b'),
            S('test_program_await_wrapper', 'test_wrapper_projection_cannot_switch_original_constructor_getter_or_state')],
        'missing_owner_call_getter_and_budget_keep_original_inventory': [
            S('test_execution_await_wrapper', 'test_missing_association_retains_original_constructor_and_drive_obligations'),
            S('test_execution_await_wrapper', 'test_missing_inner_call_never_guesses_the_only_visible_driver_activation'),
            S('test_execution_await_wrapper', 'test_uncaptured_getter_preserves_source_and_never_invents_a_native_b_read'),
            S('test_execution_await_wrapper', 'test_wrapper_tiny_budget_keeps_inventory_masks_unchecked_projections_and_has_cursor')],
    },
    'F15': {
        'same_generator_coroutine_direct_await_persistent_body_and_current_results': [
            S('test_program_await_resume', 'test_two_cut_direct_and_await_calls_share_one_original_body_and_keep_final_extraction'),
            S('test_execution_await_resume', 'test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction'),
            S('test_execution_await_outcomes', 'test_actual_completion_packet_and_final_value_stay_in_their_exact_instance'),
            S('test_execution_await_pipeline_reexecution', 'test_two_round_pipeline_keeps_source_body_kind_fullslots_and_current_consumer')],
        'wrapper_is_not_a_type_based_body_copy': [
            S('test_program_await_wrapper', 'test_wrapper_projection_cannot_switch_original_constructor_getter_or_state'),
            S('test_execution_await_wrapper', 'test_another_true_create_of_the_same_body_cannot_replace_wrappers_expected_b')],
        'ordinary_generator_legality_is_distinct_from_self_await_eligibility': [
            S('test_program_await_direct_qualification', 'test_generator_coroutine_self_await_keeps_get_body_return_and_both_final_completions'),
            S('test_program_await_direct_qualification', 'test_ordinary_generator_next_is_a_legal_body_drive_without_self_await_qualification'),
            S('test_program_await_direct_qualification', 'test_known_ordinary_generator_cannot_continue_as_a_direct_self_await_source')],
        'other_real_drive_adapter_result_not_current_result': [
            S('test_program_await_foreign_drive_result', 'test_two_real_drives_keep_their_own_final_adapter_reference_results'),
            S('test_program_await_foreign_drive_result', 'test_another_drives_same_typed_adapter_own_result_cannot_replace_current_final_result')],
        'missing_current_source_and_shared_budget': [
            S('test_execution_await_source_visits', 'test_missing_get1_input_or_selected_transfer_keeps_both_sources_without_borrowing_get0'),
            S('test_execution_await_source_visits', 'test_repeated_source_inventory_survives_shared_budget_and_detached_requery')],
    },
}
requirements['F13'] = {**requirements['D'],
    'zero_cut_and_final_slot_semantics': requirements['C']['zero_cut_own_normal_raise_packet_state_and_consumer']}


def evaluate():
    result = json.loads((HERE / 'verified-final/result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    rows = tuple(ET.parse(HERE / 'verified-final/junit.xml').iter('testcase'))
    assert rows and all(not any(row.find(tag) is not None
        for tag in ('failure', 'error', 'skipped')) for row in rows)
    current = {(row.get('classname'), row.get('name')) for row in rows}
    extra = json.loads((HERE / 'extra-source-spec.json').read_text())
    assert set(extra) == {'A', 'F12'}
    combined = {**requirements, **extra}
    found = {}
    for group, roles in combined.items():
        found[group] = {}
        for role, selectors in roles.items():
            evidence = {}
            for selector in selectors:
                filename, name = selector.split('::')
                classname = filename.removesuffix('.py').replace('/', '.')
                matches = sorted(item for item in current if item[0] == classname
                    and (item[1] == name or item[1].startswith(name + '[')))
                assert matches, (group, role, selector)
                evidence[selector] = [list(item) for item in matches]
            assert evidence
            found[group][role] = evidence
    contracts = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'docs/M1_AWAIT_ACQUISITION_PLAN.md', 'docs/M1_AWAIT_COMPOSITION_PLAN.md',
        'docs/M1_REMAINING_PROTOCOL_PLAN.md')}
    return {'status': 'CONDITIONAL_ORIGINAL_A_H_AND_F12_F13_F15_STRUCTURAL_ACCEPTANCE',
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(rows),
        'original_contracts': contracts, 'required_clauses': combined, 'executed_evidence': found,
        'previous_closed_A_H': ['E', 'G', 'H'], 'closed_A_H': list('ABCDEFGH'),
        'previous_closed_families': ['F17', 'F21', 'F23'],
        'closed_families': ['F12', 'F13', 'F15', 'F17', 'F21', 'F23'],
        'tests_started_by_reconciliation': 0, 'whole_program_model_complete': False,
        'source_runtime_verified': False, 'transformation_authorized': False, 'new_lewm_speedup': False}


def write_acceptance(record):
    path = HERE / 'structural-acceptance.json'
    assert not path.exists()
    ledger_path = HERE / 'original-obligations.json'
    ledger = json.loads(ledger_path.read_text())
    assert ledger['closed'] == ['E', 'G', 'H']
    ledger['previous_closed'] = record['previous_closed_A_H']
    ledger['closed'] = record['closed_A_H']
    ledger['retained_acceptance_archive'] = '../model_await_reevaluation/original-scope-audit.json'
    for row in ledger['rows']:
        group = row['id']
        if group not in requirements and group != 'A':
            continue
        row['previous_remaining'] = row['remaining']
        row['remaining'] = None
        selectors = tuple(selector for values in record['required_clauses'][group].values() for selector in values)
        row['existing_selectors'] = list(dict.fromkeys((*row['existing_selectors'], *selectors)))
        row['acceptance'] = 'structural-acceptance.json; original clause/actual same-source JUnit reconciliation'
    ledger['scope'] = 'Original await A-H conditional supplied-model structure accepted by exact original clauses; source/runtime/transform and remaining families separate'
    families_path = HERE / 'family-obligations.json'
    families = json.loads(families_path.read_text())
    assert families['closed'] == record['previous_closed_families']
    families['previous_closed'] = record['previous_closed_families']
    families['closed'] = record['closed_families']
    for group in ('F12', 'F13', 'F15'):
        previous = families['remaining_other_families'].pop(group)
        selectors = tuple(selector for values in record['required_clauses'][group].values() for selector in values)
        families['reviewed'].append({'id': group, 'existing_selectors': list(dict.fromkeys(selectors)),
            'remaining': None, 'previous_remaining': previous})
    families['scope'] = 'Original16 family denominator; F12/F13/F15 accepted by exact clause evidence, F17/F21/F23 retained; ten others open'
    families['other_A_H_complete'] = True
    families['remaining_scope_review'] = 'structural-acceptance.json and docs/M1_AWAIT_SOURCE_FAMILY_ACCEPTANCE.md'
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
    families_path.write_text(json.dumps(families, indent=2) + '\n')
    path.write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    record = evaluate()
    if sys.argv[1:] == ['--write']:
        write_acceptance(record)
    else:
        assert sys.argv[1:] == ['--check']
        assert record == json.loads((HERE / 'structural-acceptance.json').read_text())
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'focused_cases', 'closed_A_H', 'closed_families',
        'whole_program_model_complete', 'tests_started_by_reconciliation')}, indent=2))

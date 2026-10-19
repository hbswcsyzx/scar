"""Root-only original E/H structural reconciliation; starts no tests.

Requires the actual green final run and retains every old ledger row and
selector. The original family denominator and all unrelated scopes stay open.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()

def select(module, name):
    return 'tests/unit/' + module + '.py::' + name

S = select
requirements = {
    'E': {
        'same_generator_coroutine_direct_and_await': [
            S('test_program_await_resume', 'test_two_cut_direct_and_await_calls_share_one_original_body_and_keep_final_extraction'),
            S('test_execution_await_resume', 'test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction')],
        'selected_current_final_value_exception_and_state': [
            S('test_execution_await_outcomes', 'test_actual_completion_packet_and_final_value_stay_in_their_exact_instance'),
            S('test_execution_await_pipeline_reexecution', 'test_two_round_pipeline_keeps_source_body_kind_fullslots_and_current_consumer')],
        'same_code_multiple_creates': [
            S('test_execution_await_resume', 'test_two_same_code_creates_do_not_select_the_other_body_origin'),
            S('test_execution_await_resume', 'test_repeated_root_evaluation_never_borrows_a_sibling_body_activation')],
        'old_resume_and_other_drive_rejected_by_core': [
            S('test_execution_await_resume', 'test_old_cut_cannot_be_used_as_the_second_resume_ingress'),
            S('test_execution_await_resume', 'test_same_body_does_not_allow_another_drive_entry_and_outcome')],
        'old_state_rejected_by_shared_core': [
            S('test_execution_resumable_links', 'test_old_state_incarnation_cannot_replace_the_new_resume_formal'),
            S('test_execution_flow', 'test_loop_rejects_old_result_and_old_state_from_same_static_definition')],
        'same_body_multiple_gets_and_real_pipeline_reexecution': [
            S('test_execution_await_source_visits', 'test_same_static_get_visits_select_the_actual_own_result_not_latest_or_common_b'),
            S('test_execution_await_pipeline_reexecution', 'test_same_caller_backedge_recreates_zero_cut_self_pipeline_and_uses_each_round_child_result')],
    },
    'H': {
        'prepared_index_flow_reuse': [
            S('test_program_connection_flow', 'test_prepared_query_does_not_construct_a_second_program_index'),
            S('test_program_input_origin_pairs', 'test_origin_route_indexes_are_built_once_and_reused_across_source_and_joint_queries'),
            S('test_execution_composition_refresh', 'test_refresh_keeps_canonical_and_external_gaps_without_sharing_mutable_derived_maps')],
        'budget_one_original_denominators_cursor': [
            S('test_program_await_outcomes', 'test_budget_one_preserves_all_original_drive_successors_and_unknown_job_total'),
            S('test_execution_await_pipeline_reexecution', 'test_shared_budget_retains_both_round_anchors_and_all_original_outcome_keys')],
        'same_budget_late_joins': [
            S('test_execution_await_outcomes', 'test_late_budget_exhaustion_never_reports_a_complete_tail_or_unchecked_compatibility'),
            S('test_program_await_raise_continuations', 'test_budget_ending_after_complete_walker_does_not_exclude_unjoined_parent_legs'),
            S('test_execution_await_source_visits', 'test_repeated_source_inventory_survives_shared_budget_and_detached_requery')],
        'bounded_exact_copy_ancestry': [
            S('test_execution_await_outcome_boundaries', 'test_each_conversion_packet_is_joined_to_its_exact_terminal_before_parent_delivery'),
            S('test_program_copy_consumer_budget_work', 'test_budget_one_stops_before_query_time_callee_return_join'),
            S('test_execution_await_source_visits', 'test_history_port_budget_exhaustion_preserves_cached_current_false_as_nested_receipt')],
        'fresh_catalog_snapshot_detached_reports': [
            S('test_execution_await_wrapper', 'test_wrapper_query_detaches_returns_and_rechecks_a_changed_external_identity_catalog'),
            S('test_execution_body_values', 'test_query_rechecks_mutable_external_value_artifact_instead_of_using_old_denotations'),
            S('test_execution_await_pipeline_reexecution', 'test_detached_results_and_fresh_external_catalog_keep_each_round_source')],
        'reexecution_original_occurrences': [
            S('test_execution_await_source_visits', 'test_same_static_get_visits_select_the_actual_own_result_not_latest_or_common_b'),
            S('test_execution_await_pipeline_reexecution', 'test_two_round_pipeline_keeps_source_body_kind_fullslots_and_current_consumer')],
        'whole_deletion_preserves_original_obligations': [
            S('test_execution_await_outcome_boundaries', 'test_whole_capture_deletion_keeps_static_outcome_and_failure_keys'),
            S('test_execution_await_pipeline_reexecution', 'test_deleting_all_body_links_keeps_both_reexecuted_advances_and_outcome_denominators')],
        'missing_capture_is_not_budget_exhaustion': [
            S('test_execution_await_inventory', 'test_wholly_missing_capture_preserves_source_and_never_invents_a_drive')],
    },
}


def evaluate():
    result = json.loads((HERE / 'verified-final/result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    rows = tuple(ET.parse(HERE / 'verified-final/junit.xml').iter('testcase'))
    assert len(rows) == 1845
    assert all(not any(row.find(tag) is not None for tag in ('failure', 'error', 'skipped')) for row in rows)
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    reports = {}
    for scope, clauses in requirements.items():
        checked = {}
        for clause, selectors in clauses.items():
            evidence = {}
            for selector in selectors:
                filename, name = selector.split('::')
                classname = filename.removesuffix('.py').replace('/', '.')
                matches = sorted(identity for identity in identities if identity[0] == classname
                    and (identity[1] == name or identity[1].startswith(name + '[')))
                assert matches, selector
                evidence[selector] = [list(identity) for identity in matches]
            checked[clause] = evidence
        reports[scope] = checked
    contracts = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'docs/M1_AWAIT_ACQUISITION_PLAN.md', 'docs/M1_AWAIT_COMPOSITION_PLAN.md')}
    record = {'status': 'CONDITIONAL_M1_E_H_STRUCTURAL_ACCEPTANCE',
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(rows),
        'original_contracts': contracts, 'required_clauses': reports,
        'previous_closed_A_H': ['G'], 'newly_closed_A_H': ['E', 'H'],
        'closed_A_H': ['E', 'G', 'H'], 'remaining_A_H': ['A', 'B', 'C', 'D', 'F'],
        'remaining_family_count': 13, 'f15_complete': False,
        'f15_exact_remaining': [
            'known ordinary GENERATOR must not acquire direct/self await qualification in a core-valid model',
            'another Drive adapter result cannot substitute the required final result; wrong O association or helper result is not that exact test'],
        'tests_started_by_reconciliation': 0, 'program23_execution8_unchanged': True,
        'whole_program_model_complete': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': False}
    return record


if __name__ == '__main__':
    import sys
    record = evaluate()
    path = HERE / 'original-scope-audit.json'
    ledger_path = HERE / 'original-obligations.json'
    if sys.argv[1:] == ['--write']:
        assert not path.exists()
        ledger = json.loads(ledger_path.read_text())
        assert ledger['closed'] == ['G']
        ledger['previous_closed'] = ledger['closed']
        ledger['closed'] = record['closed_A_H']
        for row in ledger['rows']:
            if row['id'] not in ('E', 'H'):
                continue
            row['previous_remaining'] = row['remaining']
            selectors = tuple(selector for values in requirements[row['id']].values() for selector in values)
            row['existing_selectors'] = list(dict.fromkeys((*row['existing_selectors'], *selectors)))
            row['remaining'] = None
            row['acceptance'] = 'original-scope-audit.json; exact original clauses, not source/native authority or arbitrary products'
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
        path.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert record == json.loads(path.read_text())
        ledger = json.loads(ledger_path.read_text())
        assert ledger['previous_closed'] == ['G'] and ledger['closed'] == record['closed_A_H']
        for row in ledger['rows']:
            if row['id'] in ('E', 'H'):
                assert row['remaining'] is None and row['previous_remaining']
                assert {selector for values in requirements[row['id']].values() for selector in values} <= set(row['existing_selectors'])
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'focused_cases', 'closed_A_H', 'f15_complete', 'tests_started_by_reconciliation')}, indent=2))

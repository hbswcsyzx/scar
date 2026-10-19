"""Freeze exact A/F12 selectors after authors freeze; starts no tests."""
import json
from pathlib import Path
import runpy
HERE = Path(__file__).resolve().parent
spec = runpy.run_path(str(HERE / 'accept_structural_scope.py'))
S = spec['S']
requirements = spec['requirements']
a = {
    'native_coroutine_self_no_wrapper_complete_definition_and_supplied_capture': [
        S('test_program_await_native_and_general_sources', 'test_native_coroutine_self_no_wrapper_has_a_complete_zero_cut_supplied_chain')],
    'generator_coroutine_self_and_ordinary_generator_not_confused': [
        S('test_program_await_direct_qualification', 'test_generator_coroutine_self_await_keeps_get_body_return_and_both_final_completions'),
        S('test_program_await_direct_qualification', 'test_ordinary_generator_next_is_a_legal_body_drive_without_self_await_qualification'),
        S('test_program_await_direct_qualification', 'test_known_ordinary_generator_cannot_continue_as_a_direct_self_await_source')],
    'general_lookup_call_and_ordinary_generator_return_accepted': [
        S('test_program_await_general', 'test_general_await_expands_real_lookup_call_qualification_and_iterator_return'),
        S('test_program_await_acquisition', 'test_general_await_normal_result_can_be_a_known_generator_iterator'),
        S('test_program_await_qualification_flow', 'test_generator_candidate_keeps_the_same_check_and_can_accept')],
    'known_bad_general_coroutine_generator_coroutine_and_builtin_returns_rejected': [
        S('test_program_await_acquisition', 'test_general_await_cannot_return_a_known_generator_coroutine_handle'),
        S('test_program_await_native_and_general_sources', 'test_general_await_known_coroutine_return_cannot_be_continued_as_an_iterator'),
        S('test_program_await_native_and_general_sources', 'test_general_await_exact_builtin_return_cannot_be_continued_as_an_iterator')],
    'unknown_return_is_not_known_bad_and_source_deletion_budget_preserve_obligations': [
        S('test_program_await_qualification_flow', 'test_unknown_method_result_does_not_make_its_accepting_path_infeasible'),
        S('test_program_await_native_and_general_sources', 'test_general_await_exact_builtin_return_cannot_be_continued_as_an_iterator'),
        S('test_execution_await_general_final', 'test_missing_first_acquisition_join_or_completion_cannot_borrow_the_other_instance'),
        S('test_execution_await_general_final', 'test_tiny_budget_retains_canonical_source_and_marks_unchecked_actual_chain')],
    'explicit_wrapper_keeps_its_distinct_owner_and_source': requirements['F']['wrapper_constructor_getter_held_body_distinctness_and_complete_final_slots'],
}
record = {'A': a, 'F12': {**a, **requirements['B']}}
path = HERE / 'extra-source-spec.json'
assert not path.exists()
path.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'groups': list(record), 'original_rows_preserved': True, 'tests_started': 0}))

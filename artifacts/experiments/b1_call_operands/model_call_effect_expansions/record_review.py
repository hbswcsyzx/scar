"""Freeze completed read-only reviews after the actual final run; start no tests."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
destination = HERE / 'independent-review.json'
scope_destination = HERE / 'remaining-source-review.json'
assert not destination.exists() and not scope_destination.exists()
result = json.loads((HERE / 'verified-final/result.json').read_text())
source_hash, sources = fingerprint()
assert result['returncode'] == 0 and result['source_unchanged']
assert result['source_sha256_before'] == result['source_sha256_after'] == source_hash
products = tuple('scar/ir/' + path for path in (
    'program/__init__.py', 'program/model.py', 'program/validation.py',
    'program/queries.py', 'program/codec.py', 'execution/state_preservation.py',
    'execution/flow.py', 'program/call_effect_expansion.py'))
fixtures = tuple('tests/fixtures/' + path + '.py' for path in (
    'program_call_effect_expansion_graphs', 'execution_call_effect_expansion_graphs'))
tests = tuple('tests/unit/' + path + '.py' for path in (
    'test_program_call_effect_expansion', 'test_program_call_effect_expansion_codec',
    'test_execution_call_effect_expansion'))
supplements = {
    'docs/M1_CALL_EFFECT_EXPANSION_TEST_PREMISE.md': '034e4b4dffad7e5ed7a3cce597d1f289be0ba5075944ede62f29db4146382a85',
    'docs/M1_CALL_EFFECT_EXPANSION_STATE_FLOW.md': 'aebc6a49d6cc18af279c01530bd248bfea9049fca984c742cd9910cf7aa9844e'}
for path, expected in supplements.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
remaining = (
    ('F18', '/root/cleanup_forward_review', (
        'test_program_async_connections.py::test_real_async_association_gate_source_and_session_use_original_ports[value-ASYNC_YIELD]',
        'test_program_async_connections.py::test_real_async_association_gate_source_and_session_use_original_ports[packet-ASYNC_YIELD]',
        'test_program_async_connections.py::test_async_return_cannot_publish_a_known_non_none_payload_as_natural_completion'),
     'Natural Return/Raise use exact Drive/session sources; known non-None natural completion is rejected.',
     'Active StopIteration/StopAsyncIteration classification through RuntimeError adapter own N/R and actual consumer is not reconciled; async fixed profile currently lists only yield/natural-return adapters.'),
    ('F19', '/root/cleanup_forward_review', (
        'test_program_async_connections.py::test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state[THROW]',
        'test_program_async_connections.py::test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state[CLOSE]',
        'test_program_async_connections.py::test_suspended_body_is_not_finished_when_its_async_request_completes'),
     'Latent THROW/CLOSE normalizer own packets and failure state are linked; request completion cannot release unfinished body.',
     'Asyncgen-specific same-body versioned closed athrow/aclose and ignored-GeneratorExit retry chain is not reconciled; generic coroutine/generator cases do not replace it.'),
    ('F20', '/root/cleanup_forward_review', (
        'test_program_continuation_connections.py::test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct',
        'test_program_method_lookup_connections.py::test_expanded_initial_next_uses_lookup_iterator_not_bound_method_as_marker',
        'test_program_continuation_connections.py::test_initial_advance_cannot_be_reused_after_a_real_advance_backedge'),
     'GetIterator/advance N/R, item/extraction, independent iterator marker and backedge rejection exist. Old missing-method-lookup wording is obsolete.',
     'Source expression own N/R to GetIterator and invalid-iterator/first exhaustion actual consumers remain to reconcile; expanded initial-next still explicitly reports continuation_source_unresolved.'),
    ('F22', '/root/value_resource_review', (
        'test_program_method_lookup_connections.py::test_bound_throw_call_still_uses_every_original_raw_ordinal',
        'test_program_lookup_fallback.py::test_throw_fallback_preserves_all_original_normal_method_arguments_and_independent_e0',
        'test_program_continuation_connections.py::test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct'),
     'Ordered raw THROW arities, distinct original/lookup/matcher packets and delegate item/error frontiers exist.',
     'Same-source THROW through this delegate item/exhaustion/missing method to actual parent resume or lawful no-resume is not reconciled; fallback frontier_only is not whole-chain evidence.'),
    ('F24', '/root/value_resource_review', (
        'test_program_async_connections.py::test_cancel_call_injection_handling_and_final_status_are_distinct_original_sites',
        'test_program_async_connections.py::test_current_waiter_result_is_not_assumed_to_be_the_parent_body_without_forwarding',
        'test_program_async_connections.py::test_deleting_cancel_relations_does_not_delete_request_delivery_handler_status_denominator'),
     'Request, packet/target, handler or terminal and independent status consumers exist; missing relation preserves original denominator.',
     'Caught fixture currently returns directly: suppression followed by another AWAIT/C1 Replace and CURRENT_AWAITED forwarding/callback actual chain remain missing.'),
    ('X25', '/root/await_wrapper_chain', (
        'test_program_pending_cleanup.py::test_active_c1_pending_payload_crosses_two_cuts_to_the_original_host_raise',
        'test_resumption_forwarding.py::test_binding_saved_actuals_keep_same_slot_bound_facts_in_validation_and_query',
        'test_cleanup_forward.py::test_loop_self_carries_pending_context_and_fresh_pack_without_losing_seed'),
     'Two-cut pending/context/delegate, local binding preservation and loop-carried pending/context/fresh facts each exist.',
     'The same active C1/two-cut/loop-merge combination with LOCAL_BINDING and current pending/context/delegate is not reconciled; no new canonical field identified by finite review.'),
    ('X26', '/root/await_wrapper_chain', (
        'test_lifecycle_body_composition.py::test_actual_cleanup_return_and_raise_frontier_keep_independent_terminal_sources',
        'test_lifecycle_body_composition.py::test_real_helper_normal_and_raise_use_each_current_partial_poststate',
        'test_lifecycle_cleanup_composition.py::test_session_post_is_current_only_and_real_helper_normal_reseeds_it'),
     'Original normal/raise terminal sources, partial poststates, session kill/reseed and release of exact commits exist.',
     'Async/cancel terminal paths are not reconciled into one publication-to-same-body-history-to-current-state-to-release chain. Request completion or ASYNC_YIELD does not supply it.'),
    ('X27', '/root/await_wrapper_chain', (
        'test_execution_resumable_links.py::test_persistent_body_start_and_resume_keep_every_original_port_and_selected_outcome',
        'test_execution_delegate_close_continuations.py::test_missing_close_parent_occurrence_cannot_borrow_the_complete_sibling',
        'test_execution_await_pipeline_reexecution.py::test_second_round_missing_capture_never_borrows_the_complete_first_round'),
     'Persistent activation/entry/outcome/full ports and exact missing-parent/sibling/reexecution negatives exist.',
     'Remaining delegation/cancellation families need their own actual source-to-call/delivery-to-parent/no-parent-to-consumer joins. Existing occurrence fields should be reused.'))
current_cases = {(row.get('classname'), row.get('name'))
                 for row in ET.parse(HERE / 'verified-final/junit.xml').iter('testcase')}
scope_rows = []
scope_sources = {'scar/ir/program/protocol_rules.py', 'tests/fixtures/program_async_connections.py'}
for family, reviewer, selectors, covered, residual in remaining:
    entries = []
    for selector in selectors:
        path, name = ('tests/unit/' + selector).split('::')
        assert path in sources
        assert 'def ' + name.split('[')[0] + '(' in Path(path).read_text(), selector
        scope_sources.add(path)
        module = path.removesuffix('.py').replace('/', '.')
        actual = sorted(identity for identity in current_cases if identity[0] == module
                        and (identity[1] == name or identity[1].startswith(name + '[')))
        if any(identity[0] == module for identity in current_cases):
            assert actual, selector
        entries.append({'selector': path + '::' + name, 'current_final_cases': actual,
                        'current_final_retested': bool(actual)})
    scope_rows.append({'id': family, 'reviewer': reviewer, 'status': 'OPEN_SOURCE_REVIEW_ONLY',
                       'covered_in_source': covered, 'residual_assessment': residual,
                       'evidence': entries})
scope_destination.write_text(json.dumps({
    'source_sha256': source_hash, 'kind': 'READ_ONLY_SOURCE_REVIEW_NOT_FAMILY_ACCEPTANCE',
    'rows': scope_rows, 'source_hashes': {path: sources[path] for path in sorted(scope_sources)},
    'F16_reference': 'family-obligations.json:F16_current_scope_review',
    'all_nine_families_remain_open': True, 'newly_closed': [], 'tests_started': 0,
    'note': 'Empty current_final_cases means source/historical evidence only; do not claim it was retested in this run. No new canonical field was identified for X25-X27 by this finite review.'}, indent=2) + '\n')
review = {
    'source_sha256': source_hash,
    'all_authors_frozen': True,
    'interpreters_started_by_reviewers': 0,
    'reviewed_sources': {path: sources[path] for path in (*products, *fixtures, *tests)},
    'frozen_supplements': supplements,
    'reviewers': {
        '/root/cleanup_forward_review': {
            'scope': 'New record/validation; final ordinary CALL state/current update and precise state-preservation read-only review.',
            'result': 'No remaining concrete blocker identified by finite source review; final same-source runtime evidence belongs to root.',
            'frozen': True},
        '/root/value_resource_review': {
            'scope': 'Program25 and exact old-test migration; final flow/preservation read-only review; next-gate documentation.',
            'result': 'No remaining concrete false-to-true counterexample; candidate CALL with StateAccess withdrawn because existing core validation forbids the shape.',
            'frozen': True},
        '/root/await_wrapper_chain': {
            'scope': 'New original CFG and actual capture fixtures,13 dynamic cases; corrected first JUMP use fault; strengthened current-state assertions.',
            'result': 'New actual occurrences, N/R slots and effect inventories preserved; supplied relation is not source/runtime proof.',
            'frozen': True},
        '/root': {
            'scope': 'Integration across all listed sources, frozen contracts, exact baseline subclass probe, actual serial attempts and before/after probes.',
            'result': '45 new directed tests passed; final related run completed on same frozen source; original scope remains open.'}},
    'test_premise_correction': 'The baseline public ProgramGraph subclass was already rejected by address_graph; only the new test premise was corrected. Existing address validation was unchanged.',
    'real_model_defect': 'Ordinary CALL StateVersion results did not advance dynamic current. Update from actual result and kill old current on missing capture; preserve INVOKE/BodyDrive EDGE semantics.',
    'independent_invalid_counterexample_withdrawn': 'Ordinary CALL StateAccess is forbidden by program/validation.py call_access; do not change product for a non-model shape.',
    'whole_program_scope_review': {
        'reviewer': '/root/await_wrapper_chain',
        'tests_started': 0,
        'result': 'Current repairs serve cross-layer dependencies, but supplied graphs cannot replace automatic recovery. Reconcile original nine families/P5/113 constructs196 fields without inventing a Cartesian-product test mandate or requiring all native Unknown to vanish.',
        'next_bounded_automatic_delivery': 'After original M0-M2 and user explanation: entry-driven two-file Python shell plus one FX/Export region; no manual IR/slot mapping; preserve original ports/state/ordered uses and exact missing-evidence gaps.',
        'design_references': {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (
            'docs/WHOLE_PROGRAM_MODEL.md', 'docs/MODELING_REUSE_DECISION.md',
            'docs/MODELING_INTEGRATION.md', 'docs/M1_CALL_EFFECT_EXPANSION_NEXT_GATE.md')}},
    'automatic_source_recovery': False,
    'transformation_authorized': False,
    'p4_complete': False,
    'tests_started': 0}
destination.write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps({'review_sources': len(review['reviewed_sources']), 'source_sha256': source_hash, 'tests_started': 0}))

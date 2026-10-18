"""Write the owned midpoint ledger from already recorded evidence; no tests."""
from pathlib import Path
import hashlib
import json

root = Path.cwd()
here = root / 'artifacts/experiments/b1_call_operands/model_remaining_protocols/continuations'
paths = (
    'scar/ir/program/protocol_continuations.py',
    'tests/fixtures/program_continuation_graphs.py',
    'tests/fixtures/program_continuation_cleanup_graphs.py',
    'tests/unit/test_program_continuation_connections.py',
    'scar/ir/program/protocol_connection_flow.py',
    'scar/ir/program/protocol_connection_validation.py',
    'docs/M1_PROTOCOL_CONNECTION_CONTRACT.md',
    'docs/M1_PROTOCOL_FAMILY_PLAN.md',
    'docs/M1_REMAINING_PROTOCOL_PLAN.md',
)
hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
rows = [
('F12', 'await lookup/call/iterator validation, zero-suspension completion and protocol errors',
 ['test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct[await]',
  'test_await_call_cannot_use_same_typed_root_instead_of_its_lookup_result',
  'test_await_lookup_bound_method_is_not_the_iterator_returned_by_await_call',
  'test_await_iterator_cannot_replace_the_actual_extracted_expression_result'],
 'Real lookup N/R, own NORMAL bound method to a separate await call, own NORMAL iterator to delegate advance, extraction N/R and distinct final expression adapter/host consumers.',
 ['Explicit invalid iterator / plain generator eligibility and each distinct source failure branch.',
  'A native coroutine complete zero-suspension and suspension family graph, beyond the current language helper sites.']),
('F13', 'each scheduler handoff, exact resume iterator, and final expression/result',
 ['test_parent_resume_binds_the_actual_non_state_slot_without_guessing_from_flavor',
  'test_parent_slot_relation_deletion_preserves_the_original_required_slot',
  'test_parent_slot_cannot_borrow_another_same_typed_current_reference',
  'test_supplied_resume_rows_outside_the_canonical_slot_inventory_are_rejected'],
 'Eight exact nonSTATE slot/flavor combinations bind real processed sources through the gate and canonical BodyResume. BodyStart/nonDrive/missing/STATE row sites reject. Deleting rows retains original slot obligations.',
 ['A combined repeated scheduler handoff to final expression, not just one static resume boundary.',
  'New P3 dynamic occurrence combinations, actual current/saved inputs and outcomes for these language protocol sites.']),
('F14', 'coroutine phases, reentry/reuse, throw/close and actual poststates', [],
 'No new phase-complete coroutine graph is claimed by this owned batch.',
 ['Current phase predicate and exact branch through callback/reentry/reuse/throw/close consumers; preserve the whole parent denominator.']),
('F15', 'generator-coroutine direct driving and awaiting the same body; ordinary generator eligibility',
 ['test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct[wrapper]'],
 'Wrapper lookup/call own N/R and its iterator/extraction result consumers are explicit. This is a helper-site composition, not a complete body-family proof.',
 ['Same GENERATOR_COROUTINE body with both direct and await routes, rejecting wrong plain-generator eligibility and unrelated Drive outputs.']),
('F16', 'four async request kinds, association, first send, reuse/concurrency', [],
 'Outside owned continuation evidence; another owner handles async records and compositions. No uninspected test is credited.',
 ['Verify exact R/B/S/latent associations and all original async request variants in the integrated ledger.']),
('F17', 'AWAIT session HOLD versus ASYNC_YIELD item/request completion and body pause', [],
 'Outside owned continuation evidence; existing slot tests do not close session semantics.',
 ['Combine actual async outcomes and SessionUpdate with exact current state and request consumers.']),
('F18', 'async natural completion, active terminator exceptions and illegal source-level return', [],
 'No full async terminator family composition is claimed here.',
 ['Exact source rule and own N/R adapter outputs; retain active exception versus natural completion distinction.']),
('F19', 'closed/athrow/aclose and failure continuation relationships', [],
 'No native closed flag or host completion is treated as disappearance of a body continuation.',
 ['Version-scoped closed/failure routes and independent request/session/frame consumers in integrated evidence.']),
('F20', 'yield-from evaluation/GetIterator/first advance, zero parent suspension and initial failure',
 ['test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct[delegate]',
  'test_initial_advance_names_the_current_evaluation_instead_of_a_bare_initial_flag',
  'test_initial_advance_cannot_be_reused_after_a_real_advance_backedge'],
 'Real GetIterator own N/R, current iterator receiver, genuine advance N/R, initial marker tied to its evaluation, actual backedge counterexample. Delegate-only routes have no parent Drive/Attach/F.',
 ['Expanded independent method lookup stage remains a real typed rule/interface gap, not merely native applicability.',
  'Complete original source evaluation and invalid iterator/first exhaustion family graph, beyond the atomic helper boundary.']),
('F21', 'NEXT/SEND split, method lookup/call/result/current state and item/final consumers',
 ['test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct',
  'test_two_lookup_request_tuples_merge_upstream_of_the_real_send_call',
  'test_receiver_and_send_operand_cannot_come_from_opposite_merge_predecessors',
  'test_deleting_the_paired_call_attachment_keeps_both_selected_call_rows_required',
  'test_partial_single_guard_does_not_claim_the_other_merge_predecessor_was_checked'],
 'Raw trigger and ordered arguments, independent selected lookup result, two real lookup/request branches merged before an ordinary JUMP and actual call, complete receiver/argument tuple correlation and independent incoming inventory.',
 ['Independent bound-method lookup to call receiver is not yet a closed delegation rule.',
  'Missing-method branch and a dedicated reevaluated same-static-producer / stale carried result counterexample.']),
('F22', 'THROW original 1-3 arguments, missing method/failure/item/exhaustion, parent recovery',
 ['test_delegate_throw_keeps_each_original_raw_operand_and_order',
  'test_raw_throw_ordinals_cannot_be_reordered_even_when_all_references_have_the_same_type',
  'test_item_exhaustion_packet_and_state_are_not_interchangeable_metadata'],
 'Exact raw trigger and ordinals 0..arity-1, actual INVOKE arguments and selected item/reference versus exhaustion or failure packet, with metadata-only core-valid wrong-role examples.',
 ['Missing delegate.throw method to the exact original parent packet.',
  'Expanded method lookup, new versus original packet and complete family-specific cross-helper/caller tuple composition.']),
('F23', 'close NORMAL continues old GeneratorExit, RAISE overrides; pending/context and parent boundaries',
 ['test_close_normal_continues_old_injection_but_raise_overrides_with_own_packet',
  'test_close_none_normal_result_is_not_a_new_host_item_or_parent_exception',
  'test_close_normal_cannot_replay_a_different_same_typed_entry_packet',
  'test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace',
  'test_shared_cleanup_pending_cannot_use_close_none_or_lose_the_new_close_exception'],
 'Actual close N/R; own None is discarded, NORMAL continues independently supplied current injected packet, RAISE replaces it with exact own packet. Both real close completions merge into a shared fresh PendingRaise and original CleanupReplace using joint original-edge choices. Delegate-only has no parent Drive/Attach/F/release.',
 ['Raw CLOSE through a real GE normalizer and PacketDefinition in a local/noDriver helper.',
  'Raw THROW(GE) exact class-selected route and independent close-method lookup.',
  'No claim of parsed native GeneratorExit interpretation or inferred physical identity.']),
('F24', 'cancel request, actual delivery/handler, suppression/cleanup/re-await/final state', [],
 'Outside owned continuation evidence. Exception packets and ordinary close tests are not cancel proof.',
 ['Integrated exact delivery, current handler/context, selected continuation and session consumers from async owner evidence.']),
('X25', 'active C1 across at least two cuts, saved pending/context/delegate, local binding and current state',
 ['test_resume_source_connection_composes_with_active_cleanup_saved_pending_and_fresh_raise',
  'test_continuation_metadata_cannot_let_an_active_cleanup_private_token_escape_through_the_helper',
  'test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace'],
 'One real cut saves pending/context/frame (and delegate in the close fixture), precise resume sources and active caller formal, helper own N/R and shared fresh Replace. Private token escape is rejected by original core; packets and handled context stay on original SSA.',
 ['At least two real cuts with local binding, loop/merge and stale pending/context/delegate/state counterexamples.',
  'The one-cut positive and old C1 regressions cannot substitute for this original group.']),
('X26', 'terminal publication/session currentness, partial RAISE, narrow release versus broad helper', [],
 'This owned close helper does not grant F, session post, or terminal release. Its active C1 connection is not the full lifecycle composition.',
 ['New continuation protocol rows combined with actual BodyOutcomeCommit/NoBodyFinish, SessionUpdate kill/reseed, partial RAISE and TerminalFrameRelease owner/current-state guards.']),
('X27', 'these language protocols composed with P3 repeated Drive/persistent activation/actual entry/outcome', [],
 'All supplied owned graphs are static declaration fixtures. No new Execution O graph is constructed or claimed.',
 ['Actual occurrence compositions for these new sites with exact instance/capture/saved inputs/first outcome/current segment thread/run.',
  'Partial capture and deleted joins must retain consumer obligations; prior standalone P3 acceptance is not this group.']),
]
groups = [dict(group=i, status='OPEN', requirement=req, owned_tests=tests,
               observed=obs, remaining=remaining) for i,req,tests,obs,remaining in rows]
attempts = []
for directory in sorted(here.iterdir()):
    result = directory / 'result.json'
    if result.is_file():
        attempts.append({'path': str(directory.relative_to(root)), **json.loads(result.read_text())})
ledger = {
 'stage':'P4-2 intermediate implementation; not whole P4 acceptance',
 'status':'OPEN', 'denominator':{'count':16,'groups':[row['group'] for row in groups]},
 'owned_focused':{'directory':str((here/'attempt009').relative_to(root)), 'passed':52,
     'failed':0,'seconds_pytest':2.26,'exit':0,
     'source_fingerprint':'3af821cb7b9486a8f7b0befc89ed56747b3ef7dcb54abf91e79a7f9be5982459',
     'source_unchanged':True},
 'source_runtime_verified':False,'transformation_authorized':False,
 'sources':hashes,'groups':groups,'attempts':attempts,
 'scope_conditions':['Original core SSA/Use/CFG remain authoritative.',
    'Native/source applicability and dynamic identity are not proved by metadata.',
    'Shared derivation budgets do not bound snapshot/parser/FK/preparation or all CPU time.',
    'Atomic delegate helpers do not establish expanded bound-method lookup internals.',
    'No component/full/native probe ran in this owned batch.'],
}
(here/'P4-2-coverage.json').write_text(json.dumps(ledger,indent=2)+'\n')
lines = ['# P4-2 continuation coverage ledger', '',
 'Status: **OPEN**. All original F12–F24 and X25–X27 groups remain in the denominator. '
 'The final owned focused attempt is 52 PASS, not a claim that 16 groups or the complete P4 gate passed.', '',
 'Sources and exact tests are recorded in `P4-2-coverage.json`; the unit file is '
 '`tests/unit/test_program_continuation_connections.py`. Test labels below identify actual new compositions, '
 'not native Python behavior or complete source interpretation.', '']
for row in groups:
    lines += [f"## {row['group']} — OPEN", '', row['requirement']+'.', '',
       '**Observed owned connection:** '+row['observed'], '', '**Remaining required work:**', '']
    lines += ['- '+item for item in row['remaining']]
    lines += ['', '**New owned tests:** '+(', '.join('`'+item+'`' for item in row['owned_tests'])
              if row['owned_tests'] else 'No test is credited from outside this owned batch.'), '']
lines += ['## Fixed next implementation decisions', '',
 '- Add a minimal closed, independently expected delegate-method lookup stage/rule and its exact selected result to method-call receiver. Do not reuse AWAIT_LOOKUP or call an atomic helper expanded. Preserve raw ordinals, caller context, and branch tuple.',
 '- Complete raw close/GE and missing-method routes using original producer/packet/predicate/selected edge before claiming F21–F23.',
 '- Complete the original two-cut active C1/session/release and P3 occurrence combinations, including stale state, old packet, omitted relation, and partial capture negatives.',
 '- Retain coroutine eligibility/phase and same-wrapper-body direct/await obligations. The available generic graph is not a closed family protocol instance.', '',
 '## Source boundary', '',
 'All examples are supplied canonical ProgramGraphs. GetIterator/await/delegate source applicability, '
 'exception categories, runtime object identity and native method internals remain conditional. '
 'There is no second producer/state graph, fake RAW call argument, inferred GPU completion, backend, '
 'collector or workload speedup. M0–M2 and the parent full P4 gate are not declared complete.', '']
(here/'P4-2-coverage.md').write_text('\n'.join(lines))
(here/'source.final.json').write_text(json.dumps(hashes,indent=2)+'\n')

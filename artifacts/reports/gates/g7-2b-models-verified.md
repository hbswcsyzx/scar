# G7.2b-models independent criteria report

Status: **PASS**

Revision: `c7f68ce2474a3d995c410465def12ee19c86f48d`

Source digest: `17215bf8ad6c67c73ccde0cd0379335025d0a00fe42bc6bfd5a474331ab549ef`

| Criterion | Status |
| --- | --- |
| invocation_formal_actual_slot_registry_interval_scope_and_current_guard_join | PASS |
| source_replayed_control_insertion_zero_trip_exception_and_query_boundaries | PASS |
| fixed_identity_primitive_semantics_excludes_operand_dispatch_and_rejects_stale_forged_documents | PASS |
| new_comparison_boundaries_are_preserved_by_existing_import_analysis | PASS |
| public_nonexecuting_proof_models_roundtrip_source_invalidation_and_no_gpu_startup | PASS |

Scope: G7.2b Step 1 only: typed invocation-slot connections, source-replayed control/insertion models and fixed identity primitive semantics. This foundation gate does not accept G7.2b positive REUSE/MOTION or parent G7.

- Formal ports, actual reads, object/storage identity and logical versions remain distinct; an interface is not complete hidden-state or consumer closure.
- READ records are one sample per distinct slot, not a history of every read within a composite call. Registry guards describe the current event, not every earlier event.
- The current provenance registry has no Python object-only bool output representation; tensor storage is never fabricated for that purpose.
- Structured control-flow is bounded syntax evidence. Unsupported exception, context manager, iteration, suspension or class initialization behavior remains explicit; structural candidates do not authorize MOVE.
- A primitive identity certificate covers the is/is not operator itself and excludes operand evaluation, enclosing function effects and optimization legality.
- Q/runtime/debug/resource boundaries are required conditions, not accepted facts. REUSE/MOTION positive ledger proofs, guards/fallback, precise deltas and cost decisions remain pending.
- Source analysis and measurements do not execute or rewrite the target and are not workload acceleration evidence.

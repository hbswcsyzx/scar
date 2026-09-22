# G5 independent criteria report

Status: **PASS**

Revision: `4a0ae57467f689a63b2c843c943121bbd6e64cb6`

Source digest: `2f98b6b2fc3f115aa632c2b310b26921c877df457ffdc6170e8ef75ecf02bf77`

| Criterion | Status |
| --- | --- |
| source_loaded_code_witness_and_ambiguity | PASS |
| composite_boundary_coverage_and_residual_dependencies | PASS |
| q_profiles_and_concrete_requests | PASS |
| scope_domain_and_wire_counterexamples | PASS |
| raw_return_escape_and_exception_preservation | PASS |
| runtime_evidence_not_purity_or_alias_proof | PASS |
| import_constant_consumer_cannot_erase_init_effects | PASS |
| bounded_explicit_source_selection | PASS |
| public_inspection_end_to_end_no_execution_or_rewrite | PASS |

Scope: Read-only code-object correspondence, scoped composite effect queries, explicit Q policies and actionable evidence requests. No value equivalence, whole-program purity or transformation is inferred.

- Exact loaded-code hashes establish code_object_only correspondence; globals, closure, loader and parameter identity require separate evidence.
- All-path effect closure is possible only with explicit reviewed coverage; legacy dynamic traces remain open, and narrow target coverage is never promoted.
- G4 slot/provenance bindings stay explicit; generic automatic value slicing is part of G6.
- The import fixture supplies explicit module-init effect contracts; no automatic arbitrary import purity proof is claimed.
- No new detector/backend or target rewrite; satisfied effect removal is only one future proof obligation.
- Missing collector support or argv/cwd/environment remains a concrete CONTRACT request; no invented rerun command.

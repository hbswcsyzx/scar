# G7.1 independent criteria report

Status: **PASS**

Revision: `d5fe9cb69250a69d52b118386b765adf5162f8f2`

Source digest: `5c313478e1330757bfcc3155af871373dcabca8223deaddcb7f4ae98bbcebc27`

| Criterion | Status |
| --- | --- |
| typed_static_identity_literal_codec_scope_and_preconditions | PASS |
| source_operand_order_per_use_binding_and_snapshot_replay | PASS |
| independent_effect_control_namespace_and_forgery_counterexamples | PASS |
| fixed_builtin_derivations_resource_budgets_and_report_recomputation | PASS |
| public_nonexecuting_deterministic_semantics_command | PASS |

Scope: Source-version-bound typed computational semantics, per-use local bindings and bounded builtin constant type/content facts. This preparatory subgate does not accept G7 rewrite families, remove imports, select plans, invoke backends or measure workload speedup.

- Exact source bindings require explicit fresh/ordinary namespace and external-mutation preconditions; these remain required contracts, not observed facts.
- Exact binding propagation is restricted to supported straight-line scope; parameters, branch/loop merges, imports, descriptors, mutable containers and opaque dispatch retain concrete gaps.
- Constant facts establish builtin type/content under the semantic model, not object identity, effect freedom, control coverage or profitability.
- Source overlay authenticity requires replay; a structurally valid overlay or recomputed constant proof alone does not attest the target source.
- Evaluation budgets bound constant reasoning, not AST parsing and graph validation; module loading and user function execution are forbidden.
- No runtime LogicalVersion is fabricated for a static binding or expression. G7.2-G7.4 remain required before the G7 parent gate can pass.

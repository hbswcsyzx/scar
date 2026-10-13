# N1 independent criteria report

Status: **PASS**

Revision: `8179cca0b880f8e8e24607d7181587fbd85baad2`

Source digest: `561c618522f0de1f86558ea2b98e66dfe4b3b3d07d33def0b621ce74c40a1c96`

| Criterion | Status |
| --- | --- |
| typed_records_exact_literals_footprints_and_strict_wire_schema | PASS |
| whole_program_def_use_control_state_calls_and_payload_independent_structure | PASS |
| independent_adversarial_state_alias_binding_and_parallel_control_edges | PASS |
| persisted_graph_revalidation_and_tamper_rejection | PASS |
| public_cli_checks_structure_without_execution_or_transformation_authority | PASS |

Scope: Typed program entities, exact uses, bounded synchronous control/state interfaces, strict persistence and a public graph checker, exercised with complete manually constructed program graphs. This is structural validation, not source recovery, effect proof or optimization approval.

- Inputs are manually constructed IR declarations. effects_complete is a declaration, never a purity certificate; unknown effects remain explicit.
- Every block explicitly carries all region state domains. N1 supports synchronous normal calls; callee exception lowering, dynamic location lifecycle, GPU readiness and autograd remain outside this gate.
- Reference call results remain unknown until return summaries are verified. Known footprints use one location coordinate system; no arbitrary tensor geometry is inferred.
- No detector/backend, target rewrite, LeWM trace run, selected LeWM transformation or workload speedup is introduced.

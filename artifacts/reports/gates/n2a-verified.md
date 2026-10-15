# N2.a independent criteria report

Status: **PASS**

Revision: `429e87e2e32fd29e9c7d0f41dd0e0207cfab95fd`

Source digest: `def7da24a8fed048cb14a8a038285abb23667f64572581ad9abd638cb18db5a6`

| Criterion | Status |
| --- | --- |
| completion_records_strict_schema_and_v1_compatibility | PASS |
| normal_raise_dominance_state_and_exact_private_continuations | PASS |
| automatic_parameters_branch_merges_ordered_uses_and_candidate_interfaces | PASS |
| independent_python_scope_invocation_and_control_counterexamples | PASS |
| public_automatic_source_entry_persistence_replay_no_execution_and_no_overwrite | PASS |
| n1_control_state_call_and_wire_compatibility | PASS |

Scope: Automatically construct a conservative typed graph from a selected synchronous Python function and available same-file function candidates. Preserve exact source uses, branch bindings, normal/exceptional completions and conditional call interfaces, with strict public persistence and source replay. This is bounded source recovery, not whole-program recovery or optimization approval.

- The caller selects a source function entry. Command-to-whole-program discovery, cross-file bodies, loops, handlers, defaults/decorators, generators and closure binding interfaces are not recovered by this gate.
- Unknown Python expressions read/write one coarse world domain. Opcode/source correspondence does not establish fine Tensor state, alias independence, pure effects or the live dynamic target.
- Call candidates and actual/formal/result correspondences are conditional and INFERRED. Runtime code identity, GPU readiness and autograd remain unverified.
- A replayed UNSUPPORTED report is a valid diagnostic, not a complete function graph. Counts of parsed source atoms and mapped graph entities are not whole-program coverage percentages.
- No detector/backend, target source modification, selected LeWM transformation or measured workload speedup is introduced.

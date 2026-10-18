# R2.1 work-validation review closure

Worktree: `/tmp/scar-structured-model-280qf4mi`  
Final reviewed `work_validation.py` SHA-256: `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b`

## Closed findings and exact evidence

The earlier retention-basis counterexample is addressed in this final snapshot. A `UseRef` basis on a retained `HandleTarget` now compares known endpoint/value categories: a Reference-vs-native-scalar contradiction is an issue; a different value of the same category is retained as an alias/denotation gap. A `ResourceAccessID` basis now compares the accessed target with the held referent through `retained_resource_key`; unknown physical correspondence remains a gap. See lines 455–488. This review did not rerun those probes; their initial evidence is in `attempt001/`, and closure is a static inspection of the final source.

The cross-activation outcome-order counterexample from `attempt003/` is also closed at the validator level. In the earlier run (source SHA `608e7a9f…`), an outcome observation in a different activation of the same run/process passed without an ordering gap. The final source now emits `work_observation_order_unresolved` when `point_precedes` cannot order the outcome after a `WithinOperation` submission (lines 81–89). This preserves legitimate asynchronous/cross-activation observations as unresolved instead of rejecting them or treating them as ordered.

`InvokeBoundaryStateEffect` remains tied to the exact canonical invocation and exact input Use; input support is checked at that occurrence’s BEFORE point, and a declared post must match the selected completion result, landing formal, location, traversal, and activation. Cross-activation nested effects retain an explicit alignment gap (lines 104–174). These rules preserve occurrence scope without claiming physical work alignment.

Missing dynamic foreign references reviewed here are handled as issues rather than uncaught lookup failures: unknown dependency tickets, queue-prefix predecessors, execution access/binding links, outcome tickets, and retention endpoints use guarded lookups. The direct `requirements_by_id[...]` lookup in `access_target` follows the earlier resource validation pass: a binding to a missing static requirement produces a resource issue, and the top-level validator does not invoke work validation once an issue exists. I did not run a new malformed-static-program probe because `snapshot_for()` correctly rejects such a ProgramGraph before execution validation; the attempted setup failure is preserved in `attempt003/output.log`.

## Probe record and limits

- `attempt003/output.log` records the observed cross-activation acceptance, the structured issues for missing dependency/prefix references, and the rejected malformed static-requirement setup. The first invocation from the wrong directory is preserved in `attempt003/preflight-failure.log`.
- That probe used `ordinary_work_execution(activations=2)`: submission origin was in `activation.0`; `ResourceOutcome.observed_at` was changed to another operation’s BEFORE point in `activation.1`. Before the fix it reported `valid=True`, with no issue and no order/scope gap.
- No tests or workloads were run for this closure. Root reported the component gate separately; this document records static review of the final source and the preserved focused probe only.
- Other inspected source hashes: `resource_validation.py` `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08`; `validation.py` `0c79b637484dab61bacb0132ab5a81ba3b7b66a02c80188c6c31d5b8c0a1e604`; `query.py` `d968d0f19bdd148f0df3b298492ed924223e7cd10734445938212ce2d8569df8`.

This closes only the reviewed R2.1 work-validation connections. It does not establish source/runtime correspondence, physical work-effect alignment, readiness, quiescence, visibility, or retention-release authority.

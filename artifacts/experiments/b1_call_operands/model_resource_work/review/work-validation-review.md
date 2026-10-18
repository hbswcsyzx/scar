# R2.1 `work_validation` independent review

Reviewed from `/tmp/scar-structured-model-280qf4mi`; no product or test files changed.

## Findings

### Confirmed: retention target and basis can contradict without an issue

The focused mutation probe in `attempt001/` builds `ordinary_work_execution(retained='handle')`, whose base graph has no validation issues. Its retained handle is an `UnresolvedHandle` with a known `ValueOccurrenceID` and a reference-valued endpoint; the retention basis is the corresponding handle `UseRef`.

Two mutations remain issue-free in the reviewed validator:

1. Replace that basis with a different same-operation `UseRef` whose observed value is a different canonical value (`resource.fd` instead of `resource.handle`). The `HandleTarget` endpoint still names the original handle value.
2. Replace the basis with the same operation's queue `ResourceAccessID`, whose requirement binding points at the queue instance while the handle's target is the `ofd` instance.

Both results still carry generic retention gaps, so they do not authorize release. They nevertheless allow a declared basis known to contradict the retained handle to pass structural validation. The minimal repair is the one root has planned: for `HandleTarget`, compare a known Use binding against the endpoint's known value category; when same-category distinct IDs may alias, keep an explicit denotation gap rather than equating or rejecting them. For `ResourceAccessID`, compare its exact target to the underlying handle target when comparable. For `AccessRef`/other bases, emit a specific unresolved mapping gap unless the existing resource location/realization establishes the same target.

The exact reproducer and captured output are `attempt001/basis_mismatch_probe.py` and `attempt001/output.log`. The run was at `2026-10-18T05:04:21Z`; `work_validation.py` SHA-256 before and after was `5150570dc2c548a47f61f5d4daf5ee0aaf7ee000732d0ce693f961a5e1553a17`. This hash includes the root's then-current `WithinOperation` correction. No source changed during the probe.

## Checks that held in the reviewed snapshot

- `InvokeBoundaryStateEffect` resolves the exact original `invoke_arguments` Use, requires a `StateVersionValue`, checks its current BEFORE support, and for an actual post validates the selected successor, actual outgoing transfer when present, same state location, exact `CompletionResult` index, exact landing traversal, and activation. Missing transfer/input remains a gap; a wrong known edge/formal/result is an issue.
- Queue records require an existing QUEUE resource instance, a same-lifetime previous prefix, and a prefix whose work selects the exact `Queued` submission. The queue access must have the QUEUE role and target the same instance. Cycles are rejected. Prefix chronology/generation beyond those structural links remains R2.2 work; the code does not infer device order.
- `terminal_point` rejects a known observation before the enclosing submission operation. Outcome/effect frontier and quiescence remain separate; outcomes retain an `outcome_content_unverified` gap and cannot imply ready or free.
- Within-operation retention no longer substitutes the enclosing operation's BEFORE state for an internal point. It checks only candidate entry support and preserves an internal-start/interval gap. A known ended handle is rejected when the borrow starts after its end; an unorderable internal interval stays a gap.
- Foreign-reference probes for a missing executor access, missing outcome value, missing retained instance, and a resource in an unknown process all returned structured issues without raising. Full output is in `attempt002/output.log`.

## Scope and evidence

This is a small adversarial review, not a full R2.1 or R2 gate. Commands are archived under `attempt001/` and `attempt002/`. Relevant source fingerprints captured in the logs:

- `work_validation.py`: `5150570dc2c548a47f61f5d4daf5ee0aaf7ee000732d0ce693f961a5e1553a17`
- `validation.py`: `14f4817aab8b907d3d06a083d0e355db3018b5d6d30ac332d70136008e0c860c`
- `resource_validation.py`: `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08`
- `execution_work_graphs.py`: `7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f`

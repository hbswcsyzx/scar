# Retained source-call ABI follow-up

## Scope

This follow-up restores the earlier fixed-arity explicit-positional receiver path and keeps the targeted support for the 11 previously open candidates. It does not rerun the 201 source reader, full trace reader, capture, or target. The existing full publication remains 2,672 selected of 2,683 candidates; these local results are not merged into that denominator.

The source publication manifest is SHA256 `867a8fa08f97977ccf8aba2add85cd2544691f8aff1c61bcc685dc61160bfb8d`. The original old-binding shard is SHA256 `85fe9c44b3ceb7ab8f997312e2672928b7012aa24d7f622862b8206cbe45ebef` stored and `8e9d4c24da191331f401d686acc649345424a1013f88ee5acad3b67da1608b38` decoded.

## Change and observed results

For an attribute call with no keywords and `argcount == explicit positional count + 1`, the producer again checks that captured `arg0` matches the callee's first formal and maps explicit argument `i` to formal `i + 1`. The static source-call template retains `explicit_positional`, and reused occurrences must satisfy the same declared layout and receiver-reference condition. This preserves the existing rule; the reference and arity observations do not prove Python runtime method binding or receiver identity.

A normal local rebuild of published attempt 59197 exactly matched its old closed typed binding and codec round-tripped. The retained route has one explicit positional argument: original Use `94e8bea5ad3213bce3401f3cb21f9e68` to formal `col` at index 1 (the receiver is index 0). Its source location is `[141,141,15,33]`.

The same run built and codec-round-tripped all 11 local candidates: 10 `CALL` sites with omitted declared default `debug`, and one `CALL_KW` site with the original `keyword:debug` Use. All 11 remain conditional normalized-receiver projections. Combined runner wall time was approximately 4.37 seconds.

The bounded local reads returned 3,306 operand bytes and 1,374,145 frame bytes for the old binding, plus 296,165 operand bytes and 1,227,588 frame bytes for the 11 candidates. They were checked against the previously recorded whole-file receipts; the full files were not rehashed. The normal source reader read 4 bodies (29,335,931 decoded bytes), 4 code witnesses, and 2 source files (38,549 bytes).

The reproducible runner is [build_local_bindings.py](build_local_bindings.py); the combined typed result is [local-bindings-final.json](local-bindings-final.json). It uses the existing receipt-qualified source publication and bounded event intervals.

## Limits

The prior 2,672 / 2,683 publication was not rebuilt or renumbered. A same-arity plain function stored on an attribute can still be ambiguous with the preserved receiver rule; this follow-up does not establish runtime callable identity. For the 11 new cases, `default_source` denotes a static declaration, not the runtime default value. Neither path proves argument object identity, normal return, readiness, content equality, or full attempt coverage.

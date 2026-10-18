# Resumable Port and Identity Review

## Scope and source snapshot

Read-only source review of the resumable body port resolver, validator, identity pass, fresh external query path, and the P3 plan/contracts. No tests or probes were run. The static finding below is source-derived, not an observed fixture failure.

| File | SHA-256 |
|---|---|
| `scar/ir/execution/resumable_flow.py` | `e74ce73938bca668c4690b0f2df2e1c5278f34a11a8b5963a7fbaf85896bcca9` |
| `scar/ir/execution/resumable_validation.py` | `670750af064b5f865979edf59819a19045bedadbc341830a2b45df8c19b1f318` |
| `scar/ir/execution/resumable_identity.py` | `ff08277950afc4a41c8a81b8bfdabab7ad084ed0167ffe0d26e2a4b5cf87fc2e` |
| `scar/ir/execution/resumable_query.py` | `2eabe8577aee3be016b13ba90d7a614c5aad52f77afbbf455595180716fa3d02` |
| `scar/ir/execution/flow.py` | `e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc` |
| `scar/ir/execution/validation.py` | `cb406b8fba26d0dbae306aff6c42918661e5629c0dcad0ecd24d6bf9fdb3293c` |
| `scar/ir/execution/query.py` | `5f86bef0ac257e1cba411ef95765b4f74f0dc7b315caf924672c03e9a42e6a87` |
| `scar/ir/execution/content_validation.py` | `e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f` |
| `docs/M1_BODY_OCCURRENCE_PLAN.md` | `ebe7ec71cf64bd4bd1ca0b2cff19fa4f972df3a746d54953f0a232854c75b572` |
| `docs/M1_PROTOCOL_CONTRACT.md` | `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac` |

## Confirmed source closure

- `resumable_validation._endpoint` checks known entry/outcome endpoints before branching on whether the activation exists. Thus a missing activation no longer hides a known endpoint kind/FK contradiction. Explicit unresolved endpoints still go through `check_unresolved` against the declared activation when available.
- `body_errors` now builds an origin view for every captured activation whose region is declared resumable, even without a Drive row. Missing creation/origin information remains in that view as a gap instead of disappearing from the denominator.
- Dynamic Start/Resume inputs, actual Suspend ingress, body result uses, selected Drive transfer, and landing formals are projections of the original program/execution ports. The code does not materialize a second producer or state graph.
- The identity pass is ordered after fresh `content_errors`, which rebuilds scoped denotations. `ExecutionIndex.drive_execution` and `.body_activation_origin` call `_content_context()`, which calls `refresh_external_context`; that clears external-derived denotation rows, reruns the external stages including `body_identity_errors`, then returns a detached query result. I found no stale-construction-snapshot path in this query chain.
- Identity declarations remain conditional: query/runtime/value-identity/transformation flags are false, and cross-artifact object relations or missing denotations retain gaps.

## Initial blocker (superseded by the addendum below)

`prepare_value_copies` creates a canonical predecessor map from original block-argument transfers and declared call/body routes (`resumable_flow.py:228-254`), then collapses each route to a root (`:255-269`). `body_identity_errors` checks each BodyDrive input/output/forward endpoint and the Create-handle/Drive-owner endpoints (`resumable_identity.py:76-85`), then uses root equality to detect a different concrete Create handle (`:98-106`). It never checks the denotations on each predecessor edge in `body_value_predecessors`.

A specific declared route can therefore escape a known contradiction:

1. A Create NORMAL handle occurrence `H` has `ObjectIdentity(A)`.
2. An original ordinary CFG copy sends `H` into block formal `X`, whose scoped denotation is `ObjectIdentity(B)` in the same exact ValueGraph artifact, with `A != B`.
3. Another original copy sends `X` into `Y`, whose denotation is `ObjectIdentity(A)`; `Y` is the later Drive instance value.

The root map gives both `H` and `Y` root `H`, so the owner/Create-root test sees no different handle. Endpoint compatibility compares `H` to `Y` and sees `A == A`. Since the exact `H → X` and `X → Y` edges are not individually passed through `compatible`, the known `A` versus `B` contradiction at `H → X` is not reported. This is not an inference from arbitrary unequal roots: the contradictory pair is on an existing original copy edge.

Minimal correction: after the original predecessor map is prepared and denotations have been freshly resolved, compare each captured predecessor edge whose source and target are known `ValueOccurrence`s using the existing compatibility rules. Report same-artifact `ObjectID` conflicts and canonical kind/state-location conflicts on that edge. Keep different artifacts, absent denotations, and unresolved routes as gaps; do not infer inequality from distinct arbitrary roots and do not change runtime/identity/transformation flags. This reuses the existing route index and adds no producer/SSA records.

## Limits

No native/runtime correspondence, copy execution, transformation, or Python object identity was established by this review. No test suite or probe was run; the intermediate-edge case is a static source-derived counterexample. Other P3 lifecycle, host-order, and adapter obligations are outside this bounded review.

## Addendum: intermediate-copy closure review

Re-read the follow-up implementation and its targeted regression source. The earlier blocker is closed in the current code:

- `prepare_value_copies` now retains each predecessor recipe and its original support records, derives the ancestor closure of body binding endpoints and Create-handle/Drive-owner endpoints, and stores the selected recipes in `ctx.body_copy_recipes` (`resumable_flow.py:226-301`). It still uses the original CFG, CALL, and body bindings; it does not create a second producer or state graph.
- `body_identity_errors` resets and recomputes compatibility for each selected copy edge against the freshly rebuilt denotations (`resumable_identity.py:63-76`). The existing scoped ObjectID, value-kind, and StateLocation rules therefore catch the intermediate `A → B → A` route from the original report. Missing identity and cross-artifact scope remain gaps; the result flags do not grant runtime identity or transform authority.
- The new regression selects the driver-entry formal as the intermediate value, changes only its same-artifact ObjectID, and leaves the creation and later Drive-owner denotations naming the original object. Its `bare` control removes the resumable associations and confirms that the separate P3 relation is what exposes this conditional contradiction (`test_execution_body_port_review.py:11-29`). The Create-origin swap case also checks the intended exact-root check with no Object denotations (`:44-51`).
- `drive_execution` traverses the checked copy support from this Drive's original binding endpoints, spends from the same `ValidityBudget`, returns a cursor when truncated, and marks the result partial. Its host-order summary also charges that budget and returns `NOT_CHECKED` when it cannot pay the prepared cost (`resumable_query.py:20-81`). Fresh query construction still calls `refresh_external_context`, clears and reconstructs external denotation state including `body_copy_compatibility`, and reruns the identity stage before detaching results (`query.py:50-58`, `validation.py:418-446`).

The test source is well targeted to the reported route. Root reports the repair verification as the combined 55-case run and a separate 4-case `green002` run; these results are relayed evidence, not tests run by this reviewer. No remaining blocker was found in this bounded copy-route and query-freshness review.

Updated source hashes for the reviewed change:

| File | SHA-256 |
|---|---|
| `scar/ir/execution/resumable_flow.py` | `c131e2f4d2194dd69d03f505a5fbb154493451e0c19df1ff84ae5160295e4e21` |
| `scar/ir/execution/resumable_identity.py` | `6a14e49cc62c215e42c61e80dcec5b4a6d2572d0e75e1871b6f822df19d72460` |
| `scar/ir/execution/resumable_query.py` | `d34b4045f12b5f3334b4cd56aefe285f4ce67edbf7564f8c69291282c5006ce5` |
| `scar/ir/execution/query.py` | `5f86bef0ac257e1cba411ef95765b4f74f0dc7b315caf924672c03e9a42e6a87` |
| `scar/ir/execution/validation.py` | `2696dc8fc96272bb7ef3114bb117d06c8f67d5e0a32ea0af0a6eda427f8dc5f1` |

## Addendum: all-captured Create handle index

This supersedes the preceding addendum's “One known-source hole remains” finding: that unassociated-Create gap is closed in the current source. `prepare_resumables` now indexes each captured occurrence whose static operation has a `ResumableCreate` declaration. `_normal_create_handle` derives an indexed handle only when that exact occurrence has a captured outgoing transfer on its actual NORMAL successor and that successor binds the declaration's `handle_result.index` to a captured landing `ValueOccurrence`. The slot is taken from the original `CompletionResult` and successor argument/formal pair; no ValueOccurrence or producer is synthesized. The graph validator's exact-once completion-slot rule makes this slot projection unique.

Missing transfer, non-NORMAL transfer, or missing landing formal yields no indexed handle. For a Create explicitly associated with a body activation, `creation_view` retains the existing transfer/handle gap or wrong-completion issue. Unassociated creates with incomplete captures do not gain a guessed handle, so they cannot manufacture a contrary-source rejection. When the handle is known, `body_identity_errors` consults the all-captured index rather than the set of origin rows, so a Drive owner rooted at another Create can be rejected even if that Create has no `BodyActivationOrigin`.

The index is prepared from the canonical program and already-validated occurrence/transfer/value maps in `prepare_resumables`; it contains no external catalog or denotation result. External refresh carries this immutable occurrence-to-handle index while clearing/rebuilding external denotations and `body_copy_compatibility`. `body_identity_errors` recomputes compatibility against the fresh denotations, so this change does not introduce a stale external-evidence cache.

This was a source-only review. The root reported the dedicated regression's pre-fix `red001` failure and `green001` run in progress; this reviewer did not run or inspect a test process. Native/source/runtime identity remains unproven.

Current hashes:

| File | SHA-256 |
|---|---|
| `scar/ir/execution/resumable_flow.py` | `ea600a4dc8dff0368c17a9a84591d7e30bf6302b76b0602543469da23b27502e` |
| `scar/ir/execution/resumable_identity.py` | `ad7617888bbbfb404d4c90a75e5122aed9cd0e04570b1d347f07423bf8f7c264` |
| `scar/ir/execution/resumable_validation.py` | `bef0d177c4b8873ee0d46e7802263f1c861d5aa4d255b3d64db5092ffd763846` |
| `scar/ir/execution/validation.py` | `2696dc8fc96272bb7ef3114bb117d06c8f67d5e0a32ea0af0a6eda427f8dc5f1` |
| `scar/ir/execution/host_order.py` | `c4578ff1cf51b7ac922453a8e89e951a5c2393ac63d4817ebaa8bd029e659a91` |
| `scar/ir/execution/validity_budget.py` | `e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10` |
| `tests/unit/test_execution_body_port_review.py` | `4b0765fe20fad168c2503448d1f23733782392a7761a3255d93bf7c3274593ec` |

## Addendum: completion aliases and unassociated Create sources

The completion-slot concern is closed by the canonical ProgramGraph validator. For each `CompletionSuccessor`, `program/validation.py:324-327` requires the set of `CompletionResult.index` values to equal the signature slots with no duplicates; `BodyDriveResult` has the same exact-once rule at `:328-332`. The normal program codec calls `require_valid` before writing (`program/codec.py:110`), and execution analysis snapshots `program_dumps(program)`. Therefore routing one `CompletionResult(0)` to two landing formals is rejected as `completion_slots`, not a legal aliasing case. Aliases through distinct actual result slots or later original CALL/CFG copies retain distinct formal routes. `call_validation._outputs` and `creation_view` selecting the unique matching slot are consequently consistent with that normal form. `ExecutionIndex.formal_route` also returns the exact edge argument/formal position for a captured BlockArgument (`execution/query.py:195-209`).

One known-source hole remains. `body_identity_errors` builds `creation_handles` only from resolved `BodyActivationOrigin` views (`resumable_identity.py:76-79`). A different captured `ResumableCreate` occurrence can have its NORMAL completion and handle landing captured without owning any `BodyActivationOrigin` row, for example a created object that is never driven. If a Drive owner’s original copy root is that handle while its declared expected handle comes from another Create, the root is known to be another Create result but is absent from `creation_handles`. The current path reports `body_instance_copy_unproved` rather than rejecting a known contrary Create source (`:107-112`). This does not erase the denominator, but it weakens a statically known contradiction to a gap.

Minimal repair: independently index captured handle roots for every dynamic occurrence of a static `ResumableCreate`, using its actual selected NORMAL transfer and the unique `CompletionResult(handle_result.index)` landing formal. Include such roots in the contrary-source check even when no activation points to that Create. If the Create NORMAL transfer or handle formal is uncaptured, retain a gap; do not infer a handle from the static declaration alone. No extra relationship record is needed.

This addendum is source-only; no tests/probes were run by this reviewer. Current source hashes:

| File | SHA-256 |
|---|---|
| `scar/ir/execution/resumable_flow.py` | `7d926f20870034d45574a43fa1e226c32914d1c5cb62efdfe99c18ac3726c156` |
| `scar/ir/execution/resumable_validation.py` | `670750af064b5f865979edf59819a19045bedadbc341830a2b45df8c19b1f318` |
| `scar/ir/execution/resumable_identity.py` | `6a14e49cc62c215e42c61e80dcec5b4a6d2572d0e75e1871b6f822df19d72460` |
| `scar/ir/execution/call_validation.py` | `9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2` |
| `scar/ir/program/validation.py` | `c65ff8590068bed8c8c0bd8fbbbe44a33e4bfc2afce1ae218b936a90207a465e` |
| `scar/ir/execution/query.py` | `5f86bef0ac257e1cba411ef95765b4f74f0dc7b315caf924672c03e9a42e6a87` |
| `scar/ir/execution/validation.py` | `2696dc8fc96272bb7ef3114bb117d06c8f67d5e0a32ea0af0a6eda427f8dc5f1` |

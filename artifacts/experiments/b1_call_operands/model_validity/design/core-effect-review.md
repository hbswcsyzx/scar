# Canonical effect resolution review

Status: read-only design review; no source changes or tests run. Reviewed tree is `f2b4672d9555348dcd05da62a8cd126711ef22f9`. The V bindings remain proposed; this note does not claim a validity or readiness implementation.

## Finding

The same original effect is resolved in three places, with different caller assumptions:

| Caller | Current resolution | Caller-specific fact mixed into resolution |
| --- | --- | --- |
| `work_validation.check_effect(effect, work, path)` | Validates `AccessRef` or `InvokeBoundaryStateEffect`, including original state input, completion edge/result/formal, location, and activation. | Requires a concrete `work`, then checks run and submission owner at lines 165–174. This is appropriate for a submitted effect, but the resolution logic is nested inside the work validator. |
| `production_validation._effect(ctx, effect, path)` | Independently resolves the original `StateAccess`, or an INVOKE state input and actual completion landing. It explicitly supports a `HostWrite` with no `WorkSubmission`. | `write_errors` separately joins `WorkWrite` to its exact ticket/effects. This separation is the useful pattern to generalize. |
| `content_validation` | `AccessRef` goes through `resolve_subject`; INVOKE checks owner and state-input support. | INVOKE requires membership in the global `ctx.work_effects` set at lines 490–498, even for `HostConsumer`; `ResourceConsumer` is not checked against its own ticket’s effect list. |
| `ExecutionIndex.canonical_effect(effect)` | Builds a public projection of the original access or invoke/transfer/post/successor. | Rejects INVOKE unless the effect occurs anywhere in `ctx.work_effects` (lines 218–229). The API is therefore neither a pure resolver nor an exact per-ticket check. |

`ctx.work_effects` is the union of all submissions’ effects and all outcomes’ frontiers (`validation.py:95–96`). It can answer only “some work row mentions this endpoint.” It cannot establish that this `ContentRead` belongs to that work ticket. Conversely, requiring that union prevents a valid host-side INVOKE content read from being represented without inventing a work ticket. The current `ContentRead` rule also has a concrete cross-ticket gap: an effect attached to ticket A can satisfy the global-set check for a read declared for ticket B if the INVOKE operation matches.

This matters to V: a visibility alternative must attach to the exact demand, consumer, and contribution. A canonical state boundary is useful input to that join, but it does not itself prove a native read, physical bytes, or visibility.

## Shared resolver proposal

Add one internal, nonserialized module/API, for example:

```python
resolve_canonical_effect(ctx, effect, path) -> CanonicalAccessEffect | CanonicalInvokeEffect | None
```

It accepts only exact `AccessRef` or `InvokeBoundaryStateEffect`. It reads the already-built execution context and original core graph, records structural issues and observation gaps through `ctx.issue` / `ctx.gap`, and returns references to existing records. It must have **no work-ticket parameter and no membership check**. A malformed original endpoint returns `None`; an unresolved observation returns a view with explicit absent/unresolved observations and the corresponding gap. It never creates a value, state, use, successor, or transfer.

Suggested internal result fields:

```text
CanonicalAccessEffect:
  reference: AccessRef
  occurrence: OperationOccurrence
  operation: original Operation
  access: original StateAccess
  mode: AccessMode
  before: original UseOccurrence | Unresolved | None
  after: original ValueOccurrence | Unresolved | None
  activation: RegionActivationID
  run: RunID | Unresolved | None

CanonicalInvokeEffect:
  reference: InvokeBoundaryStateEffect
  occurrence: OperationOccurrence
  operation: original INVOKE Operation
  state_input: original UseOccurrence | Unresolved | None
  input_location: LocationID | None
  declared_post: ActualCompletionState | Unresolved
  actual_transfer: original ControlTransfer | None
  actual_successor_index: int | None
  declared_successor: original CompletionSuccessor | None
  actual_successor: original CompletionSuccessor | None
  declared_result: original CompletionResult | None
  formal: original ValueOccurrence | Unresolved | None
  activation: RegionActivationID
  run: RunID | Unresolved | None
```

For `CanonicalInvokeEffect`, require that `state_input` is an original `invoke_arguments` Use for this exact invocation and that its core value is exactly a `StateVersionValue`. When `declared_post` is `ActualCompletionState`, check its successor index, the actual transfer, exact `CompletionResult(result_index)` at the formal’s argument slot, same state location, exact landing block/visit, and same body activation. A known wrong port/edge/formal is an issue. Missing actual transfer or unresolved post is a gap; do not infer the post from the current-state map, a work outcome, same-name field, or neighboring successor. Return both the declared port and observed transfer so callers can distinguish static association from actual landing.

Use exact-class checks consistently for canonical core variants (`StateVersionValue`, `BlockArgument`, `CompletionResult`). `production_validation._effect` currently uses `isinstance` for two of these checks while `work_validation` uses exact types. The public resolver should match the validator’s exact canonical model contract rather than silently broaden it.

Caller policy remains separate:

1. **Work validation:** call the resolver for each submitted effect/frontier element, then retain the current checks that relate it to that exact `WorkSubmission`, `ResourceOutcome`, ticket, run, and owner. Keep complete-vs-partial frontier behavior here.
2. **Production validation:** call it for `StateProduction`/`HostWrite` without requiring work membership. For `WorkWrite`, separately require the effect to be listed in that exact ticket’s `effects` or exact outcome frontier according to the existing production association. Preserve `production_invoke_write_unverified`: state transport is not write semantics.
3. **Content validation:** call it for any `ContentRead` effect. For `HostConsumer`, require the effect operation to match the subject operation and state support to include the exact original state input; no ticket is required. For `ResourceConsumer`, additionally resolve `consumer.read.ticket` and require an exact association to that ticket’s relevant work/effect record. Do not accept the global union of unrelated tickets. Keep `content_invoke_read_unverified`: the invoke state input does not prove a native read or footprint.
4. **Public query:** `ExecutionIndex.canonical_effect` should return the shared projection after full graph validation, regardless of whether any work row references it. Its existing output keys can remain as a compatibility projection of the typed view. `ExecutionIndex.work` still exposes exact per-work effects and can call the same resolver.

The resolver should preserve the distinction between an ordinary state access and INVOKE boundary transport. An `AccessRef` carries the original `AccessMode`, `before` Use, optional `after` result, and footprint declaration. A `READ`/`READ_WRITE` may participate in a read association; a write-only access cannot be relabeled as a read. INVOKE transport has a state input and completion result/formal but no `AccessMode` or memory footprint. Neither form alone proves byte coverage, content stability over an interval, or host/queue/endpoint visibility.

## V binding implications

V should join a resolved effect to its own consumer/demand after canonicalization, not use a global effect set as an implicit bridge. The join key must retain `ContentReadID`, exact consumer variant, exact `UseRef` or `AccessRef`, and, for a resource consumer, the exact `WorkTicketID`. Host visibility and resource-work visibility remain different domains. A ticket’s `WorkStart`/`WorkEnd`, queue wait, outcome frontier, and quiescence are separate evidence; none should be inferred from the effect resolver.

The source-derived candidate universe still has to be enumerated before associations are consulted. Removing a `WriteAssociation` or work row must leave an unmatched source candidate/gap rather than remove a required contribution. Conversely, historical lineage writers are not automatically all current contributors: production, lineage prerequisites, and possible invalidators remain separate classifications. The shared effect view supplies a checked core endpoint for those joins; it does not close source completeness or authorize `READY`.

## Required regression cases and existing IDs

Reuse the existing canonical fixtures and retain these current test IDs unchanged:

- `test_actual_invoke_normal_and_raise_keep_their_own_formal_and_partial_frontier` — both successors use the same completion result index in different landing-argument positions; preserve the actual successor, result, and formal separately.
- `test_unresolved_external_source_and_actual_completion_post_keep_specific_gaps` — unresolved post remains a gap and is not reconstructed.
- `test_invoke_effect_cannot_change_actual_successor_result_formal_location_or_input` — keep the parameterized successor/result/formal/location/input/invocation negatives.
- `test_native_basis_selects_exact_initial_entry_and_completion_slot` and `test_native_duplicate_output_positions_keep_distinct_uses_for_the_same_value` — preserve P1 boundary positions and distinct UseIDs, including duplicated values.
- `test_host_interval_must_match_subject_run_and_operation` — retain scope/order binding.

Add focused cases at the shared-resolver/caller layer:

1. A valid host `ContentRead` anchored to an INVOKE state input, with no submissions or outcomes, resolves the canonical INVOKE view and remains explicitly gapped for native read/footprint proof.
2. Two tickets refer to the same observed invocation, but only ticket A lists the effect; a `ResourceConsumer` read bound to ticket B must not borrow A’s effect through `ctx.work_effects`.
3. A known actual NORMAL/RAISE transfer paired with the other successor’s post is an issue; an absent transfer or explicit `Unresolved` post is a gap and yields no invented post-state.
4. An ordinary `AccessRef` fixture preserves `READ`, `READ_WRITE`, and write-only mode and original before/after endpoints; callers apply read/write policy without changing the canonical view.
5. Cross-activation ordering remains unresolved unless the existing coordinates establish it. Same static operation, location, or equal state IDs cannot bridge activations by themselves.

The existing `tests/fixtures/execution_work_graphs.py::invoke_work_execution(raised=..., queued=...)` is the smallest reusable NORMAL/RAISE fixture. `tests/fixtures/execution_content_graphs.py::content_connection_fixture(consumer="work", duplicate_use=True)` covers separate tickets and distinct original Uses; extend/compose it for a work-free host INVOKE case rather than creating a fake ticket. Keep the existing IDs listed above stable.

## Scope and verification

Read-only inspection only. No tests or workloads were run. This report is bound to tree `f2b4672d9555348dcd05da62a8cd126711ef22f9` and these SHA256 values:

| File | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/production_validation.py` | `c824c947a3ecf745b95096cdd6b69a529c2563ed02f6b951e261783ce4bb8c1e` |
| `scar/ir/execution/content_validation.py` | `bd163c92244a06dae9e5756882124cab350ffeec09bbe22e3137278712f5b298` |
| `scar/ir/execution/query.py` | `cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1` |
| `scar/ir/execution/validation.py` | `a59db9e27b4eaa924c1b7973ac995a36cc59c3cfdd63c23d00832447b7d8c0ac` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `scar/ir/execution/flow.py` | `2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501` |
| `scar/ir/execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `scar/ir/execution/production.py` | `cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62e2e4aea43a` |
| `scar/ir/execution/order_validation.py` | `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba` |

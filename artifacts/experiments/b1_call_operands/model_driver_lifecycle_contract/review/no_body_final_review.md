# Final review: `M1_DRIVER_LIFECYCLE_CONTRACT.md`

**Result: PASS_WITH_SCOPE**

Reviewed `/tmp/scar-structured-model-280qf4mi/docs/M1_DRIVER_LIFECYCLE_CONTRACT.md`, SHA256:
`eb702442cbec2469eca239685ff4ea6476472d75b243d59fa43553f12ed93dab`.

Scope was §2–§4 and their connection to the staged implementation rule in §7. No source or runtime tests were run.

## Findings

- **Branch polarity is consistent.** §4 fixes the core convention `successors[0] = true`, `successors[1] = false`; `NoBodyFinish.precondition` must name edge 0. There is no D2 polarity override or extra `true_successor_index`. This matches the previously reviewed `(yes, no)` lowering convention. The core graph documentation/API contract must carry the same definition so hand-built graphs and later consumers cannot reinterpret the ordered edges.
- **The predicate and finish are connected through real ports.** `CreatedCloseTest.result` must be an operation-produced builtin bool and the exact branch condition. The true edge enters a private landing whose first operation is `NoBodyFinish`. The finish consumes the same body instance value, either while it still dominates or through an exact edge-use/formal copy. The false arm preserves ordinary control flow and does not invent a raise.
- **BODY and ASYNC_REQUEST roles are distinct and coherent.** BODY uses the interface body receiver and scheduler request, with a separate effective-request use of the same `ValueID`; `session` is absent. ASYNC_REQUEST keeps the request object `R`, scheduler request `S`, associated body `B`, and latent request `E` as separate role uses. `B` and `E` must be actual values. A `RequestAssociationRead` is optional, and if present its output links must be explicit. External request values and multiple Create sites remain representable. No identity is inferred from matching names or types.
- **State ports form a consistent partition.** The contract states `∅ ≠ L ⊆ D`, tests read every current `L` domain, and body publication/no-body finish write only nonempty `W ⊆ L`. Unwritten domains and `D\L` continue through the core's current-state edges; no operation invents an after value for an unmodified location. `SessionUpdate` remains independent from body terminal state. NoBodyFinish is body-only.
- **The declaration does not promote itself to evidence.** The predicate’s typed row, `effects_complete`, behavior tags, and driver rule remain declarations. §1, §4, and §7 explicitly withhold source/runtime proof and transformation authority until later correspondence gates.
- **The staged scope is internally consistent.** §7 directs D2.1 to implement only `DriverLifecycle` and `BodyOutcomeCommit` with strict v12 wire/query/CLI; later lifecycle records remain for later gates rather than being added as isolated schema fields.

## Remaining scope

No model contradiction blocks D2.1. The document itself calls out that source/native correspondence, actual instance identity, predicate behavior and purity, reset/interposition assumptions, and complete family lifecycle semantics remain unproved. Those are explicit later gates, not reasons to reject the declaration model. Ensure the core documentation/docstring publishes the edge-0/edge-1 branch meaning before consumers rely on it.

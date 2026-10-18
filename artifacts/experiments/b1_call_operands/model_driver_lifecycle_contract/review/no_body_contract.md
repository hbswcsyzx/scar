# Created-close no-body path: D2.0 contract

**Status:** proposed frozen structural contract for D2.0; not a runtime or source proof.

**Reviewed input:** worktree `HEAD 8ee8d02a901a70659062966230e3efeb777503a6`; existing lifecycle observation file `artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/review/lifecycle_probe.json` (no probe rerun). That file records observations, not assertions. In particular, its async-generator close retry ends in `AGEN_SUSPENDED`; a `StopAsyncIteration` from a later `aclose()` does not establish that the body closed.

## Frozen records

Use the existing D1 `DriverInterface`, `DriverRule`, `RequestAssociationRead`, `StateAccess`, `ControlEdgeReference`, ordinary `Operation`, and CFG successor arguments. Add only these lifecycle records:

```text
CreatedCloseTest(
    operation: OperationID,
    instance: UseID,
    scheduler_request: UseID,
    effective_request: UseID,
    session: UseID | None,
    result: ValueID,
    true_successor_index: int,
)

NoBodyFinish(
    operation: OperationID,
    precondition: ControlEdgeReference,
    instance: UseID,
)
```

`true_successor_index` is an exact integer in `{0, 1}`. The core `BRANCH` currently has two ordered successors but no true/false tag. This field declares which successor is the predicate's true arm; `NoBodyFinish.precondition` must identify that same edge. Source/provider correspondence must later verify the declared polarity. Do not silently infer truth from successor order.

The `CreatedCloseTest` operation is an ordinary, non-terminating operation immediately before the `BRANCH` terminator in its block. Its `result` must be the exact operation-produced `DataValue` of builtin `bool`, and the branch condition must use that value. A literal `True`, label, operation name, or value type by itself cannot satisfy this relation. The test has no callee or callback, no writes, and exactly read-only `StateAccess` over the interface lifecycle set `L`. For this first profile, its read set `T` is exactly `L`; it has no state access outside `L`. The rule declares this shape as a current-state, non-callback predicate. These checks establish a declaration only: they cannot establish that the implementation actually computes the predicate or is pure.

`NoBodyFinish` is the first operation in the private landing block of the declared true edge. That edge has a unique incoming predecessor. It forwards the tested body instance through an owned edge `UseID` to a landing `BlockArgument`, then to `NoBodyFinish.instance` through another owned `UseID`. All are exact same-`ValueID` transfers; the test, edge, landing, and finish each retain their own use occurrence. The finish has no call, callback, or failure edge. Its real state writes are `W`, with `∅ ≠ W ⊆ L`; every write is represented by the operation's ordinary `StateAccess` and current-state chain. The typed rule declares which of these locations represent the body's terminal lifecycle state. It does not infer this from a location name.

The false successor remains an ordinary reachable CFG path to the original handling logic, normally the final body gate and a `BodyDrive`. It forwards the actual values and current states that path needs. It is not rewritten as a fabricated `RAISE`, and no error value is invented for the predicate's false result.

## Inputs by driver kind

Every `CreatedCloseTest` has distinct owned uses for `instance`, `scheduler_request`, and `effective_request`; `session` is another distinct use when present. The use IDs remain distinct even if their values alias. All inputs must have the declared core value category, and the scheduler request must be the exact raw request value from the interface. Same type, name, source span, or code object never establishes value identity.

| Interface receiver kind | `instance` | `session` | scheduler `S` | effective `E` |
|---|---|---|---|---|
| `BODY` | Current body instance `B`, must-forwarded from the interface receiver | `None` | Interface scheduler request | A separate use of the same exact value as `S` |
| `ASYNC_REQUEST` | Current associated body instance `B`, supplied as an actual value | Interface receiver request object `R` | Interface scheduler request `S` | The request's actual latent operation `E`, supplied as an actual value |

For `BODY`, the profile's condition is “this exact current body is still created and this exact effective request is close.” The equality `E == S` is required by this interface shape, but the two roles still use distinct `UseID`s.

For `ASYNC_REQUEST`, keep `R`, `S`, `B`, and `E` as separate roles. The request may have been created by any number of static `ResumableCreate` sites or supplied at an external boundary. No unique `Create` is required. A `RequestAssociationRead` is optional: if one exists, the test's `B` and `E` inputs must be connected to its actual outputs through ordinary uses and block arguments. If there is no such record, `B` and `E` still must be actual inputs or operation results, and the typed predicate contract must say it checks the current association of `R` to `B` and the current latent operation `E` at the test point. It is invalid to invent `B` or `E` from `R`, or to equate values because their types match. Conversely, `E == S` is not intrinsically invalid: it may simply make the predicate false. The no-body finish is selected only when the actual predicate result is true.

An association mismatch, non-close `E`, or non-created `B` is a false predicate case, not a malformed graph. The false edge must preserve the original path. If the graph does not expose actual `B` and `E`, it cannot express this no-body test and must retain the path as opaque/conditional; it must not claim a successful no-body finish.

## State, marking, and session lifecycle

The test reads every location in `L` at the current versions. It must not mutate state before the branch. The true-arm finish writes only the nonempty subset `W ⊆ L` shown by its real `StateAccess`; a coarse world write may not masquerade as a precise body-only write. The body-terminal meaning of `W` comes from the declared driver rule and later source/provider mapping, not from the `NoBodyFinish` row alone.

Body terminal state and request-session state are independent facts. `NoBodyFinish` does not imply that an async request is complete, and a completed request does not imply that its body is closed. A `SessionUpdate` may be recorded separately when the path changes session state; its current request/body uses and post-state must be the real ordinary uses and `StateAccess`. It has no free-form source list. A combined physical operation may represent both facts only when its actual state accesses expose both writes and a typed rule declares that combined behavior; do not synthesize a second operation or infer the session transition from the body mark.

The mark occurs before any capture release or destructor-capable work. The existing observations show that closing a created generator can commit `GEN_CLOSED` before a captured object's destructor runs, and the destructor can re-enter the generator. Therefore the no-body mark is the terminal-state commit point; later release work must consume the post-mark state. A created-close path does not create a `BodyDrive`, `BodyOutcomeCommit`, `FrameContextDetach`, or synthetic return/raise outcome.

## Structural checks versus proof

The static validator can check: exact operation/result/use ownership; current interface `S` and receiver forwarding; input categories; `T == L`; direct bool-to-branch connection; explicit true-arm agreement; private true landing; exact body-value forwarding; false-edge preservation; `∅ ≠ W ⊆ L`; current state versions; and ordering that places the mark before release-capable work.

Those checks do **not** prove that the predicate reads a real Python frame status, tests the correct `B/R/S/E` association, avoids callbacks, or returns the semantically correct boolean. `DriverRule`/`ProviderFactReference`, operation behaviors, `effects_complete`, and this annotation are declarations, not evidence. Native/source correspondence must later bind the actual implementation and establish the no-interposition condition. Until then, the path is `DECLARED`/conditional and cannot authorize transformation, purity, or a claim that an unobserved body did not run.

## Minimal acceptance cases

1. BODY close on a created body: `B`, `S`, and distinct-use `E == S`; test reads all `L`; true edge forwards `B`; finish writes `W ⊆ L` before release.
2. BODY next on a created body and BODY close on a suspended body: predicate false; preserve the original start/resume path and do not create a raise.
3. ASYNC request with `R`, current associated `B`, scheduler `S`, and latent close `E`; accept both an explicit `RequestAssociationRead` path and an external/multi-create input path. No unique Create is assumed.
4. ASYNC non-close latent request, stale/mismatched association, or non-created body: real false edge; the graph remains valid and continues through ordinary handling.
5. Reject a bool literal, wrong branch condition, wrong true-arm index, non-private true landing, extra callback/write between test and branch/mark, wrong body instance forwarded, duplicate role `UseID`, missing lifecycle read, or mark write outside `L`.
6. Reject claims that a body finish alone completes a session, that a session completion closes the body, or that a predicate annotation proves dynamic purity.

These are structural-contract cases. Matching them does not establish Python source fidelity, runtime instance identity, or a safe optimization.

## Root resolution (supersedes the two proposals above)

The earlier proposal to add `CreatedCloseTest.true_successor_index` is withdrawn. The core contract will define `Terminator.BRANCH.successors[0]` as the true arm and `[1]` as the false arm. This agrees with the existing structured and source lowerers, which construct `(yes, no)`. `NoBodyFinish.precondition` therefore references the actual branch edge at index `0`; no D2 overlay may reinterpret the polarity. The core API documentation/docstring must state this semantic rule. This resolves the missing-meaning issue without adding a second source of branch polarity.

`NoBodyFinish` is fixed as a body-only terminal-state operation. It cannot also carry a session-post claim. A session update remains a separate lifecycle fact with its own ordinary state accesses and actual request/body uses. If a native implementation physically combines body and session handling, represent that implementation through its provider's cross-representation execution relationship where the underlying operations can be decomposed; otherwise keep the combined implementation opaque/conditional. Do not attach two potentially conflicting lifecycle annotations to one operation or imply a second physical execution.

The original discussion above is retained as review history. The frozen D2.0 contract is the resolution in this section: edge `0` is true, edge `1` is false; the no-body mark writes body lifecycle state only; and session state is modeled separately. Neither the core polarity rule nor these records alone prove that a Python implementation follows the contract.

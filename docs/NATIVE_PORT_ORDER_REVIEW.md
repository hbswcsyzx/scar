# Native adapter port-order connection review

2026-10-23. **Original read-only gap review, followed by an implemented correction and
third actual gate PASS.** The review/counterexample below describes the earlier
checker and is retained as history. Its saved-model review did not reopen raw or
restore owned authority. The later authorized correction/gate is recorded at
the end; the first two terminal experiment directories remain unchanged.

## Exact gap

`program/native_validation.py:native_errors` checks that the union of native and
core-only ports is a complete disjoint *set* of canonical entry/exit ports.
Generic NativeBoundary deliberately allows native order to differ from physical
core order. It does not assert native slot i is entry BlockArgument i.

`program/provider_validation.py:provider_errors` checks coordinate uniqueness,
foreign keys, exact representation owner, value categories and the producer/Use
owner's external key. It does not interpret `ProviderPathIndex(i)` as a proven
native argument/result position or connect that ordinal to NativeBoundary.
Neither generic validator should be tightened into this one adapter's layout.

`execution/content_validation.py:native_port` correctly follows the *declared*
NativeInputSlot/OutputSlot to an actual canonical formal or Return Use. It also
checks that the denotation selects that actual value. Canonical execution flow
correctly checks the formal/Use's own dataflow. Those checks establish internal
consistency, not that the declaration preserves the raw provider's ordered ABI.

`execution/native_port_protocol.py:NativePortEvidence.resolve` independently
replays the raw direct child, schema/type/path and held-object port inventory,
then checks boundary ID/position, original WeakRef object and actual invocation's
legacy binding. It does **not** independently connect flat native ordinal i to
entry formal i / invoke argument i, or output i to completion result / Return
argument i. `require_scope` seals exact bytes, but a fresh seal of a consistently
wrong producer result does not prove this missing semantic connection.

## Bounded saved-model counterexample

`artifacts/analysis/native_port_order_review_20261023/review.py` reads only the
saved successful ProgramGraph/ExecutionModel, small source projections and schema
interface; all saved artifact SHA/bytes are checked. No raw file is opened and
no NativePortEvidence or owned capture is created/restored.

The original builder's saved graph passes the proposed order checks. Source
review confirms `_build_program` uses the same enumerated native flat order for
BlockArgument, invoke Use/invoke_arguments, CompletionResult, normal argument,
Return Use and NativeBoundary; `_build_execution` uses that same ordinal for the
actual value, Use and denotation. Thus the concrete original producer output is
correctly ordered. This is distinct from independent checker completeness.

The script mechanically selects an existing two-Reference-input interface,
exchanges only its NativeInputSlot port references, and adjusts affected
ValueDenotation.value references to agree with those wrong declared ports.
Actual canonical formals, invocation Uses and their observed values remain
unchanged. The candidate receives its own genuine canonical ProgramSnapshot
SHA and model SHA. It is a *hypothetical declaration counterexample*, not a newly
observed execution or restored runtime authority.

Observed: public core validation and generic execution validation both accept
this internally consistent wrong candidate with0issues. A proposed independent
flat-layout checker rejects it with6order mismatches (2static native/core slot
mismatches plus4actual Use/value mismatches). This is not rejection by borrowing
the old proof's scope hash. The checker also finds0order errors in the actual
saved positive graph. Inferred from full branch inspection: the current owned
resolver has no additional ABI-order predicate that would reject this candidate
if a fresh source-owning producer sealed it. No owned-session acceptance is
claimed as an executed test here.

## Minimal production correction

Change only `ir/execution/native_port_protocol.py`, subject to root approval.
Add a private bounded helper interpreting this closed adapter's documented flat
layout, using interfaces independently replayed from the private immutable raw
source. It must not accept a caller's `validated=True`, derived mapping or saved
success report. Invoke it for the exact program/model when creating the native
session and when checking its scope, including interfaces/ports without Tensor
denotations. Existing core/execution validators and legacy no-proof behavior
remain intact; their guarantees remain prerequisites.

For each source-derived signature and its exact native region:

1. Check complete flat input/output count, types and original ordered path
   signature against the real schema interface and representation owner.
   Port IDs are locators; the following structural checks provide the meaning.
2. Input i: native input slot→entry.arguments[i]→its original
   BlockArgument(entry,i)→the opaque invoke's invoke_arguments[i] and original
   Use→the same canonical value, with the correct Reference/Data role. Check the
   same native provider binding path/target instead of trusting its presence.
3. Actual input i: the exact source-matched invocation occurs in this native
   entry visit/activation. Its actual UseOccurrence must reference the exact
   ValueOccurrence(entry visit,entry.arguments[i]); the NativeInputRef/denotation
   must select this occurrence, not merely an equal ObjectID or another call.
4. Output i: native output slot→the actual normal exit's index i→normal
   CompletionSuccessor's CompletionResult(i)→normal block argument i→Return's
   original ordered Use i. Require the exact observed normal ControlTransfer and
   Return occurrence in the same activation. Its actual UseOccurrence and
   NativeOutputRef/denotation must select that exact normal formal occurrence.
5. Check the complete input/normal-output inventory once per static interface;
   check actual visit/Use/transfer bindings per activation. The common world tail
   and unobserved exception path remain core-only and opaque. No new state,
   logical value, alias or ready authority follows from matching the ABI.

The helper must be checker code, not a call back into `_build_program` or an
assertion of the builder's result dictionary. It should report a concrete
native-port-order failure rather than masquerading as a stale-scope error.
Generic NativeBoundary/provider validators keep their existing flexible layout
contracts. No new IR, workload rule, provider token equivalence, detector or
backend is required.

## Required acceptance of the correction

Use the saved positive core/execution and the re-sealed counterexample through
the production *pure layout checker*: the positive layout passes and the
internally valid wrong candidate rejects on port/Use order, not old scope hash.
Actual output result/Return Use order is checked too. If a new owning raw gate
is authorized, build a fresh legitimate in-process owned session and test the
same counterexample at its normal constructor/check path; never reconstruct
owned authority from these saved artifacts. All previous contents/state/alias/
ready frontiers and original bounded evidence remain unchanged. The earlier
PASS proves its tested concrete reference associations, not completeness of the
independent ABI checker before this correction.


## Implemented correction and actual acceptance

Root authorized the one-file correction. `native_port_protocol.py` now contains
`_native_port_order_errors` / `_require_native_port_order`, interpreting only this
pinned flat adapter. Both constructor and require_scope execute it from the
private raw-replayed source signatures. Static counts/types/provider paths,
entry formals/invoke Uses, every normal CompletionResult/Return Use and actual
entry/normal Use/value/transfer associations are checked, including scalar/world
positions. Generic core/NativeBoundary/provider contracts are unchanged.

The production pure helper passed the saved positive and rejected the newly
sealed, internally generic-valid candidate with6order errors; no owned evidence
was restored. The authorized fresh attempt03 then passed the full real gate
(exit0,19.26s GNU-time wall,660,880KiB maximumRSS). With this run's actual live
owned source, trying to create a proof for the internally valid wrong graph+
model with its own fresh snapshot raised NativePortOrderError (2static and4
actual order mismatches). This is stronger than an old scope-hash rejection.
The original positive references, three negatives, no-proof gap and all41
content/thread/source-runtime frontiers are retained. Full modeling, logical
content and readiness remain OPEN. The previous PASS is not retroactively
claimed to have executed this new independent order check.

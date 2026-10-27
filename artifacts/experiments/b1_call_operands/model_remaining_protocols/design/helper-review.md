# Reference-only request helper: independent source review

Status: **PASS_WITH_SCOPE** for the narrow helper-context extension reviewed
below. This is not a P4 contract freeze, full protocol acceptance, selected
request identity proof or independent test execution.

Only this new ignored report was written by this reviewer. Products, tests,
fixtures, docs and `delegate.md` remain untouched. No Python, pytest, probe,
workload or git command was run by this reviewer.

## 1. Actual finding and root's preserved evidence

The initial `delegate.md` source finding concerned a genuine signature:
the caller has an original raw-request Use, while its helper receives only the
original Reference arguments. A raw formal is not part of that helper's
physical signature and must not be fabricated for the analysis.

Root's `helper-inputs/red001` ran the arity1/depth1 positive on a core-valid
ProgramIndex and reproduced an empty `bindings` result. The retained stdout
shows exactly one failed assertion (`len(bindings)==1`), not invalid core IDs or
shape. Its result records exit1, 1.288568s wall, and unchanged registered-source
fingerprint `c7c93cfcf7b061c1b06ae30eca182231ea16a8897f94cf5923f3cd01972e6579`.
This is root's run, not this reviewer's experiment.

Root's later `green001` actual JUnit has 22 tests, zero failures/errors/skips;
stdout reports 22 PASS in 1.00s. The result records exit0, 1.651662s wall and
unchanged fingerprint
`f69b01db0a09dbfe18fad36971f2f0a965edaad4859ec04f266ae0ecb248cb7f`.
Exact command: lewm Python3.14.7 `-m pytest -q` on
`test_program_request_helper_inputs.py`, `test_program_request_inputs.py` and
`test_program_input_origin_pairs.py`, with JUnit output in `green001`.
The command receipt explicitly records conda activation,
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=.`.

## 2. Reviewed source transfer

`request_inputs.py:58–92` adds `_helper_context_extension`:

1. `raw_calls` must be a strict, exact prefix of `input_calls`; an unrelated
   caller chain is not a candidate. The first downstream call's caller region
   must be the raw anchor's original region.
2. The original raw `OwnedUse` is resolved through the shared ProtocolFlow.
   `_fresh_copies` checks whether its canonical raw value is still present
   **before that first call**, rather than accepting a future pack or merely
   a same-type value. The per-flow `(raw,caller_id)` cache stores only this
   derived boolean/unknown; it stores no request/state identity.
3. Further nested calls come from the input's original actual→formal recipe.
   The helper receives no invented RAW formal or argument.
4. Metadata states `raw_argument_required=False`,
   `request_identity_verified=False`, `source_runtime_verified=False` and
   `transformation_authorized=False`.

Integration at `:169–212` keeps the existing same-context and physical-RAW
forwarding routes. The new extension is tried only when those do not match.
It does not bypass the existing exact original operand leaf check, the merged
operand/raw/input CFG-choice consistency checks, or any recipe whose evaluation
freshness is known false. It does not instantiate another ProgramIndex.

I found no concrete blocking contradiction in this narrow transfer. In
particular, the patch does not turn “some helper of the same callee region”
into the expected consumer: the input recipe retains its exact call chain and
the caller-region/prefix/choice checks remain in force.

## 3. Currentness and alias boundary

The fresh boolean concerns the original raw value's availability/copy at that
caller point. It does not mean current Task/session/occupancy, runtime request
identity or callback-preserved admission. Future P4 consumers still need their
independent expected trigger and current-state/gate obligations.

The `shared_operands=True` test intentionally keeps two possible static caller
contexts: the same canonical Reference operands are passed at both calls, and
the supplied raw anchor is available before both. Retaining both is correct for
this source-recipe query. It would be unsound for a future protocol consumer to
interpret `bindings` being nonempty as proof that one request instance was
selected. The false identity flags and `caller_scope_complete=False` accurately
preserve this limit.

Known unequal original operand leaves/ordinals still fail the match even if all
literal contents are None. A raw pack/anchor after the call is not accepted as
its current source. A helper computation that changes the Reference stops at
its own producer, as before; it is not treated as an ordinary copy.

## 4. Budget and path boundary

The extension receives the existing exact accounting object and flow. It
charges helper checks and suffix steps; new fresh-copy work uses the same
ProtocolFlow budget and cache. It creates no private 4096 allowance or unbounded
reachability search. The original context/choice processing also keeps that
budget. Unknown/failure from budget exhaustion does not produce an extension
dict; the outer query retains gaps, a cursor and TRUNCATED status.

The new budget1 regression verifies no binding and a retained cursor, while a
larger budget verifies the real reference-only path. Prepared-index reuse is
checked by making any new ProgramIndex construction fail in the test.

No new branch/loop runtime experiment was run here. The source review checks
that the existing choice/freshness logic is still executed after extension;
the focused tests are bounded evidence, not exhaustive caller/path coverage.

## 5. Actual focused denominator read

The 10 new cases are six arity1/2/3 × depth1/2 combinations, wrong ordinal with
equal None contents, late pack, two possible callers with shared operands, and
prepared-index/budget truncation. The other 12 green cases are existing request
and input-pair compatibility cases. The 22 cases are not P4's full denominator.
All original red/green logs are preserved; this report does not overwrite them.

## 6. Bound source hashes

The current files and both green before/after source maps agree on:

| File | SHA256 |
| --- | --- |
| `scar/ir/program/request_inputs.py` | `297415f7aeeb06bba0bdd7e1ac162919be6b85068e997d810427a872fd9ed062` |
| `tests/fixtures/program_request_helper_graphs.py` | `5a22755a426510966ae94ee14301760dbf2f86d622d9c0464a93f6ca0740a776` |
| `tests/unit/test_program_request_helper_inputs.py` | `5d05288c15e4e7d7968849fb4330cca170723e54371fa7cc2d578192434c925c` |

Relevant unchanged solver read:
`protocol_flow.py` SHA
`a3518f4fa83ceba2d748d0b7e5d44fbc1ac7c0f629e103d8aad3c0c852ba87a7`;
`input_origins.py` SHA
`6212a9aeb8a170387f102ba02be4ae480d641075e52232ded09ac5fca4866631`.

The remaining expected-source, trigger, full-input-tuple and consumer schema
choices in `delegate.md` remain Proposed. This small query repair does not
itself close delegation, await, native classifications, automatic recovery,
M0–M2, or transformation authority.

## Addendum: necessary-leaf filter moved before helper analysis

Read-only follow-up source SHA:
`request_inputs.py` =
`759e03338fe64e271163f9b3dff54e1e1f50c9e8b3abb51d51732da8a18c17a0`.
The earlier green001 fingerprint and 22-case results remain bound to the
previous `297415f7...` source, not to this follow-up source. Root owns a new
affected focused run; this reviewer did not execute it or assume its result.

At current lines172–173, the existing necessary condition
`operand_recipe['leaf'].id == input_recipe['leaf'].id` now filters before
`_helper_context_extension`, instead of after that helper. No other matching
test, expected source, caller prefix, CFG-choice join or freshness rule changes.

For equal leaves, the helper and all subsequent acceptance conditions are
unchanged. For unequal leaves, the old code could never append a binding;
skipping the helper cannot introduce a new binding for that pair. It avoids
fresh-copy work and cache entries for a known noncandidate. At finite budget
this can leave more budget for later valid pairs, and can omit an irrelevant
helper-context-unresolved gap formerly emitted before the mismatch was found.
Thus this is source-semantics preserving pruning, not a promise of byte-equal
diagnostics, costs, cursor position or finite-budget prefixes.

Bounded source-review conclusion: **no blocking issue in this move**. The
request-instance and source/native limitations above remain unchanged.

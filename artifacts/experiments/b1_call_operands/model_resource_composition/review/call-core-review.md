# Independent R3.1 call validator source review — OPEN

2026-10-18. This report preserves the first independently reviewed implementation snapshot.
**OPEN: one known-scope guard omission requires correction and an author-owned regression.**
No probe/test was run for this review; the construction below is a source-derived candidate,
not a claimed observed validation result. No product/test/fixture was edited during review.
The separately authorized canonical fixture smoke is not independent validator acceptance.

## Blocking source finding: missing entry bypasses known completion thread conflict

Reviewed `call_validation.py` SHA256
`2f9af86607a5ac107aafd3c935e2111c895107bbe6a89c73a62b63564c3300c6`.

The known synchronous thread equality check is nested only under
`type(row.entry) is BlockVisitID` (`:299–317`). `_terminal_kind` (`:95–121`) validates
completion occurrence/activation/RETURN-or-RAISE/exit, but not its segment's host thread.
The unresolved-entry branch (`:318–321`) checks only point run/process.

Minimal canonical construction for the author-owned regression:

1. Start from `invoke_call_execution()` (complete actual NORMAL path, or its RAISE variant).
2. Add a second known HostThreadInstance in the same existing process/run.
3. Assign the child activation's existing segment to that second known thread; the caller
   remains on the original known thread. All original child operations/Uses/definition
   visits, actual child completion and canonical caller completion remain unchanged.
4. Change only the association's `entry` to `Unresolved(reason, original same-scope
   EvidencePoint)`. The child completion still unambiguously names an existing segment
   whose known thread differs from the caller.

This does not need an invalid ID, a cross-process model, a fake CFG edge or an invented
work ticket. The current source no longer reaches the sole thread check, although a known
synchronous caller/completion thread contradiction remains. The root confirmed this must
be corrected and asked the author to preserve a regression's initial failure.

Minimal rule: check known thread scope independently of whether entry capture is complete.
At least known child entry **and completion** must match the caller's known thread; under
this synchronous profile, any other captured known segment of the child activation cannot
be used to hide a contradictory thread. Missing/UnresolvedHostThread stays a specific gap,
not a false mismatch; source FactRef equality does not establish thread identity. No new
record or lifecycle state is needed.

## Other inspected mechanisms / limits

- Entry: original static callee→activation.region, real InitialEntry/canonical entry block,
  owning activation and no incoming backedge are checked. Different provenance FactRefs
  are not treated as a strong event inequality. Missing entry preserves a row-local gap.
- Completion: only actual RETURN/RAISE in the selected activation, matching named original
  exit; ordinary calls cannot borrow a Raise. INVOKE compares the actual caller transfer
  kind. Missing transfer retains known child exit Uses and leaves caller formal/port None.
- Scope: process/run mismatch is an issue; unresolved point scope checks do not default
  unknown process to a match. One caller and one activation cannot be multiply assigned.
- Dynamic nesting: iterative indegree traversal detects dynamic cycles while allowing
  recursive static Regions with fresh activations. Visit-chain indexing is linear in
  captured visits/edges after the root preflight correction; empty call tables skip it.
- Inputs/results are projections of original call/invoke arguments and child exit Uses,
  not a new producer or copied state. Dynamic missing/Unresolved Uses and missing result
  captures are carried as gaps. State types/port arity and exactly-once CompletionResult
  routing depend on the already valid canonical core interface.
- Query wrapper returns detached original records/routes, strict ID families, DECLARED
  association status and false source/runtime/value identity and transform flags. Neither
  missing association nor same static callee selects a child. A same-scope **consistent
  permutation of whole associations** cannot be disproved by static IDs alone and remains
  conditional; this is not the known-thread structural contradiction above.
- Call completion does not seed any ResourceOutcome, quiescence, work-order, ready, borrow
  release or target retirement. Native work submitted by a returned/failed child can remain
  pending; the new table does not close native whole-work-boundary correspondence.

No additional blocking source issue was identified in these bounded reads. This does not
close final validator acceptance: re-read the author's thread correction and final hashes,
and inspect the actual author-owned regression result without rerunning its tests.

## Snapshot receipt

| Read source | SHA256 |
| --- | --- |
| scar/ir/execution/call_validation.py, full | 2f9af86607a5ac107aafd3c935e2111c895107bbe6a89c73a62b63564c3300c6 |
| scar/ir/execution/call_query.py, full | 9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42 |
| scar/ir/execution/calls.py, full | a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f |
| scar/ir/execution/validation.py, registry/hook/coordinate scope | e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d |
| scar/ir/execution/flow.py, original actual path/incarnation behavior | 2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 |
| scar/ir/execution/query.py, call/ordinary route wrappers | 94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a |
| tests/fixtures/execution_call_graphs.py, canonical fixture context, self-authored | 6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b |

The fixture is disclosed as self-authored and is not counted as independent source review.
Root's separate `review/root-core-preflight.md` was read for previously reported corrections.
No full regression, native/runtime proof, full R3/M0–M2 completion or LeWM speedup claimed.

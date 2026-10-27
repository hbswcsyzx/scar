# Root final source review: PASS_WITH_SCOPE

The original OPEN preflight remains in `root-core-preflight.md`. Reviewed final
call validator SHA-256:
`79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b`.
This receipt closes the specific source-review issues, not complete M0–M2.

- Visit-chain preparation is iterative and uses linear passes; empty call
  tables skip it. Segment/terminal indexes are prepared once per context;
  public caller lookup uses the derived caller index. This is not a claim that
  all validation, canonical CFG processing, port routing or copying is linear.
- Entry/completion views are original records or None, with the original
  association retaining exact IDs or Unresolved. Missing ends, observed
  unresolved input/exit Uses and missing caller transfer keep specific gaps.
- Different entry FactRefs or URI aliases are no longer treated as proof of
  different events. Exact run/process/activation/block/ingress constraints
  remain; source/runtime identity remains unverified even when references agree.
- Synchronous thread checks include every captured child segment, independently
  of whether the entry or caller thread is unknown. Unknown facts cannot waive
  two conflicting known threads. The original issue was source-inferred; the
  corrected boundary rejection was verified by `boundary_calls/attempt001`.
- Multiple captured RETURN/RAISE occurrences in one linked synchronous child
  are rejected, rather than selecting one and hiding the other behind a path
  gap. The new rule applies to these explicit synchronous associations, not a
  second general lifecycle state machine.
- Dynamic call cycles and duplicate endpoints are rejected. Static recursion
  through fresh activations is represented by a finite declared bool/base-case
  graph; this is not automatic recovery or runtime termination proof.
- Complete work Mat membership is checked for the exact ticket on content
  reads, writes and actual Mat borrow targets, not guessed from an allocation
  basis or another ticket. Original roles/Uses/state stay canonical.

Development receipts separately record 23 baseline core cases, 11 query cases,
10 independent boundary cases, 243 wire cases, and root's 148-case affected
interface check. These groups overlap and were not globally frozen; they must
not be added to invent a total. Final component and one clean committed full
run bind the entire source snapshot independently.

No new detector, backend, lowerer, LeWM rule, GPU run or speedup was added.
Original Q denominator, endpoint protocols and complete R3 composition remain
the next work, as the plan states. Same-scope pairs can be structurally
compatible even when falsely declared; all runtime/identity/transform authority
flags remain false. Original protected checkouts are checked separately.

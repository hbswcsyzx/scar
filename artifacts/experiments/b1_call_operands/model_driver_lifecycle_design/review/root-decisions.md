# Root review: D2 lifecycle connections

2026-10-18. Product/IR baseline: cc44e14 (D1 implementation 382363c).
This file records design decisions and objections, not new product capability.
No new pytest, workload, GPU profiling, or runtime adapter is executed here.

## Accepted constraints

1. Preserve five entity classes and canonical core Uses/StateAccess/CFG. Metadata
   refers to an existing operation/edge; it never creates state or a permit.
2. BodyOutcomeCommit is the first operation on the D1 private (drive, source)
   landing. Kind follows the exact source: Suspend remains a continuation;
   Return/Raise ends it. State writes use current source/forwarded state by
   LocationID; extra driver domains remain explicit and current.
3. D2 must not invalidate historical v11 D1-only graphs or call them lifecycle
   checked. A typed per-driver capability marker is a reasonable explicit scope;
   its presence is a declaration, not source/runtime proof or transform authority.
4. D1 lifecycle domains L are a subset of all driver domains D. Coarse WHOLE
   state can have reference=None: a real owner Use does not manufacture precise
   instance/field selectors. Owner-selector refinement remains its own M1 item.
5. Shared release/session operations after multiple valid completions are legal.
   A single declared predecessor anchor is too restrictive. Prefer deriving the
   last relevant anchors from actual CFG, with per-path owner/copy correlation;
   declarations must not substitute an origin candidate set for a must fact.

## Rejected proposals and reasons

- NoBodyFinish := any helper NORMAL. NORMAL does not imply the body is finished.
- Created-close check+mark INVOKE with RAISE for a non-Created receiver as the
  default decomposition. Ordinary close on a suspended body may validly enter
  it; a status-test false branch is not an actual propagated exception.
  The core reviewer proposed this and withdrew it after this counterexample.
- A transferable finish permit or a second general request-history state
  machine. The real control edge and StateVersion remain canonical facts.
- SessionUpdate NORMAL => post holds forever. A helper can write its post,
  release a reference, run a callback which changes state, then return normally.
  A post belongs to the exact after-state/edge and needs a real helper contract;
  unmodeled writes do not preserve it. RAISE may happen after the write, so it
  means 'no guaranteed post', not 'post did not occur'.
- One (owner, commit) pair implies only one legal reference-drop operation.
  Individual slots/bundles and traceback-owned references are distinct. A
  special terminal aggregate drop may be once per finish within its scope, but
  general duplicate-bundle proof needs selectors which the current coarse
  Footprint does not supply. It must not guess from code/site or common world.

## Nonraising no-body route under review

A typed metadata predicate over the current owner and effective request gives
an ordinary bool consumed by a real BRANCH. Its true edge privately reaches the
first NoBodyFinish state operation; false continues the real alternative path.
No callback/write occurs between test, branch and finish. No fake body Return,
synthetic exception, or physical allocation is added by the interface.

The effective request is not always the scheduler S. For BODY it may be S;
for ASYNC_REQUEST it may be the latent request read from the actual request
association, while S remains a separate current input. The exact role/source
contract and family-specific acceptance conditions still require resolution.
An unproven protocol remains a typed conditional boundary, not a success fact.

## Reference drop and session boundaries

A callback-free publication may be followed by callback-capable reference drop.
A wider native helper may remain opaque, with its own actual NORMAL/RAISE and
partial states; it cannot borrow the narrow FrameRules to swallow a real raise.
Narrow owner-reference drop preserves pending if applicable and completed,
permits unraisable effects/nontermination, and proves no free/finalize/ready.
The existing synchronous FrameModel has root/ENTER/local-slot/adjacent-exit
constraints; its whole validator must not be repurposed for a resumable driver.
Body DEL/rebind and later traceback drop remain at their real operation sites.

## Remaining review obligations

- Exact predicate inputs, actual-branch anchor and optional async association.
- Last-anchor dataflow: multiple incoming paths, cycles/reentry cut, same-path
  owner actual->formal forwarding, state updates and unknown callbacks.
- Session post target and invalidation; no generic HOLD/COMPLETE/ABANDON enum
  may silently claim complete protocol-family coverage.
- Terminal aggregate drop scope vs arbitrary slot/bundle; old schema migration,
  static-declaration flags, bounded positive/negative acceptance denominator.

D1 acceptance remains valid. Full D2/C2, M0-M2, automatic LeWM graph recovery,
simplification and workload speedup remain incomplete.

## Final review resolution for this archive

- BodyOutcomeCommit has no session post. Its nonempty write set W is derived
  from ordinary StateAccess entries, W subset-of L subset-of D; untouched domains
  retain current state. This is a conditional declaration, not inferred proof
  that a particular owner's native fields were updated.
- Prefer no explicit SessionUpdate/TerminalFrameRelease sources tuple. Derive
  alternatives from real CFG with per-path owner correlation. Exact invalidation,
  merge/cycle handling and aggregate-drop profile still need a frozen contract.
- Root compared every new lifecycle observation with its raw JSON. The initial
  adversarial review incorrectly said the second async close left CLOSED. Raw
  records say StopAsyncIteration and inspect AGEN_SUSPENDED. The original report
  is retained as adversarial.initial.md; the final report is corrected without
  rerunning or changing the probe. The script emits six observation records and
  contains no assertions. Its exit 0 is not six passed product/language tests.
- The separate session_release_probe has three actual assertions-based cases,
  all PASS in its recorded single run. These are ordinary Python helper examples,
  not proof that CPython's internal request fields are freely mutable.
- D2.0 remains OPEN at this checkpoint. docs/M1_DRIVER_LIFECYCLE.md is the next
  ordered gate plan, not an accepted product-field contract. No D2 code, new
  detector/backend, LeWM experiment, or speedup was introduced by this review.

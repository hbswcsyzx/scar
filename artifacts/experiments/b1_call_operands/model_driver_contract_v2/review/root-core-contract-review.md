# D1 driver contract core review

Review date: 2026-10-18  
Worktree: `/tmp/scar-structured-model-280qf4mi`  
Product HEAD: `499d708f9092a8bf35915e8db9a004631a223d7b`  
Reviewed contract SHA-256: `8910f63d2f40a200799e09caba1293be33af0e85d608eaa46e0891e6f912e64b`  
Reviewed implementation-plan SHA-256: `884dd4e2c795017d0ce33b6270baaf75f50c4b05f303c24f21d9fa4e1eb78593`

## Conclusion

The current D1 record shape is implementable over the existing operation Uses/results,
completion edges, BlockArguments, function/environment layouts, and suspension records.
I found no remaining field-level blocker that requires another protocol record before source
implementation starts. This is a structural declaration gate only: it does not prove a Python
source mapping, actual instance identity, dynamic guard execution, or transformation authority.

The earlier three concerns are resolved in the current draft:

1. `ResumableCreate` is explicitly a **post-binding abstract frame-create primitive**, not the
   original Python CALL's argument list. Its `invoke_arguments` contain already produced,
   bound formal/environment references. The source CALL, default lookup, argument packing,
   cell/environment reads, and their failures remain separate preceding operations. This
   removes the otherwise real mismatch between Python actual arguments and complete frame
   captures.
2. `BodyStart(body)` deliberately does not select one `Create` site. External instances and
   multiple compatible Creates can implement the same body interface. A known Create can be
   checked for compatible captures; an unknown source remains a declaration, not a guessed
   runtime instance.
3. Schema v11 is explicit, and the implementation plan now lists all seven new graph tables.
   v1–v10 must retain their exact old wire behavior and reject any new driver capability.

## Required D1 validator obligations

These are implementation acceptance conditions, not requests for additional metadata.

- Treat `CreationCapture` as an exact partition of the body entry's non-state Reference
  arguments. Each capture names a distinct formal and an owned Reference Use of the matching
  Create; repeated Python references remain separate formal occurrences/Uses. The function
  object capture must be the same canonical FUNCTION_OBJECT capture, not an extra implied
  operand. Do not infer missing default, pack, or environment producers.
- Resolve each `NormalResultPort` only against the owning INVOKE record's NORMAL signature and
  its actual completion edge. Create handles and async request/association results must land on
  the exact formal derived from that edge. Do not treat a site ID or a dominating value as the
  result.
- Enforce the final-gate corridor literally: unique paired Drive; private NORMAL landing with
  one incoming and exactly that Drive; exact independent Uses at gate, edge, and Drive; no
  intervening operation; no CompletionResult substituted for a forwarded owner/request/session.
  The RAISE edge is gate failure, not a body outcome.
- For ASYNC_REQUEST, do **not** require one separately represented `RequestAssociationRead`.
  The current body association may be obtained by a prior lookup/helper, an expanded CFG, an
  external boundary, or checked inside the final gate. A read record, when present, is useful
  provenance and its result/Uses must join exactly; by itself it cannot prove the association
  remained current after a callback. The closed `DriverRule` profile must declare that NORMAL
  admission checks the current request/body/session/continuation relation and that the body
  reference it checks is the one forwarded to this Drive. Without source/provider correspondence
  this remains a declared guard contract, not an observed fact. M4 must reject a claimed runtime
  instance mapping lacking evidence for that guard; no static `ValueID`, code identity, or
  same-location shortcut establishes object identity.
- Derive the driver region's state-domain set from the canonical core region interface. Require
  `DriverInterface.lifecycle` to name that complete set (or define it as that set in the
  validator); gate NORMAL and RAISE must each produce the current post-state for every domain.
  `BodyDrive.state_inputs` must cover the body region's exact state domains by LocationID, with
  no positional zip. Existing `validation.py` already derives `region_domains` and enforces one
  state argument per block and exit, so reuse that fact rather than maintaining a second domain
  calculation. The current text says the gate consumes “all current driver state domains” but
  does not state `lifecycle == region_domains` in one explicit sentence; make that equality a
  validator assertion.
- `BodyStart` has no resume payload; `BodyResume` names one exact Suspend successor and derives
  saved/private arguments from that Suspend's canonical slots. Resume's dynamic inputs are
  exact slot-indexed Uses. Existing `ResumeSuccessor` has exactly one non-state delivered slot,
  which is sufficient for this D1 contract; reject extra/missing slots rather than coercing them.
- Derive BodyDrive outcome signatures from the exact `body_outcomes(body, start)` frontier.
  Every finite first outcome has one distinct landing and source-specific edge; Suspend exports
  only its public value and handoff. A complete finite frontier is not a must-terminate claim.
  Reuse the pure frontier helper in validation rather than constructing `ProgramIndex` inside
  validation (the public index validates the graph itself).

## Current implementation hooks and limits

- `validation.py` derives state domains at lines 381–397 and checks INVOKE input/post-state
  coverage around lines 460–510. This is the canonical state source for the driver validator.
- `resumption.py` already provides exact `SavedInput`/`ResumeInput`, `ResumeSuccessor`, and
  `SuspendTerminator` records. `queries.py::ProgramIndex.body_outcomes` derives entry/resume
  outcomes and returns existing `UseSite` objects; it explicitly makes no runtime-execution
  claim.
- The current codec is schema v10. Driver v11 must add the new records/terminator/protocol
  markers to capability detection, strict decode, and historical-schema rejection, while
  leaving v1–v10 encodings unchanged for graphs without the new feature.
- `ProviderFactReference` identifies a provider artifact but does not attest that the running
  callable implements it. Keep CLI/runtime/source/transform verification flags false at D1.

## D1 versus later work

D1 can finish once the typed records, core joins, v11 strict wire, exact queries, and complete
Create→Start→Suspend plus Resume→Return/Raise declaration tests pass. No live Python object or
runtime driver is required to establish that structural contract.

D2 still needs outcome commit, no-body paths, request/session lifecycle, callback/nesting and
reference-release relations. D3 still needs source and runtime evidence across generator,
coroutine, async-generator, delegation, await, close, and cancellation families. Those are
material proof boundaries, but they do not block implementing the D1 structural fields.

No tests, workload, LeWM code, or product files were changed or run for this review.

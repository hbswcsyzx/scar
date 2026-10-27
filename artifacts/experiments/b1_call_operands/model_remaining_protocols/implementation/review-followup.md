# P4-2 intermediate review follow-up

This is a WIP archive receipt, not acceptance of the sixteen complete groups.
The implementation base is `add4ba84c9529e1f864e4029bd7c145cfacdfafc`.

## Independent findings and actual follow-up

- The records/codec review is preserved separately at
  `model_protocol_implementation/review/review.md`. Its own 377-pass attempt
  predates the final shared source changes. It found the package-level Any
  alias export leak; an independent child-process failure preceded the fix.
  Ten historical global version assertions now say19 while their exact old
  wire versions/fixtures remain unchanged. No execution schema was changed.
- A separate read-only reviewer found conflict handling inconsistent between
  bind and origins/available/request_binding. That finding was initially
  source inferred. The real `helper_diamond_program` then reproduced two
  failures in `shared/ambiguity-red001`, including availability returning True
  for two conflicting incoming visits. Shared selection-ambiguity handling
  now preserves a specific gap across all entries.
- The same reviewer found recipe_context ignored the False returned by the
  original caller/CFG context resolver. A recursive/loop graph reproduced
  the false-positive True in `shared/recipe-context-red002`, one actual failure
  at unchanged sources. The first attempt named red001 actually passed during
  root source edits and is not failure evidence. Its output was retained.
- Root source review found that leaf-only matching falsely rejected a real
  intermediate formal forwarded to a deeper helper. `shared/formal-red001`
  is one actual failure. The fix retains exact original formal steps and
  checks the anchor before the downstream call. Wrong ordinal and late-anchor
  negative cases remain rejected.
- Consumer discovery uses the same transfer engine with separate must/may
  caches. May is only an inventory over-approximation; it never enters input
  matching, state currentness or transformation authority. The nested merge
  fixture has possible consumers while every individual guard is insufficient.
  Joint exact original edge choices can prove the narrow route. Different
  visits to one merge require occurrence context and remain unresolved.
- A cross-region unknown consumer now retains a per-use inventory gap even
  when no positive route is found. This is source-level closure, not a separate
  executed native or runtime identity proof.
- Continuation testing first found invalid host references in a new loop
  fixture, then a real checker flaw: an unknown extraction branch returned
  before inspecting another branch's known repeated advance. Both failures
  remain; the checker now preserves unknowns and prioritizes known violations.
  The final own52-case run and root final selection cover the repair.

## Final scoped verification

`implementation/final-focused` executes 28 affected test files once at stable
sources: **694 passed**, zero failure/error/skip, 26.99 pytest seconds and
27.679291437 external seconds. There are694 distinct JUnit case identities.
All684 registered source hashes agree before/after:
`3af821cb7b9486a8f7b0befc89ed56747b3ef7dcb54abf91e79a7f9be5982459`.
This does not claim a complete component/full gate or automatic runtime recovery.

All original fixtures and both protected checkouts are checked separately by
`implementation/checkpoint.py`; that verifier starts zero tests. The old
encoder tar, command, hashes, failures and generated golden remain.335 verified
extracted/scaffolding copies (5,643,238 file bytes) were removed with an exact
receipt, avoiding adding a second old source tree to the repository.

## Remaining denominator

F12–F24 and X25–X27 remain the original sixteen groups; zero complete groups
are closed at this checkpoint. The async six-group and continuation/global
matrices list exact missing interfaces, cases and compositions. In particular,
independent bound-method lookups are not modeled by an atomic helper, request
reuse/competition and version-dependent close behavior remain incomplete,
and full two-cut/C1/session/release/P3 occurrence composition is still required.
No new backend, LeWM rule, heavy LeWM run or speedup is claimed.

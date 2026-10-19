# D6 finite independent review

Product author root; A/C/B authored only new tests/fixtures. All interpreters,
pytest and probes were reserved to root, serially, with authors frozen during
execution. C disclosed an earlier bare `python` editing command that failed
with command-not-found before interpreter startup; the edit used apply_patch.
No child interpreter, test or probe ran. This disclosure is not a test attempt.

## A: packet call carriers / protocol validation

The genuine ordinary CALL fixture exposed `protocol_definition_missing` in the
first-red log. Its own returned packet and original extractor were retained;
no fake PacketDefinition or NORMAL-only INVOKE replaced them. Admission now
checks this exact EXCEPTION_PACKET result slot against its known callee NORMAL
type. Local constructors retain their strict one-payload operation rule;
pending/cleanup protocols retain lexical rules. Prepared return-aware protocol
validation runs even when the three optional connection tables are empty.

A's additional seven cases cover good carriers, fake local CALL constructor,
primitive and unknown unconstructed packets, callee normal type/ordinal
mismatch, and a distinct same-typed packet passed through H without connection
attachments. All passed in review-regression. Its wrong-source case retains
the genuine await scope/profile, so this is not separately measured coverage
of the legacy has-capability=False preparation branch.

The first1551 attempt found two genuine regressions after protocol-stage
reordering: lifecycle derivation consumes NoEntry seeds before the delayed full
validator. Root restored pre-lifecycle structural foreign-key/route/edge/slot/
state admission without payload-copy authority, retained the full prepared
return-aware validator, and made locally unproved seed inputs non-authorizing.
A re-read both old rejection sites and the separate seed/full-check paths and
found no additional blocker in that fix. The local NoEntry seed inference still
does not refine through known-return summaries; legitimate release paths may
remain conservatively rejected. This existing limitation stays open. The86
local regression and final1551 pass are recorded, not substituted by review.

## B: incomplete flow cache reasons

Source review identified that a wrapper-only cache of newly appended gap events
could miss reasons when the iterative solver had already cached the same child
flow. A later source query on the shared context could turn an omitted copy
into False. This was a source-inferred risk, not a claimed failing runtime run.

The original ProtocolFlow cache now has metadata begin/replay/commit hooks.
Only the explicitly isolated consumer-bounds mode stores per-key missing
reasons; cache hits replay them into both the mode events and return-summary
gap stream. Default source_binding/validation mode remains unchanged. B's two
independent tests warm a recursive subflow, change to a genuine child source on
the same context, and check Reference/State downstream membership stays None
while pre-call input proofs stay True. Both passed in review-regression.

## C: budget work / incomplete effects

Source review identified eager query-time construction of every call/exit/slot
association outside the budget, plus repeated failed suffix checks. The
original-call/argument templates now belong to one ProgramIndex preparation;
no return joins are precomputed. Queries reuse that index, derive returns only
for reached child frames, and stop on the first failed charge. A failed
argument scan references the complete prepared unknown tuple. C's sentinel
test forbids query-time return-port access at budget1 and passed.

All original raw call anchors must still be presented under the frozen
budget1 contract. Preparation and raw output/serialization have separately
reported costs/counts; a derived-work budget is not a total CPU/output limit.
Incomplete operations with a live source now keep an explicit effects gap even
without a recorded matching Use; this last guard is source-reviewed, not a
separately reproduced interpreter failure.

Final finite closure replies: B re-read the original flow-cache hooks and
confirmed solver subjobs replay missing reasons, with no remaining blocker in
that scope. C re-read the ProgramIndex/raw-template split, metered child return
joins and live-source incomplete-effects guard, with no remaining blocker in
that scope. Both remained read-only and ran no interpreter. A's final carrier
review found no additional admission/validation blocker; seven independent
cases passed. These are bounded review conclusions, not full-model approval.

## Scope

No new entity/wire, source/runtime/value identity proof, detector/backend or
LeWM rule. Full provenance, cross-frame final-extraction semantics, original
A–H/16/P5/M2 and automatic complete LeWM recovery remain OPEN. Last finite
review replies and final source-bound focused/archival results are recorded in
the progress report rather than inferred from these local checks.

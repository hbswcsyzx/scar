# Independent root preflight: OPEN pending author correction

Reviewed the first `call_validation.py` source written by another agent, before
its fixtures or focused tests were ready. This is source review, not a test.
The later final receipt must identify the corrected hashes; this report stays.
Reviewed call validator SHA-256:
`2ec40356d5bc4238a3d5bada4468c6e7df3686d074f76a7facffc2dd119559e2`.

1. `_visit_chains` appends candidates using membership in the mutable `roots`
   list before any component is built. This makes preparation quadratic in
   visits. Use constant-time membership or two linear passes; empty call tables
   should not require building call-only chains. Cycle traversal is already
   iterative and should stay so.
2. `resolved.entry/completion` were IDs, while the agreed public route API and
   query tests require original records or None. Resolve actual records without
   minting another occurrence or translating an unknown end into pending.
3. Entry/completion/thread gaps were recorded outside the per-row route ledger.
   A public view must retain those gaps and explicit unobserved actual/exit
   Uses, not just the generic false runtime flag.
4. InitialEntry.source and RegionActivation.entry are EvidencePoints containing
   provenance, not a strong common native event identity. Different FactRefs
   or URI aliases do not prove different entries. Original scope/activation/
   block/ingress contradictions may be rejected; absent source correspondence
   should stay a gap unless a stronger original contract actually exists.

The new relation otherwise keeps canonical producers/Uses/state in the original
ProgramGraph and does not infer dynamic callee identity from matching values.
INVOKE's exactly-once CompletionResult requirement was checked in the existing
program validator (`completion_slots`); selecting each original slot is valid
under that precondition. No new backend or source recovery is present.

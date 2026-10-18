# R0 occurrence and identity reuse: final review

## Verdict

**PASS_WITH_SCOPE.** The final contract resolves the substantive issues from the
prior review: it defines canonical ProgramSnapshot bytes and ties the schema
version, size, and digest to those bytes; gives resume segments and host-thread
incarnations typed identities; scopes identifiers to their source artifact;
and reuses process/thread/allocation identities through a tagged
`ResourceTarget`. The document remains a relation contract: exact records, wire,
and validators are R1/R2 work, not existing product capability.

One narrow implementation boundary should remain explicit: a segment whose
provider did not establish host-thread incarnation must preserve that unknown
while retaining any observed block visits. Implement `ExecutionSegment.host_thread`
as a typed resolved-or-unresolved union (or reject the affected visit as
unresolved); do not invent `HostThreadInstanceID` from raw/missing `tid`. This
does not block the relation design, but the exact record/validator choice belongs
in R1.

## Checked corrections

- **Snapshot binding:** UTF-8, no trailing newline, canonical current
  `dumps(graph)` bytes; validate graph first, then compare schema/version,
  SHA-256, and size. Raw artifact formatting is separately identified rather
  than described as the same bytes. URI remains a locator, not identity.
- **Execution identity:** `RunID`, `ProcessInstanceID`, `HostThreadInstanceID`,
  `RegionActivationID`, `ExecutionSegmentID`, and `BlockVisitID` are distinct.
  A resume preserves body activation but starts a new segment; ordinary CFG
  transfer does not. Segment ingress is tied to an actual drive/suspend/capture
  port. Raw pid/tid and timestamps remain diagnostics, not keys.
- **Static graph remains canonical:** Operation/Value/Use/StateAccess and CFG
  endpoints stay exact references to `ProgramGraph`. Occurrences are derived
  from the exact owner visit/segment and static origin; a second producer/use/
  state chain is not introduced. Repeated uses such as `f(x, x)` keep separate
  ports even if their dynamic value occurrence aliases.
- **State and logical content versions remain distinct:** execution state refers
  to the canonical core `StateVersionValue`/`LocationID`; logical
  `ValueVersionID`, allocation, and materialization stay in ValueGraph. No
  identity join is inferred from equal payload, shape, address, or spelling.
- **Resource reuse:** static resource definitions/requirements remain distinct
  from instances and bindings. The tagged target reuses `StorageAllocationID`,
  `ProcessInstanceID`, and `HostThreadInstanceID` where appropriate; it does not
  mint a parallel `ResourceInstance` for an allocation/process/thread. A
  `CreatedResource` declaration is not runtime freshness proof.
- **Legacy evidence stays evidence:** v2 `OperationInstance`, `Materialization`,
  `CorrespondenceRecord`, `CallRecordAnchor` and old `ExecutionGraph` do not
  become core occurrences by type-name conversion. Their links need an explicit
  artifact/scope/evidence relation; many-to-many mappings are valid and do not
  by themselves prove timing, state effects, denotation, or readiness.
- **Unentered body and literals:** request/body creation does not fabricate a
  `RegionActivation`; literal equality does not create object identity.

## Scope and evidence

Reviewed only `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` occurrence/identity and
reuse clauses, against prior source inspection of `ProgramGraph`/codec,
`providers.py`, `resources.py`, v2 evidence/value/correspondence records, and
`call_edges.py`. No tests, workloads, product files, or contract files were
modified or run in this final review.

- Worktree HEAD: `309fb359be8665fc90979f270a6d4e4d20c6eb85`
- Final contract SHA-256: `afd291d40c8377b3e0af650310d369887c51cd1b617f8cbc423973edede32fb7`
- Final plan SHA-256: `5708b647e226335f02a6ac53b236063ae4b1dd9769e0d285a6e6730da40576a7`

## Final two-field closeout (2026-10-18)

A narrow follow-up checked only the two amendments below; it did not rerun tests
or reopen the broader review.

- `ExecutionSegment.host_thread` is now `HostThreadInstanceID |
  UnresolvedHostThread`, and the contract explicitly forbids inventing identity
  or thread ordering/visibility when thread provenance is absent. This resolves
  the prior unresolved-thread boundary.
- `ResourceAccessBinding.handle` is now the typed choice `ExplicitHandle(exact
  binding key) | ImplicitBinding(original rule/selection-state refs) |
  UnresolvedHandleAssociation`. This can represent an implicit current-resource
  selection without fabricating a `ValueOccurrence`; unresolved association
  remains explicit.

These changes close the two narrow reuse concerns. Final contract SHA-256:
`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`. The prior
review snapshot remains recorded above at contract SHA-256
`afd291d40c8377b3e0af650310d369887c51cd1b617f8cbc423973edede32fb7`; its
report snapshot SHA-256 was
`10c6713c38caf8a36fd3d36c8530332bc2adc66d63a831e34794f014823c1ed9` before this
append-only note.

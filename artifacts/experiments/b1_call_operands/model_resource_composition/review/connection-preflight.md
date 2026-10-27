# R3.1 materialization/record/query connection preflight

2026-10-18. **OPEN_WITH_SCOPE overall**: no blocking defect found in the materialization
membership changes, CallActivation records or the inspected query wrappers. This is a
bounded source review, **not** approval of call graph validation or full R3 composition.
No test/probe was run for this review and no product was edited. The separately authorized
new fixture batch and its five-variant smoke are recorded in `call_fixtures/report.md`;
those are fixture construction evidence, not this independent review's tests.

## 1. Observed materialization connection: source-review PASS_WITH_SCOPE

- `work_validation.py:23–43,53–59`: membership key is exact
  `(artifact.sha256,artifact.schema,artifact.size_bytes,MatID)`, excluding URI. Per-ticket
  sets are indexed once; another ticket cannot satisfy a missing member. URI aliases do
  not invent different physical/logical identities.
- On a declared actual placement/borrow, COMPLETE requires membership (issue
  `work_materialization_unlisted`); PARTIAL/UNKNOWN retains
  `work_materialization_unresolved`. This checks **associated Mats ⊆ declared set**, not
  equality with all physical runtime uses. Extra legitimately declared Mats are allowed;
  it does not infer an unprovided native access or claim capture complete.
- `content_validation.py:520–521`: exact ResourceConsumer's work is checked against the
  original read placement. Existing effect/input/work matching remains responsible for
  selecting this ticket; same host occurrence does not substitute for that match.
- `production_validation.py:160–162`: exact WorkWrite checks its original placement's
  Mat against the same ticket. HostWrite/ExternalEstablishment do not invent a Work to
  satisfy membership. An unresolved placement remains a specific gap.
- `work_validation.py:387–389`: only a retention whose **target** is MaterializationRef
  imposes that Mat membership. An AllocationTarget with a Mat used merely as allocation
  evidence does not declare borrowing that content version. Existing basis/allocation
  checks remain, without hardening an unsupported logical relationship.
- Work sets are prepared before D/P validation and copied with the execution context;
  refreshed external catalogs still undergo their separate snapshot/FK checks. This
  derived key index is not another producer/materialization graph.

Necessary focused acceptance (other owners, not run here): wrong-ticket listing; COMPLETE
missing read/write/Mat-target borrow; PARTIAL/UNKNOWN gaps; URI-alias identity; allocation
target with Mat basis remains legal; unknown placements remain gaps. The reviewed source
implements these distinctions; no actual runtime coverage or readiness follows.

## 2. Records and public queries: source-review PASS_WITH_SCOPE

`calls.py:14–49` uses a frozen/slotted exact record. Caller/activation/entry/completion
are namespace-distinct IDs; missing endpoints use typed Unresolved with a source point.
The record does not store another actual/result list or manufacture a completion.
Nested FactSource and IDs are rechecked through common exact helpers; model tables also
recheck exact row and tuple types (`model.py:102–113,134`).

`call_query.py:22–50` checks exact query-ID families and looks up only registered explicit
associations. It never scans activations for the same static callee, source span, ObjectID,
value or name. No association yields MISSING plus `call_activation_missing` when a static
callee exists; a non-call remains NO_DECLARED_CALLEE. A provided association is DECLARED,
including unresolved endpoints; this means a declaration exists, not that runtime pairing
or values were proved. Both returns are detached via deepcopy, with source/runtime/value
identity and transformation flags false. `query.py:164–172` simply exposes these helpers.
Existing `formal_route` remains a local CFG query; the new call view must carry distinct
cross-activation input/output routes instead of rewriting ValueOccurrence origins.

**Same-scope permutation boundary:** if two whole child associations have identical static
callee/signatures/process/thread and their entry/completion are swapped consistently, the
current declarations alone cannot prove which runtime call actually selected which child.
It must remain a conditional pairing with false identity flags. A duplicate child, wrong
activation entry/completion, wrong kind or wrong actual port is structurally checkable;
that is a different obligation. Do not claim the former is detected merely because all IDs
or source counts are unique.

## 3. Not signed off yet

`call_validation.py` did not exist when this preflight was assigned. It landed while the
separately authorized fixture was built; **its implementation has not been independently
read/reviewed in this report**. The validation hook at `validation.py:393–394` is observed,
but entry/terminal ownership, one-to-one pairing, dynamic cycles, process/thread, actual
INVOKE completion and exact argument/result routes await the root's final review task.
No automatic call-to-work native extent mapping is granted by this relationship.

The query consumes `ctx.resolved_call_activations`/`call_activations_by_caller` produced by
that validator. Thus its wrapper review cannot establish correctness of the resolved route
contents or missing-endpoint gaps. Root graph/query tests and final source review still
need to close that dependency. Endpoint flush/persistence, full R3 public denominator and
whole source/runtime correspondence are outside this preflight, not bugs attributed to
these bounded changes. No full M0–M2, transformation or LeWM speedup claim.

## Exact read-source receipt

Selective reading only: new membership helper/call sites and surrounding original guards;
full CallActivation/query modules; model/ID/common relevant declarations; public wrappers
and validation ordering; current R3 plan. No self-review of the agent-authored codec is
counted as independent here.

| File | SHA256 |
| --- | --- |
| docs/M1_RESOURCE_COMPOSITION_PLAN.md | 1d115816998115cd3a3f8893ea7b01d0d9ab0c260b4f4e11416a8128d2ebd3de |
| scar/ir/execution/work_validation.py | 1cccc760cb93268f4e282417e1d5fe8f1034870c474866237246ea7bae9e6984 |
| scar/ir/execution/content_validation.py | 92afdb38caf716c4187c4a2a9173207c8dc2cc6110a3fd3d83f22852b67ed49a |
| scar/ir/execution/production_validation.py | 6eda717b717581c91b9301fcb6995e199ae98fb2f618066f79dfe509819da256 |
| scar/ir/execution/calls.py | a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f |
| scar/ir/execution/call_query.py | 9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42 |
| scar/ir/execution/query.py | 94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a |
| scar/ir/execution/model.py | 14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126 |
| scar/ir/execution/ids.py | 3d5097166d01f177ec7295e74b74567c0a93ef2482cd371138d3e23578df7d29 |
| scar/ir/execution/common.py | a6a4287df931d21221be181023df0233f0b7b8cfbe0fdb69798fc9238ea2c0b8 |
| scar/ir/execution/validation.py, hook/order only | e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d |

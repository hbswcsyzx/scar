# P3 independent connection review and owned host-order receipt

Baseline supplied by root: `a740661`, worktree `/tmp/scar-structured-model-280qf4mi`.
This report preserves the initial read-only design findings and the later explicit
delegation of `host_order.py` plus two new test files. No git, full regression,
component gate, native probe or runtime capture was run by this author.

## 1. Scope and conclusion

The two natural keys in frozen contract §3 are sufficient for the proposed
relation. They do not need another owner, actuals, state or producer table.
Existing canonical occurrence flow and original static port recipes can be
reused. The missing work was precise projection and compatibility checking,
not a new resumable-kind enum or a second execution state machine.

Initial findings were sent to root before implementation. Root owns the new
body resolver/validator/query. This report does not independently approve those
whole modules, and the host module below is this author's implementation.
The bounded host implementation and its necessary original CALL compatibility
tests are now frozen; full P3/F/O/native protocol acceptance is not claimed.

## 2. Observed interfaces available for reuse

- `program/driver_flow.py::body_drive_target` resolves Start or the exact static
  Resume landing. `body_outcome_uses` excludes private saved slots. Neither
  helper grants actual frontier membership or runtime identity.
- `program/resumption_flow.py::first_body_outcome_operations` walks the original
  CFG, including C0/C1/INVOKE, and stops at the first Suspend/Return/Raise. It
  does not cross a temporal suspension edge.
- Original `ProgramIndex.drive_input_bindings/drive_bindings/creation_bindings`
  provide the static recipes. Start's `InstanceCaptureInput` is a recipe, not a
  guessed Create occurrence. Build one static index/cache, not one per Drive.
- `execution/validation.py::_Context` already owns exact `(occurrence, UseID)`
  bindings, `(origin, ValueID)` results, actual incoming/outgoing transfers,
  current state maps and expected definition maps for BEFORE/AFTER/EDGE.
- `execution/flow.py` already checks actual transfer targets, exact
  ResumeIngress, persistent activation, fresh visit incarnations and stale Uses.
  It deliberately has no common poststate for INVOKE/BodyDrive: actual EDGE
  formals retain the result and current state.
- `call_validation.py::_visit_chains` supplies component/rank for each actual
  linear visit trajectory, once. Actual transfers have at most one incoming and
  one outgoing occurrence. Reuse these chains for finite endpoint compression.
- `content_validation.py::content_errors` resolves `ctx.resolved_denotations`;
  `artifact_key` is `(sha256,schema,size_bytes)`, excluding locator URI. The
  exact existing ObjectRef/VersionRef resolvers should serve every binding.

The original flow checks each Use's current static incarnation; it does **not**
prove actual/formal object equality. Distinct formal and actual ValueOccurrence
IDs are expected across activations. Existing CALL views project ports without
being a general semantic copy oracle. A body copy resolver must follow only
original actual→formal recipes and exact observed transfers, with finite
memoized roots; opaque producers/heap reads stop the route with a gap.

## 3. Concrete decisions and counterexamples sent to root

### 3.1 All bindings and fresh identity resolution

Check owner, capture, saved, delivery, outcome and forwarded-state bindings
individually after content resolution. Same exact artifact + different ObjectID
is a declared Reference contradiction. Same ObjectID is only compatible
declaration. Cross-artifact identity remains unresolved. Data with the same
exact scoped VersionRef can be a declared same-version correspondence; two
different versions do not establish unequal contents.

Counterexample: two Drives each have internally valid ports and current Uses,
but their owner denotations name different ObjectIDs in one exact artifact.
Checking only each local binding misses the persistent activation contradiction.
Conversely, requiring identical ValueOccurrence IDs rejects every correctly
observed cross-activation formal.

Canonical structure can prepare once before external content. Identity results
must be refreshed after `content_errors` and recreated by the shared
`_external_stages/refresh_external_context` sequence. Construction-time external
compatibility cannot survive mutable catalog changes by shallow copying.

### 3.2 Missing versus contrary first-outcome path

Static first-frontier membership alone is insufficient. If the captured entry
BRANCH selects A, a disconnected B terminal must not become the claimed first
outcome merely because both are in the static frontier. Follow the captured
prefix up to its first body boundary; when capture stops, search only a
compatible static suffix. A known contrary prefix is an issue; a compatible
missing suffix is a gap. Cache static suffix frontiers, not a whole-model scan
for every Drive.

Entry unknown must not skip known outcome scope/thread/segment checks or the
contradiction of two captured first body outcomes in one selected segment.
Helper child activation Return/Raise is not a body outcome.

Root reported and source inspection confirmed a dedicated `_path` in the new
`resumable_validation.py`. Its product tests and complete validation remain
root/B ownership; this is closure of the design handoff, not self-run evidence.

### 3.3 Partial endpoints and current thread

An entry bridge does not require a captured outcome. A completion bridge can
retain exact outcome+actual Drive edge with missing entry/path as conditional
support, carrying those specific gaps. Known contradiction prevents the bridge.
Missing exact first operation, actual edge or known current thread suppresses
only its affected bridge.

Use the selected body segment's thread, not CALL's all-child-history rule.
Creation may be historical on another thread, and two Drives of the same body
may legally use different host threads. Same static region or same FactRef
does not select the persistent activation or prove object identity.

### 3.4 Mixed occurrence cycles, not an activation DAG

CALL body→driver and body-entry driver→body can form a strict causal cycle
while the CALL activation relation itself is acyclic. Conversely, two sequential
Drives of one persistent body repeat an activation without a causal cycle.

The implemented algorithm gathers admitted CALL/body bridge endpoints, groups
them by existing actual visit-chain component, sorts by visit rank/original
operation position/phase, and adds only adjacent strict local edges. Add the
original bridge edges and run Kahn once. Equality endpoints are deduplicated;
parallel bridge/local edges are counted and discharged consistently.

With P distinct bridge endpoints and B bridges, this uses O(P log P + B) time
and O(P+B) memory after the existing canonical indexes. There is no all-pairs
reachability, per-Drive whole-model traversal or O activation-DAG restriction.
Missing capture proves neither a global absence of cycles nor completion.
Explicit shared-budget exhaustion returns partial, never acyclic success.

## 4. Owned implementation and verification

On subsequent explicit delegation this author changed only:

- `scar/ir/execution/host_order.py`;
- new `tests/fixtures/execution_body_order_graphs.py`;
- new `tests/unit/test_execution_body_order.py`.

`prepare_host_order` retains original CALL rules and adds independent
`resumable-body-entry` and `resumable-body-completion` HostOrderSteps from root's
resolved canonical view. Completion support retains `canonical_gaps`.
`host_cycle_errors(ctx, *, budget=None)` is exported. Default validation is a
complete finite canonical preparation pass, separately counted. An explicit
budget is charged for endpoints, bridges, sorting, local edges and Kahn work;
truncation returns None and `host_cycle_unresolved`. No query allowance is reset.

New tests cover real Start/Resume including packet ingress, exact actual edge,
reverse/missing common AFTER, missing entry, missing outcome, missing transfer,
missing first canonical operation, unknown selected thread, legal thread change
between Drives, illegal current-thread mismatch, detached fresh containers,
shared-budget exhaustion and a real CALL+O cycle with valid original core.

The mixed-cycle fixture inserts an actual INVOKE in the body's Attached window,
keeps N/R private landings followed by a shared join, and forwards caller token
with distinct owned Uses. It retains current states and exact Suspend→Resume
transfer. Removing only the O associations leaves valid CALL/state/temporal
records and no cycle; restoring them produces `host_occurrence_cycle`.

No test treats host return as WorkEnd, device completion, readiness, flush or
persistence. Original CALL tests retain the explicit no-WorkEnd assertion.

Detailed first failures and commands: `../host-order/report.md`.

## 5. Source receipt

Hashes are of actually read source. Root-owned modules may subsequently change;
this receipt is not permission to reuse stale external derivations.

| File | SHA256 |
| --- | --- |
| `docs/M1_PROTOCOL_CONTRACT.md` | `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac` |
| `program/driver_flow.py` | `1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa` |
| `program/resumption_flow.py` | `c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc` |
| `execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `execution/flow.py` | `e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc` |
| `execution/call_validation.py` | `9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2` |
| `execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `execution/content_validation.py` | `e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f` |
| `execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `execution/validation.py` | `cb406b8fba26d0dbae306aff6c42918661e5629c0dcad0ecd24d6bf9fdb3293c` |
| `execution/resumable_flow.py` | `e74ce73938bca668c4690b0f2df2e1c5278f34a11a8b5963a7fbaf85896bcca9` |
| `execution/resumable_validation.py` | `670750af064b5f865979edf59819a19045bedadbc341830a2b45df8c19b1f318` |
| `execution/host_order.py` (owned) | `c4578ff1cf51b7ac922453a8e89e951a5c2393ac63d4817ebaa8bd029e659a91` |
| `tests/fixtures/execution_resumable_graphs.py` (B) | `456a35baaac263a2b812eea8646c30bcfd8a84ec7b8cf5a6d7b7ccb9abdbde3a` |
| `tests/fixtures/execution_body_order_graphs.py` (owned) | `c9c09b093497be480de398c405629c50b10ca9120d384062615ec91ad23b17c1` |
| `tests/unit/test_execution_body_order.py` (owned) | `435ddfe03e53330940cefff164a48773f2d0d6d6535a0594e3d01d9f824ea610` |

The 26-case final focused set is 11 new cases plus 15 original CALL compatibility
cases. It is not 11+26 distinct cases. It is not P3's whole denominator, a native
capture/identity proof, F/P4 completion, M0–M2 completion or transformation authority.

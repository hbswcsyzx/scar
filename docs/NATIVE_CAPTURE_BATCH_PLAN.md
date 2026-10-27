# Native capture batches with shared typed interfaces

2026-10-25. Design only. No production change or new source gate is authorized
by this document. The implemented 16-prefix gate remains a bounded reference
result; full first-stage program modeling remains OPEN.

The next producer should account for every dispatch attempt in a closed capture
through the existing ProgramGraph, ExecutionModel, ValueGraph and EvidenceGraph.
It should bind ordinary coordinates once, acquire one live source owner, discover
the complete static interface catalog, then emit bounded actual execution shards.
No saved report, source index, previous PASS or arbitrary token recreates that
owner. Eligibility depends on source profiles and observed slots, never workload,
repository, model, function or business names.

## Present constraints and observed inputs

`NativeProtocolWindow` explicitly requires a prefix starting at 1 with at most
16 sequences. Removing those checks alone is insufficient:

* `_stream_source` fully hashes three sources on every call but retains only
  262,144 prefix bytes. `_prefix_lines` and `_eto_prefix` use that prefix and a
  final ETO root sentinel; they cannot navigate arbitrary later batches.
* `_closure_ordinals` recovers first-seen objects, physical regions and allocation
  ordinals from prefix iteration. It treats the separately checked ETO root as
  the last original ETO ordinal. A later slice cannot recover those global
  ordinals or ancestors from its local order.
* `replay_interfaces` builds dictionaries from the whole supplied window, scans
  native nodes for each sequence, and assumes the complete selected records are
  available. Some missing normal groups become frontiers; identity contradictions
  raise instead of being repaired by another matching strategy.
* `_OwnedNativeCapture` currently detaches a canonical source dictionary;
  `source()` decodes it again, and evidence resolution revisits source/interface
  arrays. Enlarging that dictionary to a whole capture would repeat substantial
  copying, parsing and searches.
* The order checker reconstructs its DEFINITION_GRAPH artifact from its interface
  list and requires the exact expected activation inventory. A shared catalog
  plus a shard subset needs two explicit domains: all static definitions and the
  actual interfaces in that shard. Passing only the subset changes the definition
  artifact SHA; passing all activations rejects a correct partial execution.
* ProgramGraph bytes include provider artifacts, their URIs and run scope.
  Calling the existing builder independently for every slice does not create a
  single shared ProgramSnapshot.

Read-only metadata for the reference capture declares 39,796 attempts, 119,388
dispatch rows, 310,412 ETO nodes, 132,445 physical rows and 109,288 physical marker
argument slots. The three native sources total 546,619,922 decoded raw bytes.
The collector is closed; dispatch metadata declares zero dropped events/errors.
These are declarations inspected here, not a newly completed full semantic pass.

Physical metadata declares 108,682 slots with an epoch reference: 606 slots lack
that witness. This is a slot count, not a count of failed calls, and their ATen
domain membership is not yet known. It also explicitly permits preexisting
storage without an allocation birth. Neither widening the window nor retaining
a provider epoch makes a missing birth/extent known.

The original partition manifest is 72,965 bytes, SHA256
`a7b23bdb385b50522e6401433a8308343a593a4080288f3502d6e338e1e4b1b6`.
Its four relevant tables are an upper bound on selected source-record traffic:

| Original table | Records | Chunks | Decoded bytes | Stored bytes |
|---|---:|---:|---:|---:|
| evidence.instances | 461,242 | 76 | 1,200,966,077 | 76,212,360 |
| values.objects | 41,993 | 4 | 54,018,019 | 1,304,314 |
| values.regions | 108,682 | 9 | 142,927,166 | 7,693,289 |
| values.allocations | 74,955 | 6 | 92,998,937 | 5,834,508 |
| Total | 686,872 | 95 | 1,490,910,199 | 91,044,471 |

Other archive tables are not required to invent additional relations. Whole
bundle metadata totals 195 chunks / 2,982,489,343 decoded bytes; the next producer
must not rebuild or semantically load that complete legacy bundle.

## One live owner and a bounded source index

Add a separate capture-batch entry rather than silently increasing the reviewed
prefix API's hard limits. It accepts live ordinary CaptureCoordinates, explicit
capture directory, exact native partition manifest and capture-model hint with
expected SHA, fresh output, independent source/index/shard budgets and progress.
Run identity and attempt count derive from those sources, not a configured
39,796 constant. The reference count is an acceptance fixture only.

One ordinary coordinate bind runs before native acquisition. Reuse that same
live object across this batch run; do not deserialize a coordinate report as a
replacement. Check its payload/hash, membership, target process and Run exactly
as today. Coordinate binding and native ownership remain separately measured
verification scopes. The minimal change still has one coordinate pass and one
native-owner pass over overlapping inputs; it removes repetition per shard.
A future verified-reader handoff from the coordinate binder would need a separate
review and is not a prerequisite or an implied cache shortcut here.

During one native-owner acquisition, stream/decompress/hash the three complete
native sources and simultaneously build private navigation indexes and bounded
record spools. Validate full document closure and EOF, exact bytes/SHA, original
JSONL line indices, schema/version, process/nonce, closed counts and metadata
cross-links before making the owner usable. Parse ETO as a complete supported
JSON document using incremental bounded object decoding; do not extract text
that merely resembles a nodes array or trust a suffix root search for the full
domain. Duplicate JSON keys, node IDs or markers and malformed trailing bytes
are failures. An oversized source record stops with a retained budget result;
it is not skipped under a successful full-domain claim.

The private indexes map original coordinates, not new semantic IDs:

* ETO node ID -> original nodes-array ordinal, detached node bytes, original
  parent ID, RF/thread attributes; parent -> exact children and marker name ->
  unique original node.
* Dispatch sequence -> original BEGIN/OUTPUT/END or observed exceptional rows,
  original line locators and exact held-reference records.
* Physical marker -> original row/argument coordinates; allocation epoch key ->
  all observed allocation/free/birth witnesses, with process/device scope.
* Original archive record ID -> table ordinal and verified manifest/chunk/line
  locator. This is only a navigation index; ordinal or ID agreement alone never
  qualifies a record's meaning.

SQLite or bounded JSONL plus a byte-offset index can store those envelopes;
neither is an alternative IR. Keep original row/node order and full detached
bytes needed for replay. Hash private spool chunks while building them; retain
their seals in the live owner's memory and verify a spool chunk before use.
Original paths are not reread later as if unchanged, and inode/mtime equality
does not replace verified owned bytes. Metadata, raw hashes, coordinate identity
and index seals all belong to this exact acquisition.

Only the source-owning reader creates the private owner after all acquisition
checks close. A shard lease is derived by this live owner for an exact bounded
sequence set and complete dependency closure. It carries no caller-provided
`valid=True`, restored status or reusable public constructor token. Index files
and saved shard manifests cannot mint an owner after restart: a fresh process
reverifies original inputs. This preserves the current ownership protocol;
it is not a cryptographic sandbox against arbitrary code in the same interpreter.

Read each required original archive chunk through `BundlePartitions`' existing
stored/decoded SHA/bytes/newline checks at most once while preparing the private
record spool. One `iter_records` scan of each of the four named tables is a
simple conservative implementation, bounded by the table totals above. A more
selective plan may reduce it, with exact original locators. Repeated batches
must not call uncached `selected_records` for the same whole chunks. No archive
receipt is reinterpreted as runtime ownership or whole-bundle revalidation.

## Discovery, shared program and actual shards

Preparation first classifies the complete dispatch domain against indexed raw
records and checked original archive rows. Cache pinned schema parsing by exact
provider revision plus raw schema string within the owner; retain original
boxed-tree/slot checks for every occurrence. Build indexes for direct-child
selection and actual Value/Use lookup instead of repeated whole-domain scans.
Discover source-qualified flat signatures once, deduplicated by the existing
canonical signature SHA. Actual container paths and arities remain part of that
signature; distinct observed layouts must not be collapsed under a schema name.
Store the replayable witnesses, not a success flag used as later authority.

After discovery closes, write one complete `native-interface.json` and construct
one genuine typed ProgramGraph catalog with existing NativeBoundary, formal
BlockArgument/Use, CompletionResult/Return and opaque world records. Use the
DEFINITION_GRAPH schema provider and the original ETO EXECUTION_EVIDENCE provider
with the full declared capture observation scope. Validate/serialize it once,
then freeze its exact ProviderArtifact, URI, SHA, size and schema version.
Every shard's ProgramSnapshot references that same record. Do not grow the
catalog after earlier snapshots were sealed. A newly discovered signature after
closure is an error requiring a new catalog/output, not a hash-preserving append.
An output relocation can change URI-containing program bytes; reproducibility
must retain the chosen publication URIs or explicitly produce a new identity.

Execution shards are ordinary complete ExecutionModel documents, initially
bounded by at most 256 attempted sequences and independent byte/leaf limits.
Sequence boundaries choose storage units; eligibility never depends on them.
Each qualified normal invocation keeps the existing run-qualified actual IDs:
activation, segment, entry/normal visits, invoke/Return occurrences, values,
Uses, normal transfer and native evidence binding. Never renumber sequence IDs
locally. Repeated Run/process/thread context must be byte/ID consistent; include
the exact referenced coordinate records and preserve unresolved thread gaps.
An all-frontier shard has no invented invocation; it may be an accounted ledger
entry without an execution artifact, or a valid empty ExecutionModel if the
existing validator permits it. Do not require `interfaces` to be nonempty.

For the initial extension, actual raised calls, unsupported domains, missing
held slots and unsupported schema/container layouts remain explicit frontiers.
Do not map them to the possible static normal/raise branch as if that branch was
observed. Supporting a genuine exceptional occurrence later requires the same
typed exceptional completion and exact source evidence; it is a separate
capability, not a reason to remove that attempt from the denominator.

## Complete closure and qualified namespaces

Follow every selected original child/span/output marker's `ctrl_deps` to its
actual root using the full ETO index, even when a parent appears later in the
file or belongs to another batch. Check parent existence, cycles, process and
exact original parent record. Archive navigation follows full original table
ordinals, never window-local first-seen order, guessed offsets or ID spelling.
The capture-model hint may navigate; raw node/line and original record fields
must independently agree. Missing or contradictory parent identity cannot be
fixed by attaching to a convenient root.

For each held tensor, recover its existing original ObjectInstance, region and
physical epoch by exact source coordinates and independently compare the full
record fields already checked by `_project`. Include all ordinary ValueGraph
dependencies and native EvidenceGraph parents needed for each shard to validate
on its own. A provider epoch without a required birth/extent remains a frontier;
do not synthesize an allocation. Check birth uniqueness and lifetime/device
scope across the entire source, including cross-batch occurrences and frees.
Retain `PINNED_TORCH_LAYOUT_V1` as an explicit derived layout rule with the full
original region record, not a claim of byte-identical projected layout.

Publish ordinary closed source projections per shard. Duplicated ancestors or
objects retain exact original IDs/records and original manifest/chunk/row/raw
witnesses, but each projection has its own artifact SHA and qualified namespace.
The same original object in two projection artifacts does not make their typed
ObjectRefs equal. A source-line/record identity map can document common origin;
it grants no logical content equality, persistent storage association or alias
completeness. Cross-shard world states are not connected into a fabricated
complete memory history. No new IR, versions, provenance, materialization or
resource-ready fact is created to make coverage counters increase.

Do not concatenate shard JSON documents and retain one shard's hash. There is
one shared static program and many independently sealed execution/projection
documents. A storage manifest binds their exact artifacts, sequence sets and
Run; it is not another execution/state IR. Any future merged ExecutionModel
would require fresh ordinary validation, its own canonical hash and an owned
scope for that exact merged model.

## Independent order checks and proof scope

Separate the production checker's inputs into the full source-replayed static
signature catalog and the exact active source-replayed interfaces for this
shard. Reconstruct and verify the shared definition artifact against the former;
check original formals/invoke Uses, normal CompletionResult/Return Uses, scalar,
reference and world positions across those definitions. Check actual occurrences,
Use/value ordinals, normal transfers, tensor denotations and exact activation
inventory against the latter. Extra/missing/duplicate activations reject.
Generic NativeBoundary/provider representation contracts remain unchanged.

The owner independently replays a shard's exact raw source records at evidence
construction. Bind evidence to full program SHA, exact execution SHA, Run,
source-owner identity, shard sequence set and projection artifacts. `require_scope`
retains its exact checks and the appropriate order checks. Optimize static
checking only against an owner-held immutable canonical program seal; a mutable
caller graph or another catalog cannot inherit that result. Per-denotation
resolution uses bounded indexed records rather than decoding the entire capture.

Retain the attempt03 critical negative: mechanically swap two existing tensor
boundary ports and consistently remap denotations, validate the candidate through
ordinary generic validation, seal its own new snapshot/model, then pass it to a
fresh constructor using this run's live genuine owner. It must raise
`NativePortOrderError`, not merely reject an old scope hash. Test input/output,
scalar/reference/world and actual Use/transfer ordinals; also reject a wrong Run,
wrong shard, stale catalog, substituted source/projection, missing ancestor,
duplicate activation and unavailable birth. Without owned proof the original
unverified-correspondence gap remains. These are future acceptance requirements,
not tests run by this design review.

## Full-domain acceptance

Publish one accounting row for every original sequence `1..dispatch_attempts`,
with original row locators and either a qualified artifact/activation reference
or an explicit frontier reason and evidence. Preserve exceptional, non-ATen,
missing-slot, missing-epoch/birth and unsupported-schema attempts. Record multiple
causes when useful with a deterministic primary classification. Fail acquisition
on source integrity/identity contradictions; do not downgrade a mismatched hash,
nonce or corrupt original parent into a harmless supported-coverage gap.

Acceptance requires all of the following, measured from newly verified inputs:

1. Exactly one coordinate bind and one live native acquisition per batch run;
   every participating raw source is verified through EOF, with separate decoded,
   stored, spool, archive and output counters. No per-shard raw rehash/rebind.
2. The accounting sequence set equals the declared full domain exactly: no
   duplicates or omissions; `qualified + frontier = dispatch_attempts` and
   `unvisited = 0`. For this fixture the sum is 39,796, never an eligibility
   constant or a promise of 39,796 qualified calls.
3. Each qualified occurrence belongs to exactly one shard and preserves its
   original run-qualified ID. All shards reference one frozen ProgramSnapshot;
   source projections have complete ordinary closure and exact original
   manifest/chunk/row/record witnesses. Shared ancestors do not duplicate actual
   invocations in the accounting total.
4. Core, generic execution, external projection, source-owned reference and
   independent static/actual ABI-order validation pass for every qualified shard;
   all gaps and frontier reasons remain published. Critical newly sealed wrong
   order rejects specifically as described above.
5. A final aggregate manifest is published only after all shards and accounting
   checks finish. Interrupted/budget-exceeded runs retain exact progress and
   remaining sequence obligations and do not claim full-domain success.

Call the result full dispatch-domain accounting/reference coverage with explicit
frontiers. `whole_model_established`, complete state effects, logical contents,
alias completeness, resource readiness and transformation authorization remain
false unless separately established. Even zero unvisited dispatches covers only
this collector's owner process/thread and capture interval; it does not prove
all Python/native calls, other threads/processes or the whole program.

## Budgets and implementation boundary

The following are proposed caps or **Inferred** planning estimates, not measured
full-domain runtime results. Discover actual signature/slot/closure distributions
before finalizing an execution gate. Existing prefix limits remain unchanged.

| Scope | Evidence or proposed bound |
|---|---|
| Coordinate verification | Measured earlier: 1,261,870,214 decoded / 118,910,986 stored bytes; run once |
| Native owner acquisition | Metadata: 546,619,922 raw bytes; proposed 600,000,000 cap, one acquisition |
| Original four-table scan | Manifest upper bound: 95 chunks, 1,490,910,199 decoded / 91,044,471 stored bytes |
| Combined decoded input representation | **Inferred:** approximately 3.30 GB for the preceding three scopes, excluding private spool reads and codec work |
| Execution output volume | **Inferred:** about 2.25 GB if the 13-call prefix's bytes/call extrapolated; that sample is not representative and supplies no upper bound |
| Attempt-based shards | **Inferred:** at least 156 at 256 attempts/shard for this fixture; byte/leaf/closure splits can increase this count |
| Proposed per-shard caps | 256 attempts, 64 MB execution JSON, 64 MB value projection, 128 MB evidence projection, 256 MB verified chunk traffic, explicit leaf/record/depth caps |
| Proposed shared caps | 64 MB canonical program, 4 GB private source/index spool, 8 GB total published output, 16 GB free working space |
| Proposed process/time envelope | 2 GiB RSS abort threshold, 60 s per materialized shard and 1,800 s whole run; all **Inferred**, requiring freeze and first-run measurement |

A single pathological invocation/closure that exceeds a shard cap is retained
as a budget frontier with exact obligations; do not silently enlarge limits or
split one invocation into independently claimed occurrences. Spool capacity
failure, incomplete discovery or source integrity failure prevents a full-domain
completion claim. Disk use, peak RSS, all rereads/decodes, validation time and
output sizes must be measured rather than attributed only to raw input bytes.

Minimum implementation changes after the next source-freeze window opens:

* Add one generic batch orchestration/index module under `scar/trace/`; its
  records are storage/navigation envelopes around existing source and IR types.
* Change `native_protocol.py` to factor verified source acquisition, complete
  discovery, closed projection and shared program construction from one-window
  execution emission. Preserve the current bounded public entry and hard limits.
* Change `native_port_protocol.py` for a live capture owner with bounded shard
  leases, indexed replay, and distinct full static versus actual shard order
  domains. Preserve constructor sealing and exact scope rejection.
* Reuse `BundlePartitions.iter_records`, the pinned native schema parser, core /
  execution validators and codecs. No change to `bundle_partitions.py`,
  `native_schema.py`, generic execution validation or content validation is
  needed for the first conservative design. A cache API is optional future work,
  not grounds for bypassing existing chunk receipts.

The two existing modules above are among the six newly delivered sources.
Notify root and wait for its next dependency-freeze window before changing them.
This design review edits neither them nor historical artifacts and runs no gate.

# model-run offline P0: first executable automatic chain

2026-10-25. Root approved the two-file P0 implementation; the G0 entry and legal
monolithic G1 API chain are implemented, with the real G1 gate reserved for root.
Worktree:
`/home/zyf/AAA/scar-worktrees/structured-program-model`.
Initial review label0c809ecb; root subsequently supplied e5343347/792b1228.
Exact selected API source bytes/signatures are recorded in API_RECEIPTS.json.
No production/doc-state changes, target execution, trace scan, graph decode or
public modeling gate was performed for this design.

Implementation status: root ran the initial G0 session63296 against a retained
CPU capture. It returned exit2/BLOCKED at declared271 calls above default256,
after reading4 metadata files/43,954B and raw0; codes9/raw declaration19,119,646B.
That original output remains unchanged at
artifacts/experiments/model_run_offline_g0_20261025/model. Root explicitly approved
`--max-calls512` for the next G1 attempt; the command's default remains256.
Only AST/import/signature/CLI-help checks were run by the implementing agent,
without opening capture streams, importing Torch or executing a target.

## First patch and command

Only `scar/cli.py` plus new `scar/analysis/model_run.py`.

```text
scar model-run --from-capture CAP --out RUN [explicit stage budgets]
scar model-run --from-capture CAP --out RUN --plan-only
scar model-run --from-capture CAP --out RUN --resume
```

P0 consumes an existing successful capture of the currently supported retained
collector layout (`trace/`, `os/`, one unambiguous execution manifest). It never
launches CAP's command, imports a workload package, or takes a function/body list.
Unsupported capture layouts still receive an explicit failed-stage report.
The existing `scar model` remains the old static interface; this new command
does not invoke its candidate/detector/optimizer path.

P0 deliberately uses the legal **monolithic ProgramInventory8** bootstrap and
fresh source binding. It mechanically writes existing normative graph products
and a read-only workflow root linking their exact receipts. This is a partial
first automatic chain, not a replacement or requalification of the current
858 partitioned production route.

## Exact automatic inputs and provenance

1. Canonicalize CAP/RUN; reject aliases, source/input/output overlap and an
   existing RUN without `--resume`. Read bounded protocol headers: launch/run
   declaration, execution manifest, call metadata and declared archive roots.
   Fixed protocol filenames are layout rules; no experiment/PID/business paths
   are embedded. Every input keeps original URI/bytes/SHA and field locator.
2. Record command/cwd separately. `trace/run.json.command` is a launcher
   declaration, not a target-exec cwd witness. Where an explicitly declared
   collector witness exists, call `bind_collector_execution_witness(...,
   expected_sha256=declared_sha, coordinates=...)`; its registration-context
   argv/cwd remain scoped to that process/point. Never use analyzer `Path.cwd()`
   or project_root as the missing target cwd. Missing/ambiguous fields stay OPEN.
3. The recorded call metadata's project_root is the source-analysis boundary.
   Canonicalize it without expanding to `/` or a common ancestor of unrelated
   dependencies; disagreement across process declarations is an explicit scope
   block. Do not infer actual sys.path from candidate source roots.
4. Call `read_call_source_seeds(trace, project_root, budget=CallEdgeBudget(...),
   compilation_profile=RECORDED_FUTURE_FLAGS)`. This public function needs no
   entry file or historical report. It validates the original calls and returns
   typed observed codes/links/group counts. From verified, canonical local
   `.py` links derive the source catalog. A confirmed command entry is retained
   when available; otherwise choose a deterministic verified local filename as
   **analysis_seed**, keeping command-entry unresolved. This seed is not a claim
   that that file was `__main__`. Generated/frozen/missing filenames are retained
   as their original frontiers. If no seed exists, capture modeling can finish
   with a blocked source stage; do not invent a source file.

## Actual public call chain

Each arrow publishes a fresh immutable stage output; exact signatures and
source SHAs are in the companion receipt, not inferred pseudo-APIs.

1. `import_capture(CAP, RUN/capture, schema_contracts=True,
   bundle_partitions=True, os_interface_work=True, max_bytes=..., max_lines=...,
   progress=...)`. Its existing coordinate/provider checks and native/OS
   importers produce `scar.capture-model/1`, original bundle partitions and OS
   interfaces. Their OPEN obligations are retained. Missing provider/schema
   contract produces a failed/blocked stage, not a fabricated imported domain.
2. For source stages obtain a genuine `CaptureCoordinates` with
   `bind_capture_coordinates(CAP, ..., profile_uri=RUN/source-coordinates.json)`.
   P0 accepts the repeated membership read because `import_capture` returns a
   report, not the in-memory object. It must not reconstruct an owned object
   from JSON or add a trusted flag to avoid the read.
3. Derive analysis seed/catalog by the public seed function above. Call
   `inventory_program(analysis_seed, project_root=recorded_root,
   source_roots=(), calls_trace=CAP/trace,
   body_profile=BodyLoweringProfile.STRUCTURED_ENV, ...typed budgets...)`.
   Call-driven discovery combines the lexical import closure with verified
   observed sources. Persist its existing `ProgramInventory.to_dict()` as
   `inventory.json.gz` with an explicit serialization byte ceiling; atomically
   publish after closing/hash. P0 records measured compiler/lowerer work and
   does not promise compile0 for a fresh offline analysis.
4. `reconstruct_source_layers(inventory_path, RUN/source-layers, ...)`, then
   `compose_program(inventory_path, RUN/source-layers, RUN/source-composition,
   ...)`, and construct `CompositionIndex(index_path, ...)` normally. These are
   the original source/canonical products, not a wrapper pretending to be a
   ProgramGraph or an empty ProgramSnapshot.
5. `bind_source_invocations(composition, coordinates, CAP/trace,
   RUN/source-bindings, call_budget=..., witness_mode='same_capture')`.
   Fresh binding has no previous-source requirement. Keep every group/call and
   unresolved parent/source/body. Never pass fake history to
   `connect_current_capture`, which is specifically a prior-proof reuse API.
6. Resolve workload compiler archives by explicit source-origin and complete
   code/snapshot keys. Collector callback archives have the **collector** role;
   they are not assumed to contain workload code. If a declared workload archive
   exists, open it read-only with its declared manifest SHA. If absent, P0 may
   create one fresh owned `CodeWitnessStore(..., create=True,
   compile_missing=True, producer=...)` under an independently approved small
   budget, and call `resolve(captured, snapshot, optimize_levels,
   allow_compile=True)` only for exact observed VERIFIED links. Compilation
   never executes modules. Reopen read-only and require full descriptor matches;
   acquisition/version/source failures remain per-code OPEN. No historical
   archive is appended or relabeled. This resolves origins; it does not make
   monolithic P0 eligible for the newer partitioned frontend.
7. `RUN/model-run.json` is a small workflow report linking exact capture-model,
   source inventory/layers/composition, source-bindings and optional archive
   receipts. Use the existing outputs' namespaces/Run/process refs and checks;
   introduce no normative graph entities or new permission/evidence authority.
   Root existence means only stage outputs are addressable. Every model
   relation continues to come from an existing normative product.

The first implementation must not additionally invoke native V2, external
source expansion or SourceFrontend behind a partial-success label. Their exact
API prerequisites below remain visible, with the unvisited domain denominator
unknown rather than0. Importers' counts are not complete operation semantics.

## Concrete blockers and smallest follow-ups

* `publish_partitioned_inventory` requires `MaterializedBodySource` from each
  actual lowerer return, including metadata/graph object identity and actual
  operations_emitted. `inventory_program`/`expand_inventory` expose no public
  return-checkpoint handoff. Driver-side reconstructed CP1 objects, graphlen
  costs, or monkeypatching lower are unacceptable. A later approved change must
  expose a bounded producer-owned checkpoint handoff from the actual return
  through the public inventory route; the existing partition writer stays
  strict. This likely touches program_expansion + call_demand/program_inventory;
  it is excluded from the two-file P0 patch.
* Fresh monolithic binding emits source-invocations1. `plan_source_frontend`
  requires partitioned CompositionIndex plus report2/3 and exact matching
  inventory/composition. It cannot consume P0's schema1. The observed-witness
  acquisition wrapper likewise requires a partitioned composition. Preserve
  those guards. After proper handoff, automatically generate qualified keys,
  use explicit capability set/current producer, ordinary worker then batch ADD
  and composer, and finally bind the resulting snapshot once per batch.
* Dependency discovery already has `admit_dependency_sources` and continuation:
  roots are matching interpreter sysconfig namespaces and METADATA/RECORD
  ownership, with no package import. Making external definitions eligible for
  the normal entry catalog/archives remains an interface step, not proof that
  their internals/effects are modeled. Captured and analyzer interpreter/root
  mismatch must be OPEN; no unconditional host-environment substitution.
* `bind_native_capture_batches` needs fresh coordinates, an imported partitioned
  native manifest and exact capture-model roots; it is a later independently
  budgeted stage over actual dispatch inventory. `InputCatalog` currently
  explicitly rejects native_capture_batch, so a unified scope-ledger adapter is
  not already available. Do not silently pass it as native_bundle. P0 links the
  existing capture-model obligations and source report; global ledger remains
  a named unconnected stage rather than a second writable model.

## Recovery, gates and OPEN

Workflow journal/checkpoints contain stage code version, exact input/output
receipts, native schema versions, declared/read budgets, timing and exceptions.
They are navigation records. Reuse only an immutable successful stage after
its original input/output receipts and existing reader invariants still match.
Never trust a caller-edited success boolean or serialized ownership token.
Failed partial directories remain; retry uses a fresh attempt directory. Code
changes invalidate the affected consumer stage and descendants, without
re-running capture or rewriting prior canonical artifacts. Original URI identity
is preserved when paths resolve via an archive; no implicit relocation.

The minimal P0 implementation uses fresh-attempt replay for resume, preserving
all prior outputs and failures; it does not yet reuse completed stages. A small
RUNNING navigation record precedes consumption, and each stage publishes its
own started/terminal receipt. SIGTERM is converted into a saved failure when
Python can handle it. An uncatchable kill leaves RUNNING/started records rather
than a fabricated terminal. Root still imposes the external180s timeout.

Proposed approval sequence (none run here):

* G0: parser/layout/metadata-only planning, no raw/target/source compilation.
  One bounded stored metadata input; classify argv/cwd/project root/archive
  provenance and ambiguous/missing fields. Exact stage plan + OPEN list.
* G1: one root-approved already-saved small compatible CPU capture, no new
  target, no workload imports: metadata2MB, raw64MB,256 calls/128 codes,
 4 source files/256KB,4 bodies/4000total operations,64MB records,
 128MB output,180s wall; CodeWitness at most4 compile keys/16MB archive.
  These are proposed independent ceilings, not payload-derived permission.
  Root subsequently approved record64MB and output128MB as post-stage measured
  checks: preserve an over-budget partial stage as FAILED and do not publish
  COMPONENTS_LINKED. They are not continuous hard limits. The raw64MB ceiling
  is passed independently to each public reader, not a cumulative I/O cap.
  Stored plus decoded input I/O remains OPEN; repeated membership/source reads
  must be declared. Wall180s is the root's external timeout. Inventory's
  max_operations is a total remaining allowance, not a per-body4000 allowance;
  CodeWitness's four compile keys apply to its workload archive, not all source
  matching compilation done by the existing seed/inventory producers.
  Publish the two existing normative roots plus fresh source bindings and
  workflow root; compare declared/enumerated source/call counts mechanically.
* G2: resume only after an actual failure/interruption, preserving it and using
  a fresh attempt; do not manufacture an interruption for testing. No second
  capture or large LeWM/native/100k gate in P0.

`COMPONENTS_LINKED_WITH_OPEN` reports stage completion separately from target
exit, model completeness, missing capture and budget stop. Root does not close
source syntax/entry gaps, direct-call/data/state/alias/ready/resource relations,
historical collector provenance or whole first-stage obligations. Current
source858/runtime843 is unchanged by this design and is not a result for another
CAP. Root approved only scar/cli.py and scar/analysis/model_run.py. The source
pins in API_RECEIPTS.json remain design-source evidence, not a claim that all
current producer bytes are frozen by that historical receipt. Runtime budgets
are checked against the actual APIs before any G1 stage is allowed to run.

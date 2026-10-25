# Source-only dependency admission after the G1 bootstrap

2026-10-25; design only. No production edits, raw reads, source preparation,
compilation, target execution or gate run. Inputs are the saved G1 small reports;
the already-written RETENTION.json contains all9 complete descriptors/anchors.
Main source858/runtime843 and the original271-call denominator stay unchanged.

## First patch: two files, one source-only command

Proposed files: **scar/cli.py and scar/analysis/model_run.py only**. Reuse the
existing dependency producer unchanged. Do not run the eight-stage G1 route.

```text
scar model-run --from-model-run G1_MODEL/model-run.json \
  --out FRESH_SOURCE_RUN --stage dependency-sources
```

Make --from-capture/--from-model-run mutually exclusive. The latter requires
this explicit source-only stage. Add public analysis orchestration helper
`run_dependency_admission(model_run_path, out, *, plan_only=False, resume=False,
budget=...)`; its budget is ordinary work configuration, not an IR/evidence
type. Existing --from-capture behavior and all strict source guards remain.

Resolve the mutable input navigation to its exact immutable terminal receipt;
check stored SHA/bytes, schema, capture URI, original source-seed and binding
roots. Read the small existing source-seed report, not the original trace, for
the planned catalog. Keep every (process, complete CapturedCode key) and count,
first/last event anchor and descriptor anchor. Include source namespaces and
classification provenance in a navigation/catalog record, not new graph facts.
Fresh output/attempts keep the current stage journal policy. Failure or timeout
retains planned9/271 plus partial files and actual progress; it does not convert
uncompleted entries into successful admissions. Resume retries only this stage
in a fresh attempt, never native/OS, inventory/layers/composition or target.

## Mechanical namespace policy and actual starting denominator

| Candidate namespace | Groups / calls | Derivation and admission boundary |
| --- | ---: | --- |
| Original project | 1 / 1 | Captured filename is within the exact recorded project_root. It is VERIFIED `<module>`, without DefinitionID; leave to the original project pipeline. |
| Installed dependency | 2 / 261 | Absolute captured filenames under the most-specific matching interpreter purelib/platlib root; generic METADATA/RECORD ownership lookup. The observed pair happens to be Torch files; no package/function name drives selection. |
| Runtime file source | 4 / 4 | Absolute filenames under stdlib, with site-packages taking the more-specific dependency root. Current interpreter provider candidate, not proof of capture-time executable bytes. |
| Tooling candidate | 1 / 4 | The saved descriptor names the other worktree's SCAR importing callback. This is a candidate classification, not established observer origin. See the exact root mismatch below. |
| Frozen/nonfile | 1 / 1 | `<frozen os>` is not an absolute source URI. Retain NONFILE_CODE_FILENAME; do not invent os.py or an ordinary function/module body. |
| Total | **9 / 271** | No filtering of tooling, frozen or project rows. |

Use longest canonical-root containment, original logical paths and qualified
source locators. Never enlarge project_root to `/`, a common worktree ancestor,
or the analyzer cwd. Never import a candidate business package, execute setup,
evaluate .pth files or infer actual target sys.path. Current sysconfig roots are
explicit current-environment candidates; exact recorded Python-string equality
is required by the existing producer, while captured executable/provider binary
identity remains OPEN. Distribution metadata is ownership evidence, not purity,
source integrity, capture-time version or a function environment.

**Tooling mismatch:** dependency_sources._source_roots (L281) adds the current
SCAR module root, now structured-program-model. The captured callback filename
is under native-scalar-model. Therefore the unchanged public producer will leave
those4calls at NO_ENVIRONMENT_SOURCE_ROOT, rather than assigning main's tool
namespace by matching a suffix, function name, Git label or same version.
The initial command must display this separately and retain all4calls. Closing
it requires an independently admitted original tool-root/source anchor (for
example a bounded, SHA-pinned collector registration/source receipt matched to
the complete descriptor). Such an anchor is not proved by these G1 reports.
Do not add an unchecked extra-root/trust flag in this patch. Thus265calls are
mechanically candidates for current environment lookup; SOURCE_VERIFIED totals
are **unknown until the source-only gate**, not predicted265 or269.

## Exact existing calls and their prerequisites

1. `admit_dependency_sources(trace_directory, project_root, out_directory, *,
   call_budget=CallEdgeBudget(), budget=DependencySourceBudget(),
   context_budget=ContextStoreBudget(), progress=None)`
   (dependency_sources.py:L379). Fresh output; original recorded root; one
   strict call reader scan; exact recorded Python string; canonical existing
   .py sources within independently established namespaces. It preserves all
   entered code groups, prepares only demanded files, reserves compile variants
   globally, stores exact source snapshots and the first source/semantics/control
   graphs, and returns original CodeSourceLinks. All authority flags stay false.
   Check returned raw manifest, metadata, complete descriptors, group counts and
   first/last anchors against the G1 seeds; scope mismatch is FAILED, not a new
   admission. The new report is `scar.dependency-source-admissions/1`.
2. For each actual SOURCE_VERIFIED link with exact snapshot/optimize levels,
   use existing `CodeWitnessStore(directory, *, budget, create=True,
   compile_missing=True, producer=...)`, then
   `.resolve(captured, snapshot, optimize_levels, allow_compile=True)`.
   It requires captured.filename==snapshot.path, recorded flags, exact text
   fingerprint and full nested descriptor equality. Reopen read-only and resolve
   the same pairs with allow_compile=False. Missing/budget witness remains a
   separate frontier; contradictions fail. Do not fill old G1's archive, relabel
   collector archives or claim that every descriptor was source-compiled merely
   because raw descriptor replay matched9.
3. Existing `CompilerWitnessArchives(((directory, manifest_sha), ...), *,
   store_budget, budget)` admits immutable archives by complete receipts. It
   can reference old G1's1key and a new dependency archive separately. Its
   higher `plan_observed_witness_acquisition`/`acquire_observed_witnesses` require
   a partitioned CompositionIndex and exact original qualified definitions;
   they cannot be called on G1's monolith. Their _requests also derives only
   VERIFIED links in the original inventory call_sources, not external
   attachment witnesses; partitioning alone would not close that selection
   gap. Use the low-level store legally here, with the dependency link's own
   artifact/root/compiler origin rather than claiming an inventory origin.
4. Only when an actual finalized admission report exists and recovery is
   needed, `continue_dependency_sources(trace_directory, project_root,
   parent_directory, fresh_out, *, expected_parent_report_sha256,
   call_budget, budget=DependencyContinuationBudget(), context_budget,
   progress=None)` (dependency_continuation.py:L532). It rechecks raw scope and
   parent artifacts, inherits historical links explicitly and constructs only
   missing snapshots/graphs. It cannot resume an interrupted admission with no
   final admissions.json. Do not invoke it automatically merely to manufacture
   another success/root; a later recovery run has its own bounded parent/decode
   budget and does not rerun native/OS.

No new source/call/state authority is created by the orchestration catalog.
Original namespaces, SourceSnapshot, SourceContextDigest and CodeSourceLink
remain owned by these producers; logical URI, stored gzip hash and decoded
canonical hash stay distinct.

## Real connection gaps after admission

| Layer | Already implemented | Still missing; first patch does not claim it |
| --- | --- | --- |
| Source evidence | Exact recorded-flags compiler matching; snapshots; source/semantics/control graphs; installed ownership metadata. | Candidate tool root above; frozen provider; capture-time package/binary provenance; budget or syntax frontiers. Source match alone is not a dynamic call/body binding. |
| Formal source references | `SourceAttachments(report_path, *, expected_report_sha256, project_root, budget)` consumes a **final continuation**, validates its parent/snapshots/provider records, lazily checks original definition membership and returns qualified `SourceDefinitionReference`. `verify_capture(scanned, groups)` requires a genuine strict scan, not a deserialized G1 JSON token. | It does not directly consume admissions.json. CompositionIndex explicitly requires **partitioned** composition for attachments (program_composition.py:L708). G1 is monolithic source-invocations1; no attachment/schema3 promotion by caller flags. |
| Automatic entry catalog | Saved external source graphs may contain real Function/Class DefinitionIDs; ordinary qualified references already exist. | SourceFrontend planner currently enumerates inventory files/bodies and original call_source links (source_frontend_worklist.py:L195-241); external attachment definitions are not automatically added as work items. It additionally requires partitioned composition plus binding report2/3. No fake project file, DefinitionInventory, PENDING body or module Function is allowed to bypass this. |
| Canonical bodies/publication | Normal strict frontend, CodeWitness and publisher paths exist. | Fresh partition producer still needs genuine original lower-return checkpoint handoff; external entry/publication context must remain qualified to its producer. Admission does not supply canonical bodies, ordered Uses or body activation records. This is a separate next patch, not a two-file CLI switch. |
| Ordered data/state | Existing source graphs retain syntactic order/control facts; canonical/Execution IR already has the relevant typed identities. | Actual/formal and return routing, callable environment, ordered runtime Uses, DataIdentity/content versions, state effects, object identity, readiness and Python↔native occurrence are unconnected. Ownership metadata or a matching CodeType cannot close them. No new IR or metadata trust flag is proposed. |

The module's1call still needs a real module-entry protocol; the frozen1call
needs a versioned provider/source mapping. Neither is repaired by external
source admission. Old G1 body-linked0/source-only0/UNRESOLVED271 remain the
published binding facts until a separate ordinary public binding is performed.

## One proposed source-only gate, for root approval and execution

Input pins: G1 immutable terminal SHA
`a61b3d1ba30e9411aed726a882253aa92b5682a5872fdcf889326e55983433e0`,
G1 navigation SHA
`1cfaab57341b132b715e5aaab3bfac4d5c0a72efc892cdaefccf122b838340b6`,
original seed manifest/descriptors and exact CAP/trace URI. Read only small G1
roots to plan. Run **one** dependency admission, then its bounded new workload
archive and read-only checks. No native/OS import, G1 full replay, source inventory
or composition replay, body lowering, full binder, target or package import.

Suggested independent ceilings, explicitly new approval rather than inherited
G1 limits: original271calls within512/16codes;6 source files/1MB total source
(five absolute external filenames are observed; only four currently match
environment roots);64MB raw per strict source reader;8 roots;4096 metadata
directory entries/512 metadata files/16MB total metadata/4MB metadata record;
21 compile-variant reservations (3 times seven external absolute code groups,
an upper bound, not measured work);64MB archive record/256MB total canonical
source+graph archives;8MB report; ContextStore128MB compressed/64MB record;
new CodeWitness21keys/6sources/1MB source/32MB archive; external180s;
post-stage stored output128MB, with all total stored+decoded input I/O OPEN.
No source sizes or large context sizes were read to turn these into predictions.
The existing METADATA/RECORD scan may stop at its own cap and retain ownership
frontiers. Graph/archive limits may retain snapshots without graphs. Do not
raise ceilings silently or count a missing graph as a supported body.

Gate criteria: exact9-group/271-call conservation; all original keys/descriptors
and anchors preserved; every row has an actual source-status/frontier; source
namespace and provider receipts are qualified and unambiguous where claimed;
every claimed compiler witness survives read-only full-descriptor consumption;
time/budget failures and partial artifacts retained. Report actual per-category
SOURCE_VERIFIED/INCOMPLETE/MISMATCH/program/nonfile/root-unresolved counts and
call weights, snapshot/graph/witness availability separately. A gate may finish
with source-admission frontiers; its completion is not all-supported, a body
PASS, source-invocations upgrade or whole-model qualification. Actual native,
OS and body-linked counts do not change merely because a new sidecar exists.

## Design-source pins

Read-only API source SHA256 values below identify this design's inspected bytes;
they do not prove which collector source ran in the original capture.

```text
dependency_sources.py          249aaacbfdaf71ad9ecbef886438dcbbd886b387104d301f11b6bce75631e283
dependency_continuation.py     e87ddba3cca2d350890947ae80c92a43a043ca534c4a829824fdb4c5f1a2123a
source_attachments.py          2720936fbfb6734085862e9118e1b613f2df79b04421443e3d594cd0ed91aa66
compiler_witness_archives.py   8b7f9b3875098bd545775f9937d9a89c07ff4136fcdcbf6869fc228583f2c0a0
code_witness.py                fb4b2be1274750ebbc0a3971d8c43bca261e5769d088765ee42f6f05d3c26a52
program_composition.py         f64d10aa2d3a397519670c65514948405ff384b093995017b543730a08fdeb31
source_frontend_worklist.py    00581a66490ba62730022aab2772a4b0e6e47bcc2c5bd5a0d4e23423592424d2
model_run.py                  35ea0ba4434797d76dedcba53193adc7f852c8f43fcee93388e64b39ca0904b1
```

# Connect current captures to retained static source evidence

## Status and non-interchangeable scopes

**Verified for one retained current-Run gate, 2026-10-23; whole model remains OPEN.**
The initial small-input audit/design below preceded implementation. Its evidence
and proposed acceptance boundaries are preserved; the actual result is at the
end of this document.
The completed source attachment gate uses target PID272038 / Run
`capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66`.
Tensor physical and current OS evidence use PID369749 / Run
`capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0`.
The former's dynamic facts cannot fill the latter's missing source connection.

The required connection is:

```
current raw code + current frame scan + current coordinates
            |
            +-- exact complete CapturedCode match --> historical compiler/source witness
            |                                             |
            +-- current source/build/profile guard --------+
                                                          |
                                original qualified definition / optional project body
```

Only the static correspondence is reused. Old InvocationKey, process/thread,
CodeCapture.anchor, entry/exit, counts, parents, activation, effect, tensor,
resource or timing facts are not transferred. Even equal code-file bytes do not
make the two Runs interchangeable.

## Located inputs and measured descriptor demand

The current capture actually has a lossless archive:
`artifacts/experiments/first_stage_lewm_physical_20261023/archive-index.json`.
Its explicit original `logical_path` maps the codes file to
`trace/call-codes.369749.jsonl.gz`; raw and gzip SHA/bytes were checked against
that archive and the saved same-Run coordinate membership. The native manifest
is `trace/execution-evidence.369749.json`. The old272038 capture instead retains
plain raw files and has no archive-index. No filename guessing or root expansion
is needed.

The stdlib-only comparison is retained in
`artifacts/experiments/first_stage_current_source_scope_20261023/` (script,
producer/input SHA, result, stdout/stderr/time). It reads only small codes,
metadata, coordinate declarations and previously saved code/source reports;
no raw event stream, OS stream, source file, compiler or SCAR/IR module is read
or executed by the comparison.

| Descriptor fact | Observed count |
| --- | ---: |
| Historical / current captured descriptors | 855 / 855 |
| Entire CapturedCode dictionaries equal | 854 |
| Same key, conflicting remaining descriptor fields | 0 |
| New descriptor / old descriptor absent | 1 / 1 |
| Exact current descriptors with historical definition | 667 |
| Exact current descriptors historically verified without definition | 128 |
| Exact current descriptors historically unresolved | 21 |
| Exact current descriptors captured but not entered in old binding | 38 |
| Current descriptors without a complete historical match | 1 |
| Exact current descriptors matching historical external VERIFIED evidence | 242 |
| Current non-file descriptors (including captured-only) | 26 |

The667 consists of the425 original project definition records plus242 external
records. The sum over descriptor categories is855. These are **code demand
counts**, not current entered groups or per-code invocation weights.

Current collector metadata independently declares100,438 invocations,
200,876 events,855 codes, zero dropped events/codes and empty errors. The old
metadata happens to declare the same totals; only PID and wall_ns differ. This
coincidence does not prove current per-code weights, parent paths or raw event
identity. No existing small current entered-group table was located. Therefore
current entered groups/per-code counts remain null in this design evidence;
a future complete strict current raw scan must establish them.

### The old14-call drift is not a current14-call group

Historical importing code
`pycode-v2:31492bd4ea3bf79ce4185ccbe0c42e17a36c3ba63489b93077e2d053b5a4fdff`
has14 old invocations and a recorded false guard for the old
`execution_evidence.py` snapshot. That entire code descriptor is absent from
current codes. A new descriptor is present instead:
`pycode-v2:7fe9ecd39981a7fe58981e81760f3b26c4b49aa56fb29f8ea61480d0564772ef`.
Its diagnostic filename/qualname resemble the old code and its first_line is122
rather than113. Those names/positions are not a matching rule.

The new code must receive `NO_MATCHING_STATIC_CODE_SOURCE_WITNESS` until exact
new source/compiler evidence exists. Do not bind it to the old definition, count
it as the old14 calls or invent a new definition from a nearby source span. Keep
the old record and false guard as historical evidence. Current per-code weight
and a refreshed current guard are not known in this small-input audit.

## Existing interfaces and their actual limits

- `source_invocations.bind_source_invocations(..., witness_mode="reused_code")`
  already scans current raw frames independently. For project evidence it
  compares entire CapturedCode, selects original static admissions, and invokes
  `_SourceGuard.check` before publishing a current body/definition. It does not
  rerun a whole source inventory.
- `SourceAttachments.verify_capture(scan, groups)` intentionally requires exact
  historical raw files, descriptors, groups and anchors. The current schema3
  binder allows only `same_capture`; that API must retain its strict meaning.
- `SourceAttachments.code_witness(pid, code)` and
  `definition_reference(pid, code)` currently select original historical groups.
  Passing a new PID to them, or replacing the catalog PID, is invalid.
- `CompositionIndex.document`, schema2 inventory and original source artifacts
  are immutable input identities. Explicit attachments are separate receipts;
  external definitions have source graphs but no invented typed body.
- `dispatch_sources._FormalSourceScope` currently enforces schema3 same_capture
  attachment receipts. It must understand an explicitly declared reused_code
  rule before a current v3 report is accepted.
- `SourceBodyAccess` accepts only source schema2. It independently checks a raw
  operand/frame scan against that report, but assumes definition is an
  ElementReference and external locators belong to project `call_sources`.
- `CodeWitnessStore(create=False, compile_missing=False)` already supports
  read-only stored CodeType access with complete descriptor matching and exact
  local runtime/magic/marshal checks. Source association is distinct from
  availability of such a bytecode witness. No new compilation fallback is
  required for this source connection.

## Minimal proposed API connection

### 1. Add a static selector; preserve strict same_capture

Add a read-only static-code lookup to `SourceAttachments` and forward it from
`CompositionIndex`, for example:

```python
static_code_witness(captured_code, *, compilation_profile, captured_python_build)
```

It indexes complete historical CapturedCode records by structural key, then
compares **every descriptor field**. Ambiguous historical source/snapshot or
compiler witnesses are rejected. The result carries only the original complete
descriptor, CodeSourceLink, qualified SourceDefinitionReference and original
provenance locators/profile/build. A historical admission locator may identify
its origin, but its PID/count/entry/descriptor anchor is not a current fact.
The returned normalized static view must not contain a transplanted
CodeCapture or current group count.

Keep existing `verify_capture` and same_capture behavior unchanged. Never
relax equality of current and old manifests to force this new case through it.
Original graph/snapshot/provider loaders and compact exact-reference definition
caches are reused; no106-file prepare or widened program root is needed.

### 2. Current binder supplies the dynamic scope and guards

In reused_code mode, the current strict `scan_call_trace` and sink establish
all current files, captures, entries/exits and group weights. Bind them to the
**369749** coordinates. Use each current capture's original anchor; emit current
parent/completion/RegionActivation rows from current frames only.

For each current code:

1. Match the complete static descriptor using the selector above or the existing
   project reused_code path.
2. Require recorded compiler profile `RECORDED_FUTURE_FLAGS_V1`, supported
   captured future flags and original matching optimize levels. Reuse the
   existing policy helper; do not rerun the compiler matcher.
3. Compare captured Python build strings across the source-witness capture and
   current capture, and the reader/witness runtime when materialized bytecode is
   requested. `SourceSnapshot.python_version` may be only `3.14`; it is not a
   replacement for the full recorded build guard. Missing context is a frontier.
4. Apply one bounded current source-fingerprint guard per demanded original
   snapshot, using the existing `_SourceGuard` method and budgets. A mismatch,
   missing file or budget exhaustion is an explicit frontier, not unsupported.
5. Publish a current usable definition/body only when these conditions hold.
   Retain historical proof and the current guard result separately when a guard
   fails; do not erase historical evidence or promote it into a current proof.
6. Keep unentered captured descriptors distinct from current entered groups.
   The38 captured-only historical descriptors have no old binding row; valid
   original compiler links may still be consulted, without manufacturing an old
   dynamic admission. No assumed855-to817 mapping is permitted.

Current frame scanning and current guards are new evidence; source/compiler
matching is explicitly reused historical evidence. No new source producer,
DefinitionID, RegionID or root activation is created by the selector.

### 3. Preserve identity schema; declare the new reuse rule explicitly

Keep source definition format `scar.source-definition-reference.v1` and schema3
meaning. `witness_mode="reused_code"` is already an explicit selector, but require
an additional machine-readable rule marker for the newly supported attachment
case, for example `attachment_source_match_rule="EXACT_CAPTURED_CODE_STATIC_REUSE_V1"`.

The source report/bindings must carry explicit current raw-scan receipts and
original static witness locators. Current attachment capture-check scope must
say it verified the **current independent scan with per-code historical static
matches**, not whole historical same-capture equality. Old v3 same_capture
reports lacking the new marker remain valid under their old checks. No silent
reinterpretation or automatic v4 is necessary because identity representation
and existing selectors do not change.

Dispatch consumes the same current report/coordinates/bridge and verifies the
new explicit scope, original static witnesses and current guards through the
same CompositionIndex resolver. Old current/historical manifests are allowed to
have different SHA/paths/PIDs; they cannot be asserted equal. The association
remains retained ancestry, never a direct Python/ATen callsite.

### 4. Let SourceBodyAccess consume v3 without inventing external bodies

Allow versions2/3 explicitly. For v3 verify the formal reference format,
`source_inputs`, original composition SHA and static witness using the public
CompositionIndex selector/resolver. Select project bodies using the retained
`composition_element` and verify its qualified formal definition; do not read
`definition.identity` as though v3 were v2.

`bind_scan` continues to compare current raw code captures/anchors,
files/groups/counts/metadata against the **new369749 source report**. It never
consumes old272038 invocation rows. External definitions remain source-only:
keep their CodeSourceLink/reference and model frontier, with no signature,
canonical body or artificial project file index.

Bytecode-dependent operand/environment rules can use the existing read-only
CodeWitnessStore for already archived matching project code. If a bytecode
witness is unavailable, report that local frontier while preserving source
association. Do not synthesize an external project `_SourceProjection` or
silently compile106 dependencies. The four call consumers already use
SourceBodyAccess; avoid adding package checks or another graph/report model.

## Minimal implementation changes, awaiting review

| File | Required change |
| --- | --- |
| `source_attachments.py` | Static full-descriptor lookup with historical provenance; keep same-capture verifier unchanged. |
| `program_composition.py` | Forward the static selector and existing qualified resolver; keep document/SHA/root/schema unchanged. |
| `source_invocations.py` | Permit explicit attachment reused_code after current independent raw scan; current build/profile/source guards and current anchors/counts; report reuse-rule/scope. |
| `dispatch_sources.py` | Recognize that explicit rule, verify current scope and retained static witness independently; no old marker/capture import. |
| `source_body_access.py` | Explicit v3 reader, formal-definition/project-view separation and generic attached witness lookup; retain strict current bind_scan. |

`code_witness.py`, source_layers, inventory partitions, IR types and four call
consumers need no new representation for this bridge. Confirm their existing
frontier handling during implementation review; change only a demonstrated
interface assumption. Existing CLI witness-mode selector can drive the same
public API; no workload-specific flag is required. No producer archive,106
source graphs or old report is rewritten.

## Future one-Run acceptance gate (not executed)

1. Fix module/input SHA and use only369749 raw capture, coordinates, dispatch,
   tensor and OS input receipts. Retain272038 only as static witness provenance.
2. One complete strict current frame scan determines current855 descriptors,
   entered groups,100,438 entries/exits and per-code weights. These are targets
   from collector metadata, not already verified per-group facts.
3. Reconcile all854 exact descriptors, the one new descriptor, captured-only
   demand and current guards. Report per-code outcomes with current weights;
   leave the unmatched importing code frontier until a separate exact new witness
   exists. Do not assign its historical14 calls.
4. Verify current qualified definitions and unchanged original composition SHA;
   no fake external body/activation. Materialize only demanded original graph
   queries/compact definition records; do not reprepare106 files or scan roots.
5. Bind the current production bridge, preserving its actual79,592 markers and
   109,288 slots plus existing physical eligibility frontiers from this Run.
6. SourceBodyAccess independently binds its current operand/environment raw
   scan to the new report, uses read-only existing CodeWitness evidence, and
   preserves bytecode/source-only frontiers. No old Invocation/activation enters
   new current models.
7. Save output SHA/counts, current guard and profile outcomes, historical
   provenance, stage cost/RSS and a gate report. Whole program/effect/version/
   readiness completeness and transformations remain separate obligations.

The observed descriptor difference strongly limits required new compiler/source
work: at least one new code lacks a historical match, while854 can be considered
for guarded static reuse. It does not prove all current guards or exact coverage,
and does not authorize source recompilation in this design task.

## Historical pre-gate implementation freeze

The five-file implementation is now present for root review; no369749 raw scan,
source loader, compiler, target or GPU gate has been run for this change.
AST parsing and diff whitespace checks are the only executed implementation
checks. `first_stage_current_source_implementation_20261023/` retains the exact
five-module snapshots, patch, base revision, SHA and scope receipt.

Implemented public methods are `SourceAttachments.static_code_witness(...)`,
`CompositionIndex.static_code_witness(...)`, `static_definition_reference(...)`,
`source_attachment_reuse_checks(...)`, `current_source_guard(...)` and shared
`validate_static_source_binding(...)`. The shared validator is consumed by both
dispatch and SourceBodyAccess. The original same-capture verifier is unchanged.
The current-scan reuse receipt is tagged
`CURRENT_INDEPENDENT_SCAN_FOR_STATIC_REUSE`; the existing schema3 reused_code
selector additionally requires `EXACT_CAPTURED_CODE_STATIC_REUSE_V1` in both
bindings and report.

Normalized static lookup results retain original proof locators, complete code
and source link, compiler/build guard and original source frontier. They do not
return old PID, group weights or CodeCapture anchors as current facts. Project
proof origins are checked against the attachment's historical raw manifest,
while the current scan is deliberately independent. Current build/profile
rejection removes current usable definition/body and retains historical proof;
external source-fingerprint failures likewise retain the historical qualified
reference while publishing an explicit current guard frontier.

For schema3 reused_code, SourceBodyAccess requires an explicitly read-only
CodeWitnessStore (not writable and no compile_missing). Existing schema2 behavior
and the four consumers are unchanged. External source-only proofs go through
the shared public validator and do not join the project body table. Actual
369749 group weights, current source checks, source/runtime binding results and
performance remain unverified until the separately authorized one-Run gate.


## Verified current-Run gate

The single authorized `first_stage_current_source_gate_20261023` run exited0,
wall2071.73s / runner2068.11s / peakRSS2134064KiB. It used only retained369749
raw data, the original composition/static attachments and read-only20-key
CodeWitness. No new target/GPU/prepare/compiler matching occurred. Participating
producer SHA and original composition document/hash were checked unchanged.

Current independent source scan and independent SBA frame/operand scan agree on
all817 groups and their per-code weights,100438 entries/exits and855 descriptors.
Current definitions cover667 groups /95474 calls:74body groups /5624 calls and
593source-only groups /89850 calls. Current unresolved150groups /4964calls are
128verified-without-definition groups /4147calls,21non-file groups /803calls and
one new-code group /14calls. That last weight is from current raw frames, not a
transplanted old14-call count. All220 current source fingerprint guards match;
242external groups /86688calls are source-only with original static proof.

Current marker scope is79592markers /109288slots:10992body,68114source-only,
6invocation-only and480without context, including50658external source-only rows.
Public queries verified representative categories. All remain ancestry-only.
SBA retains312812operand /16403environment events,13872entry parameter records,
3347entries associated with10087environment ports,27argument +27completion
conditional routes and5173returns. The6694defaults gap and100523route issues
remain. Read-only CodeWitness loads20modules, matches224descriptors, compiles0.

105demanded dependency graphs were decoded once during source binding; marker
and SBA stages added no dependency graph reads. The final selected original
source-view query explicitly adds one small re-read, for106total. Unique
canonical input bytes2074933095; final physical bytes240397421; graph LRU2 and
242small original definition records. Canonical operand report99478478bytes,
SHA633266c86dbabe4a98377b809bb6cfc259b7a164d00c3b19293b4fb259f5f51e,
is retained using the existing bounded tables, not a merged ProgramGraph.

See that experiment README, frozen producer, exact input/module SHA, progress,
summary and output receipts for the full gate. This verifies the current source /
marker / conditional operand-environment connection only. It does not discharge
cross-body world/state identity, contents/effects/logical versions, resource
readiness or complete program coverage; first_stage_complete remains false.

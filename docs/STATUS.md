# Current evidence and remaining work

## C2B resumable body component (2026-10-18; full regression pending)

[Body contract](M1_RESUMPTION_BODY_COMPONENT.md) now has strict records,
Suspend-owned saved Uses, current-state ResumeInput signatures, context
Initial/Attach/Detach, separate logical and availability projections, and
binding/C0/C1 composition. Six initial valid graph probes passed; the missing
saved-value probe was rejected at its unavailable Use. These are manual IR
checks, not automatically recovered Python execution.

Independent review reproduced and fixed an overstrict frame-alias check. The
final component gate passes **499 checks / 7.077s**, all seven criteria, with
403 source hashes unchanged during the run. Frozen full regression remains
pending. Full C2.0/C2.4 driver, instance/generation/exclusivity and final
release remain open. M0–M2 and automatic LeWM modeling remain incomplete; no
transformation or speedup is claimed. Earlier design/C1 results below retain
their original source and scope.

## C2 resumption architecture review (2026-10-17)

[C2 design](M1_RESUMPTION_INTERFACES.md) chooses explicit temporal successors in
one logical body, with separate derived logical-control and cut-availability
queries. Three reviews and small stdlib witnesses expose context inheritance,
delegate-only driver paths and the old synchronous FrameExit adjacency conflict.
The first language batch contains 23 dynamic observation groups and four static
code shapes; four later delegation-context observations are separate. Five design
checks on existing valid core CFGs support the availability cut, not an implemented
Suspend validator. C2.0 exact-field freeze remains open. Product schema/source
are unchanged from the C1 implementation; no full retry, new capture, LeWM run,
transformation or speedup accompanies this specification update.

## C1 cleanup/context static component (2026-10-16; archived 2026-10-17)

[C1](M1_CLEANUP_INTERFACES.md) connects Enter/Resume/Replace and saved exception
context to canonical pending Uses, current all-domain state and lexical CFG
routes. All **243 component checks** pass. Independent review found and fixed
a valid divergent cleanup rejected by the old actual-exit requirement; a second
integration fix rejects new Route subclasses that would lose their wire tag.
Original failures and precise counterexamples remain archived.

Frozen `0ea05e6` passed **3,330 full tests / 428.510s / 1,028,484KiB**, with three
existing warnings and zero failures/errors/skips. HEAD, clean status, 391 source
hashes and 22 fixture hashes matched before/after; its exclusively owned basetemp
was removed. Schema v9 preserves original v1–v8 contracts. This verifies declared
static IR composition only: no new source recovery, runtime unwinding proof,
provider adapter, LeWM transformation or speedup. Complete M0–M2 remain unfinished;
resumption, precise state/literals, dynamic resources and occurrence/denotation
still require interfaces. See the [evidence archive](../artifacts/experiments/b1_call_operands/model_cleanup_interfaces/README.md).

## Current modeling/tool reuse review (2026-10-16)

The [status and modeling decision](MODELING_REUSE_DECISION.md) separates five core
entity types, behavior tags and dependency relations, and maps them to existing
tool providers. Read-only reviews at `78c5fda` confirm profiler/Kineto and Python
monitoring are integrated, while FX/Export/ETO remain unimplemented adapters.
TorchLens offers finer dynamic relations than a module-only graph; torchview is
useful for display but its deduplicated edges do not preserve every argument Use.
The audit also identifies name-based mutation guesses and collector failure-path
gaps in the current trace code; these records do not establish complete effects.
Reuse op schemas, native descriptors and provider artifacts before writing parallel
logic. No new product code, capture, tests or workload run accompanies this review.
At that read-only checkpoint C1 was a design and schema was v8; the separate C1
receipt above records the later implementation. M0–M2, automatic whole-program
LeWM connectivity and a credible automatic transformation/speedup remain incomplete.

## P1 thin native boundary component (2026-10-16)

[P1](M1_NATIVE_INTERFACES.md) adds ordered native slot references and an exact
native/core-only canonical port partition, all Return/Raise UseSite queries,
cross-region declared pairs with eight unproved domains, schema v8 and public CLI.
Final component: **168 PASS / 8.815s**, 376-file source fingerprint
`7a476a2e161109dc924615cd1c5aeb17fc4ca39176ffade393e15917dbb6fb17`.
Independent integration review reproduced a validator-valid legacy ID-subclass
index regression after the first 164-check pass; raw original-ID coordinates and
four new regressions fix it without weakening strict new records. The unchanged
five-case IR-only probe then passed. Initial results remain archived.
Frozen `79bf2a9` passed **3,215 full tests / 431.085s / 1,027,692KiB**, three
warnings, zero failures/errors/skips. HEAD, clean status, all 376 source hashes and
18 fixture hashes were identical before/after; the exclusively owned basetemp
was removed. The single full run needed no retry. This does not implement native artifact/tree
replay, provider adapters, current lifted-state/write-back, dynamic provenance or
equivalence. Complete T1/M1/M2 and automatic LeWM modeling remain unfinished.

## Tool reuse boundary refinement (2026-10-16)

The [survey](TOOLING_SURVEY.md) now includes an isolated PyPI torchview 0.2.7 CPU
probe: four small cases / five successful captures, with duplicate-input,
view/in-place, nested-display and capture-side-effect observations. This is not
a SCAR adapter or workload run. The [integration design §7.2](MODELING_INTEGRATION.md)
keeps native signature/TreeSpec artifacts authoritative and narrows SCAR additions
to canonical boundary references and scoped correspondences, avoiding a duplicate
pytree/signature implementation. Product/test source is unchanged from `5ccc1d2`;
the existing 3,139-test frozen result was not rerun for these research/docs changes.
FX/Export/ETO adapters, complete M1/M2 and automatic LeWM whole-program connections
remain unfinished; no transformation or speedup is claimed.

## P0 provider provenance component (2026-10-16)

[P0](M1_PROVIDER_INTERFACES.md) connects typed provider envelopes, representation
ownership/observation scope and ordered endpoints to the existing canonical core.
All 225 final component checks pass with source fingerprint
`97a2dfe24a6e5d3c72c31ee6d3cb94dc6e8bc9d8dad35e3e9bb4e21ebf3f4b0b`
(367 files). Schema v7 preserves original v1–v6 contracts. An independent review
found and reproduced four accepted INVOKE-result source mismatches; the fixed
validator now derives direct completion/pending projections from canonical CFG
edges. A further shared-landing review found and fixed order-dependent pending
projection ownership; a valid two-dispatch phi regression now checks record-order
invariance. The initial frozen full run was deliberately interrupted before any
tracked edit; its FAIL/-15 receipt is retained. Final frozen `b140708` passed
3,139 full tests in 424.444s / 1,026,828KiB, with three existing warnings and no
failures/errors/skips. HEAD, clean status, 367 source hashes and 15 fixture hashes
were identical before/after; the exclusively owned temporary directory was removed.
This is a declaration component, not
an FX/Export/ETO adapter, artifact replay, occurrence bridge or equivalence proof.
Complete T1, M1/M2 and first-stage modeling remain unfinished.

## Tool reuse reassessment (2026-10-16)

The [integration contract](MODELING_INTEGRATION.md) now specifies field ownership,
granularity and observer replacement criteria. Reuse existing Tensor subgraphs;
evaluate source CFG providers before expanding custom control lowering. M0–M2
requires composable boundary types, not an independently implemented full Python
compiler. A single metadata-only CPU profiler probe found allocation IDs and
schema-derived mutation versions (0→1→2); see [survey §3.5](TOOLING_SURVEY.md).
This private/experimental provider is not integrated. Product source and the
existing frozen 3,027-test result are unchanged; no new full regression, LeWM
run, automatic transformation or speedup is claimed. First-stage modeling
remains incomplete.

## C0 lexical control and pending protocol component (2026-10-16)

[C0](M1_CONTROL_INTERFACES.md) passed 354 component checks: typed lexical scopes
and ports, exception packet/pending SSA constructors, CFG-derived case unions,
dispatch projections, old wire and public CLI. Source fingerprint is
`06773c8c8863910cffb70d5859e5019dc040f0a5e8903799abeb837bb52d4a53`
(356 files). Frozen `54eb7ec` passed 3,027 full tests in 410.615s / 1,029,132KiB,
with three existing warnings, no failures/errors/skips, and identical HEAD,
clean status, source hashes and 11 fixture hashes before/after. Schema v6 preserves original
v1–v5 contracts; v5 wire came from an isolated original-revision archive.
This does not verify source ownership, runtime exception validity or cleanup
unwinding. C1 must preserve original token/payload and active exception context
across cleanup using current state; first-stage modeling remains incomplete.

## Function environment interface component (2026-10-16)

[Environment/entry declarations](M1_ENVIRONMENT_INTERFACES.md) now connect to
the existing canonical Uses, entry ports and state SSA. All 327 component checks
and 2,835 frozen full-repository tests passed. Implementation `e826713` retained
the same 346-file source fingerprint and eight fixture hashes across the run
(411.858s / 1,026,996KiB; three existing warnings). Wire v5 adds these interfaces
while original v1–v4 fixtures retain their exact contracts. Declarations do not
verify runtime callable identity, source signature binding or pure effects.
The [first-stage completion matrix](FIRST_STAGE_COMPLETION_MATRIX.md) records
remaining control/resumption, location/literal, resource, denotation and provider
interfaces. The complete modeling stage is unfinished.

## Tool reuse review (2026-10-16)

[Survey](TOOLING_SURVEY.md) and [integration design](MODELING_INTEGRATION.md)
separate existing capture capabilities from SCAR's cross-layer responsibilities.
Small CPU experiments verified usable FX/Export/state interfaces, an ETO↔Kineto
CPU record-ID join, and isolated LibCST 1.9.0 parsing/metadata. These are research
witnesses, not integrated adapters or whole-program coverage. Current SCAR already
uses profiler/Kineto and sys.monitoring; FX/Export/ETO integration remains pending.
Pinned TorchLens source/docs now add a fine-grained dynamic-provider candidate;
no TorchLens installation or local compatibility/capture experiment is claimed.
No new backend, workload run or speedup claim. Complete first-stage modeling is
still unfinished; its stopping boundary is unchanged.

## Current priority: complete the model before whole-program graphs (2026-10-16)

M1 now has one implemented [static resource interface component](M1_RESOURCE_INTERFACES.md):
four canonical tables, strict v4 capability and unchanged frozen v2/v3 wire,
198 component checks and 2,686 frozen full-regression checks passing.
[Field-level protocol specifications](PYTHON314_PROTOCOL_CATALOG.md)
now cover data/definitions, control/resumption and resource/library boundaries;
their independent language witnesses do not certify a SCAR implementation.
The rest of M1 and the complete first modeling stage remain unfinished.

**Whole-program abstraction is incomplete.** The revised
[model specification](WHOLE_PROGRAM_MODEL.md) defines independent Operation,
Value, StateLocation, Region and Resource, typed environment/completion/resume/
readiness interfaces, and the static ValueID→occurrence→denotation bridge.
Specification consistency does not mean those interfaces are all implemented.
The [model-first gates](WHOLE_PROGRAM_MODEL_PLAN.md) now precede further detector
or backend work; [review scope](WHOLE_PROGRAM_MODEL_REVIEW.md) separates them.

Development branch `codex/structured-program-model`, frozen implementation
`dcd4986`, passed 290 component checks and 2,657 full tests. It implements a
limited synchronous binding/loop subset. The fixed 256-body source stress has
51 graphs with gaps and 205 unsupported bodies; 77 of 1,591 source calls have
the checked ordered core endpoints. This is not a whole-project coverage ratio.
See [bounded acceptance](N2_STRUCTURED_BODY_ACCEPTANCE.md). Existing main branch
and historical results below must not be mistaken for this development state.

The LeWM load→inference→environment→video graph remains incomplete. No credible
automatic LeWM transformation or clean A/B speedup is available. More tests or
conditional reference routes do not change that conclusion.

## Latest bounded component: R1 recorded compilation context (2026-10-16)

Final **287 mapped checks / 77.390s**, **2,278 full repository tests** and
unchanged LeWM archive regeneration by the public verifier passed. Frozen source
fingerprint: `aefadf0d7b9b4bb6c2ccd0d8e5248bb6962c6cf79bbcbffb7406afa6d63f08bf`.
Full process: 290.334s / 1,028,636KiB peak RSS; three existing warnings,
no failures/errors/skips. Independent archive verification: 252.349s / 236,320KiB.

The five legacy mismatches now exactly reproduce complete code descriptors;
all other code links and model fields remain unchanged. Counts are 553 VERIFIED,
259 INCOMPLETE, zero MISMATCH, and 425 eligible definition seeds. New seed v2
records its matching profile; historical seed v1/nested inventory v6 retain their
legacy behavior. A second cache spelling regression was reproduced and fixed;
initial results and intentionally stopped replay remain archived separately.

This verifies source correspondence only. It does not bind actuals, environments
or state, complete the LeWM graph, authorize a transformation, or give a speedup.
The 150-file/50-body figures below remain the frozen D1 expansion results; R1 did
not rerun the entire v6 expansion. See [R1 acceptance](N2_COMPILATION_CONTEXT_ACCEPTANCE.md)
and the [current automation scope and next end-to-end gates](AUTOMATION_STATUS_20261016.md).

## Latest bounded component: D1 source-to-demand bridge (2026-10-15)

Implementation `2cf4e40` passed **303 mapped checks / 57.703s**, **2,193 full
repository tests**, and unchanged LeWM archive generation/public replay. Source
fingerprint: `a64ba352478c1808f6a1a3ed855c37e561898297e2cc3e630f9940505b540747`.
v6 automatically indexes 150 files/2,211 definitions and emits 50 local body graphs.
All 421 definition seeds join source inventory; 32 link final core regions, while
260 class scopes, 28 closure/cell functions, 2 generators and 99 other function
lowering boundaries remain explicit. These are not optimization candidates.
Generation took 602.086s/355,692KiB; replay 607.542s/881,800KiB. These are offline
analysis costs; generation overlapped regression. Raw/source/Git remained unchanged.
No actual/formal proof, whole-program graph, transformation or LeWM speedup.
See [D1 acceptance](N2_CALL_DEMAND_ACCEPTANCE.md).

Historical next step at that checkpoint: resolve the observed inherited-future compilation mismatch with explicit
matching profiles and historical replay, then deliver actual→formal→return queries,
environment/world mapping, loops and state provenance under
[the concrete cross-call plan](N2_CROSS_CALL_IMPLEMENTATION.md).

## Historical bounded component: D0 compact source seeds (2026-10-15)

Implementation `39e8f22` passed **196 gate checks / 83.324s** and **2,033 full
repository tests / 242.28s**, with no failures/errors/skips. Its frozen source
fingerprint is `81d6a6b675055eaa70a8e4dff566107dc3329859e999e7f918050bd983c26909`.
The unchanged real LeWM archive yielded 812 entered-code groups, 548 verified
code/source links and 421 complete unique definition seeds. Public independent
replay passed; target source/Git and raw trace remained unchanged. The report
is 266,292 gzip bytes. Generation took 349.361s / 230,564KiB peak RSS; replay
352.998s / 237,716KiB. Replay overlapped a separate source diagnostic; these are
analysis costs, not workload benchmarks or LeWM speedup.

At that milestone source seeds did not enter inventory scheduling, bind actual
arguments, establish environments/effects, or authorize a transformation. One source profile
identified unused full-graph digest work in `index→snapshot`. Next: preserve the
same identity/boundary rules while publishing a thin source index, then typed
v6 entry-first demand. See [D0 evidence](N2_CALL_SEEDS.md),
[D1 plan](N2_CALL_DEMAND_PLAN.md) and [current automation](AUTOMATION_STATUS_20261015.md).

## Current bounded component: C0 frame lifecycle (2026-10-15)

Frozen `72aaf54` passed **863 mapped tests / 143.949s** and **1,898 repository
tests / 209.470s** (three documented warnings, no failures/skips). Automatic
raw-source frame bodies preserve returned references with separate lifecycle
world state. SourceProgram v2, default inventory v5 and conditional path queries
retain strict replay; real historical v1–v4 inventory and v4 call reports replay.
The source fingerprint is `c8de5831ed8afb1378ba41fd7b2373de599fd818520d03970b1ec04665666d7c`.
F4 also replayed the unchanged LeWM entry/trace under equal budgets: 151 files,
2,217 definitions and all 44 bodies retained; 443.066s generation / 451.106s replay,
peak RSS 1,100,892KiB. Target Git, source snapshots, raw trace and frozen SCAR hashes
remained unchanged. These are analysis costs, not workload acceleration.
No cross-call actual/formal proof, whole-program graph, transform or speedup.
See [C0 acceptance](N2_FRAME_ACCEPTANCE.md).

## Current bounded component: N2.call-evidence (2026-10-15)

Follow-up frozen `677e10f` passed **703 mapped tests** and **1,738 repository
tests** (three documented warnings). Independent raw report/record ceilings are
public CLI options; streamed bounded output preserves existing reports on
failure. Return-position indexing keeps the previous source matching semantics.
Real API replay passed, with **9 distinct observed core calls out of 110**;
direct target-body joins remain zero, and one core call reaches existing bodies
through verified runtime parent chains with intermediary effects unproved.
The public CLI replay also passed (exit 0, 773.944s, peak RSS 5,348,072KiB),
with the frozen source hashes unchanged. These are offline analysis costs. See
[call connection audit](N2_CALL_CONNECTION_AUDIT.md) and
[the next frame lifetime gate](N2_FRAME_LIFETIME_PLAN.md).

Frozen `bedcd2d` passed **659 mapped tests** and **1,694 repository tests**
(three documented warnings, no failures or skips).
New `trace --calls-only` automatically records immediate caller positions,
bounded frame paths, invocation entries/exits and lifetime-scoped reference
identities. Offline source/core/call linking and strict replay retain concrete
boundaries. No workload graph or business-name rule is supplied.

Independent audit found and fixed closed-parent/recursive-parent misjoins,
unverified collector metadata and false source-argument provenance for bound
methods/partials/defaults. Queries now stop with `ARGUMENT_ROUTING_UNVERIFIED`;
the full N2.call-edges E4 dependency route is **still unmet**.

The original LeWM command was run twice without target edits. The first hit
the default 64MB budget. The retry succeeded and recorded 168,638 events,
84,319 Python entries (including suspended-code segments), 850 code descriptors,
and zero dropped events/codes, unmatched entries or path gaps. Its API offline
source/core linking and replay passed within the stated scope; no complete dependency graph,
transformation or clean A/B speedup is claimed. See
[component evidence and remaining obligations](N2_CALL_EVIDENCE_ACCEPTANCE.md).

## Latest autonomous acceptance: N2.function-interfaces (2026-10-15)

Frozen implementation `cfad419` passed **504 mapped cases** and **1,552 repository
tests** (two existing warnings). Default v4 inventory separates definition-time
work, conditional argument binding and bound-formal body ports. Actual historical
v1/v2/v3 packages generated reports that the current public CLI replayed;
legacy lowering behavior is preserved. No manual workload graph is supplied.

The same raw LeWM entry, archived real trace and budgets produced 151 files,
2,217 definitions and 10,235 calls. Core bodies increased **26 to 44**, runtime
source/core links **4 to 6**; only **one** has an exact code witness. Of the 17
previous signature blockers, two now have bodies; the other 15 expose seven
closure/cell and eight syntax blockers. Generation/replay took **432.895 /
458.886 s**, peak RSS **347,120 / 812,896 KiB**. Source, trace and clean target
Git state remained unchanged. These are analysis costs, not LeWM acceleration.

Automatic connectivity audit exposes the next gap: all 197 candidate binding
plans belong to unsupported or budget-deferred callers. All 110 calls inside
the 44 existing core bodies lack source target candidates. Their intersection
is zero; 478 planned actuals have no core UseID. No missing eligible use was
found, but neither group forms a connected call/body/return/effect graph.

See [N2_FUNCTION_INTERFACES_ACCEPTANCE.md](N2_FUNCTION_INTERFACES_ACCEPTANCE.md),
[the current automation scope](AUTOMATION_STATUS_20261015.md) and
[the next connection gates](N2_CALL_COMPOSITION_PLAN.md). Next: captured
environment and callable evidence, per-call exits/state mapping, then loops and
fine operation effects/provenance. No new backend, LeWM transform or verified
speedup. Project cache cleanup reclaimed another 8,290,304 allocated bytes;
compressed evidence and target/shared environments were preserved.

## Latest autonomous acceptance: N2.schedule (2026-10-15)

Implementation `994f944` passed **457 mapped cases** and **1,505 repository
tests** (two existing warnings). Source indexing now precedes a global body
demand queue. Witness admission is demand-driven too; each lowering task builds
only its root. Private bounded contexts avoid repeating full preparation.
Historical package `b886e40` independently generated a v2 fixture that the
current public CLI replayed unchanged. New runtime reports use v3; v1/v2 retain
their original replay algorithms.

The same LeWM entry, trace and budgets generated 151 files and 2,217 definitions
in **425.783 s**, peak RSS **331,492 KiB**. All 27 previously budget-deferred
observed function candidates were attempted: **3 gained core graphs with gaps,
24 exposed concrete unsupported interfaces**. Runtime-source core links rose
from one to **four**. Only one of those four has an exact code witness; the
others remain filename/qualname candidates with code mismatch. The unchanged
scope has fewer total body graphs (41 to 26), so counts alone are not progress.

Strict external replay passed in **450.457 s**, peak RSS **774,604 KiB**; all
151 source snapshots, trace bytes and LeWM clean Git state remain unchanged.
This is an analysis measurement, not
a new LeWM execution or acceleration; this single analysis is about 23 s slower
than N2.entry. The remaining 32 unsupported observed function candidates include
17 signature interfaces and three closure/cell interfaces. Next: bound-formal
body ports separate from definition/call behavior, then loop and state links.
See [N2_SCHEDULING_ACCEPTANCE.md](N2_SCHEDULING_ACCEPTANCE.md) and
[N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md). Whole-program recovery and any
LeWM transformation remain incomplete.

## Previous autonomous acceptance: N2.entry runtime-source bridge (2026-10-15)

Frozen implementation `b886e40` passed **429 mapped gate cases** and **1,477
repository tests** (two existing warnings). A source entry plus an archived
real trace now automatically selects runtime source candidates, expands their
shared import closure, attempts exact code reproduction, and persists source
definition/core-region links. No dynamic file/function list or workload graph
patch was supplied. Pure-source v1 inventory remains compatible.

The unchanged LeWM entry yielded **151 files**, **2,217 definitions** and
**10,235 source calls**, including eight files absent from the source-only
inventory. Generation took **402.571 s**, peak RSS **336,224 KiB**; strict
source/trace replay passed in **423.913 s**, peak RSS **785,256 KiB**. All read
source snapshots, trace bytes and LeWM clean Git state remained unchanged.
This is archived evidence analysis, not a new LeWM execution or A/B benchmark.

285 code/process groups produced 34 exact code-plus-definition matches,
222 mismatches, six missing definition joins and 23 external boundaries.
Filename/qualname candidates remain separate from exact code witnesses.
Although 41 bodies have core graphs with gaps, only **one** of the 256
runtime-source definition candidates links to a core region. 27 candidate
bodies were deferred by budget; 137 need class/lambda/comprehension interfaces.
The remaining 83 indexed definitions have no ordinary function body entry.

This accepts bounded source correspondence, **not** whole-program recovery,
callee/value/effect equivalence or a transformation. Next: global body demand
scheduling and separate bound-formal body interfaces from definition/call
behavior; then loops, state and cross-file composition. See
[N2_ENTRY_ACCEPTANCE.md](N2_ENTRY_ACCEPTANCE.md) and the proposed
[N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md). No new backend, target changes
or verified LeWM speedup.

## Previous autonomous acceptance: N2.b0 entry-driven source inventory (2026-10-15)

Implementation `f21eb53`, with efficiency repair `a6ed118`, adds `scar inventory-program entry.py --project-root ...`
and strict `scar check-inventory` replay. Local import candidates, definitions,
execution phases, coverage gaps and bounded core-body attempts are generated
without a user-supplied function list. The final frozen implementation passed
**336 gate tests** and **1,406 repository tests** (two existing warnings, no
failures or skips).

The first unchanged-LeWM source check was stopped after **919.862 seconds**
because SCAR repeatedly reconstructed and validated the same source layers.
It produced no final inventory and is retained as an incomplete attempt.
Generic schema caching and a same-snapshot construction path reduced redundant
analysis; public untrusted-graph replay remains mandatory.

The same source scope then produced 143 files, 2,122 definitions and 9,674
source calls in **401.595 seconds**, peak RSS **293,052 KiB**. Strict current
source replay passed in **405.052 seconds**, peak RSS **689,104 KiB**. All 143
source snapshots and LeWM Git HEAD/clean status were unchanged. These are
analyzer costs, not LeWM workload timings.

Only 16 of 256 attempted function bodies produced core graphs with gaps;
240 were unsupported, 1,307 functions exceeded the body-attempt budget and
559 definitions need other scope interfaces. The 115,723 coverage records
include just 163 source atoms connected to core graphs. Dynamic exec/compile,
unavailable external dependencies and unresolved call/state effects remain
explicit boundaries. This accepts bounded source inventory, not a full model.

Automatic whole-LeWM modeling, precise mutable-state/call links, optimization
guidance and workload acceleration remain incomplete. Next: connect observed
code loading to the source scope, prioritize expansion by entry/call/use
dependencies, then fill signature, loop and state interfaces. See
[N2B0_ACCEPTANCE.md](N2B0_ACCEPTANCE.md), [AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md)
and the proposed [N2B1_PLAN.md](N2B1_PLAN.md).

## Previous autonomous acceptance: N2.a automatic function source lowering (2026-10-15)

Frozen implementation `429e87e` passed **204** gate cases, including the 93 N1
compatibility cases, and **1,274** repository tests (two existing warnings,
no failures or skips). `scar model-program file.py --entry Class.method` now
automatically connects parameters, exact uses, branch merges, normal/raise
completions and conditional same-file call interfaces. Reports support gzip and
strict current-source replay through `scar check-source-program`. No manual
workload graph patches or target execution are required for this bounded mode.

The same command processed original external LeWM sources: `predict` produced
27 operations, 58 values and 63 uses; `get_cost` is unsupported at Assert line
129, and `CEMSolver.solve` is unsupported at its definition-time/signature
interface. All three reports replayed. Analysis including writing took
5.379/5.188/7.673 seconds, with peak RSS 44,504/43,204/50,644 KiB respectively.
These are source analysis costs, not workload profiling or speedup.

Whole-program automatic decomposition remains incomplete. The user still selects
a function entry; loops, cross-file/loaded method targets, fine state effects,
aliases and execution correspondence are not established. Unknown source
operations currently use one coarse world state. An effective optimization
cannot be inferred from structural validity or the presence of a call candidate.

See [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md), [AUTOMATIC_MODELING.md](AUTOMATIC_MODELING.md)
and the updated [N2 plan](N2_IMPLEMENTATION_PLAN.md). Next: automatic scope and
interface inventory, loop/state bindings, then runtime correspondence and
checked subgraph guidance. No new backend, LeWM rewrite or verified acceleration.

## Disk maintenance and automatic-modeling scope (2026-10-13)

SCAR-generated large artifacts were losslessly archived with decompressed
SHA256 verification. Cleanup freed **27.863 GiB**; the workspace is about
**1.4 GiB**. Source, tracked reports, Git history and LeWM were preserved.
Trace readers now accept gzip archives automatically; 26 relevant checks
passed. An archived real LeWM trace yielded its 45,888 events through the
ordinary directory entry in 2.308 seconds, without writing another large graph.
See [ARTIFACT_RETENTION.md](ARTIFACT_RETENTION.md).

Complete automatic decomposition of LeWM into the new core is still pending.
Manual IR exists as test fixtures, not the intended workload workflow.
[N2_IMPLEMENTATION_PLAN.md](N2_IMPLEMENTATION_PLAN.md) now explicitly requires
automatic construction and coverage reports without manually repairing the
workload graph, with parameter/merge/call/state/source links verified separately.

## Latest autonomous acceptance: N1 program types and dependency core (2026-10-13)

Implementation `8179cca` passed **93** gate cases and **1,157** repository tests
(two existing warnings, no failures or skips). Typed values, state locations,
operations and regions now have exact uses, bounded synchronous control,
state progression, call/exit interfaces and strict JSON validation. The public
`scar check-program` entry validates supplied graphs without executing them.

Independent tests first exposed two invalid-call acceptance bugs; these were
fixed and the resulting 27 adversarial checks are included in the gate. See
[N1_ACCEPTANCE.md](N1_ACCEPTANCE.md) and [PROGRAM_CORE_API.md](PROGRAM_CORE_API.md).
The complete examples are manually constructed IR. Automatic source recovery,
general exception calls, GPU readiness, autograd and optimization approval are
not established by this acceptance. No LeWM transform or speedup is verified.

Next: [N2_IMPLEMENTATION_PLAN.md](N2_IMPLEMENTATION_PLAN.md), adapting existing
source/opcode/CFG records with explicit parameter, merge and call bindings.

## Current priority: core program graph review (2026-10-13)

[PROGRAM_TYPES.md](PROGRAM_TYPES.md) distinguishes structural entity types,
composable operation behaviors and dependency relations. SCAR models program
execution, not human interpretation of payloads: saving video and tensor data
uses the same encoding/state-write building blocks. This is a design clarification.

[CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md) proposes four top-level semantic node families:
Operation, Value, StateLocation and Region. Values have typed data/reference/
state-version variants; input/output are port roles. Ordered uses, control,
state conflicts, effects and region boundaries define what simplification must
preserve. N1 now implements the bounded structural core; source recovery and
broader coverage remain pending. Four families are not a completeness proof. The
[N0 review](N0_CORE_GRAPH_REVIEW.md) accepts scoped design consistency only.
[LeWM source stress cases](LEWM_SEMANTIC_COVERAGE_REVIEW.md) distinguish entity
classification from actual operation rules, dependency queries and proof.

The pre-N1 code audit found no general StateLocation/StateVersion model; state_slots
is largely a reserved interface, and actual computation/value connections live
in an optional source overlay. More trace collection cannot replace these
missing semantics. N1 has addressed the declared-graph core; N2–N4 precede the
pending G7 proof/plan work.

The incomplete reference collector is archived, not merged into main, on
[wip/reference-evidence-20261013](https://github.com/hbswcsyzx/scar/tree/wip/reference-evidence-20261013)
at `2e08b4c`. At frozen implementation `0b90f38`, 80 component checks passed and
one integration test failed; this is not a gate or full regression acceptance.
The profile/monitoring combination did not yield the required instruction
stream. No valid positive capture or measurement is claimed for that draft.

No new backend, selected LeWM transformation or verified acceleration exists.

## Latest autonomous acceptance: G7.2b narrow static MOTION

Implementation `1cf6965`, with legacy-fixture repair `750639f`, passed **179**
mapped cases and **1,064** repository tests (two existing warnings, no skips).
Whole source statements, first-local bindings, precise insertion anchors,
source control and scoped Q now connect to six fixed recomputable MOTION
obligations. See [G7_2B_MOTION_ACCEPTANCE.md](G7_2B_MOTION_ACCEPTANCE.md).

One explicitly queried external straight-line alias assignment yields
NEEDS_CONTRACT with default empty Q; under the synthetic fixture's 26 precise
DECLARED conditions, all six obligations replay as PROVEN and the ledger is
CONDITIONALLY_LEGAL. It remains NOT_SELECTED, cost PENDING and applied=false.
Analysis took 0.875 seconds (0.897 with write), peak VmHWM 30,796 KiB. This is
analysis overhead, not target execution or workload speedup.

Raw MAY_RAISE edges remain; queries use ALL_PATHS. Branches, loops, handlers,
mutable values, calls, rebinding and unavailable inputs cannot use this narrow
rule. Initial legacy schema fixture failures and subsequent repair are archived.
Both external reports strictly replay against unchanged inputs and current
models; LeWM remains unchanged. No detector or backend was added.

This accepts the narrow MOTION part of Step 2 only. Object-only identity,
operand-site/event evidence and positive REUSE remain pending; full G7.2b,
import-to-CONSTANT ledger guidance and parent G7 remain incomplete. There is
still no selected LeWM rewrite or verified LeWM acceleration.

## Previous autonomous acceptance: G7.2b Step 1 models

Implementation `c7f68ce` passed 55 mapped gate cases and 995 repository tests
(two existing warnings, no skips). Typed invocation-to-slot bindings, separate
source control/insertion graphs and fixed identity primitive semantics now
provide proof inputs. See [G7_2B_MODELS_ACCEPTANCE.md](G7_2B_MODELS_ACCEPTANCE.md).

The external CEM source produced 11 lexical scopes, 420 control nodes, 514
edges, 245 insertion points and seven body/backedge/zero-exit paths. It retains
24 control gaps and one operator-only identity certificate. Analysis took
13.901 seconds (14.684 including write), current executable VmHWM 76,948 KiB.
Strict decoding and current source replays passed; LeWM remains unchanged.

This accepted Step 1 foundations only. The subsequent narrow static source
delta/MOTION acceptance is recorded above; positive REUSE, object-only
identity and full G7.2b remain pending. There is no selected LeWM rewrite or
verified workload acceleration.

## Previous autonomous acceptance: G7.2a

Implementation `141390e` plus measurement fix `603819d` passed 162 mapped
cases and 940 repository tests (two existing warnings, no skips). Static
source/OIR identities, typed conditional binding boundaries, generic import
value provenance and fixed recomputable CONSTANT/semantic DEAD ledgers are
connected. See [G7_2A_ACCEPTANCE.md](G7_2A_ACCEPTANCE.md).

The three-file generic external testcase derives the final RHS as conditional
int(7), retaining import, re-export, attribute and two index steps. Five
nonliteral conditional guidance records remain NOT_SELECTED/PENDING; import
deletion is NOT_PROVEN. Analysis took 0.646 seconds, including write 0.702
seconds; current executable VmHWM was 29,312 KiB, gzip report 37,959 bytes.
This is analysis overhead, not target execution or workload speedup.

G7.2a is partial acceptance. REUSE/MOTION positive witnesses and execution
instance DEAD remain unsupported; import facts are not yet bridged into the
CONSTANT ledger. G7.2b proceeds under [G7_2B_PLAN.md](G7_2B_PLAN.md), before
G7.3 precise composite plans and G7.4 external pressure. No LeWM source change,
selected rewrite or measured acceleration has been verified.

## Previous autonomous acceptance: G7.1

Implementation `d5fe9cb` passed all 163 mapped G7.1 cases and 848 repository
tests, with two existing warnings and no skips. Ordered operation semantics,
per-use local bindings, exact typed literals, source replay and bounded builtin
constant derivations are connected. See [G7_1_ACCEPTANCE.md](G7_1_ACCEPTANCE.md).

Eight explicitly selected LeWM source files were analyzed independently:
9,340 SG operations, 6,636 computational records, and 2,704 retained unmodeled
operations. There are 1,116 conditional constant facts, including 89 derived
operations beyond direct literals; these are not approved optimization counts.
Analysis took 22.955 seconds, peak RSS 116,568 KiB. Exact implementation/input
hashes and the 2,948,824-byte compressed report are archived. All hashes were
rechecked during acceptance archival on 2026-10-03; this is the original
measurement, not a new run.

Required source execution and builtin/floating-environment conditions remain
explicit and unaccepted. Independent verification ceilings now prevent an
imported report from raising its own recomputation budget. Finalizer and mapping
expansion counterexamples prevent stale binding proofs.

The G7 parent gate still requires graph rewrite rules, a checked proof ledger,
precise modification plans and external pressure. G7.2 proceeds autonomously;
no target source change, LeWM rewrite or workload speedup is verified.

## Previous autonomous acceptance: G6

At `4451372`, all 160 G6 mapped cases and 685 repository tests passed, with
two existing warnings and no skips. Typed composite regions retain definitions,
invocations, source slots, data/effect/control/resource interfaces and NO-OP.
Origin, proposed motion and conflict queries preserve their proof obligations.
See [G6_ACCEPTANCE.md](G6_ACCEPTANCE.md).

Archived LeWM pressure at `2a29ed4` accounted for 45,888 input records and
selected one observed subtree with 21,874 invocations. One top-level region
has 133,477 conservative ports, six open boundary facets and zero selected
transformations. Analysis took 278.724 seconds (299.109 with report writing),
peak RSS 1,385,388 KiB. The 14,383,421-byte gzip report and exact hashes are
versioned. Other clock/thread scopes were disclosed rather than merged.

The first pressure attempt was terminated after 333 seconds. Structural
counterexamples drove repairs for repeated port scans, sibling assembly,
wide explicit membership and repeated ancestor walks. Scope corruption now
returns an invalid report. The final public-API fixes are separately tested;
the recorded real pressure remains bound to its actual earlier revision.
Repeated full validation and large conservative interfaces still cost minutes.

G6 does not prove effect/control/alias closure from absent edges. G7 proceeds
under [GRAPH_SIMPLIFICATION.md](GRAPH_SIMPLIFICATION.md), beginning with typed
source semantics and per-use bindings. No LeWM rewrite or speedup is verified.

## Previous autonomous acceptance: G5

Implementation `4a0ae57` passed all 112 mapped G5 cases; full regression passed
525 tests (two existing warnings, no skips). The public `scar inspect-v2`
command connects source-code witnesses, runtime effect evidence and explicit
preservation policies without executing or modifying the target.

Archived LeWM pressure: 84 explicitly selected Python files and 45,888 raw
records. Exact code-object witnesses joined 34 definitions / 2,041 instances;
222 definitions did not reproduce the stored digest, 6 lacked needed evidence,
and 70 were outside selected source coverage. A mismatch is not proof the source
changed: missing compilation/loader context can also explain it. No globals,
closure or value identity follows from a code-only join.

The effect-removal diagnostic queried 332 definition/scope boundaries: **16
KEEP, 316 CONTRACT, zero selected transformations**. It retained 80 return escape
effects, 543 physical-copy writes and 360 barrier effects. All three runtime
scopes remain open. These counts are diagnostic region queries, not the old
candidate counts or a measured reduction in LeWM work.

Offline analysis took 207.179 seconds, peak RSS 1,166,036 KiB. Inputs and code
hashes stayed unchanged. Full evidence is saved locally as
`artifacts/reports/gates/g5-lewm-inspection.json`; its deterministic gzip archive
(5,164,158 bytes) and pressure/gate reports are versioned. The uncompressed
122,748,547-byte report repeats request/source information; reference-table
compaction remains a reporting efficiency limitation, not evidence of a
lightweight analysis. No tensor value payloads were added.

G5 also repaired a G3 defect: paired returns previously lost escape/callback
metadata. Six focused tests now preserve separate return-boundary evidence;
return callbacks still do not prove exception absence. Import-effect tests use
explicit generic contracts and do not claim automatic arbitrary import purity.

G6 proceeds automatically under [REGION_BUILDER.md](REGION_BUILDER.md). LeWM
remains unchanged, and no LeWM transformation or speedup has been verified.

## Previous autonomous acceptance: G4

Implementation `a473f1a` passed 71 G4 gate cases; the repository regression
suite passed 413 tests (two warnings, no skipped tests). Typed provenance and
validity ledgers, generation-aware allocation identities, branch-on-write
copies, alias invalidation, strict serialization, explicit observation
attachments and bounded checkpoints are implemented. See
[PROVENANCE_REGISTRY.md](PROVENANCE_REGISTRY.md).

Real CUDA checkpoint experiment: RTX 4090, PyTorch 2.13.0+cu132 / CUDA 13.2,
65,536 float32 elements (256 KiB), 2 warmups, 7 repetitions. Median actual warm
`TensorObserver.observe` was 18.683 microseconds; explicit bitwise comparison
including CUDA synchronization/transfer was 2.801 milliseconds. Full min/max,
variance, source hashes and budget/release checks are in
`artifacts/reports/gates/g4-checkpoint-pressure.json`. This is capture overhead,
not workload acceleration; expensive checks stay explicit and budgeted.

Ordinary observations do not copy tensor contents. Foreign writes without
write evidence remain NEEDS_VERIFICATION. Exact comparisons establish only
capture-time content equality. Copy collectors and SG/EEG attachments are
opt-in; old trace tokens never retroactively certify value equivalence.
No LeWM rewrite or speedup is established. G5 now proceeds under
[EFFECT_CLOSURE.md](EFFECT_CLOSURE.md), without a user approval checkpoint.

## Previous acceptance: G2 and G3

At implementation commit `1af7d14`, G2 passed 23 collected acceptance cases,
G3 passed 16, and the full regression suite passed 340 tests (one existing
fork/thread warning). Reports are under `artifacts/reports/gates/`:
`g2-verified.json`, `g3-verified.json`, `g2-g3-regression.json`.

The nonexecuting frontend builds typed operations, lexical value flow and
control regions. It conservatively preserves unsupported syntax and dynamic
calls as opaque boundaries. Static may-flow is not SSA, purity, consumer
closure or logical equivalence. `model-v2 --project-root` selects the entire
source tree, not only entrypoint-reachable files.

Real external LeWM source pressure: 581 files, 501,160 source atoms all owned,
469,343 operation definitions, 2,060,031 edges; valid graph in 247.741 seconds,
peak RSS 2,422,252 KiB. This includes vendored/local project code. The first
attempt exposed quadratic registry membership checks and was terminated;
the corrected implementation has a structural scaling regression test.

Archived LeWM trace pressure: all 45,888 records accounted for, including 14
calls with missing returns; 543 actual memcpy events remain distinct from
561 host transfer calls and 175 aggregate measurements. Conversion took
45.430 seconds, peak RSS 832,080 KiB. Reports `g2-source-pressure.json` and
`g3-runtime-pressure.json` bind implementation/input hashes and scope.
These are SCAR conversion measurements, not a new workload run or speedup.

The following G4 design introduced logical provenance and bounded, opt-in exact
checkpoints, under [PROVENANCE_REGISTRY.md](PROVENANCE_REGISTRY.md).
No new detector/backend was added. v2 still does not select a LeWM rewrite.

## G1 foundation recheck

The initial G1 report overstated coverage. Counterexample-driven repairs added
strict decoding, graph/region boundary validation and individual test evidence.
The corrected `g1-verified.json` records 136 passing cases at `aff0c20`.
See [GATE_EXECUTION.md](GATE_EXECUTION.md). Schema checks cannot establish the
truth of arbitrary externally asserted proofs; semantic proof construction
remains a separate stage.

The architecture review is recorded in [IR_DESIGN_V2.md](IR_DESIGN_V2.md) and
[IR_MIGRATION.md](IR_MIGRATION.md). The first M1 foundation is now implemented
in `scar/ir/v2/`: typed identities separate logical versions, provenance,
objects, allocations, regions and materializations; semantic definitions are
separate from dynamic instances; and value/semantic/evidence validators reject
unknown references, provenance-output mismatches and cyclic ancestry. The
micro-fixture suite is `tests/unit/test_ir_v2.py`. This is a schema-level result
only. The existing v1 trace, static graph, detectors and planner are
intentionally not wired to v2 yet, and no new optimization backend was added
in this phase.

The current report-only analysis phase also provides `audit-rejections`,
`analyze --topdown-out`, and `constants`. The first separates proven blockers
from evidence gaps, the second summarizes dynamic regions from children
upward, and the third records literal provenance across local imports. None of
these commands transforms a workload. On a real LeWM trace, the audit found
960 proven intervening-write blockers and 1568 evidence-gap records; the
top-down report still has 2528 `UNKNOWN` placements because provenance and
effect contracts are incomplete. See [REJECTION_AUDIT.md](REJECTION_AUDIT.md).

SCAR is a generic Python/PyTorch/GPU execution optimizer. Its intended scope is
avoidable work across computation, representation, memory, transfer, state,
control, ordering and external interaction. LeWM is an external testcase.
No core analysis imports its adapter or branches on its names.

This is an active prototype, not a completion claim for `../init.md`.

The pre-migration generic regression baseline had 155 passing tests. The separate
`/home/zyf/AAA/scar-testcases/lewm` project has its own passing adapter test;
no LeWM adapter or test remains in the SCAR source tree. Candidate reports
now contain explicit proof obligations for applicability, legality and cost;
the cost planner refuses an otherwise profitable estimate when any required
precondition is `UNKNOWN` or `DISPROVEN`.

A fresh clean GPU micro benchmark for the state/RNG guarded exact-reuse backend
used 1 warmup and 5 repetitions on an RTX 4090. Median time changed from
47.553 ms to 11.435 ms (4.158×); outputs and visible input/RNG state matched. This is a
generic Level 1 backend result, not a LeWM speedup. Evidence is in
`artifacts/experiments/micro_reuse_state_complete_clean.json`.

A fresh independent GPU trace verifies the matching model side. Four
`scar_pure` module invocations each captured 18 pre-forward inputs, including
four parameters, five training flags and five custom attributes; post-forward
state was stable and exact-reuse legality obligations were proven. Cost
remained `UNKNOWN`, so analysis selected no transform. Evidence is in
`artifacts/traces/generic_state_complete_20260917/` and
`artifacts/reports/generic_state_complete_20260917.summary.json`.

A separate generic callback/closure trace produced 12 Python call/return
events, two callable captures and two explicit `captures_callable` graph edges.
The callback's code/object identity and `bias` closure Tensor were observed,
while registry/global completeness remained `UNKNOWN`; selection chose no
transform. Evidence is in
`artifacts/reports/generic_callback_closure_20260917.md`.

A second generic subprocess returns a stateful closure. Its graph contains one
callable State node and one `escapes(status=UNKNOWN, escape_kind=callable)`
edge; the observed identity is retained while caller retention and invocation
order remain unproven. This is the conservative behavior required for
returned callbacks. Evidence is in
`artifacts/reports/generic_callback_return_20260917_v2.summary.json`; the two
callback invocations are also detected as one `PythonReuseCandidate`, but its
incomplete Python effect contract is rejected.

The tracer also records side-effect-sensitive CPython `c_call` boundaries in
user frames. A generic returned-closure script produced one observed `print`
action with `CTRL+IO+OPAQUE` labels; argument and return capture stay
`UNKNOWN`, so this boundary can block an unsafe simplification without
pretending to explain the C implementation. Evidence is in
`artifacts/traces/generic_callback_return_20260917_c/` and
`artifacts/reports/generic_callback_return_20260917_c.summary.json`.

Thread propagation is also verified with an independent worker-thread
program: the worker's `python_call` and its `print` C-call share the trace
while retaining a distinct thread ID. The run returned code 0 and produced
12 events; its five detected candidates were rejected. Evidence is in
`artifacts/traces/generic_thread_20260917/` and
`artifacts/reports/generic_thread_20260917.summary.json`.

Fork provenance is covered by a direct `os.fork` regression: the child event
uses the child PID namespace and receives `forked_from_pid` metadata, while the
parent metadata remains separate. This is a structural identity guarantee;
forked CUDA runtime activity still requires a process-safe profiler contract.

The loop-control graph now connects an observed bytecode back-edge marker to
later Actions in the same dynamic loop scope. The generic loop trace contains
four `loop_iteration` events and four `loop_controls` edges; actions before the
first marker remain unassigned. Evidence is in
`artifacts/reports/generic_loop_controls_20260917.md`.

The graph simplifier now consumes those observed edges through a generic
`GraphLoopInvariantCandidate`. It compares logical versions and full region
geometry across distinct loop markers, rejects changed inputs, and leaves
hoisting equivalence UNKNOWN for the planner. Two synthetic positive/negative
tests cover this graph path; no workload name or function name is used.

The unified analyzer now emits a complete Action inventory in addition to
candidate lists. Every static or dynamic Action receives its multi-label
families and a conservative disposition; on the latest LeWM trace all 45,894
Actions were accounted for, with 45,893 `UNKNOWN` and one `REJECT` because most
runtime effect collections remain incomplete. No unrecognized Action is
silently treated as KEEP. Evidence is in
`artifacts/reports/lewm_resource_sampled_c_call_20260917_inventory.summary.json`.

Nested ordinary Python calls and returns now retain the nearest active outer
loop scope in their metadata (`loop_parent_invocation_id`, target offset and
iteration). This keeps the K control view intact when a loop body crosses a
user-function boundary; the new regression is covered by the 155-test suite.
A fresh generic PyTorch loop smoke confirmed this at runtime: three module
calls and three observed back-edge markers produced two post-back-edge module
records with the propagated outer scope, seven `loop_controls` edges, and
three graph loop candidates. All remained rejected because the trace did not
prove hoisting legality or clean cost; this is control evidence, not a
transformation claim. The machine-readable result is in
`artifacts/reports/generic_nested_loop_20260917.summary.json`.

The generic runtime optimizer now has an inferred contract for exact,
deterministic built-in PyTorch module classes. It validates the first repeated
key by executing the original once, checks output/effect equality, and uses a
measured steady-state cost comparison to disable an unprofitable module. A
CPU/GPU Linear smoke showed the contract correctly falling back after cache-hit
overhead exceeded the measured original compute; this is the required cost
decision behavior, not a claimed workload speedup. The external LeWM A/B run
using this backend remains outstanding.

The supplied LeWM line-modeling archive has been independently audited. Its
mechanical coverage is supported (`source_byte_exact=true`, 2,803 line rows,
18 ledgers), while its semantic labels remain static hypotheses: the bundle
has no GPU profile and does not prove transformation equivalence. See
[`LEWM_MODELING_REFERENCE_AUDIT.md`](LEWM_MODELING_REFERENCE_AUDIT.md),
`artifacts/reports/lewm_modeling_zip_review.json`, and the reproducible script
`artifacts/experiments/audit_lewm_modeling_zip.py`.

Latest independent generic smoke (`scar.workloads.micro`, four repeated
iterations) returned code 0 and produced 98 events, 43 typed opportunities,
and 4 Kineto H→D copies. All 43 decisions were conservatively rejected
because the generic trace did not prove complete effects and guard/cost
evidence. The machine-readable run is under
`artifacts/traces/generic_latest_20260916/` and
`artifacts/reports/generic_latest_20260916.*`.

The same smoke now also runs the independent graph pass. Its proof report has
47 candidates total, 46 `UNKNOWN` decisions and one `REJECT`; no transform is
selected. On the archived pre-C-call LeWM trace, graph reconstruction produced 1,071 graph
candidates while preserving the original 1,457 event-level candidates. The
unified proof ledger classifies 960 as `REJECT` due to observed intervening
writes and 1,568 as `UNKNOWN`; no transform is selected. Evidence is in
`artifacts/reports/generic_latest_20260916_proofs.summary.json` and
`artifacts/reports/lewm_resource_global_proofs.summary.json`.

The graph now also emits three-valued liveness facts. The latest LeWM graph
has 6,799 LIVE states and 2,027 UNKNOWN states; none is classified DEAD under
the ordinary external-trace scope. Evidence is in
`artifacts/reports/lewm_resource_global_liveness.summary.json`.

The planner now has a generic graph simplification selection layer. It merges
event and graph candidates, prevents conflicting transforms for one CodeID,
and preserves `TRANSFORM`, `REJECT`, `UNKNOWN`, and `KEEP` as separate audited
outcomes. This layer selects plans; it does not claim that an unproven LeWM
candidate is legal.
A generic five-candidate selector demo verified all four outcomes and
conflict resolution; evidence is in
`artifacts/reports/selection_layer_demo.md`.

The static model also covers the external LeWM entrypoint independently of
the runtime trace: all 84 physical lines of `le-wm/run_inference.py` are
represented by 301 graph nodes and 492 edges (including the synthetic module
node, module containment, and conservative CFG/data-flow relations). `scar model` now accepts a
directory through the same generic API: it merges per-file graphs, creates
module nodes, and adds only statically resolvable local import edges. Calls
receive additive syntax
hints such as `XFER`, `MEM`, `REP`, `STATE`, `ORDER` and `IO`, with `OPAQUE`
retained whenever static behavior is not provable. Evidence is in
`artifacts/reports/lewm_run_inference_summary.md`; the generic call-family
example is in `artifacts/reports/call_families_summary.md`.

The directory-level model now joins the whole external LeWM checkout to the
same real trace. It modeled 581 Python files and linked all 4,155 dynamic events
whose source belongs to that project (100% eligible-event coverage): 3,396 by
loaded function span and 759 by exact path/line, while retaining 446 ambiguous
events. The unified graph has 834,790 nodes and 1,628,494 edges. This offline
run took 404.10 s and peaked at 4,539,492 KiB RSS, so graph storage and indexing
remain an explicit engineering cost. Evidence is in
`artifacts/reports/lewm_resource_global_project_link.md` and its JSON summary.

The current dynamic graph pass also records 22,999 observed same-stream CUDA
ordering edges on the real trace (one stream, `7`, device `0`), while inferring
zero cross-stream edges. The resulting dynamic-only graph has 210,581 nodes and
568,652 edges; this evidence is separate from the archived graph report whose
edge count predates the stream-order relation.

The resource-enabled LeWM run also produced 259 samples. Process CPU was
2.31% average / 38.52% peak, GPU utilization 0.74% average / 23% peak, and GPU
memory 438 MiB average / 2,250 MiB peak. These are `Observed` measurements from
an instrumented run, not a clean A/B performance claim.

The post-C-call-hook LeWM rerun returned code 0 with `success_rate=100.0` in
104.854 s and produced 45,894 events. Four observed C-call boundaries
(`append`×3, `setdefault`×1) were retained as `CTRL+STATE+OPAQUE`; the generic
detector emitted 1,465 rejected opportunities and selected zero transforms.
This confirms the boundary instrumentation on the external testcase while
keeping LeWM outside SCAR's implementation.

Reanalyzing that same trace after the graph-loop pass produced a valid dynamic
graph with 210,846 nodes and 580,054 edges; because this trace was collected
without `--lines`, it produced zero graph-loop candidates. The independent
generic loop trace, analyzed through the same CLI, produced one
`GraphLoopInvariantCandidate` from four observed `loop_controls` edges and
rejected it after retaining UNKNOWN hoisting evidence. The machine-readable
analyses are in
`artifacts/reports/lewm_resource_sampled_c_call_20260917_graphloop.summary.json`
and
`artifacts/reports/generic_loop_controls_20260917_graphloop.summary.json`.

An additional full-command control-flow capture completed with return code 0
and `success_rate=100.0`: it observed 7,218,041 Python line events and
2,377,804 bytecode back-edge markers in a 10.79 GB event file. Its wall time
was 1,415.135 s under line instrumentation, so it is not a benchmark. The
capture's module records did not carry loop metadata, and SCAR therefore
created no loop edge from record order; this is recorded as an UNKNOWN
boundary in `artifacts/reports/lewm_lines_20260917.json`. The subsequent
generic stack propagation fix is covered by unit tests and awaits a smaller
valid LeWM control capture before claiming module-loop correspondence.

`scar analyze --closed-world` now exposes the explicit closed-scope contract;
on the generic smoke it produced 9 LIVE and 1 DEAD fact. This is a proof
precondition for future dead-work elimination, not an automatic deletion.

| Requirement | Current evidence | Remaining work |
| --- | --- | --- |
| K/Σ/A/R/Q/M graph | Versioned serializable static/dynamic graphs, structural validation, statement CFG, function-span and path/line correspondence, observed producer→consumer `data_depends`, `overwrites`, and `escapes` edges | Join source regions with runtime spans and complete dependencies; resolve remaining ambiguous AST nodes |
| Every source line | Static physical-line coverage plus closed nine-label Action taxonomy validation; the current LeWM entrypoint is 84/84 represented and 84/84 classified | `OPAQUE` is an explicit unknown; coverage/classification do not mean every line's effects are understood |
| Code identity/version | Source snapshot and loaded-code SHA-256 tests | Version operator schemas/library binaries too |
| Object/storage/region/version | Region overlap, explicit epochs, physical materialization links, observed Tensor call inputs and return escapes, callable/closure identity records | Comprehensive allocation lifetime, callback registry/closure escape and foreign-write observation |
| Effects and UNKNOWN | Collection completeness, escapes, all-invocation checks, pre/post pure-module parameters/buffers/training/custom state, and runtime RNG guard | Closure, callback and external-state proofs remain incomplete |
| Physical transfer evidence | Per-process Kineto GPU memcpy events, bytes, correlation, and conservative unique-signature logical links | Replace inferred signature joins with shared runtime IDs where available; preserve UNKNOWN for ambiguous copies |
| Control/ordering | Thread/process provenance, call/return nesting, side-effect-sensitive C-call boundaries, observed `loop_controls` edges from line back-edge markers, separate clock domains, observed same-stream `stream_order` edges | Complete loop nesting/iteration joins and cross-stream/host CUDA happens-before; record order is not dependency |
| Candidates | Repetition, allocation, residency, host materialization, barriers, static/runtime and graph loop-invariant hypotheses with machine-readable proof ledgers; repeated user-Python regions are emitted as `PythonReuseCandidate`; complete Action inventory accounts for unrecognized Actions as `UNKNOWN` | Prefetch, fusion, capture/replay, complete liveness and escape analysis |
| Cost decision | Unknown overhead cannot be zero; explicit memory budget; clean A/B micro runs | Measure and bind guard, lookup, lifetime and savings costs per candidate |
| Backend | Opt-in exact reuse, persistent residency, and a closed-world/pure guarded source dead-expression rewrite; graph-selected accepted plans reach tested generic routes | Runtime graph-to-source mapping beyond path/line and external-workload application; all contracts are declarations |
| Validation | Generic Level 1 checks, layered Levels 1–4 API, executable `validate_callables` runner, negative tests, and explicit return escape evidence | LeWM fixed-input CEM, policy state, full episode trajectory A/B using real optimized execution |
| External testcase | Unmodified LeWM executes and yields graphs/candidates; latest post-C-call run has 45,894 events and 1,465 rejected candidates | No LeWM optimization is yet validated or enabled |

## Ordered next steps

1. Keep trace facts and claims aligned: versioned code, complete effect
   uncertainty, measured CUDA activities, and independent cost evidence.
2. Connect host spans, operators, Tensor regions, runtime correlation IDs and
   CUDA activities. Strengthen the current path/line correspondence with
   function spans and explicit read/write/alias/escape dependencies rather than
   inferring causality from file order.
3. Extend the reusable region contract and CodeID-to-runtime mapping. The
   generic dispatcher now applies an accepted plan and returns an explicit
   no-op otherwise; add adversarial tests before enabling it on an external
   workload.
4. Save fixed external-workload inputs and required states; run validation
   Levels 1–4 for the selected transformation. A successful episode without a
   transformation does not substitute for this comparison.
5. Measure clean repeated baseline/optimized runs with resource samples and
   reject unprofitable plans. Only then add another backend.

## Corrections to historical results

Earlier 5.38× (and other older) micro speedups used an incomplete mutation
guard. They remain historical measurements, not evidence for the current
strict backend. The current clean result is
`micro_reuse_state_complete_clean.json`; strict historical experiments are
retained as `micro_reuse_strict_factor*.json`.
Earlier Tensor transfer counts measured device transitions, not correlated
CUDA memcpy activities. Earlier reports are marked historical accordingly.

See `../artifacts/experiments/strict_guard_manifest.json` and run
`python artifacts/experiments/verify_strict_guard_manifest.py` for current
tests, performance, provenance, and external-workload evidence. The older
`strict_guard_audit.md` is retained as historical context. Unknown or rejected
cases remain visible so the model can expand without treating missing evidence
as proof.

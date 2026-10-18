# SCAR v0.1.0

Start with the [current modeling and tool reuse decision](docs/MODELING_REUSE_DECISION.md)
for entity types, dependency relations, provider responsibilities and actual gaps.

**Current priority:** [complete the program model](docs/WHOLE_PROGRAM_MODEL.md)
before whole-program graph recovery and simplification. The
[ordered gates](docs/WHOLE_PROGRAM_MODEL_PLAN.md) distinguish specifications,
implemented types, automatic connectivity and optimization authority. The
[bounded synchronous implementation](docs/N2_STRUCTURED_BODY_ACCEPTANCE.md)
passes its declared checks; complete LeWM modeling and a verified speedup
remain unfinished.

The [exact literal content/source/evaluation interfaces](docs/M1_LITERAL_INTERFACES.md)
pass [1,716 component checks /32 criteria and 5,294 clean frozen full tests](docs/M1_LITERAL_ACCEPTANCE.md)
(`4bc55eb`). Exact abstract Data content and source declarations attach to the
original producer ports; matching payloads do not establish object identity or
remove effects. All prior 5,144 case identities/74 fixtures survive; current 603
source hashes and 78 fixtures match. Complete C2/D3/M2, automatic source/runtime
correspondence, whole-program recovery and LeWM simplification remain unfinished.
No new workload speedup was measured.

The earlier [typed state-address interfaces](docs/M1_STATE_ADDRESS_INTERFACES.md)
pass [1,317 component checks /25 criteria and 5,144 clean frozen full tests](docs/M1_STATE_ADDRESS_ACCEPTANCE.md)
(`805c670`). Owner/key/selector effects refine original state carriers and actual
invocation ports; they introduce no separate field state chain or alias proof.
All prior 5,055 case identities/72 fixtures survive; current 590 source hashes
and 74 fixtures match. Automatic source/native identity, full literal/C2/D3/M2,
whole-program recovery and LeWM simplification remain unfinished. No new
workload speedup was measured.

The earlier [R3.3 generic buffered pipeline model](docs/M1_PIPELINE_CLOSURE_API.md)
passes [722 component checks /17 criteria and 5,055 clean frozen full tests](docs/M1_PIPELINE_CLOSURE_ACCEPTANCE.md)
(`6947778`). Exact call order, independent byte extents, buffer→flush→file and
exception/pending cleanup paths preserve original associations in one model.
Three real bounded OS cases are separately attributed. All prior 5,011 cases
and 69 fixtures survive; current 578 source hashes/72 fixtures match. This closes
the limited R3.3 plan. Full M0–M2, automatic program recovery and LeWM
simplification remain unfinished; there is no new measured speedup.

The earlier [R3.2 Q and original execution evidence composition](docs/M1_PIPELINE_COMPOSITION_API.md)
passes [677 component checks / 13 criteria and 5,011 clean frozen full tests](docs/M1_PIPELINE_COMPOSITION_ACCEPTANCE.md)
(`31bf2e4`). All previous 4,951 case identities and 68 fixtures survive.
Typed query scopes preserve expected obligations when Q rows are missing;
original data/control/state/call/source/work associations share one budget and
one fresh external context. This composes supplied models, not automatic program
recovery or transformation proof. At that checkpoint, R3.3, full M0–M2 and
automatic LeWM simplification remained open; no new speedup was measured.

The earlier [R3.1 call activation and work-set connections](docs/M1_CALL_ACTIVATION_API.md)
pass [591 component checks / 8 criteria and 4,951 clean frozen full tests](docs/M1_CALL_ACTIVATION_ACCEPTANCE.md)
(`881cbfb`). All previous 4,826 test identities and 65 fixtures survive.
Original argument/completion/state ports remain canonical; declared routes do
not prove runtime identity. Execution v7 retains v1–v6 bytes. Whole R3,
complete M0–M2 and automatic LeWM simplification remain open. Next is complete
Q-rooted load/consume/save composition at that checkpoint; R3.2 is recorded above.

The [R2.3-V content validity/support interfaces](docs/M1_VALIDITY_API.md)
now connect source-derived labeled actual/future coverage, exact alternatives,
original effects, conservative whole-read threats and target lifetimes. Its
[acceptance](docs/M1_VALIDITY_ACCEPTANCE.md) passes **649 checks / 11 criteria**
and **4,826 clean frozen full tests** (`550496f`); all prior 4,713 identities and
59 fixtures survive. Execution v6 preserves v1–v5 bytes. Endpoint protocol
parsing, native capture, R3 and full M0–M2 remain open. Conditional MATCHED does
not grant readiness or transformation; no new LeWM speedup was measured.

The earlier [R2.3-P source/write/production interfaces](docs/M1_PRODUCTION_API.md)
now connect independent raw-source manifests, strict normalization replay,
scoped endpoint bridges, original writes and actual partial outcomes. Its
[acceptance](docs/M1_PRODUCTION_ACCEPTANCE.md) passes **477 component checks /
8 criteria** and **4,713 clean frozen full tests** (`c84fbfe`). All prior 4,568
test identities and 54 fixtures survive. Execution v5 retains v1–v4 bytes.
That checkpoint left native complete writer capture, V interval validity/visibility,
R3 and full M0–M2 open; the bounded V interfaces are described above. Automatic
LeWM modeling and speedup remain unfinished.

The earlier [R2.3-D content/consumer interfaces](docs/M1_CONTENT_CONNECTION_API.md)
connect original ports, scoped denotations/materializations, exact work/source
associations and explicit contract observation roots. Its
[acceptance](docs/M1_CONTENT_CONNECTION_ACCEPTANCE.md) passes **445 component
checks / 7 criteria** and **4,568 clean frozen full tests** (`f71740e`).
Execution v4 preserves v1–v3 bytes. Missing source pairs remain explicit gaps;
That checkpoint left P production, V stability/visibility, R3 and full M0–M2 open. It does
not establish automatic LeWM modeling, transformations or a speedup.

The [R2.3 contract](docs/M1_RESOURCE_READY_CONTRACT.md) separates exact consumer
denotation, source-derived production, read-interval validity and visibility.
Its [shared geometry prerequisite](docs/M1_RESOURCE_COVERAGE_ACCEPTANCE.md)
passes **432 component checks / 6 criteria** and **4,427 clean frozen full tests**
(`aa2b917`).
The original MatRef query compares budgeted byte coverage only. P/V and
complete first-stage modeling remain open; it grants no ready/transform authority.

The [R2.2 event/order component](docs/M1_RESOURCE_ORDER_INTERFACES.md) connects
exact event generations, original state/resource ports and bounded queue profiles
to conditional producer-end→consumer-start paths. Its
[acceptance](docs/M1_RESOURCE_ORDER_ACCEPTANCE.md) passes **497 checks / 7 criteria**
and **4,387 clean frozen full tests** (`e8121f0`). Execution v3 preserves original v1/v2
bytes. Consumer production/denotation/ready, complete M0–M2 and a verified LeWM
speedup remain open.

The [R2.1 work foundation](docs/M1_RESOURCE_WORK_INTERFACES.md) now connects
actual access/INVOKE completion effects, work terminal observations, independent
quiescence and resource retention. Its [acceptance](docs/M1_RESOURCE_WORK_ACCEPTANCE.md)
passes **407 checks / 9 criteria** and **4,297 clean frozen full tests** (`bb1b402`).
Execution v2 retains byte-exact original
v1 compatibility. [R2 consumer-ready](docs/M1_RESOURCE_WORK_PLAN.md)
and complete first-stage modeling remain open; no new LeWM speedup is claimed.

The [tooling survey](docs/TOOLING_SURVEY.md) and
[model integration design](docs/MODELING_INTEGRATION.md) define how SCAR will
reuse Python compiler interfaces, FX/Export and ETO+Profiler. Current experiments
verify bounded tool capabilities; the new adapters are not yet integrated.

The [C1 cleanup/context component](docs/M1_CLEANUP_INTERFACES.md) connects pending
values, saved exception context and current state through canonical CFG routes.
Its 243 component checks and 3,330 frozen full-repository tests pass. These are
static declared-IR checks; automatic source recovery, runtime unwinding and the
complete first modeling stage remain unfinished. The
[evidence archive](artifacts/experiments/b1_call_operands/model_cleanup_interfaces/README.md)
retains independent reviews, original failures and the unchanged-source receipt.

The [resumption body component](docs/M1_RESUMPTION_BODY_ACCEPTANCE.md) passes
499 component checks and 3,542 frozen full tests: saved Uses and fresh ingress
state, drive-local context, temporal control and cut availability. The
[full resumption contract](docs/M1_RESUMPTION_INTERFACES.md) still needs creation,
driver/instance/generation and release interfaces. Body structure alone does not
establish Python source recovery or runtime resumption.

The [driver model review](docs/M1_DRIVER_INTERFACES.md) uses bounded language
witnesses to separate raw requests, ingress permits, persistent sessions and
reference release. Its exact fields remain open. The
[first-outcome query](docs/M1_BODY_OUTCOME_FRONTIER.md) is implemented as a shared
relation over the existing body graph. Its 517 component checks and 3,549 frozen
full tests pass; this introduces no driver/backend or runtime authority.
The [D1 driver connection component](docs/M1_DRIVER_ACCEPTANCE.md) implements the
canonical Create/Start/Resume/outcome path, v11 wire and input/output queries.
All 671 component checks and 3,706 frozen full tests (`382363c`) pass. Lifecycle,
source/runtime correspondence and complete whole-program modeling remain open.
The [D2 lifecycle review and gates](docs/M1_DRIVER_LIFECYCLE.md) separate body
publication, no-body paths, session state and reference drop. The
[D2.0 contract](docs/M1_DRIVER_LIFECYCLE_CONTRACT.md) now fixes fields and the
edge-first must analysis. The [D2.1 body publication component](docs/M1_BODY_PUBLICATION_ACCEPTANCE.md)
passes 741 component checks and 3,776 frozen full tests (`49201e7`).
Further session/drop and E/F/P components are recorded below; these declarations
and language observations add no runtime or transformation authority.
The [D2.2 no-body component](docs/M1_NO_BODY_ACCEPTANCE.md) now passes 836 component
checks / 21 criteria and 3,871 frozen full tests (`006a0e0`). It connects the real
bool branch, exact owner and body-only state mark, preserving the original false
path. Predicate/branch/mark structure is distinct from actual runtime guard execution.

The [D2.3 session/release component](docs/M1_SESSION_RELEASE_ACCEPTANCE.md) passes
974 component checks / 27 criteria. It derives path-correlated terminal history
and current session predicates, checks precise owner/state at release, and keeps
unknown effects and native applicability explicit. Frozen `f67037d` passes 4,009
full tests. Complete first-stage modeling, source/runtime correspondence and LeWM
automatic simplification remain unfinished.

The [D2.4 lifecycle composition gate](docs/M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md)
passes 1,015 component checks / 32 criteria and 4,050 frozen full tests (`37baeaf`).
Actual body and driver cleanup paths retain private pending/context and current
state; detached query points retain the original rule, scope and actual edge.
Applicability stays UNKNOWN. Resource completion, value provenance and the full
modeling stage remain open; no new LeWM speedup is claimed.

The [R0 resource relation review](docs/M1_RESOURCE_EXECUTION_DESIGN_ACCEPTANCE.md)
separates scoped occurrences, resource/handle lifetimes, work outcomes and
completion versus ordered consumer visibility. Six real stdlib CPU/OS witnesses
pass. That design checkpoint did not implement R1/R2 or add a new full-suite run.
The [R1 identity implementation](docs/M1_RESOURCE_IDENTITY_IMPLEMENTATION.md)
now connects exact canonical execution occurrences, resource/handle lifetimes,
requirement owners, current-state support and artifact-scoped evidence links.
Its [accepted gate](docs/M1_RESOURCE_IDENTITY_ACCEPTANCE.md) passes **302 checks /
14 criteria** and **4,192 frozen full tests** (`6fcac0f`). All 472 source and 44
fixture hashes match; every previous test identity survives. R2 work/order/ready, complete
M0–M2 and automatic LeWM simplification remain open. No new speedup is claimed.

The [P1 thin native boundary component](docs/M1_NATIVE_INTERFACES.md) connects
provider slot declarations to canonical entry/exit ports, retaining repeated Uses,
all completion sites and explicit cross-representation obligations. Its 168
component checks and 3,215 frozen full-repository tests pass. Native trees/signatures
remain authoritative external artifacts, with no adapter, replay or equivalence
claim. The complete first modeling stage remains unfinished.

The [P0 provider provenance component](docs/M1_PROVIDER_INTERFACES.md) connects
external graph origins and ordered ports to the canonical core. Its 225 component
checks and 3,139 frozen full-repository tests passed. Declared coverage and scope
do not authorize transformations or establish dynamic correspondence.

The [first-stage completion matrix](docs/FIRST_STAGE_COMPLETION_MATRIX.md)
separates implemented interfaces from remaining modeling work. The latest
[function environment component](docs/M1_ENVIRONMENT_INTERFACES.md) passed 327
bounded checks and 2,835 frozen full-repository tests; this is not automatic
source recovery or optimization authority.

The [C0 control interface component](docs/M1_CONTROL_INTERFACES.md) passed 354
bounded checks and 3,027 frozen full-repository tests. Lexical scopes, pending
completion and exception packets now connect through canonical CFG/SSA operands.
Complete cleanup/context handling and whole-program modeling remain unfinished.

SCAR means **State · Control · Action · Resource**. It is a prototype for
automatic program modeling and optimization planning for Python/PyTorch.
The current task is to recover connected value/state/control dependencies,
identify avoidable work and produce precise, evidenced modification guidance.
Complete automatic program recovery and credible LeWM simplification remain
unfinished. See the [current scope and gates](docs/AUTOMATION_STATUS_20261015.md).

The earlier v1 capture/backend experiments exercise this bounded loop:

```text
program -> JSONL execution trace -> generic opportunity detector
        -> graph reconstruction -> legality/guard/cost decision
        -> reuse backend -> validation report
```

The detector is workload independent. LeWM launch/validation metadata lives in
the separate sibling testcase project `../scar-testcases/lewm`; it is not part
of the SCAR source tree or wheel.

The current development priority is the [program type and dependency core](docs/PROGRAM_TYPES.md).
Its bounded synchronous IR has typed values, state locations, exact uses and
region/control interfaces. `check-program` validates a supplied IR document;
it does not recover Python source or authorize an optimization. See the
[N1 implementation plan](docs/N1_IMPLEMENTATION_PLAN.md) for scope and gates.

Bounded automatic source construction passed the [N2.a gate](docs/N2A_ACCEPTANCE.md). `model-program`
connects a selected function's parameters, branch merges, ordered uses,
normal/exceptional completions and conditional same-file call interfaces without
manual IR. It does **not** recover the complete LeWM program or prove a rewrite.
See [automatic modeling scope and roadmap](docs/AUTOMATIC_MODELING.md).

The [source inventory](docs/PROGRAM_INVENTORY.md) starts from
one file, discovers local import candidates and automatically inventories and
attempts available function bodies. Source scopes and conditional call
witnesses remain separate from verified runtime targets and optimization proof.
The current automation boundary, measured external coverage and next acceptance
steps are recorded in [AUTOMATION_PROGRESS.md](docs/AUTOMATION_PROGRESS.md).
The bounded inventory passed the [N2.b0 gate](docs/N2B0_ACCEPTANCE.md), including
an unchanged external-source run and replay; whole-program modeling is pending.

The runtime-source bridge reads existing trace code/process observations to
automatically extend source discovery, reproduce code objects where possible,
and persist definition/core-region links. It retains unresolved code versions
and unobserved static branches. See the [N2.entry report](docs/N2_ENTRY_ACCEPTANCE.md)
and [next interface and scheduling plan](docs/N2_SIGNATURE_PLAN.md). These links
do not establish a complete execution graph, pure effects or a LeWM speedup.

Inventories use a global body demand queue with root-only lowering and
demand-driven call witnesses. Prepared contexts use bounded private storage.
Default v5 reports add conditional frame lifetime and preserve return-reference
origins alongside definition work and bound-formal ports. Without a trace,
runtime scope is null; historical v1–v4 retain their original replay behavior.
See [current automation scope](docs/AUTOMATION_STATUS_20261016.md),
[function interfaces](docs/N2_FUNCTION_INTERFACES.md) and
[the next connection gates](docs/N2_CALL_COMPOSITION_PLAN.md).

New bounded [call evidence](docs/N2_CALL_EVIDENCE_ACCEPTANCE.md) records actual
caller instruction positions, per-invocation entries/exits and weak reference
epochs without Tensor snapshots or Torch hooks. It automatically links source
and available core calls. Queries explicitly stop at unproved actual/formal
binding; the complete cross-layer dependency gate remains unmet. Whole-program
LeWM recovery, automatic simplification guidance and a speedup remain pending.

Automatic frame construction passed **863 mapped tests** and **1,898 repository
tests**. `model-program` now defaults to a versioned root-only frame body;
`query-frame-refs` follows each completion's conditional reference origins while
retaining unknown state/lifetime effects. The Python `lower_source` API keeps
its legacy default. See [C0 acceptance](docs/N2_FRAME_ACCEPTANCE.md) and
[the implementation and commands](docs/N2_FRAME_IMPLEMENTATION.md).
Whole-program connectivity and LeWM speedup remain unverified.

The [compact source witness bridge](docs/N2_CALL_SEEDS.md) passed **196 gate
checks and 2,033 repository tests**, plus unchanged-source LeWM trace replay.
`seed-calls` and `check-call-seeds` automatically resolve entered code groups
without retaining reference vectors or saving Tensor contents. The real archive
yielded 421 unique definition seeds; these are not approved optimizations.
The [D1 bridge](docs/N2_CALL_DEMAND_ACCEPTANCE.md) now connects them to typed,
entry-first source and body expansion: **303 gate checks / 2,193 repository tests**
and original archive replay passed. It yields 50 local body graphs with gaps;
32 source groups link core regions, while 389 retain concrete scope/lowering
boundaries. Actual/formal binding and whole-program connectivity remain pending;
no LeWM transformation or speedup is claimed. See the
[cross-layer implementation plan](docs/N2_CROSS_CALL_IMPLEMENTATION.md).

[Recorded compilation context](docs/N2_COMPILATION_CONTEXT_ACCEPTANCE.md) now
resolves five source mismatches without weakening complete code descriptors.
Final **287 mapped / 2,278 repository checks** and independent real-archive
regeneration/replay passed. New seed reports use schema v2; old v1 and nested
v6 reports retain their original matching policy. The latest archive yields
425 eligible definition seeds; this does not establish argument, state or
optimization proofs.

The graph pass includes loop membership: with `--lines`, observed bytecode
back-edges become `loop_controls` edges and can produce a
`GraphLoopInvariantCandidate`. Missing line or loop evidence stays UNKNOWN;
SCAR never infers a loop rewrite from repeated record order.

## Quick start

```bash
cd ~/AAA/scar
conda activate lewm
python -m pytest -q

# Discover candidate dependencies and attempt bodies without a function list.
python -m scar.cli inventory-program path/to/project/entry.py \
  --project-root path/to/project --out artifacts/reports/inventory.json.gz
python -m scar.cli check-inventory artifacts/reports/inventory.json.gz

# Augment source candidates from existing runtime evidence, including dynamic loading.
python -m scar.cli inventory-program path/to/project/entry.py \
  --project-root path/to/project --trace path/to/trace_directory \
  --out artifacts/reports/runtime-inventory.json.gz
python -m scar.cli check-inventory artifacts/reports/runtime-inventory.json.gz

# Automatically build a function graph from source, without importing it.
# Unsupported bodies return 3 and save a located diagnostic with graph=null.
python -m scar.cli model-program path/to/program.py --entry Class.method \
  --out artifacts/reports/source-program.json.gz
python -m scar.cli check-source-program artifacts/reports/source-program.json.gz

# Trace any command in a child process. The command is not modified.
python -m scar.cli trace --out artifacts/traces/demo -- \
  python -m scar.workloads.micro pure --loops 8

# Record Python call-site metadata; this mode does not collect the Torch trace.
python -m scar.cli trace --calls-only --project-root path/to/project \
  --out artifacts/traces/calls -- python path/to/project/entry.py
python -m scar.cli link-calls artifacts/traces/calls \
  --project-root path/to/project --inventory artifacts/reports/inventory.json.gz \
  --out artifacts/reports/calls.json.gz
python -m scar.cli check-call-links artifacts/reports/calls.json.gz

# Use those original calls to drive entry-first source/body discovery (v6).
# This builds a bounded inventory, not a complete dependency or optimization proof.
python -m scar.cli inventory-program path/to/project/entry.py \
  --project-root path/to/project --calls artifacts/traces/calls \
  --out artifacts/reports/calls-inventory.json.gz
python -m scar.cli check-inventory artifacts/reports/calls-inventory.json.gz

# Larger reports require independently selected ceilings for both wire data
# and records. Source-budget boundaries stay explicit; budgets do not prove
# actual argument binding, effects or permission to transform execution.
python -m scar.cli check-call-links artifacts/reports/calls-large.json.gz \
  --max-call-report-bytes 800000000 --max-call-trace-bytes 256000000 \
  --max-call-trace-events 250000 --max-call-references 2000000

# Optional expensive control detail: user lines and observed loop back-edges.
python -m scar.cli trace --lines --out artifacts/traces/line-demo -- \
  python path/to/program.py

# Optional low-overhead process/GPU resource samples. This writes
# resources.jsonl and resources.summary.json beside the event trace.
python -m scar.cli trace --resources --resource-interval 0.25 \
  --out artifacts/traces/resource-demo -- python path/to/program.py

# Analyze a trace and write a machine-readable report.
python -m scar.cli analyze artifacts/traces/demo

# Optional resource policy: reject candidates whose retained copy exceeds a
# byte budget (the original execution remains the fallback).
python -m scar.cli analyze artifacts/traces/demo --memory-budget-bytes 1048576

# Only when the caller can prove the trace is a closed consumer scope:
python -m scar.cli analyze artifacts/traces/demo --closed-world

# Batch analyses can keep their summaries separate from the trace directory.
python -m scar.cli analyze artifacts/traces/demo \
  --out artifacts/reports/demo.json \
  --summary-out artifacts/reports/demo.summary.json

# Explain each rejected candidate as a proven blocker or an evidence gap.
python -m scar.cli audit-rejections artifacts/reports/demo.json \
  --out artifacts/reports/demo.rejection-audit.json

# Build a report-only top-down dynamic region placement view. This does not
# apply a transformation.
python -m scar.cli analyze artifacts/traces/demo \
  --topdown-out artifacts/reports/demo.topdown.json

# Resolve local imported literal constants without importing the target.
python -m scar.cli constants path/to/program.py \
  --project-root path/to/project \
  --out artifacts/reports/program.constants.json

# Build the v2 semantic graph without executing source. project-root scans all
# selected Python files; it does not assert they are reachable from the entry.
python -m scar.cli model-v2 path/to/program.py --project-root path/to/project \
  --out artifacts/reports/semantic.json

# Convert archived raw events to a separate v2 execution evidence graph.
# Aggregates remain measurements; missing returns and opaque events stay visible.
python -m scar.cli normalize artifacts/traces/demo \
  --out artifacts/reports/evidence-v2.json

# Inspect code-only correspondence and scoped effect-preservation requirements.
# This reads source + archived trace, does not execute the target or select rewrites.
python -m scar.cli inspect-v2 path/to/program.py --project-root path/to/project \
  --trace artifacts/traces/demo --runtime-sources \
  --out artifacts/reports/inspection-v2.json

# Build bounded recursive region views and preserve known boundary dependencies.
# Omitted/unexpanded regions never mean dead work. Only NO-OP is emitted at G6.
python -m scar.cli regions-v2 path/to/program.py --view semantic --max-depth 1 \
  --out artifacts/reports/source-regions.json.gz
python -m scar.cli regions-v2 artifacts/traces/demo --view execution \
  --root-limit 8 --max-depth 0 --out artifacts/reports/runtime-regions.json.gz

# Build ordered source semantics and bounded builtin constant facts.
# Execution contracts remain explicit; this does not approve a source rewrite.
python -m scar.cli semantics-v2 path/to/program.py \
  --out artifacts/reports/source-semantics.json.gz

# Follow a generic import/re-export/attribute/index value path without execution.
# Value substitution conditions do not authorize deleting initialization effects.
python -m scar.cli import-values-v2 testcases/static_imports/program.py \
  --project-root testcases/static_imports \
  --out artifacts/reports/import-values.json.gz

# Build separate source control/insertion and primitive identity models.
# These are proof inputs; no REUSE/MOTION legality or rewrite is approved here.
python -m scar.cli proof-models-v2 testcases/proof_models/program.py \
  --out artifacts/reports/proof-models.json.gz

# Optionally join a source file or whole Python project to runtime events by
# exact path/line and loaded function span.
python -m scar.cli analyze artifacts/traces/demo \
  --link-source path/to/program

# Build a source file or whole-project graph and emit conservative static
# simplification candidates. A directory recursively models local `.py`
# files and adds inferred edges for resolvable imports.
python -m scar.cli model path/to/program --out artifacts/reports/program_graph.json \
  --report artifacts/reports/program_static_candidates.json

# Run the generic backend micro benchmark (clean repeated A/B measurement).
python -m scar.cli optimize-micro --loops 30 --warmup 1 --repetitions 5

# Exercise the same strict input guard with more compute per call.
python -m scar.cli optimize-micro --loops 20 --work-factor 8 --repetitions 5

# Run an arbitrary command with the opt-in inferred PyTorch backend. This is
# a clean execution path (no Python line/profiler instrumentation); counters
# and measured guard decisions are written to the report.
python -m scar.cli optimize --report artifacts/experiments/optimizer.json -- \
  python path/to/program.py
```

For the flagship workload, the known successful LeWM launcher is
`../le-wm/run_inference.py`; see `../scar-testcases/lewm/README.md`. Real
profiling evidence is stored under `artifacts/traces/lewm_*` when available.

## Evidence vocabulary

Current coverage and unfinished requirements are tracked in
[docs/STATUS.md](docs/STATUS.md). The complete external-workload optimization
and layered validation loop is still in development.

The requirement-by-requirement evidence audit is in
[docs/REQUIREMENTS_AUDIT.md](docs/REQUIREMENTS_AUDIT.md).
The architecture review and v2 identity/provenance design are in
[docs/IR_DESIGN_V2.md](docs/IR_DESIGN_V2.md), with the staged migration plan in
[docs/IR_MIGRATION.md](docs/IR_MIGRATION.md). The isolated schema foundation is
under `scar/ir/v2/`; `model-v2` and `normalize` populate the semantic and evidence
graphs. These v2 commands do not yet select or execute optimization plans.
The code-level architecture audit is in
[docs/CURRENT_CODE_AUDIT.md](docs/CURRENT_CODE_AUDIT.md). Its gated execution
plan is [docs/NEXT_PHASE_PLAN.md](docs/NEXT_PHASE_PLAN.md). These two documents
are the authoritative order for the semantic IR migration; new detectors and
backends stay frozen until the report-only Optimization IR gate passes.
The rejection audit and top-down region work are documented in
[docs/REJECTION_AUDIT.md](docs/REJECTION_AUDIT.md). They explain why a repeated
leaf is not automatically a legal optimization and record the first generic
cross-module constant provenance pass.
The decomposition contract that defines the graph layers, source-line labels,
and LeWM mapping is in
[docs/PROGRAM_DECOMPOSITION.md](docs/PROGRAM_DECOMPOSITION.md).
The audit of the supplied line-by-line LeWM reference bundle is in
[docs/LEWM_MODELING_REFERENCE_AUDIT.md](docs/LEWM_MODELING_REFERENCE_AUDIT.md).
That bundle is static review evidence only: its labels are syntax hints, not
runtime effects or permission to rewrite a program.
The static decomposition of the external LeWM entrypoint is recorded in
`artifacts/reports/lewm_run_inference_summary.md`; it represents all 84
physical source lines and keeps syntax evidence separate from runtime proof.

Every report labels claims as `Observed`, `Inferred`, `Proposed`,
`Implemented`, `Verified`, or `Rejected`. A candidate is never an optimization
just because a call is repeated: unknown effects remain unknown and the
original execution is always a legal no-op fallback.

The generic detector currently separates repeated Python regions and Torch
operators, physical materialization, allocation reuse, host scalar
materialization, and explicit synchronization. Python spans cover parsing,
index construction, preprocessing and dispatch as well as user-defined
functions. Each family carries its own guard; unsupported legality is
reported and rejected rather than silently transformed.

The trace also records selected side-effect-sensitive CPython `c_call`
boundaries such as `print`, `open`, file mutation and synchronization methods.
They retain the caller source line and C function identity, while arguments,
returns and effects remain `UNKNOWN` because CPython's profile hook does not
expose them. This keeps external boundaries visible to the graph without
hard-coding a workload.

New `threading.Thread` workers inherit the profiler. If a workload forks after
installation, the child session is rekeyed to its own PID and writes separate
metadata while sharing append-only event storage; pre-existing threads and
processes still need independent installation.

Candidates also carry a machine-readable proof ledger. Applicability,
legality, and cost claims remain independently `PROVEN`, `DISPROVEN`, or
`UNKNOWN`; explanatory strings are not used as the primary proof mechanism.
On the current external LeWM trace this distinguishes 960 candidates rejected
by observed intervening writes from 1,568 candidates that still lack evidence,
while selecting no transformation. See
`artifacts/reports/lewm_resource_global_proofs.md`.

The current exact-reuse backend requires a reviewed value-purity declaration
and checks a two-stage input guard (shape/prefix first, retained bytes only
when that guard matches), module parameters/buffers/training/custom fields,
CPU/relevant-CUDA RNG state, and output alias constraints.
These guards can cost more than the saved computation: the benchmark reports
NO-OP when clean A/B timing is not profitable. Static syntax, repeated calls,
or a successful trace do not prove whole-program optimization correctness.
The current clean generic GPU result and raw samples are in
`artifacts/reports/micro_reuse_state_complete_clean.md` and
`artifacts/experiments/micro_reuse_state_complete_clean.json`.

Accepted plans can be applied generically by CodeID:

```python
from scar.backends import apply_candidates
from scar.planner import plan_candidates

planned = plan_candidates(candidates)
results = apply_candidates(planned, {code_id: callable_object})
```

The dispatcher keeps the original callable for rejected, unsupported, or
uncontracted candidates.

`persistent_residency` is the corresponding opt-in backend for a repeated
materialization. It requires a reviewed read-only residency contract and
guards both the source and resident Tensor; it falls back when either snapshot
changes.

The source graph also emits discarded-call candidates. The
`dead_expression_elimination` backend only rewrites a call expression when the
caller supplies both a closed-world consumer scope and a reviewed pure/no-raise
contract; assigned calls, IO, exceptions and unknown effects remain unchanged.

The selector is generic: it merges static, dynamic and graph candidate views,
then records `TRANSFORM`, `REJECT`, `UNKNOWN` or `KEEP` with the evidence and
cost reason. A selected record is a backend plan; it is not permission to
mutate an arbitrary workload without validation. Detector-level
`candidate.decision="rejected"` is a legacy discovery field and can mean
either a known legality/cost failure or incomplete evidence. The authoritative
planner disposition is the separate `simplification.decisions[*].action`:
`UNKNOWN` means “detected but not yet proved”, `REJECT` means a proven refusal,
`KEEP` means known non-applicability, and `TRANSFORM` means selected.

The opt-in `optimize` command supplies a generic library contract for exact
reuse of deterministic built-in PyTorch module classes. It checks no-grad
execution, hooks, input and module-state snapshots, RNG, output aliases, and
then validates the first repeated key by executing the original once. A
measured hit that costs at least the original steady-state computation
disables that module and falls back to the original path. User-defined modules
and unknown effects remain unchanged.

Every graph Action is also included in the action inventory. The inventory
maps multi-label Actions to compute, representation, memory, transfer, state,
control, ordering, external-I/O and opaque families. Actions with no detector
or incomplete proof stay `UNKNOWN`, so the report exposes analysis coverage
without silently treating unrecognized work as safe.

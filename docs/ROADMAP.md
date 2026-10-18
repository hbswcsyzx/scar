# SCAR roadmap and scope

> **Resource relation contract (2026-10-18):** [R0](M1_RESOURCE_EXECUTION_DESIGN_ACCEPTANCE.md)
> passes bounded design review and six asserted CPU/OS witnesses. The
> [R1→R2→R3 plan](M1_RESOURCE_EXECUTION_PLAN.md) implements exact occurrences and
> instance/handle bindings, work/outcome/order/ready, then lifecycle composition.
> This does not implement those records or establish GPU readiness; M0–M2 stays open.

> **Modeling gate (2026-10-18):** [D2.4 lifecycle composition](M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md)
> passes 1,015 component checks and 4,050 frozen full tests. Conditional facts now
> retain original scope/rule/operation/edge; native applicability stays UNKNOWN.
> Next are resource instance/work/outcome/ready, selector/literal and occurrence/
> provenance interfaces, then the remaining family/catalog obligations. The
> [first-stage matrix](FIRST_STAGE_COMPLETION_MATRIX.md) remains open; automatic
> source/runtime recovery and simplification follow its completion.

> **Priority revision (2026-10-16):** complete the
> [whole-program entity/interface model](WHOLE_PROGRAM_MODEL.md), then automatic
> graphs, then simplification guidance. [M0—M6](WHOLE_PROGRAM_MODEL_PLAN.md)
> supersede historical ordering below. Resource is a first-class entity in the
> complete model; the four-family ProgramGraph is a bounded projection. No new
> detector/backend is scheduled before model and dependency closure.

> **Tool reuse revision (2026-10-16):** use existing Python compiler frontends,
> FX/Export tensor subgraphs and ETO+Profiler execution facts before expanding
> bespoke tracing/lowering. The [survey](TOOLING_SURVEY.md) and
> [integration contract](MODELING_INTEGRATION.md) distinguish tested capabilities
> from pending adapters. Complete first-stage modeling remains unfinished.

> **Automation status (2026-10-16):** the public flow discovers sources and builds
> bounded graphs without a hand-authored workload model. Complete dependency
> recovery and LeWM simplification remain unmet. See the explicit
> [status, challenges and end-to-end gates](AUTOMATION_STATUS_20261016.md).
> R1 compiler-context recovery passed 287 final mapped checks, 2,278 repository
> tests and original archive regeneration/replay. Subsequent work
> remains actual/formal/return and environment/state connectivity, not detectors.

> **Latest accepted bridge (2026-10-15):** inventory v6 automatically connects raw
> call-source seeds to typed entry-first demands and local regions. D1 passed
> 303 mapped / 2,193 full tests and unchanged LeWM archive replay; 32 of 421
> definition seeds link core, with the other scope/lowering boundaries retained.
> See [D1 acceptance](N2_CALL_DEMAND_ACCEPTANCE.md). R1 resolved the compiler
> context mismatch under [separate acceptance](N2_COMPILATION_CONTEXT_ACCEPTANCE.md).
> Next is the full cross-call query gate under
> [N2_CROSS_CALL_IMPLEMENTATION.md](N2_CROSS_CALL_IMPLEMENTATION.md), environment,
> loop/state connections and simplification guidance. No new detector/backend.

> **Current priority (2026-10-15):** [CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md)
> defines the reviewed semantic node/edge model and N0–N4 prerequisites.
> Complete program dependencies and subgraph simplification come before
> extending the archived reference collector or opening another backend.
> N1 implements the bounded typed dependency core; N2.a adds automatic selected
> function source lowering. Whole-program recovery is incomplete. See
> [AUTOMATIC_MODELING.md](AUTOMATIC_MODELING.md) and [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md).
> N2.b0 adds automatic entry-driven source inventory; measured coverage and
> remaining entry/load/call/state connections are documented in
> [AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md).
> N2.entry now joins archived runtime code observations to automatic source
> scope and definition/core links; bounded external generation and replay pass.
> [N2_ENTRY_ACCEPTANCE.md](N2_ENTRY_ACCEPTANCE.md) records the single observed
> core-region link and all remaining boundaries. Next is global demand scheduling
> and bound-formal/definition/call interface separation under the proposed
> [N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md), then loop and state composition.
> N2.schedule implements the global queue, demand-driven witness admission,
> root-only lowering and bounded temporary contexts; 457 gate / 1,505 repository
> tests pass. All 27 previously budget-deferred runtime source candidates were
> attempted. [N2_SCHEDULING_ACCEPTANCE.md](N2_SCHEDULING_ACCEPTANCE.md) records
> external replay status. Formal/body/definition/call separation remains next.

> **Planning authority (2026-09-22):** the implementation audit is
> [CURRENT_CODE_AUDIT.md](CURRENT_CODE_AUDIT.md), and the ordered development
> gates are [NEXT_PHASE_PLAN.md](NEXT_PHASE_PLAN.md). The phase descriptions
> below preserve the prototype history. When their ordering differs, the
> gated plan is authoritative.

Current model authority is [IR_DESIGN_V2.md](IR_DESIGN_V2.md); accepted progress
is recorded in [STATUS.md](STATUS.md). G7.2b now has model foundations and one
narrow conditional static MOTION proof; positive REUSE and the parent gate
remain pending under [G7_2B_PLAN.md](G7_2B_PLAN.md).

SCAR is a **generic execution optimizer**, not a LeWM optimizer. A workload
adapter can supply a command, input fixture, and validator; it cannot be
imported by core analysis or select an optimization based on a model name.
The same `scar trace`, graph, detector, planner, and backend must work for an
unrelated PyTorch+GPU program.

## What “avoidable” means

The detector is expected to cover any evidence-supported work that can be
removed, moved, combined, or kept resident while preserving the contract:

1. repeated value computation, parsing, indexing, preprocessing, or dispatch;
2. repeated materialization, allocation/free, copies, and host/device moves;
3. unnecessary host synchronization or Python materialization;
4. loop invariant work, prefetch opportunities, residency, buffer reuse,
   capture/replay, and operation fusion;
5. dead work only when all consumers, escapes, callbacks, exceptions, and
   external effects are accounted for.

Each family follows the same pipeline:

```text
graph evidence -> candidate -> applicability -> explicit guard
               -> proof ledger -> measured cost -> backend/no-op
               -> layered validation
```

Unknown effects are never treated as no effects. A legal no-op plan is always
available. A legal candidate can still be rejected when guard, lookup, memory,
or synchronization overhead costs more than the measured saving.

## Ordered implementation phases

### Phase 0: model and evidence (v0.1, current)

* static source graph covers every line, classifies available syntax as
  K/Σ/A/OPAQUE, and records conservative variable/control dependencies, while
  dynamic evidence adds R/Q/M views;
* static graph includes conservative statement CFG edges for branch, loop,
  exception, context-manager, break and continue paths;
* dynamic graph records CodeID, InvocationID, ObjectID, StorageID, regions,
  logical versions, materializations, effects, resources, and measurements;
* dynamic dependency enrichment records observed producer→consumer,
  overwrite, and escape edges by logical version; these are evidence for
  simplification and never proof that unseen aliases or consumers do not
  exist;
* Python hooks and supported `torch.profiler` provide machine-readable JSONL;
* optional `trace --lines` records user source lines and observed bytecode
  back-edges as runtime loop-instance evidence, and the dynamic graph connects
  matched markers to later Actions with `loop_controls`;
* selected side-effect-sensitive CPython `c_call` boundaries are recorded as
  opaque `CTRL` actions with conservative IO/STATE/ORDER labels and UNKNOWN
  argument/return effects;
* newly created Python threads inherit the profile callback with explicit
  thread provenance; pre-existing threads and separate processes remain
  unknown unless independently instrumented;
* static graph analysis emits conservative loop-invariant candidates from
  control and variable dependency edges, with `Inferred` evidence and a
  rejected no-op decision until runtime guards are available;
* detector emits repeated Python-region, repeated-operator, residency,
  allocation-reuse, deferred-host-materialization, synchronization, and
  observed loop-invariant candidates.
* physical resource evidence can feed residency detection only after a
  conservative logical-version mapping; ambiguous copies remain unresolved.
* graph-level candidate reconstruction rechecks repeated actions from
  Action→State dependency edges and keeps its decisions separate from the
  event-level detector.
* graph-level loop candidates recheck observed `loop_controls` membership and
  region-aware State signatures, while retaining hoisting equivalence as an
  explicit UNKNOWN proof obligation.
* the selection layer merges those views, resolves conflicting backend plans,
  and records `TRANSFORM`/`REJECT`/`UNKNOWN`/`KEEP` without hiding uncertainty.
* the complete Action inventory visits every static and dynamic Action node,
  derives multi-label families, and preserves `UNKNOWN` for actions without a
  detector or unresolved proof.
* candidate applicability, legality and cost are explicit proof obligations;
  a negative graph fact requires complete evidence and cannot be inferred from
  a missing edge.

### Phase 0.5: top-down semantic closure (current next stage)

Before accepting another transformation, SCAR must close the gap exposed by
the LeWM rejection audit:

* reconstruct dynamic control regions and summarize child effects upward;
* represent candidate placement separately from leaf detection, so a stable
  input at an outer scope can produce a composite-region hoisting hypothesis;
* normalize logical value provenance across object, storage, view, transform and
  materialization boundaries;
* collect literal provenance across local imports and treat package
  initialization as a separate effect contract;
* distinguish `PROVEN_BLOCKER` from `EVIDENCE_GAP` in every report;
* measure region-level cost and validate a proposed placement before any backend
  is allowed to transform it.

The current implementation is report-only: `audit-rejections`,
`analyze --topdown-out`, and `constants` add evidence and do not change a
workload. No new backend is selected from this phase. The real LeWM evidence
for this phase is documented in `docs/REJECTION_AUDIT.md`.

### Phase 1: one complete safe transformation

Exact reuse requires an explicit reviewed value-purity declaration. It has
input identity/version plus shape/prefix then bitwise snapshot guards, parameter/buffer guards,
copy-on-return with alias rejection, gradient fallback, bounded retained Tensor
memory, clean measured cost, and Level 1 validation. Generic micro workloads
exercise both profitable and unprofitable decisions. A generic executable
Level 1–4 validation runner is now tested with a synthetic policy; automatic
external-workload validation Levels 2–4 remain incomplete; see STATUS.md.

The `scar optimize -- command` runner supplies a generic inferred contract for
deterministic built-in PyTorch modules. It validates the first repeated key,
measures a real original call against cache-hit overhead, and disables a
module when the measured cache hit is not cheaper. This execution path must
still be benchmarked and validated separately for each external workload.

### Phase 2: strengthen graph and guards

Extend the existing storage epochs, NumPy write observation, view overlap and
pure-module state/RNG guards to arbitrary external state. Callable code/object
identity, free-variable names and observable closure values are now recorded,
but callback registries, globals, escapes and ordering remain UNKNOWN. Same-stream
CUDA ordering is now recorded when Kineto supplies a concrete stream; add
cross-stream/event ordering and profiler input shapes. Add a deferred host-materialization backend only after a workload
provides a real, validated opportunity.

### Phase 3: broader backends

Implement buffer reuse, loop-invariant hoisting, fusion and capture/replay as
independent backends selected by the same planner. The first guarded residency
backend is now implemented; its use on an external trace still requires
complete lifetime, ordering and consumer evidence. Each backend must have a
micro counterexample suite and clean A/B benchmarks. Approximation,
distributed execution, GUI, and arbitrary LLM rewrites are outside this stage.

A narrow source dead-expression rewrite is also implemented for explicit
closed-world/pure contracts; general dead-work elimination remains gated on
complete consumer and escape evidence.

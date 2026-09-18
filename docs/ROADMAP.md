# SCAR roadmap and scope

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

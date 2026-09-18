# SCAR program decomposition

SCAR models a program as a graph of orthogonal facts. The decomposition is
fixed before an optimization rule is considered. A physical source line can
produce several AST nodes and several labels; it must never be forced into one
exclusive category.

For human-facing simplification, `ProgramGraph.operation_view()` projects the
full evidence graph into the requested shape: broad function/action/control
nodes, State/Region data nodes, data-flow edges, and recursive `children` from
AST nesting or observed call control. The full graph remains authoritative for
contracts, resources, measurements and uncertainty; the projection is a view,
not a replacement for those proofs.

## 1. The decomposition

| Layer | Graph representation | Meaning | Typical evidence |
| --- | --- | --- | --- |
| Program and module | source/module nodes | source file, loaded module, process and code version | source SHA-256, loaded code fingerprint |
| Scope and control | function/class, call, branch, loop, exception, context and dispatch nodes | where execution can flow and which invocation controls another | AST containment/CFG, Python call/return, loop back-edge |
| Action | one dynamic action per observed invocation; static expression/statement action nodes | work or side effect that may be transformed | `VAL`, `REP`, `MEM`, `XFER`, `STATE`, `CTRL`, `ORDER`, `IO`, `OPAQUE` labels |
| State | Python object, storage region, logical version, module/RNG/environment slot | value identity and mutable state, independent of code identity | ObjectID, StorageID+epoch, Region, LogicalVersion, reads/writes/escapes |
| Representation | materialization nodes and region geometry | one logical version in NVMe, DRAM, pinned host, HBM, or a view/layout/cast | device, storage, offset, shape, strides, dtype, producer, ready event |
| Resource | device, allocation, stream, thread, file and external handle | physical location and contention domain | runtime resource metadata, Kineto activity |
| Contract | effect and correctness scope | what an optimization must preserve | effect completeness, RNG, exceptions, external and ordering effects, Q levels 1–4 |
| Measurement | timing, count, bytes, memory and confidence nodes | observed cost and evidence provenance | timestamps, durations, profiler activities, `Observed`/`Inferred`/`UNKNOWN` |

The core graph therefore contains the relation, rather than merely a list of
operations:

```text
Control ─controls─> Action ─subject_to─> Contract
                       │                    │
                       ├─reads/writes─> State/version ─version_of─> Region
                       ├─uses_resource─> Resource
                       └─measured_by─> Measurement

producer Action ─data_depends─> consumer Action
prior writer ─overwrites─> later writer
Action ─escapes─> externally visible State
Control ─cfg_* / control_depends─> controlled node
```

Runtime loop back-edge markers add `loop_controls` edges to later Actions only
when the frame parent and bytecode target match. The relation carries observed
iteration metadata and never invents an iteration for work before a marker.
The graph-level loop detector groups those edges by process/thread/scope and
compares complete region signatures before emitting a
`GraphLoopInvariantCandidate`; loop membership alone does not prove that work
can be hoisted.
When a module callback is nested under another user frame, the runtime records
the active outer loop as `loop_parent_invocation_id`, so the graph does not
confuse call nesting with loop scope.

`record_order` is serialization order only. It is not a CUDA, thread, or
process happens-before edge. For Kineto events with a concrete device,
context and stream, `stream_order(happens_before=true)` records the observed
ordering within that one CUDA stream; it does not infer cross-stream order.

## 2. What a source line means

`scar model file.py` creates a node for every physical line. Passing a
directory recursively applies the same model to each local Python file,
creates one `module` node per file, and adds `imports` edges only when a local
module can be resolved from static syntax. Lines containing several
expressions keep separate AST nodes and source containment edges; blank and
comment lines remain `OPAQUE` nodes. The static graph adds conservative
variable reads/writes, control-dependence edges, and statement CFG edges.
Import hooks, generated modules and dynamic imports remain unmodeled and keep
their uncertainty; an `imports` edge is always `Inferred`.

The same boundary is accepted by `scar analyze --link-source`. A project can
therefore be modeled and joined to its dynamic trace through explicit
`dynamic_instance` edges. Exact path/line and loaded function-span matches are
reported separately; a line with several AST nodes remains ambiguous.

Callable arguments and returned callbacks carry explicit code/object identity
and closure names. Passing one creates a `captures_callable` graph edge whose
status is `UNKNOWN`: the observer cannot see arbitrary registries, C callback
slots, function globals or future invocations. A callback boundary therefore
blocks simplification until its escape and ordering contract is supplied.

Callable returns use the same graph vocabulary. A returned function, method or
partial becomes a `STATE/CTRL` node; the returning action connects to it with
`escapes(status=UNKNOWN, escape_kind=callable)`. This is an observed escape of
a control handle, not a purity claim about the closure.

Static labels answer **what kind of thing the syntax may represent**, not what
the runtime definitely did. For example:

- `.to("cuda")` receives `XFER` and `REP` hints, but only a physical profiler
  copy proves a host/device transfer;
- `reshape`/`view` receives `REP`, but it may be a zero-copy view;
- `empty`/`clone` receives `MEM` and `VAL`, but allocation lifetime and alias
  behavior still need runtime evidence;
- `synchronize`/`wait` receives `ORDER`, but wait removal requires stream and
  host-consumer proof;
- `open`/`read`/`print` receives `IO`, so a discarded return is not dead work;
- unknown calls keep `OPAQUE`, preventing an optimizer from treating missing
  effects as no effects.

The line-coverage and line-classification claims are separate. Coverage means
that every physical line has a graph node. Classification means that every
line has at least one member of the closed nine-label Action vocabulary;
`OPAQUE` is the explicit unknown category. `ProgramGraph.validate()` rejects
misspelled or ad hoc source labels. Neither claim proves reads, writes,
aliasing, exceptions, consumers, ordering, or cost.

The call-name table is generic syntax classification. It never matches a
workload, model, variable, or function name.

## 3. What a dynamic action means

A dynamic action is identified by an `InvocationID` and points to a stable
`CodeID`. Its State edges carry the observed input/output region and logical
version. Its Contract edge carries all known effects; an empty collection with
UNKNOWN completeness means “no member was observed”, not “there are no
members”. Its Measurement edge records duration and resource facts without
inventing a physical copy from a source-level `.to()` call.

When the runtime exposes a frame location, the Action node also stores
`source_file` and `source_line` attributes. These coordinates make a dynamic
action easy to join to a static node, while the static `source`/`line` fields
remain reserved for physical-line coverage and are never upgraded by one
observed execution.

Logical versions are SCAR epochs. They are not `Tensor._version`: writes through
NumPy aliases and inference tensors can otherwise invalidate a cache without
changing that private counter. A single logical version may have several
materializations, while one ObjectID can expose different logical versions
across in-place writes.

An explicit pure-module contract does not collapse the module into one opaque
node. SCAR records Tensor and scalar/container arguments plus parameters,
buffers, per-submodule training flags, and supported custom Python attributes
as State reads before forward. It samples the same state after forward;
changed versions become writes. Opaque or cyclic state keeps completeness
`UNKNOWN`. The strict backend independently fingerprints this state and
CPU/relevant-CUDA RNG, so a hidden counter or random action cannot populate a
reuse entry even when a purity declaration is incorrect.

## 4. How graph simplification uses the decomposition

Every detector follows the same sequence:

```text
candidate Action/State subgraph
  -> applicability (same versions? same region? same control scope?)
  -> legality (effects, aliases, escapes, RNG, exceptions, ordering)
  -> cost (saved work, guard, lookup, memory, lifetime)
  -> selection (TRANSFORM / REJECT / UNKNOWN / KEEP)
  -> backend and fallback
  -> layered validation and clean measurement
```

The graph selector merges event and graph views and resolves conflicting
accepted plans for one CodeID. `UNKNOWN` is retained when an edge or contract
is incomplete. `KEEP` is used for a known non-applicable candidate, such as a
changed input version. `REJECT` means the candidate is understood but cost or
backend policy refused it. The original execution is always a legal fallback.

The candidate subgraph is accompanied by a proof ledger rather than a single
boolean. Typical exact-reuse obligations are:

```text
applicability.same_input_versions
legality.effects_allow_exact_reuse
legality.no_intervening_input_write
cost.cost_profitable
backend.backend_available
validation.contract_levels_pass
```

Each is independently `PROVEN`, `DISPROVEN`, or `UNKNOWN`. A missing edge is
never a negative proof: for example, an absent write edge proves “no
intervening write” only when every intervening action's write set is complete.

## 5. LeWM mapping used as a testcase

The unmodified LeWM command supplies an evaluation control graph:

```text
configuration/checkpoint/dataset
  -> preprocessing and normalization
  -> World + policy setup
  -> repeated planner control (CEM solver)
       -> model forward actions
       -> candidate/action state
       -> cost and selection state
  -> environment step / video / metrics / output file
```

The trace does not assume these names are optimization keys. They are a
workload-specific interpretation of generic graph facts:

- repeated module/operator actions are `Action` nodes;
- repeated user-Python spans (parsing, indexing, preprocessing and dispatch)
  are `Action` nodes as well; their default effect contract remains UNKNOWN;
- candidate tensors, model parameters, RNG and Python planner fields are
  `State` nodes with version and alias edges;
- HBM/host copies and CUDA kernels are `Resource`/`Measurement` nodes;
- CEM choice, environment updates, metrics and video are visible `Contract`
  and `IO` effects;
- Python dispatch and CUDA waits are `Control`/`ORDER` actions.

The runtime also models selected CPython builtin boundaries (for example
`open`, `print`, file mutation and synchronization calls) as `python_c_call`
Action nodes. Their caller source line and C identity are observed, while
arguments, returns and effect details stay `UNKNOWN`; this preserves an
explicit external boundary in the graph when Python-level tracing cannot see
inside the builtin.

Thread creation is a Control/Resource boundary as well. New Python threads
inherit the generic profile callback and contribute calls, returns, C-call
boundaries and optional line events with their own thread IDs. The graph keeps
process and thread provenance explicit; pre-existing or separate processes
remain UNKNOWN unless instrumented independently.

Forked children are rekeyed lazily on their first event: process IDs,
InvocationIDs and metadata are separated while append-only event storage stays
shared. This prevents a copied session from making parent and child actions
look like one execution context.

In the current one-episode trace, SCAR observed 45,888 events, 14,609
producer-to-consumer `data_depends` edges, 12,635 overwrites, 80 escapes, and
543 physical CUDA copies. It generated 1,457 event candidates and 1,071 graph
candidates. The open-world graph classified 6,799 states as LIVE and 2,027 as
UNKNOWN; no state was called dead. The explicit proof ledger changes the final
classification without changing the trace: 960 graph reuse candidates are
`REJECT` because an observed intervening write disproves reuse of the input
version; 1,568 candidates remain `UNKNOWN` because effects, consumers,
escapes, ordering, mapping, or costs are incomplete. Zero transformations are
selected. Evidence is in
`artifacts/reports/lewm_resource_global_proofs.summary.json`.

## 6. Simplification experience from LeWM

1. A repeated forward action is not automatically reusable: CEM iteration,
   planner state, hooks, RNG, gradients, and hidden module buffers can differ.
2. An observed host/device transition is not enough for residency: logical
   mapping, invalidation, stream ordering, lifetime, and external consumers are
   separate proof obligations.
3. A CPU scalar materialization can be a control dependency for the next
   Python branch. Removing or delaying it needs the branch and exception graph.
4. A returned action, metric, video frame, log, or environment write is an
   escape even if the value is not used by the immediate Python expression.
5. A source loop invariant is only a hypothesis. Dynamic versions and
   iteration-local writes must confirm it before hoisting.
6. Guard and lookup work can exceed saved GPU work. A measured unprofitable
   plan is a `REJECT`, while an unmeasured plan is `UNKNOWN`.

LeWM therefore serves as a stress test for the model's completeness. It does
not define SCAR's vocabulary or backend selection.

## 7. External line-modeling reference

`LeWM_程序建模_v0.1.0.zip` is an external, user-supplied static review bundle.
Its six-view decomposition and counterexample tests are useful design input,
but its 2,803 line rows do not constitute a dynamic execution graph. The
independent audit is recorded in
[`LEWM_MODELING_REFERENCE_AUDIT.md`](LEWM_MODELING_REFERENCE_AUDIT.md) and
`artifacts/reports/lewm_modeling_zip_review.json`.

SCAR consumes such material only as provenance and static hypotheses. A row's
`action_tags` must never overwrite a runtime action's observed effects: a
`clone` or `cat` is not automatically a transfer, a function definition does
not execute its body, and a control header does not perform every action in its
body. The safe refinement path is:

```text
line/AST hint -> dynamic Invocation -> Object/Storage/Region/version
              -> effects/escape/order/resource evidence -> legality -> cost
```

This keeps the reference useful for finding what to inspect while preserving
the generic, workload-independent SCAR contract.

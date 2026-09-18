# Architecture

`scar.ir` contains serializable execution facts. `scar.trace` collects facts
without importing or modifying the workload source. The injector uses Python
profile events plus PyTorch module and profiler hooks. It emits append-only
`events.jsonl` and `entities.jsonl`, so worker processes can share a trace
directory safely; each process writes its own `metadata.<pid>.json` record.
When supported it also writes `torch-profiler.<pid>.json`. The `analyze` command adds
`report.json` and a machine-readable `graph.json`.

The v1 graph remains the compatibility evidence graph. The architecture review
in [IR_DESIGN_V2.md](IR_DESIGN_V2.md) separates three future layers: a
Semantic Graph of operation definitions and value slots, an Execution Evidence
Graph of observed instances/materializations, and an Optimization IR of
replaceable regions and alternatives. The initial schema-only foundation lives
under `scar/ir/v2/`; it is intentionally isolated from the existing detector
and planner until identity/provenance migration is complete.

`analyze --link-source path.py-or-project` adds that file or project's static
graph and links dynamic
events by observed absolute path and source line. When a loaded CodeID
qualname falls inside a static function span, the function node is linked with
`function_span` confidence. Remaining one-to-many path/line matches are marked
`ambiguous`; SCAR never chooses an AST node by name or guesses a missing line.
Without this option analysis stays dynamic-only so tracing a large dependency
tree does not parse every installed package.

`scar.analysis` turns evidence into typed candidates. Detection and use are
separate: a candidate has evidence, applicability, guard, expected benefit,
and a decision. Each migrated candidate also has a machine-readable ledger of
required applicability, legality and cost claims. Every claim is independently
`PROVEN`, `DISPROVEN`, or `UNKNOWN`; provenance such as `Inferred` does not
silently become proof. Repeated Python regions, Torch operators, allocation,
transfer, scalar materialization, and synchronization are separate candidate
families, so a detector can report
their distinct legality questions. The generic backend dispatcher applies an
accepted plan by CodeID-to-callable mapping and retains the original callable
for rejected or unsupported plans. The planner can apply an explicit retained
memory budget to a candidate's shape-derived retained-byte estimate; aggregate
allocation deltas cannot substitute for lifetime analysis. Cost assessments
are recorded separately from legality rejections. Missing saved-work or
guard/lookup measurements remain unknown and reject acceptance.
`scar.backends` contains transformations and fallback paths.

`scar.analysis.rejection_audit` is a read-only projection over a completed
analysis report. It separates a proven blocker such as an observed intervening
write from an evidence gap such as an incomplete effect or cost contract.
`scar.analysis.topdown` reconstructs the dynamic control tree and summarizes
child reads/writes/effect completeness upward. It reports where a composite
region might be placed; it does not select or apply a backend. The constant
provenance pass resolves local imported literal definitions without importing
the target program, and keeps package initialization equivalence as an
explicit UNKNOWN obligation.

`scar.planner.selection` is the graph simplification decision layer. It merges
event-level and graph-level candidates into one auditable set and classifies
each as `TRANSFORM`, `REJECT`, `UNKNOWN`, or `KEEP`. Only a cost-accepted
candidate with an available generic backend can be selected; conflicting
accepted candidates for one CodeID are resolved conservatively and the
superseded records remain in the report. `UNKNOWN` is a first-class result for
missing effects, consumers, escapes, ordering, or cost evidence.
`scar.validate` compares outputs and selected visible effects. Its
`validate_callables` runner executes baseline and optimized scopes under a
caller-provided reset contract, records separate timings, and requires every
requested Level 1–4 snapshot. `scar.workloads` contains only generic synthetic
workloads; external workload adapters live outside the SCAR project.

`graph_candidates` is an independent pass over the unified `ProgramGraph`. It
reconstructs repeated actions from Action→State `reads`/`writes` edges instead
of reusing the event detector's input lists. The pass indexes edges by state so
large traces remain tractable, retains UNKNOWN effects and intervening writes
as rejection reasons, and emits `GraphReuseCandidate` records beside
event-level candidates. The graph itself is therefore an input to
simplification, rather than only a serialization of an earlier decision.

`graph_loop_candidates` is a second graph-level pass over observed
`loop_controls` edges. It groups an Action by dynamic loop scope and target,
requires equal non-empty region-aware State read signatures across distinct
markers, and rechecks the serialized effect contract. Loop exit, exception,
consumer, ordering and hoisting equivalence remain explicit UNKNOWN
obligations; seeing two loop edges never authorizes a move by itself.

`summarize_action_inventory` then accounts for every Action node, including
ones that no detector recognizes. It derives compute, representation, memory,
transfer, state, control, ordering, external-I/O and opaque families from the
multi-label taxonomy, and reports `TRANSFORM`, `REJECT`, `KEEP` or `UNKNOWN`
with the reason and candidate count. This is an audit of coverage, not a
claim that an unrecognized action is safe.

The CLI defaults to an open-world trace. `analyze --closed-world` is an
explicit caller contract that all consumers and escapes for the analyzed scope
were captured; only then may the liveness report contain `DEAD`. The flag is
recorded in the report policy and does not itself apply a deletion backend.

`ProgramGraph.merge_execution` keeps K/Σ/A/R/Q/M as explicit node kinds. A
profiler aggregate is marked as a measurement with a count, never as a fake
dynamic InvocationID; graph keys include the event position so repeated
records cannot overwrite one another.

Python profile events emit paired `python_call` and `python_return` records
with one InvocationID, elapsed duration, outcome, thread/process identity and
the observed parent invocation. Module, transfer and dispatch records carry
the nearest user parent; all nested user actions also retain the nearest
active outer loop scope when one is observed. The graph adds
`controls_dynamic` and `returns` edges; these are observed call nesting,
distinct from serialized `record_order` and from unobserved CUDA
happens-before.

The profile hook also records selected side-effect-sensitive CPython `c_call`
boundaries in user frames. These actions retain the caller source location and
C function identity, use additive `CTRL`/`IO`/`ORDER`/`STATE`/`OPAQUE` labels,
and keep arguments, returns and effects `UNKNOWN` because the hook cannot
inspect them. This is a generic conservatism rule, not a workload-specific
allowlist.

New `threading.Thread` workers inherit the profile callback through
`threading.setprofile`; events keep their thread IDs and append to the shared
JSONL trace. This covers threads created after installation. Processes and
threads that predate installation require their own injector, so absent
events are not treated as proof that no work occurred.

After `fork`, the inherited session lazily switches to the child PID namespace
before recording an event, resets process-local counters and emits a separate
metadata file. Object and invocation identities are consequently scoped to the
actual process that produced them instead of being attributed to the parent.

Dynamic Action nodes retain observed `source_file`/`source_line` attributes
separately from static graph coordinates. A runtime hit therefore supports an
explicit correspondence join without falsely declaring the rest of that
source file covered.

Observed loop markers are connected to later Actions with a matching dynamic
parent and bytecode target through `loop_controls`; no edge is created for an
unobserved first iteration. Dynamic Action attributes retain process and
thread scope so InvocationID reuse after a fork cannot merge loop instances.
Nested actions carry `loop_parent_invocation_id`; graph scope resolution uses
the nearest active outer loop rather than the immediate call parent.

For user frames, Tensor-valued locals at call entry, Tensor-valued globals
referenced by the loaded code object, and Tensor-valued return members are
attached as observed inputs/outputs. Closures, dynamic attributes and opaque
containers keep effect completeness UNKNOWN, so these observations improve
dependency edges without making a function appear pure automatically.

Python function, method and partial callback values are additionally described
by code/object identity and free-variable names. Observable closure values are
attached as State inputs, and passing a callback creates a
`captures_callable(status=UNKNOWN)` edge. Function globals, default arguments,
registries, C callback slots and future invocation order remain outside the
observer and block simplification until a caller supplies a contract.

When a function returns a callable, the graph creates a callable State node
and an `escapes(status=UNKNOWN, escape_kind=callable)` edge. This records the
observed outward handle without assuming that the caller invokes it
immediately or that its closure state is immutable. The returned-closure
subprocess trace is a generic regression artifact, independent of any
workload adapter.

Resource sampling is an optional trace-side measurement stream. A background
sampler records process CPU utilization from `/proc` and GPU utilization/memory
from `nvidia-smi` into `resources.jsonl` plus a summary. It is disabled by
default; sampling is evidence about the run and is never used as a purity or
legality proof.

`trace --lines` additionally enables a user-frame line tracer. It records
`python_line` events and emits `loop_iteration` when a frame's bytecode offset
makes an observed backwards jump. This is a conservative runtime loop
instance signal: it does not infer loop bounds from source order, and it is
disabled by default because line-level instrumentation is expensive.

The loop analysis groups module actions carrying the same observed loop target
and parent invocation. It emits a `LoopInvariantCandidate` only after at least
two distinct iterations are observed. Changing logical input regions and
unknown effects remain rejection reasons; the detector does not perform
hoisting itself.

Kineto GPU copy, kernel, and synchronization activities become individual IR
events. Correlation IDs connect them to host runtime records; logical Tensor
mapping is normally UNKNOWN. The trace finalizer may attach an `Inferred`
logical materialization when direction and byte count identify exactly one
host transfer; ambiguous signatures remain UNKNOWN. Tensor device transitions
are separately recorded and cannot count as physical-copy proof. Host and
Kineto clock domains remain explicit. The graph's `record_order` edge is
serialization order only. When Kineto supplies a concrete device, context
and stream, adjacent events on that same stream receive an observed
`stream_order(happens_before=true)` edge; cross-stream, host/CUDA and missing
context relations remain unknown.

The static source graph covers every physical line and adds AST containment,
source order, conservative variable read/write edges, control-dependence
edges, and a statement-level CFG. CFG branches, loop back-edges, explicit loop
exits, `break`/`continue`, context-manager, exception-handler and `finally`
paths use separate relations. `from_project` composes these per-file graphs,
adds a module node for each file, and links statically resolvable local imports
with `Inferred` `imports` edges; dynamic import hooks are intentionally
unknown. Those syntax facts guide candidate generation but do not override
runtime alias, escape, ordering, or effect evidence.

Dynamic graph enrichment keeps ObjectID and Region nodes separate from logical
version nodes and adds conservative `aliases` edges for overlapping storage.
The alias index is bucketed by StorageID and canonical region geometry so large
traces do not compare every historical version pair.

The same enrichment pass keeps the latest observed producer for each logical
version. It emits `data_depends` edges for producer-to-consumer reads and
`overwrites` edges for subsequent writes, while preserving observed
`escapes`. This gives simplification passes a graph-level dependency basis;
it does not turn an absent producer or an UNKNOWN effect into proof of
deadness. Batch analyses can redirect the summary independently with
`analyze --summary-out` so one run cannot overwrite another run's evidence.

The current backend is exact reuse of a pure-like region. It is intentionally
conservative: unknown effects, writes to input, RNG, external effects,
exceptions, gradients, or mutable module state reject reuse. The opt-in
backend fingerprints supported custom module fields and CPU/relevant-CUDA RNG
state in addition to parameters, buffers and training flags, and checks them
again after execution before storing a cache entry. The trace hook captures
the same module state before and after forward; scalar/container versions are
State reads, and observed changes become writes. The opt-in
`persistent_residency` backend retains a read-only materialization on a target
device and checks source/resident byte snapshots, gradient mode, target device,
and storage aliasing; any changed snapshot falls back to the original
callable. Other observed patterns (physical materialization, host scalar
materialization, and device synchronization) use the same candidate API. A
repeated physical materialization is considered for residency only when its
logical mapping is unique or observed; ambiguous copies remain UNKNOWN. These
candidates remain rejected until consumer, invalidation, ordering and memory
guards are available.

The separate `scar optimize -- command` path attaches an inferred contract
only to exact built-in PyTorch module classes whose forward behavior is
reviewed as deterministic and read-only. It performs the same byte/state/RNG
and alias checks, validates the first repeated key by running the original
call, then measures a real original computation against cache-hit overhead.
An unprofitable module is disabled for the remainder of the process. This
runtime backend is still generic: custom modules, hooks, gradients and
unknown classes follow the original path and are counted as fallbacks.

The source-level `dead_expression_elimination` backend handles one narrow,
reviewable graph rewrite: an `Expr(Call(...))` whose return is discarded. It
requires both a closed-world scope and a reviewed pure/no-raise line contract;
assigned calls, output-consuming calls, and potential IO remain unchanged.

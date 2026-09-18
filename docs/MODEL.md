# SCAR execution model

SCAR records six orthogonal dimensions:

* **K / Control**: source code identities, calls, loops, branches, dispatch and
  ordering.
* **Σ / State**: Python objects, tensor regions, logical data versions and
  mutable state.
* **A / Action**: a multi-label action. Labels are not mutually exclusive:
  `VAL`, `REP`, `MEM`, `XFER`, `STATE`, `CTRL`, `ORDER`, `IO`, and `OPAQUE`.
* **R / Resource**: CPU/GPU device, storage/allocation, streams and memory
  locations.
* **Q / Contract**: exactness, visible state/effects, exceptions, RNG and
  external ordering that must be preserved.
* **M / Measurement**: timestamps, durations, transfers, memory, counts and
  confidence/source of evidence.

## Identity rules

`CodeID` includes normalized source path, qualified function/call name, source
line/column when available, and a version fingerprint. Static AST nodes include
the entire source snapshot's SHA-256. Python and module calls include a SHA-256
of the loaded code object (including constants/nested code), so editing a file
after loading does not relabel an old executable. This fingerprint is scoped
to the Python runtime format, not a cross-Python-version equivalence proof.
A function's current instruction is distinct from its stable definition ID.
A line number alone is not an identity. `InvocationID` is unique for each
dynamic call within its process. `ObjectID` uses Python
identity but is never treated as content identity. `StorageID` tracks the
underlying tensor storage where observable; allocator address reuse is paired
with a storage epoch.

`Region` describes storage, offset, shape, strides and dtype. A
`LogicalVersion` is advanced by SCAR's own observed write/invalidating events;
it is not inferred from `Tensor._version` alone. This accommodates NumPy
writes through `torch.from_numpy` and inference tensors. A version can have
several `Materialization` records (NVMe, DRAM, pinned host, HBM), each with a
producer and ready event.

Physical CUDA memcpy events remain separate from host `.to()` calls. When the
trace finalizer finds exactly one host transfer with the same direction and
byte count, it records an `Inferred` logical materialization link. Repeated
signatures remain `UNKNOWN`; a sequence match is never presented as an
observed correlation ID. Kineto events with a concrete stream are also joined
by observed same-stream order in the program graph; cross-stream and
host/device happens-before remain UNKNOWN.

`Region.overlap()` classifies two views as `EXACT`, `PARTIAL`, `DISJOINT`, or
`UNKNOWN`. It enumerates small strided regions, so zero-stride `expand` and
slice aliases are represented correctly. Large intersecting regions remain
`UNKNOWN`; an optimizer must not treat an unknown alias relationship as
disjoint.

The implementation exposes a `StorageVersionRegistry` for observers and
backends. It joins the allocation token, storage epoch, and logical epoch
into one guard. A backend may accept an application supplied `scar_version`,
but it must never substitute PyTorch's private version counter as a universal
cache key.

Foreign-buffer writes are explicit through `mark_external_write`. When a
NumPy array shares a previously observed tensor allocation, SCAR resolves its
interior pointer to that allocation and advances the same logical epoch. SCAR
does not claim to discover arbitrary foreign writes automatically; callers
must report the mutation, and unknown writes remain a reason to reject reuse.

The exact-reuse backend also includes Region geometry in its key (data pointer,
offset-equivalent pointer, shape, strides, dtype, and device). Two slices of
one allocation therefore cannot share a cached result unless they describe the
same observed region.

The backend is opt-in: an unannotated callable takes the original NO-OP path.
`@pure` declares a reviewed value-function contract: no hidden state/RNG/I/O,
identity-sensitive outputs, unmodeled dependencies, or concurrent writers.
It does not infer purity from `.eval()` or from inference mode. SCAR has not
implemented automatic proof of that declaration.

The strict backend uses a two-stage input guard. Every call records only
shape, stride, storage offset, dtype, device and a small logical prefix; only
when that quick fingerprint matches does it compare the retained entry
snapshot byte-for-byte. A full input snapshot is retained once per cache entry,
not once per iteration. This catches ordinary Torch writes, inference-tensor
writes, and writes through NumPy aliases even without a running observer.
Module parameters, buffers, training flags, supported custom Python fields,
and CPU/relevant-CUDA RNG states are included. Inferred built-in PyTorch
modules use SCAR storage epochs for parameter/buffer invalidation, so large
model state is not copied every call. State and RNG are compared again after a
cache miss, so a hidden counter or random action invalidates a falsely declared
pure contract before an entry can be cached. Module hooks and unsupported
values use NO-OP. Input/output aliases and shared output storage are rejected
because independent copies would break their contracts. Snapshots and output
tensors are bounded by a configurable retained-tensor-byte budget. Prefix
checks and exact comparisons can synchronize CUDA and cost more than the saved
work; their full cost is included in clean A/B measurements.

## Effects and uncertainty

Each action carries `reads`, `writes`, `allocates`, `frees`, `aliases`,
`escapes`, `rng_effect`, `may_raise`, `external_effect`, and `ordering_effect`.
Unknown is represented explicitly. Absence of evidence is not `NONE`; it is
`UNKNOWN`, and an optimizer must reject or guard it.
Each collection also has `collection_knowledge`: an empty `writes` list with
UNKNOWN completeness means no write was recorded, not proof of no writes.
Legacy records without this field default to UNKNOWN. Reuse legality checks
all supporting invocations, including escapes, rather than just the first.

Unknown cost is also explicit (`null`). Unmeasured guard/lookup overhead cannot
be treated as zero. A candidate with missing cost evidence cannot be accepted;
`not profitable` is reserved for an actual cost comparison. Aggregate memory
deltas are measurements, not retained/peak-memory estimates.

## Proof obligations for simplification

Every generic candidate can carry a machine-readable `ProofObligation` ledger.
Each required claim has one category (`applicability`, `legality`, `cost`,
`backend`, or `validation`) and one three-valued status:

* `PROVEN`: the cited evidence establishes the claim within its stated scope;
* `DISPROVEN`: evidence contradicts the claim;
* `UNKNOWN`: evidence is absent, ambiguous, inferred only, or incomplete.

Evidence provenance and proof status are separate. A versioned AST can prove
that a call result is syntactically discarded while call purity remains
`UNKNOWN`; a signature-based CUDA/logical join remains `Inferred` and cannot
be upgraded to a physical identity proof. The cost planner appends a distinct
`cost_profitable` obligation and cannot accept a candidate while a required
applicability, legality, or backend obligation is unknown or disproven.

This ledger replaces decisions based on human-readable reason strings for
migrated candidates. Text remains explanatory. The selector uses structured
states to distinguish a known non-applicable pattern (`KEEP`), an illegal or
measured unprofitable transform (`REJECT`), incomplete evidence (`UNKNOWN`),
and a fully selected backend (`TRANSFORM`).

The action inventory is the complete reporting layer above candidate
detection. It visits every static and dynamic `A_ACTION` node, derives one or
more families from its multi-label set, and attaches a disposition. An action
with no matching detector or with an unresolved candidate remains `UNKNOWN`;
only a selected plan is `TRANSFORM`, a proof/cost/backend rejection is
`REJECT`, and a proven non-applicable candidate is `KEEP`. Inventory counts
make detector coverage visible without turning an unrecognized operation into
an implicit no-op.

The planner, selector, and backend dispatcher each enforce the ledger. A
caller cannot bypass an unknown proof by manually changing `decision` to
`accepted`; structured candidates also require a proven cost obligation before
dispatch.

## Graph views

### Serialized graph contract

`ProgramGraph.write_json()` emits a versioned `scar.program_graph` document
with `schema_version=1`, the `nodes`/`edges` payload, and a structural
`validation` snapshot. `ProgramGraph.read_json()` performs data-only loading,
rejects unknown schema versions, and runs the same integrity gate by default.
The snapshot records source coverage when source files are available; it does
not upgrade static hints or runtime measurements into legality evidence.

### Graph integrity gate

`ProgramGraph.validate()` is the structural gate for every graph consumer.
It checks node identity, non-empty labels, source-line domains, edge endpoints,
relation names, and the closed nine-label Action vocabulary on source-located
nodes, then reports per-source physical-line coverage. `NodeKind` represents
the orthogonal K/Σ/A/R/Q/M view; it is not mixed into the Action label list.
An unknown source operation uses the explicit `OPAQUE` label. An arbitrary or
misspelled tag makes the graph invalid instead of silently satisfying line
classification. Static
builders promise a `coverage_complete` result only when every physical line
(including blank and opaque lines) is represented by a source node; dynamic
graphs may legitimately report unavailable coverage because their source file
is absent.  `assert_valid()` raises on structural errors and is called before
candidate generation or simplification.  A valid graph is therefore a
well-formed evidence container, not proof that any transformation is legal:
runtime effects, aliasing, escapes, ordering and contract evidence still have
to be checked by the relevant detector and validator.

Q validation is represented as four caller-supplied contract scopes: level 1
region output/effects, level 2 fixed solver result, level 3 one policy call,
and level 4 full trajectory/episode. `validate_levels` compares every requested
snapshot and fails when one is missing; it does not assume that matching one
level proves the larger contract.

Control observations may include `python_line` and `loop_iteration`. A line
event identifies the loaded CodeID, source line, invocation and bytecode
offset. A loop event is emitted only after a frame-local backwards bytecode
jump is observed; it is useful for grouping dynamic iterations while remaining
distinct from a static guess that a line is inside a loop.

When a later Action carries the marker's frame as
`parent_invocation_id`, the dynamic graph adds an observed
`loop_controls` edge from that marker to the Action and preserves the
iteration number. Actions before the first observed back-edge are left
unconnected rather than being assigned a guessed loop iteration.

The graph-level loop detector consumes these edges directly. It compares the
full State region signature (logical version, storage, offset, shape, strides,
dtype and device) and emits a `GraphLoopInvariantCandidate` only for equal
non-empty signatures in at least two marker instances. Its hoisting/control
obligation remains UNKNOWN until exits, exceptions, consumers and ordering
are proven; the graph relation is evidence of membership, not a rewrite rule.
For nested callbacks, runtime metadata carries `loop_parent_invocation_id`;
graph scope resolution uses that outer frame rather than the immediate call
parent, preserving loop membership across module dispatch.

CPython profile `c_call` events add a generic boundary for selected
side-effect-sensitive builtins such as `open`, `print`, file operations and
synchronization methods. The caller CodeID/source line and C function identity
are observed, with additive `CTRL`, `IO`, `ORDER`, `STATE` and `OPAQUE` labels.
CPython does not expose arguments or return values through this hook, so those
fields and all effect dimensions remain `UNKNOWN`; the record is a conservative
barrier against treating the surrounding Python region as pure.

The injector installs the same profile callback as the default for newly
created `threading.Thread` workers, so their user calls share the process graph
with thread identity preserved. Existing threads created before installation
and worker processes remain outside this hook unless they install SCAR
separately; missing coverage stays explicit rather than being inferred.

If a process forks after installation, the first child event rekeys the
session to the child PID, resets its local InvocationID/event index and writes
a child metadata document with `forked_from_pid`. The shared append-only trace
therefore preserves process provenance; a forked child still needs its own
runtime hooks for CUDA activities that are not inherited safely.

The static graph also has a statement-level CFG view. Branches use
`cfg_true`/`cfg_false`, normal fall-through uses `cfg_next`, loops use an
explicit `loop_exit` join and `cfg_backedge`, and `break`, `continue`, context,
handler and `finally` paths have separate relations. These are `Inferred`
syntax facts; dynamic state, exceptions and external effects must refine them
before a simplification can remove a path.

The dynamic `ProgramGraph` materializes one Action node per event and connects
it to a Control node (`controls`), an effect Contract node (`subject_to`), and
a Measurement node (`measured_by`). State and Resource nodes are joined by
`reads`, `writes`, and `uses_resource` edges. Static source graphs additionally
retain AST containment, source order, conservative variable `reads`/`writes`,
and `control_depends` edges. Every physical source line remains explicit,
including opaque lines. Static data flow is evidence rather than proof of
aliasing or absence of hidden effects, so dynamic ObjectID, StorageID,
logical-version, escape, and ordering evidence must refine it before a
transformation is allowed.

Every node created by the static source model records `label_provenance`
(`static_syntax` for AST and opaque-line labels, `static_dataflow` for
derived variable slots), `label_status=Inferred`, and
`labels_are_hints=true`. These fields are part of the model contract: a
syntax label such as `XFER` on `.to()` is a review hint and must be replaced
or corroborated by observed runtime evidence before legality or a rewrite is
decided.

Function definitions carry a source span and lexical qualname. Runtime
CodeIDs can therefore link a call to its loaded function span even when the
current line contains several AST expressions. Span matching remains source
evidence rather than proof that every operation in the function was observed;
path/line ambiguity is retained whenever a span cannot be established.

For a directory input, `from_project` merges the same per-file model into one
graph. Each source file has a synthetic module node; local imports are linked
with `imports` edges only when static resolution finds a local module or
package. This is a name-resolution hypothesis with `Inferred` provenance,
not proof of import-time execution. Dynamic import hooks, generated modules,
and namespace-package behavior remain UNKNOWN.

`scar analyze --link-source` accepts the same file-or-project boundary. It
adds `dynamic_instance` edges from versioned static nodes to observed runtime
Actions by exact path/line or loaded function span. Ambiguous lines retain all
matching AST nodes and an `ambiguous` status; no arbitrary node is chosen.
The report records modeled file count, eligible dynamic events, linked and
unlinked counts, event coverage, and correspondence confidence/status counts.
Events whose source is outside the supplied graph are out of scope rather
than being counted as false misses.

For dynamic events, SCAR also maintains a per-trace producer table keyed by
logical version. When a later action reads a version whose producer was
observed, the graph records `data_depends` from producer to consumer. A later
write to the same version records `overwrites`; an observed returned or
external state member records `escapes`. These edges describe observed
execution dependencies and are not a claim that all aliases or consumers were
seen. Missing producers, unknown effects, and incomplete traces remain
explicitly unknown, which prevents a graph simplifier from treating an
unconnected state as dead.

The graph-level candidate pass uses these edges directly. It groups dynamic
Action nodes only when their observed State read set is identical, checks
indexed intervening writes, and requires complete exact-reuse effect knowledge
before proposing a backend. This is a graph hypothesis, not an automatic
transformation; planner cost and runtime guards still decide whether it can be
used.

The selection layer consumes candidates from the event and graph views after
cost planning. It keeps four outcomes distinct: `TRANSFORM` means a selected
generic backend is available, `REJECT` means the opportunity is understood but
cost or backend policy refused it, `UNKNOWN` means proof or measurement is
incomplete, and `KEEP` means the observed applicability does not hold or a
duplicate candidate was superseded. This gives graph simplification an
explicit safe fallback instead of interpreting every repeated node as a delete
or cache instruction.

Negative graph facts require completeness. In particular, the absence of a
`writes` edge between two repeated actions proves no invalidation only when
every intervening action reports a complete write set. If any intervening
write collection is unknown, `no_intervening_input_write` remains `UNKNOWN`.
An observed write to a reused logical version makes that obligation
`DISPROVEN`.

Liveness is a separate three-valued graph fact. A State with an observed read
or escape is `LIVE`; a written State with no observed consumer is `UNKNOWN` by
default because the trace may omit callbacks, future iterations or external
consumers. Only a caller-provided closed-world scope can infer `DEAD`, and that
status remains an inference subject to the contract. The simplifier must never
delete a node merely because its consumer set is empty in an ordinary trace.

User-frame returns expose observed Tensor outputs as `escapes` and state
outputs. A return containing opaque members keeps escape collection knowledge
UNKNOWN, so partial observation cannot be used to eliminate a value.

User-frame call events capture Tensor-valued frame locals and Tensor-valued
globals referenced by the loaded code object as observed inputs. The capture
is explicitly incomplete because closures, dynamic attributes and opaque
containers are not enumerated; its read set therefore remains UNKNOWN for
legality decisions.

Callable and closure boundaries are represented separately. Python function,
method and partial arguments carry a code identity, object identity and free
variable names; captured closure values are State inputs when observable.
Because callable globals, defaults, registries and unknown object state are
outside this observer, callable capture remains incomplete. The graph adds a
`captures_callable` edge with `status=UNKNOWN` when a callable is passed. This
is a control/escape diagnostic, not proof that a callback was registered or
that it is safe to remove, memoize or reorder.

A returned closure or other Python callable is modeled as a callable State
node. The return action has an observed `escapes` edge with `status=UNKNOWN`:
the identity is known, while retention, registration, invocation order and
mutations to captured state are not. This keeps a generic simplifier from
hoisting or memoizing across an unmodeled callback boundary.

Resource samples are separate Measurement records: process CPU percentage and
GPU utilization/memory are sampled from the running process and device. A
missing sampler result is `UNKNOWN`; a high or low utilization value does not
prove that an operation is avoidable.

For an explicitly `scar_pure` module, the module hook captures reads before
forward execution. Its input state includes Tensor arguments, exact built-in
scalars, container structure and keys, parameters, buffers, each submodule's
training flag, and supported custom attributes. It captures the same state
after execution: a changed version becomes a write and disproves exact reuse.
Opaque or cyclic values make read/write completeness `UNKNOWN`; they are not
omitted from a supposedly complete contract.

Profiler aggregate actions retain measurement fields for invocation count,
CPU/GPU duration, CPU memory delta, device memory delta, and device type. These
are measurements of the observed run; they do not by themselves prove that an
allocation or transfer is avoidable.

# Current evidence and remaining work

## Latest autonomous acceptance: G2 and G3

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

G4 now follows automatically: logical provenance and bounded, opt-in exact
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

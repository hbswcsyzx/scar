# `init.md` requirement audit

This document keeps the v0.1 evidence aligned with the original project
requirements. Statuses use the same vocabulary as reports: `Observed`,
`Implemented`, `Verified`, `Inferred`, `Proposed`, and `Rejected`.

| Requirement | Current status | Evidence / limitation |
| --- | --- | --- |
| Preserve the existing LeWM checkout | **Verified** | `/home/zyf/AAA/le-wm` remains clean at commit `f70fed80288462ca4d006cb3607ec6da6eaa851f`; no reset or package upgrade was performed. |
| Keep LeWM external to SCAR core | **Verified** | The SCAR source tree and wheel contain no LeWM adapter, import, or name-based optimization branch. Launch/result metadata was moved to the sibling project `/home/zyf/AAA/scar-testcases/lewm`. LeWM names under `artifacts/` are retained experimental evidence. |
| Model K/Σ/A/R/Q/M | **Implemented / Verified** | Serializable static and dynamic graphs with explicit Control, State, Action, Resource, Contract, and Measurement nodes; unit and real trace artifacts cover the views. |
| Stable CodeID and dynamic InvocationID | **Verified** | Loaded-code/source fingerprints and paired dynamic calls are tested in `tests/unit/test_code_identity.py` and `tests/unit/test_call_stack.py`. |
| ObjectID, StorageID, Region, LogicalVersion, Materialization | **Implemented / Verified** | Region overlap, allocator epochs, foreign-write hooks, logical-version edges and materialization events are covered by the IR and version tests. |
| Multi-label actions and UNKNOWN effects | **Implemented / Verified** | `Effect` retains reads, writes, allocation, alias, escape, RNG, exception, external and ordering knowledge; UNKNOWN is not treated as NONE. Pure-module tracing models scalar/container arguments, parameters, buffers, training and supported custom fields before/after forward. Callable/closure captures add explicit code/object/freevar State records and `captures_callable(status=UNKNOWN)` graph edges. |
| Classify every physical source line | **Implemented / Verified** | Static AST graph emits a node for every line, including opaque lines, and classifies expression/state/representation/control/IO labels. The external LeWM entrypoint has 84/84 represented lines and currently produces 301 nodes/492 edges in `artifacts/reports/lewm_run_inference_graph.json`; generic call-family evidence is in `artifacts/reports/call_families_summary.md`. |
| Represent the program as a dependency graph | **Implemented / Verified** | The versioned `scar.program_graph` schema round-trips through a data-only loader and has a structural/line-coverage gate. Static graph includes a conservative statement CFG; dynamic graph emits observed `data_depends`, `overwrites`, `escapes`, control nesting, aliases and source correspondence edges. |
| Trace arbitrary Python/PyTorch/GPU programs | **Verified** | `scar trace -- <command>` and optional `--lines` were run on independent PyTorch workloads, a worker-thread testcase, and the unmodified LeWM command; selected side-effect-sensitive CPython `c_call` boundaries are retained as opaque actions. |
| Thread/process provenance | **Implemented / Verified** | New Python threads inherit profiling; forked sessions rekey to the child PID with separate metadata, while append-only events preserve process identity. Pre-existing threads and independent processes remain UNKNOWN unless instrumented. |
| Runtime resource baseline | **Implemented / Verified** | Optional generic `scar trace --resources` writes process CPU and `nvidia-smi` GPU utilization/memory samples; the real LeWM run produced 259 samples with wall-clock, CPU, GPU utilization and GPU memory summaries. |
| Physical CUDA evidence | **Verified** | Kineto kernel, memcpy and barrier activities are imported with clock domain and correlation metadata; unique direction/byte signatures can create `Inferred` logical materialization edges, while ambiguous copies remain UNKNOWN. Tensor `.to()` alone is not counted as a copy. |
| CUDA stream ordering | **Implemented / Verified** | Kineto events with concrete device/context/stream receive observed same-stream `stream_order(happens_before=true)` graph edges; cross-stream and host/device ordering remain UNKNOWN. |
| Detect avoidable work families | **Implemented / Verified** | Repetition (including ordinary Python parsing/indexing/preprocessing spans), materialization, allocation, synchronization, host scalar, static/runtime and graph loop-invariant hypotheses are emitted as typed candidates; the complete Action inventory accounts for every static/dynamic Action and keeps unrecognized or unresolved work as `UNKNOWN`; graph liveness emits LIVE/UNKNOWN/DEAD facts without treating absent consumers as dead by default. |
| Separate detection, legality, cost and selection | **Implemented / Verified** | Candidates carry machine-readable `PROVEN`/`DISPROVEN`/`UNKNOWN` obligations for applicability, legality and cost. The planner cannot accept incomplete preconditions; the selector records `TRANSFORM`, `REJECT`, `UNKNOWN`, or `KEEP` and resolves conflicts. |
| Complete generic backend | **Implemented / Verified at generic scope** | Strict exact reuse uses a shape/prefix fast guard followed by retained byte snapshots, plus module state, RNG and output alias guards; hidden-counter, random, foreign-write and output-mutation counterexamples are covered. Persistent residency and a narrow source dead-expression rewrite are also generic and guarded; external LeWM transformation remains unenabled. |
| Real LeWM optimization | **Rejected / Not yet achieved** | The latest resource trace has 1,457 event opportunities plus 1,071 graph candidates. Explicit obligations classify 960 as `REJECT` because observed intervening writes disprove exact reuse and 1,568 as `UNKNOWN`; zero transformations were selected. No LeWM transformation claim is made. |
| Level 2–4 correctness and clean LeWM A/B | **Generic verified / LeWM proposed** | `validate_callables` passes all four levels on a synthetic policy; fixed CEM, policy-state and full-episode optimized comparisons remain to be executed after a legal LeWM plan is selected. |

## Reference model audit

The supplied `LeWM_程序建模_v0.1.0.zip` is treated as a static external
reference, not as SCAR source. Its line ledger is mechanically well formed,
but the audit found over-broad syntax tags and no dynamic identity,
version/alias, resource-correlation, complete-effect, cost, or equivalence
evidence. The precise findings and SHA-256 are in
`docs/LEWM_MODELING_REFERENCE_AUDIT.md` and
`artifacts/reports/lewm_modeling_zip_review.json`. This is why SCAR imports
static hints as provenance and requires runtime refinement before a graph
simplification can be selected.

## Current next gate

The next implementation gate is a generic transformation whose candidate has
complete logical-version, effect, consumer/escape and ordering evidence. The
planner must measure guard and lookup cost before accepting it. A LeWM run that
only produces a trace or a rejected candidate does not satisfy this gate.

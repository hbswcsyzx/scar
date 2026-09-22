# SCAR v0.1.0

SCAR means **State · Control · Action · Resource**. It is an execution-driven
optimizer for real Python/PyTorch programs. Its responsibility is to discover
avoidable work, establish evidence and guards, estimate whether a change is
profitable, select a backend, transform execution, and validate the result.

The v0.1 prototype has a deliberately small but real loop:

```text
program -> JSONL execution trace -> generic opportunity detector
        -> graph reconstruction -> legality/guard/cost decision
        -> reuse backend -> validation report
```

The detector is workload independent. LeWM launch/validation metadata lives in
the separate sibling testcase project `../scar-testcases/lewm`; it is not part
of the SCAR source tree or wheel.

The graph pass includes loop membership: with `--lines`, observed bytecode
back-edges become `loop_controls` edges and can produce a
`GraphLoopInvariantCandidate`. Missing line or loop evidence stays UNKNOWN;
SCAR never infers a loop rewrite from repeated record order.

## Quick start

```bash
cd ~/AAA/scar
conda activate lewm
python -m pytest -q

# Trace any command in a child process. The command is not modified.
python -m scar.cli trace --out artifacts/traces/demo -- \
  python -m scar.workloads.micro pure --loops 8

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

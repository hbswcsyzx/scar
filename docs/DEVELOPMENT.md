# Development notes

Use the existing `lewm` conda environment. SCAR must not reset or install into
`le-wm`; profiling is injected from the SCAR process. Keep clean benchmark
runs separate from instrumented runs because profiler hooks change timings.
Use `scar trace --resources` when a run needs process CPU and GPU utilization /
memory evidence; those samples are measurements, not transformation guards.

From a source checkout, use `python -m scar.cli` for the CLI. Scripts that import
the local package use `PYTHONPATH=. python scripts/<name>.py`, after activating
`lewm`; no editable installation is required. On Linux analysis measurements
use `/proc/self/status` VmHWM for the current executable and disclose getrusage
separately, because the latter can retain a launcher's pre-exec high-water mark.

The minimum quality gate is `python -m pytest -q` followed by a trace of a
real workload. Reports must separate `Observed`, `Inferred`, `Proposed`,
`Implemented`, `Verified`, and `Rejected` claims. A performance result with no
wall-clock improvement is recorded as `not profitable` and does not become an
automatic transformation.

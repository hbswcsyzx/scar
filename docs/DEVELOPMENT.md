# Development notes

Use the existing `lewm` conda environment. SCAR must not reset or install into
`le-wm`; profiling is injected from the SCAR process. Keep clean benchmark
runs separate from instrumented runs because profiler hooks change timings.
Use `scar trace --resources` when a run needs process CPU and GPU utilization /
memory evidence; those samples are measurements, not transformation guards.

The minimum quality gate is `python -m pytest -q` followed by a trace of a
real workload. Reports must separate `Observed`, `Inferred`, `Proposed`,
`Implemented`, `Verified`, and `Rejected` claims. A performance result with no
wall-clock improvement is recorded as `not profitable` and does not become an
automatic transformation.

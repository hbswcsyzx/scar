# Source attachment gate: runner preflight failure

This file preserves attempt01. The separately authorized repaired
[attempt02](attempt02/README.md) has since passed; original failure data below
remains intact. Full modeling remains OPEN.

Observed: authorized attempt exited 1 before producer receipt construction or any
coordinate/binder/attachment construction. Runtime 1.19 s, user 1.12 s, system
0.06 s, peak RSS 45,064 KiB; no semantic gate output was created.

Cause: the experiment runner incorrectly required an optional
`first_stage_lewm_dispatch_20261023/archive-index.json` in its input receipt list.
This particular capture retains original plain raw files and has no such index.
The public coordinate binder supports that original layout. The actual collector
manifest is `../first_stage_lewm_dispatch_20261023/trace/execution-evidence.272038.json`.
This is a runner path assumption, not an unsupported source region or missing
original source/runtime evidence.

Retained evidence: original run.py/run.sh, revision.txt, stdout/stderr and
`run.time.txt`. No file was overwritten, no retry was started, no target/GPU or
source compile/prepare occurred. The frozen SCAR modules imported successfully,
but their new constructors and APIs have not yet received a real-artifact gate.

Run script SHA256: `442c0954265d8e2ca2f82f5e78685998be22d62f6f9332da3e5c6a14f6a798b6`.
Stderr SHA256: `23707159e337a6f081e246ebd8f12d8396f88d8d7de941e2b7637a77c175b75c`.
Revision: `c2578996ccd5d796e8f913d17ddaa3ed83a8f304`.

Root authorization is required before starting a distinct repaired attempt.
First-stage complete program modeling remains OPEN.

# R2.3-V evidence archive

Verified scope: declared source-derived contribution support and whole-read
validity interfaces. **Full M0–M2 and automatic LeWM simplification remain open.**
See [acceptance](../../../../docs/M1_VALIDITY_ACCEPTANCE.md) and
[API](../../../../docs/M1_VALIDITY_API.md).

- Implementation: `550496f328dbe9941e0a06a6de8c76181fa28039`.
- Component: **649 cases / 11 criteria / 18.653s**, all 544 source hashes unchanged.
- One clean full regression: **4,826 passed**, zero failures/errors/skips,
  four warnings; **494.393576s** external wall, **1,026,012 KiB** peak RSS.
- Previous 4,713 case identities and 59 fixtures retained; current 65 fixtures
  and 544 source files unchanged during the full run.
- Native/source/visibility/transform authority is not granted. Endpoint
  read/flush/persist parsing and whole-work source boundary mapping remain open.
- Real owned pipe request 131072 returned/received 65536; declared model keeps
  exactly the partial coverage. Physical pipe/core/region capture is not claimed.

## Evidence

`design/` retains independent design audits. `core/`, `wire/`, `domains/`,
`query/`, `actual_placement/`, `os_witness/` and `review/` retain commands,
hashes, actual failures and limited closures. `golden/` generated v5 bytes with
the immutable pre-V codec, not the current encoder. `component/final/` binds
each criterion to cases. `full/` retains exact environment, clean snapshots,
JUnit, all cases, `/usr/bin/time`, child cleanup and the unchanged frozen driver.

`preservation.json`, `protected.*.json`, `closure.json` and `manifest.json`
bind completeness and protected checkout receipts. No reset, environment update,
shared-cache cleanup, new collector/backend or LeWM profiling/A-B experiment was performed here.

## Read-only verification

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_validity/check_archive.py
```

The checker starts **zero tests/providers/workloads**. Acceptance wall times
are test costs, not an A/B speedup. Only exclusively owned temporary extraction
and full-regression directories were removed after their child processes exited.

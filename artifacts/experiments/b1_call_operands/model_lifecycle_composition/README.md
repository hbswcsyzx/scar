# D2.4 lifecycle composition evidence

Status: **PASS within the declared component scope**. Implementation:
`37baeaf5e8be24a88e6524cba1b99c84cfb41808`.
Source fingerprint: `e0683fad9eae6a34b0dd781a9823921aac3d969372246498ff1a236e9605ed5d`.

## Evidence

- `component/report.json`: 1,015 distinct cases / 32 mapped criteria, 18.022s.
  Collected on dirty D2.3 HEAD; its 451 file hashes match the clean implementation.
- `full/`: one clean, frozen complete run, 4,050 PASS / 0 FAIL / ERROR / SKIP,
  457.655s external wall / 455.61s pytest, max RSS 1,029,216 KiB. Three warnings.
  Exact command/environment, JUnit, raw logs, process receipt and before/after
  source/fixture hashes retained. The exclusively owned basetemp was removed.
- `root/continuity.json`: all previous 4,009 case identities and 38 fixtures retained;
  exactly 41 new case identities and four fixture files, 42 fixtures in total.
- `historical/`: schema14 golden generated solely from immutable D2.3 `fdf9d0d`
  in an isolated git archive, not the mutable encoder. Generator command, import
  isolation proof and raw result retained; historical v1–v13 checks remain mapped.
- `review/`: separate body, driver cleanup and public API cross-review with exact
  source hashes; no new experiments during read-only review. The corrected
  remaining-stage audit keeps its inaccurate initial draft separately.
- `body/`, `public/`, `cleanup/`: focused commands and raw outputs. Root body tests
  initially failed from wrong API field assumptions (4P/3F, then 5P/2F), corrected
  before the unified component. No product premise was relaxed. Cleanup first-run
  hashes were not captured and are not reconstructed. Repeated subsets are not
  added to the distinct coverage count.
- `protected-checkouts.json`: original LeWM and main SCAR checkouts remain clean
  at their unchanged expected revisions.

## Boundaries

These are canonical hand-built graph compositions and conditional scope views.
They do not establish arbitrary source recovery, native applicability, runtime
identity, physical free/ready or transformation permission. First-stage M0–M2
remains open. There is no new LeWM profile, transform or speedup measurement.

The accepted plan and limitations are in
[M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md](../../../../docs/M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md).
Test timings measure acceptance cost, not workload performance.

## Verify this archive without running tests

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_lifecycle_composition/check_evidence.py
```

`manifest.json` covers all other files, including the nested full-run manifest.
The checker reads saved evidence and compares hashes; it starts no test/workload.

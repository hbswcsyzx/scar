# R3.1 call activation and work materialization connection evidence

Baseline: `348d18277b963bc183fb420bf173f05594d667d8`. Scope and ordered
acceptance: [plan](../../../../docs/M1_RESOURCE_COMPOSITION_PLAN.md) and
[API](../../../../docs/M1_CALL_ACTIVATION_API.md).

This archive distinguishes source review, declared graph validation, historical
wire compatibility, and actual runtime correspondence. It does not claim an
automatically recovered program, native/endpoint protocol closure, a backend
transformation or a LeWM speedup. Whole R3 and complete M0–M2 remain open.

Final acceptance: **591 component cases / 8 criteria / 16.611s**, followed by
one clean frozen **4,951 passed / 0 failed / 0 error / 0 skipped** full run.
External full time **490.69270640797913s**, pytest **488.50s**, peak RSS
**1,025,300 KiB**. Implementation `881cbfbed5d13c56ea68d3adbd45d6808e092c52`;
all 555 registered source hashes stayed unchanged, combined SHA-256
`2c9bdf125adfc9c34ae9e3a9a6042317397ff1c64f4d107dc229dfd4808b6c3d`.
All original 4,826 case identities and 65 fixtures survive; 125 new cases and
3 new fixtures are added. Protected checkout HEADs and clean states match.

## Evidence inventory

- `design/`: three independent source reviews of original core connections,
  logical values/physical endpoints, and lifecycle/resources; recorded source
  revisions and hashes are review snapshots, not test outcomes.
- `root_mat_before/attempt001/`: original complete-set contradiction probes;
  **10 failed / 7 passed**. Missing declared-work-set checks were reproduced
  before the fix; no existing fixture or validator was patched to hide them.
- `root_mat_after/attempt001/`: corrected work-set tests and affected content,
  production, work and validity interfaces; **148 passed**, with explicit
  capture/native uncertainty retained. This was development evidence, not a
  globally frozen source run.
- `codec_golden/attempt001/`: immutable pre-change codec and original rich
  validity fixture generated the independent v6 byte payload; old import paths,
  blob hashes and exclusively owned temporary-directory cleanup are recorded.
  This is a codec declaration fixture, not a valid physical execution.
- `codec_wire/`: **243 passed** in the first focused wire run, including
  independent v1–v6 byte round trips, v7 capability isolation and strict tags.
- Other focused attempt directories retain their commands and outputs. The
  shared focus runner also records JUnit/source snapshots and owned temporary
  cleanup; `core/` uses direct activated pytest commands with exit receipts,
  and its later attempts record source hashes. These development runs permit
  different agents to edit disjoint files; none replaces the frozen gate.
- `review/`: independent source review receipts with precise reviewed file
  hashes and scoped decisions. Earlier unresolved observations stay present.
- `component/final/`: final combined criteria report; source fingerprint must
  match the implementation used for the single full run.
- `full/`: one clean committed-source full regression, exact environment,
  individual test identities, before/after source/fixture hashes, time/RSS,
  original log and removal of only its own basetemp after child termination.
- `preservation.json`, `closure.json`, `manifest.json`: computed after final
  acceptance; retain all prior 4,826 case identities and all 65 previous
  fixtures. New fixtures do not replace historical ones.

## Read-only verification

After the final closure/manifest exist:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/check_archive.py
```

The checker starts zero tests, profilers or workloads. It checks archived bytes,
full/component source equality, the clean implementation revision, case/source/
fixture preservation, protected checkouts, independent golden, document hashes,
scope flags and the exclusively owned full-run temporary-directory cleanup.
Test wall time is acceptance cost, not workload A/B performance.

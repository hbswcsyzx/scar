# R3.2 Q and original execution evidence composition

Baseline `f0dbbd478095b07a684fe4d35ba3b53be20ed17c`.
[Plan](../../../../docs/M1_PIPELINE_COMPOSITION_PLAN.md),
[API](../../../../docs/M1_PIPELINE_COMPOSITION_API.md),
[acceptance](../../../../docs/M1_PIPELINE_COMPOSITION_ACCEPTANCE.md).

Final component: **677 cases / 13 criteria / 20.8s**, followed by exactly one
clean frozen **5,011 passed / 0 failed/error/skipped / 4 warnings** full run.
Implementation `31bf2e4ef8d3cd6df5c0387d5c27f571b5643d41`. External full time
**486.67018712777644s**, pytest **484.42s**, maximum RSS **1,028,760 KiB**.
All 567 source hashes remain unchanged, combined SHA-256
`f24eb1400a29300bcb512d95721df8c7127932faa56b67194df931c0b88adbd4`.
All original 4,951 test identities and 68 fixtures survive; 60 new cases and
one new fixture. Previous 555 source files survive: 550 unchanged, five
extended, 12 new. Protected checkouts remain clean and unchanged.

## Evidence and boundaries

- `design/`: independent original Q denominator, dependency route and
  evidence/lifetime reviews. These are source reviews, not runtime captures.
- `scopes/`: attempts001–008 and a history receipt. Initial import/fixture
  expectation failures stay present; uncaptured first-attempt hashes are not
  invented. Final focused: 10 passed, including exact multi-requirement cursor.
- `routes_graph/`: original invalid CALL test and corrected 10-case result.
- `shared_context/`, `pv_compatibility/`, `shared-context-report.md`: new
  16-case refresh/shared-budget checks and 45-case old P/V compatibility.
- `pipeline_integration/`: eight public integration tests; focus runner did
  not include integration files in its source snapshot, so its report records
  that limitation and a separate current owned-source hash. Frozen component
  and full snapshots do include all integration source.
- `public_boundary/`, `public-boundary-report.md`: original 12/1, 13/1 and 15/1
  development failures and final 16 passed. Later Q-budget snapshot/public P
  copy refinements are covered by the frozen component/full, not retroactively
  attributed to attempt004.
- `review/`: three independent finite reviews with exact source hashes.
  Original OPEN observations and later closures remain. The source-only edge
  denominator and requirement-group cursor gaps are fixed. Trusted internal
  helpers are not advertised as resistant to arbitrary executable controllers.
- `component/final/`, `full/`: complete criteria, exact environment/commands,
  original JUnit/logs, individual test identities, source/fixture before/after
  hashes, wall/RSS and exclusively owned temporary-directory cleanup.
- `preservation.json`, `closure.json`, `manifest.json`: computed final case,
  source, fixture, document and archive-byte inventories.

The query retains the whole supplied model and derives original associations
under typed requested Q scopes. It does not prove that all program contracts,
source/native events or external effects have been recovered. Required facet
targets/cardinality and endpoint read/flush/persistence remain uninterpreted.
R3.3, complete M0–M2, automatic LeWM recovery and simplification remain open.
There is no new backend, detector, lowerer, LeWM profiling or speedup result.
Test durations are acceptance costs, not workload performance measurements.

## Read-only verification

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_pipeline_composition/check_archive.py
```

The checker starts zero tests, profilers or workloads. It checks all archived
bytes, complete component/full source equality, case/source/fixture preservation,
protected checkout receipts, final document hashes, scope flags and owned temp
cleanup. The implementation revision must remain an ancestor of current HEAD.

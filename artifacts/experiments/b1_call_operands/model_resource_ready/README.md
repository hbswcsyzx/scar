# R2.3 relation review and shared geometry prerequisite evidence

This accepts **G only**, under the complete
[R2.3 contract](../../../../docs/M1_RESOURCE_READY_CONTRACT.md).
[Plan](../../../../docs/M1_RESOURCE_COVERAGE_PLAN.md),
[acceptance](../../../../docs/M1_RESOURCE_COVERAGE_ACCEPTANCE.md).

Frozen implementation: `aa2b9178e7a23ccfd86695b68524bf3817fe1673`.
Registered source SHA:
`b2e1bcdb11b4d1df31832f4b7c2a77aa6d3d3b0f2ef45afb77df6db717460e48`.

| Path | Actual scope |
| --- | --- |
| `design/production-review.md` | Independent source review: lineage/current production/possible invalidator, scoped source universe and deletion non-vacuity. No test. |
| `design/consumer-review.md`, `contract-consumer-closure.md` | Exact input/read interval/Q root review. Keeps original Host/Q-without-ticket and visited-input wording findings and their corrections. No test. |
| `design/contract-production-closure.md` | Earlier bounded relation review tied to its original document hashes; not silently retargeted to newer documents. |
| `design/next-denotation-proposal.md`, `next-consumer-proposal.md` | **Proposed next D gate**, prepared read-only during the frozen full run; no product/test/doc changes or extra run. Not counted as implemented or current G acceptance. |
| `witnesses/attempt001/` | Exactly one real asserted CPU/OS run: 3/3 PASS; shared NumPy/Torch delayed consumer, partial file write then error, real strided holes/empty zero-stride. Hand-written witnesses, not SCAR automatic recovery. |
| `geometry/attempt001/` | First focused geometry run: 26 PASS. |
| `geometry/attempt002/` | Same cases after accounting for rank/point enumeration cost in shared budget: 26 PASS. |
| `geometry/attempt003/` | Exact-string catalog keys and present-None wrong-family handling: 29 PASS / 0.43s. Original attempts retained. |
| `queries/attempt001/` | Original MatRef public query, endpoint gaps, unknown offers, fresh mutable snapshots, detached returns and no ready authority: 11 PASS / 0.60s. |
| `review/query-closure.md` | Original bounded query/source review; its exact source hashes remain unchanged in that report. |
| `review/final-closure.md` | Final independent review binds final source/doc hashes and revised catalog/scope handling. No tests run by this review. |
| `component/final/` | 432 unique cases / 6 criteria / 9.768s PASS; all 493 registered hashes unchanged. |
| `full/` | Exactly one clean frozen run: 4,427 PASS, zero failed/error/skipped, three warnings; 473.15876185987145s external / 470.96s pytest; 1,026,340 KiB max RSS. |
| `preservation.json` | Every old 4,387 case identity and all 50 fixtures preserved. 488/489 previous registered files unchanged; only query.py extended. Four new files and 40 new cases. |
| `protected.before.json`, `protected.after.json` | Protected SCAR main and LeWM remain at unchanged clean HEAD. |

Each focused attempt retains its own source hashes; it is not made to claim the
final component fingerprint. No failed test run is rewritten as passed. Review
findings and fixes remain explicit even where discovered by static reading.

Witness source SHA:
`542a80628e5c1046a06e23970bbd387f5f7f00a0e95a8a873510330e887f56da`.
Its environment is Python3.14.7, Torch2.13.0+cu132, NumPy2.5.2. No GPU workload,
LeWM run, fsync/durability experiment, package upgrade or environment change.

## Read-only archive check

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_ready/check_archive.py
```

The checker reads manifests, frozen source/fixture/case receipts, original
witness results and review hashes. It starts no tests/provider/workload.
Root manifest covers all archive files except itself, including nested full
manifest and proposed next-gate notes. Full driver remains byte-exact SHA
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`.
Its exclusively owned basetemp was removed after child termination; shared
caches and other processes were untouched. Source wire/schema/goldens unchanged.

**COVERED means declared byte coverage only.** It does not prove the right
content/version was produced, remains stable/alive, or is visible/ready/free.
Source/native/runtime/transform authority stays false. Low-level sufficient
identity/empty shortcuts may leave irrelevant offers unvisited; used support
does not certify them. D/P/V, R3, complete M0–M2 and LeWM automatic simplification
remain open. Timings are acceptance cost, with no new A/B speedup claim.

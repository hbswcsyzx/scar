# R1 resource identity evidence

Accepted scope: declared canonical execution/resource associations, not automatic
source recovery, physical identity, content equality, ready or transformation.
See [implementation](../../../../docs/M1_RESOURCE_IDENTITY_IMPLEMENTATION.md)
and [acceptance](../../../../docs/M1_RESOURCE_IDENTITY_ACCEPTANCE.md).

Frozen implementation: `6fcac0f778d56d7fe4fdb90e546b23e545f86f96`.
Registered source SHA256:
`131fa88c62901a016b88778ea975b3a63a6e59497d49740968bd3d49df190e3b`.

## Evidence locations

| Path | Exact scope and result |
| --- | --- |
| `coordinates/attempt001/` | 17 PASS; initial non-conda preflight failure retained separately, successful run activates lewm. |
| `resources/` | Resource record constructors: 26 PASS, no graph/runtime proof. |
| `codec/attempt001/` | Independent strict execution wire: 40 PASS; no URI or provider execution. |
| `composition/attempt001/` | Initial canonical core/constructor smoke only, explicitly not execution-validator acceptance. |
| `composition/attempt002/` | First combined graph pytest: 20 PASS / 2 FAIL; invalid lifetime/known handle Use were accepted. |
| `composition/attempt003/` | Same owned 22 cases PASS after corrections. |
| `composition/report.md` | Independent bounded resource review, final hashes and static closure; no extra test run. |
| `flow/attempt001/` | Initial 17 occurrence-flow cases PASS. |
| `flow/attempt002/` | 31 flow/evidence-link cases PASS after initial review corrections. |
| `flow/attempt003/` | 33 PASS / 4 FAIL: two native namespace false rejections, unused binding cross-run leak, malformed external graph exception. Raw failures are retained, not relabeled PASS. |
| `review/` | Independent F1–F6 minimal reproductions, source hashes, reports and final static closure. No broad/full suite run by reviewer. |
| `component/report.json` | Final 302 unique cases / 14 criteria / 4.575s PASS, all 472 registered source hashes unchanged. Includes all 142 new execution cases and 160 prior checks. |
| `full/` | One clean frozen complete run: 4,192 PASS / 0 failed/error/skipped, three warnings; 459.327089545317s external, 457.37s pytest, peak RSS 1,027,068 KiB. |
| `preservation.json` | Every previous 451 source file and 42 fixture is byte-exact; only new execution files/fixtures are added. |
| `protected.json` | Read-only protected-checkout identity and clean-status receipt. |

The complete run retains all previous 4,050 test identities, adds 142 execution
cases and two fixtures (44 total). The reused full driver has SHA
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`.
HEAD, registered source and fixture hashes match before/after; source/docs were
frozen during the run. The exclusively owned basetemp was removed after child
termination. Timing is acceptance cost, not a benchmark or LeWM speedup.

## Read-only verification

From the SCAR worktree:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_identity/check_archive.py
```

The checker reads manifests, receipts and source bytes. It starts no tests,
providers, workloads or GPU profiling. Root `manifest.json` covers every archive
file except itself, including the nested full-run manifest. Reports distinguish
first failures, static review closure and actual passing runs.

R2 work/outcome/order/ready, R3 load-consume-save, full denotation/provenance,
literal/selector and complete M0–M2 remain open. No new detector/backend or
LeWM-specific rule was added; native/runtime applicability remains unverified.

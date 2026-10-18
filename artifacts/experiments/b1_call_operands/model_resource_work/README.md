# R2.1 work / outcome / retention evidence

This archive accepts the work foundation subgate, not complete R2 readiness.
[Interfaces](../../../../docs/M1_RESOURCE_WORK_INTERFACES.md),
[complete R2 plan](../../../../docs/M1_RESOURCE_WORK_PLAN.md),
[acceptance](../../../../docs/M1_RESOURCE_WORK_ACCEPTANCE.md).

Frozen implementation: `bb1b402b498e9ce80a701658a59c1471e8ec32ce`.
Registered source SHA:
`f26bb51ad783f85c43de3a8d75999d9943f915973c629411c0b27b264d57487c`.

## Receipts and exact scopes

| Path | Evidence |
| --- | --- |
| `design/` | Independent full-R2 readiness and fixture designs, copied unchanged where noted. Designs retain event generation, consumer-start order, denotation, AND/OR and partial production obligations; they are not implemented runtime support. |
| `records/attempt001/` | Posthoc account of unavailable system-python preflight; exact original timestamp/full omitted command unavailable and explicitly not reconstructed as raw evidence. |
| `records/attempt002/` | First owned pytest: 10 PASS / 7 FAIL, missing test-helper import. |
| `records/attempt003/` | Same record checks after import correction: 17 PASS. |
| `codec/historical/` | Immutable `6fcac0f` git archive, isolated Python cwd/PYTHONPATH, actual old codec and source hashes. No mutable current-code expected-value generation. |
| `codec/attempt001/` | 35 PASS, strict v1/v2 capability and variant tests. |
| `composition/attempt001/` | First complete canonical ordinary/INVOKE work combinations: 38 PASS. |
| `queries/attempt001/` | Initial original-effect/host/pending/bounded query cases: 11 PASS. |
| `queries/attempt002/` | Original 11 PASS / 3 FAIL: direct held-handle type, referent resource and empty-prefix realm leaks. Raw failing cases retained. |
| `review/` | Two independent bounded source reviews, small original probes and final static closure. Attempt003 preserves the later invalid-static-fixture construction failure; that exit is not reported as a product crash. |
| `component/attempt001/` | First component 406 PASS before last specific unknown-order gap regression. |
| `component/final/` | Final 407 unique cases / 9 criteria / 6.282s PASS. 480 source hashes unchanged. |
| `full/` | Exactly one clean frozen full run: 4,297 PASS, 0 failed/error/skipped, 3 warnings; 461.7210992919281s external, 459.81s pytest, peak RSS 1,029,332 KiB. |
| `preservation.json` | 466/472 prior registered source files byte-exact; the six specific model/codec/query integration changes are listed. Eight new registered files. All prior 44 fixtures unchanged; total 47. |
| `protected.json` | Read-only protected LeWM and SCAR main checkout receipt, still clean. |

All previous 4,192 test identities survive; 105 work cases are added. The single
full run preserves clean HEAD, every source hash and fixture hash before/after.
The exclusively owned basetemp is removed after child termination. Timings are
acceptance cost, not LeWM performance or a measured optimization speedup.

Historical v1 is exactly 88,521 bytes, SHA
`66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391`.
Its immutable original bytes, proof and new capability checks remain separate.
The unchanged full-run driver SHA is
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`.

## Read-only archive check

From the worktree:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_work/check_archive.py
```

The checker reads all manifests, before/after receipts, old/new test identities,
specific source changes, fixture hashes and historical v1 proof. It starts no
tests, provider, workload, profiling or GPU operation. Root manifest covers all
archive files except itself and includes the nested full-run manifest.

R2.2 event/order and R2.3 consumer/coverage/ready remain open, as do R3 and complete
M0–M2. Source/native/runtime verification, ready/free and transformation authority
are not established. No detector/backend or LeWM-specific rule was added.

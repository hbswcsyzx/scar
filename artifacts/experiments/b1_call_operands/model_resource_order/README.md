# R2.2 event generation / consumer-start order evidence

Accepted subgate: [interfaces](../../../../docs/M1_RESOURCE_ORDER_INTERFACES.md),
[plan](../../../../docs/M1_RESOURCE_ORDER_PLAN.md),
[acceptance](../../../../docs/M1_RESOURCE_ORDER_ACCEPTANCE.md).

Frozen implementation: `e8121f077c93286e7903e54aeb1729e250bfcb44`.
Registered source SHA256:
`10e12c818eb8c8adaeb3a4e0e4cf4dd4927137f568da590b02f648e013c4a3e5`.

| Path | Exact scope |
| --- | --- |
| `records/attempt001/` | First strict constructor/ID/endpoint checks: 13 PASS. |
| `codec/historical/`, `codec/generate_v2.py` | Independent immutable `bb1b402` archive imports and original v2 byte generation; old v1 not regenerated. |
| `codec/attempt001/` | 108 PASS, including 33 new order-codec cases. This is constructor/wire checking, not a valid physical event graph. |
| `graphs/attempt001/` | 28 PASS; original resource/state Uses, pending same/cross-queue, r1/r2, start/end, scope, mismatches and combined cycle. |
| `queries/attempt001/` | 12 PASS for bounds, exact endpoints, detached support and profile cutoff. |
| `queries/attempt002/` | 13 PASS after adding requirement-only resource Use→exact realization and missing-owner gap. |
| `review/attempt001/` | 0 PASS / 2 FAIL: malformed cloned segment ingress. This was a fixture failure, not an order-validator finding. |
| `review/attempt002/` | Corrected external-queue two-process/two-run fixtures: 2 PASS. |
| `review/composition.md` | Independent bounded static source review; external-queue scope and missing-process equality risks, fixes and limitations. No tests run by this review. |
| `review/final-closure.md` | Independent root-validator/query review, scope probes, bare-INVOKE closure and exact source hashes. |
| `component/final/` | 497 unique cases / 7 criteria / 9.382s PASS; all 489 registered hashes unchanged. |
| `full/` | Exactly one clean frozen run: 4,387 PASS, zero failed/error/skipped, 3 warnings; 476.48855237290263s external / 474.52s pytest; max RSS 1,027,808 KiB. |
| `preservation.json` | All prior 4,297 case identities and 47 fixtures preserved. 473/480 prior registered files unchanged; seven explicit integration/assertion changes; nine new files and 90 new cases. |
| `protected.before.json`, `protected.after.json` | Protected LeWM and SCAR main remain clean at the same HEAD. |

The old schema-version-3 case keeps its identity and now asserts the supported
v3 roundtrip. A new version-4 rejection case is added; it is the only new case
outside `test_execution_order_*`. Focused receipt hashes remain specific to
their original runs; final component and full bind the complete final sources.

Historical v2: **56,435 bytes**, SHA256
`b03a304a582a662d71ebdbe4685776aef9ec4fc357142f0fa2e6656cdae03234`.
Historical v1 remains **88,521 bytes**, SHA256
`66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391`.
The full driver is copied byte-exact from the earlier accepted gate, SHA256
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`.

## Read-only archive check

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_order/check_archive.py
```

The checker starts no test/provider/workload. It checks receipts, manifests,
preservation, historical hashes and the current registered-source fingerprint.
Root manifest covers every archive file except itself. The exclusively owned
full basetemp was removed after child termination; no shared cache was cleared.

All paths are conditional declarations. Native protocol/enqueue/context,
successful production, consumer denotation/visibility/ready, quiescence/free,
complete M0–M2 and transformation authority are not established. R2.3 and R3
remain open. No LeWM-specific optimization, detector/backend or speedup added.
Test timings are acceptance cost, not a workload benchmark.

# V 核心实现有限复核

结论：**PASS_WITH_SCOPE**。在本次冻结快照和审查边界内，没有发现仍然阻断正确性的缺陷。该结论只覆盖 validity、public query、production range 和 codec 接线；不表示 R2 完成，也不证明运行时来源闭合、native 可见性、内容一致性或转换权限。

## 快照

工作树 `/tmp/scar-structured-model-280qf4mi`，冻结提交 `550496f328dbe9941e0a06a6de8c76181fa28039`（提交前产品基线 `f2b4672d9555348dcd05da62a8cd126711ef22f9`）。以下为最终冻结 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `scar/ir/execution/query.py` | `b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1b2e1621739deec` |
| `scar/ir/execution/validity_query.py` | `de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9` |
| `scar/ir/execution/validity_validation.py` | `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e` |
| `scar/ir/execution/validity_stability.py` | `c394f306fe4ff318ee80badf112881f5c2b8c310b881b74253eeca66afe9aadd` |
| `scar/ir/execution/validity_order.py` | `8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4` |
| `scar/ir/execution/validity.py` | `55df8f7cc20c06b246e92822ea51ea4fcf9a64647ede17613e4325b8b8d0f120` |
| `scar/ir/execution/validity_budget.py` | `e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10` |
| `scar/ir/execution/production_ranges.py` | `b271aec4114679468269101f870f208fd933d06dc103eeed98b03b5ec0bbaabf` |
| `scar/ir/execution/production_validation.py` | `4610410f2d367d99a6abdc355ee55b628184a78ea48882b10bd6ae4bacbaa734` |
| `scar/ir/execution/effects.py` | `fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d` |
| `scar/ir/execution/content_validation.py` | `1f308c4e27ff02f751d1129eaeacfda23e0716974d248ab7934546da5e19a1ba` |
| `scar/ir/execution/coverage.py` | `53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411` |
| `scar/ir/execution/work_validation.py` | `290d8fe51c9cc091bddae107b7428bce4ef181949954c3a8751a5fd6d3adb765` |
| `scar/ir/execution/order_validation.py` | `cbea6d0b1072c0cf7a3579e07a13a3a9bad808b807c779e66ac76acf43f6ea09` |
| `scar/ir/execution/production_query.py` | `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab` |
| `scar/ir/execution/production.py` | `cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098` |
| `scar/ir/execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `scar/ir/execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `scar/ir/execution/inventory.py` | `99ed4011ebd379cff8f9b8731b5fd5c2cf9611ff7865d1241dc83dfe67a9afb5` |
| `scar/ir/execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/codec.py` | `b8520a675e5c07d1a6c6cfbba1d1efea790c445535fef4c2e3897d5b2bea7580` |
| `scar/ir/execution/validation.py` | `41baacad27c685901fd0aa2d2607b95d2211d76a3af1da66af6aa32b4231a1fc` |
| `scar/ir/execution/model.py` | `5b7bcefb18bfaaf4b8548f2ebdd4c8346046913dcb5adac528929f85306d5a6d` |
| `tests/unit/test_execution_validity_connections.py` | `ae8d232b20240c951655cc3c944125e3dbd6936f0d80d7fb4a60820d88f8098b` |
| `tests/unit/test_execution_actual_placement.py` | `4b33baa8ab69a64e84a4d35c6bf2b9b90b7b5e515f00243fc0e56dd861402737` |
| `tests/unit/test_execution_validity_query.py` | `a516f2dda8cba9f6aa805c923c789c593a6139706e6b9f2c8969ac39419b2f37` |

The earlier draft is retained as `core-author-review.initial.md`; its source hashes are stale and are not the reviewed snapshot.

## Findings

- **Fresh-query guards:** Public `ExecutionIndex.validity` rejects invalid/non-exact budgets and wrong-kind or subclass `ContentReadID` before refreshing its detached content context. The owned two-case regression monitors that refresh boundary. The frozen `validity.py` also rechecks exact identifier strings inside its union-backed records.
- **Independent source universe and incomplete joins:** The query derives source candidates independently from consumer-supplied supports, then joins write, production, support and placement evidence. A missing association remains an open source-reconciliation condition; deleting a write association cannot shrink the candidate universe.
- **Observed-result barrier:** When a WorkWrite has no linked production, `source_result_barrier` inspects exact raw references or same-bundle source-edge metadata. An already present `scar_native_result`, or an unresolved mapping that could hide one, blocks treating the requested selector as a hypothetical future whole write. This preserves the distinction between an observed result and a pending request.
- **Actual placement:** `_actual_placement` checks known region scope, allocation and containment independently of the declared write rule. Known mismatch is an issue; unresolved geometry or endpoint interpretation stays a gap. Actual fragment eligibility requires a proven placement match, while pending support remains explicitly conditional. The generic placement guard applies even when the byte-prefix rule itself is `Unresolved`.
- **Coverage and alternatives:** Per needed selector portion, support alternatives combine with OR; portions combine with AND. Only a conflicting fragment that is necessary for an uncovered portion blocks that portion. A nonnecessary historical/conflicting fragment cannot veto another valid combination. This addresses the concrete query regression represented by the final query attempt.
- **Canonical effects and completion:** Ordinary effects resolve to their original state accesses. Invoke effects retain the actual successor and completion mapping. Work-list membership is caller-specific; host reads/establishments do not invent work tickets, and an unrelated ticket cannot supply another work item's missing effect. P read/write policy remains local to its validator.
- **Wire:** Schema v6 is emitted only when validity capability is present; the strict reader rejects down-versioning or new tags in v1–v5. Frozen v1–v5 wire goldens remain the compatibility oracle. The saved v5 proof binds the independent old encoder revision and bytes.
- **Authority:** A matched or pending conditional plan is not runtime readiness. `source_reconciliation` remains OPEN; source closure, native applicability, runtime visibility and transformation authorization remain false.

## Verification evidence

My only test run for this review was:

```text
conda run -n lewm --no-capture-output env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_validity_connections.py --junitxml=artifacts/experiments/b1_call_operands/model_validity/review/attempt001/junit.xml
```

Result: **2 passed, 0 failed** in 0.51 s. It checks that invalid budget and invalid ID calls do not refresh the external snapshot context. Raw command, stdout/stderr, JUnit and exit code are in `review/attempt001/`.

I did not rerun tests after the freeze. Additional evidence is read from the preserved root runs, not represented as my own execution:

- Query final attempt `query/attempt010`: **27 passed** in 2.50 s, including the observed-source-result fallback barrier, necessary-portion conflict handling and endpoint-without-mapped-placement boundary. Its recorded source SHA file matches the final hashes above.
- Actual-placement attempt `actual_placement/attempt001`: **71 passed** in 3.57 s, including known cross-materialization/allocation/subset contradictions and unresolved cases. It emitted one pre-existing pytest warning about `record_property` and `junit_family=xunit2`.
- Combined component report `component/final/report.json`: **649 passed**, 11 criteria, 18.653 s, one same warning, zero failures; source digest `72b0125417bc1bd78b1178873e8c8a18e9cfdfe4ff3dd897b4812212542731f9` (report SHA-256 `c456c5390813d3d2409afd8e95126d70fedbf9dbc9a256e4d6faa0f31e70916e`).

No full repository suite, LeWM run, GPU workload or collection was run by this reviewer. The report does not claim complete source capture, native truth, or content readiness.

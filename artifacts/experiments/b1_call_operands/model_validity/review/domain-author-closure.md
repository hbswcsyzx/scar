# V：Q1 / P1 最终有限 closure

结论：**PASS_WITH_SCOPE**。原 `domain-author-review.md` 的 Q1、P1 在当前源码中已关闭；本次限定复核未见剩余阻断。原报告保持原样（SHA256 `690fdd24a3f6acd46708b2d34fb973dcde95ae9ba2326e94c99baf58899e7c8e`），不把旧待审版本静默改成通过。

本次只读源码、既有日志并新增本报告；**没有启动任何测试/probe、修改产品或执行 git**。本人自写 validator/order/stability 的结果不当作独立审查。

## Q1：只按必要需求片段判断已知冲突

当前 `validity_query.py:224–242` 将有效与 blocked offers 放入同一 labeled geometry partition；只有需求 portion **没有 good label 且有 blocked label** 才进入 `blocked_portions`。全局 CONTRADICTED 现在取决于这些 portions，而非任意历史坏 fragment 的 OR。共享预算仍计费，截断优先返回 TRUNCATED。

新用例 `test_repaired_left_with_historical_blocked_left_does_not_turn_missing_right_into_contradiction` 保留两条独立来源：旧 left 已冲突、新 left 有效，right [4,8) 仍缺；在明确 8192 预算内断言 MISSING、无 blocked portions、旧 leaf CONTRADICTED / 新 leaf MATCHED、right hole 仍未覆盖。产品默认预算未改变。原 `test_actual_alias_overwrite_of_needed_fragment_blocks_its_otherwise_matching_support` 继续要求真正被阻的必要覆盖为 CONTRADICTED。

因此源码修正同时保留“已知坏 leaf 的诊断”和“不让非必要历史 leaf 污染另一处缺口”；没有通过删除原来源、冲突或旧反例来取得结果。

## P1：actual 与原 Mat 的结构关系不再依赖 BytePrefix rule

当前 `production_ranges.py:41–98` 在进入任何 rule 分支前调用 `_actual_placement`：准确 artifact scope、原 Mat→allocation incarnation、actual subset 均独立核对。已供矛盾是 issue；几何未知或无 storage-backed Mat 是 gap / `placement_match=None`。该字段沿原 Work Outcome 与 Host Established 解析结果传出。

query 的实际 fragment 必须有 `placement_match is True` 才可进入 known/conditional storage coverage；没有 interpreted endpoint→Mat/bytes 对应时，不会因 actual 是某个准确 RegionRef 就借用该内存覆盖需求。

已阅读 `test_execution_actual_placement.py` 的三类 Unresolved-rule 反例（另一 allocation、Mat 外、另一 artifact）和一致 partial 的正例；正例仍明确无 native proof。另一个新 query 反例使用真实 `mat.region=None` 的 EndpointContent、同 scoped logical version 与看似恰好覆盖的 actual Region，仍要求 placement_match=None、fragment MISSING、known/conditional coverage 均不 COVERED。没有把一个已有 storage Mat 简单改名为 endpoint。

## 已有运行记录核对（均由其他 owner 执行）

- B `query/attempt010/stdout.log`：**27 passed / 2.50s**；result.json exit 0、wall 3.19099s。其 source-sha256.json 精确绑定当前 query、G、测试及 shared ranges，包含下表对应 SHA。本人未复跑。
- root `actual_placement/attempt001/stdout.log`：**71 passed / 1 warning / 3.57s**；report.json returncode 0、wall 4.28800s。包含新增 actual-placement 四例与旧 P selected files；warning 是既有 `record_property` 与 xunit2 兼容提示。该记录的 before/after 绑定 shared ranges `b271aec4...`，不冒称它检验了后续所有文件变化。
- `validity.py` 新 union-ID 分支源码已确认对 ValueOccurrenceID、OutcomeProductionID / EstablishedProductionID 调用严格 `_id`（含内部 exact-str guard）；此处只报告源审观察，不给它补造额外定向测试结果。
- 收到 root 最终统一组件报告：**649 cases / 11 criteria PASS**，544 注册源 fingerprint `72b0125417bc1bd78b1178873e8c8a18e9cfdfe4ff3dd897b4812212542731f9`；实现 clean commit `550496f328dbe9941e0a06a6de8c76181fa28039`。这是 root 的运行/提交 receipt，本人没有运行 gate、fingerprint 脚本或 git；此审查独立核对的是下列具体模块。

## 当前读取绑定（SHA-256）

```text
de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9  scar/ir/execution/validity_query.py
b271aec4114679468269101f870f208fd933d06dc103eeed98b03b5ec0bbaabf  scar/ir/execution/production_ranges.py
53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411  scar/ir/execution/coverage.py
55df8f7cc20c06b246e92822ea51ea4fcf9a64647ede17613e4325b8b8d0f120  scar/ir/execution/validity.py
b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec  scar/ir/execution/query.py
4610410f2d367d99a6abdc355ee55b628184a78ea48882b10bd6ae4bacbaa734  scar/ir/execution/production_validation.py
a516f2dda8cba9f6aa805c923c789c593a6139706e6b9f2c8969ac39419b2f37  tests/unit/test_execution_validity_query.py
478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe  tests/fixtures/execution_visibility_graphs.py
4b33baa8ab69a64e84a4d35c6bf2b9b90b7b5e515f00243fc0e56dd861402737  tests/unit/test_execution_actual_placement.py
```

日志 SHA：query attempt010 stdout `4f61a9b6dc185b246e4d22ad1908eebde97563c91b4142bfd7d5cf0436e454a2`；root actual-placement stdout `928937b52ca8ae74ab88feb6dff818befdc640a9c93d6a1e03b37c819b43f227`。owned 六文件相对 domains/attempt005/source.sha256 已只读核对，均未变化。

## 结论边界

此 PASS 只关闭已提出的 query 必要片段合并与 actual-placement 结构缺口。Endpoint read/flush/persistence 尚无原生解释器时继续 MISSING/UNSUPPORTED；粗 source span/WorkEvidenceBinding 不升级 whole-work 边界。完整 writer/alias capture、native visibility、runtime fact、ready/free 与 transform 权限均未证明。整体 M0–M2 仍 open，无 LeWM 性能结论。完整回归由 root 之后单次执行，本报告没有预报其结果。

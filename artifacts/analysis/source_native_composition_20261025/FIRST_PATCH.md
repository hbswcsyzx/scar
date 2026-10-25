首 patch 待 root 确认后实施：只新增 `scar/analysis/source_native_composition.py` 与一份小型纯 metadata 单元检查；不改 source/native producer、core IR、CLI、旧 artifact 或账本 policy。只实现按显式 sequence 的 `native_context`；不实现 `reference_ports`、不扫 source operand/invocation 流、不创建对象身份边。

拟议入口与输出：

```python
build_native_context_navigation(
    inputs: NativeContextInputs, fresh_output, *, budgets: NavigationBudget
) -> ProviderArtifact

NativeContextIndex.open(
    manifest: ProviderArtifact, *, expected_inputs: NativeContextInputs,
    budgets: NativeContextQueryBudget
) -> NativeContextIndex

index.native_context(sequence: int) -> NativeContextResult
```

`NativeContextInputs` 逐项保存准确 `ProviderArtifact`：source report、source dispatch report、native **final batch** report、原 native bundle manifest、source/native 各自 coordinates、原 AnalysisScope ledger root+revision。压缩 association/index 另保存 stored artifact 及原 report 声明的 decoded bytes/SHA/rows；不把 decoded SHA 冒充 gzip stored SHA。所有路径来自这些显式根及被核准的相对 declaration，拒绝 URI/basename 推断。首 patch 无需 source operand manifest，也不重新获取原 owned runtime authority。

输入检查必须先于数据流：严格字段/schema/version/能力检查；source report3 + dispatch-source report3 的相互 artifact、current composition/inventory binding、Run/process 与 source 原 coordinate membership；native report须为 `scar.native-capture-batch` v2、V2 profile 的最终发布根，所有 shard/shared-program/inventory 引用均来自该准确根。拒绝 execution-shard、gate-started、任意 partial/BUILDING 目录作为 final root。attempt02 exit130/20 shards 不能满足此输入，当前不会运行实档 builder。允许 final root 自身为 OPEN/有 frontier，不能要求每个 sequence 都有 activation；不同 coordinate URI 保留各自身份，不能仅因 Run 或 bytes 相同替换它们。

导航 manifest schema 拟为 `scar.source-native-context-navigation` v1，严格包含 `status=PUBLISHED`、完整输入 receipts、scope revision、adapter source receipt、分母/分类计数、有限 index/data chunk descriptors、各流实际读取计数与 SHA。不可把历史 collector assumption 作为关闭义务的布尔开关：返回结果固定保存 `HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED` 条件及其原 revision-label/metadata facts。它不赋予 weak 身份或 direct-call 权威。

可重建导航只处理已完成的 retained outputs：

- 一次流式校验 source `associations.jsonl.gz` 的 **79,592 rows / 606,200,788 decoded bytes / `5e5de5fe11f1bc89d7929c49cae2921df9e9fa54ac8c64aaf074be53b3818001`**，对照原 marker-index 的每行 line/SHA；按 sequence+phase 建导航。将准确原行保存在有界 transport chunks，记录原 artifact+原行号+SHA，不重写原事实；避免查询时顺序解压 606MB。
- 流式读取 final native report 指定的 chunked dispatch inventory，核实际 sequence 唯一性、原分类及完整行分母，建立 sequence→inventory 原行、原 shard/execution/shared snapshot 和 marker/instance locator 导航。源 marker 与 native sequence 不因数值相同就连接，仍核同 Run/process、dispatch artifact、nonce、phase、exact original instance。
- 不读原100,438 invocation/operand/ETO raw、不读 DB、不扫描对象表、不导入所有 execution shards；source graph、ValueGraph、state 等不复制。输入 metadata/root 不一致 hard reject；frontier/无观察/预算不足分别保存，不能伪造缺失序号为已观察。

builder 的一次完整 retained-association pass 将来必须由 root 单独授权；本次只给实现与小 metadata 检查。拟议 ceiling：总 decoded 1GB、rows 200,000、单 record 1MB、单 chunk 8MB/1,000 rows、stored output 256MB、wall 120s；具体 native inventory 预算在其真实 final declaration 可用时确认，不用 attempt02 partial 估成实测。fresh 输出、失败/中断保存 closed chunks 与 FAILED/BUILDING，最后才原子发布 manifest，不自动重试。

`native_context` 先查 finite index，再读命中 inventory/source association chunks；若 modeled，按准确 `ProgramSnapshot` 和 execution artifact 核唯一 activation、entry/normal visits、静态 INVOKE/normal Return、两个原 `OccurrenceEvidenceBinding`。原 EEG `OperationInstance` 用 `BundlePartitions.selected_records` 按声明 ordinal 有界读取，核 span/child/output parent、原 provider scope、instance、node ordinal、phase 与原 raw fact；不重新生成 NativePortEvidence。返回到 source invocation 的原 qualified reference 及其行 SHA，**不声称此次重读了原 invocation 内容或刷新 source guard**。若需要进一步读取 binding/body，则另一个明确 query 负责，不让本入口偷偷展开图。

结果严格区分：`RETAINED_SOURCE_CONTEXT`（带原 producer conditions）、`CONTEXT_UNRESOLVED`、`NATIVE_FRONTIER`、`SEQUENCE_NOT_OBSERVED`、`BUDGET_EXHAUSTED`。字段仅为输入 root/scope、原 sequence/classification、span/output association facts、原 InvocationKey/definition/body namespace/可选 activation ref、限定 execution 的 invoke/Return refs+bindings、原 source/native frontiers、未访问 cursor 及实际读取成本。不返回 `direct_call=true`、object identity、值/效果/ready 结论；异常或无 native activation 的原行仍可查询。

query ceiling：decoded 64MB、index chunks ≤2、retained data chunks ≤4、原 archive chunks ≤2、selected execution/static metadata 各一个、wall 10s；所有读取合计计费，artifact 超界则明确 budget frontier。metadata 不合法/identity 矛盾 hard reject，真实缺事实保持具体 frontier。manifest 与命中 chunk 全部核 stored/decoded receipts，不依赖目录存在或旧 validation PASS 标记。

首 patch 验证只用 tiny retained metadata：合法 ancestry、wrong input root/Run/nonce/phase/ordinal、wrong invocation/Return binding、native-only/zero-Tensor 仍有上下文、frontier/未观察 sequence、source-only definition、分母/预算失败、拒绝 partial root，且 reader 不调用 raw producer。producer validation/guard 被禁止调用的检查应验证真实边界，不复刻实现。实档首次构建及查询计划另外交 root 审阅，不随 patch 自动运行。

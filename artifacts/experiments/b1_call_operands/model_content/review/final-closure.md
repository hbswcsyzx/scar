# R2.3-D 最终有限只读 closure

结论：**PASS_WITH_SCOPE**。当前 D 声明接口、原端口/来源连接及公开查询范围内，
未留下需阻断本门的具体问题。本轮发现的 host exact-pair PID 缺口已经 root 修复，
并绑定更新后的组件报告；不能沿用修复前的 441 项结果作为新源码验收。

本审查仅读取源码、API 文档和已有报告，核验 SHA256，并写本 ignored 报告。
没有运行任何测试、probe、新脚本、GPU、LeWM workload 或 git，没有修改产品/文档。
Q records/validator 是本代理实施的部分，只作接口闭合核对，不冒称独立自审；
交叉审查重点为 root 的 content_validation/query/validation。

## 绑定的实际证据

- 最终报告：`model_content/component/final/report.json`、`report.md`。
- 基线 revision：`6efbe272bceb1036eba3725f11c47960fd5dd301`。
- component source fingerprint：
  `264df18c32498a03e637604de28a81912fd176b75eddeb79c7b818234bf22198`。
- 报告的 506 个 tested_files 逐一用 `sha256sum --check --quiet` 只读核对，exit 0；
  当前文件均匹配。没有重新运行 gate/fingerprint 脚本。
- 最终组件日志实际为 **445 passed in 9.24s**，7 criteria PASS，exit 0；
  report.duration_seconds 为 9.995。此为 root 的运行，本审查没有独立执行。
- 修复前 441 passed in 9.04s、fingerprint `8f8e5676…` 已保留至
  `component/attempt001`；不能与最终 445 相加。
- PID 修复后的前一组件 445 passed in 8.93s、duration 9.638、fingerprint
  `e318c72b07cb7d26469b33f83e6d4ae0ab44d735adf53fb8c413e32f9dd9cc2c`
  已原样保留至 `component/attempt002`。随后 root 的 diff-check 发现 connections
  测试多余一个 EOF 换行，仅删除该空白后重跑最终组件。该样式变更不改语义；
  本审查不沿用其旧 fingerprint 冒充最终源，也不重复累计这两次 445 项。
- Q 的原报告与提取补充仍分别为 `2724e05d…`、`8354e1fa…`，其最终四文件
  与当前文件匹配。早期 content 源审/codec 报告是各自时点快照；最终组件的
  per-file hashes 是当前实施批次依据，不把早期 coverage/content hash 当成当前值。

## 最终源审关闭项

1. **开放多对多来源。** `_paired` 对 exact owner/artifact/instance 求真实 matches。
   缺当前 pair 时，无论是否存在其他 pair 均为 gap；返回 `correspondence=()`。
   不借同 host、EEG parent、时间接近补 join，不把部分关系非成员性当排斥证明。
   查询保留 source instance、correspondence tuple 和缺口。

2. **准确矛盾仍拒绝。** source version/materialization/object、已提供图 FK、原
   native slot/actual incarnation 的冲突继续 issue。NativeInput 沿 boundary 原
   position→EntryPort→本次 initial-entry formal；NativeOutput 必须为实际
   Return/Raise 的准确 exit/index/Use，不创造 producer/after。

3. **本轮新增 PID 缺口及修正。** 修复前，host-only 且有明确
   OccurrenceEvidenceBinding 的 PID 冲突不被检查；这与 API §3 不一致。
   这是确定的源审发现，本审查没有声称实测旧实现失败。
   当前 `_paired` 只在 host exact matches 非空时比较原 occurrence 与 EEG 已知 PID；
   missing pair 仍 gap。Work PID 由 DirectExecution.thread.process 或实际
   Queued.queue_access→binding.target→Instance.ProcessRealm 解析；未知执行域
   保留 `content_work_process_unresolved`，不把 enclosing caller 当实际执行 process。
   相等 PID 仍不授 run incarnation/native 对应证明。
   root 新增 producer/reader 两个 host PID 反例及 ProcessRealm/RunRealm 两个 queue
   case；四项存在于实际源码并纳入最终 445 项组件结果。API §3 已同步此精确边界。

4. **引用读取与状态。** resolve_subject 保留原 static definition；动态 Use 未观测
   也不能把 Reference 的 effect=None 放过。原 StateAccess 的 before/support、
   owner/reference、anchor 当前 incarnation 继续核对；INVOKE effect 复用已验证
   work effect 和实际 completion/formal，不臆造成功后态。

5. **区间不缩义务。** ResourceConsumer 查询的 interval 始终为准确 ticket 的
   WorkStart..WorkEnd，conservative_work_interval 同值；较窄 NativeWorkRead 仅放
   declared_native_interval，保持协议未证 gap。Host interval 与原操作 scope/order
   对齐；ObservationConsumer 用真实 root interval，不假造 work。

6. **Q 及五表。** RequiredOutput 是准确 contract.required_outputs membership；
   endpoint 是额外 typed requirement+required facet+协议关联，不能由 EXTERNAL
   facet 自动生根。Known core endpoint 使用 BoundEndpoint，外部无 core endpoint
   不造绑定/代码 consumer。Binding 可先于观察，跨 activation pairing 保留 gap，
   已知 run/process/current-state 冲突拒绝。五表均接入 model、validation、catalog、
   codec 和查询；authority flags 一直为 False。

7. **共享快照及格式。** 每次 content query 新建 exact ExternalSnapshots，三种
   ValueGraph/EvidenceGraph/SemanticGraph 白名单按 bytes/hash/schema/size 校验后
   strict decode 成 detached 图，查询内复用，返回 deepcopy；URI 不读取。
   geometry 复用 `_ValueCatalog.from_snapshots`，不再用不兼容 duck type。
   AllocationTarget 以 hash/schema/size/AllocationID 比较，URI 别名不改变身份。
   任一新表非空触发 v4；旧 v1/v2/v3 字段和 reachable tag vocabulary 隔离，
   不允许带新 capability 降级隐去。旧 golden 来源与实际兼容日志已有归档。

上述第 7 项 geometry resolver、第 5 项 host interval、第 7 项 URI identity 的
三项早期源审修复仍在当前源码；相关 canonical graph/query 回归确在组件中，
未因本轮 PID 修复撤销。未发现新增 FK crash 或接口阻断。

## 所审当前 SHA256

| 文件 | SHA256 |
| --- | --- |
| `content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `content_validation.py` | `ebff98a37d99583fe1c2a103e25639bba1e536697bdcf60d9276474754d59a23` |
| `query.py` | `b5c56756e7d81e162c71edf32da477092b2d3daba09450b59a94fa142396ea8a` |
| `validation.py` | `49066eed09567850ae824fd8800b359be33f4c403d641e2fe117b0a786e63966` |
| `observations.py` | `8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882` |
| `observation_validation.py` | `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983` |
| `model.py` | `74d226bc031f557f8074f818fef2bb488bab5ffab96f53c46d25b85f275ce613` |
| `snapshot.py` | `e3b4e071a865f8cb94bcf732ae8b45688ee33243e03921c551dc76690621ed5b` |
| `coverage.py` | `43a0f21c7a5e5815f3e4408dcf76ff39eeb96f30f4fc0af655a8ccf0aff3a32b` |
| `codec.py` | `97aab7e5cf736d8687f85236028294eeb23dd20504c1867ff68529261c14f90a` |
| `tests/unit/test_execution_content_query.py` | `b7e177ecda35ddb45726b063852884427004d651744499842cb173747d5f025d` |
| `tests/unit/test_execution_content_connections.py` | `176a4c94edfca978f5c956277f95494f1bf0d321a38336f974a37509ff5f8c3f` |
| `docs/M1_CONTENT_CONNECTION_API.md` | `894c22d9a724981e049dc5e7b1fafa4092beb3834753fc7dfdd7c4da1eb4ae27` |
| `docs/M1_CONTENT_CONNECTION_PLAN.md` | `26f86d36c172ea4d37ab396a32cbcc0c6f99f4a5a84299b29afd5a8e72d7c8de` |

产品文件名未带目录者均位于 `scar/ir/execution/`。

## 有界结论

PASS_WITH_SCOPE 只覆盖 D 声明结构、准确引用、来源连接和公开查询。
生产贡献 universe/P、完整读区间有效性及 visibility/V 没有在本门完成，不能因此
反推 D 实施错误，也不能以 D 通过宣称 ready/free。整体 M0–M2 仍 OPEN；
没有 runtime/source correctness、transform authorization、LeWM 自动建模或加速结论。

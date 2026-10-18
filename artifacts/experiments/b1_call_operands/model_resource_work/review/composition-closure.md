# R2.1 work/query/wire 有限交叉复审

范围：`work_validation.py`、`query.py` 及相连 `validation.py`/execution codec，对照 `docs/M1_RESOURCE_WORK_PLAN.md` R2.1。仅只读源与已落测试；本次未运行 Python、pytest、probe、组件或全仓。自写 38 个组合用例既有首轮结果不重跑，也不充作本轮独立测试。

## 初读快照与结论

初读 `work_validation.py` 为 `5150570dc2c548a47f61f5d4daf5ee0aaf7ee000732d0ce693f961a5e1553a17`。
本快照有一个本代理报告的独立候选及 root 已在修的两处 peer basis-target 问题；最终结论待下方修复 receipt，不将初读判为最终 PASS。

### 本轮独立源审候选：空 queue prefix 的已知 run 未核对

旧循环 `work_validation.py:201` 对每个 prefix 只检查观察点存在、queue 实例 QUEUE role 与 previous 的 queue ID；只有 work 非空才通过 terminal_point 比较 work run。
因此可从 owned queued 正例新增一个真实登记的 Run1/Process1 EvidencePoint，再加 `work=None, previous=QueueStart` 的 empty prefix：queue 仍为原 ProcessRealm(Run0) 实例，observed_at 改为 Run1。原 prefix.previous 指向该 empty prefix；不修改任何 canonical core/access/Use/State。
此构造的 known queue 身份域与观察点跨 run，旧代码没有比较路径。最小修正是每个 prefix（包括空起点）独立校验已知 queue realm 对其观察点，并保留 External/不明确 scope 的 gap；不据此展开 R2.2 设备顺序证明。

这条在本报告写入时是**源码构造候选，未由本代理执行复现**；root 已落 `test_empty_queue_boundary_must_match_queue_identity_run_even_without_a_work_ticket`。测试存在不等于运行通过。

### root/peer 已知问题

peer 已报告 HandleTarget 的 UseRef 类型错配、ResourceAccessID 与 underlying handle target 矛盾未被核对；root 在本任务前已明确接管修复。本代理没有重复 probe，也不将这两项计作自己的独立发现。需要同时保留同 category 的不同 Reference 可能 alias 的 denotation gap，不能用不等 ValueOccurrenceID 证明不同对象。

## 其余已核对的范围

1. **host RAISE 不抹工作。** WorkSubmission 来源为 WithinOperation/ExternalWorkSource；没有按 host NORMAL/RAISE 删除 ticket。`ExecutionIndex.work` 的 host_completion 只从实际 INVOKE transfer 派生，独立返回 outcomes、quiescences、retentions。已落查询测试含 host RAISE 且 outcomes/quiescences 为空的 pending 正例；查询无 ready/free 字段。
2. **不制造 producer/after。** 普通 canonical_effect 直接解析原 StateAccess index、其原 before UseOccurrence、原 after ValueOccurrence；INVOKE 分支返回原 input、实际 transfer/原 successor 与准确 landing formal，或原 Unresolved post；不构造 StateAccess 或共同 AFTER world。边界必须是已验证 submission/frontier 中的原关联，不能将任意新 post 当查询授权。
3. **实际 completion。** validator 核对 State input 属本 INVOKE invoke_arguments、当前 BEFORE state、原 successor/result、同 Location 的原 State formal、实际 transfer 与 landing visit/activation。known 错边为 issue；缺 input/transfer/post 保留具体 gap，不回填 NORMAL。
4. **terminal/quiescence/retention 分离。** 多 observation 保留且 known terminal kind 冲突拒绝；frontier 不覆盖旧效果，未证明完整产生的内容仍 gap。quiescence 单独引用本 ticket；release 检查 cited quiescence 与已知顺序，未知 interval/source 保留缺口，绝不授 free。WithinOperation start 不假造 BEFORE/AFTER 点，只校验候选边界 state，保留 internal-start gap。
5. **queue prefix 的有限性。** persistent previous 链、准确 queue 实例、Queued.queue_access 的原 requirement/target、prefix.work 与 submission 双向选择及依赖/前缀 cycles 有机械校验。query 有正整数 budget，截断返回边界与 `runtime_order_verified=False`；不把链本身当设备 HB。除上列 scope 候选外，未发现要求扩展 R2.2 的本门阻断。
6. **缺失 FK 诊断。** _Context 对 work 各表先检查重复 ID；ticket、effect occurrence/access index、invoke input/formal、executor/queue access、prefix/previous、materialization/allocation、quiescence、retention target/backlink 均有明确 missing 分支。resource/coordinate 验证在 work 前有 issue 短路，避免 work 中受保护的直接索引/next 访问无效 resource FK。此项是源审，不冒称穷尽所有恶意输入运行。
7. **不升级声明。** submission/effect/native applicability、frontier 内容、quiescence 与 retention 都保留具名 gap；report 的 source_runtime_verified/transformation_authorized 永为 False。R2.1 不导出 event record、consumer denotation、AND/OR readiness 或 ready 布尔，也未将 partial FAILED/CANCELLED 当空输出/已可释放。

## old v1 / new v2 wire 静态核对

- codec 的 version-specific record schema 在 v1 只去掉五个新 work 表，v1 vocabulary 从该闭合 schema 递归派生，新 work tag 不能通过旧 union 混入。
- 编码前重查整个 exact model；任一 work 表非空选择 v2，显式 schema_version=1 拒绝；resource-only 默认仍 v1。v2 可显式空五表，不把表示迁移宣称为“没有工作”的证据。
- 解码要求准确字段集合；v1 不能携带新字段，v2 不能缺新表；ID/Enum/union/exact integer/重复 JSON key 仍严格。wire 只检记录，不冒充 graph 及 native 证明。
- 已读取独立历史 v1 golden/proof 断言及新 v2 测试源码；未在本轮执行它们。

## 初读绑定 SHA256

| 源 | SHA256 |
| --- | --- |
| `work_validation.py` | `5150570dc2c548a47f61f5d4daf5ee0aaf7ee000732d0ce693f961a5e1553a17` |
| `query.py` | `16b384b9a932366a7308462b9b746faaff5d4e95aaaad52db37f4fd84267dc41` |
| `codec.py` | `b9df39823e351e855702a8bdb324cb637da1431fd55b5a5bc1a3c3310e0fd890` |
| `validation.py` | `14f4817aab8b907d3d06a083d0e355db3018b5d6d30ac332d70136008e0c860c` |
| `docs/M1_RESOURCE_WORK_PLAN.md` | `46483f9a9cfbcd203db364dba65b5914b8a4f49cb5ac3d395a21792e5e5f9717` |

后续修复必须另记准确 source hash 与实际执行者/结果；不得将本代理只读判断改写成实测。

## 最终静态修复 receipt

最终结论：**BOUNDED_PASS**。本轮只读范围内无剩余阻断；没有新增实验或重跑 owned38，也未修改跟踪文件。

root 最终组件报告：**407 PASS / 9 criteria / 6.282s**，480 注册源 fingerprint
`f26bb51ad783f85c43de3a8d75999d9943f915973c629411c0b27b264d57487c`。
已读取 `component/final/report.md`，其 source digest 与 root 通知一致；组件由 root 运行，不是本代理独立执行。

最终静态核对：

- `work_validation.py:200–228`：每个 prefix 先核对 queue 的 RunRealm/ProcessRealm 与 observed_at 已知 scope；包括 `work=None` 起点。ExternalRealm 明确 `prefix_scope_unresolved`，不授跨域已知顺序。本轮候选闭合。
- root 在 `queries/attempt002/output.log` 实际记录 **11 PASS / 3 FAIL / 0.64s**：两个 peer basis 反例和本代理 empty-prefix 候选。原失败保留；本代理没有执行该复现。最终组件通过包含其修复，不累计旧失败轮次的用例数。
- `:455–488`：HandleTarget basis 检查已知 Reference/native scalar 类别矛盾；同类别不同 occurrence 仅给 alias/denotation gap。ResourceAccessID basis 经 `retained_resource_key` 解析 retained Handle→原 referent、Materialization→原 allocation，再比较可比 target，明确矛盾为 issue；不可比较则具体 gap，未将 tag 或 UseID 不等当对象身份证明。两处 peer 问题闭合。
- `:81–89`：同 run、不同 activation 或 native EvidencePoint 的观察，在没有 host 顺序对应时增加 `observation_order_unresolved`。仍允许合法外部/跨 activation 观察；没有把缺顺序误写成 before，也没有硬拒绝它。该项由 peer 源审提出、root 补充，本代理只静态确认。
- 最终 query 改为读取 _Context 预索引的 work effects/outcomes/quiescences/retentions；`validation.py:87–93` 的索引只保存原行，不造 producer/state。`canonical_effect` 仍只解析已有准确关联；`work` 仍分别返回 host completion、原效果和独立 observations，保留 False authority；prefix 查询继续有预算且不授设备 order。
- codec 与 frozen plan 的 hash 未变，前述 v1/v2、精确 actual completion、诊断缺口及 R2.1 边界结论保持。

最终读取的 SHA256：

| 源 | SHA256 |
| --- | --- |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/query.py` | `d968d0f19bdd148f0df3b298492ed924223e7cd10734445938212ce2d8569df8` |
| `scar/ir/execution/validation.py` | `0c79b637484dab61bacb0132ab5a81ba3b7b66a02c80188c6c31d5b8c0a1e604` |
| `scar/ir/execution/codec.py` | `b9df39823e351e855702a8bdb324cb637da1431fd55b5a5bc1a3c3310e0fd890` |
| `docs/M1_RESOURCE_WORK_PLAN.md` | `46483f9a9cfbcd203db364dba65b5914b8a4f49cb5ac3d395a21792e5e5f9717` |
| `tests/fixtures/execution_work_graphs.py`（本代理冻结交付） | `7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f` |
| `tests/unit/test_execution_work_graph.py`（本代理冻结交付） | `3c8fdef85aa02b72a63745c0be4b411426adf06da076bbda477789f7d1a60bb5` |

本 receipt 只确认具体源码修复与声明级边界。实际协议、物理提交/完成/保留、source/runtime 对应、完整内容、ready/free 和变换授权继续未证；完整 R2、R3、M0–M2 不因本子门闭合。

# R0 最终有限复核：work/outcome/order/ready

日期：2026-10-18。范围为合同 §4–5 与其必要的 occurrence、资源身份、观察根和迁移关系。
本轮仅阅读和新增本报告；未运行 Python、实验、测试、LeWM、GPU 或 git，未修改产品/测试/合同或旧报告。

## 所审版本与结论

- `docs/M1_RESOURCE_EXECUTION_CONTRACT.md`：**`afd291d40c8377b3e0af650310d369887c51cd1b617f8cbc423973edede32fb7`**；实际 sha256sum 与 root 指定一致。
- 当前计划 SHA256：`5708b647e226335f02a6ac53b236063ae4b1dd9769e0d285a6e6730da40576a7`。

**BOUNDED_PASS：在本代理所审 work/ready 关系范围内，前两轮实质缺口均已落盘关闭，没有剩余 R0 阻断。**
这是关系合同复核；§1 明确具体 records/wire 在 R1/R2 验收。不是产品、自动恢复、物理协议适用或运行 readiness 通过，不替代其他代理的 occurrence/resource 审查。

## 修正闭合核对

| 关系/反例 | 最终合同位置 | 复核结果 |
| --- | --- | --- |
| opaque call 内先提交再 host RAISE | `166–172,194–204` | WithinOperation 是发生归属，不强行放到调用 BEFORE/AFTER；ExternalWorkSource/EvidencePoint 不伪造 Python 点。INVOKE 状态引用原 input Use 与实际 completion result→formal；未完成可 UnresolvedPost，不造普通 StateAccess。 |
| 无队列同步执行与队列未知 | `174–176,191–193` | DirectExecution 与 UnresolvedQueue 分开；queued profile 仍需精确 queue binding，不给 CPU 捏造 stream。 |
| ResourceOutcome 与 host outcome 分开；正常短写/失败部分输出 | `182–186,194–196,208–211` | COMPLETED 不等于整个请求区域已产生；protocol_result/effect_frontier 保留实际范围，失败/取消不回滚。 |
| work 在途借用与回收 | `180,212–215`，关联 `144–157` | retention 指向原 Use/effect/materialization 的同一 target，work holder 与 authority/sharing 分开；host 引用离开或 outcome/ready 标签不终止借用；未知 coverage 不当空。 |
| event 复用与旧 prefix | `222–226,251–254` | EventRecordID 为一次 record 代次，wait 精确绑定 captured record/frontier；空 event query、同名队列、时间戳不造完成。 |
| queue order 合法消费但 CPU 未见 Completed | `243–244,255–258` | OrderedVisibility 是独立支持分支，限定精确消费 queue/prefix；不授 host、别的队列或持久化。 |
| 多工作贡献、mixed Completed/Ordered | `239–248,259–263` | 每个贡献的替代支持 OR、全部必要贡献 AND；不同贡献可用不同 basis，不把 work/consumer 集合独立 union 后交叉授予。 |
| FAILED/CANCELLED 已知内容不足 | `268–270` | order chain 不能补出缺失内容；部分证据只支持对应 footprint；无 outcome 不误判失败，Ordered 仍带内容产生/异常传播条件。 |
| ready 多 consumer 复用及版本失效 | `264–273` | ready 不作单次 permit；精确内容/物化/承载生命周期、visibility、scope 匹配，写入/复用/未知 alias 不继承旧支持。 |
| consumer 尚无可靠 logical denotation | `70–72,271–273`，关联 `24,30–31` | 保留 typed consumer 与具体 unresolved 义务，不从 shape/部分内容造版本；不要求完整 denotation 自动恢复先完成。 |
| 程序结束后的文件观察根，无源内 reader | `228–234,279–288` | ConsumerTarget 明确 ExternalObservation/UnresolvedObservation；新 ObservationRoot 引用准确 scoped ContractID/root/端点/协议，不冒充旧 EXTERNAL facet 已有此接口，不造 core reader。 |
| 非内存表示和 region=None | `235–238,290–293` | StorageBacked 沿原 ValueGraph 派生；EndpointBacked 明确端点及原 selector/state，其他情况 UnresolvedPlacement；不凭 region=None 猜文件，不给文件造 allocation，不因 backing 标签授 disjoint。 |
| ready 不代表 allocation/endpoint 可 free | `212–215,274–277` | pending access、retention、ownership/quiescence 仍是独立义务，一项输出可用不覆盖所有在途访问。 |

## 对具体 records 实施的有界读取

1. 本合同不是 exact wire schema。ReadyEvidence 摘要中的 allocation，以及匹配文字中的 StorageRegion/allocation，应按新 Placement 判别解释：只有 StorageBacked 才解析这些端点；EndpointBacked 使用实际端点生命周期/内容支持；UnresolvedPlacement 不造承载。R1/R2 具体 records 应遵循该已明确关系，不能回退成所有 evidence 必填内存 allocation。
2. core AccessOccurrence/InvokeBoundaryStateEffect、准确 UseOccurrence/actual completion，加 snapshot/occurrence 外键，足以支撑本门关联；不要求追加静态 WorkSite/ReadyUse 表或另一套可修改 producer/state。
3. `required_contributions` 的覆盖与内容/物化匹配必须真实核验；支持候选的版本、scope、consumer 域与条件要相容。Observed/Declared 是来源轴，不自动将未知 applicability 升为 PROVEN。
4. §6:297–311 保留旧 `Materialization.ready_event` / `mark_ready` 含义，不为旧输入补造 generation/visibility；execution bundle 自己版本化，不给静态 core 填本次运行身份。

上述是实现读取边界，没有要求新 native rule、scheduler、完整前端或再跑 witness。六个既有 CPU/OS witness 的有限解释沿前报告保留：worker 部分失败及稍后 future.result 报错，不等于已实测 enqueue 调用自身 submit 后 RAISE；没有 CUDA、power-loss durability 或 SCAR 产品证据。

## 交叉源码依据与界限

`scar/ir/program/model.py:612–623` 的 INVOKE 禁止普通 access/results；`validation.py:519–540` 的真实 completion 状态来源；`v2/values.py:150–159` 的 region 可缺省；`v2/contracts.py:136–158` 的旧合同 root 能力边界，与此次合同修正一致。源码 hash 沿前报告复核未变：

```text
scar/ir/program/model.py 3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1
scar/ir/program/validation.py 04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264
scar/ir/v2/values.py 2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259
scar/ir/v2/contracts.py c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1
```

本报告只关闭所列设计关系的复核，不关闭 R1/R2/R3 产品分母、resource/native/source-runtime 对应、第一阶段或优化授权。

## 最终 SHA 的小差异复核收据（追加，保留上述候选历史）

root 随后将最终候选从 `afd291d...` 更新为 **`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`**。本代理已重新只读 §4–5（现 `171–301`）并 sha256sum 核对；上述 work/outcome/order/ready 关系内容与判断保持一致，原表行号属于 `afd291d...` 版本。

另已读到最终两处 typed 边界：ExecutionSegment.host_thread 可以 UnresolvedHostThread，不能借缺失线程身份授同线程顺序；ResourceAccessBinding.handle 可以 ExplicitHandle、ImplicitBinding（原 rule/current selection refs）或 UnresolvedHandleAssociation，无 handle 的 CPU/current-stream 不需伪造 ValueOccurrence。两者都保留未知/隐式来源的准确范围，没有产生额外肯定 readiness。

**最终结论：BOUNDED_PASS，绑定 `74a606fc...` 完整 SHA 如上；无剩余本范围实质阻断。** 本次差异复核同样没有运行实验/代码或编辑合同，仍非 R1/R2 产品验收或 source/runtime 证明。

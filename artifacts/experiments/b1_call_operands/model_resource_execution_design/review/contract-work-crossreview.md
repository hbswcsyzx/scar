# R0 work/ready 合同反向复审

日期：2026-10-18。仅只读合同、计划、原 core 与既有 CPU/OS witness 源/日志；未运行脚本、测试、GPU、LeWM 或 git，未编辑产品/测试/文档及旧报告。

## 1. 所审版本与有限结论

- 初读 DRAFT：`docs/M1_RESOURCE_EXECUTION_CONTRACT.md` SHA256 `247a09628b279a34ce6ccc904ef788e97a656c7924d8cd49f314e3a6d833ec2c`。
- 复读已落盘修订：同文件 SHA256 `fc2b282770ec896ef0988eb535d590cbeb41c0090d42db2b3f164d6e7170a09c`。
- 计划：`docs/M1_RESOURCE_EXECUTION_PLAN.md` SHA256 `9f7647b905a9ed8ace399cb16570c49e0ea5abe40360581905145f0b1cbcad37`。

**BOUNDED_PASS（§4–5 的关系/层次设计复审）**：初稿确有不能接原 INVOKE 的字段缺口；root 已改为普通 AccessOccurrence / InvokeBoundaryStateEffect 联合，并修正 opaque call 内提交的归属与 mixed contribution 支持。已实际重读这些修订。未发现需要另造静态 WorkSite/ReadyUse 表或第二套 producer/state 的阻断。

此结论不是 execution records、validator、产品或 CUDA 支持已通过；合同仍为 DRAFT，完整 R0 收敛由 root 汇总其他审查。

## 2. 初稿实质问题及已关闭的修正

### R1：opaque INVOKE 没有 StateAccess，不能强迫其工作引用 AccessOccurrence

**源码事实：**`scar/ir/program/model.py:612–623` 明确 INVOKE 不能定义普通 results 或 StateAccess；状态输入是原 invoke_arguments 的 Use，NORMAL/RAISE 后态为 CompletionResult→landing formal。`validation.py:519–540` 依该路径校验输入域及未知效果两边的新状态。

**初稿机制：**旧 §4 `WorkSubmission.accesses: canonical AccessOccurrence refs`，而旧 §2 AccessOccurrence 必须索引原 StateAccess。考虑真实 opaque `submit_then_raise()`：先提交 work W，再在同调用内抛错。该调用的 resource effect 只能接实际 RAISE completion 的状态 formal，原 Operation 根本没有 access index。若为满足字段而加 access、虚构 NORMAL 或先强制展开完整 native body，均违背 core 或本门范围。

**已核对修订：**新 §4:113–144 定义 `InvokeBoundaryStateEffect(invocation,input_state,post)`，post 是实际 completion state 或 UnresolvedPost；input 精确指原 invocation 的状态 Use，后态派生原实际 edge/result→formal。它不发明 mode/footprint、普通 access 或 producer；匹配未恢复保持具体 UNKNOWN 义务。此缺口已关闭。

### R2：一次调用内部提交不能强迫定位到调用的 BEFORE/AFTER

**初稿机制：**`submitter: ExecutionPoint` 只有操作前后/边等 host 点。若把内部 W 绑到最终 RAISE edge 并当作精确提交时刻，会错误表达 W 在抛出后才提交；绑 BEFORE 又可能错误跨过内部 callback/检查。

**已核对修订：**§4:113–139 的 `WithinOperation(occ,physical_submission_fact)` 只声明发生归属及真实提交依据；未对应 core 的物理事件可用 scoped ExternalWorkSource。§2:41 的 native EvidencePoint 不伪装 Python 操作。多 ticket 存储顺序不推出设备执行顺序。此层次矛盾已关闭。

### R3：多贡献可以混合 Completed/Ordered，不能只选一种全版本 basis

**最小合法图：**一个 required region 由工作 A、B 两个贡献组成；A 已有完成与可见证据，B 通过精确 queue wait 在 consumer 前执行。CPU 尚未观察 B 完成，但该 consumer 有合法有序消费关系。

旧单个 `ReadySupport = CompletedVisibility | OrderedVisibility` 容易实现为“所有贡献必须同一种依据”，从而错拒；把 required contributions 改 OR 则会漏 B。

**已核对修订：**§5:167–187 改为 per-contribution alternatives，并明确：

```text
Satisfied(requirement r) = CompatibleIdentityVersionScope(r)
  AND ConsumerDenotationResolved(r)
  AND CompleteRequiredContributionCoverage(r)
  AND FOR ALL required contribution c:
        EXISTS valid support s for that exact (r,c)
```

同一贡献的候选支持是 OR，全部必要贡献是 AND；候选可以分别 CompletedVisibility 或 OrderedVisibility。候选各自的资源、generation、版本、consumer 域及条件必须相容；不能把 work 集合与 consumer 集合分别 union 后交叉配对。此歧义已关闭，无需为实现该公式另建 producer 图。

## 3. 各压力路径的反向核对

| 场景 | 当前合同的准确对应 | 结论 |
| --- | --- | --- |
| submit 后 host RAISE | §4:134–144；WithinOperation + 实际 RAISE state，ticket 不依赖返回 Python handle。 | 不丢提交；未完成后态可 unresolved，不能伪造正常结束。 |
| work Failed/Cancelled 有部分写 | §4:126–151 的 effect_frontier/部分状态与 quiescence 义务。 | 保留部分内容；不回滚、不给 free。 |
| 设备队列有序消费但无 Completed 观察 | §5:179–187 的 OrderedVisibility 与 mixed per-contribution 支持。 | 不强制 CPU synchronize；也不授 host read。 |
| event record g1→再 record g2 | §5:175–178 EventRecordID 标一次代次，wait 捕获准确 record/prefix。 | 旧 wait 不自动覆盖新工作；空 event query 不能证明任意 ticket。 |
| 多工作/多 writer/跨队列 | §4 dependencies；§5:183–187 footprint coverage + AND/OR 分层。 | 一项完成不足整个内容；后续新提交不属于旧 captured frontier。 |
| ready 复用和内容/承载失效 | §5:188–194 的准确版本/物化/allocation lifetime/domain/scope 与未知 alias 处理。 | 可多 consumer；不消费 ready。新内容/生命周期不继承旧支持。 |
| 未对应 consumer denotation | §2:53–55、§5:192–194，以及 §1:23 Unresolved。 | 保留 consumer 端口与候选物化/缺口，不按 shape/部分数据补造版本。 |
| output ready 与 allocation free | §5:195–198；free 另需所有 pending accesses/ownership。 | 不把一份输出可消费当作整个 allocation 可回收。 |
| flush/close/persistence | §5:179–182 限定 visibility domain；计划明确分开 CPU 可读与持久化。 | 设备顺序、host 返回、flush 和 durability 不互相冒认。 |

**应保持的一条显式解释：**coverage 是所需内容贡献真正得到支持的覆盖，不能仅指“预定 writer 范围”。若已知 A FAILED/CANCELLED 且 effect_frontier 不覆盖 requirement 的完整内容，纯 Order 链不能填补缺失内容；确有部分区域证据时只满足对应子区域。未知 outcome 不判失败，也不因此判完整内容已实现。这是现 content/coverage 条件的必要含义，已发 root 建议写明；不要求新增字段或 runtime 测试。

## 4. 不要求新增静态 WorkSite/ReadyUse 表

**本轮结论相对原预审的澄清：**原 `work-ready.md` 提出的静态表是 Proposed 草案，不是不可替代的实施前提。当前 execution 层已有 snapshot→OperationOccurrence→原 Operation/Use/Access/实际 completion 的准确路径，足以校验一次真实发生中的提交、效果边界和消费要求。

- 多个 work：同 occurrence 可关联不同 WorkTicketID，无需额外静态 slot 证明动态个数。
- ordinary effect：AccessOccurrence 精确读回原 index；INVOKE effect：新边界联合精确读回 input Use 和实际 completion，不需要假造访问行。
- consumer：准确 UseOccurrence/AccessOccurrence、物化/版本候选、denotation/coverage 义务足以表达动态要求；未对应时可保留 unresolved，不能必须先有完整 denotation。
- 尚未执行路径的静态 work/ready 协议模板可将来有独立用途，但不应为 R1/R2 的发生接口冻结增设重复 requirement/actual 表，更不能将模板存在当作肯定提交。

计划 §2 的 R1 occurrence/resource 与 R2 work/ready 有序切分因此可实施；本审查不要求完整前端、全量 trace reconstruction、scheduler 或 CUDA runtime 适配器先完成。

## 5. witness 的实际支持范围

只读 `witnesses/runtime_witnesses.py`、`command.json`、`run.log`：已保存的 root 执行记录为 conda lewm Python 3.14.7、returncode 0、6 case PASS、0.09265675488859415s。本代理未运行。

脚本 `90–119` 的实际机制是：`pool.submit()` 正常返回 Future；worker 已写 partial 后失败，稍后 `future.result()` 在 host 报错。它支持 host 返回不等于工作完成、失败保留效果，以及 running cancel 失败。**它没有实测“提交调用自身在提交后 RAISE”**；那仍由上述字段/最小图机制审查约束，不能把二者混成同一个已测 case。

queued-cancellation witness 对该有限 executor 队列验证工作未执行；不推广所有 cancel 都无部分效果。flush/fsync witness 明确 `power_loss_durability_tested=False`。六项 stdlib/OS 证据不是 SCAR 产品/CUDA/跨队列或优化证明，合同 §7 的有限范围保持正确。

## 6. 其余所审源/证据 SHA256

```text
scar/ir/program/model.py 3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1
scar/ir/program/validation.py 04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264
scar/ir/v2/evidence.py dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5
scar/ir/v2/values.py 2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259
scar/ir/v2/correspondence.py 7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5
witnesses/runtime_witnesses.py 149e0fb885b900edafc1b0abd2a6340663de2d81d24a6adef7db86bfda86fb3f
witnesses/command.json 3817d31764288c768127170808d339f839363162fb8a1c2dbd04c9eb0371cbf5
witnesses/run.log 6e5c17cd4080fbb58180f0c13936d36cee89a87122d9f4118f7c3252881c405f
```

`witnesses/` 相对 `artifacts/experiments/b1_call_operands/model_resource_execution_design/`。未覆盖的 source/runtime/family 对应不升级；本报告不替代后续 R1/R2 records、图验证和组件验收。

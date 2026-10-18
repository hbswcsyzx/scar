# R0 补充：外部观察 consumer 与非内存承载

日期：2026-10-18。仅源码/文档只读与本新报告；没有运行实验/测试、修改产品/测试/文档或旧报告。

## 1. 结论与所审版本

**赞同 root 提出的两项修订，均为 R0 应补足的类型范围：**consumer 不限于代码内 Use/Access；Materialization 的承载不能一律要求 StorageRegion/allocation。前次 work/ready 复审的 BOUNDED_PASS 未覆盖这两种泛化边界，本补充明确补上。

本次所读合同仍为 §5 consumer=Use/Access、region/allocation 必填的 DRAFT，SHA256 `fc2b282770ec896ef0988eb535d590cbeb41c0090d42db2b3f164d6e7170a09c`。以下是认可的 Proposed 修正与必须保持的检查，不冒称其已落盘或产品已实现。

## 2. a：外部观察根是合法 consumer，不造源内 reader

**最小反例：**程序写出文件并结束；合同要求指定内容在指定持久化故障模型下成立。程序没有随后读取该文件的 core Use。原 consumer 联合无法表达此观察根，不能为方便表达而捏造一次读文件或 native Operation。

建议最小联合：

```text
ConsumerTarget = CoreUse(UseOccurrence)
               | CoreAccess(AccessOccurrence)
               | ExternalObservation(contract_root: ContractObservationRef,
                                     endpoint: ResourceInstanceID,
                                     point: ExecutionPoint | scoped EvidencePoint)
```

- `ContractObservationRef` 必须准确引用带版本的 ContractID 及该合同中明确的观察 root。ContractID、端点字符串或 EXTERNAL facet 本身不是完整 root。
- 当前 `v2/contracts.py:136–158` 的 ContractDefinition 只有 required_outputs、facets、assumptions、evidence；`ContractFacet.EXTERNAL/RESOURCE` 不包含精确文件 endpoint、内容版本或 durability 条件。新增关联须明确承认这是 typed root binding，不从旧 facet/description 自动恢复。
- ReadyRequirement 中继续保留所需 logical version/materialization、contributions 和 visibility；ExternalObservation 不因位于程序末尾而免除这些匹配。原 root/版本/端点关系未恢复时保留准确 unresolved obligation。
- `point` 标评价范围/观察边界，不声称代码中发生额外 consumer。未观察的故障后恢复结果不是 Observed；声明的 durability 条件与运行 witness 分开。
- “最后一次 close 已返回”既不定义观察根，也不证明 persistence。endpoint lifetime/content/namespace 对应及具体 sync/durability 合同仍需独立支持。

## 3. b：承载判别，不能为文件制造 allocation

**源码事实：**`v2/values.py:150–159` 明确 `Materialization.region: StorageRegionID | None`；`:119–133` 的 StorageRegion 是具有 allocation/shape/strides/dtype 的 strided view。强制文件/NVMe 表示采用这套字段会捏造内存身份与几何。

建议最小联合：

```text
PlacementTarget = StorageBacked(materialization: MaterializationID)
                | EndpointBacked(EndpointPlacementRef)
                | UnresolvedPlacement(materialization: MaterializationID, reason)
EndpointPlacement(materialization: MaterializationID,
                  endpoint: ResourceInstanceID,
                  content_state: canonical State occurrence ref,
                  selector/effect: canonical access/boundary refs,
                  alignment/coverage obligations, evidence)
```

- StorageBacked 从原 Materialization.region→原 StorageRegion.allocation 派生，不另填一份可能矛盾的 allocation/version。
- EndpointPlacement 是物化与实际存储端点/原内容状态的对应；仍从原 Materialization 取 logical ValueVersion。selector/状态只引用原 StateAccess 或准确 INVOKE 边界，不造 file.before/file.after 副本或第二 producer。
- `region=None` **不是 EndpointBacked 的充分条件**：它也可能是尚未恢复的 memory placement 或其他 representation。无 explicit placement 时采用 Unresolved，不强行按 device/representation 字符串猜分支。
- 文件 path 是数据，namespace 绑定是状态，file/storage endpoint 是资源。rename/replace 后同 path 不保证同 endpoint；旧 endpoint 内容也不自动对应新 path 所需观察。
- 不从 backing 标签推出 disjoint。mmap、文件缓冲或共享承载可同时关联 memory 与 file 状态；选择主要 placement 分支不抹掉其真实 alias/同步关系，也不授不同角色互不影响。此处无需实施完整 mmap 协议，只须保留已知对应与未知覆盖义务。
- 若某 Materialization 已有准确 region，却另声明同一表示为不相容端点承载，须报告矛盾或明确解释两种表示之间的关联，不能静默覆盖原 region。

## 4. Ready 的范围继续限定为值与观察目标

Ready 匹配的是“这个内容/表示版本，对这个代码 consumer 或外部观察根，在该域/点满足必要贡献与可见条件”。EndpointBacked 仍执行多贡献 AND、各贡献可选支持 OR，以及内容覆盖/未知 writer 处理。

以下结论保持分开：

- device 顺序可用 ≠ host 可读 ≠ flush 完成 ≠ persistence；外部 root 不使这些域自动互通。
- 文件/内存的目标内容 ready，不证明所有借用已停止、无其他 pending accesses 或 ownership 已结束。
- ResourceOutcome 的 quiescence、取消后的在途访问、allocation/endpoint 回收要求另立义务；不把它们装进 value-specific Ready 的真假位。
- 新内容状态、端点生命周期或 allocation 生命周期变化，使旧支持不能证明新要求；历史工作完成事实可以继续保存。

## 5. 有限验收增量与边界

不要求新 native rule/实验；后续 R2/R3 的手工模型至少补：无源内 reader 的文件观察根；region=None 的已知 endpoint placement；region=None 且未知 placement 保留 unresolved；同 path 不同 endpoint；存储目标 ready 但仍有 pending access 时不授 free。

这些是类型/关联正反例，不是 power-loss、NVMe、mmap 或 GPU 实测。无需新增第二 ProgramGraph、allocation 身份、world 或 producer；无需先完成全部合同 root/denotation 自动恢复，明确声明与 unresolved 对应即可先落实结构。

## 6. 其余源 SHA256

```text
scar/ir/v2/values.py 2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259
scar/ir/v2/contracts.py c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1
scar/ir/program/resources.py 167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f
docs/WHOLE_PROGRAM_MODEL.md ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509
docs/model/RESOURCE_PROTOCOLS.md 5033fd3221d112dcebcbf087788440d7545effc88330dff589ed3ed4cdd482e4
```

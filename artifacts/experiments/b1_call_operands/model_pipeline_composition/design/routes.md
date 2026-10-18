# R3.2：原端口依赖与完整观察账本的组合视图

状态：**Proposed，未实现、未验收**。只读源审；没有运行 pytest、probe、capture、LeWM 或 GPU。

基线 HEAD：`f0dbbd478095b07a684fe4d35ba3b53be20ed17c`。本次读源时另有 root 正在编写的未跟踪 `docs/M1_PIPELINE_COMPOSITION_PLAN.md`；本文不改该文或产品。R3.1 已有声明调用路由不等于完整 R3 或 M0–M2 完成。本报告不重验上一门的 4,951 项全仓结果。

## 1. 决定与实际缺口

1. **不需要另一张规范 producer/Use/state 图或新 wire。** 原 Operation/Value/StateLocation/Region/Resource、动态 occurrence 与实际端口已足够支撑本门派生视图；关系查询只是引用原实体及原端口。
2. 对外可显示“广义 function/action 节点 + 数据边 + 可展开 Region”。动态边的身份是 `(OperationOccurrenceID, UseID)`，不是仅 `ValueID`。`f(x,x)` 的两个原 Use 保留两个端口；同一静态循环节点的不同 visit 不合并。
3. 现有单 read 的 D/P/V 公开面没有覆盖整个程序的 Q/effects/source 分母。新的工作是**组合、对账、暴露缺口**，不是从最终 tensor 回溯后宣布其余操作 dead。
4. 现 `ExecutionIndex._content_context()` 只重新执行 source/Q/D/P/V 外部关联阶段；组合视图若公开资源/work/order，也必须一次性刷新这些阶段，不能借 index 构造时旧的外部图派生结果。保留 canonical flow，不重跑 source compiler。
5. `formal_route.source_use=None` 不是无依赖；多数 completion/resume/protocol 投影本来没有复制 Use。需要完整 typed marker 展示，而非停止在 None。

现有原生产者是 OperationOccurrence、BlockVisit、RegionActivation 等既有 origin。entry、literal、外部观察不伪造为 Compute 节点。原操作的输入集合可以作为**声明的操作级依赖边**展示；没有细粒度依赖摘要时，不进一步声称“每个输出必然依赖全部/某几个输入”。

## 2. Q 适用范围与完整分母

支持 query-only scope：`ContractRef + owner + FactSource`，无 ExecutionModel 新表。`owner` 至少 RunID；如需区分两次调用，应准确允许 RegionActivationID/OperationOccurrenceID，不能把两份调用义务压成 run 级一份。scope 是分析请求，**不是 runtime 适用性证明**。

- 从该原 SemanticGraph Contract 的 `required_outputs`、required facets 建立“期望义务”，再对照原 requirement/root/read。不能由已经连接的 roots 反向定义全部义务。
- facet 只给类别/required 时没有端点目标或基数；保留“目标/基数尚未解释”，不把一行 RequiredEndpoint 当成穷举完成。
- ObservationRequirement 本身没有 owner/run。同 ContractRef 不能让一个 requirement 无条件满足多个调用 scope；从原 Root.anchor、actual、interval 与当前端口派生适用候选，缺对应仍未绑定。
- 全部现有 requirements/roots/reads/operations/source inventories 保留。允许呈现 focus，但不接受 root/writer/relevant-operation 列表来缩小分母。其他合同或 owner 不确定的行列为 outside-scope/attribution-unresolved，不能消失。
- 缺 SemanticGraph、没有 scope、删整行 requirement、requirement 无 root、root 无 read，分别可见。多个 root/read 不择首，也不按“最后一个”替代前面的观察。

现有路径（`observations.py:50,90`；`query.py:150`；`observation_validation.py`）：

| 原实际端点 | 可回查关系 | 不能推导 |
| --- | --- | --- |
| OutputValue | ValueOccurrence → core Value/origin；各原 consumer Use | 精确 required-output slot denotation、物理读取、Mat/Work 必然存在 |
| BoundEndpoint | RequirementBinding → 原静态 requirement/owner/target；anchor/support/interval | tensor producer、文件内容身份、visibility/persist |
| ExternalEndpoint | 原 scoped ResourceTarget + 声明 interval/protocol | allocation/ticket、原生协议已解析 |
| Unresolved | 原 gap/point/source | NONE、没有消费者 |

ContentRead 是观察与具体内容/placement/current-state 的显式连接。scalar/ref 输出没有 ContentRead 时保留原 value/端口与协议缺口，不为补齐图造 Mat 或 Work。

## 3. 直接复用的 ctx 连接；不重演编译器

| 关系 | 现有原数据/索引 | 组合用途与限制 |
| --- | --- | --- |
| 静态定义/Use | `core_operations/core_values/core_uses`；`operation_blocks/block_regions/regions/blocks` | 原 Operation、Value、Use；core_uses 保留原 op 与原 Use |
| 动态值读取 | `occurrences/values/uses[(opocc,UseID)]/results[(origin,ValueID)]` | 原 UseOccurrence → 实际 ValueOccurrence → 原 producer；Unresolved 不删边 |
| 调用与 visit | `visits→segments→activations`，process/run/thread | 区分动态 activation、segment、loop visit；不是静态 Region.parent 的运行解释 |
| 实际 CFG | `incoming[visit]`、`outgoing[opocc]`、原 term `successors[index]` | 保存实际 ControlTransfer、原 successor 与原 argument ordinal；不是按相同类型配对 |
| 当前状态 | `before/after/edges`、`current(point)`、`current_definitions(point)` | 精确 Location 当前 ValueOccurrence/定义 visit；INVOKE/BODY_DRIVE 无 common AFTER |
| 跨调用 | `call_activations_by_caller`、`resolved_call_activations[id]` | 复用原 association、inputs/outputs 与 gaps；无 link 明确 MISSING |
| 内容/来源 | `resolved_denotations/resolved_content_reads/resolved_writes/resolved_produced`；`source_resolutions/inventory_sources/resolved_source_bridges` | D/P/V 原关联；开放多对多缺 join 不当排斥，来源祖先不当全部 writer |
| 资源/工作/顺序 | 原 `requirements/accesses/handles/realizations/submissions/outcomes/retentions`、queue/event/wait 与已校验 order 派生 | 各自保持原 owner/target/current support/profile/point；没有因果证据不按行号/时间/ID 排 HB |

R3.1 inputs 每项已有 `formal_definition/formal/actual_definition(原Use)/actual/actual_value/ordinal`；outputs 已有原 child exit、原 child Use、caller result、实际 transfer/CompletionResult 与 landing formal。保留这些原对象/端口即可。可构建一次 query-local reverse 索引，不能每个值重复全表扫描，更不能存第二份 actuals。

跨调用仅 `DECLARED` 路由：两次完全同 scope/shape 的 child 被恶意互换，不一定能由类型结构识别；source/runtime/value identity 仍未证。不按函数名、源码字符串、相同值或 denotation 猜 child。

## 4. CFG、协议、暂停边的最小 typed 解释

`query.py:182` 的 formal_route 已保存原 transfer/argument；`program/resumption.py:233` 的 saved_actual_use 只返回原 UseID 或原 SavedSlot.use。必须补足展示层的 marker 分支，不改 producer。

| 原 argument/边界 | 可机器派生的展示路径 |
| --- | --- |
| UseID | 原 predecessor Use → 原 UseOccurrence；相同值不同端口仍独立 |
| SavedInput | 原 Suspend.saved[slot].use → resume formal；保存引用不保存旧 shared-world |
| CompletionResult | 实际 INVOKE successor/ordinal 的新 completion 投影；有 CallActivation 时接其真实出口路由；缺 transfer/child link 保留 gap，不假 normal |
| BodyDriveResult | 原 BodyDrive/source outcome/实际 successor 投影；没有动态 body activation 关联时不猜实际 child |
| ResumeInput | 原 ingress/slot 的本次 payload 或 current shared-state；不能连接旧 creation-world/saved state |
| PendingPayload | 原 PendingDispatch.pending Use 与原 port 的 payload 投影；不等于复制当前 state；无可解析 pending definition 就保留协议边界 |
| CleanupRoute | 原 route 的 Uses、当前 state、pending/context 锚与实际 successor；不伪造 Payload 或旧状态快照 |

LocalBindingValue 保持 binding 类型和原读写接口，不变成 object content。未知 marker 明示 unsupported typed route，不能把 None 当 literal/fresh/独立。实际 loop visit/definition 依 `flow.py:145–226` 的 incarnation 处理；不复用上次 visit 的静态同名结果。

## 5. 各类关系必须保持用途

- **Data Use**：读取原 DataValue；没有额外摘要时只说明原操作端口依赖。
- **Reference Use**：传递引用；内容读取要原 StateAccess/current state 或 ContentRead。相同 ref/storage 不证明相同当前内容。
- **State content / State order**：StateAccess READ/READ_WRITE 与 WRITE/STATE_ORDER 分开。WRITE 前态可为 ordering/version 依赖，不自动代表读取旧内容；full_overwrite 不消除历史 IO/异常/Q/alias 义务。
- **Region/control**：定义可展开；实际 activation/call/transfer 单独显示。未走静态分支是未观察，不是死代码。
- **Logical lineage**：VG parent_versions/provenance.inputs 是逻辑前提，不是当前 Mat 的 writer AND 集合。
- **Physical production**：P/V 源候选、actual selector/placement_match、partial contribution、Completed/Ordered 支持独立保留，不把整项状态当整范围成功。
- **Resource/order/lifetime**：原 binding/handle/allocation/retention/queue/event/borrow/drop 各保留身份和事实适用条件。Mat/retention 不证明 ready/canfree；release 不等于 free/flush/persist。
- **Effect/escape**：`effects_complete=False`、OPAQUE/缺采、异常/RNG/external/ordering/逃逸保持未决。行为标签和 `.eval()` 不授纯性。

原 EEG ESCAPES 已在 P `_RELATIONS`（production_query.py:26）；整个组合不能依赖“恰好某个 ContentRead 的 P 查询会遇到它”才记录。没有到 Q root 的 observed op/effect/escape 仍出现在完整 ledger，状态叫 unrouted/unbound，不能叫 dead。访问过的 BlockVisit 内缺 occurrence 是 `operation_unobserved`；根本未访问的 definition/branch 是 unobserved-definition，两者不混。

## 6. 最小公开面（字段名待 root 冻结）

返回一个 detached dict，不给调用者可写 proof，也不变成 Graph 编码字段：

```text
request/scopes               原 query-only Q 适用请求与来源
obligations                  每 scope 的合同输出/facet期望；全部现req/root/read及匹配/未绑
operations/regions           原定义/occurrence/activation/visit，含不在反向路径者
relations                    原Uses、formal routes、calls、state access、resource/order
content                      各原read的D/P/V派生；lineage与current writers分开
unresolved                   未绑/未观察/未知effect/escape/protocol/source归属缺口
inventory                    原全量计数/身份、已扫描/未扫描/待处理与每类完整性分母
budget                       一个总派生预算与costs/truncation；准备成本单列
source_runtime_verified/runtime_identity_verified/value_identity_verified = False
transformation_authorized = False
```

关系项至少含原 opocc/use/value/origin、原 role、原 marker/port/index、适用 source/condition/gap；不能只有两个文字节点名称。未做输出特定依赖证明时明确 `declared-operation-input`，不伪造精确 semantic edge。展开深度可影响展示，不能影响全量 ledger。

## 7. 预算、freshness 和可机械验收边界

一个 fresh composite context 复用 ExternalSnapshots，原 canonical flow 只读；完整重查外部 source/resource/work/order/Q/D/P/V。不要循环调用公开单 read 查询造成重复 replay/hash/deepcopy 和每 read 重置预算。顶层 detach 一次。

总预算 positive exact int；花费至少覆盖 inventory 遍历、req/root/read匹配、Use/origin/formal/call joins、marker展开、effects/resources/order/source扫描、P/V lineage/geometry/formula。已有 G/order budget 从同对象扣除，不按 root/fragment 重置。FK/记录验证、受独立 bytes/lines 限制的工件重放和结果复制成本单列，不能声称全部 CPU 受 4096 限制。

耗尽仍保留全量身份/计数及未访问项；后面的 root/read/action 不能消失。缺 source/capture coverage 不升级 closed-world。返回条件性关系可以有意义地 MATCHED，但 native/runtime/identity/transform 不获授权。

必要通用验收（Proposed，本文未运行）：

1. Q value→compute→两个原 Use→ref+current-state→Mat/work；另一个 required endpoint 完全无 requirement/root，期望账本仍缺项；scalar/ref 输出不造物化。
2. 两次同 callee/不同 activation、`f(x,x)` 双 Use、缺 call link/缺实际 completion transfer；既有端口按序回查，缺项不补 normal。
3. loop 新 visit、INVOKE RAISE/private states、PendingPayload、CleanupRoute、Suspend saved/current ResumeInput、BodyDriveResult 各保留准确 marker；None 不断开成无依赖。
4. 与最终 tensor 无路径的逃逸引用/unknown call/file effect 留 ledger；full overwrite 不能删先前要求观察的副作用。
5. provenance ancestor/copy 的物理 writer 分开；部分成功/失败、later alias overwrite 按原 V 结果保留；绝不祖先全部 AND。
6. 删 requirement/root/read/call/write/work 连接后，原 scope/source/operation 分母不缩小；未绑定义务/候选仍在。
7. 跨 roots 总预算截断仍有 pending/unvisited，外部图修改后新查询重验；返回对象修改不污染 index。

本门不是自动全源码 lowering、原生 runtime 配对恢复、Endpoint read/flush/persist 解析、优化合法性/删除/加速证明。后续 R3.3 的真实通用 load→materialize→compute→consume→write/flush/close 见证仍单独验收。

## 8. 本次源指纹

以下为本次实际读取版本 SHA256；root 后续实施变更不在本报告的审查结论内。

```text
94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a execution/query.py
9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42 execution/call_query.py
79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b execution/call_validation.py
2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 execution/flow.py
e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d execution/validation.py
8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882 execution/observations.py
eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983 execution/observation_validation.py
92afdb38caf716c4187c4a2a9173207c8dc2cc6110a3fd3d83f22852b67ed49a execution/content_validation.py
3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab execution/production_query.py
fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d execution/effects.py
34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2 execution/source_validation.py
3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08 execution/resource_validation.py
cbea6d0b1072c0cf7a3579e07a13a3a9bad808b807c779e66ac76acf43f6ea09 execution/order_validation.py
3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1 program/model.py
584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1 program/queries.py
ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac program/resumption.py
88d2640c7cb23c454f95888ced4130784fd829e8d1d60292a17000278fbe4ef2 program/control.py
c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1 v2/contracts.py
467d92987aafbfa686ce3116f9bbd0e0e6aca437d31c924d420b50cbfe12110f docs/M1_RESOURCE_COMPOSITION_PLAN.md
20e84828158f76544409514cc4856c864b03a792a7a328a40ea09bfad04ebcd7 docs/M1_PIPELINE_COMPOSITION_PLAN.md (当时未跟踪draft)
```

路径中 execution/program/v2 均相对 `scar/ir/`。没有测试运行或实现授权由本文产生。

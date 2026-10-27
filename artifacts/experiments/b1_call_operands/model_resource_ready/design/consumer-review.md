# R2.3 consumer、读取区间与 Q root：独立只读建议

状态：**关系建议，不冻结 record/API，不宣称 R2.3 已实现。** 本报告按 root 授权保存先前审查结论；只读取仓库源码/合同，未运行 Python、pytest、probe、native/GPU 或 LeWM，未编辑产品、tests、docs。

## 1. 现模型已能派生什么

- ProgramGraph/ExecutionModel 是原 Use、StateAccess、ValueOccurrence、实际 completion/formal、scope 与当前 StateVersion 的唯一来源。普通 canonical_effect 回查原 access，INVOKE 沿真实边界，不能额外造 producer 或共同 after state。
- ValueGraph 已给 materialization→ValueVersion、region→allocation 与原 offset/shape/stride/dtype；不能由地址、shape、同名字、旧 ready_event 或同 wrapper 推内容相等。
- R2.2 work_order 给准确 WorkEnd→WorkStart 的**条件**路径，包含原 profile/record/wait；不是已经发生的设备顺序或 Host/Endpoint visibility。
- v2 CorrespondenceGraph 的 definition-instance/source-instance/slot-version 不是 core Use→native input 的完整桥。ValueObservation 的字符串 role、旧 object binding 的 scope 也不能直接变成准确输入槽与读取区间。
- semantic artifact 保存现存 ContractID；ContractDefinition 的 EXTERNAL/ORDERING facet 没有准确 endpoint、selector、观察点或 persistence root。

## 2. 必须连接的三组前置关系

以下列出信息义务，字段名及 exact records 仍待 D/P/V 门收敛。

### D：消费内容及实际读取者

1. 原 UseRef/AccessRef，或明确 Q observation root，连接本次准确 ValueOccurrence/读状态、scoped 原 MaterializationRef、selector 和 basis/source。logical version、region/allocation 从原图派生；独立 expected version 如存在必须对账，不是在 Use 旁随填一个 logical ID 就建立 denotation。
2. basis 需保留实际读取端口、原值发生、对象/物化/观测或有版本协议关系、对应依据与缺口。Data、Reference、State、Binding、Protocol 保持原类别；引用 identity 不永久绑定初始内容。
3. 对实际资源消费 work，精确连接某 ticket、原 read effect、native/provider 实际输入槽和读取区间。同一 WithinOperation 内的多个 work 不能按 host operation 相同自动匹配。跨 activation/native 子事件需准确动态 pairing；缺失不猜最近 owner。
4. 直接 host read 或外部 observation 没有资源 work 时，应保留准确 host/协议读取点或区间；不能为满足一种字段形状制造 ticket。若存在实际 consumer work，必须按上一项连接。
5. 读取区间有真实 last-read 事实可引用它；否则对 work 至少保守覆盖 WorkStart..WorkEnd。enqueue 点的 current support 不能替代实际资源读取期间的内容稳定性。

### Q：真实输出/端点观察根

- 连接现存 ContractID 的精确 semantic artifact、typed output/endpoint 要求、准确 endpoint/selector、真实观察点、协议条件及来源；验证提供图的 digest/schema/byte-size 与原 FK。
- 外部观察使用带真实 run/process scope 的 EvidencePoint 或准确已存在边界，不伪造代码 operation/consumer。只有路径字符串、close 或 EXTERNAL facet 时保留 unresolved root/endpoint，而不是生成 persistence 要求。
- Storage-backed 沿原 region/allocation；Endpoint-backed 需要显式 ResourceTarget、selector/选择状态和 placement 对应。region=None 不推出文件/NVMe，也不造假内存 allocation。

### P/V：贡献、有效期与可见域

- 必要贡献必须从准确源 endpoint/work/effect/selector 与可核对 writer inventory/覆盖边界派生，不能让调用方删小 required 集合。血缘前提、当前生产贡献与潜在 invalidator 分开；同 writer 的多条来源不重复计入 AND。
- 每个必要贡献可有匹配的 CompletedVisibility 或 OrderedVisibility 替代支持，再逐贡献 AND。不同内容、placement、consumer、domain 不独立 union 后交叉配对。FAILED/CANCELLED/short-write 的实际部分 frontier 不扩大为 whole。
- Host、Queue、Endpoint、Unresolved 是判别域。Queue 需准确 consumer work/queue/context 和到 Start 的 order；Host 另需 process/thread/address-space 建立依据；Endpoint 分清 buffer/flush/persistence 条件。
- 有效性覆盖建立支持至实际读取区间，核对 current state、写入/alias、allocation incarnation/retirement、端点选择和源覆盖。**retention 是借用/生命周期关系，不保证内容稳定**；两个端点状态一致也不排除中间覆写。
- 历史证据保留；新内容、分配、run/process/domain 重新匹配。Ready 可服务多个匹配消费者，不是一次性 permit；free 仍另有全部 pending-access/ownership/quiescence 义务。

## 3. 机械校验与仍需外部依据的边界

可机械检查准确 artifact/FK、原端口归属与有序输入槽、实际 completion、动态 scope/current StateVersion、原物化版本和 backing、selector 几何、已知 order 路径及声明间矛盾。
core Footprint 的计量单位不能直接当 StorageRegion bytes；UNKNOWN selector 不按 whole/disjoint。未知 alias、截窗、graph break、未匹配 native input 必须有具体 gap。

真实 denotation、native 输入/输出匹配、物理读区间、完整 writer coverage 和 visibility 协议适用仍依赖准确条件声明/外部证据。ProviderFactReference 只是 locator；COMPLETE/PROVEN 名称不能补齐对应。保留条件模型即可推进，不要求先实现完整自动前端，也不把新 enum 当自动支持。

## 4. 六个必须保留的反例

1. 同 wrapper/shape 已换内容版本，或地址复用为新 allocation：旧证据不满足新需求。
2. 一个 host call 提交两个 native work：同 operation 不能选定实际读取输入的 ticket。
3. producer-end→consumer-end 或 queue order：不能替代 consumer-start，更不能授 host read。
4. EXTERNAL facet＋路径＋flush：没有准确 Q root/协议，不能冒认持久化观察。
5. allocation/handle 仍保留，但 consumer 读取期间有并发覆写：retention 不使内容稳定。
6. FAILED/CANCELLED 仅产生部分区域或少一个 writer：正确 order 不能填补缺失贡献。

## 5. 实际读取源的 SHA256

下列为读过的相关文件版本；部分读取限上述相关章节，不声称整文件产品独立验收。

| 文件 | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` | `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729` |
| `scar/ir/execution/query.py`（本轮相关查询及 G 入口） | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/resources.py` | `657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d` |
| `scar/ir/v2/contracts.py` | `c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/correspondence.py` | `7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5` |
| `scar/ir/v2/evidence.py` | `dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5` |
| `scar/ir/v2/semantic.py` | `9d0af8a2b4a868df00388ccb910cdabdc93066aad7ff0e593d1c8d0e969885ab` |

共享 geometry 查询只是 D/P 的前置算法，不关闭本报告关系、完整 R2.3/R2/R3 或完整 M0–M2。

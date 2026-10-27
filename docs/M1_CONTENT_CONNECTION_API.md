# R2.3-D API：指代、读取和观察

本接口落实[计划](M1_CONTENT_CONNECTION_PLAN.md)。这是声明关系及其结构校验，
不宣称已经自动从真实程序恢复这些关系。生产集合 P、区间有效性/visibility V
仍按[R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)独立实施。

## 1. 原事实不搬家

ProgramGraph 的 Operation/Value/Use/StateAccess、ExecutionModel 的动态 incarnation、
实际 CFG/completion、ValueGraph 的版本/物化/分配、EEG 的 runtime 记录和 Q 合同
保留各自规范来源。新增表只引用这些端点，不复制 producer、后态或另一套调用图。
同一静态 Use 在不同 invocation 上有不同 UseOccurrence；不能拿静态位置代替动态身份。

## 2. 五组连接

| 表 | 必要字段及含义 |
| --- | --- |
| `denotations` | `value` 指准确 ValueOccurrence。DataValue → DataIdentity(VersionRef)；ReferenceValue → ObjectIdentity(ObjectRef)。`basis` 指 source row/native slot 或明确缺口；`source` 保留来源。 |
| `work_evidence_bindings` | `ticket` 对应精确 EEG artifact 中的 `instance`。同 host 操作的两个 work 不自动共用对应。允许保留多对多关系；关联不是 native pairing 证明。 |
| `observation_requirements` | 精确 SemanticGraph 的 ContractRef；target 是准确 required output slot，或显式 core endpoint requirement/Unresolved + 必需 facet；protocol/source 只声明关联。 |
| `observation_roots` | requirement 的实际 OutputValue、BoundEndpoint、ExternalEndpoint 或 Unresolved；interval、anchor、support 说明观察区间和已记录当前状态。没有实际 work 就不创建 ticket。 |
| `content_reads` | consumer、placement、原 effect/明确缺口、anchor/support、source basis；将“传引用”与“读内容”分开。 |

StateVersionValue 的 location/version、LocalBindingValue 的 slot/boundness 和
ProtocolValue 的协议类型由原图派生，不增加 denotation rows。一个原值只登记一份
指代声明，额外的读取来源保留在对应 ContentRead/EEG 关系中。

## 3. 身份与来源

VersionRef 是 `(exact ValueGraph artifact, ValueVersionID)`，不从 storage 地址派生。
ObjectRef 指 ValueGraph bindings 或 EEG object registry 中的对象；对象身份不永久
等于某个版本。所有 artifact 身份使用 hash/schema/size，URI 只是定位信息。

EvidenceEdgeRef/EvidenceObservationRef 必须在提供的精确 EEG artifact 中存在。
读取边必须是 OBSERVED_READ，已知版本、物化、对象、native actual 或 process 矛盾拒绝。
ValueObservation.role 是字符串，不能据此猜 operand 0；EEG 无槽序号时显式保留
`content_exact_port_unresolved`。FactReference 本身也不能关闭这个缺口。

operation/work binding 是开放的多对多关系，没有 COMPLETE/exclusivity 合同。
缺 exact pair 一律是缺口；“已有 A、没登记 B”不能证明 B 不属于这次操作或 work。
查询分别返回 source instance、实际匹配的 correspondence rows 和 missing-join gap，
不按相同 host 或 EEG parent 自动补 pair。后续 P/V 必须保留这项未闭合义务。
已匹配 host occurrence 的已知 process ID 必须一致；work 的 process 从 Direct
线程或实际 queue 的 ProcessRealm 派生，未知执行域保留缺口，不用 enclosing caller
代替执行 process。相等 PID 仍不能证明 run incarnation 或 native 对应。

NativeInputRef 使用 boundary 的 native position 和实际 initial entry visit；
NativeOutputRef 使用 native position 和实际 Return/Raise occurrence。position
沿原 P1 signature/port 解析，不是 core operand index。错误 entry、completion 或
actual value incarnation 拒绝。声明边界与实际内核/读取工作是否对应仍未验证。

## 4. 三类消费者与 placement

- HostConsumer：准确 UseRef/AccessRef + ProtocolInterval。已知区间 run/process、
  host 顺序必须与原操作一致；跨 native clock 的未解析对应保留 gap。
- ResourceConsumer：准确原端口、WholeWorkRead(ticket) 或 NativeWorkRead(ticket,
  interval)、native input/EEG edge/Unresolved。WholeWorkRead 派生 WorkStart..WorkEnd。
  较窄声明区间不能在缺 native 证据时缩短保守稳定性义务。
- ObservationConsumer：准确 ObservationRootID，不伪造 Python Use 或工作 ticket。

StorageContent 引原 MaterializationRef 与可选 RegionRef；None selector 仅表示该
物化原 region 的整体。显式 selector 必须在同 artifact/同 allocation，且在几何预算
内确认是该 region 子集；未知几何不当作空集或 whole。

EndpointContent 引无 storage region 的原物化、显式 ResourceTarget 和 selector。
selector 可是原 UseRef/AccessRef、协议 selector 或 Unresolved；不会把 mat.region=None
变成 CPU/NVMe allocation。协议 selector 未解析时保留缺口。相同 allocation artifact
只有 URI 不同时不误判为另一个目标。

## 5. 状态、Q 与区间

Reference 的内容读取需要原读取 StateAccess/已验证 InvokeBoundaryStateEffect 或
显式 Unresolved。StateAccess 的 before 必须包含在 support，anchor 必须是原读取
操作 BEFORE 的准确当前 incarnation。WRITE-only access 不能充当 READ。
INVOKE effect 继续引用现存实际 completion/formal，不新造 after state。

这些检查只建立本次 host anchor 的状态关系；Reference/current state 与物化版本的
对应、读取区间内稳定性、alias writer、allocation lifetime、visibility 仍单列缺口。

Q 的 required output 必须属于该合同。显式 endpoint facet 必须 required=True，
但 facet 名称不自动生成端点。已知 core endpoint 必须走实际 BoundEndpoint；
ExternalEndpoint 不绕过 binding owner/realm。观察可以晚于绑定 owner；跨 activation
传递保留缺口，已知 run/process/当前 state 矛盾拒绝。close 不等于 flush/durability。

## 6. Codec、查询与费用

五个新表触发 execution schema v4；空表模型维持既有最小 v1/v2/v3 capability。
旧 schema 字段/tag vocabulary/字节隔离，v4 内容不能降级隐去。ProgramGraph schema
不变。旧 golden 从不可变旧提交的独立源码生成，不能由新版编码器自证兼容。

`ExecutionIndex(..., value_graphs=..., evidence_graphs=..., semantic_graphs=...)`：

- `denotation(value_occurrence)`：原类型/definition、scoped 指代或原状态/绑定/协议。
- `content_read(id)`：原端口/effect、准确 consumer、物化及 selector、来源解析、
  保守 work interval 和逐项缺口。resource 的 `interval` 始终是保守 Start..End；
  未验证的较窄声明单列 `declared_native_interval`，不能缩小该义务。
- `observation_root(id)`：原合同要求与实际值/端点。

每次内容查询重新验证调用方可变外部图，严格 decode 成 detached snapshot，查询内
共享 resolver；返回记录也 deepcopy。原 canonical flow 复用，不重做静态全图验证。
快照校验成本独立于 selector 几何预算。URI 不读取、provider 不执行；缺图是 gap，
明确提供但错误的 family/hash/schema/size/FK 是 issue。

查询输出 `source_runtime_verified=False`、`transformation_authorized=False`。
Implemented/Verified 仅表示上述声明接口与校验已实现/验收；不授 ready/free，不代表
LeWM 自动建模、自动化简或已有加速。

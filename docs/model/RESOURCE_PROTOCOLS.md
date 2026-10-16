# Resource、状态与库边界协议

日期：2026-10-16。状态：**第一阶段模型规格；不是自动建图或优化验收结果。**

本文件细化 [WHOLE_PROGRAM_MODEL.md](../WHOLE_PROGRAM_MODEL.md) 的资源、状态、
库边界和异步完成接口。所有规则均依据操作协议，不依据 workload、变量名或类名。
文件、Tensor、帧和编码器结果共享 Value/State/Resource 基础结构，没有业务节点类型。

## 1. 规范引用、端口和完成

下列 schema 中 `UseRef`、`ResultRef`、`StateRef`、`ControlEdgeRef` 都引用完整模型
中的规范记录。`StateRef` 只引用已有 `StateVersionValue`；动态记录通过 occurrence
对应获得实际版本。协议表不是第二套可独立修改的 def-use、控制或 before/after world。

```text
ProtocolBinding {
  operation: OperationID,
  specification: (protocol_kind, revision, language/library_build),
  inputs: ordered (role, UseRef)*,
  state_domains: ordered (role, LocationRef, access_mode, footprint_expression)*,
  resources: ordered (role, RequirementID | ResourceDefinitionID)*,
  normal: (result_signature, StateRef*, ControlEdgeRef),
  exceptional: (ExceptionPacketSignature, StateRef*, ControlEdgeRef),
  resource_work: WorkSubmissionSignature*,
  aliases_and_ownership: AliasOwnershipRule*,
  ordering: OrderingRule*,
  precision: per_domain_and_port_completeness
}
```

`state_domains` 声明所需位置及访问方式，实际前后版本只由规范 state use/result/edge
给出；状态不变化时可以引用同一版本。一次操作可有多种效果及多个退出，不强迫
compute、copy、I/O 等标签互斥。结果错误与外部工作错误是不同端口：

```text
HostOutcome     = Returned(payload) | Threw(ExceptionPacket)
ResourceOutcome = Completed(WorkTicketID)
                | Failed(WorkTicketID, diagnostic, partial_effect_evidence)
                | Cancelled(WorkTicketID, protocol_specific_result)
```

Host Threw 不保证“未提交/未写入”；如果失败前已创建、提交、截断或写入，实际
post-state 与已提交工作仍从异常边传出。未完成、未观测完成和确定不完成分别记录。
没有规则支持时，Cancel 也不表示无部分结果或可以立刻释放承载空间。

### 1.1 组合必须满足的不变量

1. 每个数据实参来自有序 Use，而不是版本集合；每个 state 实参来自该路径当前
   StateRef，异常出口不能回接操作前的旧状态假装回滚。
2. 子协议接口接入同一 Location/Resource 身份；未知 selector 与细位置之间的
   覆盖/alias 关系不能因分表或不同 ID 消失。
3. Region 的接口是内部规范边的投影：读写、alias、escape、异常及未完成工作都
   要穿出边界，不能只汇总最终 Tensor。
4. 内容依赖、RAW/WAR/WAW 顺序、外部交互历史、生命周期和 ready 是不同关系；
   杀死旧内容不自动杀死旧操作的其他效果。
5. `precision` 描述恢复程度；它不改变协议的操作类型。接口全覆盖、内部已展开、
   依赖已闭合分别验收。未解析的 native 实现不能以空效果集合获得化简权限。

## 2. 资源定义、要求、实例和 handle

```text
ResourceDefinition {
  id: ResourceDefinitionID, kind,
  origin: ExternalRole | CreationOperation(OperationID) | SelectionExpression(UseRef),
  identity_relations: ResourceRelation*
}
ResourceRequirement {
  id: RequirementID, binding_owner: OperationID | RegionID,
  user_port: OperationOrRegionPortRef, kind,
  constraints: TypedConstraint*, relations_to_other_requirements: TypedRelation*
}
ResourceInstance {
  id: ResourceInstanceID, kind, execution_scope, lifetime_generation,
  parent_or_shared_resource_relations: ResourceRelation*, identity_evidence
}
ResourceRealization {
  definition_occurrence, instance: ResourceInstanceID, scope, evidence
}
RequirementBinding {
  requirement: RequirementID,
  binding_scope: OperationOccurrence | RegionActivationEntry,
  instance: ResourceInstanceID,
  satisfied_constraint_evidence
}
HandleBinding {
  reference_or_descriptor_occurrence, handle_lifetime_generation,
  resource: ResourceDefinitionID | ResourceInstanceID,
  rights, ownership, validity_interval, evidence
}
```

Definition 是可共同引用的程序资源角色，不是一次运行的实际实体；Requirement 是
使用处的约束，不是 handle 的 referent。一个创建定义重复执行可产生多个实例；
Operation owner 的 requirement 按该次 operation occurrence 绑定，不同次执行可由
不同实例满足；Region owner 的 requirement 是该 activation 入口的隐式资源端口，
其内部使用引用该次入口绑定，不能在每个内部 use 上随意改绑。新的 activation 可以
有不同实例。外部实例无须伪造源内创建操作。
容量、队列、ownership、open/closed 等可变性质通过 StateLocation 版本化，不能
以替换 ResourceInstanceID 来掩盖状态更新。

约束至少能表达类别、设备/context、可读写能力、容量、地址空间、共享/独占及
与其他资源的同一/不同/可达关系。未满足约束不生成一个虚构“已就绪”的实例。
字符串 selector 可保留为显示信息，不能替代这些有类型的关系。

约束为版本化判别联合，不是任意字符串或未检查的 dict：

```text
TypedConstraint = Device(DeviceDefinitionRef)
                | Context(ContextDefinitionRef)
                | Access(RightSet)
                | Capacity(dimension: Bytes|Slots|Threads, lower_bound: ValueExpr)
                | AddressSpace(AddressSpaceDefinitionRef)
                | Ownership(Shared|Exclusive|Borrowed)
TypedRelation   = SameResource(other_requirement)
                | DistinctResource(other_requirement)
                | ParentResource(other_requirement)
                | CanAccess(other_requirement, RightSet)
```

动态约束表达式的依赖仍引用规范 Uses/StateRefs。约束是否满足必须按对应 occurrence
求证；资源 Definition 中的选择表达也保留真实求值及可能异常，不能当无成本标签。

### 2.1 关系的 occurrence scope

SAME、DISTINCT、严格 CHILD 等关系必须明确比较哪些绑定；不能对两个静态
RequirementID 无条件传播运行时相等。相同 Operation owner 的关系比较同一次
operation occurrence 的绑定；相同 Region owner 的关系比较同一次 activation
入口的绑定。跨 owner、跨 activation 或跨循环 visit 的关系需要显式的 occurrence
pairing 及可验证对应，不能凭共同代码、词法嵌套或相同 ID 猜配。

同 scope 的 SAME 构成等价闭包；闭包内 kind/role 必须兼容。DISTINCT 和严格 CHILD
不能落在同一个 SAME 分量；严格 CHILD 关系无环。CHILD+DISTINCT 可以同时成立。
这些是接口约束的一致性规则，不是已有动态实例满足约束的证明。

### 2.2 ownership 与生命周期端口

```text
Acquire / Allocate -> owned or shared handle + resource/location state
Borrow             -> access permission + lifetime/ordering obligation
Retain / Release   -> ownership state transition
TransferOwnership  -> outgoing and incoming owner relation
Escape             -> boundary + affected locations/resources + observation coverage
Destroy / Free     -> lifecycle transition, subject to outstanding-use obligations
```

ownership 是关系及状态，不等同 Python refcount。释放 Python 引用不证明 storage
立即释放；析构/weakref/清理可能继续执行操作。CPU allocator 地址再用、fd 再用和
stream wrapper 再建都需独立生命周期对应。共享关系未建立时也不能反向声称不共享。

### 2.3 当前四张资源表的有限实现

当前 `ProgramGraph.resources/resource_requirements/resource_uses/resource_locations`
已接入静态定义、要求、规范 Operation/Use 的引用及规范 Location 的资源 owner
关系。validator 只检查接口 well-formedness；同 owner 关系按上述 scope 做 SAME
闭包、kind/role 和严格 CHILD/DISTINCT 一致性检查。跨 owner pairing 尚未实现，
当前明确拒绝这类未定 scope 的关系；这是该子组件的边界，不是完整模型的永久限制。

这四表没有动态 ResourceInstance、RequirementBinding/HandleBinding 观测、运行时
约束满足、resource availability、WorkTicket/Ready 证明；静态 `ResourceUse.definition`
不是这些事实的替代。设备/context/rights 等完整约束、库协议自动恢复及整个 M1
验收也不能从该子组件通过推导出来。旧 wire 1/2/3 按原能力解释，新资源表使用
明确版本化的 v4；不能将 v4 标签解释为完整资源生命周期已经实现。

## 3. 文件状态不是一个 `path -> bytes`

| 位置/实体 | 规范职责及共享关系 |
| --- | --- |
| namespace Location | `(filesystem/directory identity, name)` 到文件实体的绑定；rename/unlink 改变绑定。 |
| file Resource | 文件实体身份；硬链接路径可指同一实体；数字 inode 需 filesystem 与生命周期依据。 |
| file content/metadata Location | 内容、长度、必要 metadata 与其版本；可由图外写入改变。 |
| open-file-description Resource | 一次打开所得共享访问状态的承载；offset/status 等独立版本化。 |
| descriptor/handle | 带代次和访问权限的引用；dup 可共享 open-file-description；独立 open 可有独立 offset。 |
| Python buffer/wrapper Location | 缓冲区、未写数据、read-ahead、closed 等状态；不是文件内容本身。 |
| text adapter Location | codec、decoder/encoder、newline 与位置 cookie；不把 text tell 当一般 byte offset。 |

外部写入/rename、mmap 与多 handle 共享关系进入 alias/coverage；路径字符串相等
不足以证明内容、文件实体或权限状态未变。以下基本 read/write 协议以二进制接口
为准，文本、压缩、网络文件系统和特殊设备通过各自版本化 adapter 展开。

以下位置 schema 将具体 selector 绑定规范 LocationID；它们不是可独立改写的状态
副本。StateRef 的类型必须匹配其 LocationID，位置由动态引用决定时附 occurrence
correspondence：

```text
NamespaceEntry(fs_resource, directory_resource, name_value) -> FileReferenceState
FileContent(file_resource, byte_footprint)                  -> ByteContentState
FileMetadata(file_resource, field_selector)                 -> MetadataState
OpenPosition(open_file_description_resource)                -> OffsetState
OpenFlags(open_file_description_resource)                   -> AccessStatusState
HandleLifecycle(handle_identity_with_generation)            -> OpenClosedState
WrapperBuffer(wrapper_object, buffer_role)                  -> BufferedDataState
CodecState(wrapper_or_encoder_object, codec_state_selector)  -> CodecStateValue
```

coarse 文件系统域覆盖其内的 namespace/file/handle 状态；无法恢复准确 file identity
时不能把这些位置声明为两两无关。buffer、encoder 与普通 object location 通过明确
owner/selector 共用身份，避免“库状态表”和“对象状态表”各记一份同一内存。

### 3.1 Resolve/Open

- **输入**：path 或 dir-handle/name、mode、flags、编码/缓冲配置的有序 Uses。
- **状态**：读取 namespace、权限及所需环境；产生 handle/open-file-description 和
  wrapper 状态；create/truncate/append 可能更新 namespace、文件长度或 metadata。
- **资源**：filesystem/file 实体、open-file-description、handle；保留共享对应。
- **结果**：打开的引用与模式/rights 关系；不产生“文件 bytes 已加载”的结果。
- **异常/完成**：Host Returned/Threw，失败路径保留已发生创建/截断或 wrapper
  初始化的部分效果。是否发生、是否清理由具体层/系统协议决定，不一概回滚。
- **alias/ownership/顺序**：handle 持有相应打开资源；后续访问需 live/rights；
  open 在首个 read/write 之前；模式及 namespace 访问自身也是可观察依赖。

### 3.2 Read/ReadInto/Seek

- **输入**：live handle、请求长度；readinto 另有 destination 引用/footprint；seek
  另有 position/whence 或文本 cookie。
- **状态**：读文件内容/metadata、open-file-description、wrapper buffer；返回 n
  个 bytes 时按真实协议推进 offset/buffer，允许 short read/EOF。read-ahead 可让
  底层 offset 与用户可见位置不同；readinto 同时更新 destination 状态版本。
- **资源/结果**：打开资源与承载内存；read 新结果与文件是否共享由普通 copy、
  mmap 或 native 协议决定；readinto 返回长度并保留被更新的目的对象身份。
- **异常/完成**：普通同步 read 的 host 完成不等于持久化；异常可带已推进位置、
  已填入的目的区域或 buffer 状态，接口不能默认为“零字节且无效果”。
- **alias/ownership/顺序**：读到的数据依赖当前内容版本；共享 offset 的 handles
  互相影响；readinto 写与后续 consumer、外部 writer 之间保留冲突和顺序。

### 3.3 Write

- **输入**：live writable handle、数据引用/实际区域、请求数量与必要模式。
- **状态**：读源内容；更新 wrapper buffer、open-file-description、文件内容/长度/
  metadata 及外部交互历史中相应部分。buffered write 的 host 返回不代表 bytes
  已全部进入内核；unbuffered write 可以返回短长度。
- **资源/结果**：打开资源与源区域；结果是协议规定的计数/ack，不是持久化证明。
- **异常/完成**：可能已经输出前缀或改变 offset；异常边带实际或保守的部分更新
  范围。操作中断后重试不是无条件幂等，不能自动重复追加整块。
- **alias/ownership/顺序**：同步消费、复制进 buffer 或异步借用的源生命周期依
  协议区分；append/共享 offset 与其他 writer 的关系由具体 API 保证，不能
  由 SCAR 凭时间戳推导全块原子性。先前外部输出不是后写覆盖就自动 dead。

### 3.4 Flush/Sync/Close

- **输入**：handle/wrapper、具体 flush/sync/close 种类与必要标志。
- **状态**：flush 消费待输出 buffer，更新底层状态；sync 消费对应系统同步协议；
  close 更新 wrapper/handle 及打开资源的 ownership/lifecycle，可能先 flush。
- **资源/结果**：同一 file/open-file-description/handle；成功通常返回 ack/None。
- **异常/完成**：flush 失败可已有部分外部写；close 失败后的 closed/仍打开状态
  依 wrapper/OS 协议描述，不能通用假设其仍可用或盲目重试已复用的 fd。
- **alias/ownership/顺序**：flush 不是 fsync，close 不是断电持久化。持久化合同
  需具体文件系统/系统调用及必要目录同步规则。close 不等于删除文件；共享资源
  是否终止取剩余 ownership。错误传播仍需走 with/finally 的 pending completion。

## 4. 从读取到模型状态的库协议

### 4.1 Deserialize/Decode

- **输入**：bytes、file-like 或映射引用；format/options、schema、decoder/loader
  callable、位置映射等有序 Uses。
- **状态**：读输入版本及必要位置/库配置；维护 parser/memo/decoder 状态；允许
  创建对象、storage 和共享引用。实际 callback/custom reducer 的状态效果穿出。
- **资源**：输入文件/映射/内存、输出 allocations；mmap/lazy decode 可以保留文件
  或映射依赖，不强行简化成一次 eager `bytes -> Tensor`。
- **结果**：对象图与内容/表示版本；共享 storage、view 和对象 memo 关系保留。
- **异常/完成**：已创建对象、已消耗输入、callback 效果及部分 allocations 从异常
  状态传出；是否释放由相应清理协议决定，不假定事务性。
- **alias/ownership/顺序**：源码中的 pickle/custom loader 不是默认纯函数；模式
  限制、allowlist 和实际实现版本是协议输入。内部未展开不妨碍表达完整边界，
  但内部依赖未闭合时不能删除 import、执行或回调。

### 4.2 Install/Update Model State

- **输入**：module/object 引用、输入 mapping/对象图、keys/strict/assignment 等配置。
- **状态**：读取对象结构、hooks、目标参数/buffer 及载入配置；更新相应内容、
  引用槽、metadata、hook/extra-state 及所需 autograd/optimizer 关系。
- **资源**：现有或新 allocation；必要 copy/设备工作按第 5 节分解。
- **结果**：协议规定的 module/状态报告或 ack，连同新的规范 StateRefs。
- **异常/完成**：逐项安装可先写前面的参数再因后项形状/缺失失败，不能假定原子
  回滚；hook/自定义 setter 的异常与效果同样保留。
- **alias/ownership/顺序**：copy-into 与 replace-reference 是不同子协议；前者可
  保留对象/alias，后者会改变既有持有者所见关系。参数同值不证明其引用、梯度图、
  optimizer binding 或 buffer 状态可替换。不能用 `.eval()` 推导无状态/无梯度。

## 5. 分配、物化、设备工作与 compute

### 5.1 Allocate/View/Copy/Convert

- **输入**：规格、allocator/device/layout 参数，或源引用及其当前内容/selector。
- **状态**：allocator/pool/ownership、源读状态、目的写状态、当前设备/stream 选择、
  所需 autograd/mode；写 footprint 及重叠关系显式保留。
- **资源/结果**：Allocate 产生新 allocation 生命周期与引用；View 产生区域描述
  与共享 allocation；Copy/Convert 依协议返回同对象或新引用及物化关系。
- **异常/异步完成**：分配、转换、提交或后续设备执行可分别失败；成功 host 返回
  可以只带 WorkTicket，尚未证明目的表示对当前 consumer 可用。
- **alias/ownership/顺序**：同设备 `.to()` 可直接返回原引用；`copy=True` 可强制
  新副本；zero-stride expand 不分配完整结果。cast 一般产生新逻辑值；精确搬运
  可保持载荷版本但不抹去设备、alias、ownership 或 ready 的差异。

### 5.2 WorkTicket、event generation 与消费条件

```text
WorkSubmission {
  ticket: WorkTicketID, enqueue_occurrence,
  executor: ResourceInstanceID, queue: ResourceInstanceID,
  queue_generation, ordered_dependencies,
  accesses: (StateRef, footprint, read/write/retain_permission)*,
  output_materializations: MaterializationID*
}
ReadyRequirement {
  consumer_occurrence, required_work_or_access,
  materialization_version, allocation_generation, visibility_domain
}
ReadyEvidence {
  completed_or_ordered_work_generation, event_generation?,
  materialization_version, allocation_generation,
  visibility_domain, establishing_operation_or_rule, evidence_refs
}
```

WorkSubmission 引用规范 state accesses，不生成第二套内存版本。工作身份、queue
身份、queue/event generation 和内容/分配版本均需对应；同名 event、同 pointer、
时间戳较早都不充分。ReadyRequirement 是 consumer-specific 条件；ReadyEvidence
可复用，但表示被覆盖或分配生命周期结束后，旧证据不再证明新内容可用。

### 5.3 Enqueue/RecordEvent/Wait/Query/Synchronize

- **输入**：operation 数据/引用及当前状态，或 stream/event/工作引用；event record
  产生明确代次，wait 消费实际指向的代次。
- **状态**：读写队列、event、allocator 使用关系、相关位置与可见性；被提交工作
  的源借用/目的写入延续至相应完成，不能由 host 局部变量离开直接结束。
- **资源/结果**：enqueue 返回工作及结果引用；record 返回 marker；query 返回对应
  范围的布尔结果；wait/synchronize 返回相应 ack。它们不是同一完成操作。
- **异常/异步完成**：提交成功与资源工作 Completed/Failed 分开；错误可在后续
  host 操作上报告，其关联依真实库/运行证据，不仅按报错代码行归因。
- **alias/ownership/顺序**：同 stream 的合法后续操作可由 queue 顺序满足依赖，
  **不要求先做 CPU synchronize**。跨 stream wait 建立后续提交依赖，通常不等待
  CPU；host 读取需对应 host 可见条件。`wait_stream` 只覆盖调用时的相应前缀，
  不是未来对方 stream 所有工作。`record_stream` 是 allocator 生命周期协议，
  不是 producer/consumer 数据同步；需同时检查正确的等待与承载复用规则。

### 5.4 Compute / Module Invocation

- **输入**：实际 callable/dispatch、全部有序数据 Uses、环境、参数/buffer 的当前
  状态、hooks、RNG 及必要模式；module 调用是可递归展开 Region，不默认原子纯算子。
- **状态**：按实际 operator/module 协议读取/更新；in-place、buffer、自定义对象、
  Python 状态、autograd 与随机状态分开。未知 native 的必要 coarse domains 保留。
- **资源/结果**：CPU/GPU/stream、读写 allocations、临时 workspace；结果包括数据/
  引用、状态和可能的设备工作，不把 enqueue 时间当 kernel 完成。
- **异常/异步完成**：参数检查、hook、执行中与资源工作失败分别有出口；先前写入、
  RNG 推进和已提交工作从异常接口保留。空输出或异常不等于此前工作可删除。
- **alias/ownership/顺序**：输出可 alias 输入/参数，或持有 saved tensors/梯度图；
  `.eval()` 不封闭以上依赖。内容一致不足以共享可变输出；未来 backward/梯度
  consumer 仍在观察合同内时不能删除其所需关系。

## 6. 编码、序列化与保存

编码器/压缩器/serializer 是普通协议实例：对象引用、内部 StateLocation、资源
要求和有序输入输出；不新增“视频语义节点”。Tensor 保存和视频保存使用同样的
表示变换、缓冲、写出与清理结构，具体协议、顺序与失败合同可不同。

### 6.1 Create/Feed/Drain/Finalize Encoder

- **输入**：编码配置/codec callable、输入数据或帧版本、序号/timestamp 及输出 sink。
- **状态**：创建实例状态；feed 读当前输入并更新内部历史/缓冲；可返回零个、一个
  或多个输出块。drain/finalize 消费剩余状态并更新 finalized/closed 状态。
- **资源/结果**：CPU/GPU 编码资源、workspace、sink 与必要文件；输出 bytes/块或
  已提交工作。一个输入对应一个输出并非一般保证，延迟和重排必须有协议关系。
- **异常/异步完成**：已消费输入、已输出块、内部部分推进或已提交资源工作保留；
  finalize 可产生必须写出的尾部内容，也可失败。关闭 sink 不默认为成功 finalize。
- **alias/ownership/顺序**：feed 是同步复制还是保留输入借用依协议定义；缓存不得
  越过其输入生命周期。输入顺序/内部历史依赖不能按相同 shape 或重复 feed 标签
  消除；最终文件观察包括已提交的全部必要块及清理/错误路径。

### 6.2 Serialize/Save Region

- **输入**：对象图/逻辑数据版本、format/options、目标 path 或既有 sink、回调环境。
- **状态**：读源对象/alias/metadata 与 serializer 状态；执行获取 sink、编码和
  write/flush/close 的各自前后状态；对 caller 提供的 sink 是否关闭依明确协议。
- **资源/结果**：输出 allocation/块、文件/打开资源；save 的 host ack 不自动表示
  可恢复的完整格式或持久化。
- **异常/完成**：失败可留下截断文件、合法前缀、不完整尾部或已执行 callback；
  将“保存”当纯值计算会丢失这些状态。原子替换只能来自实际 temporary/rename/
  sync 协议，不能因 API 名是 save 自行补造。
- **alias/ownership/顺序**：格式中的共享对象与 storage 关系由 serializer 保留或
  明确转换；文件生命周期、借用源及外部顺序跨整个 Region 组合；不能只比较读回
  的最终 Tensor 就证明保存操作等价。

## 7. RNG、mode 与 autograd 是普通的必要状态

```text
RNGLocation      = generator identity + device/context + state/version
ModeLocation     = owner_scope(thread/context/module) + mode kind + state/version
AutogradLocation = object/graph identity + saved data/lifetime/gradient relation
```

随机操作消费其实际 generator 状态并产生下一状态；相同 seed、输入或输出样本
不使两次调用可互换。显式 generator 与设备默认 generator 分开；随机失败前是否
推进需按真实协议记录，不能一概重置。重播同值还须保持后续 RNG 状态与合同。

训练标志、grad mode、inference mode、autocast、current device/stream 具有各自
owner/scope；不能统一成全局 `inference=True`。基类 `.eval()` 委托 `train(False)`，
自定义 override 仍要 dispatch；它不关闭 autograd。`no_grad` 的反向求导模式不
等同关闭 forward-mode AD，也有 factory 等接口差异；inference mode 另有协议。

autograd 的必要信息包括 requires-grad、view/in-place 关系、saved tensors、hooks、
梯度累积和 backward/forward-AD consumer。它们是依赖/状态/lifetime，不要求保存
每轮 Tensor 内容。候选 action 需梯度时与其他普通输入同样建模，不用 workload
名称切换“推理必无梯度”的假设。

## 8. native 不展开与协议完整性

```text
ImplementationBody = ExpandedRegion | ExternalImplementationBoundary
BoundaryPrecision  = source_ownership + port_coverage + effect_coverage
                   + alias_coverage + completion_coverage + resource_coverage
```

没有 native 源码展开时，仍可以由受版本约束的官方/API/运行协议完整描述边界行为；
如一个已知纯数值 primitive 的输入、效果、异常和执行资源都已闭合，则不必先恢复
每条机器指令。反之，“标成 native”只完成分类，未完成接口依赖证明。动态回调、
外部共享指针和未知写域必须以具体端口/coverage 缺口保留，不当成 NONE。

纯 Python 自定义函数同样可能缺目标/环境，native 同样可能有精确协议；完整性
不按源码语言或“标准模块”名字决定。库协议必须绑定实际实现版本、参数条件和
必要 guard；运行观察提供事实，不能自行把未观察路径升级成全路径证明。

## 9. 全生命周期组合压力路径及验收边界

```text
namespace/current content -- Resolve/Open/Read --> bytes or mapped representation
  -- Deserialize --> object graph + allocations + alias/lazy dependencies
  -- Install State --> parameter/buffer/reference/autograd state
  -- Allocate/Copy/Convert --> device representation + work/ready obligations
  -- Compute/State Transition --> outputs + state + required gradient/RNG relations
  -- Encode/Serialize --> ordered chunks + encoder/serializer state
  -- Write/Flush/Close --> file/sink state + outcomes + required persistence protocol
```

每个箭头是上文协议组成的 Region，可递归展开，并沿正常/异常/异步出口连接。
这个类型检查路径不是手工 workload graph，也不计自动源码恢复覆盖率。完整程序
自动生成、运行对应、依赖闭合及可化简性仍按主规格分项验收。

### 9.1 本机证据（只支持有限反例，不授予化简）

证据脚本和 JSON：`artifacts/experiments/b1_call_operands/model_resource_protocols/`。
使用现有 `lewm` conda 环境，CPU 小张量与临时文件；未运行目标/未初始化 CUDA。

观察到：dup 后共享 offset，独立 open 同一硬链接文件 offset 独立；open-truncate
后错误 write 不恢复原内容；NumPy alias 改变 Tensor 内容而 Torch `_version` 不变；
同设备 `.to()` 可返回同对象而强制 copy 返回不同对象；grad mode 改变梯度关系；
显式 RNG 状态推进；`load_state_dict` 可在后续形状错误前写入前项参数。

本机 source hash 随 probe JSON 保存，关键实现位于已安装 PyTorch 的
`cuda/streams.py`、`_tensor_docs.py`、`nn/modules/module.py`、
`autograd/grad_mode.py`、`serialization.py`。stream/event/record_stream 规则来自
这些本机版本源码与 docstring 的接口说明；本轮没有 GPU 实验，未声称已观测实际
DMA、跨 stream race、kernel 错误归因或物理持久化。小 probe 也不证明完整 API
所有输入/异常行为；它们用于反驳过强的通用假设并约束后续实现验收。

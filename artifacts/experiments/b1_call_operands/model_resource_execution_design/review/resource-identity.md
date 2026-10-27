# R0：资源实例、代次与实际发生的最小身份合同建议

**Proposed，非已实现/非验收。** 只读指定规范、静态四表及 v2 价值/证据/有效期
代码；本轮不改产品/docs/tests、不运行测试/采集/LeWM/GPU、不 git。绑定本目录
`source-sha256.json` 的12个实际阅读文件。以下是可实施的身份边界，不是新的 profiler。

## 1. 当前事实和必须修正的连接假设

- ProgramGraph 四表只做静态 wellformedness：definition、requirement、owned handle
  Use 和 Location 对应。同 owner SAME 闭包只比较同一次 op occurrence / activation
  的绑定；没有动态存在、实际 handle、容量满足或 ready 证明。
- v2 ResourceID 当前用于 SemanticGraph.ResourceRequirement；normalize_v2.resources
  对 process/device/context/stream selector 散列后建“要求”并挂 USES_RESOURCE。
  此 ID 不能改名/直接当动态 ResourceInstanceID，selector 也非 lifetime 证据。
- v2 OperationInstance.definition 为 OperationDefinitionID，并非 Program OperationID；
  旧EEG/provider事件与 Program occurrence 的粒度可多对多。**采用 root 决定：新增
  canonical OperationOccurrenceID / RegionActivationID，通过显式有依据的对应连接
  旧 OperationInstanceID，不共享同一ID后暗示同一实际发生。** 我先前直接复用旧
  OperationInstanceID 作 core occurrence 的建议撤回。
- v2 ObjectID / StorageAllocationID / StorageRegionID / MaterializationID 可沿用其
  各自身份域；但当前 device/lifetime_scope/ready_event 字符串和 EvidenceKind.OBSERVED
  不能充当 typed instance/generation/完成证明。EventPoint 仅 registry 局部事件序号，
  不可用跨 scope ordinal 或 collector 到达顺序推 GPU/CPU happens-before。

## 2. generation 究竟属于谁：确定选择

**ResourceInstanceID 已是一次资源生命周期的 generation-qualified 身份。**
不再同时加一个可独立修改的 lifetime_generation counter，也不以同 Definition 的
第n次调用当资源代次。状态写不改变此 ID；真正销毁后重建即新 ID。ID 不绑 capture
window / clock；资源可跨窗口存在。多个观察指同一实例需明确对应依据。

| 实体/重复动作 | 哪个身份或版本变化 | 绝不能混成 |
| --- | --- | --- |
| 同一静态 Create 执行两次 | 两个 OperationOccurrence；可能两个 ResourceInstance | DefinitionID 的新版本。 |
| 同一 fd table slot close 后复用 | 新 descriptor/handle incarnation | fd整数、小整数ObjectID、OFD身份。 |
| dup 得到另一descriptor | 新handle incarnation，可指同一OFD instance | 新OFD或独立offset。 |
| 同一路径独立open | 可指同file entity，通常不同OFD lifetime | 路径、文件内容、OFD、handle同一件事。 |
| allocation free 后同地址再分配 | 原有 StorageAllocationID 的新生命周期ID | Tensor _version、逻辑版本、pool身份。 |
| 同event再次record | 同event instance；新的record/work/content版本 | 新资源生命周期。 |
| stream继续enqueue | 同stream instance；新的work/prefix | stream重建或body suspension generation。 |

对象生命周期/descriptor slot生命周期/资源生命周期相互独立。open/closed、offset、
rights、occupancy 仍由 canonical state 表达，不复制到 instance 上当事实快照。

## 3. R0必须依赖的 occurrence 最小基础

需在独立 Execution artifact 中先冻结以下基础，不塞静态 ProgramGraph：

```text
ExecutionScope: snapshot(ProviderArtifact), run identity, process incarnation identity
RegionActivation(id: RegionActivationID, scope, region: RegionID, origin/evidence)
ActivationIngress(id, activation, target: BlockID, actual entry/resume source/evidence)
OperationOccurrence(id: OperationOccurrenceID, activation, ingress,
                    operation: OperationID, visit: nonnegative exact int, evidence)
UseOccurrence(operation: OperationOccurrenceID, use: UseID)
AccessOccurrence(operation: OperationOccurrenceID, access_index: nonnegative exact int)
StateOccurrence(value: ValueID, producer: OperationOccurrenceID | IngressID)
```

- snapshot 必须是该 ProgramGraph 的确切版本；run/process incarnation 不用 pid/
  frame地址替代。raw pid/thread/window/clock 只是 provider 观察域/诊断，不授相同。
- activation 是一次真实 frame/region 激活，resumable activation 可跨多个 ingress；
  ingress/segment/visit 与 resource lifetime、外部 drive epoch 分开。delegate-only
  不伪造 body ingress。该基础必须与既有 C2/D1 入边/出口合同对应，不能自写解释器。
- OperationOccurrence 对唯一静态 Operation，Use/Access 必须确属它；StateOccurrence
  producer 由原 StateVersionValue.origin 唯一决定。block参数需对应实际 entry/
  resume/edge，普通结果需对应真实 producer occurrence，不能直接用静态ValueID。
- 旧EEG OperationInstance、kernel/native事件、canonical occurrence 多对多对应是
  另外的带证关系；缺关联可保留 raw resource 观察，但不能编造 canonical occurrence。
- 跨窗口使用同一实例不需要更换 Scope；跨进程继承/共享可有明确 import/transfer
  对应。创建所在process的incarnation是身份namespace，不是资源只能被该进程使用
  或进程退出时资源必毁的断言。缺此基础不能宣称动态 resource binding 已完成。

## 4. 建议的最小资源记录（所有新行 frozen/slots/exact types）

以下字段中的 Site 是真实 occurrence 的 BEFORE/AFTER/实际completion-index之一；
不是时间戳推测。Evidence 使用现 ProviderFactReference；可附现 EvidenceClaim
解释学到事实的方式，但二者均不自动产生 ProofStatus.PROVEN。

```text
ResourceInstance(
  id: ResourceInstanceID, identity_scope: ExecutionScopeID, kind: ResourceKind,
  role: ResourceRole, origin: CreatedAt(Site) | ExternalImport(ProviderFactReference),
  identity_evidence: ProviderFactReference)

ResourceRealization(
  definition: ResourceDefinitionID,
  scope: OperationOccurrenceID | RegionActivationID,
  instance: ResourceInstanceID, evidence: ProviderFactReference)

RequirementBindingKey(requirement: ResourceRequirementID,
                      owner: OperationOccurrenceID | RegionActivationID)
RequirementBinding(key: RequirementBindingKey, instance: ResourceInstanceID,
                   at: Site, support: tuple[StateOccurrence,...],
                   evidence: ProviderFactReference)

HandleBinding(id: HandleBindingID, source: ObjectHandle | DescriptorHandle,
              instance: ResourceInstanceID, at: Site,
              support: tuple[StateOccurrence,...], evidence: ProviderFactReference)
ObjectHandle(source: UseOccurrence, object: existing v2 ObjectID)
DescriptorHandle(source: UseOccurrence, namespace: ResourceInstanceID,
                 incarnation: HandleIncarnationID)

ResourceAccess(operation: OperationOccurrenceID,
               binding: RequirementBindingKey, handle: HandleBindingID | None,
               evidence: ProviderFactReference)
```

固定不变量：

1. Realization 的 CreatedResource 必须对应同snapshot的准确创建 OperationOccurrence；
   ExternalResource 对应准确声明 Region activation 的隐式端口。失败也可能已发生
   部分创建，不能强制所有 realization 只可出现在整个call NORMAL后。外部 import
   可以无源内 Create，观察开始不伪装资源出生。
2. 不默认 definition↔instance 是一对一。重复创建、池返回既有对象、外部共享等
   是否允许由实际协议/evidence决定；静态 definition 不生成不同实例证明。
3. 同 Operation owner 的 RequirementBindingKey 必须是同次 op；Region owner 的
   key 指该次入口 activation。入口绑定在该activation内不任意改绑；失效/资源
   closed 不等于改identity。ResourceAccess引用此唯一binding，不重复存第二actual。
4. **词法parent不等于动态binding来源**：嵌套函数/闭包可在外层返回后使用所捕获
   资源。Access必须明确引用实际owner activation的binding，并有现call/environment
   actual→formal/capture对应；不能只找最近caller或同RegionID。未知则不授满足证明。
5. ResourceUse.definition若已声明，实际binding须能回连相应Realization；handle若
   已声明，source必须是该次op的那个owned UseOccurrence。静态handle=None不补
   假Use；隐式current-stream等可由现状态读/协议对应解释，否则仅保留未知。
6. ObjectHandle沿用ObjectID一次生命周期；DescriptorHandle的incarnation是该
   namespace中那个native slot/handle生命周期，不是Python整数/包装器生命周期。
   raw fd/指针值来自该Use的denotation/原provider事实，不作身份主键。旧核心
   ResourceUse.handle只收ReferenceUse；原生scalar descriptor可有单独有证动态
   endpoint，但不得伪造Python Reference或默默修改旧静态字段含义。
7. binding只记录关联。kind/role、same-owner关系可做结构检查；容量/rights/
   当前open/ready的满足需逐对应occurrence/state求证。没有 satisfied=True、live、
   ownership-free 或 ready 布尔字段；不同InstanceID也不反向证明different。
8. support仅引用既有动态canonical state版本，不复制状态值。未知写/图外修改/
   coverage缺口后，旧association/access支持不能继续当当前有效。close RAISE可能
   已有partial state，不回滚旧binding、不从异常推“仍open”。

其中 ExternalImport/CreatedAt 与 Object/Descriptor 是严格判别联合，不接受任意
dict/string selector。新增ID仅为确实缺的execution/activation/ingress/instance/
handle关系域；不再造第二组 ObjectID/AllocationID/MaterializationID。

## 5. validity、destroy 与状态唯一来源

- 资源历史身份不因 close/seek/write 重置；实际 destroy/recreate 才新lifetime。
  终止事实指真实destroy occurrence/外部事实，缺终点是未知，不是无限live证明。
- binding当前有效区间从实际state/support及coverage派生，必要沿已有EventPoint
  附观测范围；不把局部序号顺序当跨CPU/GPU因果。
- close一个handle仅改变该handle/OFD引用状态；dup/fork/异步借用等可能仍保持底层
  资源。释放Python引用不证明native资源毁、allocation free或GPU完成。
- ResourceLocation仍只连接既有Location的资源owner；动态owner/selector对应由
  realization/state-occurrence建立。coarse world可共享覆盖多resource，不能由不同
  ResourceInstanceID 自动宣布StateLocations不alias，也不建parallel resource-state表。

## 6. 与 v2 allocation/materialization 的关系

StorageAllocationID 已标一次allocation生命周期；同一内存块不要为R0再mint并行
ResourceInstanceID。memory pool/executor/queue/file/OFD可用新instance；
AllocationPlacement(allocation: existing StorageAllocationID, pool/device: ResourceInstanceID,
 evidence)只是“分配自/位于”关系，不是same identity。若后续泛resource target
确需引用allocation，应加tagged target引用原StorageAllocationID，而非复制registry。

StorageRegion保留同allocation的offset/shape/strides/dtype。Materialization仍沿原
region→allocation和ValueVersion/provenance链；resource placement不证明值相同、
view分配或物化仍有效。NumPy外写可保持Object/Allocation而失效内容版本/物化。
任何device字符串、shape/少量样本相同都不证明逻辑版本、materialization可替换或
resource同一。无需保存大Tensor，也不逐次复制模型参数。

## 7. 无静态worksite/ready端口时的具体桥接决定

R0动态关联只引用现 Op/Use/Access/真实完成，不假造ready producer：

- owned入参：UseOccurrence；工作读写：AccessOccurrence及原StateAccess/footprint；
  输出：准确OperationResult occurrence或真实completion的BlockArgument occurrence。
- host完成：ordinary AFTER，或INVOKE实际NORMAL/RAISE successor-index；BodyDrive
  则引用其真实source关联及body occurrence，不将它改成INVOKE完成。
- 一个opaque canonical操作可对应多个真实enqueue/kernel/copy，反向也可多对多；
  用provider/source对应，不为凑单worksite复制Operation或第二套Use。
- 无证据不能声称WorkTicket/Ready已接通。后续R1/R2必要可加只引用owned Uses、
  access index、实际result/completion的静态签名overlay；canonical实参/状态源仍唯一。
  host NORMAL、event同名、时间较早或静态ResourceUse存在均不推出device ready。

## 8. 必须验收的反例

| case | 必须保留/拒绝的错误推断 |
| --- | --- |
| 同Create在loop两次，第二次失败但有partial allocation | 不合并两occurrence；不把失败当无资源创建。 |
| close(fd3)后另一open复用fd3，旧Pythonwrapper仍在 | 新descriptor incarnation，旧handle不得自动指向新OFD。 |
| 两open同file与dup | file实体可同；两OFD/offset可独立；dup可共享同OFD而handle不同。 |
| fd关闭但dup/queued work仍持引用 | 不从单handle close推出底层destroy/free。 |
| capture开始已有GPU/context/OFD，跨窗口仍存活 | 外部import无fakeCreate；不以窗口/clock结束实例。 |
| pid/地址/stream0复用或不同context同数值 | 必须有lifetime/namespace依据，原数字不作same判断。 |
| 两次调用同Region、闭包逃逸后再次调用 | 独立activation；资源binding通过准确captured activation而非词法Region合并。 |
| event再次record、旧event wait或queueprefix证据 | 资源可同但record/work版本不同，旧Ready不能授权新内容。 |
| NumPy共享buffer原位写、allocator同地址再分配 | 前者新内容版本/失效物化；后者新AllocationID，二者不能互换。 |
| 内容采样相同但cached输出identity/alias不同 | 不授替换权限，更不保存大Tensor作为通常guard。 |

## 9. 实施分门和迁移

R0先冻结 occurrence/identity/source合同及上述schema；再做独立执行artifact的
records/validator与通用手工正反图，复用现provider事实，不开发collector。动态表不
进入静态ProgramGraph，旧schema14不偷带字段。旧v2值/证据/registry保留原解释，
以显式bridge接入，不把旧ResourceID或ready_event标签升级为新证明。R1/R2再完善
work/ready与静态端口引用；本轮没有实现动态绑定、ready、完整文件协议或自动建图。

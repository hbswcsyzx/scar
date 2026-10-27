# R0合同：identity / handle / realm 只读交叉审查

**结论：方向接受；冻结前须将以下字段按本建议收紧成明确类型。** 这是DRAFT
规格关闭清单，不是产品漏洞或R1/R2实现验收。只读，无测试/采集/产品修改。
所审 `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` SHA256：
`fc2b282770ec896ef0988eb535d590cbeb41c0090d42db2b3f164d6e7170a09c`。
审查聚焦§2–3/5；§4仅核对新 InvokeBoundaryStateEffect 与canonical源衔接。

## 1. 已接受且没有发现回归的决定

- core occurrence/activation/visit 独立于旧EEG Instance，显式多对多对应正确；
  snapshot/run/process incarnation 是规范身份，window/clock/pid只属来源范围。
- instance ID即一次lifetime；event record/work/prefix另有版本。realization 取得
  既有资源不等于首次创建，不应要求 instance.origin 等于每个提供操作。
- ImportedAt/UnresolvedOrigin 可保留实际图外来源；capture开始不是birth，
  缺end不等于live；native EvidencePoint不伪装Python op。
- Region requirement准确activation且可capture/escape，不按词法最近caller绑定。
- allocation只用原StorageAllocationID；pool/device placement不是same identity。
  target的Instance/Allocation联合与MEMORY_POOL不得错配也写对。
- §5逐贡献AND、每贡献替代support OR、Completed/Ordered可混合，及无可靠
  denotation不填content版本均正确。本文不将其当GPU实测。
- §4显式 InvokeBoundaryStateEffect 接原owned state Use及实际completion formal，
  闭合了unknown INVOKE没有普通StateAccess时的连接需要，不建第二state。

## 2. identity_realm：本门冻结判别联合，不用自由string

```text
IdentityRealm = RunRealm(run: RunID)
              | ProcessRealm(process: ProcessInstanceID)
              | ExternalRealm(namespace: ProviderFactReference)
```

realm定义ID namespace，不是ownership或寿命上界。ProcessRealm不推出进程结束
时共享OFD必毁/别进程不可访问；ExternalRealm的namespace事实需说明实际外部
身份域/复用范围，不是任意名字。raw pid/address/device0/stream0 不可直接构造
同realm证明。不同realm/InstanceID也不自动证明physical不同。不能确定更强域时
使用本run的opaque新身份和Unresolved identity correspondence，而不是猜全局相同。

## 3. HandleBinding必须区分两种端点，避免平行对象lifetime

最小改动：将目前所有handle共有的handle_lifetime移入native端点：

```text
HandleEndpoint = ObjectReference(value: ValueOccurrenceID, object: existing ObjectID)
               | NativeDescriptor(value: ValueOccurrenceID,
                                  namespace: ResourceInstanceID,
                                  lifetime: HandleLifetimeID)
HandleTarget = InstanceTarget(ResourceInstanceID)
             | AllocationTarget(existing StorageAllocationID)
BindingEnd = EndedAt(point: ExecutionPoint, evidence: ProviderFactReference)
           | UnobservedEnd(reason: str, original_fact: ProviderFactReference)
```

ObjectReference检查原Reference值/denotation，不强迫每Python wrapper再mint另一
ObjectID同义lifetime。wrapper可以不换ObjectID但其底层binding发生变化；那是新
关联区间和state，不是新Python对象。NativeDescriptor的lifetime属于namespace中
的slot/handle incarnation，值由真实Data/Protocol occurrence提供，不伪造ObjectID。
dup新slot可同target；close后fd复用必须不同lifetime；整数interning与此无关。

ResourceAccess若有静态ResourceUse.handle，需准确匹配该owned UseOccurrence
读取的ValueOccurrence（必要经有证copy/denotation），不能仅以同数值join。
static handle=None的implicit资源不补假Use；保留协议/状态读对应或Unresolved。

## 4. 关联身份与当前满足性分离：需补support和访问点

目前字段只有 start/end/rights/ownership，不足以机械阻止“绑定后图外close/
重绑定仍沿用旧权限”。建议：

```text
StateSupport = tuple[ValueOccurrenceID,...]  # 必须各自指原StateVersion变体
HandleBinding(..., support: StateSupport, coverage: CoverageClaim, end: BindingEnd)
ResourceAccessBinding(operation: OperationOccurrenceID,
                      requirement_binding: exact RequirementBinding key,
                      handle_binding: exact HandleBinding ref | Unresolved,
                      constraint_evidence: tuple[ConstraintEvidence,...])
```

support仅引用现canonical动态版本；coverage复用Completeness+原事实/缺口，不
复制状态payload，不把end未知当区间内任意时刻均有效。未知写/外部alias/close
partial failure后需要当前state重证；没有覆盖时答案UNKNOWN，而不是没有发生写。

Region入口的identity binding保持固定，但capacity/rights/open等满足性在**每次
实际ResourceAccess**的current版本检查，不能一次绑定承诺整个activation。
constraint的必需集合从原Requirement派生，不让用户删obligation获得满足：

```text
ConstraintRef = CapacityAt(requirement, exact tuple index)
              | RelationAt(requirement, exact tuple index, other binding key)
              | ProtocolCondition(schema/rule: ProviderFactReference, canonical deps)
ConstraintEvidence(ref, support: StateSupport, evidence: ProviderFactReference)
```

kind/role和同owner关系按原registry派生；跨owner无显式pairing不猜。记录保存
证据关联，不收satisfied=True或任意ProofClaim(PROVEN)当事实。缺evidence即明确
未知。现静态未含device/rights等完整constraint，不可用一个裸字符串冒充它们。

## 5. rights / ownership：保留字段就应同时冻结类型和Unknown

不建议堆各业务enum；最小通用表达是schema-qualified协议成员+明确holder：

```text
UnresolvedFact(reason: str, original_fact: ProviderFactReference)
ProtocolRight(protocol: ProviderFactReference, member: ProviderFactReference)
RightsClaim(members: tuple[ProtocolRight,...], completeness: Completeness,
            support: StateSupport, evidence: ProviderFactReference)
OwnershipClaim(holder: ObjectID | ResourceInstanceID | RegionActivationID | WorkTicketID,
               relation: OWNED | SHARED | BORROWED, support: StateSupport,
               lifetime_obligation: ProviderFactReference, evidence: ProviderFactReference)
rights = RightsClaim | UnresolvedFact
ownership = tuple[OwnershipClaim,...] | UnresolvedFact
```

ProtocolRight是对具体协议schema/成员的精确引用，不是自由字符串“rw”；未识别
协议不能自动解释为allow。completeness仅是有来源的条件声明，非授权；空集合
且coverage未知不表示no rights。Ownership不等Python refcount，不存全局余额；
多个holder/borrow可以共存，实际关系由canonical状态支持。unknown finalizer/
queued access可失效当前snapshot，不能从历史finished推出仍held或free。

若R1尚不实现known-rights/ownership验证，v1可只接受UnresolvedFact这条分支，
明确不授满足；随后schema显式扩展known variant。不能将字段留作未检查string。

## 6. visibility_domain：R0应锁定“消费者上下文”，不允许同名字符串

```text
VisibilityDomain = HostVisibility(process: ProcessInstanceID,
                                  address_space: ResourceInstanceID)
                 | QueueVisibility(queue: ResourceInstanceID, prefix: QueuePrefixID)
                 | EndpointVisibility(endpoint: ResourceInstanceID,
                                      protocol: ProviderFactReference)
                 | UnresolvedFact
```

address_space/queue/endpoint是规范instance而非device名；现role/kind无法确定时
保持Unresolved，不造一个看似通用的endpoint。Host read、device ordered consume、
文件persistence不能互换。QueueVisibility需对应准确consumer提交位置/前缀，
不是任意同queue任务；同一stream/Event名字不得复用。真正native visibility规则
仍需带版本证据，本类型本身不授ready。

ReadyRequirement/ReadyEvidence/ContributionSupport都用此同一判别联合；匹配
content/materialization/allocation、footprint与scope，且每贡献有自己的可选support。
未知denotation/外部写保持缺口，不能把shape/样本相同升级为匹配。

## 7. 最小关闭反例与实施结论

- ProcessRealm raw pid复用、不同context同stream0：不得跨lifetime/realm合并。
- Pythonwrapper仍在但fd已close/reuse：旧ObjectReference不指新slot；native fd不
  转ObjectID，旧rights support不保持当前有效。
- 外层activation已返回，闭包实际捕获其resource binding：有明确对应则可引用；
  同Region新调用不能取代该captured activation。
- Region入口绑定后callback写capacity/rights/closed：identity可仍同，当前
  constraint不再自动满足。RAISE partial state不能回旧world。
- MEMORY_POOL requirement误连allocation、same address不同AllocationID：拒错域，
  不因placement造same identity。
- OrderedVisibility给host read或别queue/prefix：拒；unknown domain不改ready=True。

上列具体variant/support/access连接收紧后，§2–3/5可进入R1/R2字段实现；当前
DRAFT尚不能称完整机器schema已冻结。本文没有发现需改旧core的数据生产者或
状态定义，不要求R0实现采集/完整denotation/原生协议，也不授M0–M2或runtime验收。

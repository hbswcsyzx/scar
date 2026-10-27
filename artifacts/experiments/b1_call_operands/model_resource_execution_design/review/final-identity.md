# R0 final候选：identity / current constraint 终审

所审合同 SHA256：
`afd291d40c8377b3e0af650310d369887c51cd1b617f8cbc423973edede32fb7`。
本轮只读该最终候选，无产品/docs改动、测试、探针或新采集。

## 已关闭的前审项

- identity realm 已为 Run/Process/External typed variants，窗口/clock不决定寿命；
  instance ID即lifetime，process/thread/allocation重用原身份，无平行registry。
- core occurrence与EEG多对多显式对应，跨bundle端点按artifact+typed ID限定。
- 首次creation与realization取得alias分离；静态CreatedResource不授fresh。
- Object/NativeDescriptor/Unresolved endpoints分开，native slot lifetime不复制
  ObjectID；rawfd不伪造reference；reference/descriptor未知对应留明确缺口。
- Region入口身份binding固定，capacity/rights/open按每次ResourceAccess的current
  state重核；closure引用准确activation，不按词法/最近caller猜。
- StateSupport只引原StateVersion的ValueOccurrence；所需ConstraintRef集合从原
  requirement/profile派生。start/end不能吞未覆盖写，未知endpoint/denotation有
  typed Unresolved与MissingEvidence，非已知空。
- ProtocolRight带schema/member来源；ownership的release-authority与sharing分轴。
  visibility分Host/Queue/Endpoint/Unresolved，不自动给host/free/persistence权限。
- 关系合同与R1/R2 exactrecords/wire分门，未声称动态registry或source/runtime
  产品已存在。该范围表述正确。

## 唯一需关闭的关系澄清 F1

§3 ResourceAccessBinding.handle_binding 当前为“exact binding key | UnresolvedHandle”，
但 HandleEndpoint.UnresolvedHandle 的字段强制含ValueOccurrence。

反例：静态 ResourceUse.handle=None，资源要求是已知CPU executor、进程/线程，
或由当前上下文状态选取的queue。实际instance/binding可以有准确依据，却没有
可指向的canonical handle ValueOccurrence。不能为了填该字段创造handle producer，
也不能把“本访问没有显式handle关联”偷换成“其资源不明”。

建议最小修正（不新增state/producer）：

```text
AccessHandleAssociation = ExplicitHandle(exact HandleBinding ref)
                        | NoExplicitHandle(rule/selection canonical refs)
                        | UnresolvedHandleAssociation(reason, scope, original_fact)
```

NoExplicitHandle只表示该ResourceAccess不通过显式handle关联，**不表示底层native
没有handle**，也不授无副作用/ready。若static ResourceUse.handle已声明，则不得
选此分支，必须对应其owned Use或明确缺口。HandleEndpoint的UnresolvedHandle仍
用于“确有该ValueOccurrence，但其handle denotation未知”的情况，不兼任无handle。

截至上述SHA，本报告结论是 **NEEDS_ONE_RELATION_CLARIFICATION**；除F1外未
发现identity/currentconstraints/typedUnknown的实质未决。不以该项扩成新的runtime
采集或完整native协议要求；若root采纳等价明确表述可追加限定关闭，不改原审计。

## 限定关闭复审（保留上方原始问题）

最终候选SHA256：
`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`。
只核对本次两个小关系修正，没有扩大审查/运行实验。

- F1已关闭：§3现明确 ExplicitHandle / ImplicitBinding /
  UnresolvedHandleAssociation 三分支。ImplicitBinding只用于静态handle=None并
  引用原rule/selection-state；不伪造ValueOccurrence，不推出native无handle。
  静态handle已声明不可绕过；未知选择来源使用不强制handle值的独立Unknown分支。
- ExecutionSegment.host_thread允许UnresolvedHostThread；缺线程来源不伪造
  HostThreadInstance、不授thread order/visibility。这符合partial evidence原则，
  未改变activation、segment或资源lifetime的职责。

**最终结论：PASS_WITH_SCOPE。** 在上述最终SHA的R0关系合同范围内，identity /
current constraints / typedUnknown未再发现实质未决；可按合同进入R1/R2 exact
records/wire分门实现。前文原SHA的问题是历史审查状态，不是当前未关闭项。
此结论不验收新产品registry、完整denotation、actual native/source/runtime对应或
自动建图/优化，也没有新增测试、探针或产品修改。

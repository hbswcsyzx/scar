# P4：剩余协议的原端口、消费者与组合计划

2026-10-18。此为下一门的实施规划，不是P4验收报告。依据
[父计划](M1_PROTOCOL_FAMILY_PLAN.md)、[冻结合同](M1_PROTOCOL_CONTRACT.md)及三路
只读源码审查；未为本计划运行新语言探针、测试或LeWM工作负载。
P3首次完整回归失败与其[修复门](M1_BODY_OCCURRENCE_REPAIR.md)分别保留；
不能拿本计划或P3局部通过代替P3修复验收。

## 1. 在模型里补什么

五类实体仍是Operation、Value、StateLocation、Region、Resource。输入/输出是
原端口角色，行为标签不互斥。P4不按await、视频或业务名称另造基础节点类型。

```text
原请求/receiver/有序实参/当前状态
  → lookup/真实调用的本次NORMAL或RAISE
  → 原gate/当前request关联
  → 本次body入口及精确resume slot，或合法无body路线
  → 本次中间handoff/item/最终值/异常
  → 父表达式或host消费者 + 当前session/生命周期
```

新增的是这些原事实之间的约束和派生查询。每个consumer须能追溯到准确
producer、ordered Use、selected edge及当前状态，不能由类型相同或唯一可见
producer猜来源。跨region复用原call输入/输出及P3发生关联；同一表示不复制
第二套producer/Use、历史、phase或状态SSA。

## 2. 已确认的源码事实与缺口

以下是**Observed：只读源码审计**，不是native/runtime证明。

- `program/protocol_rules.py`已有固定profile/clause与允许合同。它们列出义务，
  不等于这些义务已经接到消费者；当前部分clause没有派生实现。
- `protocol_validation.py`会核ProtocolCall本操作receiver/argument Uses及自有
  result，但`connection_errors`跳过OperationSiteSubject；lookup→call.receiver→
  本次结果消费者尚未普遍闭合。BodyResume的消费者检查还跳过DELEGATE_VALUE/
  DELEGATE_PACKET，而对应原slot已经存在。
- `driver_validation.py`已核AsyncRequestCreate、RequestAssociationRead各自
  原端口与N/R；尚未把实际request经copy/call得到的body、latent raw和最终gate
  联成同一次关联。CHECK_INITIAL_ASEND也未接完整原ordinal/状态谓词链。
- async item adapter已有准确ASYNC_YIELD输入限制，但最终item消费者及按
  AWAIT/ASYNC_YIELD/终结区分的session更新尚未闭合。
- TASK_CANCEL_REQUEST、CANCEL_DELIVERY、CANCEL_HANDLER_OR_TERMINAL、
  TASK_STATUS_ROUTE分母存在；后两项尚无完整允许合同/派生规则。请求成功
  不能替代实际交付、处理器后果或最终cancelled状态。
- family/flavor、saved/current state、C1 pending/context、F/P/T与release、
  P3持续activation/segment/host桥已有接口；继续复用，不重建调度器。

源码定位：`scar/ir/program/{protocol_rules,protocol_validation,protocol_query,
protocol_flow,driver_validation,resumption_validation,session_release_validation,
lifecycle_flow}.py`。三路审查仅回消息，未修改冻结源码或写报告。

## 3. 固定验收分母

下表保留父计划原编号，共F12–F24与X25–X27，不以实施方便删行或合并成
“支持异步”。每行均需原图正例、具体错接反例及缺失关系/预算截断结果。

| 原义务 | 必须接通 | 典型拒例或边界 |
| --- | --- | --- |
| F12 | await lookup→本次call receiver→iterator校验；零挂起/正常完成及各自失败。 | 错同型iterator、缺lookup、错误completion、普通generator误授await资格。 |
| F13 | 每次scheduler handoff→准确body恢复→最终表达式；normal/raise各接原slot。 | 旧状态、另一子调用结果、漏异常交付；中间handoff不冒最终值。 |
| F14 | coroutine的当前phase谓词、真实branch、重入/重复使用、throw/close后果。 | 早期状态跨callback使用、错误终态、把重复await当新body。 |
| F15 | generator-coroutine直接驱动和await路径分别接同一body的准确结果。 | wrapper与body凭类型拼接、普通generator误分类、另一Drive的adapter结果。 |
| F16 | 四种async request创建/外来来源→本次关联→交付；首次发送/复用/竞争。 | 错request/body/latent/ordinal；R=request、B=body、S=scheduler角色不能混。 |
| F17 | AWAIT保持当前session；ASYNC_YIELD完成本次item/request但暂停body。 | AWAIT当item、另一item、旧session/state、由host返回误授body终结。 |
| F18 | 自然完成、主动终止异常、源级非法非空return分别建模。 | 旧return payload、错adapter来源、用自然完成规则吞主动异常。 |
| F19 | 版本限定的closed/athrow/aclose和失败后续体；各类终结分别连接。 | request完成误作frame可释放、native closed bit误作continuation消失。 |
| F20 | yield-from求值/GetIterator/首次advance及零次父挂起、各自失败。 | lookup失败误作exhaustion；未执行的父Suspend/Attach被伪造。 |
| F21 | NEXT/SEND分流、真实lookup/call/result/state→item或最终值消费者。 | 缺方法/调用失败、错同型结果、item误作父表达式最终值。 |
| F22 | 本次THROW的1–3原参数→delegate有序实参；item/exhaustion/缺方法。 | 两个raw pack/branch互换，原包与新包混接，parent不该恢复却造Drive。 |
| F23 | close成功续原GeneratorExit；失败按本次新包覆盖，接pending/context。 | 异常覆盖丢失；delegate-only无父Drive/Attach/F，不能先统一Attach。 |
| F24 | cancel request→实际delivery→handler抑制/cleanup再await或最终状态。 | 旧packet/错target/请求成功当已交付；正常/异常/取消终态混同。 |
| X25 | active C1跨至少两cut，saved pending/context/delegate与当前state组合。 | 旧包/旧state、fresh Replace错误继承旧token。 |
| X26 | 真publication、session当前性、partial RAISE、窄release/宽helper组合。 | Suspend种F，宽helper未杀P，request结束误授释放。 |
| X27 | 上述协议与P3本次Drive/持续activation/entry/outcome逐次组合。 | 错实例/代次/线程/来源；缺采不能删除原consumer分母。 |

## 4. 冻结前需解决的有限接口问题

优先从原端口派生，确实无法引用的事实才增加最小附件并显式版本化。

1. 无DriverInterface的helper/site如何引用准确原raw来源？ProtocolCall的实际
   argument不能伪加RAW。先检查原OwnedUse与已有调用对应是否足够；不足则
   冻结准确引用关系，不能用“某pack可达”代替本次来源。
2. await/wrapper和async request的原site义务如何从scope派生？删除关系row
   不能删除分母；scope/site库存未闭合时保精确全局缺口，不空成功。
3. family/flavor与normal/exception resume slot、当前session更新如何联合核？
   使用原selected N/R edge及原状态读/branch，不靠自造finished/phase标志。
4. cancel的handler/status如何锚原site、当前状态和本次结果？先明示原端口
   规则，不能把opaque helper当内部已理解或实现任意Task框架。

## 5. 实施顺序、自主关卡和效率

| 关卡 | 交付 | 自主拒绝条件 |
| --- | --- | --- |
| P4-0审计 | 本计划及三路源码事实；准确保留原分母。 | 只列enum或将语言猜测记为实测。 |
| P4-1合同收束 | 上述四问题的原端口/最小附件决定及机器义务表。 | 无来源就猜绑定，或用新表重复已有SSA/身份。 |
| P4-2集成实施 | 三组：await/coroutine；async request/session/cancel；delegation/C1。各自先最小正反例，再接同一canonical resolver。 | 单组green冒充P4；漏site/关系后分母缩小；已知冲突降为gap。 |
| P4-3统一验收 | 固定16组、公开query/预算、原case/fixture守恒；独立复审→最终定向→组件→干净提交→一次冻结全仓。 | 未解决source blocker；截断冒成功；并行测试/写入污染冻结源。 |
| P4-4归档 | 原失败不覆盖、manifest/源码/保护目录核验及commit/push。 | 测试计数当覆盖率，或声明IR冒自动建图。 |

三组在同一P4实施门内集成，不为每个函数或小修重复跑全仓。组内只做能回答
具体风险的必要定向；统一组件后才做冻结完整回归。若全仓失败，留证、定位并
另立修复门，不自动重试。预算复用原copy/paired-origin/worklist和prepared
索引，不按每个formal重置，不枚举路径/轮次，不保存Tensor逐轮数值。

分工延续：A核await/coroutine及跨调用；B核request/session/cancel；C核委托/
C1组合；root核规范事实归属、共享规则和统一验收。没有用户逐门审批步骤。

## 6. 完成后的边界

P4完成后仍需P5完整F01–F24/X25–X28 ledger及公共面、M2原113构造/196字段
映射与完整M0–M2总验收。满足后按用户要求停下来解释模型，再推进自动建图。
本计划不新增detector/backend，不写LeWM规则，不给LeWM加速结论。

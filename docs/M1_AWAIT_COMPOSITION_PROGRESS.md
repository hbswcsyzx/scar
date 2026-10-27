# Await组合：当前进度与未完成项

2026-10-19；依据冻结 [D2计划](M1_AWAIT_COMPOSITION_PLAN.md) 和
[准确合同](M1_AWAIT_ACQUISITION_CONTRACT.md)。本轮是PROGRESS；完整A–H、
原F12–F24/X25–X27十六组、P5、M2原113构造/196字段及M0–M2仍OPEN。

## 模型没有变成特殊场景清单

原五类实体仍是Operation / Value / StateLocation / Region / Resource。
函数、协议操作和提取操作由原Operation表示；输入、候选iterator、W、B、异常
packet是Value的角色；状态沿原SSA和owned Uses传递；控制由Region/CFG承载。
本轮测试是供应IR的构图与发生连接验证，不是从任意Python/LeWM自动恢复全图。
它也没有建立跨deepcopy的数值身份、逐Tensor数值存档或变换授权。

## Observed：保留的真实首红

原始命令、环境、前后源码清单、SHA、完整日志及JUnit保存在
`artifacts/experiments/b1_call_operands/model_await_composition/`。

| attempt | 实际结果 | 归因与边界 |
| --- | --- | --- |
| first-wrapper | 3P/1F | 真native W构造→getter→两层CALL→原Drive已可表达；同域W==B未被拒绝，实际身份约束缺口。 |
| wrapper-fix-and-first-resume | 5P/1F | W/B矛盾转拒绝；零cut原最终提取的existing OutcomeAdapter在正确acquisition scope遇到2条protocol_rule，实际合同准入缺口。 |
| first-composition | 28P/11F | 缺BodyDriveExecution会清掉独立CFG/CALL copy库存，是真缺口；general构图的capture数量错误、case构图复用控制Use以及resume错误码oracle错误单独记录，不冒充产品首红。 |
| first-valid-cases | 1P/3F | case core已合法：删一case让原4job缩成2；两实际incoming各误留下2active。这是完整来源分母与实际incoming选择的真实缺口。 |
| second-composition | 38P/6F | wrapper/resume及部分case修复通过；全删输入附件仍4→2是真缺口；另5F为general新图的控制Use/RegionID错误。 |
| third-composition | 41P/3F | 全删附件分母修复通过，一般协议的真实core/Execution正例与已知不合格返回反例通过；3F为details未透传、静态全图计数误作局部、ExecutionIssue误作字符串。 |
| accepted-focused | **1437P/0F/0E/0skip** | 包含原1393义务与新44；757源前后固定。受影响定向，不是组件/full或完整A–H。 |

## Implemented：针对原关系的公共修复

- native fresh-wrapper关系独立检查同一准确artifact作用域的ObjectIdentity。
  同ObjectID冲突、不同ObjectID仅声明为不同对象；缺身份/跨作用域仍未证明。
  W/B没有进入普通copy/alias闭包。
- 按[有限补充](M1_AWAIT_COMPOSITION_AMENDMENT.md)区分required与optional
  clauses，仅新acquisition profile允许已有准确最终提取合同。获取helper不被迫
  伪造lookup/最终提取，旧profile规则不放宽，wire和Execution8记录不改。
- 原CFG/CALL copy库存不再依赖可选BodyDriveExecution表是否非空。
  缺执行关联只影响对应body桥，不能抹掉已知普通传值。
- 原incoming与实际观察到的incoming分别保留。缺case不虚构expected tuple；
  当前case按最近进入原merge的真实transfer选择，不因另一臂传相同B而接受。

全删输入附件时，只沿原receiver/arguments与准确single-copy回溯最近merge，保留
原incoming，不制造expected tuple。遇生产者/非copy/caller/环/不同merge或预算
边界，保pending/cursor且库存不完整。供应图中的两实际incoming及缺单case/缺全
附件均已运行；更复杂loop/crosscaller仍未因此自动闭合。

最终受影响gate为757源固定SHA
`ee8636d763c96f3a8081a0bce806dbee6f432a63ff928f1678b9c7a3f385c5b7`；
pytest113.63s、runner114.62805700488389s，1437项全过。原e935082的1393项case
身份及所有已有tests/fixtures字节由归档门逐项核对；本轮没有schema词汇迁移。
新44项覆盖wrapper20、resume12、general5、case7。测试数量只说明本门分母，
不代表原16组或全部语言情况已完成。各次失败仍仅属于各自归档SHA，不作合并
计时或当前整仓绿测。有限独立源码复核见证据目录 `independent-review.md`。

## 仍未完成的原验收

零/多cut、同B direct/await、第二Create、真实W与一般协议组合需要共同核对。
即使所有当前供应图通过，也不代表完整消费者解释已闭合：完整resolver还需从
原body terminal→适配packet→caller真实consumer派生最终提取义务，删除adapter
不能使这项义务消失。一般方法合法早失败/资格TypeError、跨caller完整tuple、
更复杂循环及全部删除附件的分母须保持明确；未实际覆盖的组合继续OPEN。

没有新detector/backend，没有LeWM特例，没有新LeWM profiling/benchmark或加速比。
上一1393定向只属于e935082及其741源SHA；历史5822 full只属于原81389862。
验证充分后归档、commit/push并核对远端；不以单helper或测试数量关闭原阶段。

## 下一原验收节点

1. 保留本轮五类实体和原端口，完成一般协议合法lookup/call/qualification失败的
   精确packet/state/consumer组合；尤其不能把实际合法TypeError路线误作成功推进。
2. 将零/多cut原body终端、已有packet适配与caller提取关联起来，独立派生末端
   义务。删除整个adapter时仍有待解释consumer；可选准入不代替完整消费证明。
3. 补齐原shared-caller/current-state及剩余A–H实际组合，对原16组分别自验收。
   原16全部就绪后才组件/冻结全仓，随后P5和M2原清单；保持每门证据、版本管理。
4. 只有完整第一阶段通过，才汇报整个自动建模能力；当前不跑优化后端或LeWM
   benchmark来替代尚缺的模型连接验收。

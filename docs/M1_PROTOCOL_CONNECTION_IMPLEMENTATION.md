# P4-2 实施中的连接与边界

2026-10-18。工作基线 `add4ba8`；本页是实施记录，**不是完整 P4 验收**。
[冻结 v1](M1_PROTOCOL_CONNECTION_CONTRACT.md) 原文和原设计证据保留。
仍按[原 16 组计划](M1_REMAINING_PROTOCOL_PLAN.md)开发，不增加 detector/backend。

## 模型如何落实到代码

五类规范实体不变：Operation 描述操作，Value 描述原值与端口，StateLocation
标识可变状态的位置，Region 表示有入口/出口的可展开区域，Resource 描述资源。
输入、输出、receiver、请求、packet 是端口角色，不是新增的业务节点类型。
行为允许多标签；控制边、状态版本和 ordered Use 仍由原图唯一保存。

新增附件声明独立的 expected 来源及必须满足的消费者关系。它们不能从 actual
producer 反选来源，更不构成第二套 SSA 或执行历史：

| 实现 | 连接的原事实 | 不授予的结论 |
| --- | --- | --- |
| `protocol_connections.py` | 精确协议行自然键、整组输入/guard、parent slot、request/session/cancel 链 | native 实现正确、动态身份或优化许可 |
| `protocol_connection_flow.py` | 原端口、合流 formal、call actual/formal、同一来源的 current copy | 相同类型/内容即同一值；可达即当前 |
| `protocol_connection_validation.py` | 全输入 tuple 的 caller/CFG 相关性；先从原 Use 派生消费者清单再核附件 | 一个成功参数或合法消费者子集代表完整覆盖 |
| `protocol_continuations.py` | lookup→iterator→本次推进→parent/host；原 resume slots 与 close 续路 | 重复节点可 reuse；close 的正常 None 是原异常包 |
| `protocol_async.py` | request 的 B/L 关联、当前 gate/session、真实取消目标/交付/处理/状态读取 | request 完成即 body 结束；请求成功即已交付 |

验证顺序先完成原 core 的 CFG/SSA、resumption、lifecycle、provider/native
结构检查，然后私有准备同一个 ProgramIndex 供连接检查。公开 ProgramIndex
复用这一准备结果；查询复用 index、ProtocolFlow 和预算，不递归验证，不为每个
端口重建整图。Program19 是声明能力版本，Execution8 不变。

## 实施补充决定

这些决定只补实施解释，不覆写冻结 v1：

1. await 的正常调用结果已经是 iterator。后续 DELEGATE_NEXT 与 InitialAdvance
   可精确引用该 AWAIT_CALL 的 NORMAL 结果，或 GetIterator 的 NORMAL 结果。
   不制造额外 getiter，也不把 iterator 当最终 await 表达式结果。首次推进仍须
   检查求值后的原路径和 backedge。
2. close 正常成功后继续原注入 GeneratorExit packet。来源取当前 case 的独立
   InjectedPacketTrigger，沿原 NORMAL 路线核 host/parent/C1 消费者。close 的
   None 仍是它自己的原结果；失败时用准确 RAISE 的新包覆盖旧包。因此不为这个
   情况扩大旧 OutcomeAdapter.input，也不伪造普通 copy 边。
3. async 的 latent CLOSE 可以使用原 NORMALIZE_GENERATOR_EXIT，而非伪装为
   THROW。其新增 profile/rule 组合必须进入 Program19 能力检查。
4. coroutine / generator-coroutine 使用旧形状的只读 AdmissionPredicate 时，
   新增 profile 适用同样进入 Program19；普通 generator 原规则仍保旧版本。
5. 单个有 guard 的 case 可表达部分声明。原输入合流有另一条 incoming 时，
   仍须报告缺 case；不能因为附件只剩一个 case 就改成无条件完整。多个 case
   仍必须各有唯一的准确 guard，全部绑定同一合流。这一补充让删除关系后的
   缺项可由原图清单呈现，不会授予遗漏路径通过的权限。
6. 消费者清单同时需要 must 与 may：两层独立合流可能使任一单 guard 都不能
   证明当前来源，却仍有合法消费者。复用同一原 CFG transfer engine，以 union
   meet 求有界 may-copy，仅用于保留可能消费者，并显式标条件相关性未证。
   输入绑定、状态当前性和变换许可始终不用 may 代替 must。嵌套合流的真实原图
   检查保存在 `shared/nested001`（1 项通过，源码前后相同）。
7. 条件化输入/状态检查支持多个准确原控制边的联合选择，不增加持久图节点或
   phase。选定 decision 的 successor 和对应 merge 的 incoming 必须一致；同一
   merge 的不同 incoming 若代表不同访问，不压成一次静态选择，而保 occurrence
   context 缺口。`shared/choices002` 的 39 项定向通过且源码前后相同；不是完整
   P4 组件。may 结果仍只用于消费者库存。

## 复审发现与修复记录

- **Observed / Implemented / Verified at focused scope**：package 在 model
  绑定 canonical union 前导出三个 alias，导致包级 alias 残留 Any。独立 Python
  进程测试真实失败后修正导出顺序；[复审报告](../artifacts/experiments/b1_call_operands/model_protocol_implementation/review/review.md)
  记录修复后 377 项受影响 codec/record 定向通过。原 v18 oracle 由冻结旧 encoder
  独立产生；十个旧测试只迁移全局 schema 上限，实际旧 wire 版本/字节断言保留。
- **Observed / Implemented / Verified at focused scope**：多 choice 的 bind
  拦截了同 merge 的冲突访问，另外三个来源入口却可能取最后一个 incoming。
  无 RAW 实参的真实 helper diamond 在 `shared/ambiguity-red001` 实际 2 FAIL，
  其中 availability 错报 True。现在共享 selection ambiguity 检查，origins 保空
  recipes 与具体缺口，request binding 不产成功关联。
- **Observed / Implemented / Verified at focused scope**：recipe_context
  重新包装了 `_context` 的 rooted=False。真实递归/循环图在
  `shared/recipe-context-red002` 实际 1 FAIL；现在保 None 和精确上下文缺口。
  名为 red001 的那次尝试实际 PASS 且运行期间 root 修改了源，不是有效失败复现，
  原记录保留。两个问题的三项回归在 `shared/ambiguity-green002` 全过且源稳定。
- 综合开发期 `shared/ambiguity-green001` 实际 119 PASS / 1 FAIL，不能写为
  综合通过。先前 loop fixture 的旧 host 引用修复后，还真实暴露 checker 在一条
  未知 extraction 路线上立即返回 None，吞掉另一路确定的重复 advance。
  continuation 的 attempt008 为 51 PASS / 1 FAIL；修复只让未知分支继续保未知、
  继续扫描确定反例，attempt009 为 52 PASS、源码前后相同。其失败和所有早期
  fixture 错误均保留，没有用 native 未证来遮掩已知反例。

## 已运行的定向检查

共享层尝试记录位于
`artifacts/experiments/b1_call_operands/model_remaining_protocols/shared/`。
attempt001–003 保留了新 fixture 构造错误和一次真实 caller-context 字段连接错误，
没有用后续成功结果覆盖。attempt004 通过 12 项；补跨 helper trigger availability
后 attempt005 通过 25 项；补原 merge guard 对 raw ordinal 的相关检查后
attempt006 通过 27 项，源码在各次运行中保持不变。

随后又真实复现了普通来源的错误拒绝：中间层 formal 原样传给更深 helper 时，
leaf-only 匹配只看到了更上游 producer，漏掉原 caller/CFG 中的中间 formal。
`shared/formal-red001` 实际 1 FAIL；修复保留原 formal 支持并在该层的准确下游
call 前核 currentness，`shared/formal-green001` 的 32 项通过，源码前后相同。
另有 wrong ordinal、晚于调用才观察的 anchor 反例，防止把新连接能力变成宽松
的相等判定。不会为 helper 添加不存在的 RAW 实参。

这些检查验证合流后继续 JUMP、错接不同分支参数、缺 incoming case、遗漏真实
消费者、opaque consumer、精确 FK、prepared index 复用、无虚构 RAW 参数的
跨层 helper、旧求值及真实预算截断。它们只验声明原图连接。

另外两组正在分别运行 records/codec 与 async/continuation 的正反例，并逐组
对照原分母记录覆盖；未获得稳定统一组件或完整回归结论。本页不引用旧 full
结果来认证当前新增实现。

## 下一自主验收节点

本轮稳定最终受影响定向为 **694 PASS**，0 failure/error/skip，pytest 26.99s，
外部计时 27.679s；684 个登记源码的前后 fingerprint 均为
`3af821cb7b9486a8f7b0befc89ed56747b3ef7dcb54abf91e79a7f9be5982459`。
这是中间版本的受影响定向，不是完整16组组件或全仓回归。归档只读核验入口为
`model_remaining_protocols/implementation/checkpoint.py --check`，不启动测试。
原100个 fixture 字节和两个保护 checkout 另做守恒检查。

逐项欠账见 [async 六组台账](../artifacts/experiments/b1_call_operands/model_remaining_protocols/async/P4-2-coverage.md)
和 [continuation/组合台账](../artifacts/experiments/b1_call_operands/model_remaining_protocols/continuations/P4-2-coverage.md)。
当前不关闭完整16组中的任何一组。下一轮优先处理：

- 展开的独立 bound-method lookup→真实调用关系，不能拿 atomic helper 或
  AWAIT_LOOKUP 冒作委托方法的完整内部表示。
- request 重用/竞争、多 Create/context、首步与 body-phase 的完整组合；
  版本限定 closed/athrow/aclose 后果及 Task 当前 waiter 的真实转发链。
- 两 cut 的 close/C1、partial state/session/release，以及新家族与 P3 持续
  activation/具体 occurrence 的联合覆盖。

本轮旧 encoder 的独立 tar、生成命令、指纹、失败日志和输出保留。仅删除已逐字节
对照该 tar 的自建解压副本，精确回执位于 `records-codec/oracle-v18/cleanup-extracted.json`；
该后续清理不改写复审报告当时“仍保留解压树”的原记录。

1. 补齐每个家族的原端口/消费者及组合反例，逐原 F12–F24/X25–X27 报告缺项。
2. 复审来源独立性、known contradiction 与 gap 的区别、全 tuple/context 覆盖、
   删除附件后的分母和历史 codec 字节；发现问题先复现再修复。
3. 全部 16 组 ready 后才冻结源码，运行统一组件、干净提交和一次完整回归。
   每次失败留证，禁止自动重试 full。
4. P4 完成仍需 P5 和原 M2 的 113 构造/196 字段、完整 M0–M2 总验收，然后按
   用户要求停下来解释模型。当前没有自动拆完整 LeWM，也没有新加速结论。

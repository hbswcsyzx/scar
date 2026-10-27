# P4 后续：原图连接实施与验收记录

2026-10-18，起点 `7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`。
[本轮计划](M1_PROTOCOL_FOLLOWUP_PLAN.md)与[设计审查](../artifacts/experiments/b1_call_operands/model_protocol_followup/design-review.md)
保持原范围；完整 P4 的16组、P5、M2和完整 M0–M2仍 OPEN。

## 1. Implemented：连接什么，为什么这样连接

基本实体仍是 **Operation、Value、StateLocation、Region、Resource**。数据依赖的
规范路径是 producer → Value → ordered Use → consumer；函数到函数的数据边是
这个图的投影。静态 Operation 和一次动态 occurrence 不合并；本轮只补静态原端口
的有条件连接，未实现自动源码恢复，也未授权优化。

方法读取与随后调用是两个 Operation：

```text
准确 iterator 求值
  → lookup 的 receiver Use + 当前 state
  → lookup 自身 NORMAL 的 bound-method Value
  → 实际 call 的 receiver Use + 原有序 raw operands + 当前 state
  → call 自身 NORMAL/RAISE → 原消费者
```

这是数据依赖，不是把 iterator 和 bound method 声明为同一个对象。
新增的四个闭合 lookup rule 复用原 ProtocolCall、INVOKE 和 N/R 结果；实际调用的
expected 来源独立选择准确 lookup，actual 不能反选 expected。原 atomic helper
保持原边界，不能冒充已经展开其内部。查询复用原 prepared index、copy/caller/CFG
路线、独立消费者库存及同一个预算，不新增 producer 或状态 SSA。

lookup 的 RAISE 保本次真实 packet；没有类别判别就保
`method_lookup_exception_category_unproved`。缺方法、一般 lookup 失败、原注入包
以及 close 调用自己的新包不合并，完整 fallback 仍未关闭。

## 2. Implemented：请求状态到准入分支

从原 FinalBodyGate 先建 `request_admissions` 分母，再查可选 predicate。
每个 frontier 分别保原 R 来源、同 R 绑定、历史 truth、state snapshot 当前性、
条件兼容性和诊断。删 predicate 保 MISSING；预算不足保 NOT_CHECKED/cursor。

- 同 R、非空完整当前 READ、COMPLETE=true：潜在成功入口不相容，给 False+gap。
  静态 CFG 潜在 NORMAL 边不等于成功发生，不以此硬拒整张过近似图。
- callback 换状态：历史 bool 仍解释已走分支；当前兼容性为 None，保重检缺口。
- COMPLETE=false 只表示该谓词没排斥，不证明 admitted。
- request 首步不是 body Created。L/S 来源选择仍由准确历史分支解释；delivery
  显式标 `selection_basis=ORIGINAL_PREDICATE_EDGE`、`current_step_verified=False`。
- 首步 predicate 建 scope 索引并单列准备成本，predicate/frontier 展开扣共享预算；
  截断不得把一部分已选分支合成确定 bool。
- 状态谓词 view 使用轻量诊断 context，跳过不需要的全表 maps/inventory 准备；
  主分析仍完整准备。避免每个谓词再做一次整表准备，不改变原状态/来源规则。

同一个 Create 来源经过两个原 caller 的 recipes 都保留；这不是 native request
身份、复用或两次实际运行 occurrence 的证明。跨 callee session 摘要仍缺。

## 3. Observed / Rejected：复审发现的错误证明

真实反例：先求值 B，再求值 A；两个原分支让前次 SEND 的 receiver φ=A|B，
随后对 A 声明 InitialAdvance。无 guard 的 must-copy=False，并不证明所有分支都
没推进 A。原检查曾错误给后续 InitialAdvance `DECLARED`。

首个反例尝试因 fixture 中纯 CONTROL 操作仍声明 unknown effects 而被保守 gap
遮住，实际为1P；报告不把它称复现。只修正新 fixture 的真实无副作用 CONTROL
声明后，第二尝试真实1F，旧产品未回退。修复联合 prior/current 原 guard，保留
混合或未解析路线，possible copy 不能被 must=False 当成不存在。原确定重复的
loop 拒例继续保留。所有尝试各自留命令、JUnit、日志和前后源码指纹。

另一审查意见把旧历史 L/S 选择误读成当前 phase 断言；回看批准语义和原正例后
撤回。采纳的具体问题是扫描计费不足，并补显式历史来源标记，未破坏 normalizer
改变 state 后仍沿已选原分支供 L 的合法连接。

## 4. Implemented：wire 兼容

新闭合 rule 选择 **Program20**；旧能力仍选原1–19 family，Execution仍8。
仅旧19 shape 不能授新20语义；降级 envelope 和不含新能力的假20都拒绝。
删除可选连接表而保留 lookup rule，仍须选择20并保缺失义务。

独立 Program19 golden 来自冻结 `7dd8c54` encoder 的隔离子进程；不是用新 encoder
伪造。旧 tar、生成命令、失败和成功输出、模块来源与 SHA 保留。旧 fixture 字节
及原 wire 版本不改；旧测试只更新 codec 最大版本断言。

## 5. Proposed：下一步仍按原分母推进

完整 F12–F24/X25–X27 的16组本轮均未关闭：方法缺失类别及原包 fallback、R 的
多次驱动/竞争和跨callee session、两cut C1、partial state/release、与P3实际发生
的联合检查仍需完成。全部就绪后才统一 component、干净提交和一次 frozen full。
之后还有 P5 与原 M2 的113构造/196字段，完整 M0–M2后按用户要求停下来讲解。

当前没有新 detector/backend、LeWM 特殊规则、LeWM transform、重型 profile或
新加速比。源/native适用、原图连接、动态身份和变换权限始终分别报告。

## 6. Verified：本轮自主验收

状态 **PASS_WITH_SCOPE_WIP**。这是有界后续任务的验收，不是完整 P4 或 M0–M2。
三位作者全部停止 source/tests/evidence 写入后，root只运行一次最终统一相关定向：

- **746 passed / 0 failed / 0 errors / 0 skipped**；746个唯一 JUnit case identity。
- pytest **29.82s**，runner wall **30.511102779s**；Python **3.14.7**，conda **lewm**。
- **689**个登记源码，前后指纹同为
  `5b1ba427ac6475a4fa36b26febf445c7bd80e70210fe3f53f006fe8b060295f8`。
- 旧694项的28个文件选择全部保留，加三个新测试文件和必要的旧 lifecycle codec
  文件。精确命令、选择、JUnit、日志、全部源码前后 SHA见 `final-focused/`。
  不把开发期24/77/51/387重复累加成更多独立用例。
- 最后的轻量 prepare 修改包含在这份最终源码里；B此前51P没有冒作它的验证。

| 本轮节点 | 结果与范围 |
| --- | --- |
| D | 三路限定设计审查通过；冻结计划 SHA `44437087…`，不改原合同。 |
| L | 四种展开 lookup→call、原N/R、branch tuple、错误同型/旧求值、删除/预算通过。完整missing fallback仍缺。 |
| A | 原 request predicate/branch/gate、历史与当前支持、来源选择及预算通过。完整多次驱动/竞争仍缺。 |
| W | 新20能力/旧19独立oracle、缺表、降级/假升级/future/bool及受影响旧wire通过。 |
| R | 三路最终只读复审和本次746项通过；具体false-proof修复，首败完整保留。 |
| V | 只读archive检查记录源/证据、旧fixture、原合同与保护checkout；结果以checkpoint.json为准。 |

证据根目录：
`artifacts/experiments/b1_call_operands/model_protocol_followup/`。
`checkpoint.py --write/--check`只做归档核对，**不启动测试**；首次write拒绝覆盖。
历史 `model_remaining_protocols/` 证据不覆盖。本轮源码没有完整回归；上次完整
5,822P仍只归 `8138986`，不归本轮Program20源码。

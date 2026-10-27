# P2 完整同步 generator 矩阵实施计划

2026-10-18。基线 `b88670b`；[基础检查点](M1_PROTOCOL_FOUNDATION_ACCEPTANCE.md)
已有 5,401 项冻结回归。本计划落实[父计划](M1_PROTOCOL_FAMILY_PLAN.md)完整 P2，
不将基础检查点改名为整门。P3–P5、M2 与完整第一阶段仍保留原分母。

## 1. 本门要补的连接

```text
caller 的实际 raw pack / 原 operand / 原 literal 附件
    → 每个静态 CALL/INVOKE 的有序 actual/formal recipe
    → driver 当前输入
    → 原状态读取或 arg-is-None 操作 → 原 bool → 原 BRANCH
    → 准入后 Start / Resume，或无 body 的拒绝/关闭路线
    → 本次 body 首出口或实际 helper N/R
    → host adapter、当前状态与历史 F
```

这些全是原 Operation/Value/Use/State/CFG/call 的连接，不增加一套实际生产者、
phase 变量、entered/finished 许可或第二状态链。多 caller 保留各自 recipe；
同一静态生产者多次执行不冒充同一个逻辑版本。缺运行发生仍由 P3/M4 处理。

## 2. 先审模型，再实施

现有五类 F contract 没有表达“原状态谓词与被它控制的分支”这一明确关联。
现 RequestProcessing 自有 bool、state_sites 和 scope label 不足以表示它；
也不能为了合同给 `gi_running` 读取或 `arg is None` 人为增加 raw/body 实参。
先独立收敛最小只读谓词附件，再冻结 amendment；不得为兼容已有代码隐去缺口。
若确需新 variant，Program18 单独选择，保存独立 v17 golden，旧五类 wire 不变。
本轮真实重试构图另发现仅RAISE调用缺口，按[completion amendment](M1_INVOKE_COMPLETION_AMENDMENT.md)
允许一般INVOKE使用准确非空completion子集；同属未发布18，特殊gate仍要求双边。

阶段条件在实际读取/分支处是否 current，与后续 callback 之后 FinalBodyGate
是否重新检查当前状态是两个问题。不能把前一次 read 保证延长成永久 phase
事实，也不能为了这种延长而禁止程序中合法的 callback。

## 3. 自主验收节点

| 节点 | 交付 | 必需证据 / 失败条件 |
| --- | --- | --- |
| P2-A 事实与字段 | 本机有界 CPython 矩阵；Created/Running 与 Suspended/Closed 独立审查；谓词及原端口 amendment。 | 每项区分 native 观察、结构缺口和未证 source 适用；不按异常类型独断 F；不能用假 Use 填合同。 |
| P2-B 完整实现 | 精确静态 caller recipes；准入/谓词/branch 与 Start/Resume；no-entry、close、完成 adapter 及 consumer。 | 所有 16 格及下面各变体有正图和错误来源/状态/出口反例；不能 firstmatch caller、靠行存在放行，或借 STATE 槽冒 payload。 |
| P2-C 组合与冻结 | focused → 组件 → 干净提交 → 一次全仓 → 只读守恒/保护目录/归档 → commit/push。 | 所有原 case/fixtures 保留；预算截断不删义务；原失败保留；全仓运行期间所有作者停写，无并行测试/工作负载。 |

各节点由 agent 自验收，不等待用户审批。本门最终 PASS 需要完整 P2-B 范围；
若仍有实质模型缺口就继续修，不按测试数或部分组件数量宣称通过。

## 4. 不可删除的矩阵与变体

| 当前条件 | NEXT | SEND | THROW | CLOSE |
| --- | --- | --- | --- | --- |
| Created | 正确 Start，无假 resume | None 可 Start；non-None 拒绝后仍可启动 | instance/class、原参数、校验失败、构造 callback 失败、无用户入口的实际终结 | 不进 body；原 CreatedCloseTest 真分支与 NoBodyFinish |
| Running | 重入拒绝，外层继续 | 重入拒绝及原参数顺序 | 校验/规范化与重入次序、外层仍可继续 | 重入拒绝，不假终结 |
| Suspended | 本次准确 None → SENT_VALUE | 本次 ordinal0 → SENT_VALUE | packet/traceback、捕获继续或传播、准确首出口和当前状态 | Return(value)、GeneratorExit 消解、其他异常传播、非法 YIELD 后仍可续体及 retry |
| Closed | 当前完成异常，不重放旧值 | 当前完成异常，不重放旧值 | 当前参数/规范化/异常，不重放旧 packet | 当前正常结果，无假 Drive/新 F |

另外核：body 内主动 StopIteration、暂停后外来 StopIteration escaping 与
Created.throw(StopIteration) 的不同转换；前置错误不等于进入 body；多个 N/R
post-state、callback 失效、跨循环旧版本、C1/context 和 release 的原连接。

RawRequestDefinition 保留 NEXT/CLOSE 零参、SEND 一参、THROW 一至三参的有效协议
形状。调用绑定阶段的非法 arity 在形成有效 raw 之前建模为原调用失败，不能
放宽 raw pack 类型或伪造 body drive 来表示它。

## 5. 归属与公开限制

本批 caller 来源、只读谓词和 close 规则均为通用程序/语言协议接口，核心不得
出现 LeWM 业务名。native observer 只观察本机，不是自动前端或运行图捕获。
supplied IR 的结构验证不等于 source inventory、native 适用或 runtime identity
已证明；这些缺口必须精确返回，不给 planner 变换授权。

全阶段顺序仍为完整 M0–M2 → 先向用户讲解 → 自动恢复/证据对应/依赖闭合 →
化简指导。当前不新增 detector/backend，不重跑 LeWM 重型 profiling，不宣称加速。

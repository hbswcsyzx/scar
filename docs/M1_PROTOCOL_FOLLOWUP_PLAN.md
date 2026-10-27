# P4 后续连接：展开的方法与请求准入

2026-10-18。起点 `7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`。
本补充不修改 P1/P4-v1 冻结合同，不缩减 F12–F24/X25–X27 的 16 组分母。
本轮是其中两个连接缺口的有界实施；全部组就绪前不运行组件或 full。

## 1. 模型决定

Operation、Value、StateLocation、Region、Resource 仍是基本实体。方法查找、
方法调用、状态读取、分支都是原 Operation；接收者、结果与状态是原端口角色。
不加第二套 producer、状态 SSA 或执行历史。每个 INVOKE 的 NORMAL 与 RAISE
都保留原结果和状态，即使当前只知道原连接而不知道具体 Python 实现。

```text
source → GetIterator / __await__() → iterator
    → method lookup(iterator, current state)
        NORMAL → bound method → actual call(raw operands, current state)
        RAISE  → original packet → real exceptional consumer
```

调用的 receiver 是 bound method 时，不能以 iterator 本身冒作这个原 Use。
原 atomic helper 表达仍有效，但它不证明 helper 内部已经展开或验证。
expanded/atomic 的 expected 来源独立声明；actual 只能核对，不能反选 expected。

## 2. 最小补充接口

复用现有 `ProtocolCall`，新增四个闭合 rule：

- `DELEGATE_NEXT_LOOKUP`、`DELEGATE_SEND_LOOKUP`；
- `DELEGATE_THROW_LOOKUP`、`DELEGATE_CLOSE_LOOKUP`。

它们分别只允许在原 DELEGATE_ADVANCE、DELEGATE_THROW、DELEGATE_CLOSE clause。
查找本身无 request 参数/trigger，receiver 独立指准确 iterator 求值。
实际 DELEGATE_* 调用的 case.receiver 可指匹配种类 lookup 的自身 NORMAL
`ContractResult`；原 Use 必须当前复制这个结果，查找 receiver 另核准确 iterator。
查找 RAISE、另一 lookup、另一 iterator、错误规则或旧求值不能替换。
原 formal/合流继续逐 incoming 和整组 caller/guard 上下文核对；无法唯一解释
就保具体缺口，不能以 ANY 成功覆盖所有已知路线。

独立方法查找不是普通 copy：不能把 bound method 放进 iterator 的复制闭包。
实际输出消费者仍由原端口/有序 Uses/CFG 派生库存，再与附件比较。删附件不消除
查找自身 N/R 的义务。保留 unknown effect/category，不宣称 native applicability。

### 查找失败

RAISE 不等于方法缺失。按 [PEP 380 的展开形式](https://peps.python.org/pep-0380/#formal-semantics)，
缺 `throw` 和缺 `close` 对原注入异常的处理不同于一般 lookup 异常。
本轮只接受原图真实 packet/consumer 连接；没有原异常类别判别及准确分支时，
保持 `method_lookup_exception_category_unproved`，不自动吞包或恢复旧包。
完整 missing-method fallback 仍是原 F21/F22/F23 未关闭项。

## 3. 历史 wire 边界

Program19 已有真实编码归档，因此新闭合 rule 选择 Program20 能力；Execution
仍 8。Program20 与 19 共用现有字段和严格 tags，不新增表。只含旧能力的图仍选
原 1–19 family，已有 JSON 字节不变。19 或更早 envelope 装新规则必须拒绝；
20 envelope 不含新能力也拒绝。验证/query 能力检测与 codec 共享一个规则来源。
独立 Program19 golden 必须由 `7dd8c54` 的旧 encoder 子进程生成并保 source tar、
生成命令和 SHA，不能用新 encoder 伪造。只更新旧测试的最大版本断言；原 wire
版本与旧 fixture 不改。

## 4. 请求准入的有界目标

R 是 request；B 是 body；S 是本次 scheduler；L 是创建时 latent request。
`IS_INITIAL_STEP` 与 `IS_COMPLETE` 都应使用真实 R 的只读状态 → 自身 bool →
准确原 BRANCH，不能借另一个同型 R 的谓词。
历史分支仍是合法控制事实；callback 后旧 snapshot 不再证明当前准入。
当前 complete=True 与成功进入 body 冲突，但静态过近似 CFG 的 gate 潜在 NORMAL
边不等于发生了成功入口。沿现 Running/Closed 政策，frontier 报兼容 False 和具体
缺口，不以此硬拒整张静态图；实际成功 occurrence 的矛盾留给 P3 联合检查。
没有 current 支持则兼容 None，不能因为 bool 为 true 就对任意 gate 宣称非法。
已知错 R/错 bool 的原端口连接仍应拒绝，未知 native 身份不能按 ValueID 猜不同。
所有检查只约束供应的静态图，不证明 Python 真实 request phase，也不替代真实
driver/native admission。每个原 gate 的分母先建立；删 predicate 仍 MISSING。

同一 R 多次 driver 调用、session HOLD → 续步 → COMPLETE、再调用拒绝，以及
R2 竞争的完整组合须继续做；跨 callee 的 state/session 传播必须沿原 caller 输入、
selected completion 和状态输出联合，不从同名 state 或单个 post 推断。
本轮不能以单次 factory 参数化测试宣称上述完整组合已经实现。

## 5. 自主验收顺序

| 节点 | 必需证据 | 拒绝条件 |
| --- | --- | --- |
| D | 三路源码审查、上述接口决定及固定分母 | 新建事实图、按 actual 选 expected、将查找异常都算缺方法 |
| L | 四种展开查找/调用的原图 N/R 正例、错误种类/结果/接收者、删除/预算反例 | 只有 enum/类型检查，没有真实原 Use 连接 |
| A | R 的自身 predicate/branch/gate 与 stale/错 R 反例 | 跨 callback 保活旧许可或无 current 支持仍判已证 |
| W | Program20 新能力，独立19 golden及旧 family，降级/假升级拒绝 | 改历史 fixture 字节、旧 reader 静默收新能力 |
| R | 只读交叉复审及统一受影响 focused | 已知错接被 gap 洗掉、失败日志覆盖、用定向冒 full |
| V | 源码/证据指纹、保护 checkout、报告、独立 WIP commit/push | 误关完整16组、声称自动 LeWM 或新加速 |

必要定向只解决具体风险，留首败，不自动重试 full。并行开发期可做小定向，
各自源码稳定性与全局稳定性分别报告；最终定向须所有作者冻结。
所有新证据写入 `artifacts/experiments/b1_call_operands/model_protocol_followup/`；
旧 `model_remaining_protocols/` 检查点不覆盖，当前 source 变化不归因旧测试。

下一步仍按原 P4 → P5 → M2 的 113 构造/196 字段 → 完整 M0–M2 验收。
本轮不加 detector/backend，不跑重型 LeWM profiling，不生成未经测量的加速比。

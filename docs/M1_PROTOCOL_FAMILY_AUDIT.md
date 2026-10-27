# C2/D3：协议家族与发生连接审计

2026-10-18，基线 `08c4cbfc6b675919ab15e8654567889727f3c466`。
**本轮完成源码审计及有界观察；D3 字段尚未冻结，产品未扩展。完整 M0–M2 未完成。**
后续按 [实施计划](M1_PROTOCOL_FAMILY_PLAN.md) 自主推进，不等待用户逐门审批。

## 1. 当前缺少的是哪些关系

Operation、Value、StateLocation、Region、Resource 五类基础实体继续使用。
请求处理、委托、异常构造、body 执行和调用方结果适配都能由这些实体承载。
当前问题是协议关系与特定原端口之间的约束不全，并非缺少另一套家族枚举。

```text
原有序参数/receiver/当前状态
  → request 创建或读取 → raw/latent 请求的实际选择
  → 参数检查/异常规范化/真实委托/当前资格分支
       ├─ 不进入用户 body：拒绝、委托结果或初入终结
       └─ 原 gate → BodyDrive → 本次 body 入口/执行段
                                  → 首 Suspend / Return / Raise
  → 当前原结果适配/请求与body后态 → host Return / Raise
```

每条箭头必须连接原 producer、有序 Use、具体 CFG 边及当前状态。图中存在一段
普通调用，不等于这段调用已经满足某个版本协议。反之，不能因内部未展开而把
周围已经知道的参数、状态、正常/异常结果及消费者一并抹掉。

## 2. 保留已有实现，避免重做

| 已有接口 | 已实现的有限约束 | 仍不能由它证明 |
| --- | --- | --- |
| ResumableBody / Suspend | 四种 body 家族、允许的 suspension flavor、saved Uses、新状态入口及 cut availability | 完整方法行为、真实 code flags 或实例身份。 |
| Initial / Attach / Detach、C1 | 私有 context、当前 caller、pending/finally 与逐边准确转发 | 实际解释器切换、运行时 frame 完整捕获。 |
| Create / raw / async request / association | 已绑定 captures、原参数顺序和 arity、原 NORMAL 结果及 RAISE 部分后态 | 请求创建已经驱动 body，或 raw 标签已经构造了异常。 |
| FinalBodyGate / BodyDrive | 当前状态全域后态、角色独立转发、唯一私有入口及首出口分母 | SEND/THROW 的真实交付值正确、host 结果满足家族协议。 |
| D2 publication / no-body / E-F-P / release | 有条件的历史终态、当前 session、真实分支与窄引用放弃 | 任意 no-body 路径都等于 Created-close；host 异常都使 body 终结。 |
| Execution ResumeIngress | 原 suspension occurrence→新 segment，持续 activation 与准确 temporal transfer | 本次 BodyDrive 与这个实际执行段/出口已经相连。 |

DriverRule 当前只有 PYTHON_RESUMPTION_V1 与 implementation FactRef，没有
UNKNOWN/EXTERNAL 枚举。UNKNOWN 是适用条件状态；它不会关闭已有结构校验。
source/native 适用性未知不应被误报成“没有任何图关系”。

## 3. 两条必须补齐的主线

### F：协议义务连接原 CFG 与端口

当前 validator 主要校验 raw arity、slot 类型、gate 转发、body 首出口和生命周期。
尚缺下列协议连接：

- SEND 原操作数 / NEXT 的 None / THROW 的真实规范化结果，到实际 delivery。
- async scheduler 请求与 latent 请求各自的角色及选用路线。
- body Return、body 内部 Raise 和初入前注入，到各自准确的 host adapter。
- delegate-only、await 中间结果、request 完成与 body 暂停/终结之间的区别。
- no-body 的真实前置条件、部分效果和终结来源；取消请求与实际交付的区别。

新增协议 scope 后，必需义务必须由固定版本合同派生；省掉一个连接只能造成
MISSING/PARTIAL，不能让分母消失。旧 generic D1 图保持原范围，不静默升级为
完整 Python 协议。不能靠名字、同类型 payload 或任意可写 phase/verified 字段授权。

### O：本次 Drive 与持续 body 的实际发生关联

当前 ExecutionModel 无 BodyDrive occurrence→持续 body activation→本次入口/segment
及首 outcome 的关联；composition_routes 对 BodyDriveResult 明确保留
dynamic_occurrence=None。同步 CallActivation 要求 static callee，且一个 activation
只对应一个 caller，不能拿来表达多次恢复的持续 body。

最小新关系只引用原 drive occurrence、activation、entry visit 和 outcome occurrence，
缺捕获使用现 Unresolved/FactSource。segment 从 entry visit 派生，generation 锚定
原 suspension occurrence，不再维护一份整数代次、actual、保存列表或结果图。
具体字段、键及 instance/capture 连接仍待下一节点独立复审。
NO_USER_ENTRY 和 delegate-only 路径没有父 BodyDrive，使用原 host/helper/adapter
发生的 F 关系表达；不得为填这条 O 关联而伪造 Drive、body 入口或 body outcome。

同一 body 可由多个 drive 分次恢复，也可分次换线程；本次同步执行段可核线程，
不能强制所有历史 segment 同线程。Start captures、Resume saved/current inputs 和
结果都必须沿原 UseOccurrence/ValueOccurrence 及实际 transfer 回查。缺失不是 NONE，
同内容不是同对象，当前 owner 的源码/运行对应也不能由静态 site 猜出。

**给定关联能否表达和拒错属于 M1；从真实运行自动采集它属于 M4。** 不将接口
缺失整个推迟到自动采集阶段，也不把手工声明接口当自动恢复已实现。

## 4. 本轮实际观察与被推翻的假设

### 4.1 五项现有 IR 观察

使用当前未改产品及原 fixture 构造四个有效 D1 图和一个 wrong-flavor 反例：

| 观察 | 实际结果 | 准确结论 |
| --- | --- | --- |
| generator Start→Suspend | structural issues 为空，driver Return | 原端口结构有效；没有因此验证 Python adapter。 |
| generator Resume→Return | body Return 可直接接 driver Return，结构有效 | D1 未校 next/send 的完成适配。不是旧合同 bug。 |
| packet Resume→Raise | 原 Raise→driver Raise，结构有效 | 仍需区分真实异常来源和转换规则。 |
| GENERATOR + ASYNC_REQUEST | generic 结构有效 | receiver 角色存在不证明某个 native 家族组合合法。 |
| COROUTINE + YIELD | resumption_flavor 拒绝 | 家族/flavor 检查已经实现，不能再列为待补 enum。 |

记录：归档 current_core_probe.json。这是声明 IR 观察，不是 Python 协议运行测试。

### 4.2 六项启动前 throw 观察

为了消除一个具体字段决策风险，仅新增了一次有界 stdlib CPU 见证。CPython
3.14.7 的原六项结果先写 JSON，随后首个错误预期触发 AssertionError/exit1；
脚本、JSON 和工具返回 traceback 转录全部保留，未改原脚本或重跑这六项。

| 样例 | throw 后状态与结果 | 用户 body/finally 日志 |
| --- | --- | --- |
| generator + ValueError 实例 | GEN_CLOSED；ValueError | 空 |
| generator + 非法参数42 | TypeError；仍 GEN_CREATED，随后 next 可启动 | throw 时空；后续启动/cleanup 另记录 |
| generator + 异常构造器回调抛 RuntimeError | GEN_CLOSED；构造器确实执行 | 空 |
| generator + StopIteration 实例 | GEN_CLOSED；原 StopIteration，cause=None | 空 |
| native coroutine + ValueError 实例 | CORO_CLOSED；ValueError | 空 |
| asyncgen + ValueError 实例 | 创建 athrow request 时 AGEN_CREATED；驱动后 AGEN_CLOSED | 空 |

**Rejected：** “异常规范化阶段发生错误就一定仍 Created”已被构造器样例反证。
该推断由语言审查提出、root 采纳；root 另写入的“初入 StopIteration 必转
RuntimeError”预期也被 JSON 反证，但原执行尚未到这个后续断言。不能把两个
错误预期改写成两次已执行的失败断言。

后续只读 checker 核验保存的数据、脚本 hash 和具体观察，不执行原见证或测试。
它通过不等于原见证的断言通过。inspect 标签/空 body 日志也不证明没有任何
解释器指令、frame 切换或底层释放发生。

设计必须分别表达前置拒绝、规范化/回调的实际路线、无用户入口的初入注入
终结，以及已进入 body 的 Raise。CreatedCloseTest 的专用真分支不适用于它们。
暂定采用明确的 no-user-entry 路线，不向函数形参塞入假 SEND/packet；准确的
规范化产出、终结提交与 host adapter 字段仍须冻结后再实施。

## 5. 证据与权限

三份独立分工报告见归档 design/：family-obligations、core-connections、
independent-scope。独立结论为 OPEN_WITH_BOUNDED_PLAN，**不是设计或产品 PASS**。
各表有重叠，不能把其行数相加成协议覆盖率。原旧语言见证只读复用，不重跑。

原产品603文件 SHA 保持
`7d3187f36f6cca07e0714a49ac20dbe1c0634601568f2986ef8f0c178431f7a9`，
此前冻结 `4bc55eb` 的5,294全仓结果仍归属上一门，本轮没有运行新的 pytest/full。
未新增 backend/detector/lowerer、GPU/LeWM profiling 或速度结论。

版本依据使用 [Python generator 方法](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)、
[coroutine 对象](https://docs.python.org/3.14/reference/datamodel.html#coroutine-objects)、
[PEP525](https://peps.python.org/pep-0525/) 与
[CPython3.14.7 genobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c)。
网页当前3.14.8不冒充本机实测；本轮六组观察只约束所记录的3.14.7样例，不能
推广成全部解释器/协议路径。完整模型、自动 LeWM 建图与化简仍未完成。

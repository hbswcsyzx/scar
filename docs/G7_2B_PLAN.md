# G7.2b：先补证明所需实体，再打开正向 REUSE / MOTION

状态：**Step 1 模型基础已验收；G7.2b 正向证明尚未验收**。依据 `603819d` 的代码和三个 Luna max 子代理的
独立只读审查。G7.2a 已归档；本阶段不添加 backend，不改目标源文件。
Step 1 的实现、55 项 gate、995 项回归和外部源实测见
[G7_2B_MODELS_ACCEPTANCE.md](G7_2B_MODELS_ACCEPTANCE.md)。继续执行 Step 2。

## 1. 为什么当前两个家族全部拒绝

不是候选数量问题。当前四项 REUSE 与六项 MOTION 义务均为 UNKNOWN，终态固定为
NOT_YET_SUPPORTED。它们缺少的不是一个“批准”开关：

| 必要事实 | 当前缺口 | 要进入的模型 |
| --- | --- | --- |
| 一次调用的某个输入/状态/输出槽到底是哪版数据 | observation 有 role 无 slot，correspondence 有 slot/version 无 invocation，无法唯一连接 | InvocationSlotBinding，instance × role × slot × handle × event |
| 相同输入是否仍有效 | 相同 VersionID 不排除外部 alias 写 | 独立 ProvenanceRegistry 的绑定区间、mutation coverage、readiness 和 guard |
| 原语是否可互换 | eval/module 重复不是纯性或 ownership 证明 | 从真实源码重算的有限 PrimitiveSemantics，而非 pure=True |
| 更高层的精确放置点 | control parent 只表示包含关系 | SourceControlFlowGraph 与 source-bound InsertionPoint |
| 所有进入路径、循环零次及异常 | 当前 block 字符串和控制树不是 CFG | normal/branch/backedge/zero-exit/exception 的类型化连接及明确缺口 |
| 实际修改内容与失效 | RegionMove 只含两个 control ID | source fragment、目标 anchor、绑定/值闭包及单独静态 move 差量 |

重复计数、共同祖先、值来源位于第 3 层都只帮助定位候选。要从第 8 层上移，必须
同时知道第 3 层具体 entry 的可用输入、控制路径、跨过的效果和新 live range。

## 2. 执行顺序与文件范围

### Step 1 — 可连接的证据实体

三个子代理并行，主代理负责模型约束、集成和独立攻击性审查：

1. invocation slot overlay：独立 typed record，不把 metadata/role 推猜为已观察
   slot。检查完整 slot 清单、instance definition、registry 的实际 binding interval、
   version/materialization/object、scope/clock 与 evidence，保留缺项状态。
   definition.input_slots 是本操作拥有的 formal 接口；READS_SLOT 指向实际读取的
   源槽，可能属于另一操作。两者不能混填。overlay 用单独 READ role 连接实际
   读取，精确核对 READS_SLOT；有序/重复操作数仍由 source overlay 表达。
2. source control-flow overlay：source replay 后构造有限 Python AST 控制骨架，
   entry/exit、顺序、分支和循环路径分开。语句可抛异常时保留异常连接/未解析 handler
   缺口；unsupported construct 不落成普通顺序边。插入点绑定实际 suite 和 statement。
3. primitive semantics：首先补 Python `is` / `is not` 的单次二元操作到 source
   overlay；不执行用户比较，不用任意函数纯性声明。固定规则保留输入对象身份、
   bool singleton 输出、无用户 dispatch 的适用条件和观察范围。

本 step 的测试只验结构、源码重算和有效性查询，不宣称正向 REUSE/MOTION 已成立。
overlay 与 SG/EEG/value graph 并列，不因“有这张图”就成为优化许可。
`gates/g7_2b_models.json` 单独检查这些模型输入；它不代替下面的正向证明验收。
`proof-models-v2` 保存控制图、精确 source insertion anchor 和原语证书，不输出
优化审批。Python bool/object-only 输出仍需非 tensor 的真实 materialization 模型；
当前 registry 的 tensor region 不能为正例伪造该输出。

### Step 2 — 差量、义务与正向证明

先新增精确 static source fragment / insertion 差量，再接入固定账本。每个新增
证据模型、源码版本、规则版本、Q、scope、event 与 registry 都进入摘要和重算。
动态 pair 必须精确对应被删除 invocation；动态路径证明不得升级为跨运行 all-path。

REUSE 固定义务分别检查：完整 input/state、effect/RNG/exception/ordering、output
identity/alias/ownership、autograd/hooks/consumer。以具备真实 typed slot/对象见证的
`is` 原语建立第一个窄正例，不把该原语推广为任意 Python/PyTorch module 可缓存。
guard 缺失、mutation coverage 不闭合或动态路径无 fallback 的请求不放行。

MOTION 首先验证同一无分支 suite 内的上移：

```python
def f():
    token = ()
    marker = 1 + 2
    alias = token
    return alias
```

可提出把 `alias = token` 移至 `token` 定义之后。必须重算目标 availability、整个
语句的 binding 效果、跨越 marker 的总性/效果、全部 uses、身份/live range 和精确
source anchor。frame locals、外部干预及资源失败的语义边界明确列入 scoped Q。
这不是循环 hoist 证明。后者还要 invariance、循环路径/零次、异常及每轮 alias。

若某种粒度尚无正向能力，其状态仍 NOT_YET_SUPPORTED；不能用改 outcome 常量或
传入一条手写 PROVEN 来通过。Q 只限定可观察行为/可接受前提，不能凭声明生成
两次输入相等、没有 mutation 或正确 autograd 图的事实。

### Step 3 — G7.2b 自行验收

1. 每种 overlay 的 strict serde、dangling/type/scope/duplicate/stale 拒绝和源码重算。
2. REUSE 至少一个全义务可重算正例，以及改变输入、foreign alias、状态/RNG、异常、
   输出 identity/mutation、autograd/hooks、缺少 guard/fallback 的拒绝反例。
3. MOTION 至少一个精确同 suite 上移正例；额外执行、zero-trip、不可用输入、跨
   handler/finally、alias write、mutable allocation、binding finalizer 不能误批准。
4. 篡改 premise、源码、Q、registry、source anchor、delta 和缺失义务的账本重算拒绝。
5. 专项 gate、整仓回归、通用外部源码报告、分析资源成本、实现与验收分别提交并推送。

只有 Step 2 的正向能力和 Step 3 全部成立，才写 **G7.2b Verified**。Step 1 的
结构验收不会替代该结果。目标源码和环境保持原状；本阶段没有 clean A/B 加速结论。

## 3. 后续连接（不抢跑）

G7.3 将 import provenance 的 typed witness 精确接入 CONSTANT ledger；每条
REQUIRED_CONTRACT 以种类、operation/module 和内容摘要匹配 Q，不由同一个泛化
“普通运行环境”通吃。SOURCE_BLOCKER 不能通过声明 Q 消除。

值替换和 import 删除各有独立 delta/ledger，组合计划依赖二者。初始化、loader/
cache、异常和其他消费者仍需 DEAD 的闭包证明。不能因为路径终点是常量而删除
整包。source change 指令携带精确 source span/fingerprint、替代 literal、provenance、
proof、guard、失效条件、residual、validation 和 fallback，不自动改源文件。

G7.4 再用外部 LeWM 源码和既有 execution evidence 做压力验证，回答实际卡在哪个
具体义务。G8 接成本/冲突选择，G9 分层验证，G10 才评审是否开放 backend。

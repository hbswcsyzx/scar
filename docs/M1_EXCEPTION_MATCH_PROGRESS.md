# 通用异常匹配：模型、连接与有界验收

2026-10-18。依据[冻结计划](M1_EXCEPTION_MATCH_PLAN.md)，基线 `8f08bda`。
原 F12–F24/X25–X27 共 16 组仍全部 OPEN，本轮没有完成整个 P4/M0–M2。

## 1. 为什么需要这项模型

**Observed:** 原模型能表示 lookup 的 NORMAL/RAISE 原端口，但没有通用
“异常输入、handler、matcher 自己的结果、branch”契约。只有 for lowering
中的 MATCH_STOP_ITERATION 特例。原 AdmissionPredicate 要求普通、只读、无
callback，不能容纳动态 handler 类型检查导致的 matcher 自身 RAISE。

真实图的 lookup RAISE 可以已经被一个 matcher 消费，旧 continuation query
却只能保留 category gap，没有这条已存在的原连接。
`model_exception_matches/red-lookup-matcher/` 保存原公开 query 的真实首红：
bare core 和完整 graph 均合法，断言实际消费者连接不存在而失败；不是新 API
未定义导致的错误。

**Implemented:** 基础实体仍是 Operation / Value / StateLocation / Region /
Resource。`ProgramGraph.exception_matches` 是按原 operation 建自然键的解释
附件，不生产 Value，不建立第二份调用/状态图，也不为普通 except 造协议 scope。

```text
独立 exception Reference / whole packet source → 原 input Use
独立动态 handler source → 原 handler Reference Use（实际存在时）
    + 原 state input/access
    → 原 matcher Operation（可展开已知 callee Region）
        NORMAL → 自己的 bool → 原 BRANCH → true / false 原边
        RAISE  → 自己的新 packet + 各自原完成状态 → 原消费者
```

## 2. 哪些部分有独立含义

- `FixedBuiltinHandler`：声明固定 intrinsic 的条件解释，没有虚构 handler Use。
- `ExceptionHandlerOperand`：原动态 class/tuple 的真实 Reference Use、独立来源
  及条件解释；不能凭名字或对象同型判 builtin。
- `ExceptionMatcher`：原输入、独立 expected source、准确自身 normal/raise
  result、真实 bool branch 和原 state sites。Reference 与整体 packet 角色不同，
  没有真实 packet-component projection 依据时不伪加实参或复制关系。
- ordinary 只读 primitive 只能有自身普通 bool；INVOKE 支持真实 N/R 非空子集，
  only-RAISE 不造 NORMAL/bool/branch。真实完成不能通过 None 从分母删除。
- handler 表达式求值、类型匹配、handled-context 安装、handler body 与 cleanup
  不合成“无效应节点”；except* 不由普通 except matcher 冒充。

语言边界核对使用 [Python 3.14 except 规范](https://docs.python.org/3.14/reference/compound_stmts.html#except-clause)
和 [PEP 380](https://peps.python.org/pep-0380/#formal-semantics)，没有用第三方解释
替代原端口证据；本机运行环境保持 lewm 的 Python 3.14.7。

## 3. 检查如何复用原图

结构检查验证准确 owned Use、实际 invocation argument 而非 edge-forward Use、
Reference/packet 角色、独立 handler、原 N/R kind/slot 与 bool/packet 类型、真实
branch，以及全部原 state accesses/operands。

准备后的 `ProgramIndex.exception_match(operation, budget=4096)` 使用原
ConnectionContext/source binding/caller/CFG 关联，核整个输入 tuple 及自身 bool
到 branch 的本次复制。复用同一 consumer ledger 派生自身 N/R 的原消费者，
没有复制第二套 consumer 算法。所有复制仍服从原 fresh reset 和实际端口。

状态报告沿每条真实 completion edge 的 argument/formal 对齐：

- 产生的 `CompletionResult` 保准确 `InvokeLiteralResult`，不混 edge 号/slot/
  landing ordinal；
- 未改状态的原 forwarded Use 保 `OwnedUse`，`result=None`，不能因为签名没有
  state result 就丢掉真实 state formal；
- 历史 bool 可继续用于控制，但不是 callback 后所有状态永久 current 的证明。

lookup RAISE 从既有独立 consumer ledger 找到真实 matcher input，再核独立来源；
报告在原 lookup obligation 的 `method_exception_matches` 中保 matcher、binding
和 query 证据。删除附件后，原 lookup、RAISE 和实际消费者仍保留义务。

## 4. 真实反例、修复与成本

**Observed:** 三路只读复审后又构造了两个合法 core 反例，分别被初版误拒/漏报。
`red-expanded-and-forwarded/` 为真实 2 FAIL：

1. 已知 callee 的真实 INVOKE 被普通 primitive 的禁止 callee 条件一并拒绝。
   修为仅 ordinary primitive 限制，INVOKE 继续按自己准确的原接口检查。
2. effects-complete INVOKE 的状态通过原边 Use 转发，但报告只扫描完成签名的
   state slot，得到 0 个端口。修为逐真实 argument/formal，正例现在保留两边。

**Observed:** `red-applicability/` 另保留 2 FAIL。FixedBuiltinHandler 的
StaticProtocolGap 和未重放 FactRef 都曾被忽略，输入及 bool 正确时报告 DECLARED。
修后两者都明确保 `exception_match_builtin_applicability_unproved`，报告 PARTIAL；
即使有 locator，也不自动授予运行时 builtin 身份。

**Implemented:** query 使用单一共享预算。matcher 总库存只检查计费前缀，保
`supplied_matcher_count`、未检查数量、partial operation 和继续 cursor；不在预算
耗尽后继续物化所有附件，也不把未检查后缀当空集合。原 consumer ledger 已有
外层截断退出，审查中相关疑点经复读撤回，没有无依据修改原循环。

## 5. Wire 与兼容证据

**Verified:** Program21 只由非空 exception_matches 选择，Execution8 不变。
新 record tags 为不可变注册表。旧 1–20 top-level 字段不含这个空字段；读取旧
family 时内存默认空 tuple。21 无能力的假升级、20 带新表的降级、嵌套 tag/字段/
bool slot/自然键重复等均检查。

独立旧20 golden 来自冻结 `8f08bda` 的原 encoder 子进程：

- scope 只归档 scar/tests/pyproject.toml，避免把历史 artifacts 再打包。
- 原 encoder SHA：`3753c0ac02667e5bc6e816f23e6c624393a04e4e86278aab01861a0f89d09d47`。
- wire **55,479 bytes**；SHA：
  `27d603cb69786f122ba5cf1647ac47ab9f1311b03f89c1a132842e6a9c503edc`。
- source archive、独立 cwd/PYTHONPATH、命令、receipt、stdout/stderr/exit 均保留在
  `oracle-v20/attempt001/`；只清理自己创建的临时展开目录，tar 留作证据。
- 新 encoder 逐字节保持旧2–20 golden，旧 fixture 本身不修改。

旧 codec 测试只迁移最大版本断言和未来版本参数。上一轮811项中的810个身份
不变；唯一必要迁移是 future-schema case `[21] → [22]`，原义务未删除。
不能把参数迁移隐瞒成“811个原始身份完全相同”。

## 6. 自主有界验收

**Verified:** `model_exception_matches/final-focused/`：

- **880 PASS、0 failure/error/skip**；原811项义务保留（810身份不变+1明确迁移），
  新增 **69** 项。新单项/首红/修后均独立归档。
- pytest **34.13s**，外部 runner **34.908327s**。
- **707 份源码**测试前后指纹均为
  `90e68063cddbd2ab5e17a3064406923ff5c59cff61ad634589d9dfb28afd42c3`。
- 三路只读设计/反例/最终源码复审；最终测试期间所有作者冻结 source。
- 原夹具、旧证据、冻结合同/计划、保护 checkout 与 case 迁移由 archive-only
  检查核对，启动 0 个测试；独立 WIP commit/push。

D/R0/M/L/W/V/A 是本轮有界连接验收，不关闭原16组。没有组件/full；历史完整
回归保持其原 revision 归属。

## 7. 还缺什么，下一步怎么做

**Inferred:** 通用 matcher 已能连接原操作数和准确控制/完成状态，但这不等于
自动恢复源代码语义或知道每个 handler 的真实 builtin 身份。

**Rejected:** 将 lookup RAISE 当方法缺失；把 matcher 新包当 lookup/原注入包；
按名字猜 handler；用声明/FactRef 冒运行时证明；删除附件缩小已知分母；把缓存
复制分析或测试计数当整程序建模完成。

**Proposed:** 继续原 P4 的 fallback 连接：独立 E0（原注入包）、EL（lookup
RAISE）、EM（matcher RAISE）；matcher true/false/自身失败逐原 CFG 接准确包、
host/parent resume/C1 pending/Replace 与最新 context/state。THROW 当前 raw
1–3参数不足以推出已规范化 E0，需要原端口的独立锚；CLOSE 的现有
InjectedPacketTrigger 可复用。接口取舍须先审查，不能从 actual 反选 E0。
然后完成剩余16组、P5/M2及原整体验收。

完整模型、自动 LeWM 建图与可信 TRANSFORM **仍未完成**。没有新增优化 backend/
detector，没有运行重型 LeWM 或 A/B，没有新的加速比；所有 native/runtime/
identity/transformation 权限仍不授予。

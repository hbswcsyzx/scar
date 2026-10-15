# N2.function-interfaces 自主验收

日期：2026-10-15。状态：**PASS_BOUND_FUNCTION_INTERFACES**。
实现 `cfad419df03c14d9f7e38869929b4ee451fe6f62`。
实现/测试/gate SHA256：
`c92e3a4681fde28297eb7723119589796b2eb542ce74d333002a4afb71e6cef4`。
父 N2、完整程序自动建图及优化闭环仍未完成。

## Implemented：本门范围

默认入口 inventory v4 自动分离定义阶段、调用绑定计划与已绑定 body。
五种参数以显式 slot 对应 body 入口引用，world 单列。默认值走函数默认状态，
variadic 包含空 pack 计划；不执行表达式、不制造实际容器或已证明的默认版本。
BOUND 模式不沿用旧 CallTarget.arguments/results，避免将绑定失败接成 body 异常。
v1/v2/v3 保留旧调度与 lowering；无 trace 的 v4 runtime_scope 为 null。

没有新增 detector/backend、LeWM 名称规则、手工 workload 图或目标源码修改。

## Verified：冻结与迁移

| 自验 | 结果 |
| --- | --- |
| mapped gate | **504 passed**，全部标准通过 |
| 全仓 | **1,552 passed**，无失败/跳过，2 条已有 warning；wrapper 129.977 秒 |
| 独立接口反例 | 22 项包含于 gate；跨文件来源、错连/回滚/计费与公共篡改拒绝 |
| binder 定向检查 | 25 项包含于 gate；全部参数、defaults、空 packs 和不完整边界 |
| 实际旧包迁移 | Git archive `f21eb53` / `b886e40` / `994f944` 分别用原公共 CLI 生成 v1/v2/v3，当前 CLI 全部重放 |

旧包测试保留 defaults 的 UNSUPPORTED、caller 的2/2/1 region行为，不给旧报告
补新接口。其合成 trace 仅用于兼容，不冒充实际 profiling。

开发检查先有6个、后有1个失败用例，均为旧默认schema断言。公共断言按v4更新；
旧schema测试改为显式旧构造路径，实际历史包检查另行验证。首个开发命令误用
不存在的测试路径，未运行测试。另修正非keyword actual接受空keyword字符串的
构造器缺口，有独立反例。开发JUnit已核对解压内容并保存为gzip。

## Observed：原始 LeWM 外部来源复验

输入仍是原入口 `run_inference.py`、同一归档真实trace、文件256/body256/
操作10,000预算，不提供函数名单。SCAR自动生成与严格重放均exit0。

| 同一来源和预算 | N2.schedule | 本门 |
| --- | ---: | ---: |
| 文件 / 定义 / 源调用 | 151 / 2,217 / 10,235 | 相同 |
| 有core的body（仍有gaps） | 26 | **44** |
| 运行来源候选到core连接 | 4 | **6** |
| 其中有精确code witness | 1 | **1** |
| 36个观察函数候选 | 4 core / 32 unsupported | **6 core / 30 unsupported** |
| 原17个旧签名阻断 | 17 unsupported | **2 core / 15 unsupported** |
| 核心操作 / 构造收费 | 678 / 1,544 | **846 / 2,209** |

新增自动接口：1,663份signature、44份body interface、66个formal port；
197份候选绑定中142 CONDITIONAL、55 INCOMPLETE，有54条DEFAULT_STATE路线。
这些都是源码条件计划，不是197个已确认运行调用。

原17个签名阻断中余下15个的首要阻断：7 closure/cell、2 Call，以及AnnAssign、
IfExp、Assert、普通赋值、BoolOp、For各1。完整逐定义迁移见comparison及自动
connectivity报告。源码对应保持；不按这些结果中的函数名写规则。

### 必须保留的连接缺口

通用自动join审计显示，197份计划的478个actual仍没有core UseID：
146份计划的owner未尝试构图（355 actual），51份owner不支持（123 actual）。
44个core body中的110处CALL均可对应到源码调用，但候选目标都为空。
这两组按operation ID和versioned source atom的交集均为0；未发现已有core
actual应接而漏接的证据。不能把plan计数当成真实数据流连接数。

### 成本与原输入保护

| 阶段 | wall秒 | peak RSS KiB |
| --- | ---: | ---: |
| 构图及写出 | **432.895** | **347,120** |
| 严格重放 | **458.886** | **812,896** |

相较上一轮，单次构图约慢7.1秒、重放约慢8.4秒；不宣称分析加速。
本轮不是新的LeWM执行，也不是clean A/B。复验期间另有一次短只读报告比较/
连接审计；上述是共享服务器上的分析成本，不是隔离性能benchmark。
全部151个源码快照、trace压缩/原始字节及LeWM干净Git状态前后不变；
LeWM仍为 `f70fed80288462ca4d006cb3607ec6da6eaa851f`。
新inventory压缩7,328,776字节。项目可再生成缓存另清理8,290,304分配字节，
不删除trace/报告或共享环境；此前释放27.863GiB的历史结果不重复计为本轮。

## Inferred / Proposed：下一步

现有入口关系不足以构成可递归展开并回接的完整图。优先补捕获环境、已有
core调用的目标与逐调用normal/raise/state出口；再补循环携带与细粒度操作
效果、alias和逻辑来源。运行证据未记录的对象关系需要新的最小采集，不能
从归档hash猜出。具体自验门见 [N2_CALL_COMPOSITION_PLAN.md](N2_CALL_COMPOSITION_PLAN.md)。

## Rejected：本门不支持的结论

本门没有证明实际callee、defaults版本、细粒度effects、全路径覆盖、完整
程序依赖、LeWM变换或加速比。CONDITIONAL不是优化批准；UNKNOWN/缺口没有
被改为NONE。没有自动删除import、提升计算或启用复用。

## 证据

机器可重算汇总与精确文件哈希清单：
`artifacts/reports/gates/n2-functions-acceptance.json`。
同前缀保存冻结gate、压缩全仓JUnit、真实旧包报告/runner、LeWM生成/重放命令、
时间/RSS、自动比较、连接审计及压缩inventory。仅按清单归档本门文件。

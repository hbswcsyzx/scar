# M1 L：精确常量内容、来源与原求值端口

基线：干净 `13201ad24e0d8236623e28709f86e13a887ed4fb`。
上一门 S 的1,317组件/5,144冻结全仓已通过；这是新门实施计划，不是通过报告。
第一阶段 M0–M2 仍未完成，不增加 detector、backend、lowerer 或 LeWM 专用规则。

## 1. 建模决定

常量至少分三轴，不能用一个 node label 合并：

1. 精确 builtin 类型和内容表示：复用 `PythonLiteral`。
2. 定义来源：源码表达式、特定 code artifact 的常量池槽、未定位声明。
3. 实际求值/对象：保留原 OperationResult、INVOKE CompletionResult、Uses 和
   occurrence/denotation；同内容、同源码或同 code hash 不产生对象身份结论。

旧 LiteralOrigin 按 activation 预装。不能把每次 Python Reference 字面量求值
直接扩为这种来源，否则 loop/call 的多次对象求值会被合并。旧语义/wire 保留为
历史有限投影，不把旧对象 literal 自动迁移成新的完备求值模型。

新 `ExactLiteralOrigin(literal, definition)` 仅可用于 DataValue 的抽象内容常量，
按精确 kind 校验 data_type；不能用于 Reference/State/Binding/Protocol。
Python 对象的加载、构造、格式化等仍是操作；内容已知也不删其分配、回调、
异常、状态或生命周期依赖。

## 2. 原端口附件

```text
ProgramGraph.literal_evaluations: tuple[LiteralEvaluation,...]
LiteralEvaluation(site, literal, definition)
site = 原 OperationResult(operation,index)
     | InvokeLiteralResult(原 ControlEdgeReference, 原 CompletionResult)
literal = PythonLiteral | UninterpretedConstant(reason)
definition = SourceExpression(原 SourceReference)
           | CodeConstant(原 ProviderFactReference,index)
           | UnlocatedLiteral(reason)
```

SourceExpression 保留有版本的源码范围，不冒称该 span 必为 AST Constant；负号、
复合 complex、tuple 及运行构造都可能是表达式。CodeConstant 的 fact 精确引用
code 对象记录，index 选其 co_consts 槽；编译器实现/版本、mode/flags/future/
optimization 等上下文由原不可变 artifact 保存，附件不另复制 code registry。
fact/slot 存在只是一项声明，未读取/重放时必须保留未证条件。
frozenset/code 对象等编译常量可以引用准确槽并保留 UninterpretedConstant，
不通过 repr、pickle、marshal 或 eval 把它伪装成 AST literal。

direct site 必须指原操作的真实结果，origin 必须就是原 OperationResult。
INVOKE site 必须指 NORMAL 的真实 produced Data/Reference 槽，沿该边原
CompletionResult 精确派生 landing formal；state、RAISE、旁路 forwarded Use
不能冒充该求值结果。原 core completion_slots 要求一边每 produced slot 恰好
绑定一次，本门保持，不另存 formal/producer/ValueID。每个 site 仅一条附件。

LiteralEvaluation 也允许原 DataValue 计算结果的内容声明，known payload 必须
精确匹配其 data_type。这样可表达 computed constant 而保留计算 producer。
Reference 内容是该次产出时的声明，不是对象后续永不改变的证明。unknown payload
不升级类型/纯性/完整性。所有新声明不改变原 effects_complete 和 state/CFG。

静态查询从 site 返回原操作、结果/完成端口、附件和原有序 Uses。动态查询按
确切 occurrence、actual transfer 和已有 ValueOccurrence/ValueDenotation 解析。
未选边、缺完成、缺结果或 identity 保留具体状态/缺口，不补 normal 值、不选择
相同 payload 的其他 visit/child activation。完整声明和未检查项在预算截断后保留。

## 3. 精确 payload 与固定预算

支持 None/bool/int/float/complex/str/bytes/Ellipsis 八类标量以及 tuple 内容树。
tuple 内容不是源 tuple 构造已经可删除的证明；list/dict/set/可变元素/任意对象
不能进入 payload。complex 使用实部+虚部各16小写hex binary64 bits，保留
signed zero、inf、NaN bits；record equality 既不表示 Python ==，也不表示 is。
STR 保留 NUL、所有代码点及孤立 surrogate，不做 normalization。

精确profile中含任意surrogate的字符串使用 STR_CODEPOINTS：每代码点8位小写
hex UTF32BE（surrogatepass），必须至少含一个surrogate。它可区分两个代码点
D800/DC00与单一U+10000；仅escaped JSON会把前者合并，因此不能作为完整修复。
普通无surrogate STR 保持原payload。新core入口用 require_exact_literal 检查全树，
拒绝raw STR中的surrogate，要求使用可逆STR_CODEPOINTS。

本门冻结候选上限为：root depth0、最大depth64、展开节点16,384、payload总量
1,048,576 bytes、单整数4,096 decimal digits，先用 bit_length 限制昂贵转换。
共享子树按展开次数计费，不用对象去重绕预算；循环/篡改嵌套必须拒绝。
from_python/to_python/as_dict/from_dict、record codec 与 v2 decoder 统一校验；
在递归解码/昂贵转换前检查，不靠构造完叶子之后才发现越界。整数分块转换避免
依赖或修改全局 sys.set_int_max_str_digits。超额明确拒绝，不截成另一个有效值。
这些是每个 payload 的表示预算，不冒整个程序、JSON parser 或所有 CPU 时间预算。
L0预算审查如发现具体数值矛盾，先追加理由，再实施；不为了过测试临时提高预算。

## 4. wire 与旧消费者

新 exact origin/附件选择 Program wire v16；无新能力时保持旧 v1–v15 字段/tag/字节。
先从冻结旧实现保存独立 v15 golden 和来源 proof，再修改 codec；旧 fixtures 不改。
新能力采用 escaped JSON，让 surrogate 经 UTF8 snapshot 无损；旧版本编码不改。

共享 PythonLiteral 新 kind 不得静默扩展旧 SourceSemantics/OIR family schema。
本门保持这些旧 family 的 capability 明确拒绝新 complex kind；其原前端保留具体
unsupported gap，避免借载荷扩展提前启用 detector/变换。原支持 kind 的编码不变，
统一有界解析；新的 Program v16 明确支持 complex。实际受影响接口逐个记录。

既有SourceSemantics孤立surrogate往返及from_python(complex)拒绝是实际旧契约，
不能为新门改为拒掉原测试。from_python(value,exact=False)默认保留旧支持kind/
raw STR；exact=True才支持COMPLEX128与STR_CODEPOINTS，tuple递归传同profile。
require_legacy_literal在旧family拒两种新kind，仍接受旧raw STR。STR构造的历史
允许范围保持；新core所有known payload明确调用require_exact_literal。旧raw STR
的相邻surrogate在JSON合并是baseline defect，不宣称本门修复旧schema字节协议；
新精确profile完整表达，旧正常wire和已有测试守恒。

core dominance、execution literal activation/flow、query、validity/production integer
对应需接 exact Data origin；LiteralEvaluation 对象/计算结果绝不进入 literal 预装。
Reference-only frame/call 查询仍停在原 producer，不能把附件改为 LITERAL_REFERENCE。
数值协议比较先取 exact INT payload，不能把 bool、NaN、相等内容或字符串冒整数。

## 5. 自主验收节点

独立审查 `design/independent-scope.md` 的 L01–L10 是完整本门分母，不以测试总数
代替。包括八标量/tuple、surrogate/bits、预算、source/const scope、direct/INVOKE、
两loopvisit/两childactivation、重复Uses/is、容器/格式化及全部旧消费者。

| 节点 | 必须交付 | 拒绝条件 |
| --- | --- | --- |
| L0 | 三份源码审查、本合同、独立旧v15 wire witness | 只补enum；来源/identity/原求值仍混同。 |
| L1 | 共享payload/complex/一致预算，旧family边界 | 无界转换/递归，surrogate损失，旧schema静默扩kind。 |
| L2 | exact Data origin、求值附件/原端口校验、v16和静态query | 改原producer/Uses；Reference预装；错完成/state/forward槽。 |
| L3 | 原execution接入、动态查询与有限组合 | 同payload代替identity；跨visit/activation串线；构造/副作用被删。 |
| L4 | 独立有限复审、最终联合组件、干净实现提交、唯一冻结full | 丢原5,144 case/74fixtures/590sources；运行full时改写或并行测试。 |
| L5 | 原失败与修正、精确范围/预算、保护、指纹、归档/push | 数量冒自动覆盖；声明冒实际source/native/变换或LeWM加速。 |

所有Python使用 conda activate lewm。full复用固定SHA driver，fresh目录、无自动
重试；运行期间所有代理停止写入，只有同一handle轮询。仅清理本门独占已终止
进程的临时目录。主SCAR、LeWM原仓库、环境和共享缓存保持不动。

## 6. 后续与停止边界

模型依据：[Python expressions](https://docs.python.org/3.14/reference/expressions.html#literals-and-object-identity)、
[code objects](https://docs.python.org/3.14/reference/datamodel.html#code-objects)、
[整数转换限额](https://docs.python.org/3.14/library/stdtypes.html#integer-string-conversion-length-limitation)。
在线文档当前显示3.14.8，不冒充本机3.14.7实测。本机先前15片段编译见证复用，
不重复编译或将 co_consts 当 AST；没有运行目标代码/新LeWM profiling。

本门关闭有限内容/来源/求值声明接口及其组合，不宣称自动source/code绑定或实际
身份采集完整。之后继续C2/D3和M2原构造分母。用户要求第一阶段完整后先停下来
讲解的边界保留；现在仍未达到。完整M0–M2与自动LeWM化简保持OPEN。

## L0 冻结解释补充

三份只读审查已完成。整数快速上界为13,608 bits；后续仍按实际 canonical
decimal digits≤4,096 检查，不把bit预检视为精确位数证明。A原审查采用root=1，
本计划采用root=0，实施和所有边界验收统一以本计划为准，修订历史保留。
literal_builtin_type 返回 builtin type，不物化payload，由core派生完整data_type名。

CodeConstant.fact 必须按协议指原 artifact 中的 code/const-pool 容器记录，index是
唯一co_consts槽选择，不能把locator已选槽又二次索引。没有重放该原记录时保持
code context/slot/来源未验证条件，不根据字符串路径/内容hash推code对象identity。
Data端口的UninterpretedConstant保留内容/类型对应未解析，不宣称exact-match。

P1初案只采用escaped JSON、继而拟全局拒raw STR surrogate；实际标准库源码和
旧surrogate测试反证了这两种过宽方案。当前采用上述显式profile与STR_CODEPOINTS，
保留原风险/更改理由，不冒称已运行pair probe或修复全部legacy schema。

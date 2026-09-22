# G7：先补可计算语义，再做图化简

状态：**Proposed**。G6 通过后实施；只生成修改指导，不改目标源码、不调用 backend。

## 1. 从当前实现审查得到的缺口

G2 已保存 AST owner、读写和调用的可能连接，但这些边还不足以计算表达式：

- `ast_type=BinOp` 没有保留 Add/Sub 等 opcode。
- 无角色的 READS_SLOT 集合不能表示左右操作数、参数顺序或重复使用同一输入。
- 同一 lexical slot 有多次写入，不能把 slot 相同当作同一值。
- `literal_repr` 不是保留 Python 类型的常量 IR；tuple/list、bool/int 不能混淆。
- 本地 import 候选路径没有证明真实 loader、module cache、lazy attribute 或
  re-export 的运行语义。
- 原 OIR ValueSubstitution 只替换动态版本；静态化简不能伪造 ValueVersionID。

因此 G7 先补这些模型信息。规则随后只读取类型化图及其证明，不读取 workload
名称，也不通过“识别到某个包”直接输出固定方案。

## 2. 类型化语义层

增加明确对应到 SG operation/source atom 的记录：

```text
OperationSemantics
  opcode
  ordered operands (role/index/reference)
  result / type and dispatch preconditions
  source version / semantic contract

Static binding definition
  lexical slot / writer / scope / control
Use binding
  use site / reaching definitions / completeness

PythonLiteral
  exact Python type / scalar representation / ordered children

ImportResolutionContract
  import site / resolved module and source version / export binding
  loader / cache / lazy attribute / rebinding / observation scope
```

第一版精确绑定范围为可证明的直线局部数据流。跨 branch/loop、closure/global、
opaque call 和动态写入保持 reaching-definition 缺口。所有 SourceReference
都绑定已读取的文本版本；修改文件后不能沿用旧常量证明。

常量求值只处理有明确 builtin 类型前提的有限子集，并设置整数位数、容器元素、
字符串字节和运算工作量预算。不得执行用户函数、import、descriptor 或 eval。
整数、布尔、float 位模式、tuple/list 和 bytes 保持区别。mutable container
构造配方不等于跨调用可共享的不可变常量。

## 3. 四组最小通用规则

| 规则 | 图输入 | 输出与主要反例 |
| --- | --- | --- |
| constant propagation / path contraction | typed operations、ordered operands、scoped reaching definitions | 精确静态值替换；重绑定、mutable escape、lazy attribute 或 builtin shadowing 阻止错误折叠 |
| dead subgraph | region outputs、closed consumers、effects、Q | DELETE 指导；未来 consumer、callback、异常、日志和外部状态需要保留 |
| exact reuse | 同一语义操作、同一输入/状态版本、完整效果合同 | REUSE alternative；变更输入、隐藏状态、RNG、autograd 或可变输出别名形成反例 |
| composite motion | region、loop/control、origin paths、boundary delta | MOVE 指导；零次循环、异常时机、alias 写入和 readiness 均需证明 |

“有相同祖先”“有相同节点”“重复调用同一 module”都不是适用规则的充分条件。
保留 G5 已证明的效果维度；不能因值或 loader 仍未知，就把整个证明重新写成
一个没有原因的 UNKNOWN。

## 4. import 的值路径与初始化效果

通用本地包 fixture 应沿 import→re-export→attribute→index→consumer 推导
常量。规则可同时产生值路径替换和 import 删除的修改指导，但两个证明分别列出：

1. 使用点的值与替代字面量等价，身份、alias、异常和所需状态符合 Q。
2. 被删除 import 的初始化、loader/cache、注册、环境和外部效果在约定范围中
   没有必须保持的消费者；否则保留明确 residual 或原始区域。

前者成立不自动证明后者。已知 live effect 要说明哪一个必须保留；无法分离其
执行依赖时不能把“保留副作用”写成不完整的伪代码。fixture 使用任意自建包，
不能在规则中识别 LeWM 或某个依赖包名。

## 5. 修改计划与收益选择分离

静态替换使用显式 binding/slot substitution，与动态 ValueSubstitution 分开。
每个 alternative 绑定实际 region，并保留 NO-OP、精确 source span、证明树、
guard、失效条件、residual、validation 和 cost request。目标代码保持原样。

G7 输出可审核的修改指导和未满足的具体条件；G8 负责收益及组合选择。有限的
语义等价证明不能声称获得全局唯一最优方案，也不能把重插桩时长当 clean 收益。

## 6. 自行验收顺序

G7.1 typed semantics/bindings 与严格 codec → G7.2 图规则及反例 →
G7.3 端到端修改计划 → G7.4 外部压力报告。每个子节点自行测试、记录对应范围、
实现提交和报告提交；G7 总门还需四类计划集成、整仓回归及外部压力。子节点通过
不能写成整个 G7 已通过。通过总门后自动进入 G8。

| 子节点 | 验收证据 | 不能宣称的结果 |
| --- | --- | --- |
| G7.1 | 类型、操作数顺序、use binding、源码失效、预算、非执行式常量推导及反例 | 常量事实不等于可删 import 或已选择 rewrite |
| G7.2 | 四类规则固定证明义务、推导重算、缺失/伪造/过期证明拒绝 | 一条手写 PROVEN 不是合法性证据 |
| G7.3 | 精确修改位置、替代内容、残留效果、失效/验证/回退及 NO-OP | 不修改目标、不测得即不声称盈利 |
| G7.4 | 任意包通路及外部 LeWM 输入、报告确定性和代码无名称特判 | 未支持的动态语义不能伪装成已解析 |

## 7. 证明是按变换差量建立的

每个规则版本固定其必要义务集合，不能由提交 alternative 的代码自行删减。
证明账本绑定 region construction、源码版本、语义模型、Q、scope 和合同版本；
从 JSON 读取的 PROVEN 必须通过相同 checker 重新计算。缺项、重复项、循环前提、
过期引用及篡改状态均不能进入合法修改指导。

义务按实际删除/替换/上移的操作确定。精确 builtin 值替换不要求关闭整个程序的
所有 consumer；删除区域则必须核对其消费者、逃逸和必须保留的效果。否则一个
无关区域尚未闭合，也会错误地阻止已经能证明的局部化简。

Declared 合同必须显式纳入 Q 并显示适用条件，不能升级成 Observed。G6 的 origin、
调用祖先和 boundary delta 不能直接充当 target-entry 可用性、控制支配或零次循环
证明。reuse 也必须核对输出 alias/identity、autograd 与 hooks，不能以 clone 作为
普适修复。

合法修改指导标注 `selection_status=NOT_SELECTED`、`cost_status=PENDING` 和
`applied=false`；G8 才负责有成本证据的最终选择。

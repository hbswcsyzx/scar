# 规则怎样从图产生修改结论

本层是 G7.2 的证明接口，仍为 report-only。SG/source semantics 表达源码计算，
EEG/ValueGraph 表达执行证据；region inventory 列出原区域。证明账本解释一个
明确 TransformDelta 为什么符合或不符合 Q，不写目标源码，不选择收益最高方案。

## 静态值不冒充动态版本

```text
OperationDefinition ──producer──> StaticValue
StaticBinding ──binds──> StaticValue
BindingUse ──EXACT / conditional──> StaticBinding
                         ↓
StaticValueSubstitution(value, operation, source, literal, optional binding)
                         ↓
ProofRequest(region, family, exact delta)
```

引用必须连接到真实 producer、源码 fingerprint/span 和 region 成员。binding
表示被替换的 binding 本身，不能借用区域外的同值 binding。IRBundle 可携带
独立 source overlay，但没有把静态值等同于运行 Tensor、storage 或 LogicalVersion。

## 四类规则的范围

| 家族 | 当前检查 | 当前正向能力 |
| --- | --- | --- |
| CONSTANT | AST replay、固定 builtin 求值、完整前提 DAG、精确类型与 Q | 静态替换的条件合法性 |
| DEAD | 整个删除差量的 consumer/effect closure、scope 和 Q | 语义定义删除的条件合法性 |
| REUSE | 输入/隐藏状态、effects/RNG/exception、输出 alias/identity、autograd/hooks/consumer | 缺正向见证，NOT_YET_SUPPORTED |
| MOTION | target 可用性、控制/零次循环、效果/顺序、lifetime/readiness、精确插入点 | 缺正向见证，NOT_YET_SUPPORTED |

CONSTANT 只接受 static substitutions，不能夹带删除、动态替换或移动。
缩短整个路径若还要删除其他节点，必须额外建立 DEAD 证明，随后才能组合计划。
局部常量不要求关闭整个程序；删除区域也不能用局部常量事实代替 consumer 闭包。

## 条件合同不是运行事实

QAssumption 是固定 typed predicate、精确 subject 和 scoped DECLARED evidence。
常量替换需要说明：是否只观察值内容、是否观察对象 identity、如何约定资源失败，
以及前提 binding 与目标 builtin/floating runtime 是否匹配。runtime subject 包含
具体环境记录的 digest。父表达式必须继承所有 premise 中的 binding 条件。

声明的完整 effects/closed scope 同样要显式纳入 Q；空 events 不能自动变成 NONE。
`dead_effect_coverage_q_subject` 和 `dead_scope_closure_q_subject` 对精确记录生成
subject，分别对应 EFFECT_COVERAGE_ACCEPTED 与 SCOPE_CLOSURE_ACCEPTED。
账本保留 DECLARED 标签。Source replay 只验证源码与模型连接，不证明 loader、
初始化效果、消费者闭包、收益或目标运行的数值行为。

## 外部记录的信任边界

`derive_proof_ledger(context, request)` 从当前图和固定规则建立必要义务。
`validate_proof_ledger` 重新推导并比较整个记录；JSON reader 同样重算。
保存的 PROVEN、手工删除的义务、重复或循环前提均没有审批权。

失效依据包括 source/model/Q/region/scope/request digest。验证预算由调用方控制，
不是由报告文件指定。独立 source graph 边的类型正确也不代表其名称/程序点正确。

结果含 CONDITIONALLY_LEGAL、NEEDS_CONTRACT、ILLEGAL 或 NOT_YET_SUPPORTED。
所有结果仍保持 `selection_status=NOT_SELECTED`、`cost_status=PENDING`、
`applied=false`。G8 才做成本选择；本层不报告 LeWM 加速比。

实现与反例分别在 `analysis/proof_ledger_v2.py`、`test_proof_ledger_v2.py`、
主代理的 `test_proof_ledger_adversarial_v2.py`。节点接受范围见
`gates/g7_2a.json`；G7.2a 通过不意味着 G7.2b 或 G7 总门通过。

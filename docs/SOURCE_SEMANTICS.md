# G7.1：有序操作、静态绑定与有界常量推导

状态：**Verified（G7.1 子节点）**。163 项专项测试、848 项整仓回归通过；
范围与真实输入结果见 [G7_1_ACCEPTANCE.md](G7_1_ACCEPTANCE.md)。G7 总门仍待完成。

## 模型分工

SG 保留所有源码 operation、控制、可能数据流；`SourceSemanticsGraph` 是其计算
语义层。它引用 SG 的 operation/source atom，补上 opcode、按求值顺序排列的
操作数、静态表达式结果、每次读取的 reaching definition。尚无计算规则的 SG
节点登记在 `unmodeled_operations`，附具体 gap，不被丢弃或假定无效果。

```text
SourceAtom + OperationDefinition
       ↓ 精确源码版本对应
OperationSemantics(opcode, ordered operands, result)
       ↓
StaticValueID ← StaticBinding(epoch, lexical slot, writer)
                         ↓
                 BindingUse(使用点, reaching definitions)
       ↓ 固定 builtin 规则、有预算的推导
ConstantFact(type/content, proof DAG, source/model/runtime references)
```

`StaticValueID` 不是 G4 `LogicalValueID`，静态 binding epoch 不是 storage epoch。
此层没有观察 Tensor 数值，也没有虚构动态 execution/version。

## 哪些部分现在能推导

第一版支持显式直线绑定、不可变 literal/tuple、有限的精确 builtin 数值运算和
不可变序列常量索引。左右操作数、重复输入、位置和类型保留。整数以十进制文本、
float 以 binary64 位串、bytes 以 hex、tuple 以有序成员表示；bool 与 int 不混同。
list/dict/set 保留为新对象构造操作，不作为可共享的不可变常量。

所有扩大结果的运算先检查整数位数、字节数、元素数、深度及累计工作/输出预算。
越界索引和零除等结果记为已知异常；不得输出普通 literal 替换。预算只覆盖常量
推导，不声称同时限制 AST 解析和 schema 校验成本。

import、attribute、call 保留独立操作；没有 loader/lazy/dispatch 证明时给出
相应合同缺口。参数、closure/global 读取、跨 branch/loop 的定义合并仍不精确。
模块名、变量名、函数名不触发特殊化简规则。

class 构造和自定义 namespace 保持开放；其 deferred method body 仍以独立
function scope 建模，不能因为 class 效果未知就丢弃 method 中的局部计算。

## 执行条件不隐含为真

静态绑定推导明确要求普通新模块 namespace、标准函数局部绑定，以及没有未建模
的外部 namespace 修改。它们是 required execution preconditions，未被接受为
运行事实。预填充 globals 的 exec/reload、其他线程/信号/trace callback 等可能
破坏这些条件；后续 Q/规则必须核对适用条件。浮点计算还需要匹配目标解释器与
浮点执行环境，AST 对应本身不能证明位结果。

已建模的副作用边界会使绑定失效。例如：

- opaque 调用、descriptor 或可能调用用户代码的运算；
- 覆盖可能带析构函数的旧值，包含其修改其他绑定或赋值目标的可能性；
- opaque 代码可以创建此前源码没写过的 namespace 项，不能以 write count 为零证明不存在；
- 字典与 keyword mapping 展开可能在后续条目/参数之前修改绑定；
- loop carried state、分支合并、异常路径与 deferred function body。

这些限制不会抹掉独立 literal 子表达式的推导，例如 opaque 调用前求值的 `2+3`。
但有常量事实不代表其对象 identity、allocation、异常/效果及控制都可删除。

## 验证与入口

结构校验验证 ID、类型、引用、源码版本、最新局部定义和无环数据依赖。
`validate_source_semantics` 重新执行固定 AST 提取过程，拒绝被篡改但类型仍合法的
opcode、操作数顺序或 use binding。`ConstantReport` 从固定规则重算，而非相信
序列化文件中的成功状态或摘要。二者验证的事项不同，不能相互替代。

验证导入报告时，`verification_budget` 是调用方给出的独立上限，默认与普通
求值预算相同。不能用外部报告自带的预算作为重算上限；报告要求更大的预算会在
重算前拒绝。可信调用方主动设置更大预算时，也须显式传入相应验证上限。

```bash
scar semantics-v2 /project/program.py --out /tmp/semantics.json.gz
scar semantics-v2 /project/program.py --max-int-bits 4096 --max-nodes 10000 \
  --out /tmp/semantics.json
```

入口不执行或 import 目标，不改源码；输出语义记录、推导 DAG、缺口、预算使用和
零 selected transformation。`--project-root` 遵循 G2 的显式文件树选择语义。

验收由开发代理运行 `gates/g7_1.json`，保存报告并提交、推送。下一子节点 G7.2
连接四类差量规则与固定证明义务；完成 G7.3 修改指导、G7.4 外部压力后，才可能
通过 G7 总门。

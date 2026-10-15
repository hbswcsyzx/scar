# 程序图的核心节点、连接与化简目标

日期：2026-10-13。状态：**设计已审查；N1 有限同步核心已实现并验收**。
自动源码构图与更广的规则仍待 N2—N4，见 [N1_ACCEPTANCE.md](N1_ACCEPTANCE.md)。
2026-10-15 补充：N2.a 已实现有限函数体自动构图和正常/异常完成边；完整程序
恢复仍未完成。实现扩展见 [N2_COMPLETION_AND_LOWERING.md](N2_COMPLETION_AND_LOWERING.md)，
范围与证据见 [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md)。
本文件是后续核心建模的决策依据。它纠正“已有多维标签和图容器，就已完成
程序语义建模”的表述，不把规划写成现有能力。

术语澄清：这里的“语义”仅指程序操作及依赖的定义，不指人类理解的业务含义。
用户关注的类型清单、保存视频/保存 tensor 的统一分解，见
[PROGRAM_TYPES.md](PROGRAM_TYPES.md)。四类是结构类型，操作行为类型另行细分。

## 1. 图要解决什么问题

SCAR 的目标是先表达程序，再通过图和子图的等价替换减少执行工作。对于一个
明确的语义合同 Q，程序可理解为：

```text
输入值 + 初始状态
    -> 结果值 + 最终状态 + 可观察交互 + 完成方式
```

完成方式包括正常返回、异常及终止行为。所需输出、外部效果和状态由 Q 指定，
不能只以最后一个 Tensor 为根。优化应保持这些要求，消去可以替代的工作，
再根据资源约束和实测成本选择实现。

“最小必要依赖”不是让所有节点或所有边的数量最少。缓存会增加保留、查找、
guard 和失效处理，却可能大幅减少计算。当前可验收的目标是：找到明确观察
根的保守依赖闭包，实施有依据的局部图化简；不承诺已求得任意程序的全局最优。

## 2. 当前方案：四类顶层语义节点

| 节点 | 严格含义 | 示例 | 不是它的东西 |
| --- | --- | --- | --- |
| **Operation** | 源/IR 中一个操作的静态出现位置，带算子语义、有序输入使用和编号结果 | 调用、加法、读取、写入、import、分支判定 | 函数名称、一次动态 invocation、单纯分类标签 |
| **Value** | 一个不可变的定义结果或区域参数；具有强类型变体 | 标量结果、Tensor 逻辑数据、对象引用、状态版本 | 变量名、裸地址、采样时保存的一份数据 |
| **StateLocation** | 可变位置或外部状态域的身份 | buffer 内容、对象字段、闭包单元、RNG 实例、文件/输出历史 | 某次内容、物理 StorageID、一个字符串状态标签 |
| **Region** | 具有明确接口和内部控制结构的子图 | 程序入口、模块初始化、函数体、循环体、分支 | 仅表示缩进的父节点、自动获得纯性证明的容器 |

这是四种顶层实体的设计方案，不是“程序只有四种行为”，也不是已证明的最小、
唯一或完备分类。当前 LeWM 尚未被完整恢复成这套图。状态版本、边界、控制和
效果必须保留明确类型及不变量；下文规定它们如何表示。

能给一行代码贴上 Operation 标签只证明它有存放位置，不证明已经理解它。
每个支持的具体操作还需要：解析/dispatch 条件、有序输入及结果、读写位置与
范围、alias/身份/生命周期、控制与完成方式、效果/顺序，以及可核对的语义规则。
例如数值加法、RNG 采样、原位写入、view、import、callback 和 CPU 物化不能
只凭共同的 Operation 类型获得同一种化简规则。

分类是否够用以程序反例和查询结果验收，不能以 enum 数量验收。如果一种必要
的语义实体无法在强类型值/位置/区域接口及关系中自然表达，应修订顶层分类，
不为维持“四”而塞进无约束 metadata。实际 LeWM 源码压力清单见
[LEWM_SEMANTIC_COVERAGE_REVIEW.md](LEWM_SEMANTIC_COVERAGE_REVIEW.md)。

### 2.1 输入、输出和常量

输入、输出是 Value 相对于某个 Region 的**端口角色**。一个值可以同时是
内层函数的输出和外层函数的中间值。因此不将 Input/Output 设成互斥值类别。

Value 的定义来源单独表示：

```text
ValueOrigin = RegionArgument | OperationResult | LiteralConstant
```

常量属于 Value，来源是精确 literal 或经过证明的恒定推导。Python 中生成
对象的行为如果涉及身份、分配或其他可观察效果，仍由 Operation 表达；
“已知数值”不自动消除创建对象的语义。

证明一个 OperationResult 恒定，只增加恒定事实，不改掉其 producer。
只有显式图替换才建立新的 literal 定义、改接 use 并保留变换 provenance。

程序源/汇用根 Region 的输入/输出、状态和控制端口表示。Boundary 是这个
强类型接口，不另建一个虚构的执行步骤。观察目标通过 Q 精确引用这些端口。

### 2.2 Value 必须是强类型联合

```text
Value =
    DataValue
  | ReferenceValue { referent_identity, target_locations, selector_or_view }
  | StateVersionValue { location_id, definition, footprint }
```

- DataValue 是逻辑数据，可仅有符号定义、类型/shape 等已知信息，不要求存数值。
- ReferenceValue 是引用；引用保持不变不代表引用对象的内容保持不变。
  referent_identity 是独立的语义身份（可明确未知），动态 ObjectID 只是证据
  映射。两个同形同位置的 view 可是不同对象；两个 producer 也可返回同一个
  singleton。位置集合允许为空或未知，不能据 location/selector 相等推导身份相等。
- StateVersionValue 是某个明确 StateLocation 的状态版本，可完全不知道内容。
  它必须有 typed location ID；`semantic_type="state"` 字符串不能代替该关系。

StateVersionValue 是一等节点，复用 Value 的定义、使用、合流与循环携带机制。
它不是“已经复制保存旧内容”的承诺。物理上能否再次读取旧内容是另一个问题。

ValueID 标识静态定义；同一定义在不同调用或循环轮次会有不同动态 value
occurrence。相同静态 ID、对象或 provenance 不证明值相等或状态版本未变。
这同样适用于循环中的 StateVersionValue，不能把一个静态节点当成恒定前态。

普通局部变量名由绑定/def-use 关系表达。`x = y` 通常是名称重绑定；
`x[...] = y` 是对某个 Location 的内容更新，两者不能混淆。全局或闭包单元
等本身可被其他操作访问的绑定，可以成为 Location。

### 2.3 Operation、函数体和 invocation

```python
a = f(x)
b = f(y)
```

需要一个函数体 Region、两个调用 Operation、两组实际参数/返回值绑定。
不能仅用一个名为 f 的节点来承载两组数据。运行时每次调用再有独立的 EEG
OperationInstance；循环中的一个静态调用位置可对应很多动态实例。

Python 的 `def` 语句也会执行：默认参数、装饰器、闭包创建等属于定义时操作。
函数体 Region 的执行要等到调用，两者不能混在一起。

Operation 的具体语义可以是 compute/read/write/allocate/transfer/IO/control
等，多标签 A 继续保留。标签不替代算子规则、状态端口和效果摘要。

### 2.4 StateLocation 与别名

位置身份独立于 object、allocation 和内容版本。静态分析可以使用分配/绑定
位置与调用上下文；运行证据再关联实际对象生命周期和资源表示。

ReferenceValue 的 selector/view 说明访问哪个位置、哪个区域。两个引用可以
访问同一个位置的不同部分。alias 关系与访问 footprint 决定写入是否影响读取；
未知 alias 必须形成保守冲突，不能当作无重叠。

target/selector 是带作用域和状态条件的访问关系。目标、shape、stride 等
元数据若可被修改，读取它们也必须依赖对应状态版本；引用身份稳定不证明
访问范围稳定。

**纠正旧文档：view/reshape 不能默认认作同一 ValueVersion。** 它们可能共享
位置/storage，却有不同的形状、选择范围、步幅和 Python 引用身份。只有针对
明确语义定义的等价/表示合同，才能作进一步合并。

## 3. 必须有哪些连接

| 关系 | 端点及含义 | 关键约束 |
| --- | --- | --- |
| defines | Operation → Value | 普通结果恰有一个定义；literal/region argument 有各自来源 |
| uses | Value → Operation 的特定输入使用点 | 保留 role/index/UseID；`f(x,x)` 是两个 use |
| refers_to | ReferenceValue → StateLocation | 保留选择器、alias 精度与不确定项 |
| version_of | StateVersionValue → StateLocation | 版本与位置一致；不能以 Tensor `_version` 替代通用语义 |
| owns | Region → 内部实体；Operation → 自有 body Region | 结构所有权无环；不意味着执行顺序 |
| body_ref | callable/call Operation → Region | 调用引用可递归；动态 dispatch 可以是候选集合或未知 |
| control_flow | typed 出口 → 入口 | normal/raise/return/break/continue、分支和零次路径明确 |
| must_before | Operation 的事件端口 → 事件端口 | 保留冲突、外部效果和同步所需顺序；不能等同 trace 记录顺序 |
| port_binding | 外层实际 use/result ↔ 区域形式端口 | 分调用上下文；不把不同调用都写入同一形参绑定 |

defines、ValueOrigin 和端口绑定属于规范语义；历史来源、源码位置及证据
引用属于辅助索引。一个事实只能有一个规范来源；字段与边不能各维护一套
互相冲突的定义。不存在的边只有在相关范围已闭合时才支持“没有该依赖”。

每个 use 的定义必须在对应路径上可用。分支、异常和循环合流用逐前驱端口
绑定表示，不能把不同路径或轮次的状态版本无条件合并。未观察路径与零次
执行路径不能仅因 trace 缺失而删除。

### 3.1 控制为何不单设通用 ControlToken 顶层节点

当前以结构化 Region、强类型控制端口和 control_flow 边表达控制。
`if p: print(1)` 的 print 必须受分支启用，不能因输入常量就提前执行。
Boolean 值本身不等于执行许可。以后若需要扁平 token 执行 IR，可从这里 lowering。

循环用有限的循环携带端口和回边表示，不将一次 trace 展开图当作整个程序。
结构包含无环不要求控制流或调用引用也无环。

### 3.2 效果域与顺序

外部效果域采用 StateLocation 及 StateVersionValue，例如 stdout 历史、RNG
状态。它们的内容可以 opaque，但前后版本和顺序不可消失。因此无需另造
与状态版本平行的 EffectToken 框架。

Operation/Region 的效果摘要至少连接：

```text
reads / writes: location + footprint + overwrite mode
allocates / escapes / alias
completion: normal / may_raise / may_diverge
required ordering
completeness: 按域区分已知与未知
```

导出 RAW、WAR、WAW 以及外部效果/异常所需的依赖。

```python
r = x[0]
x[0] = 1
return r
```

两个操作都接到旧状态 S0，不足以保证先读后写。必须保留 WAR 顺序，或证明
旧状态已有独立物化。抽象状态版本不等于物理快照。

另一方面，完整覆盖写可能 kill 旧内容依赖。不能对所有边统一反向可达，
否则每次新状态都保活全部历史写入，连死写都无法删除。需区分内容依赖、
必要顺序、结构关系和证明/源码关系；删除写入还必须考虑其 RHS、副作用及异常。

overwrite kill 只消去旧内容依赖，不自动删除 must_before。删除已证明不可
观察的写后，仍需重算并保留存活操作间必要顺序。期间有读取、并发观察、
外部效果或异常时，不能仅凭后续覆盖删掉前写。stdout 的完整输出历史不是
普通可覆盖单元：`print(1); print(2)` 不能化简成只输出 2。

## 4. 递归展开与展示

用户看到的图可以以广义 function/operation 为方框，以数据为连线：

```text
Call f #1 -- value a --> Add
Call f #2 -- value b --> Add
```

底层 Value 仍是一等实体，折叠视图中的边携带 ValueID 和使用端口。展开调用
显示其 body Region，并保留该调用自己的绑定。控制、状态和效果边可作为
独立视图显示，不能在化简时隐藏其语义。

展开/折叠必须保持：输入输出、状态前后版本、alias/escape/新对象身份、
正常与异常等控制出口、外部效果和顺序、未知范围。内部发现一个隐藏写后，
不能仍将外部摘要称为完整。

语义 Region 是程序的组合结构；OIR OptimizationRegion 是从程序图选择的
替换边界，可以跨多个操作。两者相关但不可混用。后者不能凭包装一个成员
集合就创造缺失的语义。

## 5. 资源、合同和测量的位置

- **R**：对象的物理观察与实现记录、storage/allocation、Materialization、
  CPU/GPU、stream 等是物理实现图。Python 可观察的对象身份仍在语义层的
  ReferenceValue 中。StateLocation 不直接等于 storage；`.to()` 不等于真实 copy。
- **Q**：哪些结果、状态、交互、异常、数值及梯度语义必须保持，是约束与根集合。
- **M / evidence**：运行实例、观察、计时、覆盖范围支持或限制模型中的事实。

这些可以有自己的 typed 节点与索引，但不是“输入/状态/计算”语义节点的
替代品。K/Σ/A/R/Q/M 继续作为正交视角，不能当作每行代码的六选一分类。

SG、EEG、OIR 的分离保留；重心调整为 **SG 的程序语义先完整表达，再由 EEG
精化事实，最后构造 OIR 变换**。不能靠不断增添 trace 标签来补出语义。

异步完成不能仅归为计时元数据。CPU 调用返回与 GPU 结果就绪必须有不同的
typed 完成端口；跨区域等待/消费须依赖正确的完成条件。autograd 的求导连接、
detach 和模式作用域也须进入相应操作与区域语义。当前文档仅确立这些要求，
尚未完成这两部分的具体规则和验收；不能据四类节点宣称已经覆盖。

## 6. 用三个程序检查化简是否自然

### 6.1 重复 encoder 子图

```python
a = encoder(x, W)
b = encoder(x, W)
return a + b
```

```text
before: x,Sx,SW -> Encode#1 -> a -> Use#1
        x,Sx,SW -> Encode#2 -> b -> Use#2

proposal: x,Sx,SW -> shared computation -> result
                         -> required output identities/representations -> uses
```

必须比较全部实际读取的状态版本和完整接口，而非只看 x/W 这两个名字。
如果两次原调用产生独立可变 Tensor，直接令 a、b 指向同一缓存对象可能改变
`a is b` 或 `a.add_()` 后的行为。可先展开寻找可共享的纯计算部分，保留输出
身份/表示要求；接口允许共享时才合并整个调用。

精确 before/after 需要列出：移除的操作、改接的 use、结果的保留范围、必要
guard/失效与 fallback。共享 True 对象同样不能合并不同结果 occurrence 的
producer。这是存档引用切片可贡献的局部经验，不是该切片必须先完成的理由。

### 6.2 view、原位写与跨层上移

```python
v = x[::2]
a = encoder(v, W)
x.add_(1)
b = encoder(v, W)
```

v 引用的 Location 未变，a、b 读的状态版本不同，不能直接复用。写入不重叠
部分时，后续 footprint 分析可提高精度；现在可先保守失效。

第八层的子图若只依赖第三层的值/状态，可以提出向上移动；来源在第三层仅
说明一个条件。还需第三层精确插入点的可用性、支配/执行次数、零次路径、
跨越效果、异常时机和新增存活范围。调用嵌套深度不等于移动合法性。

### 6.3 import 常量路径

```text
module initialization -> bindings -> re-export -> attribute/index -> constant
          |                                  
          +-> module-cache state / IO / exceptions
```

常量值路径的替换和初始化操作的删除是两个图变换。若初始化效果、其他用途和
异常在 Q 下确实不需保留，可删除 import；否则保留相应残余依赖。
规则来自节点/边及 effect liveness，不来自包名，也不能仅因终点是常量就删整包。

## 7. 当前代码审计

审计基线为 main `2208b61`（核心实现此前在 `d5fa963` 已冻结）。

| 现有部件 | 能保留的内容 | 尚缺的能力 |
| --- | --- | --- |
| `v2/semantic.py` | OperationDefinition、ValueSlot、ControlRegion、源码归属 | ValueSlot 是接口位置；SG 端点没有真正 Value/StateLocation/StateVersion |
| `semantics_v2.py` / source overlay | 有序 operands、StaticValue、BindingUse、有限源码语义 | 尚非所有程序操作统一消费的核心；不能用可选 overlay 代替完整依赖 |
| `v2/values.py` / provenance registry | 对象/分配/逻辑值分离，tensor mutation/copy 证据 | 尚无统一 Python 字段、RNG、文件等位置的 typed 状态转移 |
| `state_slots` | 预留的 typed slot ID 接口 | 搜索仅见 schema/codec/validator/region/invocation 使用，未见 frontend/normalizer 填充路径 |
| CFG / effects overlays | 已有控制路径、异常缺口、effect occurrence 与覆盖 | 未统一进入带状态/值合流的依赖查询 |
| EEG | 动态实例、观察、运行事实 | 不能替代整个程序、未执行路径及消费者闭包 |
| OIR regions/deltas | 区域接口、原执行候选、部分精确差量 | 尚不能完整表达一般 use 改接和统一状态接口 |

因此千余项既有测试证明的是各自已验收的有限能力，不证明整个程序的依赖模型
已经完备。当前尚无自动可信的 LeWM TRANSFORM 或加速比。

## 8. 新的验收顺序

1. **N0：节点与依赖语义审查**。本文、实际代码差距、三个反例、WIP 存档齐备。
   这是设计验收，不运行目标，也不宣称统一 IR 已实现。
2. **N1：语义核心及接口**。实现四类节点、Value 强类型变体、UseID、Location、
   合法边和端口；用完整小程序的手工 IR fixture 验证，而非只测独立 enum。
   包含输入、分支、读写状态、返回、日志/异常边界；每个 use/出口可追溯。
   此处四类是待实现并受反例检验的方案，不是固定的最终类别上限。节点可入图、
   操作规则完整、依赖查询正确、变换可证明须分别报告；前者通过不代表后者。
3. **N2：从现有前端构造统一图**。提升/适配 source semantics、CFG、effects；
   明确名称重绑定、状态写入、调用参数绑定、循环携带和 opaque 边界。返回
   缺少的具体关系，不把所有不支持情形压成一个 UNKNOWN。
   首批只恢复提供源码的普通同步函数、局部绑定和 builtin 常量、显式 if/loop
   控制骨架及已解析直接调用；状态访问必须有可核对的访问规则/合同。动态
   attribute/descriptor、loader、全局干预和未解析调用保留具体未知边界，
   不把一般 Python/PyTorch 的完整恢复设成本门完成条件。
4. **N3：依赖闭包与图化简指导**。按 Q 根查询 data/state/control/effect 依赖，
   区分 overwrite kill 与必要顺序；三个程序能给出明确 before/after 和保留项。
   非数值效果、alias、异常、零次循环、输出可变身份反例不得误删/误合并。
   每个正例注明语义来自已解析源码/固定算子规则，还是手工 IR/显式合同。
   `encoder` 名称和任意 `pure=True` 不提供证明；合同正例只能按其声明范围
   报告条件结论，不能包装成从任意函数自动推导的纯性。
5. **N4：连接证据与原 G7 路线**。按具体缺口接入现有 trace/provenance，补精确
   OIR use 改接、proof/cost/修改指导，再恢复 import 与外部 LeWM 压力验收。

每门由开发代理自行验收、保存失败及成功报告、提交并推送。N1 已验收有限
同步手工 IR 范围；N2—N4 未完成，不能把本章长期范围全部计作已实现。
不添加新 backend、不改 LeWM、不设计新的用户编程语言。

## 9. 远期声明式执行

若用户直接提供功能、状态转移、效果约束及目标接口，这些描述可以作为同一个
语义图的另一种输入来源。系统再选择等价子图、物理表示、调度与实现。

近期是从现有 Python/PyTorch 程序恢复语义并给出化简指导；远期是从声明的
语义组织执行。二者共享上述核心模型，但自动合成、全局调度与新语言属于后续
能力，不由本次设计审查宣告完成。

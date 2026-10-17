# SCAR 完整程序模型：实体、接口与组合规则

日期：2026-10-16。状态：**规格修订；不是整个程序已自动建模的声明。**

本文是完整模型的当前设计入口。它修订旧文档将四类 `ProgramGraph` 结构当作
完整模型的说法。已实现的同步子集仍按原版本解释；本文没有静默升级其能力。
实施顺序与验收见 [WHOLE_PROGRAM_MODEL_PLAN.md](WHOLE_PROGRAM_MODEL_PLAN.md)。

本模型不要求从零实现全部图前端。现成工具的能力审查见
[TOOLING_SURVEY.md](TOOLING_SURVEY.md)，事实来源、规范化与对应合同见
[MODELING_INTEGRATION.md](MODELING_INTEGRATION.md)。优先复用 Python 编译见证、
FX/Export 子图、ETO 与已有 profiler；SCAR 补齐它们之间及外部程序的依赖关系。
新适配器尚未接入，不能把复用设计计为已完成自动建图。

## 1. 先定义程序，再构图，再化简

```text
程序 + 版本化语言/库协议 + 分析边界
    -> 类型、接口及组合规则
    -> 自动恢复程序定义与依赖
    -> 运行证据精化与对应
    -> 合同内的依赖闭包与子图替代方案
    -> 成本选择与修改指导
```

SCAR 分析执行工作是否可以避免，并给出具体、可审查的修改指导。直接改写
任意源码不是当前阶段的交付。LeWM 是外部压力案例，不能成为类型或规则的条件。

一个程序的观察包括返回、必要状态、外部交互及完成/不完成行为。观察合同 Q
指定哪些必须保持，包括异常、随机性、数值/梯度、身份和顺序；不是只保留最后
一个 Tensor。性能是合同约束下的选择问题，不承诺任意程序的唯一全局最优解。

### 1.1 四种不能混报的完成程度

| 层次 | 可验收的问题 | 不足以证明它的东西 |
| --- | --- | --- |
| 类型可表达 | 每种必要实体、协议和关系是否有明确身份、端口与不变量？ | 增加一个分类标签。 |
| 自动结构恢复 | 全部源部分是否有归属，支持部分的操作/有序 use 是否自动连接？ | AST 行覆盖率、opaque 外壳。 |
| 依赖与执行精度 | 实际目标、环境、版本、别名、控制和完成是否接通？ | 相同引用、同名函数、一次 trace。 |
| 化简权限 | 某个替代方案是否保持全部观察，且成本值得？ | 重复节点、测试总数、查询能通过一条边。 |

完整结构可以含明确的未知协议边界，但未知内部操作不得算已展开，未知依赖
不得算已闭合。模型能表示“这里缺什么”和模型已经恢复其内部，是两件事。

## 2. 五类基础实体及其正交属性

| 实体 | 规范职责 | 身份不能等同于 |
| --- | --- | --- |
| **Operation** | 一处静态操作，有有序输入使用、结果及控制/状态/资源接口。 | 名字、动态调用、性能事件。 |
| **Value** | 一个定义结果或区域参数；有强类型的数据、引用、绑定、状态和协议变体。 | 变量名、地址、采样内容。 |
| **StateLocation** | 可以变化的位置/域，具有 owner、selector、覆盖与别名关系。 | 某次内容、allocation 地址。 |
| **Region** | 有入口、出口、环境和内部结构的子程序，可递归展开。 | 缩进容器、默认纯函数。 |
| **Resource** | 多个状态、分配、工作与物化共同引用的执行/承载身份。 | handle、某个状态版本、一次 enqueue。 |

这不是五种互斥的程序行为。计算、读写、表示、生命周期、搬运、控制与等待
是操作的可组合行为；外部访问是边界属性；常量/不变量是带范围的事实。
输入/输出是端口角色。K/Σ/A/R/Q/M 保留为观察坐标，不再承担节点分类。

同一 stream 在多次 enqueue 前后身份相同而队列状态变化；多个 allocation
属于同一 memory pool；两个 handle 可能指向同一文件。因此完整模型需要
独立 Resource。旧四类 `ProgramGraph` 可作为控制/数据投影，但资源表和强类型
引用属于完整 ProgramModel，不能只在 trace 中出现。

### 2.1 规范来源唯一

完整 ProgramModel 是组合容器，不是与现有图并行维护的第二套 def-use 图：

```text
ProgramModel
  program definitions / regions / canonical uses and control edges
  resource definitions and requirements
  versioned protocol bindings and source ownership
  claim references and scoped incompleteness
```

现有 `scar/ir/program` 承接程序定义；`scar/ir/v2` 的物理、provenance 和 evidence
记录经明确接口接入。producer、有序 use、逐边参数、state version 各只有一处
规范事实。展示边、摘要、索引和 overlay 从它们派生；不能在另一张图再独立
保存一套可修改的输入/结果或前后 world。未来 wire 扩展必须显式版本化。

## 3. 身份、逻辑值与物理表示

### 3.1 分清静态定义与动态发生

```text
OperationID       一处静态操作定义
ValueID           一个静态 SSA 定义/区域参数
ValueOccurrence   (run, activation/resume context, ValueID, visit)
ObjectID          一次 Python 对象生命周期
LogicalValueID    一条逻辑数据 lineage
ValueVersionID    该 lineage 的一个不可变逻辑数据版本
AllocationID      一次分配生命周期，而非裸地址
MaterializationID 一个逻辑版本的物理表示及有效区间
```

一个循环中的 ValueID 可以对应很多 occurrence；不能因此认为值不变。两次
调用同一个函数也不能共用参数 occurrence。ObjectID 和 AllocationID 均需要
生命周期代次；地址再用不构成同一对象/分配。

### 3.2 单一桥接：occurrence 的 denotation

Program ValueID 与 v2 ValueVersionID 不是同一命名空间，也不互相替换。
二者通过带依据和范围的对应关系连接：

```text
Denotation(ValueOccurrence) =
    Data(ValueVersionID)
  | Reference(ObjectID, access relation)
  | Binding(binding state and referenced payload occurrence)
  | State(state location and dynamic state version occurrence)
  | Protocol(typed protocol payload)
  | Unresolved(reason, scope)
```

引用不永久绑定其对象的初始内容。读取引用所指对象时，`StateRead` 消费当前
location/version 和 selector，才产生这次读的 data occurrence。否则同一个
NumPy/Tensor buffer 原位覆盖后会错误沿用旧逻辑版本。

`StateVersionValue` 是 core 中承载位置版本的 Value 变体；v2 `ValueVersionID`
标识逻辑数据版本。名称都含 version 不代表二者可以直接互换。

LogicalValue 的 domain 明确载荷的类型、shape 与元素解释；device/地址等物理
属性另存。同一 lineage 可以分叉；revision 是唯一标签，祖先关系取显式推导边，
不能用全局 `latest` 更新所有副本，也不能按 revision 数字比较推导先后。

### 3.3 来源不是相等，相等不是可直接替换

`ProvenanceID` 标识一次版本推导：实际输入版本、读到的状态版本、产生操作/
occurrence、完成方式和所用协议。它是从规范 use/state 关系派生的解释，不得
反向编造输入。相同来源可以经过不同变换得到不同值；相同数值也可以有不同来源。

其记录区分 `ValueDerivation`（产生逻辑版本）与 `RealizationDerivation`（产生
物化/运输关系）。保持版本的 copy 只连接物化推导，不制造逻辑祖先 `v -> v`
自环。一般变换产生新逻辑结果；是否保持抽象载荷由明确 domain/表示合同判断。

| 变化 | 模型关系 | 禁止的推断 |
| --- | --- | --- |
| 普通局部 `x = y` | 绑定新版本指向同一引用；不复制内容。 | 新变量名即新数据。 |
| copy / deepcopy | 对象/分配通常不同；按实际 copy 协议判断内容版本关系。 | 所有 deepcopy 都透明；自定义 copy 无效果。 |
| view / expand / slice | 引用和 selector/shape/stride；可能共享 allocation。 | view 即新完整分配，或必定同一逻辑 Tensor。 |
| cast / normalize / encode | 有输入与状态依赖的变换；通常产生新逻辑结果。 | 同一来源即同一 ValueVersion。 |
| 精确 materialize / H2D | 在已证明的表示合同下可关联同一数据版本的多个表示。 | `.to()` 源码调用即物理 copy。 |
| 原位写 / 外部 alias 写 | 相应 location/footprint 产生新状态版本，并失效受影响表示。 | ObjectID 或 Torch `_version` 不变即内容不变。 |

即使数据内容相等，输出对象身份、alias、autograd、可变性和生命周期也可能
阻止用同一个 cached Tensor 替换。caller 可以修改输出；相等结论不授予共享权限。

### 3.4 Materialization 必须连接什么

```text
Materialization = logical value version
                + representation contract
                + allocation lifetime / storage region
                + producer occurrence
                + validity interval / invalidation relation
                + typed readiness obligation or evidence
```

StorageRegion 保留 offset、shape、strides、dtype；重叠、部分重叠和未知单列。
覆盖底层内存后，历史 Materialization 记录仍可保留，但不再表示旧值现在可读。
逻辑旧版本的存在不承诺有物理快照。

模型不要求记录 Tensor 全部数值。shape/stride/dtype/device 与少量样本可用于
排除候选、调度进一步核对；采样相同不是内容或版本相等证明。模型参数不逐轮复制。

## 4. 状态、别名、效果与顺序

### 4.1 位置的规范接口

```text
Location = identity + owner relation + domain + selector/footprint description
Access   = location + footprint + read/write mode + pre/post state ports
Alias    = scoped overlap/coverage fact, including UNKNOWN
```

owner 与 selector 可以由运行值决定；动态 selector 的求值及状态依赖必须保留。
两个 ID 不同不证明不相交。细粒度 location 与 coarse world 必须有覆盖/冲突
关系；不能把未知 world 改名后声称与参数、文件或 RNG 无关。

| 状态域 | 必须分别建模的部分 |
| --- | --- |
| namespace / environment | module/global/builtins、defaults、cell 内容与所属身份。 |
| frame | 本地绑定、临时引用与异常/cleanup 上下文；普通 fast-local 采用 binding SSA。 |
| object / container | 字段、元素、descriptor/lookup 所需状态。 |
| Tensor / allocation | 内容、metadata、view selector、alias、求导关系及外部共享访问。 |
| RNG / mode | generator/device、training/grad/autocast 等模式和所需求导状态。 |
| filesystem | 路径绑定、文件内容/metadata、open-file 状态、handle offset 与缓冲。 |
| protocol instance | 编码器、环境、iterator 等实例前后状态。 |
| resource | queue、capacity、ownership、可见性与生命周期状态。 |
| observable history | 输出、日志及外部交互的顺序历史。 |

### 4.2 操作的效果接口

每个操作/Region 至少描述 reads、writes、allocates、releases、aliases、escapes、
RNG、异常/可能不完成、外部交互和所需顺序；每域分别标记完整性。空集合加
UNKNOWN 不等于无效果。normal/raise 等不同出口使用各自实际 post-state；
异常前已发生的写不能回滚为输入 world。

规范状态边只引用 StateVersionValue。Completion、frame overlay 和 resource
record 不另外维护可冲突的 before/after world。

RAW/WAR/WAW 和外部顺序必须区分内容依赖、必要先后与结构/证据关系。
`r=x[0]; x[0]=1; return r` 的先读后写不能只靠两个操作都读取旧状态保证。
完整覆盖写可以消除旧内容依赖，但不会自动消除前写的 RHS、异常或历史输出。
`print(1); print(2)` 的第二次写不 kill 第一次输出。

## 5. 控制：语言完成、挂起恢复、host 返回、资源完成

所有控制接口至少有规范字段：

```text
ControlPort(id, owner: RegionID, protocol,
            payload_signature, state_domain_signature)

EnvironmentInterface(function_object_reference, code_definition,
                     globals_namespace, defaults_location,
                     kwdefaults_location, ordered captured_cell_identities)
```

protocol 是版本化的强类型判别联合，不是自由字符串。payload 的实际绑定只
引用有序 Use 或该边产生的结果；状态实参只引用规范 StateVersionValue。
Environment 是隐式 body 入口，不是新增 Python formal；它声明身份/位置，
其内容版本经规范状态参数传递。两个函数可以同 code 不同环境，也可以共享 cell。

### 5.1 语言完成与类型化目标

```text
LanguageCompletion =
    Fallthrough(FallthroughTarget)
  | Return(ReturnBoundary, evaluated payload reference)
  | Raise(ExceptionPacket)
  | Break(LoopBreakTarget)
  | Continue(LoopContinueTarget)

LanguageOutcome =
    Complete(LanguageCompletion)
  | Suspend(SuspensionSite, ResumeProtocol, exported payload, ContinuationHandle)
```

Program target 是静态 scope/port；Execution 的 activation/loop/resume occurrence
为它提供动态绑定。不能将同 code 的两次调用指向同一返回 continuation。
Suspend 不完成原函数；没有观察到出口也不证明 divergence。

需要跨 cleanup 保存时，PendingCompletionValue 只包装 variant、目标和 payload
的规范 Uses；完成边传递当前 post-state。`finally` 可保留或替换 pending
completion；`with` 可抑制异常，不能用吞异常规则吞掉 return/break。

ExceptionPacket 引用异常对象、传播/handler 上下文及相关状态；不复制一套
可独立修改的 cause/context/traceback 属性。bare raise 依赖当前 handler。
`except*` 有 split/merge 协议，不能等同普通首个匹配 handler。
规则依据 [Python 复合语句](https://docs.python.org/3.14/reference/compound_stmts.html)。

### 5.2 调用不是一条无条件 body 边

```text
求值 callable -> 按语言顺序求值/展开实参 -> dispatch/绑定
    -> body entry / protocol adapter -> body outcome -> caller continuation
```

求值或绑定失败可以产生 Host Threw，但不能伪造 body entry。默认值来自函数
对象环境，不是某个显式 actual；bound receiver、partial、descriptor、hooks 与
`__call__` 需要各自路由。参数位置用有序 UseID 保留，`f(x,x)` 是两个使用。

同步函数的 Return 经边界适配成该次 Host Returned；callee Return 不是 caller
Return。动态目标/环境未确认时保留条件边，不能仅按函数名或相同引用闭合。

### 5.3 挂起实例与恢复

generator/coroutine 创建、进入、挂起、恢复、最终完成、关闭是不同阶段。
恢复请求有 Next/Send/Throw/Close 等具体协议，不用一个任意 NORMAL token。
ContinuationHandle 指定 owner Region、site、resume protocol 和 saved-frame
接口；执行时另带实例身份与 suspension generation。

保存的接口包括局部 binding、仍存活的临时引用、求值栈和 handler/cleanup
stack，以及存在时的 pending completion。恢复时接：

```text
保存的 frame-private 状态 + 当前共享状态 + 本次恢复请求
```

不能沿用 yield 时的旧共享 world；caller/callback 可以在两次 next 之间修改
cell、global 或输入对象。同一 suspension generation 不能动态复制恢复执行。
Yield 的 payload、最终 Return 与 iterator exhaustion 经不同 adapter 对接。

该 generation 指实际 body continuation，不等于每次外部 driver request 的 epoch。
委托协议可能接受请求并直接产生 host 结果而没有恢复父 body；只有真实 body
恢复才消费相应 continuation。driver 重入/排他与 body 恢复的代次分别建模。

frame 的 handled-context 保存可重定位的 body-owned 片段及“继承本次 caller”
边界，不能保存一次 `sys.exception()` 的扁平结果或固定 None。初入/恢复时以当前
caller 接链，挂起/真正结束时归还本次 caller；该 caller token 不跨挂起保存。
最终 frame-release 与 body completion/上下文切换分阶段描述，不静默套用同步
FrameExit 的出口邻接规则。

待实施的 [C2 合同](M1_RESUMPTION_INTERFACES.md)采用同一逻辑 body 的显式 temporal
successors；ordinary 数据可用性在恢复 landing 切断，保存 Uses 接新参数，共享状态
接本次输入。logical CFG 与 availability 是同一规范边的不同派生查询，不另存另一
套 producer/use。该设计尚未成为产品 capability，C2.0 字段冻结仍未关闭。

closure 是函数对象与环境/cell 的关系；callback 注册不等于实际调用。调度关系
可以跨词法父 Region 的返回，次数/线程/状态必须由实际协议和证据连接。

### 5.4 资源工作与就绪

```text
HostOutcome     = Returned(payload) | Threw(ExceptionPacket)
ResourceOutcome = Completed(ticket) | Failed(ticket, diagnostic)
                | Cancelled(ticket, protocol-specific result)
ReadyEvidence   = work generation + content/materialization version
                + allocation generation + consumer visibility domain + rule/evidence
```

enqueue 正常返回仅表示按协议提交；WorkTicket 指向具体工作及资源，不表示
结果已可消费。wait/event/stream 规则建立相应完成和可见性依赖。Cancelled
不普遍等于无部分输出或可立即 free。Ready 证据通常可被多个 consumer 使用，
不能套 continuation 的单次恢复约束。

Host return、device completion、host 可读、文件 flush/close 和持久化不是一个
事件。时间戳先后、相同 stream 名或 `ready_event: str` 不足以构造 ReadyEvidence。
具体物理规则要绑定实际 PyTorch/CUDA 版本；本文不宣称现 collector 已恢复它们。

## 6. Resource 的静态要求、定义与实例

```text
ResourceRequirement  对类别、选择条件、能力/容量的约束；不是已经存在的资源
ResourceDefinition   Program 中可被共同引用的资源身份/选择表达
ResourceInstance     Execution 中有生命周期代次的实际资源
Realization          definition/requirement -> instance，附范围和依据
HandleBinding        reference/object -> definition/instance，附生命周期与依据
```

Requirement 不是 Python handle 的 referent；未满足的要求不伪造实例。静态
未执行分支也可以表达资源要求。handle 仍是引用 Value，通过关系指向资源；
不新增一个无区分的 Reference 把 requirement/definition/instance 混在一起。

资源身份被 location、allocation、materialization、WorkTicket 和同步端口共同
引用。资源状态变化不改资源身份；资源销毁和新一代实例不能按同地址合并。

文件路径是数据值；路径到文件的绑定是状态；文件/输出端点是资源；Python
handle 是对象；open-file/offset/buffer 是状态。硬链接、rename、重开和图外
写入可能改变对应关系；路径字符串不变不证明读取值不变。

文件实体、open-file-description 与 handle 分开。两次 open 可共享文件内容但
offset 独立；dup 可共享 open-file-description/offset；fd 数字再用需要新代次。
ResourceDefinition 的一次静态创建可多次执行而产生多个实例，requirement 在
不同 occurrence 可由不同实例满足；外部实例无需虚构源内创建操作。

retain/release、ownership transfer、escape、flush/close/free 是有状态和完成
接口的操作。释放 Python 引用不保证立即释放 allocation，未完成 GPU 工作仍
可能使用 storage。finalizer、weakref、异常清理的可观察效果不能默认 NONE。

## 7. 每个源部分怎样分解

分类依据版本化语言/库协议，不依据业务命名。一行可对应多个操作；未执行
源码仍保留定义、作用域和归属，不制造假执行边。

| 构造族 | 必需的组合规则 |
| --- | --- |
| module/import | 搜索与 hook、cache/namespace、部分初始化、正常/失败状态、导出绑定；取到常量不删除初始化。 |
| function/lambda | 定义阶段与调用阶段分开；默认值、decorator、annotation/type-param phase、globals/cells、函数对象创建和实际调用。 |
| class/type alias | class namespace/body、bases/metaclass 与隐式调用；lazy/type scope 与其访问阶段明确。 |
| binding/assignment/delete | 编译作用域、普通重绑与对象写分开；RHS、target 求值及解包顺序、部分写/失败与旧引用释放。 |
| arithmetic/lookup | operands 按协议求值；特殊方法、反向/in-place dispatch 和状态/异常；attribute/subscript 不是纯字段标签。 |
| call/packing | callable/实参求值、star 展开、keyword 合并、绑定和 entry 分开，重复实参有独立 Uses。 |
| boolean/compare/conditional | 短路路径、truth 调用、返回的实际 operand；比较链不重复求值中间项。 |
| for/while/comprehension | iterator/advance、零次、回边、carried binding/state、过滤及 scope、else 与 break/continue 目标。 |
| match | subject 一次求值、pattern lookup/匹配、capture/guard、按路径失败与后续 case；不能把 pattern 当普通全求值表达式。 |
| try/raise/with | handler、异常上下文、pending completion、cleanup/抑制、部分效果；except* 独立协议。 |
| yield/await/async | activation 与 resume、委托/异步迭代/context、保存 frame、当前共享状态、关闭/取消及异常。 |
| formatting/template | 表达式、conversion、format spec 及协议调用；3.14 模板不等同立即格式化字符串。 |
| assert | 目标编译模式决定是否执行；message 惰性求值，异常构造也可失败。 |
| global/nonlocal/pass/metadata | scope/phase 事实与无执行效果分别记录；不作为未知计算替身。 |
| native/library/dynamic code | 类型化调用接口、环境/状态/资源/完成及展开状态；动态源码有新快照与编译上下文。 |

必须保留语言特有的求值顺序，不能依 AST field 顺序机械展开。例如 Dict 的
key/value 交错、短路、assignment target、comprehension scope 和定义阶段都
需要自己的协议。Python 3.14 的构造守恒清单另见
[PYTHON314_PROTOCOL_CATALOG.md](PYTHON314_PROTOCOL_CATALOG.md)。

`return x; x=1` 的后一句虽未执行，仍影响 x 的局部作用域。因此不可达源码
不能全部删除后再解析绑定。[Python 执行模型](https://docs.python.org/3.14/reference/executionmodel.html)
与 [import 规则](https://docs.python.org/3.14/reference/import.html)分别约束这两类关系。
隐式调用依据 [数据模型](https://docs.python.org/3.14/reference/datamodel.html)，求值依据
[表达式规则](https://docs.python.org/3.14/reference/expressions.html)。

每个具体协议需要列出输入、环境、状态域、资源、正常/失败/挂起出口、顺序、
生命周期和内部展开规则。库实现未知时保留这些接口及分域未知；不能用一层
opaque 包装把已知的前后调用抹去，也不能把未知内部当已恢复。

## 8. 从加载到推理到保存：同一组接口

```text
文件 namespace/content version
 -> read -> bytes/表示 -> deserialize/parse
 -> object/allocation -> 参数与 buffer 状态写入
 -> materialize/transfer -> GPU 表示 + readiness
 -> 有 control/environment/state 输入的推理/规划 Region
 -> 动作 -> 环境状态推进 -> 帧版本序列
 -> 编码器前后状态 -> 字节/块序列
 -> 有序 write -> flush/close/失败后态 -> 输出文件版本
```

视频保存与 Tensor 保存共享表示转换、状态推进、外部写入及完成协议。载荷
不同不新增业务节点；编码算法、流式缓冲、顺序、失败和输出合同仍不同。

LeWM 反向验证要求如下，原始名字只在 testcase 文档出现，不进分析规则：

| testcase 中的角色 | 通用表达 | 对化简的约束 |
| --- | --- | --- |
| goal / observation | producer、binding/reference、当前内容版本、来源与表示。 | 不按名字推定恒定；observation 更新必须沿状态边传播。 |
| embedding | transform 的结果，连接输入版本与模型/模式状态。 | 输入相同不独自证明 encoder 无其他依赖。 |
| action candidates | 分布/RNG/状态相关的新结果与动态发生。 | 每轮变化不能按同一静态 ValueID 合并。 |
| CEM loop | sample、rollout、encode、cost、update 的 Region/端口与 carried state。 | hoist 需要路径、异常、版本、资源与生命周期同时合法。 |
| environment / frame / output | 外部状态推进、callback 环境、帧来源、编码和有序输出。 | 不能只沿最终 Tensor 反向追溯而丢失交互。 |

自动前端必须从原程序产生这些具体连接；人工画出的压力路径不计自动覆盖。

### 8.1 Python、PyTorch 与 kernel 的层次对应

```text
Python function Region
 -> module 调用协议（对象状态、hooks、forward dispatch）
 -> Torch operator 协议（tensor/metadata、模式、RNG、autograd 与状态访问）
 -> 实现/dispatch 对应
 -> CPU 工作或 GPU WorkTicket（kernel/copy/allocation/wait）
 -> allocation/materialization/readiness
```

层次之间不是固定一对一：一个 operator 可没有 kernel、产生多个 kernel 或
物理 copy；多个 operator 也可由一个实现区域承载。view/expand 可只建立访问
关系；同设备 `.to()` 可返回原对象。collector 看到的 host span 不是 GPU 执行
区间，module 的重复调用次数不是 kernel 或 transfer 的次数。

module 对象、参数、buffer、hooks、training/grad 模式与所需 RNG 状态均是输入
依赖的一部分，`.eval()` 不授予纯性。默认 CEM 路径不代表其他 planner 不需要
action 的梯度；autograd 关系及 detach/alias 的影响由合同和状态接口保留。

dataset/index/文件读取、解码、归一化、共享外部 buffer、device 物化与 embedding
是不同的生产/访问/推导关系，不能只用“输入 Tensor”压缩全部生命周期。
反序列化也可能执行用户代码；未核对协议时不能将 load/parse 当无效果常量操作。

## 9. 三种图与跨层对应

| 投影 | 保存什么 | 不得承担什么 |
| --- | --- | --- |
| Program / SG | 所有定义/phase、操作/Uses、Region 接口、状态与资源要求。 | 将未执行分支当作已执行。 |
| Execution / EEG | invocation/visit/resume、对象/分配代次、实际工作/物化与原始证据。 | 用一次运行补齐所有可能行为。 |
| Optimization / OIR | 已闭合替换边界、观察合同、替代 delta、证明/guard/失效和成本。 | 从缺失程序边凭空生成合法性。 |

Correspondence 明确静态/动态多重性、有序 use、目标/环境、completion 与资源
realization。引用路由、数据内容来源、效果闭合分别报告；一条路由成功不证明
其他两项。Observed、Inferred、Proposed、Implemented、Verified、Rejected
按具体命题与范围使用，不能给整张图笼统升级权限。

### 9.1 递归展开守恒

展开/折叠保留 actual/formal、环境、资源要求、输出、所有完成方式、状态、
alias/escape/身份、生命周期及必要顺序。词法包含不是执行顺序；调用引用可
递归，结构所有权仍无环。隐式协议调用也必须有位置，不能只展开显式 Call。

展示可用 Operation 作方框、Value 作边，但规范 Value 与具体 Use 仍是一等记录。

## 10. 化简需要的接口，而非本轮新增规则

后续优化单位由依赖闭包决定，可以是 instruction/operator、function、loop、
dataflow subgraph 或 pipeline stage；不预先固定为 module call/event。

| 后续任务 | 必需模型信息 |
| --- | --- |
| 常量替换并删除 import | 精确值推导 + 全部活使用改接 + 模块初始化/cache/异常/交互依赖是否仍活跃。 |
| 深层工作上移 | 全部数据/环境/状态最早可用边界 + 支配/路径条件 + 失效/异常/生命周期。 |
| reuse / residency | 内容版本、完整 effects、输出 alias/身份合同、物化有效期与资源成本。 |
| fusion / capture | operator/region 依赖、控制稳定性、资源/stream/生命周期及完成协议。 |
| prefetch / deferred materialization | producer-consumer、可用/消费时点、可见性、异常/外部顺序。 |

“第八层只依赖第三层输入”不足以独自许可上移：第八层可能只在某分支执行、
读取隐藏状态或抛异常。模型需给出缺失依赖的具体端点；不能永久以一个泛化
UNKNOWN 拒绝，也不能为了通过而删除这些义务。

SCAR 应给出具体位置、替代值/子图、保留依赖、可删区域、理由、合同、未证
条件与成本。当前阶段不添加 detector/backend，不把表中任务写成已实现。

## 11. 当前实施边界与待验收事项

### 11.1 下一阶段 validator 必须检查的不变量

1. source/definition、静态 ValueID、动态 occurrence 与 logical version 不混用。
2. 每个规范结果有唯一 producer/合法 origin；每个有序 Use 在实际入边路径可用。
3. completion target 的 scope/类型正确；cleanup、resume、host 与 resource 端口
   不能仅凭相同 payload 类型互接。
4. 状态实参与位置/domain 一致；每个出口保留最新后态；未知/coarse 与细域有
   保守覆盖，不能按不同 ID 消除冲突。
5. continuation 的实例/代次只合法恢复一次；恢复 frame 与当前共享 world 分开。
6. resource requirement 不冒充实例；handle、allocation、work/ready 各自代次
   和有效期一致，旧 event 完成不证明后来一次工作已完成。
7. 值推导与物化推导分离；内容相等不取消 alias/身份/梯度/ownership 约束。
8. Region 展开前后接口与未知范围守恒；derived summaries 不创造规范事实；
   未展开内部调用不得计为已恢复。

### 11.2 当前实现状态

原 core 已增加四张静态资源表、对应校验及严格 v4 wire；有限组件 198 项通过，
见 [M1_RESOURCE_INTERFACES.md](M1_RESOURCE_INTERFACES.md)。这是 M1 的资源子项，
不代表动态资源满足、work/ready 或完整第一阶段已实现。字段级协议规格另见
[数据定义](model/PYTHON_DATA_DEFINITION_PROTOCOLS.md)、
[控制](model/PYTHON_CONTROL_PROTOCOLS.md)与[资源](model/RESOURCE_PROTOCOLS.md)。

冻结实现 `dcd498699e0cd1331cf496158b29575c3fc2c536` 有限支持 local-binding、
普通同步表达式/调用、if、while/for、break/continue/else 和显式 typed 接口。
组件 290 项、全仓 2,657 项通过，见
[有限实现验收](N2_STRUCTURED_BODY_ACCEPTANCE.md)。这些结果不证明本规格整体实现。

完整 FunctionEnvironment、cleanup/exception、resumption、Resource/ready、
library/file 协议与跨复制/变换来源尚未自动接通；whole-body unsupported 路径
仍存在。旧 inventory 尚未全面接入 structured profile。LeWM 全过程未闭合，
没有经验证的自动变换或 clean A/B 加速比。

规格通过、类型代码通过、自动建图通过和化简通过分别验收。未知部分逐项列明，
用户无需手工补图、标 pure、列常量或选择待分析函数。

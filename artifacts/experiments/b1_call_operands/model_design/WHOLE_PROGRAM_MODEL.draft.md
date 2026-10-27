# SCAR 完整程序抽象模型

日期：2026-10-16。状态：**模型规格修订草案；不是全过程自动建模已完成的声明。**

本规格先定义程序由什么组成、接口怎样连接，再约束自动建图和后续图化简。
它修订“完整模型只有四类实体”的说法。现有 `ProgramGraph` 的四类结构是一个
控制/数据投影；完整模型另有独立资源实体，以及强类型协议和运行对应关系。

## 1. 模型的边界与问题

当前实施范围是 Python/PyTorch、CPU、单 NVIDIA GPU、本地文件与程序实际调用的
本地库/环境/输出过程。入口命令、源码及依赖版本、配置、环境和观察合同共同
确定分析范围。没有观测的分支、未调用的定义和 native 边界仍须有明确位置。

```text
Program = 输入值 + 初始状态 + 资源要求 + 代码/环境
       -> 返回值 + 最终状态 + 可观察交互 + 完成/不完成行为
```

“任意一行有分类”不等于“所有依赖已恢复”。规格分开验收：类型是否可表达、
每个构造是否有协议、源码是否自动构建端点、运行是否对应、依赖是否足够精确。
图化简只能在这些接口与合同支持的范围内进行。

## 2. 五个一等结构家族

| 家族 | 身份与职责 | 不允许混淆 |
| --- | --- | --- |
| Operation | 一处操作定义；有有序使用、结果、状态效果及控制/完成接口 | 源码函数名、动态调用或性能事件 |
| Value | 一个不可变定义或区域端口的结果，包括数据、引用、绑定与协议值 | Python变量名、物理地址、采样内容 |
| StateLocation | 可以变化的位置/状态域的身份；每次读取/更新引用明确版本与footprint | 当前位置内容、资源身份或allocation地址 |
| Region | 带入口、出口、环境、捕获和内部结构的子程序；可以递归展开 | 缩进容器、默认纯区域或一次trace展开 |
| Resource | 多个操作/状态/物化共享的执行或承载实体；有要求、定义和实例对应 | 资源容量状态、Python handle或某次enqueue |

Resource 的必要性可由最小例子验证：同一 stream 被多次 enqueue/wait 引用，
多个 allocation 属于同一 memory pool，两个文件句柄可能指向同一文件。资源可
在程序进入前存在，其状态又独立变化。把资源写成某个 StateVersion 或 op 的
label 会丢失这种共享身份。

程序定义、资源/表示、执行证据、优化区域可以分别存储；它们属于同一完整模型，
通过强类型端口和对应关系连接。四类旧 ProgramGraph 可继续作为投影，但必须
保留资源外表/引用；不能因此宣称完整模型没有 Resource。

## 3. Value、身份与来源

Value 的必要变体如下；这是模型合同，不表示全部变体已经实现：

```text
DataValue                  逻辑结果/数据
ObjectReferenceValue       指向对象身份及访问关系
LocalBindingValue          某槽的 BOUND/UNBOUND/合流状态
StateVersionValue          某位置的前后状态版本
LanguageCompletionValue    normal/return/raise/break/continue/suspend
ResumeRequestValue         next/send/throw/close 等恢复请求
ResourceReferenceValue     指向资源定义/需求/实例的 handle 对应
WorkTicketValue            某次提交工作的身份/代次
ReadyCapabilityValue       特定工作、资源和可见范围的完成条件
```

输入/输出是 Region 端口角色。常量、不变量、相等、收敛是有范围和依据的性质，
不把它们当互斥值类型。协议值不允许作为普通 Python 实参或 Tensor 数据偷渡。

必须分开五种身份：

1. Code/Operation definition：版本化的静态定义。
2. Dynamic occurrence：调用、循环访问、恢复和执行上下文中的一次发生。
3. Object identity：对象存活期内的引用身份；地址再用不是同一对象。
4. Logical value/version：哪次逻辑数据定义或状态版本；独立于 storage。
5. Allocation/materialization：物理分配、表示实例及其生命周期。

`Provenance` 是输入版本、操作及状态如何产生输出版本的推导关系。它不自动
证明输出相等。deepcopy/copy 是否保持逻辑版本取决于具体协议与效果；自定义
copy 不能默认透明。view 可以共享位置，同时有不同 shape/stride、选择范围与
对象身份。相同引用或 Tensor `_version` 不证明 NumPy 共享内容没有外部更新。

DataValue 不要求保存 Tensor 数值。shape/少量样本可用于排除变化或安排核对，
样本相同不授予版本/内容相等结论。

## 4. 状态位置、版本与效果

Location 至少需要可区分的 owner/selector/domain：

| 状态域 | 位置与访问必须保留什么 |
| --- | --- |
| namespace/binding | module/global/builtins/cell 的owner与slot；普通fast-local绑定另用binding值 |
| object/container | owner引用、field/key/index selector及动态descriptor/lookup协议 |
| tensor/storage | allocation生命周期、offset/shape/stride/dtype及重叠footprint |
| RNG/mode/autograd | generator/device、训练/梯度模式、buffer与求导关系的状态域 |
| filesystem | namespace/path绑定、文件内容/metadata、句柄offset/open状态分别版本化 |
| encoder/environment | 协议实例的内部状态、输入顺序、外部交互与部分更新 |
| resource/queue | capacity/ownership/queue/visibility状态，引用独立Resource身份 |
| observation history | 日志、stdout、文件写入或外部交互的必要顺序历史 |

一个状态版本是逻辑定义，不是把旧内容复制保存了一份。循环中的静态版本定义
有多次动态发生。Unknown/coarse域与细域之间必须有覆盖/alias关系；不同ID不能
成为不冲突证明。未知范围读取/写入保守影响对应观察根。

每个操作/Region的效果接口包含读、写、分配、释放、alias、escape、RNG、异常、
外部交互和顺序。正常与异常完成分别带post-state；异常前发生的部分写入不能
回滚。未证明无效果时不使用空集合代替未知。状态版本、访问范围与控制选择
共同决定依赖，不能仅按操作类别推导复用。

## 5. 三种不同的完成关系

### 5.1 语言完成与continuation

```text
Completion = kind + typed target + payload + post-state
kind = Normal | Return | Raise | Break | Continue | Suspend
```

target是具体激活实例的continuation/循环/返回端口，不是函数名。`finally` 接收
pending completion，执行后保留或替换它；`with` 的退出协议可抑制异常。清理期间
新异常及其context也必须保留。异常分组处理不能等同普通单异常匹配。
这些语言协议依据[Python复合语句规则](https://docs.python.org/3.14/reference/compound_stmts.html)。

### 5.2 挂起与恢复

generator/coroutine拥有自己的激活状态：create、enter、suspend、resume、finish、
close等是不同动作。恢复连接保存的frame-private绑定/handler/pending completion
和恢复时的当前共享状态；不能恢复旧world并假定外部未变。callback引用函数对象、
环境和实际调度关系，不能简单成为词法父Region的无条件顺序子块。

### 5.3 host return、工作完成与ready

enqueue正常返回可产生WorkTicket，但不产生“GPU结果已就绪”的结论。Ready必须
绑定工作代次、资源、stream及可见范围；wait建立必要的先后/可用关系。work完成、
host可读、文件close与持久化不是同一个事件。缺少证据时保留具体未满足端口。

这三类关系通过依赖边联系，不能合并成一个 NORMAL/RAISE 或 ready 字符串。

## 6. 程序每个部分怎样进入模型

源码关系保留版本、AST/编译结构、声明phase、词法scope与生成对象；执行关系再
描述何时激活这些定义。单行可以产生多个操作；无执行动作的源部分也有source归属。

| 程序构造 | 规范分解/协议与必要连接 |
| --- | --- |
| module/import | 解析与模块查找、cache/namespace、初始化Region、正常/失败状态；不只取一个值 |
| def/class/type/annotations | 定义时与调用/访问时phase分开；环境、默认值、装饰器、class namespace及lazy部分有各自接口 |
| Name/赋值/删除 | compile scope与运行绑定分开；读/重绑/unbind；属性/索引写与普通局部重绑不同 |
| arithmetic/lookup/call | 有序求值、语言dispatch协议、实际参数occurrence、环境/状态、返回/异常；隐式用户方法仍是调用 |
| if/boolean/compare/match | 路径启用、短路、truth/匹配协议、路径相关绑定与合流，不把子表达式全当必执行 |
| for/while/comprehension | 获取/推进iterator、零次/回边、绑定与状态carried、else、break/continue、临时生命周期 |
| try/raise/with | handler选择、pending completion、清理和抑制、异常状态与部分效果 |
| yield/await/callback | create与enter分开；恢复请求、保存frame、当前共享状态、实际调度与完成 |
| I/O/native/library | 有输入/输出、状态/资源与完成的外部接口；实现未知与接口未建模分项记录 |
| 非执行源码部分 | 声明、注释、type metadata、未激活body等仍有来源归属；不制造假的执行CFG边 |

作用域和绑定规则需要完整代码块，即使某条赋值在return之后，也可能影响前面的
局部名称解析。因此未执行源码不能简单从模型丢弃。
[Python执行模型](https://docs.python.org/3.14/reference/executionmodel.html)规定该基础关系。
import本身的初始化/cache等行为依据[import系统](https://docs.python.org/3.14/reference/import.html)。
运算和求值顺序依据[表达式规则](https://docs.python.org/3.14/reference/expressions.html)，
隐式方法与对象协议依据[数据模型](https://docs.python.org/3.14/reference/datamodel.html)。

版本化语言规格应有完整构造清单及逐field求值/作用域规则；遇到新AST类型需明确
扩展规格，不能自动归成纯compute。当前已实现lowerer子集不等于该清单已实现。

## 7. 加载、推理与保存的共同模型

```text
文件namespace/内容版本
 -> 读取 -> bytes/表示 -> 解析/反序列化
 -> 对象/分配 -> 模型参数与buffer状态
 -> 物化/搬运 -> GPU表示及ready条件
 -> 有控制与状态输入的推理/规划Region
 -> 返回动作 + 环境状态推进 -> 帧版本序列
 -> 编码器前后状态 -> 字节/块序列
 -> 有序写入 -> flush/close/失败状态 -> 输出文件版本
```

这是通用协议组合的压力路径，不是预写给LeWM的优化图。自动前端必须从原程序
生成具体操作、引用、状态与端口；人工图不计自动覆盖。保存Tensor/视频共享同类
表示转换、状态推进和外部写出基础接口，具体编码器规则、顺序与失败合同仍有区别。

资源侧同时连接file/storage device、host memory、GPU memory、CPU/GPU/stream、
thread/process及外部编码库。数据/控制一条路径不能替代这些承载和完成依赖。

## 8. 从模型到图

1. **Source/Program projection：** 保存所有定义和phase、操作/端口、状态、控制、
   资源要求与递归Region；未激活body和不可达源码有明确归属，作用域事实仍保留。
2. **Execution projection：** 加入真实invocation/loop/resume occurrence、对象/
   allocation epoch、物化、资源实例及事件；observed与inferred事实分开。
3. **Correspondence：** 逐个有序Use、实际dispatch、环境/状态及完成端口连接；
   一个静态callsite的多次执行不能合并。资源requirements到instances另有映射。
4. **Optimization projection：** 以观察合同为根选择已闭合区域，再构造替代方案。
   未知依赖穿过区域时保留具体证明义务；不能以重复节点数量授予权限。

模型的静态定义不是执行展开；trace不是所有可能程序行为；OIR不能补造缺失依赖。

## 9. 完整性的验收条件

以下全部是必要条件，不用测试数量或节点数代替：

- 语言构造/声明phase/源部分有守恒清单，所有未解析部分逐项列明。
- 每个操作有有序输入、结果、所需环境、状态、控制与完成接口；未执行源码影响
  scope时，其事实仍能追到相应binding/lookup规则。
- 每个Region有可递归展开的接口；未知子部分不抹去周围已知结构，也不伪装为
  无效果、普通fallthrough或没有内部调用。
- 资源身份、要求、实例、状态、ownership、allocation与ready是可区分的实体/端口。
- 正常、异常、清理、挂起、恢复及不完成行为均有表示；相关反例可击穿错误简化。
- 可从视频/日志/返回/外部交互等观察根追到所需输入、状态和完成条件；无法追通
  的边界有具体类型、原因和影响范围。
- 自动生成、依赖精度、运行对应、化简权限分别报告，任何一项不借另一项充数。

当前判定：**未完成。** dcd4986实现了有限同步binding/loop模型，组件290项和
全仓2,657项通过；原自动候选集的新源码压力验证仍进行中。完整环境、异常清理、
resumption、Resource/ready与library/file协议尚未自动接通。本文不宣称LeWM变换
或加速，也不把规格写下等同实现和验收。

官方参考页面本次为Python3.14.8；实际环境为3.14.7。规格和探针必须绑定实际版本。

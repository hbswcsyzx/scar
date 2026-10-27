# 程序图中的节点、边和采集职责

当前阶段目标是完整建模。动态采集用于补充实际调用、数据、状态、资源和必要顺序；
不以性能热点或运行时间排名决定哪些部分进入模型。性能采样保持显式可选。

## 展开到哪里：以化简所需的依赖为界

2026-10-26用户澄清：建图、存图服务于化简，完整建模不要求还原不可替换组件的
内部实现。核心图覆盖程序操作、值、必要状态和资源接口；Linux FD表内部布局、
内核分配器或驱动内部算法不作为必需展开项。程序中的open/read/close、allocation、
enqueue/wait仍是操作，可以在上层区域中消除、合并或移动。

接口摘要须表达有序输入/输出、读写状态、别名/逃逸、失败及必要顺序。资源身份、
读写游标和handle代次只在关系判定需要时保留；完整FD表回放不是全图前置。
例如同一个fd数字先后可指向不同文件，核心关系应是Read→资源/版本，而非将fd
数字当作数据身份。上层已能提供准确关系时，不再为了覆盖率展开操作系统实现。
底层原始事件属于可选证据，只有具体依赖或化简合法性仍未确定时按需追查。

有边界合同不等于任意Python函数可被当作黑箱。程序可化简的函数、循环和算子仍
须恢复其子图；未知效果保守表达，不能用精简图为理由将其改成NONE。

## 节点怎样对应程序

以下是五个核心概念家族，具体实现有各自的强类型记录，不能仅凭一个家族标签
认为全部细节已经建模。

| 家族 | 程序对应 | 已有具体记录示例 |
| --- | --- | --- |
| Operation | import、调用、计算、索引、复制、分配、等待、读写等动作 | 静态`Operation`、动态`OperationOccurrence`；异步实际工作另有`WorkSubmission`及完成记录 |
| Value | 计算传递的数据、对象引用、局部绑定和状态版本 | `DataValue`、`ReferenceValue`、`LocalBindingValue`、`StateVersionValue`、`ValueOccurrence`；内容层有`LogicalValue`/`ValueVersion` |
| StateLocation | 对象字段、容器槽位、模块/RNG/环境等可变位置 | `StateLocation`、`StateAccess`、具体地址refinement及前后状态端口 |
| Region | 模块、函数体、循环、分支、异常处理和可展开的复合结构 | `Region`、Block、控制/异常端口、`RegionActivation`和`BlockVisit` |
| Resource | 执行设备、内存、文件、设备、线程、队列及其具体实例 | `ResourceDefinition`、`ResourceInstance`、`HandleBinding`、`StorageAllocation`、`StorageRegion`、资源关系与使用记录 |

对象身份、storage、逻辑版本和`Materialization`分别保留准确记录及ID。一个逻辑
版本可能有多个物理副本；多个view可以指向同一allocation的不同区域；一个对象
可以有多个状态版本。同来源、同shape或相同地址均不自动建立值相等关系。
CodeID/源码定义给静态操作提供版本身份，Invocation/activation给动态发生提供身份。
来源和观察记录在证据层，通过引用支持程序图中的关系。

例如bytes等不在旧标量表示范围内的源码常量，通过`CODE_CONSTANTS_314_V1`指向独立
CodeWitness中原`LOAD_CONST`的准确位置和常量槽；复用现有`CodeConstantSource`及
`ReferenceValue`，不新建一类对象或把内容塞进对象身份。源码/槽内容匹配不证明
活动CodeType或常量Python对象实例相同。该能力只接受有准确槽依据的原常量；编译折叠
等导致原表达式没有对应`LOAD_CONST`时保留具体前沿，不补造运行操作。

Lambda同样区分创建与执行：创建操作产函数引用，default表达式只在创建时求值，
closure捕获cell引用；独立子Region包含原表达式body及自己的参数、环境和返回端口。
创建到body的引用是可展开定义关系，不是一次已经发生的调用，也不冻结将来的cell内容。

## 边怎样连接

| 边/关系 | 必须保留的含义 |
| --- | --- |
| 产生与使用 | producer→Value；Value→consumer的有序Use，含输入角色/序号；同一个值使用两次不能合并成一次 |
| 状态流 | 操作读取/写入的准确位置、进入版本和后继版本；未知影响保持保守依赖 |
| 控制流 | 分支条件、后继、循环回边、异常/返回及清理路径 |
| 跨调用 | 调用者的实际Use→callee formal，以及返回/异常→调用者对应结果；receiver有自己的角色 |
| 包含/展开 | Region包含Block/Operation，调用或复合操作通过限定关系展开到内部Region |
| 物理实现 | 值版本→Materialization→storage区域/device，操作→资源使用，句柄→资源实例 |
| 顺序/生命周期 | enqueue、队列、wait、完成、allocation/free及handle代次；时戳相邻不建立数据依赖 |
| 来源 | 精确源码版本、实际provider事件或接口协议支持哪一条关系 |

普通关系既可由有类型的edge记录保存，也可由有类型记录中的ID引用表达。多元关系
如Materialization需要同时指向值版本、区域、设备、producer和ready；这些字段
不能在展示成一条简单线时丢掉。

## 操作节点、数据边的展示

```text
[读取] ──raw──▶ [预处理] ──CPU tensor──▶ [搬运] ──GPU tensor──▶ [编码]
  │               │                      │                       │
文件/句柄       CPU/DRAM              stream/设备内存          GPU work
```

这是示意，不是本次LeWM的已证链。数据边是Value记录的折叠视图；展开后可以查看
版本、各个消费者和物理副本。点击函数/循环节点展开其Region，再进入算子、runtime
与kernel；边的类型和原ID始终保留。静态图涵盖未执行路径，动态图说明哪些发生过，
跨层关联将两者连接；collector上下文不能冒充直接调用。

## 怎样自动获得，怎样减少干扰

1. 静态使用AST、symtable、字节码、CFG/def-use恢复定义、操作、控制、端口和候选依赖。
2. 动态仅补实际dispatch、入口/退出、必要引用/状态变更、native活动与资源生命周期；
   参数和来源能由静态规则恢复的，不逐迭代复制Tensor数值。
3. 优先观察器已有的ID、metadata和完成关系；不为建模新增Tensor全量hash、`.cpu()`
   或CUDA同步。GPU利用率/CPU利用率采样不属于结构建图的必需数据。
4. collector自身工作与目标程序工作分别标记。记录采集下的发生关系；观察到的耗时
   和调度不能直接当作无插桩执行的耗时或顺序。
5. 用原ID及版本连接分片，按需读取；具体未支持的结构或缺失的边保留明确缺口。

## 当前真实实现边界

已有局部静态图、动态发生图和跨片查询；全程序连接仍未完成。
`query-program`已沿真实GPU work查询到native/source上下文及静态body。
`query-call-ports`读取本次实际产出的2,516个调用、6,805条条件实参→形参端口关系；
该关系不证明运行时对象/内容相等。原完整运行的末尾比较脚本exit1保留，独立
postflight核输入和旧27条关系通过，不能把原失败改写为成功。
`query-os-file-topology`可返回真实OS调用及原资源引用；本次目标IO到块设备的准确
绑定仍缺完整stat与共享FD连续性依据，不能由硬件库存或文件路径补猜。

实现入口见[跨层查询](PROGRAM_QUERY.md)，后续继续补真实缺失的边，不进入图化简。

新增的[stream接口观察](STREAM_INTERFACES.md)给原CALL附加实际builtin接收者、状态
角色及C完成，内存流与文件流共用接口；不包装对象、不读内容或cursor、不重建FD表。
它仍是原调用的资源接口证据，尚未补齐流到backing资源和canonical状态端口。

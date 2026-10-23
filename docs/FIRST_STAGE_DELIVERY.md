# 第一阶段交付：自动恢复整个程序及其资源

日期：2026-10-23。状态：**OPEN**。验收标准以
[FIRST_STAGE_MODEL_CONTRACT.md](FIRST_STAGE_MODEL_CONTRACT.md) 为准。
本文件统一当前执行顺序；历史 F 系列组件编号不构成串行开发队列。

## 1. 程序拆成什么

| 层次 | 实体及对应内容 | 必须连接的关系 |
| --- | --- | --- |
| 规范结构 | CodeIdentity；Operation；ValueDefinition；StateLocation；Region；ResourceDefinition/Requirement | 来源版本、有序输入/结果、状态读写、控制/异常、调用、包含、资源要求 |
| 实际执行 | Run、Process、Thread、Invocation/RegionActivation、OperationOccurrence、ValueOccurrence | 哪次执行实现哪个定义，哪个参数/结果属于哪次调用或循环访问 |
| 对象与环境 | ObjectInstance、Function/Module Environment、StateVersion | 引用对象、实际 callable、globals/defaults/cells、位置与前后态 |
| 内容与表示 | LogicalValue、ValueVersion、Provenance、Allocation、StorageRegion/View、Materialization | 来源与版本、alias/重叠、分配代次、物理副本、producer、失效及 ready |
| 执行与承载资源 | ResourceInstance、HandleBinding、ResourceWork、Completion | 使用者、设备/存储/线程/stream、handle 代次、生命周期与异步顺序 |
| 非执行事实 | Effect、Contract、Evidence、Measurement、CoverageObligation | 每个结论的依据、适用范围、未知的具体关系和成本 |

前述规范结构的五个支点并不是“只有五种记录”，也不是五种互斥行为。输入/输出
是端口角色；计算、表示、内存、搬运、状态、控制、等待、外部访问是可组合行为。
一行 `x[i] += f(y)` 会分解为多个操作和完成路径；保存 Tensor、保存视频共用表示、
buffer、资源写入与完成接口，不新造业务类型。

节点为广义操作、边为数据的图是查询投影。值必须是一等记录，才能保留唯一
producer、多 consumer 和重复参数槽。状态、控制、资源及包含有各自关系类型；
Region 可以递归展开。定义、实际发生及外部 provider 图不强行合成同一个 ID。

## 2. 如何机械获取

```text
原命令 + 原项目根 + 环境/输入范围
  → ast/symtable/dis + 编译/code witness：版本化源结构与控制
  → Python call/operand/function-environment 原档：实际调用、引用及入口
  → ETO + profiler/Kineto + dispatch 有序槽：算子、kernel/copy/sync
  → OS 独立记录：文件/设备/进程/线程/pipe/mmap 等资源
  → 共同 capture/run/process 坐标 + 准确来源对应
  → 原图组合、调用/端口/状态/物理关系连接
  → 按独立原始分母验收，保留未覆盖与未闭合项
```

复用现有编译器、profiler、schema 和 OS 证据；不执行额外 forward 猜数据边，
不存每轮 Tensor 数值，不按 LeWM 函数或包名写规则。依赖源码由实际 code 路径
需求触发，使用环境的独立 source root；不扫描整个文件系统或全部传递依赖。

## 3. 已有实际产物与边界

| 已实现并实际运行 | 实际结果 | 仍不代表什么 |
| --- | --- | --- |
| 未修改 LeWM 完整原命令采集 | episode 成功并保存视频；最新 100,438 次调用、39,796 次 dispatch | 不是干净性能基准，不代表已闭合全部依赖 |
| 联合运行坐标及资源导入 | 5 进程、252 线程；24,082 条 runtime→GPU 对应；74,574 条内存记录 | 未恢复的 OS 共享/继承、ready 与使用者仍 OPEN |
| 原档逐槽审核 | 79,592 个 marker、109,288 个 Tensor 引用槽均保留 | 保留 480 个祖先缺失、383 个未资格化叶，不能计作直接 Python→ATen 调用 |
| 版本匹配 ATen schema 适配 | 100 schemas、481 形式端口，467,756 个 Tensor 槽接形式端口 | 175,022 个无 schema；effects 均 PARTIAL；不证明纯性或逻辑内容相等 |
| 源码图组合与实际调用绑定 | 已有151文件原图可查询；旧54 body 的精确静态 witness 可用于当前调用 | 旧 body 数不与新检查点相加；不是完整 ProgramSnapshot |
| 更大范围源码构造 | 1,627 个原返回检查点，其中840个保留原图 | 最终报告因256MB输出上限失败；待恢复发布，尚无新全量覆盖率 |

详细依据分别在 `artifacts/experiments/first_stage_lewm_dispatch_20261023`、
`first_stage_joined_dispatch_20261023`、`first_stage_native_schema_20261023`、
`first_stage_dispatch_sources_20261023` 与 `first_stage_full_inventory_plain_20261023`。
所有关系保留原档 SHA、来源和未满足条件。没有新增 LeWM 变换或加速比。

## 4. 当前执行顺序与自验收节点

| 顺序 | 本次具体任务 | 自验收条件 |
| --- | --- | --- |
| A | 从逐body检查点恢复分片inventory，再复用原151文件源图组合并绑定同次 capture | 原请求/源码/profile/预算、1627个原checksum与完整图/overlay检查一致；不再组装大JSON；不重新称作 fresh lowering；发布最终manifest后才更新覆盖数 |
| B，与A并行 | 自动准入实际观察到的依赖源码，保留namespace/provider/snapshot/原三图/code witness | 全部entered group仍在分母；相同编译语境的完整descriptor匹配；不以路径归属冒充代码或effect证明 |
| C，与A/B并行准备 | 复用 profiler event tree，补同marker有序Tensor槽到物理allocation代次 | 精确nonce/原档/槽位依据；TensorMetadata.id、Result*、RF id、TID不可混用；不存在的映射保持OPEN |
| D | 接已有actual/formal/return/environment路由与原source/body引用，再核状态和资源依赖 | 沿原图而非复制producer；重用声明/引用不能替代实际关系；明确每个断口的来源 |
| E | 原命令端到端覆盖报告 | 加载→计算/环境→视频/结束全部必需项无未解释断点；范围与分母固定；S4通过后停止汇报 |

一次完整采集只在需要的新字段已共同确定后进行；不为每个小字段重复跑 LeWM。
失败原样保存，优先复用已保留证据。只验证实际剩余风险，不扩展无关测试套件。
新字段或接口实现但尚无实际运行时只能写 Implemented，不能写 Verified。

用户最新提出的大模型存储问题已纳入A：规范IR按图边界保存，原证据分块归档，
下一步通过统一ModelStore接口接SQLite查询索引。设计、并行与权威边界见
[GRAPH_STORAGE.md](GRAPH_STORAGE.md)；SQLite迁移尚未实施，不作为已完成功能。

## 5. 当前最关键的断口

- 依赖源码：71,368 次旧未绑定调用来自项目边界，70,565 次对应源码实际存在；
  不是整体不可理解。另有新 code、模块初始化、genexpr/lambda、延迟 annotation
  需要各自正确的定义与区域接口。
- 跨调用数据：源码 body、调用帧和 native Tensor 引用已有局部连接，但 actual/
  formal、return、function environment 及可变状态必须逐槽接入。
- 物理表示：allocation 记录不等于 Tensor→allocation 的证明；物理副本不是
  LogicalValueVersion。host 返回不能证明 GPU ready。
- 外部资源：OS handle/事件清单仍有共享、继承、mmap、设备和完成关系未闭合；
  不能用“有文件/线程节点”代替使用者及数据依赖。

因此第一阶段仍 OPEN。其后的化简、修改指导和成本选择均不在本轮执行范围。

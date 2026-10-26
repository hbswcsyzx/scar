# 建模边界审计：为化简保留最小充分依赖

2026-10-26。用户最新要求优先：建图和存图服务于化简，不追求越底层越好。
本轮已审计模型主干及其实际producer/consumer，下面区分边界决定、实测问题和
尚未实施的收敛。**这不是完整程序已建模或迁移已完成的声明。**

## 1. 纳入理由

一项信息只有满足以下用途才进入默认模型：

- 表达程序可以删除、复用、提前/延后、合并、替换或重新调度的操作/区域。
- 保留判断上述调整是否合法所必需的数据、状态、副作用、别名或顺序。
- 提供选择方案所需的资源能力、容量或实际成本。

其余材料作为按需证据或实现细节处理。不能只以“已采到”“底层更真实”或
“以后可能有用”为理由将其变成核心节点。能否调整程序侧调用/区域与能否改动
被调用组件的内部实现分开判断：分配、复制、launch、wait和文件读取仍可被上层
化简；操作系统、驱动、分配器的内部算法无须因此展开。

一个边界摘要必须保留输入输出、所读写状态、失败、必要别名/逃逸和顺序。
不了解内部实现时可以保守表达效果，不能把UNKNOWN改成NONE；也不能以接口摘要
替代本来应展开、且有化简价值的程序函数/循环。这是抽象层级收敛，不是删除依赖。

## 2. 当前模型逐层处置

| 当前记录及实现 | 审计决定 | 理由及边界 |
| --- | --- | --- |
| `program/model.py` Operation、Value、Use、Region、StateLocation | 保留核心；按Region递归展开 | 这是程序数据/状态/控制依赖及后续区域替换的对象；同一次Use不能随意去重。 |
| `program/functions.py` 与函数/闭包接口 | 保留创建、调用、捕获状态、返回/异常接口 | 函数对象创建和调用是不同动作；子body定义共享，不能把创建误算成执行。 |
| `program/structured.py`、`control.py`、`cleanup.py`、`frames.py` | 折叠管理性步骤，必要约束保留；细节放语言展开/验证层 | 异常、最后释放及对象finalizer可能影响行为；packet/pending转发和CPython staging无须逐一进入默认操作视图。不能直接把它们当可删除运行工作。 |
| `v2/values.py` LogicalValue、ValueVersion、Provenance | 保留核心数据关系，补实际连接 | 来源、对象、内容版本分开；状态版本符号不等于保存Tensor数值。 |
| StorageAllocation、StorageRegion、Materialization | 保留决策所需的分配/view/副本/设备及生命周期摘要 | buffer复用、驻留、传输消除需要这些关系；裸地址、allocator日志和内部free-list不成为主图。 |
| `program/resources.py`、`execution/resources.py` | 保留程序资源接口及必要alias/生命周期；完整handle-table细化按需 | 文件/游标/访问目标有意义；Linux FD表内部实现和全量回放不再是第一阶段前置。 |
| CPU/GPU、DRAM、存储拓扑与设备能力 | 共享资源属性/成本附着 | 不创建不可调整的微架构/控制器内部操作图；序列号、全sysfs快照等未被决策使用的细节留证据。 |
| `native_schema.py`、原OperationDefinition/OperationInstance | 保留可观测算子边界/端口及展开关系 | schema可用性与CPU/category分轴；缺强normal/identity证明不能成为不建操作节点的理由。 |
| SCAR markers、user annotations、provider回放检查 | 证据或scope附着，不自动升级为程序计算节点 | 它们用于定位/验证；collector生成的标记不属于目标的可化简工作。 |
| GPU kernel/copy/memset/runtime及`execution/work.py` | 程序launch/copy/sync及必要队列依赖保留；物理活动按需附着 | fusion、批处理、驻留、移除同步可能需要实际成本；不展开driver内部函数、SASS或硬件实现。活动结束不能冒充value ready。 |
| `call_edges.py`、`call_operands.py`、`python_call_targets.py` 原事件 | 只保必要动态对应；指令/完整外部frame流作可选证据 | 静态CFG/Use/State已能提供确定结构，不能因曾看到某CodeType就无界递归细采其所有实现。 |
| OS syscall原日志 | 资源/IO/同步接口的按需依据 | 不将每条内部futex/stat/ioctl都强制变成主图动作；不建立完整内核内部模型。 |
| collector witness、process-image、CodeWitness及source guards | 来源/验证层，源定义与运行版本共享引用 | 目标代码版本仍必要；采集器注册、验证循环和证明材料不成为目标程序依赖节点。 |
| `v2/contracts.py`、measurement与cost | 合同/属性/成本附着 | Q/M用于约束和比较方案，不为每条证明再创建一条执行路径。 |
| 旧`ir/graph.py`与新`program/model.py`等表示 | 保留兼容，明确权威与桥接；停止新增平行图 | 旧planner当前仍读legacy ExecutionGraph；丰富的新建模产物尚未完整接入它，不能用类型或证据数量宣称化简能力已具备。 |

规范图、运行对应、资源/成本附着、证据归档分工明确。程序图不应成为所有原始
事件、语言解释器步骤、采集器行为和验证材料的混合全集。

## 3. 已测到的过度展开与重复

- 真实239-operation函数样本中，113项是packet/pending/dispatch转发，54项是Frame
  管理，19项是纯binding定义。它们不是“186次可删除计算”；应在主视图折叠，
  保留它们表达的控制、SSA和最后释放约束。
- 同一样本source上下文占21,668,986B，约91.83%；函数core graph为877,089B。
  整份source context随body反复保存/验证是明确的收敛对象，应共享上下文并引用。
- 本次native canonical产物约4.738GB，execution和projection receipts各约1.416GB，
  合计约59.8%。两份重复执行表示及反复嵌入的ID/source描述应收敛为原记录引用。
- 新尝试的967行native adapter重复保存实例分类/父关系/schema，并给annotation
  再造观察行。**未合并，已停止扩展**；后续只允许复用原实例的必要端口侧车。
- 最新真实采集正常退出，但frame记录到1.2GB上限并丢事件，operand也提前停止。
  更多底层日志没有补齐必要关系；采集应以静态结构及所需dispatch/端口/状态为主，
  局部未支持不能无理由停止全部区域。实际global hook/完整性失败仍须扩大失效范围。

完整清单扫描370个源文件、1,418个顶层class声明；包含budget、reader、validator和
helper，**不是1,418种图节点，也不是逐类已迁移的覆盖率**。清单用于防止审计漏层。

依据：[源码/core审计](../artifacts/analysis/source_core_boundary_audit_20261026/REPORT.md)、
[native/GPU审计](../artifacts/analysis/model_scope_audit_20261026/native_gpu.md)、
[采集审计](../artifacts/analysis/collection_scope_audit_20261026/REPORT.md)、
[类型清单](../artifacts/analysis/model_scope_audit_20261026/inventory.json)。

## 4. 建图与存图的组合方式

按body/Region或执行片段独立构建；每片保存本地节点/边、输入输出/状态/资源摘要，
跨片使用准确命名空间、版本与端口引用。静态定义、schema、source与资源描述共享。
索引可重建，根manifest可合成；没有全局可写大表成为所有builder的事实中心。
共享状态产生真实跨片依赖，按相关状态域连接，不强加所有actor的全序。

一份函数定义执行100次，保1份定义与100次必要发生/对应；不保存100份源码、类型
定义和完整证明。压缩表示不能抹掉各轮输入、状态及副作用差异。

## 5. 已执行与下一步

已执行：停止完整FD表攻坚；停止新native平行图扩展；停止新增全量采集；保留旧
原件及兼容reader。161项源码普通发布已保留；后续重复全量reader按本审计中止，
实际exit1/KeyboardInterrupt保留，不借已发布状态追认独立回读或整体模型完整。

下一步按本审计实施三项核心收敛：

1. 核心图提供可展开的操作/区域及最小充分接口，语言管理步骤和验证材料有明确
   去处；把调用、返回、状态和Tensor端口真正接通。
2. source/schema/资源定义按引用共享，去掉execution/projection及每body上下文重复；
   独立片段可以并行构建、合并和查询。
3. 采集只补静态结构不能确定且分析需要的动态事实，保版本化旧profile及明确缺口，
   不以删掉必要依赖或修改分母宣称完整。

本审计不新增optimization backend、不删除历史用户数据，也不宣称上述迁移已实现。

## 6. 后续自身验收节点

| 顺序 | 核心交付 | 验收依据 |
| --- | --- | --- |
| A 边界审计 | 本文及三份分层producer/consumer审计 | 每个模型家族有明确保留/折叠/证据/排除决定；新平行图和底层追逐已停止。当前已交付；逐条旧记录迁移未完成。 |
| B 最小程序抽象 | 可展开Region、实际源操作与输入输出/状态/异常接口 | 真实函数的管理性编码从默认主视图折叠；原有序Use、控制/清理、最后释放约束可追溯且没有被删。新增观察节点不以强normal/identity资格为创建前置。 |
| C 组合与共享 | source/schema/resource共享引用、独立子图片段与跨片端口 | 同上下文的两个函数只保存一份上下文；原ID/版本/端点含义保持。单片可独立构建/读取，索引可重建；不重新序列化完整execution作为另一份权威。 |
| D 必要动态补全 | 版本化的dispatch/区域端口/必要状态采集、局部缺口隔离 | 静态结构可恢复的确定步骤不逐次记录；失效按依赖范围传播，全局hook损坏仍使对应epoch失效。明确字节/事件及缺口，避免再以退出码0代表完整覆盖。 |
| E 真实程序全链 | 自动生成LeWM最小充分图，查询加载→处理→搬运→规划/交互→输出 | 源函数/算子/数据状态/程序资源接口连接完整；原始事件、语言验证与物理实现细化可按需追查，不能作为填充节点的覆盖成绩。不进入性能优化/加速比阶段。 |

B/C/D按当前实际缺口实现并集成，E最后验收。优先复用已有节点、端口和reader；
不再为每个证明协议、底层事件或概念家族另造一套图。

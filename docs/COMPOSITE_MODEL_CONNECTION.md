# 从局部原图到完整程序：身份、状态和关联的集成边界

2026-10-23。**Observed / Verified：原图命名空间审计；整体执行模型组装仍 OPEN。**
本文件约束第一阶段的集成，不增加优化阶段或新backend，不另造producer/state图。

## 1. 当前代码实际提供什么

- `ProgramGraph`是一个规范图；`ExecutionModel.snapshot`绑定一份ProgramSnapshot。
  execution validator以该图的准确schema/hash/bytes校验来源。`snapshot_for`不能将
  composition manifest冒充`scar.program-graph`，也不能用空图占位。
- `CompositionIndex`按原artifact/representation/body维护限定引用，按需加载原图；
  `SourceDefinitionReference`定位原源码定义，外部source-only不假造typed body。
- `GraphIndex`的实体键为namespace+kind+local_id，已有840个原图namespace。
  它是可重建索引，不是新的可独立修改的模型事实来源。
- `SourceBodyAccess`核原body receipt/namespace；裸definition有歧义时拒绝。原参数/
  返回报告中的local IDs必须结合其canonical_namespaces及原调用上下文解析。
- Python/source、Torch物理图、OS work与R2资源关联目前仍有多个准确限定片段。
  保留原来源与部分关系不等于已有一个全部依赖闭合的ProgramModel。

## 2. 真实数据反例：不能按ID文本拼接

独立只读SQLite审计重新核库SHA、437,228实体/840namespaces，按kind+local_id分组：
106组StateLocation ID跨namespace重复，合计830次出现，最大一组出现于66个body。
其它已索引实体类型在本份归档未发现相同kind+local_id的跨namespace重复；这不是
对所有程序/未来lowering版本的全局唯一性保证。

取最大组的两个原checkpoint，独立核decoded SHA并回读准确原字段：它们均声明
`coarse Python/external world`，local ID相同，原root/body不同，stability为UNKNOWN。
数据库正确地保留两个限定原声明。不能因此说索引冲突，也不能从相同文本推出
不同activation或Run的before/after state相等。

反方向同样重要：不同源文件的不同coarse-world local IDs不证明运行时世界互不
影响。将它们简单作为互不相交的状态域，也会漏掉跨调用的读写依赖。
完整证据及成本见[原档审计](../artifacts/experiments/first_stage_composition_identity_audit_20261023/README.md)。

## 3. 集成方向：限定原图与显式关系

整体程序采用对原图的组合查询视图，而不是为了得到一份JSON而重命名/复制全部
记录。现有局部ProgramGraph/ExecutionModel保持其合同与版本。全局发布必须清楚
声明它包含哪些原快照、对应哪个AnalysisScope/Run、关联哪些端点，以及哪些覆盖
义务仍未闭合。发布了可读取的组合索引也不能将完整性自动置为PASS。

```text
固定AnalysisScope / 当前Run
  ├─ 原规范body/源码定义/provider接口（各有原snapshot与namespace）
  ├─ 当前invocation/operation/value与环境/状态事实
  ├─ 实际native/kernel/copy/OS work与资源生命周期
  └─ 跨片typed关联 + 原证据 + 逐项coverage
```

跨片关联至少分别核验：

| 关联 | 必需限定 | 不能替代它的东西 |
| --- | --- | --- |
| actual→formal / return / exception | 两端原body/端口、当前invocation、实际dispatch与完成 | 静态callee候选、相邻时间或保留祖先 |
| caller world→callee entry / post-world | 当前控制路径及before/after端口、状态域实例对应 | 相同world local ID或全部叫world |
| 对象/位置/alias | 对象生命期、owner/selector、实际引用或schema/协议证明 | 相同变量名、形状、地址或Tensor `_version` |
| 逻辑值/版本→副本 | 来源、读写失效、实际变换与表示 | 单独StorageID、allocation epoch或少量样本相等 |
| operation→work/resource | 原occurrence/provider选择、同Run、实际执行器/handle | 只有函数名、系统型号或一次host返回 |
| ready/order/lifetime | 明确enqueue/完成/等待、代次与资源协议 | 时间相邻、普通syscall返回、kernel correlation本身 |

这里的限定键复用原namespace、CodeIdentity、InvocationKey和provider receipts。
不会建立一套可与原记录分别修改的producer、StateLocation或资源身份。读者必须能
沿每条跨片边回到准确原端点；存储路径/文件序号不单独决定其身份。

## 4. 接下来怎样验收

1. 完成当前369749的source→marker→operand/environment实档接线，保持同一Run；
   只复用通过guard的旧静态证明，不移植旧Invocation/状态。该门已准备，尚未运行。
2. 接入通用source-language新body时，显式选择其新receipt与capability；旧CP和
   source bindings不能被静默原地升级。未支持的模块/生成器/类等界面保持具体缺口。
3. 在现有组合入口上补齐限定的跨片查询和逐端点检查；按原分母核source/state/
   runtime/resource，而非根据记录数量宣布一个统一图。单图ExecutionModel校验
   仅对真实拥有完整ProgramSnapshot的局部范围执行，不伪造全局snapshot。
4. 逐项补调用阶段、对象/环境、state/world、逻辑来源及资源/ready关系；原档不能
   提供的字段统一列为一次联合补采需求。不能通过重命名UNKNOWN或把may-alias当
   disjoint消除必需义务。
5. 按第一阶段合同复核加载→推理/环境→输出/结束全部必需项。局部覆盖成功、组合
   发布成功和完整性通过分别报告；S4必需OPEN=0以后才向用户宣告第一阶段完成。

本轮只确认真实身份边界及当前集成缺口；没有创建新的全局ProgramModel实现、
没有把声明world等同于实际状态、没有推进图化简或修改LeWM。

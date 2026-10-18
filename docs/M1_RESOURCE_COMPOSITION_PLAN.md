# R3：执行接口组合计划

实施起点：`348d18277b963bc183fb420bf173f05594d667d8`。
上轮 V 的 649 项组件与冻结实现 `550496f` 的 4,826 项全仓验收已归档。
本门仍属于 M0–M2 建模，不新增 detector、backend、lowerer 或 LeWM 专用规则。
本文件是计划，不是已通过的报告。

## 模型与审查结论

规范实体仍是 Operation、Value、StateLocation、Region、Resource。静态端口和
producer/Use/state 留在 ProgramGraph；执行层通过准确的动态发生与关联引用它们。
不能因表都存在，就认为跨表或跨调用的依赖已经连接。

审查按三个方向进行：原端口与动态连接、逻辑值与物理端点、语言完成与资源生命周期。
报告保留在 `artifacts/experiments/b1_call_operands/model_resource_composition/design/`。
以下是需要落实和核验的具体问题：

1. 静态 `callee` 能确定形参接口，却不能在多次调用同一个函数时选择正确的动态
   activation。现有 `formal_route` 只沿本 activation 的实际 CFG transfer 回查。
   必须有显式调用发生关联，不能从父 span、名称、行号或相同值猜测。
2. `WorkSubmission.materializations` 的 COMPLETE 声明必须与实际声明的 work
   读写物化相容。PARTIAL/UNKNOWN 下缺项保留缺口，不伪造成不存在。
3. Q requirement 是完整观察义务的分母。缺 root/read/support 只能产生缺口，
   不能从最后一次 close 或已连接的成功路径重新选择分母。
4. EndpointContent、Q facet、resource/state、ProtocolSelector 已能保守表达端点。
   任意 FactRef 还不能解释实际 read/flush/persist；新加一个字段不会成为证明。
5. 返回/抛异常、native terminal、quiescence、borrow release、handle end、retirement
   是不同事件，组合不能将任何一项当作另一项。

## 顺序与自行验收节点

| 节点 | 交付 | 必须保留的反例与边界 |
| --- | --- | --- |
| R3.0 连接审查 | 三项独立源审与本计划；列出既有能力、实际缺口和后续自动恢复义务。 | 不复制 Use/producer/state，不把新 schema 或 native parser 当成默认解。 |
| R3.1 动态调用与集合连接 | 准确 caller→callee activation/initial entry/actual completion 关联；输入输出查询从原端口派生；校验 work 完整物化集合。 | 两次同 callee、递归不同 activation、错 owner/process/thread、错 entry/exit、实际 INVOKE raise、缺采集、缺关联；不授权 hoist/reuse。 |
| R3.2 全过程组合公开面 | 从完整显式 Q requirement/root 接回原 read/write、逻辑版本/Mat、work/order/support/lifetime 和跨调用原端口。 | 删 join 不缩义务；部分写/覆盖、pending work、host raise 后仍在执行、cleanup/release 分离；端点协议尚未解释保留准确 UNSUPPORTED。 |
| R3.3 联合验收与范围关闭 | 通用 load→materialize→compute→consume→write→flush/close 模型的正反组合与有界 OS 观测，原端口可回查；必要的 source/runtime/native 缺口明确列出。 | 手工声明组合不冒充自动建图；真实 OS witness 也不自证 IR 与 runtime 对应；完整 M0–M2 另按原分母验收。 |

各完整实施门必须经过独立复审、组件验收、干净实现提交和一次冻结全仓，保留原失败、
case/fixture/source 守恒与工件指纹，归档并推送。全仓期间不改源码/文档或并行启动测试。
不为每次小编辑跑全仓；完整门的共同风险关闭后再冻结。

## R3.1 调用关联合同

新增关系只声明**这次**调用所关联的**这次**被调执行，不存第二套参数/结果/状态。
关联的 caller 是原 OperationOccurrence，callee 是原 RegionActivation；entry 指原
InitialEntry 的入口 BlockVisit，completion 指原 RETURN/RAISE occurrence。缺 entry 或
completion 用显式 Unresolved，不能把未知写成尚未返回、无副作用或无输出。

- 原静态 callee 必须对应动态 activation.region；同一同步调用与 activation 不得
  重复配给其他调用；动态关联无环，静态递归和不同 activation 的嵌套允许。
- run/process 和已知 host thread 必须一致。跨线程工作用已有 WorkSubmission 表达，
  不用错误的同步调用关系代替。入口必须是准确 callee 的真实初次入口，不能借循环、
  resume 或 capture 的 block visit 填补。
- 普通 CALL 只连接其规范正常返回接口。INVOKE 必须核 actual RETURN/RAISE 与调用方
  实际 taken successor/completion kind；缺实际 transfer 保留缺口，不能默认 NORMAL。
- 输入从 `call_arguments`/`invoke_arguments` 的原 Use 顺序与 callee entry formal
  派生。输出从实际 return/raise 的原 Use 与 caller 原 result，或 INVOKE 的准确
  CompletionResult/landing formal 派生。状态端口同样保留，不跨 activation 直接重绑 Use。
- 关联是声明，不是 runtime adapter 证明。没有关联的既有 execution model 仍合法，
  查询应报告无法选择动态 callee；不靠相同 DataIdentity、ObjectID 或物理地址推断。
- 新能力保持旧执行 wire 的字段/tag/字节，只有使用新表时提升 capability version；
  历史空表迁移不证明没有发生调用。

`WorkSubmission.materializations` 是该 ticket 声明关联的物化集合，包含明确声明的
内容读取、内容产出和以 MaterializationRef 为 target 的借用。COMPLETE 必须包含
这些准确 scoped Mat；不同 URI 的同一 SHA/schema/size/MatID 是同一身份。其它 ticket
的列表不能补项。只有 allocation target、以 Mat 作为 allocation 依据的引用，并不
声明这个逻辑版本被该工作借用，不能由此硬推 Mat membership。集合校验不证明真实
捕获完整、物理 read/write、ready、quiescence 或释放权限。

## 完成后仍不代表什么

R3.1 不关闭 R3 全过程组合；R3 也不关闭剩余 selector/literal、C2/D3 等完整构造义务。
本门不产生新的 LeWM 性能数据。真实自动恢复、native 协议闭合、合法性证明与变换权限
分别记录；组件测试耗时不是 workload 加速比。

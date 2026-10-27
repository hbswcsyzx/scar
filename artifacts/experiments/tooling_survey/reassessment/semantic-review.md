# 工具复用与前端范围：独立架构复审

2026-10-16；只读审查，HEAD `845ebb4`。设计建议，不是适配器实施或全程序验收。
本轮没有执行目标、测试、采集或新实验；读取现有报告、源代码及官方资料。

## 裁决

**存在继续自写 Python 编译器的实际风险，应停止把全语法 lowering 当作完整模型的前置。**
`program_lowering.py:469/552` 与 `structured_lowering.py:215/384` 已自行展开表达式求值、
控制转移和绑定状态；这确实是编译器工作。规范 completion/state/identity 接口仍有必要，
但接口能够组合未知实现，不要求 SCAR 先实现每种 Python 语法和所有库内部。

最新 `MODELING_INTEGRATION.md` §3.1 字段归属和 §3.2 边界方向正确。M0–M2 应收口于
类型、连接、组合规则及其校验；额外源码 lowering 属于之后的自动建图阶段。
不推倒已验证的 wire，也不因已投入实现就继续无条件扩大自建前端。

## 保留、适配、停止扩写

| 对象 | 明确决定 | 不能据此获得的事实 |
| --- | --- | --- |
| SCAR core / replay | 保留规范身份、有序 Use、状态/完成/资源边界、来源与严格重放；每种表示内部事实唯一。 | 类型图有效不等于原程序恢复正确或可变换。 |
| FX / Export / Dynamo / AOT | 适配已有计算图、签名、约束、mutation outputs、分解与前后向接口；停止另写 Tensor tracer、算子分解和自动微分。 | guard 不是纯性证明；规范化图不是原对象身份/存储历史；任意 Python 外部副作用仍未覆盖。 |
| ETO + Kineto | 优先适配动态算子、Tensor/storage 观察与物理活动；按字段替代重复 observer。 | Tensor/storage ID 不是内容版本、Python 实参 occurrence 或 GPU ready。 |
| ast / symtable / dis / LibCST | 保留标准解析和编译见证；按需用 LibCST 替代重复源码定位/格式保留与修改设施。 | ScopeProvider 的变量作用域不是异常 CFG 或 cleanup 控制作用域。 |
| CodeQL | 在新增手写控制 lowering 前，先安排有界提取/查询对照，决定可导入的 CFG、调用与数据流。 | 工具的 dataflow/summary 不自动成为所有异常、别名、外部写和等价性的完备证明。 |
| MLIR / xDSL | 可以替代通用 SSA/Region/验证/重写基础设施；本门不迁移现有 wire。停止再造另一套通用 optimizer/pass 框架。 | 采用框架不会自动恢复 Python 协议或跨层身份；“参考 MLIR”也不等于已经复用其实现。 |

FX 官方说明默认符号追踪不能处理输入相关的 Python 控制流；这是选取适配范围的依据，
不是全部 Python 控制都必须自写的依据。[FX](https://docs.pytorch.org/docs/2.14/fx.html)
ETO 可由 profiler 管理同一采集窗口；具体对应仍须独立验证原始 ID 和作用域。
[Profiler](https://docs.pytorch.org/docs/2.14/profiler.html)

CodeQL 已明确提供 `try/finally` 的正常、break、异常多条 CFG 路径，以及局部/全局数据流；
不能把它概括成只能做安全标签的工具。官方当前支持表列 Python 3.14，但本轮未运行本机
extractor，兼容性、成本和所需事实可导出性尚未验收。
[CFG](https://codeql.github.com/docs/codeql-language-guides/analyzing-control-flow-in-python/)、
[dataflow](https://codeql.github.com/docs/codeql-language-guides/analyzing-data-flow-in-python/)、
[版本支持](https://codeql.github.com/docs/codeql-overview/supported-languages-and-frameworks/)

LibCST 的位置/作用域/名称接口与 MLIR/xDSL 的通用 IR 基础设施分别解决不同层次问题。
[LibCST](https://libcst.readthedocs.io/en/latest/metadata.html)、
[MLIR](https://mlir.llvm.org/docs/LangRef/)、[xDSL](https://github.com/xdslproject/xdsl)
本机 Torch 是 2.13.0+cu132，在线 stable 是 2.14；本机结论沿用既有固定源码和 CPU 探针，
不将网页新版本能力倒灌为本机实测。xDSL 当前 main 的兼容说明也不是本机兼容验收。

## “每一行完全理解”应替换成什么

源归属全覆盖、内部结构覆盖、依赖精度、运行对应、变换权限分别计量。
完整模型允许未展开库/本地子区域，但边界必须有规范输入/结果和环境、当前状态依赖与
可能后态、可能 alias/escape/retention、异常/控制/非终止、资源需求与完成接口。
未知结果不能伪造引用/别名精度；不能把未展开子树中的内部调用计为已经恢复。

最危险的遗漏是把 `effects_complete=False` 当作足够保守：如果任意回调可能改变其他
已声明状态域，未列 StateAccess 的域不能被解释为 NONE/内容保持。应保守推进可能影响
的全部域，或使用有依据且适用的有限 footprint；coarse world 与细分域重叠须显式处理。
部分失败仍携带已发生的后态，非终止没有伪造完成边。保守模型可以阻止优化，但不能
把不知道的依赖删除后声称完成建图。模型不能表达未知范围时，该边界必须明确不可用。

§3.2 的“normal/raise/suspend 完成”应理解为不同 typed 通道的列举，不应落成一个混合枚举：
语言完成、暂停/恢复、host 操作返回与 resource ready 的既有区别继续保持。

替换 observer 的门槛是：既有查询依赖的每个事实均有可追溯替代或明确缺口；保留有序
重复实参、作用域/生命周期、drop/失败报告与历史重放；运行开销和扰动另测。先证明
这张字段表，再关闭被替代的采集路径。ETO 不提供的 Python occurrence 仍需受限补充，
不能因为 trace 更小就删除唯一来源，也不默认同时开启全部 observer。

## 最近三个验收节点

1. **复用合同定稿（第一阶段）**：在现有集成文档完成字段归属及 observer 替代条件；
   使用已存探针逐项核对重复 Use、raw/decomposed mutation、alias、guard、graph break、
   ETO/CPU 关联。没有证据的字段列缺口；完成 CodeQL 前端对照的有限输入/输出合同。
2. **边界组合验收（第一阶段）**：M1/M2 的类型和 validator 能拒绝旧状态旁路、未知调用
   被当 pure、NORMAL/RAISE/暂停/ready 错接、cleanup 丢原 payload、coarse/细域错误不交。
   明确未实现协议和适配器分母；达到第一阶段验收后停下解释，不启动化简。
3. **获得后续建图授权后的最小公开导入**：通用两文件“读取→计算→保存”自动接入现成
   Tensor 图与 ETO/profiler；输出根可回溯到准确 Use/入口状态/异常边界，未知处准确停边。
   同时执行有界 CodeQL/现前端对照，再决定新增 lowering；不用手写 workload 图、纯函数
   或常量名单。之后才把未修改 LeWM 加载→推理→保存作为压力验收，不提前声称加速。

以上三个是建议的验收顺序，不表示本轮已执行其中的新适配、测试或建图工作。

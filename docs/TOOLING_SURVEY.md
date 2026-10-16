# 程序建模工具调研与复用决定

日期：2026-10-16。状态：**官方资料、源码审查及独立小实验；不是适配器已接入的声明。**
与 [完整模型](WHOLE_PROGRAM_MODEL.md)、[集成设计](MODELING_INTEGRATION.md)配合阅读。
本轮不增加 detector/backend，不修改 LeWM，不升级运行环境。

## 1. 当前事实及本轮问题

SCAR 的完整程序模型仍未完成。复审时开发分支
`codex/structured-program-model` 为 `845ebb4`，冻结实现 `54eb7ec` 的 3,027 项
全仓回归通过；这验证已实现代码，不验证尚未实现的模型。下文小实验仍绑定
各自报告中的历史 revision（包括 `d5311a6`），不是在最新实现上重跑的结果。
固定 256 个 LeWM 源定义的旧压力批次只有 51 个 graph-with-gaps、205 个 unsupported，
不能作为完整程序建图的验收。没有可信自动变换或 clean A/B 加速比。

本轮重新审查：哪些事实已有成熟工具可提供，哪些关系必须由 SCAR 补充，以及
现有自建 lowerer 是否承担了不必要的工作。不能先假定其他工具的粒度都更粗。
kernel 时间、算子图、源码控制、状态版本和生命周期是不同维度；一张图节点多
不意味着覆盖其他维度，也不意味着更适合化简。

本机为 Python 3.14.7 / Torch 2.13.0+cu132，`torch.version.cuda=13.2` 是构建信息，
不是本轮 GPU 实验结果。Torch source revision
`cf30153c4c131c8164ee7798e5022d810682e2cb`。在线 PyTorch stable 当前显示 2.14，
Python 3.14 网页显示 3.14.8；本机行为以探针及对应源码为准。网页能力不静默
倒灌为本机能力。所有本轮 Torch 实验仅 CPU；没有新 LeWM 或 GPU profiling。

## 2. 能力与边界

| 工具/接口 | 可以直接复用的事实或结构 | 不能由此获得的结论 | 决定 |
| --- | --- | --- | --- |
| Python `ast` / `symtable` / `dis` | 版本匹配的语法、source spans、编译作用域、code/bytecode 位置及异常表。 | AST 不是执行 CFG；作用域不说明任意对象 lookup 的状态；字节码表不直接给跨调用 dataflow。 | 保留标准库作为源前端与编译见证，不重写 parser/symbol-table。 |
| LibCST | 保留格式的源码树、Position/Scope/QualifiedName metadata、codemod 基础设施。 | Scope assignment/access 不等于带异常、别名和状态的完整程序依赖图。 | 可选源定位/将来修改指导前端；本轮隔离验证，不替换全部 core。 |
| CodeQL Python | 既有 AST、CFG/basic block、跨过程 dataflow 查询；一个 AST 可对应多个 control-flow node。 | 安全分析中的 flow/summary 不自动成为数值等价、无副作用或 GPU ready 的证明。 | 优先评估静态结构/依赖导入与独立对照；未本机运行，不宣称兼容验收。 |
| `torch.fx` | 可遍历、修改、生成 Python 的 operator/module/function 图；有序 args/kwargs 与 def-use。 | 默认符号追踪不捕获任意 Python 控制/副作用；被执行或特化掉的 Python 不等于可删除。 | Torch 子区域的现成图接口，不手写第二个 Tensor tracer。 |
| `torch.export` | FX/ATen 图、graph signature、pytree call spec、lifted parameters/buffers、shape constraints；特定规范化阶段显式 mutation outputs。 | 成功 export 不说明原 Python region 无效果；约束外输入、mode、alias 和未捕获 Python 行为仍需合同。 | 优先复用规范化 Tensor 区域及其边界；记录具体 pipeline 阶段。 |
| Dynamo / AOTAutograd / functionalization | 分段捕获、guards、graph-break 原因、前后向及 mutation/alias 重写接口。 | guard 不等于 logical value 相等；functionalization 的新图不是原执行的 storage/identity 记录。 | 编译覆盖/限制和已有图的来源，不启用编译来冒充建模完成。 |
| torchview | 实际 forward 中 module、Torch function、Tensor 连接、shape；支持嵌套展开、显示深度和 meta device。 | 不是整程序 source/状态图；运行 forward 有执行和模式/引用等影响；图中没有出现的副作用不代表不存在。 | 可选人工审查/展示前端，不能只因有 SVG 就作为规范 IR。 |
| TorchLens | 上游提供 eager Torch 操作依赖、模块嵌套、动态路径、metadata、activation/gradient 记录与展示。 | rich graph 不保证整程序依赖；有捕获模式、状态/引用/保存成本和未覆盖来源，部分恢复可重跑 forward。 | 增列为动态 provider 候选；只读固定源审查，尚无本机兼容性或采集成本验收。 |
| torchviz / autograd graph | 从结果的 `grad_fn` 查看反向依赖及相关 saved tensors/parameters。 | 无梯度推理可能没有这张图；没有承诺完整 forward、Python 控制、文件输出。 | 梯度关系审查辅助；不作为整程序前端。 |
| `torch.profiler` / Kineto | 真实 operator、CPU/runtime/GPU kernel、memcpy、等待及内存活动；原始 correlation 字段。 | 一次 trace 不覆盖未走分支；时间重叠不证明因果；物理 memcpy 不自动说明哪个逻辑值。 | **当前已经使用**，保留物理采集与原始证据，不重写 CUPTI。 |
| Profiler experimental event tree / `_memory_profiler` | 已有 Tensor metadata、allocation ID、内存事件及按 schema 推导的 DataFlowGraph/版本。 | private/experimental；不等于有序全值 def-use、逻辑内容版本或外部写检测；memory timeline 导出已标 deprecated。 | 本轮单次 CPU 探针通过；列为版本固定的可选来源，先评估已有采集字段，禁止默认再写一套 allocation/版本分析。 |
| `ExecutionTraceObserver`（ETO） | 动态 RecordFunction 图、operator inputs/outputs、Tensor/storage 标识和 shape/stride/type/device；`rf_id`。 | 标识不是内容版本；普通 Python/NumPy/文件行为不完整；host 记录不是 GPU 完成。 | **优先新增导入适配器**；当前尚未接入 SCAR。 |
| `sys.monitoring` | 低层 Python call/start/return/throw/yield/resume、分支/指令事件。 | CALL 只给规定的少量实参信息，不提供任意完整操作数栈/所有数据依赖。 | **当前已用于 call operands**；按需使用，避免全程序逐指令常开。 |
| Nsight Systems / Perfetto | 前者可作实际 GPU 系统时间线参考，后者可查看/查询兼容 trace。 | trace viewer 不负责 logical identity、程序合法替代或唯一最优计划。 | 可选 ground truth/查询展示，当前 PATH 未找到 `nsys`，不安装重型依赖。 |
| MLIR / xDSL | 成熟的 Operation/Value/Block/Region、类型/校验/重写框架；effects 接口是设计参考。 | 框架不自动恢复 Python/import/cleanup、NumPy 外部写、库协议或跨层数据身份。 | 沿用成熟 IR 原则；完整迁移需先对照试验，当前不推倒已实现 wire。 |
| NetworkX | 通用 SCC、可达性、支配等图算法。 | 算法不知道哪种 SCAR 边有相应语义，不能把混合图当 DAG。 | 优先作为分析原型/算法对照，输入使用明确投影；本机已安装 3.6.1。 |

### 主要资料

- [Python AST](https://docs.python.org/3.14/library/ast.html)、
  [symtable](https://docs.python.org/3.14/library/symtable.html)、
  [dis](https://docs.python.org/3.14/library/dis.html)。
- [LibCST metadata](https://libcst.readthedocs.io/en/latest/metadata.html)、
  [项目与语法支持](https://github.com/Instagram/LibCST)、
  [CodeQL CFG](https://codeql.github.com/docs/codeql-language-guides/analyzing-control-flow-in-python/)、
  [CodeQL dataflow](https://codeql.github.com/docs/codeql-language-guides/analyzing-data-flow-in-python/)。
- [FX](https://docs.pytorch.org/docs/stable/fx.html)、
  [Export](https://docs.pytorch.org/docs/stable/export.html)、
  [Export IR](https://docs.pytorch.org/docs/main/user_guide/torch_compiler/export/ir_spec.html)、
  [Dynamo overview](https://docs.pytorch.org/docs/stable/torch.compiler_dynamo_overview.html)。
- [torchview 原仓库](https://github.com/mert-kurttutan/torchview)、
  [torchviz 原仓库](https://github.com/szagoruyko/pytorchviz)、
  [TorchLens 固定源](https://github.com/johnmarktaylor91/torchlens/tree/550b96a61972cf7db23044125e5ee63489d217cd)、
  [Profiler/ETO](https://docs.pytorch.org/docs/stable/profiler.html)、
  [sys.monitoring](https://docs.python.org/3.14/library/sys.monitoring.html)。
- [MLIR LangRef](https://mlir.llvm.org/docs/LangRef/)、
  [MLIR effects/speculation](https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/)、
  [xDSL](https://github.com/xdslproject/xdsl)、
  [NetworkX dominance](https://networkx.org/documentation/stable/reference/algorithms/dominance.html)。
- [Nsight Systems](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)、
  [Perfetto Trace Processor](https://perfetto.dev/docs/analysis/trace-processor)。

官网/原仓库支持能力描述；下面的 artifact 支持本机观察。没有运行的工具只标
资料审查；不把列表写成已安装集成清单。`torch.profiler` 属于 PyTorch，不是 Python 标准库。

## 3. 本机实验：不能用通用印象替代实测

证据根目录：[`tooling_survey`](../artifacts/experiments/tooling_survey/)。各报告含
脚本、版本、命令、实际结果及范围；少量互不等价的能力案例不汇总成模型覆盖率。

### 3.1 标准前端与 LibCST

`python_frontend/probe.py` 对含 import、文件调用、闭包、finally、generator、async、
generic alias、t-string 的样本只 parse/compile/symtable/dis，**不执行样本模块**。
6 项能力检查通过：不存在的模块没有被 import、文件没有创建、cell/freevars 与
异常表可取、新语法可表示。它没有构造 SCAR 完整图。

LibCST 原本未安装。`libcst_probe.py` 临时解包 PyPI 固定 **1.9.0** wheel
（2,255,879 bytes，完整 URL/hash 入报告），退出删除专用目录，没有改 conda。
5 个样本均 parse、格式精确 roundtrip、PositionProvider 和 ScopeProvider 成功，
包含 generic alias、t-string 和 finally。不能据此宣称其 ScopeProvider 理解所有
动态 Python lookup；这只是可选前端在本机版本上的能力见证。

### 3.2 FX / torchview / torchviz

详见 `visual_fx/` 的独立报告和 FX CPU 探针。torchview/torchviz 未安装；本轮对
它们进行官方资料与源码审查，不伪称在 3.14/2.13 组合实测成功。
torchview 能画 function 和 Tensor 连接，也能展开嵌套；默认显示层级不是能力上限。
FX 可提供机器可读 operator/module 连接；其捕获范围及 Python 执行影响必须导入。

补充的 [TorchLens 固定源审查](../artifacts/experiments/tooling_survey/torchlens_review/REPORT.md)
读取官方 `550b96a61972cf7db23044125e5ee63489d217cd`（包声明 2.36.1），没有安装或
执行它。其 eager 操作/动态路径/层级图已有较细粒度，不应再造同类 tracer。
限制页披露重跑恢复、eager/compiled 捕获差别和来源缺口，payload/引用仍有成本；
无值结构模式也不等于已证明实值依赖。该 checkout 的结构合同和限制页还有阶段
文字差异，须以隔离兼容实验核对，不能直接导入为 SCAR 事实。新增资料的 URL/hash、
错误路径404及更正均保留；第三方原文只临时读取并清理，留本次自己的小报告。

本机 FX 探针中 `x+x` 在 args 保留两次 use，而 users 只有一个 consumer；buffer
写和 Python counter 可发生于 trace 却不保留在重放图中；无 Proxy 的 rand 可被
固化成 get_attr，而带 Proxy 的 rand_like 保留为调用。静态循环可展开，动态 if
拒绝，stack metadata 还随 tracing 路线不同。不能把这些默认行为泛化为全程序图。

### 3.3 Export / Dynamo：图变换阶段决定接口

`export_dynamo/` CPU 实验实际观察到：本机默认 export 保留部分 in-place op，
仅从 signature 的 USER_OUTPUT 不能判“无 mutation”。在
`run_decompositions({})` 后，样例显式出现 BUFFER_MUTATION、USER_INPUT_MUTATION，
`no_grad` 参数写样例出现 PARAMETER_MUTATION。因此 adapter 必须记录
原始/规范化阶段和版本，不能套用网上另一阶段的 signature 规则。

非 strict export 中的样例 Python list append 在捕获时发生，但导出图运行不 append；
全局 scalar 被特化。普通数据依赖 if 捕获失败，显式 cond/while_loop 样例可导出。
Dynamo 样例得到 2 图、1 break。functionalize 的输出 alias 行为也不能直接
当作原程序的对象/存储身份。详见报告中的初始失败和最终分离实验，禁止删失败记录。

### 3.4 ETO + Kineto：已有比自写元数据记录器更直接的接口

`runtime/` 的 CPU 证据中，ETO schema 是 `1.1.1-chakra.0.0.4`。Tensor tuple 的
槽位为 TensorImpl 映射 ID、storage data 映射 ID、元素 offset、numel、itemsize、
device；shape、stride、type 另列。两次 add_ 的 tuple 相同；view 可换 Tensor ID
而共享 storage。这些是物理/对象观察，**不提供 LogicalValueID 或内容版本**。

样例的 34 个正 `rf_id` 与 Chrome 的 34 个 Record function id 按相同 ID/名称
对应；两个 root/thread 的 rf_id=0 排除。这个结果只验证本次 CPU 记录，不能
推广成所有线程/进程/window 的无条件一对一，也不验证 GPU work/copy 关联。

Profiler `record_shapes` 可能临时保留引用并影响执行；ETO 某些环境变量还能
启用额外 Tensor 数据/范围采集。因此 metadata-only 仍有开销，未来 adapter
须核对实际配置并按预算采集；本轮不启用全 Tensor 内容观察。具体源码依据及
环境变量名称见 runtime 独立报告，不能把字符串 `'0'` 当“未设置”。

### 3.5 本次补充：已有 profiler 内存数据流

[复审与单次 CPU 探针](../artifacts/experiments/tooling_survey/reassessment/provider-review.md)
发现本机 Torch 已有 `experimental_event_tree()`、`_TensorMetadata`、`TensorKey`、
`_Storage(allocation_id)` 和 `_memory_profiler.DataFlowGraph`。固定版本源码及
hash、命令、metadata-only 结果保存于 `reassessment/memory-provider/`。

本次只采集一次 CPU profile，启用 record_shapes/profile_memory/with_stack：
event tree 得到 34 条 op/allocation 记录、memory dataflow 得到 12 节点；两次
add_ 对同一 provider TensorKey 的版本依次为 0→1→2。CUDA 初始化前后均为 false，
未保存 Tensor 内容、未 import SCAR、未改 LeWM。这是工具能力探针，不是自动
SCAR 建图、采集开销比较或工作负载加速验收。

边界必须保留：

- DataFlowGraph 聚合 TensorKey，view 可没有新的 outputs；它不是保留全部
  Python/Tensor 输入槽位的值图。相同 metadata id 不等于同一个 Python 对象，
  也不能直接与 ETO 的同名 ID 合并。
- schema 的 may-write 版本不能证明 NumPy/native 外部写不存在，更不是
  LogicalVersion。尚未验收 allocator reuse、GPU ready 或外部 alias 写。
- 本机 `_memory_profile()` 要求三个采集 flags；底层 metadata/ID 的条件并不
  相同。源码显示部分字段可能已由现 SCAR 的 shapes+memory 采集得到；本轮未测
  with_stack=False 组合，不宣称现有磁盘 trace 已保存这些字段。
- 这些接口是 private/experimental。本机 `export_memory_timeline` 已标
  deprecated；其建议的 CUDA allocator snapshot 不自动替代 CPU 内存数据流或
  有序实参关系。先按固定版本评估，不能设为无回退的长期公开依赖。

决定：先验证从已有 profiler 结果取得所需字段能替代多少重复 observer；需要
rich memory dataflow 时再按预算开启额外选项。保留 ETO/FX 的不同职责，不把
所有 provider 默认同时打开。接口范围和替代条件见集成设计 3.1、7.1。

## 4. SCAR 当前已有复用与实际缺口

| 当前代码 | 已复用 | 本轮结论 |
| --- | --- | --- |
| `scar/trace/inject.py` | `torch.profiler.profile`、module/wrapper、可选 TorchDispatchMode。 | 保留 Kineto；评估 ETO 替代可覆盖的重复元数据，不把多个 observer 默认全开。 |
| `scar/trace/cuda.py` | Chrome runtime/activity correlation 与 memcpy。 | 保留；host wrapper 到逻辑 Tensor 的现有方向/字节数唯一匹配仍是 Inferred，不能升级成证明。 |
| `scar/trace/call_operands.py` | CPython 3.14 `sys.monitoring` CALL/INSTRUCTION。 | 保留受限窗口；现有条件路由不是完整 actual/formal/value 连接。 |
| `scar/ir/program` 与 source lowering | Python AST、code/source 对应、有限同步 core。 | 保留已验证子集及旧 wire；先接现成 Torch 子图/源作用域，停止扩写平行 Tensor tracer。 |

**尚未接入** FX/Export/ETO，也没有把它们与整个 Python 图统一。调研报告不是
集成完成；具体接口、自动发现与验收顺序见 [集成设计](MODELING_INTEGRATION.md)。

## 5. 决策

1. 优先复用标准 Python 源/编译见证、ETO+Profiler 动态证据、FX/Export Tensor
   子图。SCAR 负责接口规范化与跨图对应，不要求先自写所有 Tensor 运算规则。
   TorchLens 增列为动态记录/依赖 provider 的复用评估对象，按具体事实与成本
   与 ETO/已有 wrappers 比较；不默认同时全开，不把资料审查说成已集成。
2. 先以适配器试验与公共反例比较精度/成本，再决定是否删除已有 observer 或
   替换静态 lowerer。工具未安装不是“不采用”的充分理由，本机小轮子可以隔离验证。
3. torchview 作为展示/结构交叉检查；autograd 图补梯度关系；CodeQL/LibCST
   用于源结构与依赖前端评估。禁止从 SVG 或忽略副作用的计算图生成删除指令。
4. SCAR 保留的核心是**跨层身份、带范围的依赖/效果/完成、证据对应、合同与
   可化简子区域**。这些关系不是一次 forward 画图自动给出的。
5. 第一阶段仍以完整模型接口及组合规则验收为止点；先落实本次复用设计，
   不继续堆 detector/backend，也不因调研完成而宣称程序建模完成。

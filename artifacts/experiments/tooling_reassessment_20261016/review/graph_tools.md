# 图工具复用复审：torchview、TorchLens、torchviz

**范围。** 只读复核 `docs/TOOLING_SURVEY.md`、`docs/MODELING_INTEGRATION.md`、已有 CPU probe 和三项目官方 README/源码。未安装包、未运行 capture、未改产品或 LeWM。下面分开标识本机观察与固定官方源审查；图的用途不同，不能只按节点数量比较。

## 版本及证据边界

| 工具 | 核对版本/来源 | 本机执行情况 |
|---|---|---|
| torchview | PyPI `0.2.7` wheel，SHA256 `c7f3a9d16138c20b606900ecbf46d01489f2b8c77ed97e71293883bc606c2be0`；来源和代码摘要见 [`torchview_compat/SOURCE_MANIFEST.json`](../../tooling_survey/torchview_compat/SOURCE_MANIFEST.json)。wheel 与已审的 GitHub `main` commit `241d22b5cdeb2c227acee2c85611f0442f15c091` 虽然都报 0.2.7，未证明内容相同。 | 已有 Python 3.14.7 / PyTorch 2.13.0+cu132 CPU 小探针；五次 capture 成功。没有渲染、GPU、LeWM 或大模型测试。详见 [`torchview_compat/REPORT.md`](../../tooling_survey/torchview_compat/REPORT.md)。 |
| TorchLens | 固定官方 commit `550b96a61972cf7db23044125e5ee63489d217cd`，`pyproject.toml` 标称 2.36.1。审 README、`torchlens/data_classes/op.py`、`layer.py`、`trace.py`、`user_funcs.py`、限制及性能文档；每份源的 byte/hash 收据见 [`torchlens_review/source_receipt.json`](../../tooling_survey/torchlens_review/source_receipt.json)。 | 未安装、未 import、未执行 forward。只是固定版本的官方文档与源码审查，不能声称 3.14 / torch 2.13 兼容。 |
| torchviz | 固定官方 commit `5cf04c13e601366f6b9cf5939b5af5144d55b887`，`setup.py` 标称 0.0.2。审 README 与 `torchviz/dot.py`。 | 未安装或执行。 |

## 各图表达的关系

### torchview：执行中的张量/算子/模块前向图

- **不是纯模块摘要。** README 列出 tensors、modules、`torch.functions`、输入/输出 shape、模块嵌套及 rolling/unrolling；代码有 `TensorNode`、`FunctionNode`、`ModuleNode`。`ComputationGraph` 可读 `root_container`、`node_hierarchy`、`edge_list` 与 Graphviz object。可用于看前向张量谱系和层次结构。
- **不是位置完整的参数使用图。** 本机 wheel `x + x` 的 `FunctionNode` 有两个输入 shape 记录，但 parent 集合只有一个 TensorNode；父子邻接去重，visual `edge_list` 也按显示策略过滤。shape 次数不能替代“第几个参数用了哪个值”的 typed Use。
- **嵌套的折叠/展开主要是展示选项。** 本机两种 nested capture 记录相同 10 个对象和 4 条展示边，差异是新增 Graphviz cluster；不能把视觉展开当成多执行或多语义信息。
- **捕获会执行 forward。** 本机 `view` + `add_` 确实修改输入并共享 storage，但图字段没有给出 storage/alias 证明；counter 和 buffer 都递增，buffer 写未成为图节点。mode 也会被改变：原来混合的 parent/child training 状态结束时被统一设为 True。固定 wheel 源还显示调用 `.to(device)`、默认 eval、`no_grad`、包装 `Module.__call__` 和部分 Tensor factory；这些不等于副作用隔离。
- 该 wheel 的 node 记 `tensor_id`、shape、`compute_unit_id` 等 ID/metadata，不持有可供 SCAR 认定生命周期的原 Tensor/module 对象；节点也没有 code identity/source span。此前“图保留原对象”的宽泛说法应限缩到报告已修订的版本范围。

**复用边界：** 留作形状/模块层级/算子谱系的可视化交叉检查。不要把它直接当 canonical graph、source CFG、alias/state graph 或完整 ordered-Use 数据源。其 forward 必须视为有状态执行。

### TorchLens：细粒度 eager Torch 操作执行图，带实际分支上下文

- **不是仅有 module 节点。** 固定 `Op` 源码定义为一次 Tensor operation 的一次调用，记录 output、function、parents/children、module containment、参数使用、timing、RNG 和参数 metadata；recurrent 同一 Layer 的多次执行分别为 Op/pass。还有 Module/ModuleCall、参数、buffer、梯度等记录。README 公开每 op metadata、stack context、滚动/逐 pass 视图与 pandas/export 接口。
- **比“有一条 parent 边”更细。** `Op` 有 `parents`、`parent_arg_positions` 和 occurrence 级 `_edge_uses`；源码注释明确允许同一 parent 在不同 argument slot 出现多次。适配时应从有序 slot/edge-use 记录读关系，不要只读 unique parents/children。它有运行中 Tensor op 依赖和嵌套 module containment，足以成为 SCAR 动态 Torch 子图 provider 的优先候选。
- **控制是所执行路径及其上下文，不是完整静态 CFG。** 上游 README 明确以 eager Python wrapper 捕捉实际运行的 `if/else`、loop、early exit，并记录 per-op conditional metadata。它因此不是 torchview 那种只展示操作/层次的相同能力。但没有运行的分支没有执行节点；把 Tensor 转成 Python bool/item 等的依赖可能成为 ScalarEscape/warning 或验证缺口。`structure_only` 模式将分支/值相关结果标作 hypothesis，遇到值分支会拒绝，不能据此证明实值依赖或另一条路径。
- **有范围的 mutation/alias/state 观察，不是通用 Python 状态语义。** 源码存在 inplace/version、buffer-source/sink、per-child output version、RNG/autocast 和条件字段；这些适合复用为 PyTorch 侧证据。限制页明确 `.data`/raw storage/NumPy alias/custom kernel/特殊 subclass 可能不完整；未注册的 pybind C++ 调用不可见；global/closure tensor、opaque source、某些 schema mutation 会让 source provenance 失败。它不能涵盖任意文件 IO、普通 Python 对象写、库回调副作用，也不能用缺节点推出 pure。`save_mode=view` 下早期 activation 会随原位写变化；payload 的 copy/reference/view 语义要作为 artifact 条件保留。
- **Source 和执行身份要分开。** `code_context` 给文件/行/函数位置，是有价值的匹配线索；它不是当前源码 hash、代码对象 identity 或 AST witness。函数多次执行/一次 wrapper 可能产生多个 op，不能按文件名或行号直接合成静态节点。
- **捕获有明显执行影响与成本。** `trace()` 会运行模型；README/限制明确 stale detached callable 可能触发额外 rescue forward（结果明示未 byte-attestable），compiled module 捕的是 eager source 而不是融合 kernel；普通 capture 可能持有 autograd/saved tensors，需要 `cleanup()`。`save=`、`record()`、disk/window 选项可限制 payload 与部分内存，不会消除 instrumentation/引用/状态影响。包在首次 trace 后懒安装并保留 Torch wrapper；不能假设一次探针完全不改进程级调用环境。

**复用边界：** 三者中 TorchLens 最值得优先做隔离 adapter 对照。它能提供真实执行的 Torch op/输入位置、pass/module/条件上下文、部分 mutation/RNG/Tensor 证据；但不能替代 Python 静态未执行控制、cleanup/exception/host state、源码精确对应、外部 IO，也不自动成为合法变换证明。先对固定 artifact 保留其版本、capture mode、run、payload policy、缺口与副作用，再以现有 C1/P0 typed references 连接；不要把完整 TorchLens 数据模型复制到 SCAR，也不默认重复启用 SCAR/ETO 全量 capture。

### torchviz：从输出沿 autograd 回溯的梯度图

- `make_dot(y)` 接受**已经算好的输出**，实现遍历 `grad_fn.next_functions` 并返回 Graphviz `Digraph`；可选择显示 grad_fn attributes/saved tensors，并专门显示输出 view 的 `_base` 关系。
- 所以它回答“这个带 autograd 历史的结果，其反向函数/叶参数如何连接”，而非完整 forward/data dependency 图。没有 `grad_fn` 的推理结果、不可微运算或提前 detach 会使运算路径缺失；saved-tensor 与 view `_base` 是 autograd 保存/特定 alias 线索，不是 Python object/storage alias 的通用表示。
- 输出是带 `id(...)` 标签的可视化 Graphviz 文本，不含 Python source、CFG、状态/效果协议或版本化 typed interchange。`make_dot` 自身不重跑 forward，但其调用者此前已执行模型；`show_attrs/show_saved` 会访问 autograd 的保存信息。

**复用边界：** 仅用作反向梯度连通性检查/展示。不要导入为正向 producer/use、调用图或运行事实的权威来源。

## 面向 SCAR 的结论

1. **优先对照 TorchLens，而不是再写同类 Torch eager tracer。** 第一轮只测试 adapter 是否能保真读取一个固定 TorchLens artifact 的 op occurrence、重复输入位置、module/pass/conditional、Tensor mutation/version 与缺口。与已有 ETO/Profiler 的字段重叠由 adapter comparison 决定；不叠加两套采集后把同名 ID 合并。
2. **torchview 不足以作为这个 adapter 的数据关系来源。** 其观测 edges 对重复参数位置有损，且 capture 自身有 mutation/mode 影响；保留其展示能力即可。
3. **torchviz 的图方向和类型不同。** 有真实 autograd 问题时再作为外部校验，不让它补缺失的前向/源关系。
4. **所有 provider 保持作用域：** 实际某次 Torch 执行、图内 op/梯度、当前 payload 和系统测量是不同事实。静态未运行路径、Python/文件/外部别名、完整异常/恢复和后续可替代性仍需 SCAR source/core/evidence 层提供；provider 图为空不等于效果为零。

## 可核对的一手链接

- torchview [`README`](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/README.md)、[`computation_graph.py`](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_graph.py)、[`base_node.py`](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_node/base_node.py)、[`recorder_tensor.py`](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/recorder_tensor.py)。PyPI wheel 下载地址与 SHA 在上述本地 manifest。
- TorchLens [`README`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/README.md)、[`Op source`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/data_classes/op.py)、[`Layer source`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/data_classes/layer.py)、[`trace entry`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/user_funcs.py)、[`limitations`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/reference/limitations.md)、[`performance`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/performance.md)、[`structure-only contract`](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/reference/structure_only_capabilities.md)。
- torchviz [`README`](https://github.com/szagoruyko/pytorchviz/blob/5cf04c13e601366f6b9cf5939b5af5144d55b887/README.md)、[`dot.py`](https://github.com/szagoruyko/pytorchviz/blob/5cf04c13e601366f6b9cf5939b5af5144d55b887/torchviz/dot.py)。

**未验证：** TorchLens/torchviz 本机安装及兼容性、任一新 capture、GPU/大模型/LeWM、TorchLens 对任意自定义 dispatch/native side effect 的全覆盖；torchview wheel 与其同版本 GitHub commit 的源码等价性。不能把以上源码阅读升级成运行验证。

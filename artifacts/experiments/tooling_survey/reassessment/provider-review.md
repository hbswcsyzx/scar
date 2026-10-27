# 建图 provider 独立复审

2026-10-16。只读审查 `docs/TOOLING_SURVEY.md`、`MODELING_INTEGRATION.md`、
现有 `scar/trace` 与 IR；补读固定上游源码。另经 root 授权，执行一次独立 CPU
memory-provider 探针。未改产品、测试、共享文档或 LeWM，未安装、未跑全仓、未新增 backend。

## 结论

**现有映射没有发现阻断性夸大；复用方向合理，但有两个值得立即补入设计的具体接口。**

1. PyTorch profiler 已经有带 allocation ID 的实验 event tree、schema-based memory
   DataFlowGraph；不能忽略后再自写同类生命周期/算子变更分析。它的输入图是按
   TensorKey 聚合的 memory graph，**不是完整有序值 def-use 图**。
2. TorchLens 已有实际细粒度父参数位置，不只是画图；导入时要选
   `parent_arg_positions`，不能仅消费折叠后的 `ParentEdge`/`parents`。

上述是补充复用合同，不是授权将 provider 的版本、空字段或 validation 标志升级为
SCAR 的逻辑值/无效果/完整程序证明。新 provider 尚未接入。

## 1. 各工具真正给出的边和身份

| Provider | 可复用的数据连接 | 身份/变更信息 | 不能替代什么 |
| --- | --- | --- | --- |
| torchview 固定 `241d22b...` | module/function/Tensor 的具体 forward 连接和可展开层级；不是仅模块树。 | Tensor recorder 历史及节点身份；未提供通用 allocation generation / 外部写版本。 | `NodeContainer=OrderedSet` 折叠重复父节点，不能恢复 `f(x,x)` 两个实参槽；不是完整 Python CFG/状态图。 |
| TorchLens 固定 `550b96a...` | eager op、模块嵌套、动态路径及父 Tensor 参数路径；`parent_arg_positions` 保留具体 args/kwargs 位置。 | 有 source provenance、版本 witness、mutation/alias 相关记录及失败分类；这些已有能力应评估复用。 | 不是通用外部 alias 写监控；操作 schema 被信任，native/closure/escape 有明确边界；上游通过验证不等于 SCAR 纯性。 |
| FX | `Node.args/kwargs` 的每个引用位置；可递归导入 module/function/operator 子图。 | 定义级值关系；metadata/源码栈依捕获路线与版本存在。 | `users` 只枚举 consumer，不能代替有序 uses；不是 Python ObjectID/AllocationID/LogicalVersion。 |
| Export | FX/ATen 图、signature、call spec、lifted state、形状约束与规范化阶段的 mutation outputs。 | 条件化/变换后的数据接口；图阶段必须保留。 | functionalized 值不等于原物理 storage 身份；不能从 export 成功推导外部 Python 效果不存在。 |
| ETO | 实际 RecordFunction 输入/输出及 tuple、shape/stride/type/device；CPU `rf_id` 可与 profiler 对应。 | observer-local TensorImpl/data-pointer 映射身份；不含内容 epoch。 | 不是一般 Python ObjectID；allocator 重用、外部写、跨 copy 的统一逻辑值仍须额外证据。 |
| Profiler/Kineto | CPU op/runtime/kernel/copy/等待及原始关联字段；已有 raw Chrome 可先导入。 | 物理活动/采样/内存活动；不是逻辑数据证明。 | 聚合统计不能代替动态 occurrence；关联 enqueue 不等于 ready。 |
| Profiler experimental event tree / memory DataFlowGraph | 输入 Tensor metadata、allocation/free、schema 推断的 memory input/output versions。 | provider TensorID + AllocationID；某些字段可为 None。 | 按 TensorKey 聚合，view 在本次 memory graph 中没有输出，缺有序 full actuals 和通用值 producer；不可替代 ETO/FX 或 SCAR 全程序图。 |

torchview 具体源码还会执行 `model.to(device)`、改变 mode、在 `no_grad` 下 forward，
最后调用 `model.train(saved_model_mode)`。因此它适合受控展示/交叉核验，不宜在
需要保留梯度、混合子模块 mode、RNG/外部效果的 live 程序中额外调用后声称无扰动。
[官方固定源码](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/torchview.py#L250-L275)

重复父节点的折叠发生在基础节点容器本身，不能仅靠 Graphviz `strict=False` 修复。
[基础节点容器](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_node/base_node.py#L3-L14)

## 2. TorchLens：应复用具体位置，而不是再造 tracer

固定源码 `_locate_parent_tensors_in_args` 收集父 Tensor 的 args/kwargs 路径。
另一方面，`_parent_edges_from_fields` 为每个 label 选择一个位置；它不能单独提供
同一父值的全部 use 槽位。SCAR adapter 应导入原始位置映射中的每个路径，再建立
有序 Uses。现有文档将 TorchLens 列为动态 provider 是正确的；应把这个精确导入
接口写入合同，避免只导入可视化边后又自行推测实参。
[位置采集](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/backends/torch/tensor_tracking.py#L1024-L1085)、
[ParentEdge 投影](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/backends/torch/_ops_capture_records.py#L492-L519)

同一固定版本有 `_version` witness 和 same-object mutation verdict；这可导入为
限定来源事实，不能升级为覆盖 NumPy/raw-storage/native 全部写。某些 fallback
记录使用空 mutation/alias 字段及 `unknown_aliasing=False`，也不能自动解释为全域
NONE。上游限制页明确披露 schema 被信任、特殊写位置/来源缺口、恢复重跑和编译
回到 eager 的条件。必须保留具体 capture/validation reason 和 provider 合同。
[记录实现](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/backends/torch/_ops_capture_records.py#L202-L279)、
[fallback](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/torchlens/backends/torch/_ops_capture_records.py#L611-L623)、
[官方限制](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/reference/limitations.md)

本轮没有安装/import/运行 TorchLens 或 torchview；不声明本机兼容性、开销比例或
哪一个 provider 更快。上游功能声明与源码能力不等于当前环境验收。

## 3. 新发现：本机 profiler 内已有 memory identity / dataflow

本机 Torch **2.13.0+cu132**，git revision
`cf30153c4c131c8164ee7798e5022d810682e2cb`。以下本机源码位置均已直接读取：

| 路径（根 `/home/zyf/miniconda3/envs/lewm/lib/python3.14/site-packages/`） | 精确内容 |
| --- | --- |
| `torch/_C/_profiler.pyi:135–180` | `_TensorMetadata` 的 impl/storage pointer、id、allocation_id、layout/device/dtype/sizes/strides；TorchOp inputs 与 Allocation metadata。 |
| `torch/profiler/_memory_profiler.py:76–144` | `_Storage` 以 allocation_id 而非裸 pointer 比较；TensorKey 结合 provider tensor id、allocation 和 device。 |
| 同文件 `:215–246` | schema 匹配推断哪些输入可能写；无法匹配时保守处理，不是实际内容检查。 |
| 同文件 `:428–512` | DataFlowNode 按 TensorKey 合并 inputs、维护 may-mutate/version，处理 allocation/free。 |
| 同文件 `:524–640` | DataFlowGraph 及版本递增、验证、选择 operator 叶层。 |
| `torch/profiler/profiler.py:574–585` | `_memory_profile()` 的三个 flags 和 `kineto_results` 门槛。 |
| 同文件 `:587–591` | `export_memory_timeline` 的弃用声明。 |

对应[内存分析源码](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/profiler/_memory_profiler.py)、
[元数据类型](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/_C/_profiler.pyi)、
[profiler 入口](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/profiler/profiler.py)。
本机三份文件 SHA256 保存在探针 results.json；没有保存第三方源码副本。

### 3.1 两条接口的获取条件不同

| 接口 | 条件与边界 |
| --- | --- |
| `prof.profiler.kineto_results.experimental_event_tree()` | 需要本次有效的 profiler result。对应 C++ `collection.cpp:343–345` 在 `report_input_shapes` 时记录输入；`:1664–1665` 仅在 `report_input_shapes && profile_memory` 时赋 Tensor/Allocation IDs。不经 Python `_memory_profile()` 的三个 flags 检查。metadata 可缺失，ID 可 None，所有字段必须按实际存在导入。 |
| `prof._memory_profile()` | 本机 Python 入口明确要求 `record_shapes=True, profile_memory=True, with_stack=True` 且 Kineto result 已就绪；它另建 schema-based memory DataFlowGraph。不能因为树存在就假定这个入口也可调用。 |
| `export_memory_timeline()` | 本机已经标 deprecated；导出 timeline 也不是完整 op def-use 交换格式。源码建议的 CUDA allocator snapshot 侧重 GPU allocation，不替代 CPU/算子输入图。 |

底层 ID 算法对可观察的 allocation/free 做 lifetime 区分并合并关联组；其 TensorID
不是 ETO 的 TensorImpl 映射 ID，更不是 Python 对象或 SCAR LogicalValueID。
[采集/后处理条件](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/collection.cpp#L1664-L1665)、
[身份合同](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/data_flow.h)、
[身份分组实现](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/data_flow.cpp)。

**Inferred from source**：SCAR 目前 `inject.py` 默认 `record_shapes=True`、
`profile_memory=True`、`with_stack=False`，可能已经采得可复用的 raw 输入/身份信息。
因此不必为读取这类 metadata 先开启 with_stack。**本次只测三个 flags 全开的组合，
没有测其他组合，也没有证明现有 SCAR artifact 已持久化这些字段。**

### 3.2 一次 CPU 实测，所有成功/失败原样落盘

[`memory-provider/probe.py`](memory-provider/probe.py) 实际只捕获一次，包含小 CPU
tensor 的 add、view、两次 add_、clone/free；不输出 Tensor 内容，不 import SCAR。

- capture、experimental event tree、memory profile 三阶段均 PASS。
- **34 条 TorchOp/allocation 记录，12 个 memory DataFlowGraph 节点**。
- 两次 `aten::add_` 对相同 provider `tensor_id=3/allocation_id=4`，依次 **0→1→2**。
- view 前后 `impl_ptr` 不同，而 provider id/allocation_id 相同；该 memory graph 的
  view 节点 outputs 为空。这是 memory-flow 抽象，不能当完整值 producer 图。
- CUDA `is_initialized()` 前后均 false；没有 GPU 关联或外部写实验。

原始小证据：[results.json](memory-provider/results.json)、
[stdout](memory-provider/probe.stdout)、[stderr](memory-provider/probe.stderr)。
未重跑、未扩展 flags 矩阵。版本递增只是此 provider 的 schema-based 分析结果；
不证明值真的改变，更不证明以后稳定、外部写完整或跨 copy 逻辑等价。

## 4. SCAR 当前接线审计与最快可复用路线

**Observed from SCAR source**：`trace/inject.py` 已使用 profiler，导出 raw Chrome，
但通用 Torch op 主要写 `key_averages()` aggregate；`trace/cuda.py` 导入实际 GPU/
runtime 活动。可选 TorchDispatch/module/transfer wrapper 提供更多元数据，但
没有 ETO/FX/Export/TorchLens adapter。`normalize_v2.py` 没有把旧 storage/version
字符串升级为确证身份；`values_v2.py` 也明确描述 mutation coverage UNKNOWN。

建议的接口接入顺序（**Proposed，未实施**）：

1. **先消费已保存的 raw CPU op，而非再采同样统计。** 保留 scope、原始 ID、
   availability、occurrence 和 clock domain；aggregate 继续只作测量。
2. **同次采集使用 ETO 的输入/输出和 rf_id；评估 existing event tree 的 allocation
   metadata 补充生命周期。** 对 provider 身份分开建 namespace，实际关联键要验收；
   不因两个字段都叫 id 或 pointer 数字相同就直接 join。实验接口需版本门槛和
   能力探测，失败保留明确缺口；不要重新实现其所有 schema/identity 分析。
3. **已有 FX/Export 图直接导入，控制捕获与执行图分开。** 逐 args/kwargs 位置
   建 canonical Uses；保留 graph stage、guards、lifted state 和 alias/mutation
   边界。没有现成图时，额外 forward 必须是可控 replay。
4. **TorchLens 作细粒度动态 provider 隔离比较。** 对已存在的父参数位置、
   source/mutation attribution 进行复用评估，不默认与所有 observer 同时开启；
   torchview 保留为展示/交叉核验。先测兼容、来源完整性和采集成本再决定取舍。

这条路线只需 provider adapter 和对应验证，无需再造 Tensor tracer，也不要求
先完成任意 Python 编译器。Profiler shape/stack、payload 保存、引用持有和私有
接口都可能有成本；没有测量时不许写成零开销或已比另一工具快。

## 5. SCAR 应保留的核心

保留一套 canonical Operation/Value/Region/state/control/resource 接口，以及来源、
动态 occurrence、provider realization 的限定对应。Provider 提供局部事实；SCAR
连接 Python 作用域/调用、状态版本/别名/外部写、同步/异常/部分状态、资源 ready、
跨 copy/transform 的逻辑来源、观察根依赖闭合与未来可替换区域。

不能用 ETO 重复 tuple、TorchLens label/validation、memory DataFlowGraph version、
FX 常量叶子或 profiler 时间替代这些关系。采样相同不证明相等；物理副本相同也
不证明合法替换。当前文档的这条边界应保留，不应因为采用成熟工具而删除。

本轮无整程序完整性、自动化简、LeWM 加速或 GPU 因果结论。

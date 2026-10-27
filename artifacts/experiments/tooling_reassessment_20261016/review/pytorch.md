# PyTorch 建图接口复审：实际接入与最小复用路线

2026-10-16；审查 HEAD `78c5fdaaea5b189c0de8c3d9f26159912d615486`。
范围：只读产品/文档/既有实验、本机源码及官方网页；未 import Torch、运行新 capture、
测试、LeWM/GPU 或修改环境。下列源码能力不等于 adapter 已运行。

## 1. 版本与证据界限

本机 `T=/home/zyf/miniconda3/envs/lewm/lib/python3.14/site-packages/torch`。
`T/version.py:4` 显示 2.13.0+cu132，`:7` git revision
`cf30153c4c131c8164ee7798e5022d810682e2cb`；CUDA 字段是构建信息。
官方 stable 网页现跳转 2.14；本轮部分 2.13 URL 不可访问，故网页仅复核概念，
本机 API/默认值以已安装源码为准。没有把在线 2.14 行为验收为本机行为。

## 2. Implemented：实际接线到哪里

| 现有代码 | 已实现的复用 | 尚未实现/不能声称 |
| --- | --- | --- |
| `scar/trace/inject.py:149`、`:166`、`:200` | Python profile、torch.profiler(shape/memory=True, stack=False)、Chrome 导出 | 初始化失败可静默停用；没有统一结构化 collector 缺口记录。 |
| `inject.py:75`、`:107`、`:175` | module/transfer wrapper，可选 TorchDispatchMode | module 和 dispatch 记录在正常返回后才写；不能算异常调用/全操作数覆盖。 |
| `inject.py:208` | key_averages 统计，明确 aggregate、无 InvocationID | aggregate 不是一次次真实 op 的 def-use。 |
| `scar/trace/cuda.py:69`、`:95` | Chrome kernel/memcpy/wait、correlation/runtime 字段 | wrapper→Tensor 的 direction/bytes 唯一签名匹配（`:47`）明确仅 Inferred。 |
| `scar/trace/call_operands.py:140`、`:922` | sys.monitoring 受限窗口及操作数证据 | 不是 Dynamo adapter，也不是 Python 全操作数栈。 |
| `scar/ir/program/providers.py:1`、`native.py:1/120`、`native_validation.py:31` | P0/P1 来源、native 槽与 canonical 端口分区、八域未证关系 | 不读 artifact，不解释 raw role/TreeSpec，不验证映射真实性、不产生真实 provider 图。 |

对 `scar/**/*.py` 搜索 FX/Export/Dynamo/AOT/ETO/event-tree/memory-profile 调用，未发现
生产适配入口。**FX、Export、Dynamo、AOTAutograd、ETO、profiler memory dataflow 均未接入**；
文档中的试验/接口声明不能计成集成。普通 profiler/Kineto 已接入，不应再造 CUPTI。

## 3. Observed（源码/官方资料）：哪些现成接口足够复用

| Provider | 最小可用接口及源码位置（前缀 T） | 边界 |
| --- | --- | --- |
| FX | `fx/node.py:433/456` 的 args/kwargs；按每个嵌套位置生成 canonical Use | `all_input_nodes:479`/users 聚合 unique nodes，不能保留 `x+x` 两槽；symbolic_trace 不支持普通数据依赖控制。 |
| Export | `export/exported_program.py:1165/1236/1292`：graph_signature/range_constraints/call_spec；graph_module；`export/graph_signature.py:81/121` 输入输出 roles | 原生 signature 包含 lifted inputs、mutation/grad/token；call_spec 的用户 pytree 不等于所有 flat 槽。raw/decomposed 图必须分阶段分身份。 |
| Dynamo | `T/_dynamo/eval_frame.py:1812` explain 的 graphs/break_reasons/out_guards；已有 compiler graph 与 logs 优先 | `:1853` 真正执行 opt_f；`:1818/1862` reset，不能当 live 程序无扰动检查。FX graph 之外还有 residual bytecode/效果；guards 不是内容版本证明。 |
| AOTAutograd | `T/_functorch/aot_autograd.py:702` joint→partition；`:1538` aot_export_module；`:1308` aot_export_joint_with_descriptors | 私有接口且会捕获/改变表示。`:1324` 明确无固定位置协议，不能硬编码第 N 输入对应原第 N 参数。 |
| ETO | `profiler/profiler.py:1270/1347` observer/register_callback；`:338/389` 与同一个 profiler 窗口 start/stop | RecordFunction 的动态 op I/O、schema、局部身份；不是完整 Python/外部状态/程序静态图，host 记录不说明 GPU ready。 |
| profiler/Kineto | `autograd/profiler.py:602/747/760` 已按 correlation/linked_correlation 关联 CPU、runtime、device | 应引用现成关联并保留原域；不能用时间邻近、名称或 copy 字节数补因果/逻辑身份。 |
| event tree / memory profile | `_C/_profiler.pyi:135` metadata；`profiler/_memory_profiler.py:98/215/428/524` TensorKey、schema may-write、内存数据流与候选版本 | DataFlowGraph 是 TensorKey 聚合，view 可无新 outputs，不是 ordered fullactuals；版本不覆盖 NumPy/外部写。 |

官方交叉依据：

- [FX 动态控制限制](https://docs.pytorch.org/docs/2.14/fx.html#dynamic-control-flow)。
- [Export 概览](https://docs.pytorch.org/docs/stable/export.html)：默认图可含 mutation；
  [Export API](https://docs.pytorch.org/docs/stable/user_guide/torch_compiler/export/api_reference.html)
  与本机 `export/__init__.py:65/130` 均需按 strict 模式解释；本机默认 strict=False。
- [Dynamo graph/残余字节码/guards](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/compile/programming_model.dynamo_core_concepts.html)：
  list append 等效果可由 residual bytecode 保留，导出 FX graph 不含它并不说明效果不存在。
- [AOT joint descriptors](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/export/joint_with_descriptors.html)。
- [Profiler 与 ETO 同窗口](https://docs.pytorch.org/docs/2.14/profiler.html)：record_shapes 会保留引用并增加开销/副本，metadata-only 不等于零成本。

## 4. 应停止重复手写的两个具体位置

**mutation 猜测应由 schema 来源替代。** `scar/trace/session.py:354–367` 当前按 op 名
尾 `_` 判写，然后标记全部 positional Tensor；没有解释 kwargs/out 或精确 overload。
`inject.py:180` 又把已有 func 先转成 str。可保留原 op/schema，按 argument 槽复用
`alias_info.is_write`；`T/utils/_python_dispatch.py:773` 已这样读取，profiler 的
`SchemaMatcher.inputs_are_mutable:228` 对 overload 不明做保守合并，找不到 schema 返回
未知。无需再维护 op 名规则；schema 本身仍不是 custom/native 外部效果完备证明。

**前后向/物化改写不要自己复刻。** 本机 AOT descriptors 已包含 Param/Buffer、
ViewBase/SyntheticBase、InputMutation/MetadataMutation、Grad/Tangent、Philox 与 Token
（`T/_functorch/_aot_autograd/descriptors.py:382–690`）；已有 fx_utils 角色查询
（`:44/230/258`）。按原生 descriptor fact 适配，不复制全部枚举/重写解释器。
这些工具处理了部分 alias/mutation 包装，SCAR仍需连接当前 module/ref/state 与写回；
不能将 mutation Tensor payload 改型为 StateVersionValue。

Dynamo 已有 `T/_dynamo/source.py:147/304/337/694/738` 的 Local/Attr/CellContents/
Defaults/GetItem 来源链，`side_effects.py:93/1303` 追踪并生成被支持的残余修改。
若现成 capture 含这些事实，先引用其原生路径和 guards；不再手推同类 lookup 路线。
它们是内部捕获合同，不是任意 Python 的完备依赖分析，也不直接提供当次 StateVersion。

## 5. Proposed：最短接入与验收顺序

1. **优先导入已有 FX/Export artifact**：原生图/签名/TreeSpec 留存 hash；从 args/kwargs
   精确路径接现 Use；从 signature 接 P1 边界，当前未解 lifted 状态/完成义务逐域保留。
   不要求先重写所有 Python 规则，也不额外在 live 模型上多跑一次 forward。
2. **动态证据用同一 profiler + ETO**：导入原生 ordered I/O/schema/rf_id，并优先取已有
   profiler 结果字段；先比较能替代哪些 wrappers。不要所有 observer 默认全开。
   `_memory_profile()`（`profiler.py:574`）要求 shapes/memory/stack 三项，但普通 metadata
   的条件不同；不为读字段无条件打开 with_stack。memory timeline API 已 deprecated。
3. **有现成 Dynamo/AOT 图再引用其 conditions/descriptors**；受控隔离 capture 是独立
   任务，不把 explain/strict/non-strict 捕获当纯读取。AOT 不是初始接入的必需阻塞项。

最小反例验收：`x+x` 两个 Use 不被合并；raw/decomposed mutation 接不同表示且不能
漏写回；rf_id 缺失/重复/跨窗口拒绝强配；同 tuple 的 add_ 或 NumPy 共享写不能复用
旧 LogicalVersion；捕获期间 Python counter/list/RNG 副作用不可凭 FX 缺节点删除。

## 6. Verified / 未证实 / SCAR 必须保留

本轮仅重新读取历史 CPU 证据：`tooling_survey/runtime/REPORT.md` 的 schema
1.1.1-chakra.0.0.4、34 个正 rf_id↔34 CPU record；`reassessment/memory-provider/results.json`
的两次 add_ 候选版本 0→1→2。它们不升级为当前集成验收，更不证明 GPU 关联。
ETO TensorImpl/storage 映射 ID、profiler metadata id/allocation_id、FX Value 名互不等同；
跨 deepcopy/copy/transform 的逻辑身份、owner/selector、外部 alias 失效、activation、
异常/状态/资源完成以及 Q/M 合同仍由 SCAR 接通，但不能重新采集工具已提供的同类事实。
无需每轮保存 Tensor 数值；metadata/少量样本不能充当相等证明。AOT descriptors 本机
可用性、导入真实性、开销、GPU memcpy/ready 及 LeWM 整图/可信变换/clean 加速比均未验收。

结论：现文档对“adapter 未实现”的边界基本准确；应补具体 AOT descriptor 与 Dynamo
residual/source 复用点，并优先把现成图接到已实现 P0/P1，避免继续扩手写 Tensor tracer。

# Tensor → provider allocation epoch：复用现有 PyTorch 物理模型

## 状态与范围

2026-10-23。**Observed**：已安装 Torch 的类型声明、头文件、内存分析实现和固定版本
源代码表明，`experimental_event_tree()` 已提供 Tensor 的物理元数据和 allocator
receipt；SCAR 不需要再实现 TensorImpl ABA 检测或根据地址猜测 allocation 代次。

**Implemented**：新增 `scar/trace/tensor_physical.py`，仅有 post-close sidecar exporter。
后续已接公共CLI `trace --tensor-physical`、collector及原ValueGraph/EvidenceGraph
importer；同一次现有CPU案例实采核验35marker/39slot/17物理epoch通过。依据见
`artifacts/experiments/first_stage_tensor_physical_20261023`。生产OS membership及
LeWM GPU实际核验仍待统一采集；不是完整程序建模已通过的声明。

**OPEN**：同 provider 结果中的 marker 参数可以引用其 allocation epoch；单条 tree
Allocation 与既有 Kineto `[memory]` 原档 receipt 的准确对应还缺少公开 locator。
这两个连接有不同的证据，不能合并宣布完成。

## 1. 固定 provider 与本机一手来源

安装根：
`/home/zyf/miniconda3/envs/lewm/lib/python3.14/site-packages/torch`。
Torch `2.13.0+cu132`，git revision：
`cf30153c4c131c8164ee7798e5022d810682e2cb`。以下 SHA256 于本机实际读取；行号针对
这份安装/保留原档。私有 API 只接受这一完整 revision，不能按版本号近似兼容。

| 相对安装根的文件 | 行 | 实际 SHA256 |
|---|---|---|
| `_C/_profiler.pyi` | 90–178 | `c4656810004ee9569965f6c3fb80c0eec4e28d788a79b85368fa9556457c3757` |
| `_C/_autograd.pyi` | 34–101 | `d2959a593cf79d12dbff3f457c322908d72a82b0c01293d2f5b8649f6773f65b` |
| `include/torch/csrc/profiler/collection.h` | 45–123、150–246 | `f6e92b28ee8b2ab737b1709c7b8a5d3327ad0d5cba445f90655e0a317102e811` |
| `include/torch/csrc/profiler/data_flow.h` | 13–37、56–83 | `ab6a23a9cb336c05a1662a7a32e0a8d82dbdb00adf0450399e200c4cbb87f780` |
| `profiler/_memory_profiler.py` | 75–145、329–410、443–490 | `c905e005274968bbcd0cf9db0c9361cc48789f4da7982c71f14a350a6a3631de` |
| `profiler/profiler.py` | 195–200、574–586 | `2e7e248cba6f46787aeb693cd3fb82a1328936dc37e41be86a8e490ea1051eb9` |
| `include/torch/csrc/profiler/orchestration/observer.h` | provider options | `8450e07c1044aebe226f2a5f949f984a6da5ff28291dfb93a4bbe918f850807d` |

工作区原有固定版本 source receipts：
`artifacts/experiments/first_stage_native_scope_20261020/sources/`。

| 保留文件 | 行 | 实际 SHA256 |
|---|---|---|
| `torch-collection.cpp` | 33–66、124–145、330–347、721–742、878–915、975–1015、1540–1565、1664–1666 | `2142919c3fffffb87770d54b6c9ba5bd070164852c419b671195ea8031a1323d` |
| `kineto-shim.cpp` | 110–115 | `8ad44814f7e2128f47276bce2ca79d9b0ddbc1f22cd2308ef2e2dd65fac2a03d` |
| `output_json.cpp` | 785–807 | `7301286695d55122f45bd1c2150df89cccd02104182a2f6580b055dccc354db2` |

另有固定 revision 的上游一手源代码，补充安装包未保留的 C++ binding/实现：

- [python/init.cpp](https://raw.githubusercontent.com/pytorch/pytorch/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/python/init.cpp)，
  518–578、624–649：Python 可见字段；event.id 实为 `Result*` 地址；没有暴露 TorchOp
  的 C++ `record_function_id_`。
- [data_flow.cpp](https://raw.githubusercontent.com/pytorch/pytorch/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/data_flow.cpp)，
  25–39、99–173：TensorMetadata/Allocation 共用物理分配索引；allocation 计数从 1
  开始，free 删除 `(ptr, device)` 当前代次，TensorID 分组计数从 0 开始。
- [profiler_kineto.cpp](https://raw.githubusercontent.com/pytorch/pytorch/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/autograd/profiler_kineto.cpp)，
  320–334、494–519、596–600：Chrome RF 标识、memory 字段、结果生成和 inputs 开关。

以上来源只能支持指定 provider 契约。它们不是任意版本、任意外部 collector 的授权。

## 2. 已有字段足够做什么

`_TensorMetadata` 的实际字段：

```text
impl_ptr
storage_data_ptr
id                  # provider TensorID
allocation_id       # provider allocation epoch
layout / device / dtype
sizes / strides
```

`storage_data_ptr` 来自 `tensor.storage().data()`，是 storage 的起点。不是加过
view offset 的 Tensor 数据指针。Python binding **没有 storage_offset，也没有准确
allocation nbytes**。不能用 shape/stride 估算替代 allocator receipt 的真实 extent。

`_ExtraFields_Allocation` 的实际字段：

```text
ptr
id / allocation_id
alloc_size          # signed: positive allocation, negative free, zero 单独保留
total_allocated / total_reserved
device
```

每条 receipt 还保留所在 event 的 Result 地址、parent、时间、provider thread token
和 correlation id；缺字段明确留空并附 gap。它表示 allocator 观察，不能自动改写成
物理 `cudaMalloc/cudaFree`、stream completion 或 Tensor contents。

`_ExtraFields_TorchOp.inputs` 包含有序 TensorMetadata 或其他 provider 输入类型。
本桥只接受 SCAR 已有生产 marker 所传入的**直接 Tensor 参数**。output marker 也把
真实输出 Tensor 作为 marker 的输入，因此读取同一个 `extra.inputs` 接口。TorchOp
没有 Python 可见的 outputs 字段，不能编造。

### 四种身份不能混用

| 原字段 | 范围/含义 | 不可推出 |
|---|---|---|
| Python weak ObjectID | Python 包装对象身份和对象生命周期证据 | Tensor 内容、TensorImpl 相同 |
| `impl_ptr` | provider 以 weak intrusive pointer 防 ABA 的 TensorImpl 地址 | Python ObjectID、逻辑值 |
| `TensorMetadata.id` | TensorImpl/storage 关系的**传递分组** | allocation、LogicalValueID、LogicalVersion |
| `allocation_id` | 这一 profiler result 内部的物理 allocation 代次 | 内容不变、跨 profiler 身份、ready |

`data_flow.h` 明确说明：同一 TensorImpl 曾先后指向 S0/S1 时，两边 Tensor 会被并入
同一个 TensorID 分组。因此 TensorID 既不能当 logical value，也不能当唯一 storage。
**实际观察到的 TensorID=0 有效；缺省字段绝不填 0。** allocation_id 必须有正整数
观察；空指针保留原始 0，但不构成有效物理分配引用。

## 3. 准确连接及仍然 OPEN 的一段

```text
dispatch source: weak ObjectID + 原始 payload path + reference ordinal
  ↓ 固定生产契约：同 nonce / pid / sequence / phase 的唯一 marker
tree marker: extra.inputs[argument ordinal]
  ├── TensorMetadata.impl_ptr / storage_data_ptr / geometry
  └── TensorMetadata.allocation_id
        ↓ 同一 provider result、capture/process/device namespace
      tree Allocation.allocation_id + 原始 signed allocation receipt

同一 marker name + 同一有序参数槽
  ↓ 原有 dispatch importer 必须实际核验唯一性、槽数、provider descriptor
ETO marker + ETO Tensor descriptor
  ↓ 原有 exact RF 对应
Kineto CPU record

tree Allocation ── OPEN ── 既有 Kineto [memory] 原档 receipt / 既有 allocation epoch
```

生产 marker 格式固定：`scar-dispatch:<nonce>:<pid>:<sequence>:span|output`。
唯一 nonce 及完整实际名称来自生产采集器，不是任意用户函数名或邻近时间的匹配。
同一个 Tensor 出现多次仍是多个有序参数槽，不能集合去重。

exporter 将每条 marker 连接到**原 dispatch 文件行及同一 reference ordinal**，不复制
原大数组。消费者须读已绑定 exact raw SHA/bytes 的原档。`DISPATCH_END` 还需确认
对应 marker enter 返回；仅有 BEGIN 不足以授予完整对应。实际树扫描结束后，metadata
才统一确认 marker 唯一、所需 marker 全部出现、参数槽数/类型合格。扫描中写出的行
标为 PROVISIONAL；完整性不通过时消费者不能把它们当成已验证连接。

event_tree 的 `event.id` 是 `Result*` 地址，`start_tid` 是 RecordFunction 的线程
token。二者都不是 RF id 或 Linux TID。sidecar 单独保留真实 dispatch `native_tid`
与 Python ident；其连接来源是同一个已核验 marker，不能按整数相等合并。tree
correlation id 同样不能改名成 RF id；Allocation 的 correlation 通常是 0，不能用它
做跨图唯一连接。

### 为什么旧 Kineto allocation 仍 OPEN

`torch-collection.cpp:878–915` 将**当时原始 Result vector index**写为 `Ev Idx`。
Kineto 接回原 Result 的内部流程有此 locator，但 Python `_ProfilerEvent` 没暴露它。
Result 随后又经过 merge、排序、建树；DFS order、按时间排序、`enumerate(events())`
都未证明与原 vector index 相同，尤其是时间相等时。源码的内部临时 activity 指针
也未作为 Python 属性保留。

因此地址/时间/size/totals 全部相等仍不足以认定是同一条 receipt。本实现只保留
tree 原始 allocation receipt 和 provider epoch，明确
`legacy_kineto_allocation_correspondence_established=False`。后续需要暴露明确原始
locator，或逐步骤证明且验证同版导出映射，才能接原有 IR 的 allocation epoch。
不得用 tree.id、TensorID、storage-map token 与其他 namespace 的同数值硬接。

## 4. 下一次统一采集必须增加的配置/字段

```python
record_shapes=True
profile_memory=True
with_stack=False
experimental_config=torch._C._profiler._ExperimentalConfig(
    adjust_timestamps=False,
    trace_only=False,
)
```

`torch-collection.cpp:1664–1666` 只有 shapes 和 memory 同时开启才调用
`calculateUniqueTensorIDs`。低层 TensorMetadata 物理桥不需要 with_stack。高层
`profiler._memory_profile()` 要求三项全部 True，且另做 schema mutation 推断、版本
推断和分类；那些版本不等于 SCAR logical version，本桥直接复用底层物理证据。

本机 `_ExperimentalConfig` **没有 memory_dataflow_graph 开关**。当前 collector
manifest 的同名 False 是自身描述，不能误传为 PyTorch API。`trace_only=True` 不生成
所需 tree，必须拒绝；时间自动调整也不用于此桥。with_stack 不决定本桥资格。

已保存的 `first_stage_lewm_dispatch_20261023` manifest 明示 record_shapes=False。
该档没有被采集的 TensorMetadata/allocation IDs 不能事后恢复。新的统一采集将
使用公共flag补齐字段，旧原档及其未闭合项完整保留。

## 5. 实际 exporter API 与生命周期

```python
from scar.trace.tensor_physical import export_tensor_physical

# 整个 manager.close() 已返回：dispatch stop → profiler stop/export → ETO
# unregister → final native manifest → dispatch meta/hash 全部固定。
report = export_tensor_physical(
    manager._profiler.profiler.kineto_results,
    output_directory,
    nonce=capture_nonce,
    provider_revision="cf30153c4c131c8164ee7798e5022d810682e2cb",
    dispatch_metadata_path=explicit_dispatch_meta,
    dispatch_observations_path=explicit_dispatch_jsonl,
    native_manifest_path=explicit_native_manifest,
)
```

调用方仍持有**同一关闭 profiler 的真实 result**；本模块不 import torch、不启动
任何 provider、不给其他 profile 造所有权。接口验证精确私有 result 类型和当前
已加载 Torch revision。文件路径由调用方显式提供，仅打开 output directory 下
exact filename/PID/nonce 对应的 live plain 文件；不会跟着 manifest 的任意 URI 开文件。

读取并严格核对：

1. 最终 native manifest CLOSED/owned、provider/config、同 nonce 的 ETO/Kineto 路径；
2. dispatch profile/owner process/nonce、owned mode popped、准确文件声明；
3. dispatch meta 中 native manifest 的真实 SHA/bytes；
4. 流式读取 dispatch 原档，严格 JSON、连续 index、marker/phase/原线程和 ordered
   slot 数，核全档真实 raw SHA/bytes/lines；
5. 不修改任何原 manifest，避免破坏已固定的 raw hash 链。

新增且独立的文件：

```text
tensor-physical.<pid>.<nonce>.jsonl
tensor-physical-meta.<pid>.<nonce>.json
```

二者 O_EXCL 创建，原文件永不覆盖。metadata 先独占保留、最后写入最终报告；消费者
只能在调用返回、文件关闭且元数据完整可解析后做 membership publication。发生失败时
空/部分文件不会被当成 CLOSED 原档。调用方负责捕获 exporter 错误，不能改写应用结果。
此新 receipt 绑定已关闭原档；原生 manifest 不会被回写增加它。

### 有界与吞吐

- dispatch 输入单行、总 bytes/rows、marker/attempt 数、Tensor 槽数均有限制；无效或
  超限 source 在发布前直接拒绝。
- tree 采用 iterator stack DFS，不 `list(all_events)`、不复制全量 event 数组。记录
  visited provider IDs 以检测重复/循环，内存由 max_nodes/max_markers/max_depth 限定。
- 只输出实际 owned marker metadata 和**所有观察到的 Allocation receipts**，不导出
  无关 operator 全量副本，不保留 Tensor 内容或真实 Tensor 引用。
- 输出受 max_events/max_bytes/max_line_bytes 限制；命中预算停止，报告明确 frontier、
  已访问数和 `dropped_events_at_least`。未访问数量为 unknown，不能伪造准确 drop 总数。
- provider 自己已经持有的缓冲、API 返回 roots/children/inputs 的浅列表不受 exporter
  硬内存预算约束；instrumented run 不能作为 clean benchmark。

默认 output 1,000,000 rows / 512MB，遍历 2,000,000 nodes，marker inventory 250,000。
默认参数都是显式可覆盖正整数；metadata 2MB、单行 2MB。配置应由真实采集容量决定。

## 6. 接原有模型的条件与拒绝边界

**Proposed** 的后续 importer 应通过原有 entity/edge 接口表达：

1. 由已验证 marker/槽，把现有 Python Object reference 和 ETO Tensor reference 接到
   provider TensorMetadata receipt；建立物理 reference refinement，保留源位置。
2. 同一 result 的 allocation_id 只在 provider/capture/process/device 命名空间内有效。
   按此原生 epoch 将 Tensor storage reference 接到该原生 allocation receipt；实际
   pointer/device 冲突要拒绝，同地址跨 epoch 必须拆开。
3. birth/free 在 capture 外缺失时保留 OPEN lifetime；不能让 preexisting 分配的首次
   Tensor 观察冒充 allocation birth。
4. 完整 Region 还需要准确 offset、shape/stride/dtype 和已绑定 allocation extent。
   这些要与同 marker 同槽的 ETO descriptor 实际核对；不能由 base ptr 推测 offset。
5. 只有额外具备 logical version、producer、representation/device、真实物理 allocation/
   region 和 ready 证据时，才能创建原有 `Materialization`。本 sidecar 一项也不伪造。

必须拒绝或留 OPEN：provider 不匹配；source hash/bytes 不匹配；非 production marker；
marker 重复、缺失、未确认 enter、参数槽数/类型不一致；Tensor subclass/unsupported
geometry；未完成遍历；无 allocation ID；0/null storage pointer；跨 result/进程整数碰巧
相等；仅有地址/时间近似；只有 alias schema 而没有真实 alias/lifetime；外部 NumPy
写入未封闭；GPU ready 未观察。

物理关联是完整程序建模的一块证据，不是常量证明、缓存许可或逻辑版本证明。本轮
没有增加 backend、detector、优化规则或 LeWM 特例。

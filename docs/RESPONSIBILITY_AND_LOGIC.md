# SCAR 的职责与逻辑流程

当前架构和实现范围分别见 [IR_DESIGN_V2.md](IR_DESIGN_V2.md) 与
[STATUS.md](STATUS.md)。本阶段输出可重算的分析和精确修改指导，不修改目标源文件。
后文明确标为 v1 的 capture/backend 接口保留兼容，不代表 v2 已连通完整自动优化。

## 1. SCAR 要解决什么问题

SCAR 的职责是面向**任意真实程序执行过程**，自动发现可以避免的工作，并在证据足够时决定如何处理。目标不是把程序简单分成“计算”和“IO”，也不是针对某个模型写规则。

这里的“可以避免”包括：

- 相同逻辑数据上的重复计算、解析、索引构造和 preprocessing；
- 相同逻辑版本的重复 materialization、CPU 到 GPU 搬运和 host scalar materialization；
- 不必要的 allocation/free、buffer 未复用和 layout/representation 转换；
- 不必要的 Python dispatch、同步、等待、barrier 和重复控制路径；
- 循环不变量没有 hoist、可以安全 fuse/合并的操作、应该提前的 prefetch；
- 只有当副作用、异常、随机性、别名、可见状态和外部顺序都能守住时，才可以消除或延迟工作。

SCAR 的检测器是通用的。PyTorch 和 NVIDIA GPU 是 v0.1 的运行范围，不是模型的特殊分支。LeWM 是外部 testcase，位于 `../scar-testcases/lewm`，不能被导入为 SCAR 核心逻辑。

## 2. “任何代码都要分类”应该怎样理解

SCAR v2 对程序建立三种职责不同、通过 typed correspondence 连接的图：

1. **Semantic Graph**：广义 OperationDefinition、输入输出槽、有序操作数、局部绑定和控制结构，绑定源码版本。
2. **Execution Evidence Graph**：真实 OperationInstance、read/write、对象/版本观察、kernel、copy、sync 和资源测量。
3. **Optimization IR**：可递归展开的替换区域、边界接口、精确 delta、Q、证明义务、成本、冲突与 fallback。

静态分类不是动态事实。比如 AST 可以看出一行包含调用，但不能证明调用纯净、没有 callback、没有异常或没有隐藏写入。动态 trace 也不能看到所有未来分支。SCAR 用图把两种证据连接起来，并保留证据来源和未知状态。

每个 Action 可以同时拥有多个标签：

| 标签 | 含义 |
| --- | --- |
| `VAL` | 产生或检查数值，例如 scalar、parse、GEMM、attention、topk |
| `REP` | 改变表示，例如 view、reshape、permute、cast、deserialize |
| `MEM` | allocation、free、retain、reuse |
| `XFER` | 设备或存储之间的 materialization/copy |
| `STATE` | 读写 module、dict、list、RNG、环境等状态 |
| `CTRL` | call、branch、loop、dispatch、enqueue |
| `ORDER` | wait、synchronize、barrier、stream ordering |
| `IO` | 文件、环境、日志、视频和外部交互 |
| `OPAQUE` | 当前证据不能可靠解释的区域 |

标签不是互斥枚举。一次 CUDA enqueue 可能同时是 `VAL|CTRL`，一次 `to(device)` 可能是 `REP|XFER|MEM`，一次文件读可能是 `IO|CTRL|STATE`。

每个动作还必须记录 effect：`reads`、`writes`、`allocates`、`frees`、`aliases`、`escapes`、`rng_effect`、`may_raise`、`external_effect` 和 `ordering_effect`。没有证据时使用 `UNKNOWN`，不能把空列表误当作没有副作用。

## 3. 六个正交视角与独立数据身份

SCAR 的内部模型是 `<K, Σ, A, R, Q, M>`：

- **K / Control**：CodeID、调用、循环、分支、调度、stream 顺序；
- **Σ / State**：Python 对象、Tensor、storage、逻辑版本、module/RNG/环境状态；
- **A / Action**：带多标签的实际动作及其 effect；
- **R / Resource**：CPU、DRAM、pinned host、GPU/HBM、stream、文件和设备；
- **Q / Contract**：结果、状态、副作用、异常、随机性、数值误差和顺序必须保持什么；
- **M / Measurement**：duration、执行次数、传输字节、内存、利用率和测量可信度。

关键身份不能混用：

- CodeID 标识源码和代码版本；同一个函数的 100 次执行只有一个 CodeID；
- InvocationID 标识一次真实动态调用；
- ObjectID 是 Python 对象身份，不是数据内容身份；
- StorageID 是底层分配/存储身份，必须考虑 view、alias 和地址复用；
- Region 是 storage、offset、shape、stride、dtype 的几何区域；
- LogicalValueID 标识逻辑 lineage，ValueVersionID 标识其某个版本；
- ProvenanceID 记录生成/变换的输入和状态来源，不能由内容 hash 代替；
- 一个逻辑版本可以有 NVMe、DRAM、pinned host 和 HBM 等多个 Materialization。

LogicalValue/version 不依赖 storage 命名；同对象可以有新版本，不同对象可以在
有 copy provenance 证明时表示同版本。同 storage 的多个 view 保留各自 Region。
普通 transform 通常产生新的 derived value；不同表示等价也需要明确的关系证据。

SCAR 不把 `Tensor._version` 当作通用正确性基础。v2 registry 保留独立 logical
lineage、版本和物理 materialization，foreign writes 未被闭合时仍需要验证。
v1 runtime guard 的 storage epoch、前缀和显式完整比较只是兼容路径，不自动
为 v2 生成跨调用 logical equality 或 identity 证明。

Tensor 不一定应该保持不变。循环中的状态、优化器参数、候选 action、RNG
和环境观测本来就可能每次迭代改变。SCAR 只把“同一个 logical version”视为
可复用的输入；检测到写入或版本改变时，旧候选必须失效。静态图会把赋值、
原地写、循环控制和读写槽标出来，动态图再用实际 storage epoch、Region 和
effect 完成判断。以后可以在这个模型上增加收敛提前终止：对被声明为可提前
停止的循环记录相邻版本的范数/相对变化、重要性和置信度，并把终止条件作为
Q contract 验证。v0.1 不会把“变化变小”自动当作“可以停止”，因为这属于
近似语义和高级 contract。

## 4. 从 trace 到决策的完整流程

```text
Program → Semantic Graph
             ↕ typed correspondence
          Execution Evidence
             ↓ region interfaces + provenance + evidence references
          Optimization IR
             ↓ fixed proof obligations / Q / guards
          Cost-aware plan → precise modification guidance
             ↓ later transformation/validation stage
          Backend → layered validation → clean measurement
```

每一个候选都必须经过以下阶段：

1. **Observed**：实际运行记录了什么，包含事件、对象、版本、设备和测量。
2. **Inferred**：由静态结构或严格可重复的签名推导什么；推导证据不会冒充物理 runtime event。
3. **Proposed**：检测器提出可能的重复、驻留、延迟 materialization、循环不变量等候选。
4. **Proof**：逐项检查读写、别名、逃逸、随机性、异常、状态和顺序。缺证据是 `UNKNOWN`。
5. **Cost**：把 lookup、guard、同步、额外内存和原始工作放进同一个测量模型。成本未知不能接受。
6. **Decision**：
   - `TRANSFORM`：所有必需证明和成本都通过，选择一个 backend；
   - `REJECT`：有明确证据证明当前变换非法或不划算；
   - `UNKNOWN`：候选看起来存在，但证据不足；
   - `KEEP`：检测到的模式不适用，保留原执行。
7. **Validate**：至少比较区域结果、固定 solve、一次调用和完整 episode 这四层中的适用层级。
8. **Measure**：用无插桩 clean benchmark 重新测量。trace/profiler 时间不能当作最终加速比。

原始执行永远是一个合法的 NO-OP fallback。SCAR 不会因为找到了候选就强制改写程序。

## 5. 面向用户的操作/数据图

v2 的 OperationDefinition 可沿 children 下降，实际调用由独立 Instance 表达；
数据是 ValueSlot/LogicalValue/Version/Materialization 的一等实体。人读的视图
可以把它们折叠为 operation 之间的数据边；证明层必须保留完整身份与端口。
静态定义、真实实例和优化 region 不混成同一个 Action 节点。

保留的 v1 `ProgramGraph` 另提供 `operation_view()` / `write_operation_json()`
投影，供读取旧报告：

```text
operation(function/op) ──reads──> data(State/LogicalVersion/Region)
        │                         ▲
        ├──writes─────────────────┘
        ├──data_depends──> operation
        └──children──> nested operation/function
```

投影中的 operation 节点包括广义函数、调用、表达式、控制节点和动态 action；
data 节点包括变量、对象、Region、LogicalVersion 和 materialization。边的
主要语义是 `reads`、`writes`、`data_depends`、`overwrites`、`aliases` 和
`materializes`。`children` 来自静态 AST containment 或已观察的调用控制，
因此可以从一个函数递归展开，而不必把整个程序压成一张没有边界的平图。

例如：

```bash
scar model path/to/program --out program.graph.json
scar analyze trace-dir --operation-out operation.graph.json
```

当前 v0.1 的候选分析同时使用完整证据图和这个 operation/data 投影：投影
让化简目标清楚，完整图负责检查资源、合同、测量、别名和不确定性。

## 6. v1 opt-in backend 的“标准模块”是什么

“标准模块”不是类名包含 `Linear`，也不是 `.eval()` 就等于纯函数。它是 SCAR 针对某个库版本审核过的**精确类合同**：

- 当前 v0.1 opt-in runtime backend 只接受 `torch.nn` 的精确内置类，例如 `Linear`、卷积、确定性激活、`LayerNorm`、pooling、`Flatten`、`Identity` 等；
- 不接受用户自定义 subclass，即使名字相同，因为 subclass 可能覆盖 `forward` 或加入隐藏状态；
- 不接受 stochastic layer、训练态状态更新、hooks、启用 autograd 或未知表示；
- 运行时仍检查输入、参数/buffer、RNG、输出别名和返回表示；
- 第一个重复 key 会执行原始实现作 probe，验证结果和 guard；后续 hit 还要经过成本闸门；
- 测得 cache lookup/guard 不比原计算便宜时，模块会被禁用并回退原路径。

因此标准模块是一个可审计的 library contract，不是 LeWM 规则，也不是对任意自定义模块的猜测。自定义模块保持原执行并在报告中说明原因，未来可以通过显式 contract 扩展。

## 7. v1 高效的 Tensor guard 与 v2 证据范围

SCAR 不在每次迭代保存完整 Tensor 数值。runtime reuse backend 使用两级 guard：

1. 每次调用只计算 shape、stride、storage offset、dtype、device、conjugate/negative 标志和最多 8 个逻辑前缀元素；
2. 只有快速指纹相等，才核对缓存条目保存的首份逐字节快照；
3. 首份快照只在一个新缓存 entry 建立时保存，不会为每次迭代复制一份；
4. 参数和 buffer 默认使用 SCAR storage epoch；已观察写入直接使缓存失效，不复制每个模块参数；
5. 指纹相同但中间元素被外部写入时，第二级精确核对会拒绝旧缓存；
6. GPU 上的样本和精确核对可能同步设备，因此成本测量包含 guard 开销，不能用理论节省替代实际 A/B。

这个策略实现了“先便宜筛选，只有 shape 和前缀相同才细查”，同时没有把少量样本误当成完整正确性证明。

v2 常规观察不复制 tensor 数值；exact checkpoint 独立 opt-in、受预算约束，只能
证明该 capture 时刻的内容。历史 event 和跨层等价仍需独立连接与 guard。

## 8. 如何解释“1,465 个候选全部拒绝”

早期报告中的 `candidate.decision="rejected"` 是检测器的历史字段，含义混合了“已证实不合法/不划算”和“当时信息不足”。它不能单独代表最终简化结果。

现在报告同时给出：

- `detected_opportunities`：所有检测器候选总数；
- `detector_decisions`：检测器原始字段，向后兼容；
- `simplification_decisions` / `authoritative_dispositions`：规划器最终的 `TRANSFORM/REJECT/UNKNOWN/KEEP`；
- `action_inventory`：程序中所有动态 Action 按 family 的覆盖和处置。

早期 v1 planner 归档给出 1,571 个 `UNKNOWN`、959 个 `REJECT`、0 个
`TRANSFORM`；它们不是原始 event 数。后续独立审计在既有 LeWM trace 上统计
960 个 intervening-write blocker 和 1,568 条 evidence-gap record，分析单位不同
不能当作同一候选总数相加。真实 trace 输入共 45,888 条记录。
这些记录不证明 LeWM 没有可避免工作，也不表示 SCAR 已完成自动化简。

## 9. 当前 LeWM 证据边界

已完成并可复核：

- 在不修改 LeWM 仓库的情况下成功运行 baseline；
- 采集 module/Torch/CUDA/Python/call/transfer/resource 证据；
- 建立静态项目图和动态执行图；
- 验证 same-stream ordering、storage epoch、fork/thread 身份隔离和 loop back-edge 记录；
- 在通用 micro workload 上验证 exact reuse 的正确性、输入原地修改、NumPy alias、隐藏状态、随机性和输出 alias 守卫；
- 运行了通用 opt-in PyTorch backend 的原型成本闸门。

尚未声称完成：

- 尚未得到可信的 LeWM clean A/B 加速比；
- 现有 LeWM trace 中没有足够证据让通用 backend 合法改写完整 episode；
- 复杂自定义模块、autograd、外部进程、跨 stream happens-before 和动态 Python 反射仍然是 UNKNOWN 或 fallback；
- 全程序“所有可避免操作”的完备证明不可能由 v0.1 的一次 trace 自动得到，必须通过更多观察、contract 和 backend 逐步扩大覆盖。

详细的有效/无效实验记录见 [EXPERIMENT_RECORD.md](EXPERIMENT_RECORD.md)，当前实现状态见 [STATUS.md](STATUS.md)。

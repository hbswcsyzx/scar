# 运行证据工具调研：现成能力与 SCAR 的边界

2026-10-16。只读调研、独立小 CPU 探针；未改产品/共享规范/LeWM，未安装或升级。
检查了 workspace/worktree 的适用祖先路径，没有发现适用于本目录的 AGENTS.md。

## 1. 结论与可复用分工

**应复用 torch.profiler/Kineto 获取实际活动，优先验证并接入已有
ExecutionTraceObserver 的 op 输入/输出元数据，而不是重新写 PyTorch operator 图
采集器。** `sys.monitoring` 提供 Python 控制事件；SCAR 承担来源/动态 occurrence
对应、状态/逻辑版本、效果/合同、资源生命周期及依赖闭包。它们是互补层，不是三套
互相替代的“整程序图”。

| 组件 | 复用的现成事实 | 不能由它单独给出的结论 |
| --- | --- | --- |
| torch.profiler/Kineto | 每次 CPU op、runtime/device activity、内存事件、输入描述、来源栈和关联字段。 | 所有可能路径、Python heap 状态、逻辑值版本、纯性、合法 hoist/reuse。 |
| ExecutionTraceObserver（ETO） | RecordFunction op 层次、输入/输出、shape/stride/type/device、Tensor/storage 标识和 schema。 | 整程序语义；跨复制统一逻辑身份；外部 alias mutation 覆盖；完整控制/效果；每节点物理时间。 |
| sys.monitoring | 实际调用/进入/返回/异常/分支/指令/挂起恢复等解释器事件。 | 完整 call 参数/求值栈、任意内存写、C 函数结果或 native 内部/GPU 活动。 |
| Nsight Systems | 可选系统级 CUDA/NVTX/OS 时间线及独立参考。 | Python 逻辑状态与变换合法性；不能用 GUI 可见箭头替代模型证明。 |
| Perfetto Trace Processor | 可选现成 trace 解析、SQL 查询、slice/flow/counter 分析。 | 程序正确性、逻辑版本和自动化简规则。 |

PyTorch profiler 是现成的观测入口，Kineto 是其 CPU/GPU profiling 依赖；无需自造
CUPTI 框架。[Kineto 官方仓库](https://github.com/pytorch/kineto)

## 2. 实际版本和证据

- Python：本机 CPython **3.14.7**；Torch **2.13.0+cu132**，CUDA build **13.2**。
- `torch.version.git_version=cf30153c4c131c8164ee7798e5022d810682e2cb`。
- SCAR 只读审计 HEAD：`d5311a63211470500c6892af484f500e71c0d61f`；相关 source SHA
  在 `analysis.json`，不是声称主分支已实现新 collector。
- 探针 `probe.py` → `probe.json`、`execution-trace.json`、`chrome-trace.json`；exit 0。
  CUDA `is_initialized()` 前后均 false。stderr 的 ETO enable/disable 和 profiler
  start/stop 是实际输出，保留在 `probe.stderr`。
- 探针只用小 CPU tensor/临时实例和本专属目录的小文件；没有 Tensor 全量数据 dump。
- 官方对应 commit 的两份 C++ source 下载至本目录，URL/SHA/bytes 见
  `official-source-manifest.json`；installed profiler.py 的 SHA 在 `probe.json`。

复现（worktree 根目录；不应对正在使用的证据文件重复执行覆盖）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/tooling_survey/runtime/probe.py
python artifacts/experiments/tooling_survey/runtime/analyze.py
```

本轮没有 GPU 因果/实际 copy 实验，也没有干净性能 benchmark，不能据此报告 GPU
覆盖、采集开销比例、加速比或 LeWM 变换。

## 3. ETO 的直接收益：已有 op graph 和元数据

**Observed**：本机 schema `1.1.1-chakra.0.0.4`，36 节点，其中 34 个 op 与两个
process/thread 结构节点。每节点有 `id/name/ctrl_deps/inputs/outputs/attrs`；
inputs/outputs 分列 `values/shapes/types/strides`，attrs 含 `rf_id`、`op_schema`、
thread/forward/sequence 等。`ctrl_deps` 是实际记录层次关系，不是完整 Python CFG。

本机与官方对应 source 的 Tensor tuple 含义如下：

| 槽 | 含义 | 不能当成 |
| --- | --- | --- |
| 0 | TensorImpl 指针经 observer map 分配的 ID。 | Python ObjectID、逻辑数据版本。 |
| 1 | 底层 `storage.data()` 指针经同一 observer map 得到的 ID。 | 带 generation 的 AllocationID 或 StorageImpl `_cdata`。 |
| 2 | `storage_offset()`，按 tensor 元素单位。 | 字节 offset；要按 itemsize/实际 layout 解释。 |
| 3 | numel。 | 分配容量或 view 实际独占字节数。 |
| 4 | itemsize，字节。 | 全 storage 大小。 |
| 5 | device 字符串。 | 完整设备/context/lifetime 身份。 |

dtype/type、shape、strides 另列，不能凭六元组单独重建所有表示。符号大小或无 storage
时 source 使用缺省描述；解析器需保留适用范围。此类元数据及 op schema 可直接复用，
不需要 SCAR 从函数名字再猜 view、分配和 schema alias。具体读取实现见
[对应 commit ETO source](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp)。

**Observed**：`t()` 输入 `[12,9,0,4,4,"cpu"]`、输出 `[16,9,0,4,4,"cpu"]`；
新 Tensor ID、共享 storage ID，stride 从 `[2,1]` 变 `[1,2]`。两次 `add_` 之间已有
内容写入，但 self tuple 都是 `[19,20,0,4,4,"cpu"]`。因此同 tuple 不证明不变；
同 storage 不证明相同视图或相同内容版本。完整实例见 `analysis.json`。

**Inferred from source, not a lifetime experiment**：ID map 用 pointer 作 key，未提供
独立 free/重用 epoch；SCAR 不能据它归并 allocator 地址复用后的对象。两个 observer
session 的这些数字也无统一身份。应导入带 capture scope 的观测标识，另建立有依据的
Object/Allocation/Region 对应。现有 SCAR TensorObserver 的 storage token 是
`untyped_storage()._cdata`，不能与 ETO tuple 槽 1 裸数字相等连接。

### 3.1 ETO 不提供什么

**Observed**：普通 Python 函数、dict counter 写入、Path.write_text、NumPy 原位写均
没有 ETO op 节点；它们确实执行了。`with_stack=True` 的 Kineto Chrome 可见该普通
Python 函数和 write 的 span，但 span 本身没有恢复其 heap 写/文件版本/所有输入。
没有执行的分支更不会在这次动态图中出现。

ET 节点未包含逐节点 `ts/dur`；本文件只有整体 start/finish，不能当 GPU kernel 或
copy 完成时间。RecordFunction scope、模块调用、ATen dispatch、kernel 是不同层。
ET 可以做 replay/simulation 的已有工作负载表示，不是全程序 Semantic Graph/OIR。

## 4. CPU → runtime → kernel/copy：关联和时钟

### 4.1 本轮已经测得的 CPU 连接

**Observed**：34 个正 ETO `rf_id` 与 Chrome 34 个 CPU op 的 `Record function id`
逐项同 ID/同名匹配，零重复正 ID；两结构节点 `rf_id=0`，必须排除。
这比“时间邻近/名称相同”更有依据，优先作为 ETO↔Kineto adapter 的待验收路径。

`rf_id` 来自 RecordFunction handle；对应 source 用 process 内 static atomic 计数，
需要 ids 的 callback 才分配 handle，不是全局永久 ID。[RecordFunction source](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/aten/src/ATen/record_function.cpp)

**Proposed parser 条件**：只在确认同 run/process、同 producer/build 及可对应 capture
window 时配对；保留原始 node/event 引用。缺失/0/重复/冲突 ID、window 只覆盖一侧、
observer start/stop 跨未闭合 scope，均不得靠名称或重叠时间补配。一个关联键应对应
受验证的动态 record occurrence，而不是某 CodeID。process fork、重启和 trace 合并
需重新 namespace；counter 当前实现不保证任意合并文件间无冲突。

### 4.2 GPU 连接是现成能力，但本轮未实测

本机 `torch/autograd/profiler.py:_parse_kineto_results` 已使用 correlation 与
linked_correlation 字段关联 CPU frontend、device runtime 和 device activities，并
区分 async/legacy fallback；动态 FunctionEvent 还暴露 flow/external/structured shape/
stride/dtype 等属性。应先复用此关系及 raw Chrome IDs，避免自己重新实现按时间猜图。
代码参照[对应版本 profiler.py](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/autograd/profiler.py)。

GPU collector 必须单独验证：一 CPU op 可提交多 kernel/copy，一 kernel 可不在所有
capture 窗内；copy bytes/方向、stream/context、runtime activity 和 launch 关联需要
保留。关联到提交 op 不等于逻辑版本已证明，也不等于 host 返回时设备结果 ready。
跨 stream wait、source borrow、目的物化有效区间仍按 SCAR 资源模型验证。

**Clock 边界**：Chrome 的 `ts/dur`、`baseTimeNanoseconds`/displayTimeUnit，SCAR
`perf_counter_ns`，ETO 整体 steady-clock timestamps 不应直接混成一个 ns 时间轴。
导入要保存 producer、原单位、clock domain、转换依据；优先 ID/因果关联。时间早晚或
区间重叠本身不能证明“这个 Tensor 发生了这次 copy”或合法 happens-before。

## 5. sys.monitoring：复用事件系统，不自造解释器

官方 API 已有 PY_START/RESUME/RETURN/YIELD、CALL/C_RETURN/C_RAISE、branch/jump、
instruction 与异常事件；支持 code-local 激活与位置 DISABLE，3.14 新左右 branch
事件和清理 tool API。[Python 3.14 sys.monitoring](https://docs.python.org/3.14/library/sys.monitoring.html)

**Observed**：独立小 probe 在两个 code 上启用局部事件，得到 2 PY_START、22
INSTRUCTION、2 CALL、2 PY_RETURN、1 BRANCH_LEFT、1 C_RETURN；finally 释放工具。
这里只保存元数据，没有 frame/应用对象长期引用。

- CALL/C_RETURN/C_RAISE 的参数只有 code、offset、callable、arg0；**C_RETURN 不给
  C 函数实际返回值**，arg0 不是 retval。完整 actual tuple/kwargs 仍需别的受约束接口。
- PY_RETURN/PY_YIELD 可给该次 Python payload；PY_START 等不给 frame/完整 locals。
  INSTRUCTION 给位置，不给任意求值栈。不能据此宣称已捕获每个表达式的真实值。
- callback 没有规范 timestamp/thread 字段，采集器另记时钟/线程/顺序；C/native/GPU
  内部不因 Python CALL 可见就变成已展开。
- 本地预算、DISABLE、过滤、工具冲突、未启用事件和回调异常都要记录为范围缺口。
  不观测某事件不证明该行为从未发生。全 instruction 跟踪不是零开销默认选项。

## 6. SCAR 当前已经复用了什么

以下为本次实际读代码，hash 见 `analysis.json`，不是拟议能力：

| 当前文件 | 已有复用/适配 | 明确缺口或保留边界 |
| --- | --- | --- |
| `scar/trace/inject.py:166` | 使用 torch.profiler，shape/memory开启，导出 raw Chrome；没有重写CUPTI。 | 默认 with_stack=False；初始化失败会停用profiler，输出失败仅debug打印，需结构化可用性/缺口。 |
| `inject.py:208` | key_averages作为aggregate统计，明确无InvocationID。 | 不能把aggregate当每次CPU op；动态raw CPU op目前未完整导入统一IR。 |
| `scar/trace/cuda.py:69` | 解析Kineto kernel/gpu_memcpy/runtime barrier，保留correlation/external_id与kineto clock。 | CPU frontend↔runtime关联未完整导入；logical Tensor mapping另缺依据。 |
| `cuda.py:11` | 方向/字节唯一signature尝试关联host transfer，明确Inferred/AMBIGUOUS。 | 唯一签名仍不是证明；normalize_v2已标legacy signature match unresolved，不能用作逻辑身份授权。 |
| `scar/trace/call_edges.py` | 复用sys.setprofile获取frame call/return，有限元数据与weakref代次。 | return event不普遍证明正常无异常，预算/未知退出不应丢弃；不是全解释器值追踪。 |
| `scar/trace/call_operands.py` | 已用sys.monitoring CALL/INSTRUCTION、code-local windows、DISABLE与工具冲突检查。 | 完整kwargs/栈/动态派发/未进入目标仍可缺，不能以call attempt替代body entry。 |
| `scar/trace/operand_bytecode.py` | 使用标准dis/code信息定位有限call窗口。 | 这部分是SCAR对应适配，不应扩成另一个通用Python解释器。 |
| `scar/trace/inject.py:57` | 包装Module._call_impl和Tensor.to/cuda/cpu，opt-in TorchDispatchMode。 | Python包装有额外开销、异常路径和覆盖边界；ETO可减少重复operator元数据采集，仍需验证Py对象对应。 |
| `scar/trace/values_v2.py` | tensor描述+weak storage生命周期桥接provenance registry。 | 不是native/NumPy所有写的监控；storage descriptor不等于逻辑不变。 |
| `scar/trace/resources.py` | 复用/proc与nvidia-smi采样CPU/GPU资源。 | 采样GPU利用率不是kernel归因或优化合法性；device-wide值不是本进程独占用量。 |

`rg` 检查整个 `scar/trace` 没有 ExecutionTraceObserver 接入。因此新增 ETO adapter
是复用未接入的现成能力；不是继续发明另一个 op input/output collector。

## 7. 开销、内容采集与缺失行为

本机 profiler.py 明确说明 shape/stack 增加开销，record_shapes 会暂时保留 Tensor
引用，可影响依赖引用计数的优化并引入额外 copy。**metadata-only 不等于零开销或
不扰动生命周期。** clean benchmark 与 instrumented run 必须分开。
源码依据[对应 profiler API implementation](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/profiler/profiler.py)。

ETO extras 可收集生成 kernel/整数 tensor 数据；整数 range 选项还可执行 aminmax/
item。集成必须明确关闭数据/range采集，不能只调用
`set_extra_resource_collection(False)` 就宣称不可能读 Tensor 内容。对应 source 对
`ENABLE_PYTORCH_EXECUTION_TRACE_SAVE_INTEGRAL_TENSOR_RANGE` 使用“存在性”开关，
设为字符串 `0` 仍存在。应在隔离子进程启动时验证/清理这些特定 flags，并保存采集
合同；本次分析进程这些 flags 未设置，probe未生成数据extras。

记录窗口、未进入scope、source failure、symbolic tensor、callback异常、进程异常
退出/文件未finalize、profiler post-processing timeout都可造成缺失/部分结果。
本机版本的 timeout 文档和实现明确允许返回 partial events。应导入原始可用性事实，
计入覆盖；不能把JSON能解析或没有事件当“这段程序没有工作/状态/副作用”。

## 8. 可复用与必须自研的界线

**复用**：PyTorch动态op输入/输出/schema、runtime/device活动/相关ID、Python事件
机制、现成source/symbol/dis接口、可选现成trace查询引擎。现有raw Chrome里已经
有的动态CPU事件应先适配，而不是再次执行目标采同一信息。

**SCAR仍需实现**：独立身份域/epoch与动态对应；规范 ordered use/state/control
图；外部 alias/写覆盖；跨copy/transform的逻辑来源；资源借用、ready、异常/部分状态；
source/static定义与动态轨迹连接；观察合同、区域依赖闭包、合法性/成本及具体修改指导。
这些依赖不能由ET重复节点、op_schema一条alias标记或profiler时间统计代替。

**建议下一步（Proposed，未改代码）**：先以小CPU适配验证ETO+Chrome的rf_id scope/
唯一性/缺失与schema，直接导入已有数据。随后在单GPU小case验收CPU→runtime→copy/
kernel关联和窗口截断，不跑全LeWM重profiling来替代adapter验证。确定最小采集组合，
只在现成证据不能覆盖的来源/状态端口加有限观察；不要同时默认开启所有层的重插桩。

Nsight可作为可选独立参考；当前 `command -v nsys` 无输出，仅说明当前PATH不可用。
没有安装/运行。其官方说明的CUDA/NVTX/OS tracing可复用，不要求内部IR依赖GUI。
[Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)

Perfetto可复用解析/SQL与trace查询；本轮未安装其Python包/二进制或启动下载器，
后续是否采用取实际大trace解析成本。它不会生成SCAR逻辑状态或化简权限。
[Perfetto Trace Processor](https://perfetto.dev/docs/analysis/trace-processor)

# 完整程序类型复核：加载模型、推理、保存视频

日期：2026-10-16。状态：**独立只读设计审查，不是新能力验收。**

SCAR 基线 `8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`；LeWM 工作树
`/home/zyf/AAA/le-wm`，捕获证据记载其提交为
`f70fed80288462ca4d006cb3607ec6da6eaa851f`。本次只读源码和既有小型报告，未执行
目标程序、未启动新分析、未改输入。新 `STRUCTURED_BODY_V1` 仍是 Proposed。

## 1. 对“四类”的确定判断

**完整 SCAR 图不是只有四种类型。** `Operation / Value / StateLocation / Region`
是 Program core 的四个结构家族。它们不替代 Value 的不同类型、操作协议、完成
接口、资源身份、动态实例、存储布局、来源证据和变换合同。

从下面的实际路径没有发现必须新增第五种 **Program core 顶层结构家族** 的
反例：句柄可用强类型引用，状态可用带 owner 的 location/version，完成条件可用
有 producer 与 scope 的强类型 completion value/port。但是，这不等于现有四个
Python 类已经足够实现全过程。当前 core 只实现其中很小一部分；例如没有完整
的文件句柄/编码器协议、typed GPU readiness 或 function environment 端口。

**Execution/physical 层已经且必须有额外一等实体。** Resource、StorageAllocation、
StorageRegion、Materialization、OperationInstance、Observation，以及需要补齐的
typed execution event/stream/lifetime 不能挤成四个 action label。若产品界面展示
所有层，应显示这些类型。OIR 的 OptimizationRegion、port、delta、contract 与
evidence 也不是 Program Region 的别名。

新增类型的标准是可验证的身份、合法边和不变量。若后续发现完成、外部交互或
环境无法在上述合同内表达，就应增补类型/实体；不能以维持“四”这个数字为约束。

## 2. 真实源码全过程：可核对的位置与压力

以下是**静态调用/依赖路径**；没有把源码名字匹配声明为某次运行的真实 dispatch。
路径均相对于 `/home/zyf/AAA/le-wm`。

| 阶段 | 源码位置 | 必须保留的类型与关系 |
| --- | --- | --- |
| 启动、环境、动态加载 | `run_inference.py:17–31,45–75` | 环境变量读取、输出目录写、module/function 属性重绑、读取 eval.py 后 compile/exec；代码身份不等于函数实例或 globals 环境。 |
| 配置与数据输入 | `eval.py:49–79`；`stable-worldmodel/stable_worldmodel/data/formats/hdf5.py:91–99,140–143` | decorator/default 定义阶段；配置读取/修改；HDF5 handle、底层文件或 fs stream、offset/close 与数据内容版本。 |
| 模型加载 | `eval.py:87–97`；`stable-worldmodel/stable_worldmodel/wm/utils.py:77–93,104–120` | path/config/checkpoint 读取、可能的远端解析分支、反序列化/构造、model 参数状态写；`.to` 设备/表示变化，`.eval` 与 `requires_grad_` 修改模式状态。未观测到的 HF 分支仍属程序结构，不能声称运行过。 |
| 选择动作/模型推理 | `policy.py:349–434`；`solver/cem.py:145–260`；`wm/lewm/lewm.py:58–108,126–151`（均在 stable_worldmodel 下） | 多层循环、分支、method/instance/kwargs/*args dispatch；RNG state；view/alias、Tensor mutation、缓存字典写、按候选改变的输入；GPU enqueue/ready，autograd/inference mode。 |
| 环境推进与帧来源 | `world/world.py:403–446,448–449,506–550` | `_run_iter` 有 `yield`，不是普通同步完成；`on_step` 是捕获 frames/results/goal_snapshot 的 closure；env step/reset 可写 RNG/外部世界；图像帧来自环境状态与数据集，不只是模型返回 Tensor。 |
| 视频构造与编码 | `world/world.py:555–563`；`plot/video_utils.py:20–64` | 多层 loop/comprehension、字体资源读取、try/except fallback、图像布局与 copy、frame 顺序，最后调用 save_video。 |
| 文件完成与其他可观察输出 | `plot/video_utils.py:8–17`；`eval.py:157–169` | writer 创建、逐帧 append、close/flush 完成；目录/file namespace/content；异常后的部分输出；with 下文本追加与配置/metrics/timing 内容。正常 Python return 不单独证明编码器进程或持久化已完成。 |

其中 `world.py` 的 generator/closure，以及视频路径的 try 和日志路径的 with，
说明只补循环不能完成这条链。只给这些函数一个 opaque Region、标记 IO 或统计
到调用次数，也不能证明其内部依赖已经建模。

## 3. 类型落点和当前证据状态

表中 **D** 是设计可表达，**I** 是类型/校验是否已有实现，**A** 是是否已从原始
源码/观察自动接入当前 ProgramGraph，**T** 是本次已读证据能否支持其完整实测。
“部分”不等于全过程完成；未知记录存在也不算协议已理解。

| 项 | Program / Execution / Optimization 的规范落点 | D / I / A / T |
| --- | --- | --- |
| 输入、输出、常量 | Value 及边界角色；常量/不变量是带范围和版本的事实，不是按输入名字判断 | D 可表达；I 现有 literal/reference/data/ports；A 有限源码子集；T 小程序历史门，非整个 LeWM 常量闭包。 |
| 局部名称绑定 | slot→LocalBinding token；token 区分已绑定/未绑定/未知；不等于对象引用或物理内存 | D 本门明确；I/A 新 profile 尚 Proposed；T 尚无本门结果。 |
| 对象/堆/模块/函数环境 | ReferenceValue identity；StateLocation+StateVersion；globals/defaults/cells 需要 owner/version 与隐式环境端口 | D 可表达；I coarse world/引用已有，精确 environment/cell 接口缺；A global lookup 多为 opaque、closure 拒绝；T 不能声称函数实例环境已证。 |
| 文件、路径、句柄 | path 是值；句柄是引用；file namespace/content、handle position/open/closed 是不同状态域；Execution 有 Resource/lifetime，OIR 保留外部输出和异常根 | D 需要 typed owner/protocol；I ResourceKind.FILE、EffectTargetKind.FILE 已有，但 reference 多为字符串，不是完整句柄协议；A 无本链精确生成证据；T 文件产出不证明模型闭包。 |
| 编码器/序列化器 | 普通对象引用+内部 state；frame Uses 有序；输入字节/图像、codec 参数、外部 handle、flush/close 的成功/失败完成；可有 subprocess/线程资源 | D 同一通用状态/协议形式；I 当前没有完整规范协议；A 调用可被记录，内部读写/完成未知；T 只见视频产物/调用捕获，未证内容与完成依赖。 |
| RNG | generator owner/reference 与 RNG state location/version；抽样消费旧状态并产出新状态，seed 是一次状态写 | D 可表达；I legacy RNG effect 类别已有；A 本源码 core 多为 unknown world；T 无跨调用精确 RNG state 闭包。 |
| Storage / view / Materialization | Program 的逻辑引用/内容版本和 selector；Execution 的 Allocation、StorageRegion、Materialization，有 typed join；OIR 保留 alias/overlap、生命周期、设备/表示要求 | D 已设计；I `v2/values.py` 有结构，`provenance.py`/`normalize_v2.py` 有构造路径；A 在旧观察链部分可生成，未与当前完整源码 core 接通；T 不能把既有存储观察测试算成本次 LeWM 跨层证明。 |
| CPU/GPU/stream/resource | Program 操作带实现需求/可观察状态；Execution 的 Resource 与实例、stream、device、thread/process、allocation 是一等身份 | D 已设计；I ResourceKind 与 legacy records 存在；A 部分 trace 归一化；T 本门 call capture 不能证明 stream 或资源依赖完整。 |
| Async completion / readiness | Program 的 issued/ready/failed/cancelled 等 **typed** completion value/port 与等待/消费边；Execution 的 producer/event/stream/time scope；OIR 保留 happens-before | D 必须可表达；I 当前 program INVOKE 只有 NORMAL/RAISE，legacy Materialization.ready_event 是 `str | None`；A 尚无完整统一构造；T GPU fixture 成功或 host return 不能代替 ready 证明。 |
| Autograd/mode | 版本化模式状态、求导连接、detach/view 与引用关系分离；Execution 记录实际模式与图关系；OIR 约束值、梯度和副作用 | D 有要求；I 当前 core 无完整接口；A `.detach/.eval/inference_mode` 仍不能靠名称当协议；T 未证明。 |
| 外部环境/交互 | 文件系统、进程环境、设备、仿真/远端状态与日志历史；external location/version + observable interaction order；未知别名不得按不同 ID 判不交 | D 可保守表达；I coarse world 与 legacy EffectTarget 存在；A 粗粒度部分；T 未达到必要依赖最小化。 |
| 异常/cleanup/生命周期 | pending completion、payload、postworld；try/finally/with 的控制替换/suppression；frame escape/unraisable/非保证 free | D 已有有限规则并需扩展；I 普通 BOUND_FRAME 已实现，try/with/generator 未覆盖；A 仅旧支持子集；T 当前真实全过程尚不支持。 |
| OIR 子图化简 | 从已连接程序/实例中选区域，显式 inputs/outputs/state/order/observable roots、contract、rewrite delta、证据和成本 | D 有旧 OIR 设计；I `v2/optimization.py` 有 records/validators；A 尚无本链完整 state/use 改接闭包；T 未授权变换，无 LeWM 加速结论。 |

现有资源/物化类型的代码证据：`scar/ir/v2/contracts.py:EffectTargetKind,ResourceKind,
ResourceRequirement`；`scar/ir/v2/values.py:StorageAllocation,StorageRegion,Materialization`；
`scar/ir/v2/evidence.py:OperationInstance,EvidenceNodeKind`；
`scar/ir/provenance.py` 和 `scar/trace/normalize_v2.py` 的构造位置。
这些是具体已有实现，不是“完整 Program core 已接通”的证据。

## 4. 保存视频和保存 Tensor 的共性及不可省区别

不需要 `SAVE_VIDEO`/`SAVE_TENSOR` 两个业务 node kind。两者都可展开成输入引用与
内容读取、表示转换/编码、外部写入及完成协议。相同结构不代表效果可省略：

- serializer/encoder 会读取内容，不能只依赖对象 identity。相同 tensor 引用被
  原位改写后再保存，内容来源不同；view 需要保持 storage overlap。
- encoder 可缓冲多帧：每次 append 的顺序、状态版本和最后 close/flush 都会影响
  输出。省略 close 与仅保留最后一次 append 不是等价化简。
- path 同字符串不保证同一个文件对象；rename、symlink、不同 cwd、并发写入会
  影响解析。反之不同句柄可能指向同一文件，不能按不同 handle ID 证明不相交。
- 失败可能留下部分文件、写入日志、启动进程或保留句柄。正常/异常/清理三者不能
  只用“函数返回 None”合并。

以上由通用协议/类型和实际 resolved target 的证据决定，不按 LeWM 函数名字、
路径或“video”字符串添加特殊规则。

## 5. 必需的全过程反例与下一门顺序

1. **G0–G2：core/结构基础。** 新 binding 类型→正确循环 CFG→逐 call/ordered Use。
   `for x in xs: use(x); return x` 零次不能假装 None；`leaf(shared, shared)` 两位置
   不能合并；未知控制子树不能计作内部 call covered。
2. **G3：公开自动构图与精确来源连接。** 同一原始入口/raw archive→全局 source
   scope/body queue→新 profile→strict replay→逐阶段 coverage。模块初始化、
   definition-time inputs、comprehension 的 lexical/execution owner 必须保留。
   这是结构门，不是全过程语义门。
3. **G4：真实控制/环境/跨调用闭合。** generator suspend/resume/close、closure
   cell、finally 替换 payload、with suppression、receiver/default/kwargs/pack 失败
   阶段、动态 loop occurrence。`saved_frame`/finalizer、同 code 不同环境不得串线。
4. **G5：外部与物理依赖闭合。** checkpoint/config 读取、model state 写、RNG、
   alias/representation、GPU ready、dataset/environment、encoder/file/append/close
   有 typed 连接；同引用不同内容、不同 stream、部分写失败、无 close 反例必须
   阻止错误删边。未知 leaf 必须保留边界而不能宣布协议已完备。
5. **G6：依赖查询与 OIR。** 从视频和 metrics/log/file 状态、异常/顺序根自动回溯
   到帧来源、环境推进、推理、模型参数和加载输入；含未证条件的切片不能授权
   删除/复用。仅在特定区域的实际依赖与合同闭合后验收具体改写，不新增 backend。

真实 LeWM 的验收分母必须覆盖启动/加载、数据准备、推理/环境推进、视频/文本输出
四阶段，逐阶段列 source Call、core Call/Use、已匹配动态 call、状态/完成边、
尚未解释边界。任何阶段为 opaque shell 不能用总体覆盖率掩盖。结构完整、语义
精度、执行对应、变换权限分别出结果；没有达到后两门就不能称完整可化简依赖图。

## 6. 本次可报告和不可报告的实测

读取的 windows capture summary：目标 exit 0，312,812 sidecar events，100,550
attempts，4,069 handshakes，945 `PROJECT_FUNCTION_CALL_DID_NOT_ENTER` gaps，0 drops；
目标源码未改。该报告标记 NEEDS_READER_REVIEW，且 whole_program_complete 与
transformation_authorized 均 false。离线分析 progress 仍为 RUNNING。

这证明目标全过程运行及记录器产生有边界的观察，**不证明上述类型全部已自动
建图、不证明数据/状态依赖闭合、不证明没有遗漏 GPU/编码器异步效果，也不证明
任何 LeWM 加速**。本审查没有生成新的运行结果。

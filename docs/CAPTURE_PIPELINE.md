# 采集与建模分离

2026-10-27。第一阶段仍 OPEN；本页明确本轮实现边界，不宣称完整 LeWM 图已经恢复。

## 五类实体意味着什么

Operation、Value、StateLocation、Region、Resource 是规范程序模型的顶层结构，
不是所有记录的封闭枚举。调用、分支、读写、分配、搬运、同步、外部交互有不同的
操作规则；输入和输出是端口角色。值定义、对象身份、可变位置和物理资源不能合并。
动态 invocation、value occurrence、allocation/materialization、事件和来源证据有各自
身份，分别连接上述程序定义；不把一次 kernel 事件当成静态函数定义。
这里的 Region 是程序子图；内存访问的 offset/shape/stride/footprint 是另一种
带类型的范围描述，不能因为都叫 region 就混用。

这五类是否足够，应由真实程序的表达和连接验证，而不是由分类数量证明。例如：

| 程序部分 | 必要实体及连接 |
|---|---|
| 从文件读取权重 | 文件 Resource、文件内容 StateLocation/版本、read Operation、字节 Value、CPU 内存物化 |
| 函数中调用 module | 调用 Operation、函数/body Region、逐 invocation 的实参/形参及返回绑定 |
| view 后原位修改 | 引用 Value、共享位置和范围、读写前后状态版本、allocation/view 对应 |
| 异步 GPU 推理 | 操作/Region、输入版本、GPU/stream/allocation Resource、enqueue/work/ready 与消费者顺序 |
| 编码后保存视频 | 编码子图和编码器状态、字节 Value、写入 Operation、文件 Resource、输出状态与完成 |

如果其中的必要依赖只能塞进无约束 metadata，就应修订类型或关系。能容纳一个
OPAQUE 标签并不表示恢复了那个部分。规范见 PROGRAM_TYPES.md、WHOLE_PROGRAM_MODEL.md。

## 现场只记录事实

```text
被观察程序
  -> 事件位置 + 必要的动态身份/绑定快照
  -> 快速冻结为不含应用对象引用的字节
  -> 有界 DRAM 队列
  -> 后台批量写原始日志
程序退出或日志分片关闭
  -> 独立后端解码、校验、静态分析、跨层关联
  -> 分片程序模型及查询索引
```

回调不能做源码 lowering、子图展开、图遍历或完整 IR 验证。源码/code 和静态 ABI
元数据按版本登记一次；动态 dispatch、defaults、receiver、状态变化不能因此省略。
Tensor 不逐次存完整数值，不在采集回调中为构图强制 D2H/synchronize。

不能排队保留 frame、Tensor、任意对象，等后台再读取它们：其状态可能已经变化，
而保留引用本身也改变生命周期。现场必须冻结必要的身份和观测事实；不能观测的
内容或先后关系如实留空，不能由后处理猜成事实。

DRAM 有严格 byte 上限。队列满、writer 错误、fork、异常退出和截断须留准确计数、
范围及 incomplete 状态。禁止静默丢事件后宣布完整。后台 IO 线程必须排除在目标
事件采集之外；fork 子进程不得回放父进程队列。正常 close 要确认 writer 已结束。

线程负责 IO，不声称绕过 Python GIL 加速 CPU 分析。源码 lowering、解码、建图和
关联按关闭的文件/分片送独立进程并行处理，不用一个全局可变图作为收集中心。
暂存编码与规范图存储是两件事；暂存文件绑定实际解释器/格式版本，不作为长期
可移植 IR。

## 当前事实与本轮顺序

- 原 JSONL 模式有 64 KiB 字节缓冲，JSON 编码及部分记录构造仍在回调中。
  新增可选 snapshot 模式：四个主要 observer 的五条流用 marshal C 路径现场冻结，
  五个独立有界队列的后台线程只批量 IO。默认每流 8 MiB（队列合计 40 MiB，另有
  有界单条记录、in-flight batch 和现有身份表）；不保留应用对象来延后观察。
- 采集停止后，独立进程完成每条流的 JSON 编码/结构校验，并在成功后生成原有
  reader 的 metadata。父进程等输出完成，退出时长包含后处理；不属于 clean benchmark。
  原始暂存和规范图格式分开；暂存绑定准确 CPython/marshal 版本。
- 现场执行的是暂存字节上限，原 JSONL 行/总字节上限由离线转换再验证。队列满、
  raw quota 或写入失败的日志标为 incomplete，不能生成成功的旧 reader 输入。
  每条关闭收据记录 SHA、接受/写出数量、拒绝原因、队列峰值和 writer 存活状态。
  转换进程身份标为 SCAR_OFFLINE_POSTPROCESSING，不作为应用调用或资源使用。
- 静态 CALL/layout 缓存已接入；动态 defaults/receiver 仍按事件观察。离线依赖
  分析已使用四个实际工作进程。
- 原 trace 的 2,683 对直接源码候选现已全部发布条件连接，84 个新分片均经普通
  reader 回读；旧 2,672 条逐条相同，新增 11 条为默认/关键字调用 ABI 修复。
  这不是原 100,550 次调用尝试或全程序的覆盖率。旧 84 个连接分片的依赖视图均已有输出，其中 24 个曾因单文件
  解码大小失败，改为逐查询文件后恢复；导航预算截断仍存在。
- 新真实 LeWM 采集 1,801.896 秒触及上限，未完成 episode；原始 11,558,927,174 字节
  经独立回读核对压缩为 908,380,860 字节保留。LeWM 源仓库未改。不能将此失败的
  插桩运行用于原程序性能或完整图结论。

固定字段编码的独立 5,000-call 微负载中，三对交替测量中位 1.047196 秒降至
0.871064 秒，原 TARGET/environment 字节和 operand shape hash 相同；动态 defaults
和 receiver 持续变化。这是特定采集路径约 16.8% 耗时下降，不是 LeWM 加速比。

公开 CLI 的 process-ports + snapshot 真实小程序（主/子线程、变化的 defaults、
交替 receiver）已得到 822 enter/822 exit、1,024 attempts，普通 operand/target
reader 通过且无 observation issue；五条流均接受=写出、无拒绝、关闭后 writer
不存活。早先 JSONL windows 对照有一次 INSTRUCTION_FRAME_UNAVAILABLE，保留其
失败，不能拿不同 scope/Run 的计数比较恢复率。详见本轮实验报告。

```bash
python -m scar.cli trace --out /fresh/trace --project-root /path/to/program \
  --capture-profile process-ports --capture-transport snapshot -- python program.py
```

当前 snapshot 通道覆盖主要 Python 调用流，stream/native provider 还有各自的
采集路径；不是全部 observer 已经零现场处理。图 lowering 和跨层关联仍为后端工作。
新的 LeWM snapshot 采集按原命令执行，冻结源码 7afd39be，源码树 SHA
17f64b651f02e40e500325277d261a7f6542b6cc375e1ae9c237f5fd3cb555c2。
时间、event/per-stream byte 上限与前次相同；总 32GB 上限计入暂存+JSONL双表示，
不是增加调用范围。实际仍在 1,801.807 秒触及 provider 上限退出 241，未完成
初始化/episode，LeWM 原仓库不变；不能把暂存通道改进说成完整采集成功。
原始 snapshot 已纳入失败归档：10,323,514,714 原始字节经四线程压缩并完整
解压回读核 SHA，保留 963,689,027 字节；只有本次生成的原始重复文件在清单发布后删除。

进一步的同初始化 import 前缀诊断只运行 69.248 秒有效窗口：249,693 次 target
on_call 的 inclusive 16.422 秒、913,845 次 Deferred append 的 12.968 秒。它们
包含子调用，不能相加；诊断没有 native/strace/witness，不是原全流程 A/B。
据此，target 内部回调已改成直接记录原始 V2 fields，不构造/验证 InvocationKey、
PythonCallTarget 等 IR 对象；普通 reader 仍完整验证。原有公开 typed emit API 保留。
小方法负载的同进程 wire 对比通过，新的真实 LeWM 全流程尚未验证。

控制异常也必须保留：已修复回调 fallback 中记录错误后吞掉 KeyboardInterrupt/
SystemExit 的 BaseException 捕获。真实 sys.monitoring 小循环在旧版吞掉 self-SIGINT
并继续，新版将 SIGINT 传播给程序；constructor cleanup/原目标异常的重抛路径保持。
弱回调本身的 unraisable 边界单列，不宣称所有异步边界已经恢复。

跨层数据关系新增 `query-native-allocation`：从原 NativeInputRef/ValueOccurrence
及其原端口，经过同 capture/provider epoch，查询原 AllocationTarget；不生成新
逻辑值或 Materialization。公开 CLI 已对真实 `aten::lift_fresh` 的 CPU4B 输入通过，
GPU、内容版本、写入后态和 ready 仍未验证；这不是全图批量接线。

`--derive-region` 可选择静态范围推导。若 pinned valid-strided-Tensor 协议下，
原输入 metadata 与同一 allocation 的基址、extent 唯一限制了 offset，返回现有
StorageRegion 的派生 view。例如原 CPU4B 输入有 4*offset+4<=4、offset>=0，
所以 offset=0。原 observed_storage_offset=None/gap 保留；更大的8B extent 不唯一，
返回 OPEN。这个证明有明确协议假设，不是新观测、逻辑版本或完成/ready 证明。

独立 CPU/CUDA/文件往返样例完成 native+OS 采集后，五个 materializer 的角色已由
同 Run 的父子/exec 来源核对。现有 `import-capture --os-interface-work` 自动发布
角色导航，`model-run` 复用此路径；公开 CLI 对同一原件一次导入 82.647 秒通过，
保留全部65,352条 OS observation，5 positive roles、0 role frontiers/missing receipts。
原事实不被过滤；未分类不等于 application。此小程序不是 LeWM 全程序验收替代。

接下来继续本阶段建模：接本次内容读取/状态版本、跨 copy/transform 的来源与
Materialization、输出同点 region 及资源 ready/lifetime；符号版本与已知数值分开，
不为建模逐次保存 Tensor 内容。copy 方案及原断口见
[read/provenance 方案](../artifacts/analysis/logical_copy_provenance_plan_20261027/PLAN.md)。
端到端仍需同 Run 接通加载、推理、环境和保存，以及逻辑版本、物化、ready/lifetime。
当前不增加 detector/backend，不报告 LeWM 加速比。

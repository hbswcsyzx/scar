# 实际 Python 调用连接原 source/body

日期：2026-10-23。状态：适配器已实现；等待完整 inventory / composition 后实际
运行。**尚未声称通过真实绑定验收，第一阶段仍 OPEN。**

## 1. 职责

`scar.analysis.source_invocations` 连接每一条实际 `call_enter` 与已有自动源码模型。
它不重编译、不重新 prepare 源码、不生成新的规范操作或 root、不复制 Value
producer / StateVersion。调用实例仍使用原 `InvocationKey`，不能按函数名或
CodeID 将多次调用合并成一次。

```text
原 call-codes/events/meta 的完整扫描
    → 原 process/code source witness
    → exact SourceSnapshot + DefinitionID + SourceReference
    → 最终 CallSourceAdmission
    → CompositionIndex 原 definition / 原 canonical body
```

`pycode-v2` 是原采集器的完整结构代码指纹，包含 code、constants、flags、names、
freevars/cellvars、源码位置表等。原 code/source resolver 已比较编译后的完整描述；
本适配器复用这个 witness，**不会自行根据 qualname / first line 猜测等价**。
源码版本相同不表示函数环境相同，更不表示输入、Tensor 内容或模型状态不变。

## 2. API 与输入身份

```python
from scar.analysis.source_invocations import bind_source_invocations

report = bind_source_invocations(
    composition,           # 已绑定原 inventory 的 CompositionIndex
    coordinates,           # 同一次 capture 的 CaptureCoordinates
    trace_directory,
    new_output_directory,
    call_budget=independent_call_budget,
    witness_mode="same_capture",  # 默认；跨运行复用代码来源时显式选 reused_code
)
```

调用方提供独立 `CallEdgeBudget` 上限；source seed report 不能自行抬高它。输入可为
原普通 JSONL 或现有 reader 支持的无损 gzip，不能同时提供同 family 的两种副本。

两种模式都使用现有 `scan_call_trace(..., sink=...)` 完整独立扫描当前原档，核验
当前 metadata、events、codes、原引用协议和计数。默认 `same_capture` 另核对：

1. source seed model 与当前扫描的全部 process/file family 必须一致；
2. 每个文件的原字节 SHA、字节数、行数与完整路径对应必须一致；
3. 每个进程实际捕获的 CodeID、完整 descriptor 与原行 anchor 必须一致；
4. 每个 process/code group 的调用次数、首尾 invocation 和首尾 anchor 必须一致；
5. collector metadata 的原 typed projection 必须一致；
6. final admissions 的分母必须等于原 eligible groups；
7. source/body 引用必须保持 exact snapshot、definition、SourceReference、body root
   与原 canonical graph SHA。

默认模式中，不同旧 trace 与新 source witness 混接会中止发布。不会仅凭 PID、文件名、shape、
时间邻近或 qualname 接线。没有 source witness 的 trace 可以保留原调用清单，但
不能建立 source/body 对应，缺口始终可见。

`CallSourceSeedModel` 只解码结构，不能证明过去真的执行过编译。报告明确记为
`REUSED_CODE_SOURCE_WITNESS`，绑定原 inventory 身份，保留 producer 条件；
`source_recompiled_by_binder=False`。没有调用会重复编译的 `link_calls`、
`CallSourceSeedReport.from_dict` 或 `replay_inventory_from_calls`。

### 2.1 显式跨运行代码来源复用

`witness_mode="reused_code"` 将静态来源证明与动态调用证据分开：

1. 当前捕获的完整 `CapturedCode` 必须与旧 witness 的 descriptor 完全相等，
   完整 `pycode-v2` 也必须相同；只匹配名称、参数个数或位置不够。
2. 原 CodeSourceLink 必须为 VERIFIED，其 snapshot、definition ID、完整
   SourceReference 和最终 body 引用必须与原 CompositionIndex 一致。
3. 使用 `tokenize.open` 只读当前源文件，以原解码文本、通用换行与 UTF-8 SHA256
   规则核验 fingerprint 未漂移。每个 snapshot 缓存一次，保留字节预算、变化检查
   与缺失/漂移 frontier，不执行 parse、compile 或 prepare。
4. 旧 admission 仅作为静态 source/body 收据使用：不拿旧 origin PID 作新进程
   身份。多个旧收据的静态字段若冲突，保留 frontier，不猜选 body。
5. 旧调用组、次数、metadata、entry/exit、线程和 invocation 不用于生成当前
   动态事实。当前全部 invocation 始终由当前 raw scan 输出，坐标只取当前 capture。

新增 CodeID、相同 key 但完整 descriptor 不同、没有原 source witness 等，保留
`NO_MATCHING_CODE_WITNESS`，仍输出该代码的每次当前调用。源码漂移则不绑定该
snapshot 的 source/body。旧 source 的未知部分不会因为复用而变为已知。

报告明确区分 `witness_mode`、`source_witness_raw_manifest_replayed`、完整 descriptor
匹配数与逐文件 `current_source_checks`；不声称本轮重编译。此模式只复用代码来源
证明，不表示复用程序执行、函数环境、值、状态或资源事实。

## 3. 共同执行坐标

先以原文件路径 / 已核验实际路径和原字节确认 membership，再调用
`CaptureCoordinates.process_for(artifact, pid)`，复用已有 Run/ProcessInstance。
当前协议使用 membership.local_path 定位实际 plain/gzip，ProviderArtifact.uri
保持 collector 原逻辑 URI；因此无损压缩/重定位不会重新生成执行身份。旧报告没有
local_path 时，只兼容它原先记录的精确物理 URI，不扩展为文件名或任意路径猜测。
无进程 membership 的额外输入保留 raw fact 和缺口，不偷偷分配当前 Run 的
EvidencePoint，也不按 PID 猜所属进程。

原调用事件只有 Python thread ident。`thread_for(..., "python_ident")` 当前仍为
明确未解析的线程，不能将它等同于 Linux native TID。后续需要实际映射证据。

已关联原 canonical body、进程 membership 明确且不属于 suspended frame 的 entry，
可引用已有 `RegionActivation` 类型。该记录与 body 限定引用一起保存在片段中；
不伪造一个统一 ProgramSnapshot / ExecutionModel，也不声称 actual/formal 已绑定。

## 4. parent 关系与资格分别保存

| 记录关系 | 含义 |
| --- | --- |
| DIRECT_RECORDED_PARENT | 采集器记录 immediate caller invocation；仍须检查实际路径和区间 |
| RETAINED_ANCESTOR | 只有保留祖先，中间可能有未记录 frame；不是直接调用 |
| NO_RECORDED_PARENT | 原事件没有父调用身份；不能自行补成入口 |

每条调用另查：保留栈 top、父/子 CodeID、path 完整性、entry/exit 顺序和活动区间。
缺出口、掉事件、区间冲突、路径不完整、suspended frame 等均保留具体 frontier。
全部匹配时仅给出 `RECORDED_FRAME_INTERVAL_MATCH`，不是 canonical callsite、
actual/formal、返回值或世界状态的证明。

`suspended=True` 的记录是原采集器观察到的一次挂起/恢复边界。本适配器不把多次
恢复猜成同一个普通函数 activation，也不制造 generator frame 连续性。

## 5. 产物与发布

```text
<output>/
├── bindings.json
├── invocations.jsonl.gz
├── orphan-exits.jsonl.gz
└── report.json
```

- `bindings.json` 每个 process/code 保存一次原 witness、definition/body 引用、
  source/body 缺口及尚未连接的接口义务。
- `invocations.jsonl.gz` 每个原 invocation 保留一行：原 anchor、共同坐标、
  binding index、parent 关系及资格、原 completion 观察与缺口。
- 参数、caller locals、return reference 等指回原行字段，不重复保存长引用向量，
  不保存 Tensor 数值。
- 无 entry 的 exit 单独保留，不能静默丢弃。
- `report.json` 绑定输入、输出字节与计数；区分总调用、source/body 关联数、
  parent 关系、资格、未解析项和未连接接口。

扫描回调结果在 metadata 全部核验完成前只是临时状态。整份原档扫描、source
witness 对比与产物构造均成功后才创建独占的新输出目录；先发布数据，最后发布
`report.json` 作为完成收据。失败不会覆盖已有输出，也不发布部分成功的模型。

## 6. 本适配器尚未完成的连接

以下义务在 binding 表和汇总中保持显式未连接：

- actual → formal 有序路由；
- callee exit → caller result；
- 实际 function/defaults/cells/globals/builtins 环境；
- StateLocation / StateVersion 与 visible effects；
- canonical 控制及完成出口；
- Python → Torch operator → native work，以及资源 ready / lifetime。

`BODY_LINKED_REUSED_WITNESS` 只表示这次 entry 可以指向哪一个原 body。它不等于
纯函数、不等于输入不变、不等于可以缓存，也不等于第一阶段完整模型已经成立。

## 7. 待实际验收

根任务将提供 `first_stage_lewm_environment_mounted_20261022/trace` 对应的新 full
inventory 与 composition。同 capture 使用默认模式；附加 dispatch 采集的下一次
运行若复用这份静态证明，必须显式使用 reused_code。届时运行实际绑定，核验：原 entry 分母全部保留、
相同 capture membership、body 原图限定引用、direct/retained 分离，以及所有未恢复
source/body 和接口缺口。当前文档不提前填写或推测成功数量。

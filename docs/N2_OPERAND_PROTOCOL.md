# B1 operand sidecar protocol

日期：2026-10-16。状态：**Implementing；不是完整 B1 验收。**
本协议补充原始 v1 frame trace，不改变它的文件、记录或历史重放规则。
完整交付还要求原始两文件程序自动采集、源码对应和 actual→formal→return 查询。

2026-10-23 的分片接线见 [CALL_SOURCE_ROUTES.md](CALL_SOURCE_ROUTES.md)：复用本协议
及既有精确 CALL/window/handshake 规则，通过原 SourceBodyAccess 与 owned CodeWitness
读取原 CP/端口。新 report schema2 显式限定 namespace，旧 v1 replay 不改义；新接线
当前仅完成 AST/源审查，尚未运行实档验收。

## 1. 文件与身份

每个采集 PID 写入两个独立文件：

- `call-operands.<pid>.jsonl`：有序事件，每条为完整 JSON 行。
- `call-operand-meta.<pid>.json`：关闭原 frame recorder 后写出的 metadata。

reader 同时支持 `.gz`；同一逻辑文件不能同时存在压缩和未压缩副本，不接受 symlink。
schema 为 `scar.call-operands-trace`，版本为 exact integer `1`。

sidecar event identity 是 `(process_id, index)`；load occurrence identity 是
`(process_id, instruction_index, suboperand)`。同对象的两个实参仍有两个 occurrence。
它们不是 InvocationID、静态 ValueID 或对象身份。

原 frame 事件、sidecar 事件各有自己的 index。`frame_index` 只是原 v1 事件序列
的水印，不是 raw anchor。reader 自行从当前文件内容生成 `CallRecordAnchor`；
raw row 不能提供或覆盖 anchor。

## 2. 事件与类型

所有事件具有以下 raw 字段：

| 字段 | 约束 |
| --- | --- |
| `index` | PID 内严格递增的正 exact int |
| `kind` | 下述四种固定字符串之一 |
| `process_id` / `thread_id` | PID 正 exact int，TID 非负 exact int |
| `invocation_id` | 原 v1 invocation 正 exact int；只有 GAP 可为 null |
| `frame_index` | 非负 exact int，PID 内不回退，不超过原 frame attempts |
| `hook_epoch` | 正 exact int，不回退；变更须有 GAP |

事件的其余字段：

| kind / typed record | 字段 |
| --- | --- |
| `INSTRUCTION` / `OperandInstruction` | `site: CapturedSite`, `loads: tuple[LoadObservation]` |
| `CALL_ATTEMPT` / `OperandCallAttempt` | `site`, `dispatch: CallableShape`, `arg0`, `arg0_missing` |
| `ENTRY_HANDSHAKE` / `OperandEntryHandshake` | `attempt_index`, `entry_index` |
| `GAP` / `OperandGap` | `reason`：非空文本 |

`ENTRY_HANDSHAKE` 的 common invocation 是实际 callee；`entry_index` 是原 v1
`call_enter` row.index，必须等于该 row 的 `frame_index`，不是 invocation_id。
`attempt_index` 指向本 PID 的 sidecar CALL_ATTEMPT。

`arg0_missing` 必须为 exact bool。true 当且仅当 arg0 为 null；实际 Python None
是一个被观察对象，具有 token，不能编码成 MISSING。

`LoadObservation` 字段为 `suboperand, namespace, slot, slot_index, reference,
callable_shape`。namespace 枚举为 FAST_LOCAL/GLOBAL/BUILTIN；FAST_LOCAL 要求
非负 slot_index，另外两者必须为 null。suboperand 从 0 连续排列。纯 LOAD/LOAD
融合指令保留两个独立 micro operand；没有支持规则的混合 STORE/LOAD 必须停边。

`CallableShape(kind, reference, code, layout)` 中，kind 是 EXACT_FUNCTION、
EXACT_METHOD、OTHER、UNAVAILABLE。只有 EXACT_FUNCTION 携带 code 与
`FunctionLayout(argcount, posonlyargcount, kwonlyargcount, flags, parameters)`。
参数名按真实 positional、keyword-only、vararg、varkw 顺序保留；记录长度必须
与 counts/flags 一致。EXACT_METHOD/OTHER 不携带 code/layout；UNAVAILABLE 全 null。
load.reference 必须等于该 load 的 callable_shape.reference。

pre-load observations 不等于已经执行的值栈操作数。原始事件保留完整 required
instruction 路径，由 route 层按具体 attempt 独立推导有序 actual；不信任最近同名
load，不从引用相同选择来源，不把 recorder 预先计算的绑定当作证明。

## 3. 引用范围

- `weak:<pid>:<ordinal>` 复用原 recorder 的弱身份发行器。
- `operand-snapshot:<pid>:<sidecar-index>:<ordinal>` 仅属于当前 sidecar event。

PID、ordinal 为正整数；snapshot index 必须与当前事件相等。原 v1 的 `snapshot:`
不能用于 sidecar；sidecar snapshot 也不能跨事件合并身份。不可 weakref 的对象
仍可经位置规则得到有条件来源，不能因此声称已观测跨事件对象相等。
采集器不保存 Tensor 内容，不长期保留应用值或 frame。

## 4. metadata 与独立预算

metadata 严格字段集：

```text
schema, schema_version, process_id, project_root, python, implementation, rule,
limits, events, event_attempts, instructions, call_attempts, handshakes, gaps,
loads, references, bytes, dropped_events, errors, io_failed, previous_profile,
base_manifest, reference_contents_observed, callable_environment_established,
transformation_authorized
```

implementation 固定为 `cpython`；rule 是按PID严格分派的观察profile：

| rule | 观察范围 |
| --- | --- |
| `CPYTHON_LOAD_OCCURRENCES_V1` | 旧逐指令记录；旧raw/report继续使用原算法 |
| `CPYTHON_CALL_WINDOWS_V1` | 支持的完整CALL窗口、CALL事件及持续的continuation/handler失效观察点 |

wire字段和schema版本不变，未知rule拒绝。独立重放读取各PID的metadata.rule，
不能用当前CLI默认模式重解释旧记录；同bundle可有不同PID使用不同规则。
后三个 authority 字段只能为 false。`previous_profile`、`io_failed` 是 exact bool；
errors 至多 16 条非空字符串。未知字段或提升权限均拒绝。

limits 的五个 exact positive int：

| 字段 | collector 含义 / 默认 |
| --- | --- |
| max_events | 分配 event index 的上限 / 100,000 |
| max_bytes | sidecar 事件写入字节上限 / 32,000,000 |
| max_loads | 每条 instruction 的 load 上限 / 64 |
| max_namespace_items | 单次 namespace 扫描上限 / 4,096 |
| max_references | 与原 recorder 共用的 live weak 表上限 / 8,192 |

events 及分 kind 计数只计成功写入的完整行。event_attempts 是实际分配的 index
次数；`events <= event_attempts <= max_events`，未写入的 attempt 数不得超过
dropped_events。达到上限后没有分配 index 的丢失也可计入 dropped_events。
bytes 是实际成功写入字节；partial write 后不能继续追加，碎行拒绝。
loads 是所有成功 instruction.loads 的总长度；references 是每个非 null reference
字段的出现次数：每 load 的 reference 与 shape.reference 分别计费，attempt 的
dispatch.reference 与 arg0 分别计费，即便 token 重复。reader 重新计算以上计数。

windows profile中的instructions是**记录数**，不是执行的所有指令次数。
有意省略的非窗口位置不计drops，且不支持这些位置没有操作、状态或效果的结论。
collector的静态计划及disabled-offset累计记账也分别受max_events数值上限约束；
这些内部工作上限不能混同raw event计数，也不是reader能从省略事件重算的计数。
它们耗尽须给明确GAP并停止，而非无限保留CodeType实例或位置集合。

`base_manifest` 采用三个现有 CallTraceFile records，完整绑定 codes/events/meta 的
逻辑路径、PID、family、解压后的 SHA256、bytes、lines。collector 在 base.close 后
生成；reader 逐字段与独立 v1 scan 对照。sidecar 自身文件摘要由 reader 计算并
进入上层报告，不以 metadata 自报摘要替代重放。

独立 `CallOperandBudget` 的上限为总 raw bytes、lines、line bytes、processes、
events、loads、references、metadata bytes。其中 max_loads/max_references 是
**总计数**，与 collector 的每指令/live 表上限不同。原 frame trace 同时受独立
CallEdgeBudget 约束。解压、单行和 metadata 读取都有上限。

## 5. reader 接口与准入

```python
from scar.analysis.call_operand_reader import read_call_operands

observations = read_call_operands(trace, project_root,
                                 budget=CallOperandBudget(),
                                 frame_budget=CallEdgeBudget())
```

返回 `CallOperandTrace`（analysis 层）：directory、project_root、budget、frame_budget、
原 frame_scan、entries、exits、sidecar events/files/typed metadata/issues；另有
instructions/attempts/handshakes/gaps 分类属性。它不是可从任意 dict 获得的可信扫描
许可；公共 reader 始终重新读原始输入。root 内部 builder 可复用这次本地扫描，
不提供公共 trusted flag。

reader 核验同 PID/TID、原 owner entry 与活动区间、单调水印、原直接 active caller
与 CALL site、唯一 attempt/entry、epoch 以及所有引用范围。caller 恢复下一条
instruction 后，旧 pending attempt 失效；较新的 attempt 不能被旧 attempt 冒充。
结构错误拒绝整个输入。code/layout 不一致、缺 descriptor、采集缺口与干预分别
产生具体 boundary，不能得到成功路线。

完成对应复用该 handshake 的原 FrameExit：只有同一 invocation 的 NORMAL exit
与合法返回指令才能继续接唯一 caller CALL normal-result；UNKNOWN/SUSPENDED
不能接 normal。route 层仍须核对源码、完整 code、layout、字节码动态窗口和 core
端口，reader 返回本身不意味着这些条件通过。

windows profile还须从准确匹配的当前源码CodeType独立重建窗口：完整相邻的
LOAD/PUSH_NULL/NOP直到CALL，窗口内部不得有jump target或异常handler入口，
首offset允许多入口。全部必需位置每次都记录并核对动态顺序；不能按过滤后相邻
的LOAD子序列推导来源。caller暂停代码保持明确边界。正常CALL continuation与
handler入口持续观察，不能因首次无pending就DISABLE；未进入的attempt仍由既有
GAP/INSTRUCTION机制取消。旧profile不暗加该新规则。

采集CLI提供`--operand-capture windows|instructions`；新CLI默认windows，显式
instructions可复现旧逐指令模式。直接安装collector的无配置默认仍为instructions。
windows使用本机验证过的local事件DISABLE，code存活期保持有界weak identity登记，
stop/fork先检查全部tool/mask所有权；外部已改配置时不清掩码或释放其slot。
完整设计与实际失败依据见 [调用窗口修复计划](N2_CALL_WINDOWS_PLAN.md)。

GAP 与 previous_profile 必须阻断受影响的正路线。hook 配置快照相同不证明持续
无干预。所有条件路线保留 producer 信任、NO_FRAME_INTERPOSITION、namespace
观察到 load 期间不被替换、observer/audit 非干预及未证 hook 连续性，不授予
环境、内容、效果或变换权限。缺入口不等于已证明绑定失败。

## 6. 自验边界

records/reader 单测覆盖严格字段、布尔整数、snapshot 范围、预算、gzip、manifest、
水印、重复/过期/跨 PID attempt、错误 parent 与 code/layout boundary。
这些手工反例只检验协议，不能替代完整生产正例。

完整 B1 必须以原始两文件源码实际采集，公开查询穿过多层 actual→formal→return，
同一次 `leaf(shared, shared)` 的两个位置不能串线。还须通过重绑、同 code 不同
callee、bound method/default、递归、截断、缺首 LOAD、异常及旧 v1 重放反例。
不手工构造 workload 图，不新增 detector/backend，不按 LeWM 名称出规则。

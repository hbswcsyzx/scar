# R1：自动恢复记录中的编译上下文

日期：2026-10-16。状态：**Verified R1 only**，最终287项专项、2,278全仓及真实归档
独立重算通过。见 [验收记录](N2_COMPILATION_CONTEXT_ACCEPTANCE.md)。
前置 D1 已合并主线 `9cb3805`。
本门是源码身份对应修复，不是 detector/backend，也不是目标源码变换。

## 1. 实际问题

原 LeWM calls 归档有5条 code mismatch，位于同一源码文件。该文件 fingerprint
与归档完全一致；零 flags 的三种 optimize 尝试都不匹配，使用 captured flags
中的 future annotations 后，5条完整 descriptor 均可重现。源码未被执行或修改。
这是通用 exec/loader 编译上下文缺口，禁止按文件名、函数名或行号补匹配。

CodeID 表示的是给定源码与编译上下文的代码版本。源码文本、代码对象、函数实例、
运行 invocation 和数据版本不是同一实体。恢复 code descriptor 只授予 source
correspondence，不证明历史 parent/loader、参数、函数环境或纯性。

前置证据：`artifacts/experiments/c1_operand_preflight/compiler_and_lazy/`。
探针还证明 dynamic import 后首次启用指令观察可收到第一个 LOAD，支撑后续 B1，
但本门不实现 operand capture。

## 2. 冻结接口与版本

`scar.ir.program.compilation.CallCompilationProfile`：

- `LEGACY_ZERO_FLAGS`：旧 `compile(..., dont_inherit=True, flags=0)`，保留原重放。
- `RECORDED_FUTURE_FLAGS_V1`：只从 captured code 的受支持 future bits 恢复
  compiler flags；仍逐字段比较完整 descriptor，optimize 0/1/2。

新 source-seed report 为 schema v2，顶层保存 `compilation_profile`；模型实体不复制。
旧 schema v1 没有该字段，显式分派到 LEGACY。公共新采集分析默认 recorded profile，
无需用户指定 flags；旧完整 call-link v1 路径默认仍为 LEGACY。

inventory v6 的结构不变，消费嵌套 seed report 中明确版本的 matching profile。
公共新建使用 recorded；历史 v6 含 seed-v1 时显式走 legacy，不改既有 frame/core
含义。未知版本、未知/错配 profile、提高独立预算均在原始输入 I/O 前拒绝。

## 3. 编译与缓存规则

只恢复能从当前解释器明确解释的 future bits，不把 CO_NESTED、GENERATOR、
COROUTINE、文档标志等结构 flags 当成 compiler context。历史 nested_scopes
feature 位与 CO_NESTED 有重叠，必须明确排除，不能简单把全部 co_flags 传给 compile。

缓存 identity 至少绑定 canonical path、原样compile filename、decoded source
fingerprint、profile、future mask、optimize、解释器版本/实现与 compile mode/dont_inherit。
`/./`或重复斜杠可能读取同一文件但产生不同co_filename，不能在缓存键中折叠。
相同文件的不同编译
上下文不得共用错误的 trials。只缓存本进程的有界源码/code元数据，不保存Tensor。

唯一成功条件仍是完整 `describe_code(child) == captured descriptor`，包含pycode-v2。
不同名称、行号、shape等不能补对应。SourceSnapshot/唯一 AST definition 对应和
预算/错误边界继续使用既有规则；模块/annotation等无唯一定义的scope仍单列。

## 4. 自主验收

| 门 | 必须通过 | 阻断反例 |
| --- | --- | --- |
| R1.a | 原始小程序经 exec 继承future→自动源码匹配；多文件和嵌套代码 | 修改源码、描述或flags；同名/同行误配；结构co_flags误当compiler flags |
| R1.b | source-seed v1/v2独立重放；v6按嵌套profile重放 | 静默升级旧报告；删改profile；布尔schema版本；预算检查晚于I/O |
| R1.c | 同文件不同compiler context缓存；公共CLI | cache跨flags污染；采集到但source失败的输入被输出覆盖 |
| R1.d | 必要回归与冻结真实5 mismatch重现证据 | 放宽descriptor比较或目标文件特判；误称target运行/优化 |

原始程序自动产生正例。允许为decoder/缓存/失败路径写结构反例，但不手补 workload
图或伪造 VERIFIED 作为端到端验收。保留首次失败和修复报告，按源指纹冻结后提交。

初次冻结后，独立审查补充复现了原样compile filename缓存冲突，已保存反例并修复。
初版完整回归2,270项通过；最终修复使用新源指纹重新验收。
初次CLI生成的报告保留，公共check-call-seeds会从raw/source完整重算并精确比较，
最终复验可复用该报告，明确分别记录初次生成及最终重放的源指纹，避免重复生成。

完整LeWM重新执行与A/B性能不属于本门；真实归档的源码身份结果改变必须明确
记录，不能把之前的5条旧策略MISMATCH称作源码被改。本门不授予TRANSFORM。

## 5. 接续工作

R1后按 [跨层实现计划](N2_CROSS_CALL_IMPLEMENTATION.md) 完整交付B1查询链，
再补environment/world、loop-carried、dict/view/alias和版本，最后生成具体化简指导。

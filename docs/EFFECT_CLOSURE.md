# G5：源码对应、副作用闭包与可执行的补证据请求

状态：**Proposed**。本文定义 [NEXT_PHASE_PLAN.md](NEXT_PHASE_PLAN.md) 中 G5
的实施边界和验收案例，不代表 G5 已实现或通过验收。G4 验证结果以其独立
report 为准。G5 不增加 detector/backend，不产生源码改动。

## 1. 本 Gate 要交付什么

输入是 G2 Semantic Graph、G3 Execution Evidence Graph、G4 ValueGraph/registry，
以及明确的观察范围与 Q 合同。输出是：

1. 有版本证据的 source definition ↔ runtime instance ↔ value slot 对应关系；
2. 对调用者给定的 operation 集合，计算边界读写、escape、外部效果和覆盖缺口；
3. 每个缺口对应具体位置、缺失事实以及采集/合同请求。

G5 先接受显式给定的区域成员，不承担 G6 的区域发现或 G7 的化简选择。
它必须回答“这块区域读了什么、影响了什么、哪些影响越过边界、哪些信息还缺失”。
一个区域的闭包完成后标记 `ready_for_region_construction=true`；这不等于已经
批准 reuse、hoist 或删除 import。

## 2. 当前代码可以提供的证据与缺口

| 代码入口 | 当前提供 | G5 必须补齐 |
| --- | --- | --- |
| `scar/ir/frontend_v2.py` | AST source atoms、operation/slot/control、静态可能值路径；effect 默认 UNKNOWN | source→loaded-code 见证、区分直接和子区域效果、闭包查询 |
| `scar/ir/ids.py:CodeID.from_code` | `marshal.dumps(code)` 的 `pycode-sha256`，绑定实际加载的 CodeType | 编译环境与源码版本关联，不能改成读取当前磁盘文件代替 |
| `scar/trace/normalize_v2.py` | runtime definition stubs、实例层级、raw 文件/行/digest、独立 clock、provisional values | 与 source graph 对应；raw `legacy_effect` 不能自动升级成完整效果 |
| `scar/ir/v2/correspondence.py` | definition-instance、source-instance、slot-version、evidence 与 ambiguity | 候选对应的分组、版本见证、覆盖范围与具体不匹配理由 |
| `scar/ir/v2/contracts.py` | EffectSet/EffectPresence、Q facets、LOG/ENVIRONMENT/FILE 等 target kind | 每个维度的 coverage、目标选择器、外部效果的细分合同 |
| `scar/analysis/topdown.py` | v1 child→parent 报告和 incomplete reasons | 不能直接复用其 completeness 结论作为 v2 语义证明 |
| `scar/analysis/liveness.py` | v1 observed consumers 与显式 closed-world 条件 | 必须用带范围和覆盖证据的 closure，不能只复制一个布尔开关 |

当前每一行源码都有 AST owner，不代表每个 operation 的语义已经知道。
每个 raw event 有保存位置，也不代表所有路径、所有写入或所有消费者已观察到。

## 3. Source 与 loaded code：先证明对应哪一份程序

### 3.1 两类 hash 含义不同

G2 的 `SourceReference.fingerprint` 是当前读取、解码后的源码文本 hash。
G2 使用 `tokenize.open` 读取源码后计算 `sha256(text.encode())`。它不是原始文件
字节的 hash，也不是 CodeType hash。

v1 runtime `CodeID.version` 是 `pycode-sha256:sha256(marshal.dumps(code))`，包含
实际加载的 code object 信息。文件可能在 import 后被编辑；路径、qualname 和
行号仍相同，运行的代码却可能与当前 source graph 不同。

**禁止直接比较上述两个 hash，禁止把 path/line 命中当作已验证的版本对应。**
旧 `scar/ir/correspondence.py:link_events` 的 path/span join 只能提供定位候选。

### 3.2 最小版本见证

新增独立的 `CodeSourceWitness`，至少包含：

```text
source_snapshot: path + text fingerprint + hashing algorithm
loaded_code: CodeID + raw co_filename + co_qualname + co_firstlineno
compile_context: Python implementation/version + optimize + compile flags
method: collector_bound | offline_compile_match | location_only
scope: run/process + source snapshot lifetime
evidence: raw record references / immutable source snapshot references
status: VERIFIED | AMBIGUOUS | MISMATCH | MISSING
```

`offline_compile_match` 只编译已有源码快照，递归检查 nested CodeType，不执行
module、不 import 被分析程序。只有编译环境一致且实际 CodeType hash 相等，
才能把该快照连接到加载代码。必须使用采集时原始 `co_filename`；CodeID 中的
规范化路径不能替代它。编译失败、缺少 flags、不同 Python 版本或 hash 不同
时保留候选，提出具体请求，不尝试“忽略差异后算相等”。

新 collector 可以在 loader 获取源码并编译的同一次受观察操作中记录对应见证。
仅在 call hook 中同时读文件和 code hash 仍不足以证明文件就是加载来源。
第三方二进制、动态 `exec`、自定义 loader 用版本化 library/loader contract；
缺少见证时保留 opaque boundary。

### 3.3 Join 的范围

- 同一 source definition 可以对应很多动态实例；实例不能因此合并。
- 多个候选 source atom 允许同时保留，并用同一个 ambiguity group 关联。
- `module_call` hook 与 `python_call` 可能观察同一实现的不同层次；CodeID 相等
  不足以认定它们是一次相同 invocation。
- module state、closure、实例参数仍需独立 value/state 绑定，不能由函数代码
  相同推断相同。
- profiler aggregate row 是 measurement，不允许伪造成单个 source invocation。
- slot-version 关联必须有 invocation/binding interval 与有效 provenance。
  同名变量或相同 shape/prefix 不构成对应证明。

合并 SG 与 EEG 时保留 G3 runtime stubs 和原始 `OperationInstance.definition`，
通过 correspondence 指向 G2 definitions。不能把候选 source 定位写回成原始
runtime 事实。ID 冲突必须验证记录一致或拒绝合并。

## 4. 最小新类型：把范围和缺口从自由文本中提出来

初期沿用 `EffectSummary` 表示已知集合和 presence，增加以下有校验的记录。
新增 schema 应有 version、codec 和 round-trip/非法引用测试。

| 类型 | 最少字段 |
| --- | --- |
| `ObservationScope` | entry/exit、run/process/thread/control、时间域、dynamic-path 或 all-paths、collector 范围 |
| `EffectOccurrence` | instance/definition、直接效果类别、typed target、顺序位置、source/raw refs、evidence |
| `EffectCoverage` | scope、维度、target domain、COMPLETE/PARTIAL/UNKNOWN、branch/call/alias coverage、证据与假设 |
| `BoundarySummary` | 区域成员、entry reads、outward writes、alloc/free、aliases/escapes、外部/RNG/异常/order、每维 coverage |
| `ConsumerClosure` | 起点 value/version/effect、已访问消费者、范围终点、逃逸/未知边界、覆盖证据 |
| `EffectPolicy` | contract id、目标类别/选择器、preserve/ignore/tolerance、适用范围、声明来源 |
| `EvidenceRequest` | INSTRUMENT/CONTRACT、缺失事实、精确 target/source、采集范围、collector、完成判据、失效条件 |

`EffectPresence.PRESENT` 仅表示至少存在一个效果。它不能表达“还有没有未观察到
的效果”；这个问题由独立 `EffectCoverage` 回答。`NONE` 也必须引用能覆盖该
维度和范围的证据。不能由空列表推导 NONE。

## 5. 对显式区域做 compositional effect closure

### 5.1 先确定直接效果，再合成子区域

每个输入 summary 标明 `direct` 或 `inclusive`。父 module hook 的 inclusive
summary 和已展开子调用不能重复计数；实际效果按 occurrence identity 去重。
unresolved Python/C 调用、未跟踪 callback、缺少 return、未覆盖路径，都保留
为明确的开放边界。

对每个 effect 维度，合并成员并合成 coverage。一个孩子缺少写入覆盖时，父区域
也不能宣称完整写集合。已观察到成员但集合不完整为 PARTIAL；没有足够事实为
UNKNOWN。PRESENT 可以与 PARTIAL/UNKNOWN coverage 同时存在。

静态 possible effects 与动态本次 observed effects 分别保存。一次运行没走到
某个分支，不能使 all-paths summary 变纯。递归调用按 SCC 做单调闭包；未收敛
或存在开放调用时保留 unknown target domain，不因达到迭代上限而删除边。

### 5.2 哪些效果越过区域边界

- **Entry reads**：读取由区域外产生的版本，或无法证明在区域内先定义的值。
  不能简单使用 `reads - writes`；先读后写仍依赖入口值。
- **Outward writes**：写入 caller/global/module/环境等外部可达状态。内部随后
  覆写不自动消除前一次效果；中间 consumer、callback、异常路径仍可能看见它。
- **Local temporaries**：只有完整 allocation lifetime、alias/escape 和 consumer
  closure 才能判定内部使用。异常、析构、weakref 和资源合同仍需检查。
- **Aliases/escapes**：共享 storage、返回对象、存入容器/全局/module、callback
  捕获都可能让影响越过边界。G4 overlap 为不确定时必须按可能重叠传播影响。
- **RNG/exception/order/external**：保留目标与顺序。异常前已发生的日志或文件
  写入不能因正常返回值相同而消失；CUDA barrier 也不能仅按时长合并。

嵌套区域可以逐级查询并展开。G5 先计算给定成员的边界；跨层上移所增加的依赖
和替换后的图由 G6/G7 处理。

## 6. Consumer closure 与 effect liveness

Backward slice 沿 source def-use、有效 binding interval 与 G4 provenance 回溯。
Forward closure 跟随所有适用 consumers、materializations、alias、escape 和
控制/异常出口，直到观察范围明确的终点。cross-device readiness 和 clock
不完整时保留 ordering gap。

closure 的结果至少区分：

```text
LIVE          已找到 Q 要求保持的消费者或效果
DEAD_IN_SCOPE 在明确封闭范围内，证明没有合法消费者/外部影响
OPEN          遇到未覆盖调用、alias、escape、未来使用或范围出口
```

“图里没有出边”只能说明当前投影没有记录出边。OPEN 不能变成 DEAD_IN_SCOPE。
动态单次 episode 的 closure 不能默认推广到未来 episode 或另一个输入。

Residual effect extraction 先产生“必须保留的 effect occurrences + 依赖切片 +
原始相对顺序/异常位置”。G5 不据此生成替换代码。若无法把 effect 与值计算
分开，报告该原始区域仍必须保留；不能生成一个没有可执行依赖的“保留日志”口号。

## 7. Q 必须区别日志、环境、文件和外部交互

现有 `ContractFacet.EXTERNAL` 只有一个总开关。G5 增加 `EffectPolicy`，利用
已有 `EffectTargetKind.LOG/ENVIRONMENT/FILE/EXTERNAL` 对目标分类，避免把所有
外部效果放进一个不可解释的 UNKNOWN。

| 合同目标 | 必须明确的内容 |
| --- | --- |
| output/state | 哪些输出、module buffers、容器/全局状态、对象身份需要保持 |
| RNG | 哪些 generator/设备、状态推进和随机序列要求 |
| exception | 类型、触发条件、可见顺序；何种 traceback 细节属于合同 |
| logging | 哪些 logger/channel、内容与顺序；handler 状态修改另计 STATE/EXTERNAL |
| environment | 哪些键的读写、缺失值与默认值、作用范围及下游读者 |
| file | 路径/handle 的读取、写入、offset、内容、可见创建/删除行为 |
| ordering/resource | stream/event/thread 顺序、异步 readiness、内存/设备生命周期限制 |
| numerical | exact 或明确容差；approximate 行为不在当前自动变换范围内 |

未列出的 facet/target 默认 preserve；`ignore LOG` 不会自动忽略 handler 的
状态修改，`ignore ENVIRONMENT` 不会消除环境键对结果或分配器行为的依赖。
EffectPolicy 必须有显式来源和适用 scope，不能因为“日志通常不重要”自动填入。

Module initialization、lazy attribute、import hooks/reexports 都按普通 operation
和状态/外部效果建模。Q 要求的注册行为、环境写入或异常路径若仍 live，就列入
residual slice 或保留原始 init。纯常量值路径可单独闭包；是否删除整个 import
由该范围内全部 required effects 的闭包决定，规则不读取 workload/package 名称。

## 8. 缺口必须成为可执行请求

proof 内部仍允许 UNKNOWN；任意 Python 程序并不能保证静态可判定全部语义。
G5 消除的是“只有 UNKNOWN，没有原因和下一步”的最终报告。

| 面向 planner 的处理 | 适用情况 | 报告必须携带 |
| --- | --- | --- |
| KEEP | 已知 required effect live，或当前支持范围无法闭合且保留原始边界 | 具体 effect/target、source/raw 位置、Q 条款及保留范围 |
| INSTRUMENT | 已知缺失事实有受支持的采集方法 | precise scope、collector、需要捕获的字段、采集成本上限、成功判据、重跑入口 |
| CONTRACT | 缺失的是用户/库必须定义的语义边界或可观察性要求 | 缺少的 facet/target、待声明性质、适用代码版本和验证要求 |

多个缺口全部保留；主 disposition 采用确定性优先级：已知违约 KEEP，其次缺少
必要合同 CONTRACT，其次可采集缺口 INSTRUMENT，否则保留当前 opaque 边界 KEEP。
不要因为有一个容易补的事实，就隐藏另一个已知无法保持的效果。

请求示例（结构为 Proposed，字段需落到上述 typed records）：

```json
{
  "disposition": "INSTRUMENT",
  "missing_fact": "loaded code 与源码快照版本的对应",
  "target": {"definition": "opdef:...", "source_atom": "source:..."},
  "location": {"path": "/project/package.py", "start_line": 12, "end_line": 19},
  "scope": {"entry": "module loader", "exit": "first matching function call"},
  "collector": "code_source_witness",
  "fields": ["raw co_filename", "CodeID", "source text hash", "compile context"],
  "rerun": {"command_ref": "run manifest argv", "required_phase": "module initialization"},
  "completion": "source compiled under captured context matches loaded CodeType hash",
  "fallback": "keep original region"
}
```

现有 run manifest 没有 argv/cwd/environment identity 时不能捏造重跑命令；请求
明确列出需要提供的入口。命令使用 argv 数组，不能生成含任意 shell 拼接的脚本。
INSTRUMENT 是可审查工作项，不是默认开启全程序 line trace 或保存所有 Tensor 值。

## 9. 实施顺序与验收案例

| 子阶段 | 窄范围交付 | 指名验收案例，尚未实现 |
| --- | --- | --- |
| G5.1 | scope/coverage/request/target policy 类型与严格 codec | `test_effect_presence_does_not_imply_complete_coverage`、`test_unknown_facets_default_to_preserve`、非法范围/引用反例 |
| G5.2 | source witness 与候选 join，不重写 runtime stubs | `test_source_edit_after_import_does_not_join_by_path`、`test_compile_context_mismatch_requests_witness`、`test_nested_code_join_never_executes_module`、`test_ambiguous_lambda_locations_keep_all_candidates` |
| G5.3 | 给定区域的直接/子区域 effects 与 boundary 查询 | `test_parent_inclusive_effect_not_double_counted`、`test_read_before_write_remains_boundary_input`、`test_hidden_module_state_and_rng_keep_parent_open`、`test_uncaptured_exception_branch_blocks_all_paths_closure` |
| G5.4 | consumer/effect closure 与 residual slice 报告 | `test_absent_consumer_in_open_scope_is_not_dead`、`test_callback_escape_keeps_future_consumer_open`、`test_local_temporary_requires_alias_and_lifetime_closure`、`test_residual_effect_keeps_dependencies_and_order` |
| G5.5 | Q 评估与具体 KEEP/INSTRUMENT/CONTRACT 报告 | `test_logging_ignore_does_not_ignore_environment_write`、`test_q_profiles_explain_different_required_effects`、`test_import_constant_path_keeps_live_initialization_effect`、`test_request_contains_source_scope_fields_and_rerun_requirement` |
| G5 gate | generic end-to-end fixture，已有真实 trace 的 join/closure 报告 | `test_same_input_produces_deterministic_closure_report`、raw/source coverage 数可对账、每个 unresolved boundary 有位置和具体请求 |

先用小型多 module fixture，包括正常返回、异常、隐藏状态、RNG、callback、
import initialization、lazy attribute 和源码版本改变。随后把同一实现用于
已有 LeWM source/trace，仅作为外部压力输入；历史 trace 没采到的见证要如实
生成请求，不能为了提高 correspondence 覆盖率放宽版本要求。

每个子阶段写清测试与限制，G5 独立 gate report 逐项登记。达到这些标准后才
进入 G6 region builder；G5 的通过不等于 LeWM 已有可信变换或加速结果。

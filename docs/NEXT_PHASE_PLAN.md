# SCAR 下一阶段开发计划与验收门

状态：**执行计划**

起点：`CURRENT_CODE_AUDIT.md` 记录的 2026-09-22 架构基线。

目标：把 SCAR 从 evidence profiler + candidate detector 推进为能输出确定、
可审计、AI 可执行修改指导的 semantic-aware execution optimization system。

## 1. 阶段目标

下一阶段不以“新增多少候选”为指标。完成标志是下面链路真实连通：

```text
Python/PyTorch source
  -> Semantic Graph
runtime trace
  -> Execution Evidence Graph
SG + EEG
  -> Value/Provenance Graph
  -> correspondence + effect closure
  -> Optimization IR
  -> generic graph rewrite alternatives
  -> deterministic modification plan
```

修改计划至少要回答：

```text
where       哪个 source/semantic/runtime region
what        删除、替换、上移、合并、驻留或保留什么
with        替代值或替代 region 是什么
why         provenance、effect、control、contract 和 cost 证据
guard       运行或静态守卫
invalidate  哪些变化使计划失效
residual    哪些副作用仍需保留
validate    如何分层验证
fallback    不满足时如何保持原执行
```

本阶段只生成计划，不自动修改任意目标仓库。后续可以把结构化计划交给 Codex 等
代码代理执行。

## 2. 开发纪律

### 2.1 Model-first

任何 feature 必须先进入 IR，再进入 analysis。不得先写 detector，再把缺少的
语义塞进 metadata 字典。

### 2.2 Generic-first

每条规则先通过最小通用 fixture 和反例，再在 LeWM 上做压力测试。SCAR core
不得导入 testcase adapter，不得匹配项目、包、函数、类或变量名。

### 2.3 Evidence separation

Observed、Inferred、Proposed、Implemented、Verified、Rejected 保持分离。静态
语义、动态事实和 optimization alternative 使用不同 schema 和 ID namespace。

### 2.4 Gate discipline

每个阶段必须通过本文件的验收门。未通过时只修复该阶段，不开启后续 detector
或 backend。每个 gate 产出机器可读 validation report。

验收、修复、报告、commit 和 push 均由开发代理自行完成。用户不承担阶段审批。
执行规范见 [GATE_EXECUTION.md](GATE_EXECUTION.md)；每个通过的阶段应立即推进
下一个满足依赖的阶段。

### 2.5 Terminal decision

proof 内部允许 UNKNOWN；用户可执行计划的终态只能是：

- `REWRITE`；
- `KEEP`；
- `INSTRUMENT`；
- `CONTRACT`。

后两者必须包含缺失事实、采集位置和重跑入口。

## 3. 总体里程碑

| Gate | 里程碑 | 主要产物 | 进入条件 |
| --- | --- | --- | --- |
| G0 | 审计与规划基线 | 本文、current audit、测试基线 | 已完成 |
| G1 | 完整 v2 core schema | SG/EEG/Value/OIR typed IR | G0 |
| G2 | Python source → SG | package/import/control/def-use frontend | G1 |
| G3 | v1 trace → EEG | 兼容 normalizer 与 evidence coverage | G1 |
| G4 | logical provenance | 跨 object/storage/view/copy/transform/materialize registry | G2 + G3 |
| G5 | correspondence/effects/contracts | SG↔EEG、effect closure、Q boundary | G4 |
| G6 | OIR region builder | composite region 与完整接口 | G5 |
| G7 | report-only simplifier | 通用 rewrite + AI-ready plan | G6 |
| G8 | global cost planner | alternative composition/conflict/cost | G7 |
| G9 | validation plan + pressure tests | contract-derived validation、LeWM report | G8 |
| G10 | backend eligibility review | 是否解除 backend 冻结 | G9 |

G2 和 G3 在 G1 完成后可以并行开发，但 G4 只能在两者可用后验收。

## 4. G0 — 审计与规划基线

### 任务

- 冻结新 detector/backend；
- 记录实现、schema-only、partial、absent 的真实状态；
- 固化 155-test baseline；
- 定义下面各 gate 的输入、输出和拒绝条件。

### 验收

- [x] `CURRENT_CODE_AUDIT.md` 能从代码逐项核对；
- [x] `NEXT_PHASE_PLAN.md` 有有序依赖和硬性验收门；
- [x] README/ROADMAP 指向本计划；
- [x] 完整测试仍通过；
- [x] 单独 commit 并推送，作为后续迁移基线。

## 5. G1 — 完整 v2 core schema

### 任务

补齐以下 typed entities：

```text
SourceAtomID / ModuleID / PackageID
ValueSlotID / ContractID / EffectSummaryID
ResourceID / MeasurementID / CorrespondenceID
OptimizationRegionID / PlanAlternativeID / PlanID
```

SG 增加 typed relations：

```text
contains, calls, controls, reads_slot, writes_slot,
consumes, produces, may_raise, initializes_module,
imports, reexports, accesses_attribute, has_contract
```

EEG 增加 typed relations：

```text
instance_of, observed_read, observed_write, produces,
materializes, aliases, overwrites, escapes,
happens_before, controls_instance, measured_by
```

OIR 首次实现：

```text
OptimizationRegion
RegionPort
PlanAlternative
TransformDelta
ResidualEffect
GuardSpec
InvalidationSpec
CostRequest
ValidationRequest
PlanInstruction
```

所有 schema 支持 deterministic JSON serialization、strict reference validation
和 schema version。

### 验收 G1

- [x] 不同 ID 类型不能因 string 相同而混用；
- [x] dangling reference、cycle、非法 region boundary 被 validator 拒绝；
- [x] OIR 能表示 constant substitution、import residualization、loop hoist、
  residency 四种 plan fixture，但不执行它们；
- [x] 每个 alternative 同时含原始 NO-OP；
- [x] serialization 重复运行 byte-for-byte 相同；
- [x] 单元测试覆盖正例和非法 schema 反例；
- [x] v1 CLI 行为和 JSON reader 不退化。

## 6. G2 — Python source 到 Semantic Graph

### 任务

实现 generic Python frontend：

- package、module、module initialization region；
- import、from-import、alias、re-export、lazy attribute boundary；
- function/method/class/lambda/comprehension；
- call target candidates 与 unresolved dynamic dispatch；
- assignment、attribute/subscript access、phi-like merge；
- branch、loop、try/raise/finally、with、yield/await；
- globals/nonlocals/closure/callback slots；
- source atom 到 semantic node 的完整映射；
- built-in/PyTorch contract registry 使用明确版本和来源，未知库保留 opaque
  operation。

Frontend 的目标是完整表示，而不是声称完整理解。每个可执行 source atom 必须
属于已解析 operation/control/value relation 或显式 opaque boundary。

### 验收 G2

- [x] fixture 的每个可执行 source atom 都有 SG owner；
- [x] import→module-init→attribute→index→consumer 的值路径可查询；
- [x] unresolved call 产生有输入输出/effect boundary 的 opaque op；
- [x] 跨函数参数/返回值和跨本地模块 import def-use 可查询；
- [x] branch/loop/exception control edge 有正反例；
- [x] 不执行目标程序也能构图；
- [x] 没有任何 workload 名称规则。

## 7. G3 — v1 trace 到 Execution Evidence Graph

### 任务

- 保留 raw JSONL，新增 deterministic normalizer；
- 把 call/module/op/kernel/memory/control/resource record 变为 v2 instances 和
  typed relations；
- raw record ID 保留为 evidence reference；
- storage epoch 只生成 physical allocation/version evidence；
- 标明采集 scope、collector、clock domain、completeness 和 ambiguity；
- 为 unsupported event 生成 opaque evidence record，不丢弃；
- 增加 coverage report：normalized、ambiguous、opaque、unmatched、invalid。

### 验收 G3

- [x] 现有 generic trace 可完整 normalize，原始 event 数可守恒核对；
- [x] 现有 LeWM trace 无需重跑即可 normalize；
- [x] operation nesting、same-stream order、copy、allocation、barrier 均有 typed edge；
- [x] 不把 `.to()` 调用计为物理 copy，不把 `expand()` 计为完整 allocation；
- [x] raw→EEG→JSON 重复运行结果确定；
- [x] normalizer 不产生 optimization candidate。

## 8. G4 — Logical value 与 provenance registry

### 任务

统一 static slot 和 runtime value identity：

```text
ValueSlot
  -> binding interval
  -> ObjectID
  -> ValueVersionID
  -> ProvenanceRecord
  -> MaterializationID
  -> StorageRegionID
```

支持 origin、copy、deepcopy、view、representation transform、semantic transform、
aggregate、mutation、serialization/deserialization、host/device materialization。

相等是显式 claim：identity、exact content at time、representation-only、contract
equivalence、approximate。shape/prefix 只作为 cheap filter；详细比较按需触发。

### 验收 G4

- [x] `torch.from_numpy` 外部 NumPy 写入产生新版本/失效；
- [x] inference tensor 不依赖 `_version` 作为唯一依据；
- [x] allocator 地址复用产生不同 allocation identity；
- [x] view/expand 正确共享 region/stride 语义；
- [x] deepcopy 是不同 object/storage，并保留 provenance；
- [x] CPU↔GPU copy 可绑定同一 value version 的不同 materialization；
- [x] semantic transform 产生新 logical value，而不是伪装成相同内容；
- [x] mutation、alias、escape 都有反例测试。

## 9. G5 — Correspondence、effect closure 与 Q contract

### 任务

- source span/CodeID/library contract/runtime stack 多证据 SG↔EEG join；
- 一对多、多对一和 ambiguous mapping；
- child→parent compositional effect summary；
- reads/writes/allocates/frees/aliases/escapes/RNG/raise/external/order 的
  completeness 和 scope；
- backward value slice、forward consumer closure、effect liveness；
- residual effect extraction；
- Q profile 明确 output、state、RNG、exception、logging、env、file、ordering、
  numerical tolerance 是否必须保持；
- 缺证据时生成 InstrumentationRequest 或 ContractRequest。

### 验收 G5

- [x] 任意 composite region 的 boundary reads/writes/effects 可查询；
- [x] “未观察到 consumer”在开放 scope 下不会变成 dead；
- [x] callback/escape、hidden module state、random operation 阻止错误 pure summary；
- [x] import module initialization effect 能被保留、证明 dead 或提出具体请求；
- [x] 同一输入下不同 Q profile 可得到不同且可解释的合法性结论；
- [x] planner-facing 结果无裸 UNKNOWN：转为 KEEP/INSTRUMENT/CONTRACT。

## 10. G6 — Optimization IR region builder

### 任务

从 SG、EEG、ValueGraph 构造不同粒度 region：

- instruction/expression；
- operator graph；
- function/module call；
- loop body/loop-invariant slice；
- dataflow subgraph；
- pipeline stage。

粒度选择按 transformation requirement：

| 目标 | 必需 region 视图 |
| --- | --- |
| constant folding/import elimination | source/value/effect slice |
| kernel fusion | operator dataflow graph |
| CUDA Graph | stable control/resource region |
| KV/state cache | state/value provenance subgraph |
| prefetch | producer-consumer/resource graph |
| residency | materialization lifetime graph |
| hoisting | loop/control/value origin graph |

### 验收 G6

- [x] 已知 region input/output/state/control/resource/effect ports 完整保留；语义闭合缺口显式；
- [x] composite region 可递归展开且 member identity 不丢失；
- [x] 第八层 consumer 在有明确 binding/producer 证据时可沿 provenance 回溯到第三层 origin；
- [x] region 上移查询能计算已知跨越边界的新增/删除依赖，保留合法性义务；
- [x] overlap/nesting/conflict 可查询；
- [x] region builder 仍不选择 backend。

自行验收与实测成本见 [G6_ACCEPTANCE.md](G6_ACCEPTANCE.md)。G7 按
[GRAPH_SIMPLIFICATION.md](GRAPH_SIMPLIFICATION.md) 的子节点继续。

## 11. G7 — 通用 report-only 图化简器

### 任务

第一组 rewrite families：

1. constant propagation 与 path contraction；
2. dead value/effect subgraph elimination；
3. common subexpression/exact reuse hypothesis；
4. loop-invariant composite region motion；
5. repeated materialization/residency hypothesis；
6. deferred host materialization；
7. allocation lifetime/buffer reuse；
8. fusion/prefetch/capture 的结构性 hypothesis。

每条规则产生 `PlanAlternative`，包含 before/after graph、proof tree、residual
effects、guard、invalidation、cost request、validation request 和具体 source
instruction。规则只读 OIR，不读取 workload 名称。

constant/import generic fixture 必须能输出：

```text
REWRITE value path to literal
DELETE import only if module-init/lazy effects are dead under Q
otherwise PRESERVE explicit residual effects
```

这不是 stable-pretraining 专用测试；fixture 使用自建的任意包名，并包含 module
init effect、lazy attribute、re-export、mutable constant 等反例。

### 验收 G7（backend 冻结解除前置门）

- [ ] 至少四类 generic plan 端到端产生；
- [ ] 每类都有合法正例及 mutation/state/RNG/escape/raise 反例；
- [ ] plan 能回答 where/what/with/why/guard/invalidate/residual/validate/fallback；
- [ ] 相同输入重复运行生成相同 plan 和排序；
- [ ] source instruction 精确到 file/span/symbol，不修改源码；
- [ ] stable-pretraining 类型案例由 generic rule 自主给出 literal substitution，
  并依据 effect liveness 决定 delete import 或 residualize；
- [ ] LeWM 只作为运行输入，SCAR core 无名称特判；
- [ ] 未满足证据的目标变成具体 INSTRUMENT/CONTRACT 任务。

## 12. G8 — 全局 cost-aware planner

### 任务

- original NO-OP 与所有 alternatives 同台比较；
- startup、warmup/compile、steady-state、guard、lookup、memory、transfer、sync、
  overlap、variance 和 confidence；
- candidate region overlap、value dependency、effect ordering、resource budget 的
  conflict graph；
- 可组合 rewrite 的依赖顺序和收益重算；
- 明确优化目标与 deterministic tie-break；
- 不盈利的合法 plan 输出 KEEP(not_profitable)。

### 验收 G8

- [ ] synthetic plans 覆盖互斥、依赖、可组合、memory budget；
- [ ] 测量缺失时生成具体 MeasurementRequest；
- [ ] profiler 重插桩时间不会当作 clean benchmark；
- [ ] 全局选择结果优于或等于 NO-OP 的目标值；
- [ ] 计划包含估计区间、证据来源和敏感性。

## 13. G9 — Validation plan 与压力测试

### 任务

- 从 Q 和 TransformDelta 自动生成 validation snapshots；
- Level 1 region、Level 2 solve、Level 3 policy、Level 4 episode 的输入/状态/
  输出/effect checklist；
- clean A/B benchmark spec；
- baseline defect 独立记录；
- generic test suite 与 LeWM external pressure report。

### 验收 G9

- [ ] 每个 REWRITE 都有 machine-readable validator 和 fallback；
- [ ] output、visible state、RNG、exception、external/order effect 按 Q 核对；
- [ ] micro 正反例全部通过；
- [ ] LeWM 报告列出 REWRITE/KEEP/INSTRUMENT/CONTRACT，而不是候选总数；
- [ ] 未实际应用/验证的 plan 不报告加速比；
- [ ] 应用后的 clean benchmark 报 median/min/max/variance/warmup/repetitions/
  GPU/PyTorch/CUDA/config。

## 14. G10 — backend eligibility review

只有 G1–G9 全部通过后，才审查是否实现下一个 backend。评审输入必须是一个
已经由 OIR 输出且通过 generic/LeWM plan validation 的真实计划。选择依据：

1. 在真实运行发生；
2. 估计成本显著；
3. legality 与 invalidation 可定义；
4. generic fixture 已通过；
5. 无 workload-specific rule；
6. clean A/B 有合理盈利空间。

评审可以继续选择 NO-OP。通过 G10 不保证一定开发 backend。

## 15. 持续开发顺序

严格执行顺序：

```text
G0 文档基线
 -> G1 schema/OIR
 -> G2 source frontend ┐
                       ├-> G4 provenance
 -> G3 trace normalizer┘
 -> G5 correspondence/effect/Q
 -> G6 region builder
 -> G7 report-only simplifier
 -> G8 global planner
 -> G9 validator/pressure tests
 -> G10 backend review
```

每个 gate 的工作循环固定为：

```text
model update
 -> schema validator
 -> positive fixture
 -> counterexample
 -> deterministic serialization
 -> integration test
 -> documentation/status
 -> commit/push
```

## 16. 第一批具体开发任务

G0 通过后立即执行 G1，按以下提交拆分：

1. **G1.1 Typed identities and common claims**

   增加缺失 ID、evidence claim、source reference、effect/contract/resource 基础类型。
2. **G1.2 Typed SG/EEG relations**

   用显式 edge dataclass 替代关键 metadata relation，并增加 strict validation。
3. **G1.3 Optimization IR**

   实现 region/port/alternative/delta/residual/guard/cost/validation/plan instruction。
4. **G1.4 Serialization and fixtures**

   deterministic JSON、round-trip、四类 report-only plan fixture、非法输入测试。
5. **G1 gate report**

   生成 `artifacts/reports/gates/g1.json` 和简短 Markdown，逐项记录 PASS/FAIL。

任何 G1 子任务都不接 detector/backend。G1 gate 通过后才开始 G2/G3。

## 17. 风险和控制

| 风险 | 控制 |
| --- | --- |
| graph 继续膨胀 | 分离 raw evidence 与 projection；typed indexes；按需展开；后续增加增量/列式存储 |
| arbitrary Python 无法静态理解 | opaque boundary + library/user contract + targeted instrumentation |
| UNKNOWN 被掩盖 | proof 保留 UNKNOWN；终态转为具体 INSTRUMENT/CONTRACT/KEEP |
| trace 成本过高 | 默认 call/op/memory，按 proof gap 请求 line/value evidence |
| 错误合并逻辑值 | equality claim 有证据和 scope；shape/prefix 只做 filter |
| 规则彼此冲突 | OIR before/after graph + global conflict graph |
| LeWM 污染核心 | generic fixtures 先行；core 禁止 workload import/name match |
| 文档超前于实现 | gate report 从测试生成；状态只允许 Verified/Partial/Absent 等明确词 |

## 18. 阶段完成定义

本阶段完成时，SCAR 对一个任意 Python/PyTorch/GPU 项目应能输出类似：

```json
{
  "target": {"file": "...", "span": [12, 27], "region": "..."},
  "decision": "REWRITE",
  "instructions": [
    {"kind": "replace_value_path", "with": {"literal": [1, 2, 3]}},
    {"kind": "delete_import", "condition": "module effects dead under Q"}
  ],
  "proof": {"value": "PROVEN", "effects": "PROVEN", "control": "PROVEN"},
  "residual_effects": [],
  "guards": [],
  "invalidation": ["source fingerprint changed", "contract changed"],
  "cost_request": {"mode": "clean", "region": "..."},
  "validation_request": {"levels": [1, 2, 3, 4]},
  "fallback": "original_region"
}
```

该结构只是说明完整性，具体字段以 G1 通过校验的 schema 为准。真正完成标准
是计划由通用图规则导出、证据可追溯、反例被拒绝，并能在 LeWM 之外复用。

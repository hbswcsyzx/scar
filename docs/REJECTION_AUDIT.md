# LeWM 候选拒绝审计与自顶向下分析

本文件记录一次对真实 LeWM trace 的逐条 proof audit。它解释当前的
`REJECT`，不把“证据不足”写成“程序确定不能优化”。原始证据和本次压缩
报告分别是：

```text
artifacts/reports/lewm_resource_global_proofs.json
artifacts/reports/lewm_rejection_audit_20260918.summary.json
artifacts/reports/lewm_topdown_20260918.summary.json
artifacts/reports/lewm_constant_provenance_20260918.json
```

## 1. 先给出数字

对 global proof report 的两个候选视图合并后：

| 结果 | 数量 | 含义 |
| --- | ---: | --- |
| `PROVEN_BLOCKER` | 960 | 至少一个必须条件被观察证据明确否定 |
| `EVIDENCE_GAP` | 1568 | 没有被否定，但至少一个必须条件仍为 `UNKNOWN` |
| selected transformation | 0 | 没有候选通过完整 legality、cost 和 backend 选择 |

这批联合候选共有 2528 条。事件视图 1457 条，graph 视图 1071 条；两种
视图是同一运行证据的不同投影，不能把它们相加后称作 2528 个独立优化点。

### 事件视图

| 候选 | 数量 | 主要阻塞 |
| --- | ---: | --- |
| `ReuseCandidate` | 1281 | 输入签名通常相同，但 effect 合同未知，cost 也未知 |
| `RepeatedOperatorCandidate` | 167 | Kineto aggregate 没有逐次输入和 effect，不能当作可复用算子 |
| `AllocationReuseCandidate` | 5 | allocator 计数不等于 allocation lifetime/alias 证明 |
| `SynchronizationCandidate` | 2 | 缺完整 consumer 和 happens-before |
| `DeferredMaterializationCandidate` | 2 | 缺 consumer、escape 和 ordering 证明 |

`ReuseCandidate` 中有 1281 条的 `same_input_versions` 已经是 `PROVEN`，
但 1281 条的 `effects_allow_exact_reuse` 仍是 `UNKNOWN`。这说明旧 detector
确实找到重复输入，不说明输出可以安全缓存。

`RepeatedOperatorCandidate` 的 167 条的输入适用性也是 `UNKNOWN`：它们是
profiler 聚合记录，没有逐次 invocation 的 tensor identity。把 aggregate
count 当成 167 个可复用点是错误的。

### graph 视图

1071 条 `GraphReuseCandidate` 的相同 read-state 集合是 `PROVEN`，但：

```text
effects_allow_exact_reuse: UNKNOWN  1071
no_intervening_input_write: DISPROVEN 960
no_intervening_input_write: UNKNOWN 87
no_intervening_input_write: PROVEN 24
cost_profitable: UNKNOWN 1071
```

因此 960 条不是“SCAR 过于保守而拒绝”的误报，而是图中确实出现了复用
输入的中间写入。剩下的 111 条仍然不能进入 transform：24 条虽然没有看见
中间写入，但 effect 和 cost 仍没有闭合；87 条连中间写入集合都没有完整
观测。

## 2. 为什么当前全部没有 TRANSFORM

当前拒绝有三个层次，不能混为一个原因：

### A. 真的不合法：`PROVEN_BLOCKER`

典型是 graph candidate 的中间写入：

```text
candidate reads ValueV
→ another observed action writes ValueV
→ candidate reads ValueV again
```

对 exact reuse 来说，第一次输出不能直接代表第二次输出。这个候选应当
拒绝，除非未来 provenance 能证明写入只影响无关 region 或者把整个区域一起
纳入新的 composite plan。

### B. 可能合法，但模型还没有证明：`EVIDENCE_GAP`

绝大多数 leaf reuse 落在这一类。当前 trace 对 Python/module action 的
effect 仍带有：

```text
reads/writes/aliases/escapes = UNKNOWN
rng_effect/may_raise/external_effect/ordering_effect = UNKNOWN
```

而且所有 2528 条候选的 `cost_profitable` 都是 `UNKNOWN`。所以拒绝的是
“现在就自动替换”的决定，不是对程序做出“永远不能优化”的判决。

### C. 优化粒度不对

当前 detector 主要按：

```text
CodeID + input signature
```

寻找重复 leaf。它没有先构造：

```text
module → function → call region → loop/branch → operator → kernel
```

也没有把跨层传入的 value provenance 上溯到最早稳定的 region。因此一个
第 8 层 leaf 被拒绝，可能不是 leaf 自身不可优化，而是应该把第 3 到第 8
层作为一个 composite region 重新规划。

## 3. 当前新增的自顶向下证据

`scar analyze --topdown-out <path>` 会在已有 ProgramGraph 上生成动态
region summary。它不改变 candidate，也不执行 transform。

对真实 LeWM global trace：

```text
dynamic regions: 45,888
placements:       2,528
PROPOSED:             0
UNKNOWN:          2,528
```

主要原因：

| 原因 | 数量 |
| --- | ---: |
| `candidate_effect_contract_incomplete` | 2527 |
| `input_origin_inside_candidate_region` | 2238 |
| `supporting_actions_have_no_observed_input_states` | 175 |
| `input_provenance_origin_not_observed` | 114 |
| `control_correspondence_missing` | 1 |

这个结果暴露了旧模型的具体缺口：它可以把 repeated leaf 连起来，却无法
稳定回答“输入值在哪一层产生、在哪个 region 失效、哪个父 region 可以接住
这个操作”。

## 4. stable-pretraining 常量案例

SCAR 的静态 constant provenance pass 已经不依赖包名规则地识别出：

```python
spt.data.dataset_stats.ImageNet
```

最终来源是：

```python
stable_pretraining.data.dataset_stats.ImageNet
```

其值是字面量：

```python
{"mean": [0.485, 0.456, 0.406],
 "std": [0.229, 0.224, 0.225]}
```

进一步的顶层初始化扫描显示：`stable_pretraining` 根模块有 23 个顶层
effect 记录，`stable_pretraining.data` 有 16 个，真正保存这些数字的
`dataset_stats` 模块本身是 `PROVEN_PURE`。因此当前阻塞点确实是 package
初始化，而不是常量值解析。

这已经是一个通用的 `ConstantProvenanceCandidate`，不是 LeWM 特判。它仍然
没有被自动删除，因为 `import stable_pretraining` 的初始化可能注册
OmegaConf resolver、设置环境变量、配置日志或暴露其他状态。常量事实已经
证明，包删除的 effect equivalence 还没有证明。这个区分是必要的：

```text
constant value proven ≠ import package removable
```

下一步要做的是对 import/module initialization 建立 effect summary，并用
baseline/constant-inlined execution 做验证；不能凭“最后只用到几个数字”直接
改写。

## 5. 优化顺序的改变

SCAR 后续不应继续从 leaf detector 直接进入 backend。顺序应当是：

```text
1. 建立静态 Semantic region tree
2. 建立动态 control/iteration region tree
3. 给每个 Value 建立 provenance 和 materialization 生命周期
4. 从子操作向父 region 汇总 reads/writes/effects/escapes
5. 在父层先判断 region 是否可以闭合、上移或合并
6. 再在 region 内递归选择 operator/kernel/dataflow 粒度
7. 最后才生成 OIR candidate、guard、cost 和 backend plan
```

如果第 8 层操作的输入在第 3 层已经稳定，正确结果应当是一个“可尝试把
整个 region 上移到第 3 层”的 `OptimizationRegion` 假设，而不是又生成一
个第 8 层 `ReuseCandidate`。当前 v1 还不能安全做这个转换，这正是 M2–M5
需要补齐的模型工作。

## 6. 当前结论

当前全部 reject 的根因不是一个阈值或 selector bug，而是：

```text
leaf-level repeated evidence
缺少
semantic region / provenance / complete effects / cost measurement
```

已经明确证明的可优化事实、暂时无法证明的事实和确实被写入破坏的事实现在
已经分开记录。后续开发应优先完善跨层 region 和 provenance，再重新审查
这些候选；不应把 UNKNOWN 批量改成 TRANSFORM。

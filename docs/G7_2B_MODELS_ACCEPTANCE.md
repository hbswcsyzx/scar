# G7.2b Step 1 模型基础自行验收

状态：**Verified，限于模型连接、固定源码重放和结构查询**。
G7.2b 的正向 REUSE/MOTION、G7 总门和 LeWM 优化尚未通过。

以上是本节点验收时的范围。后续窄 MOTION 已单独验收，见
[G7_2B_MOTION_ACCEPTANCE.md](G7_2B_MOTION_ACCEPTANCE.md)；它不会追溯改变本报告
的 Step 1 测试、测量或证据等级，完整 G7.2b 和 LeWM 优化仍未完成。

实现提交：`c7f68ce2474a3d995c410465def12ee19c86f48d`。
专项 gate **55 项通过**，完整回归 **995 项通过**，两项既有警告，无失败或跳过。
两份报告绑定相同源码摘要
`17215bf8ad6c67c73ccde0cd0379335025d0a00fe42bc6bfd5a474331ab549ef`；
测试期间及归档前均未变化。gate 11.412 秒，回归 wrapper 60.041 秒。
两个测试任务并发运行；下面的分析测量在它们结束后分别运行。

## 模型与代码对应

| 实体 | 含义与实现 | 当前不提供的结论 |
| --- | --- | --- |
| InvocationSlotBinding | 一次 invocation 的 formal input/state/output 或实际 READ，连接 registry handle、绑定区间与事件 | 完整 hidden-state、每次 read site、跨运行等价 |
| SourceControlFlowGraph | 独立 source-versioned suite/statement/branch/loop/exception 连接，带实际 insertion anchor | 效果、路径可行性、上移许可 |
| PrimitiveSemanticsCertificate | 由源码重新推导单次 `is`/`is not` 的身份比较、bool singleton 和有限 effects | operand 求值或 enclosing function 的纯性、REUSE 许可 |

formal port 必须属于本操作；READS_SLOT 可以引用其他操作拥有的实际源槽。
不能为了补齐输入，把源槽填进 formal port 清单。ObjectID、内容版本与存储身份
仍分开；当前 tensor registry 不能为 Python bool 出口伪造 storage。

图查询重新计算**给定图的结构性质**。独立 source replay 才建立图与源码的连接；
后续 proof ledger 必须同时绑定两者及摘要。每个查询重复重放全部源码没有必要。
当前 guard 检查 registry 的当前事件，不宣称它是历史事件的独立运行证据。

## 通用样例与真实 LeWM 源码测量

公开入口 `proof-models-v2` 分析源文件，不执行 import、callback 或目标程序。
通用样例位于外部 `testcases/proof_models`；LeWM 只作为外部源输入。
本次只选择真实 `stable_worldmodel/solver/cem.py`，不代表整个项目或 import 闭包。

| 项目 | 通用样例 | LeWM CEM 源文件 |
| --- | ---: | ---: |
| source files / lexical scopes | 1 / 2 | 1 / 11 |
| suites | 8 | 35 |
| control nodes / edges | 78 / 93 | 420 / 514 |
| source insertion points | 44 | 245 |
| loop body / backedge / zero-exit | 1 / 1 / 1 | 7 / 7 / 7 |
| 明确保留的 control gaps | 5 | 24 |
| identity primitive certificates / comparison gaps | 3 / 0 | 1 / 4 |
| SCAR 分析时间 | 1.152 秒 | 13.901 秒 |
| 分析及压缩写出 | 1.224 秒 | 14.684 秒 |
| 当前 executable VmHWM | 31,524 KiB | 76,948 KiB |
| gzip report | 67,947 bytes | 741,873 bytes |
| selected / applied transformations | 0 / 0 | 0 / 0 |

CEM 的 `solve`、`init_action_distrib` 等方法均进入独立词法 scope，内部循环被
保留。类初始化继续有未知边界；声明到方法 body 没有伪造执行边。普通赋值有
MAY_RAISE，分支双路、循环零次、用户 iterator、try/finally 等条件不会被计数抹掉。
唯一 identity certificate 对应第 104 行 `actions is None` 的原语；它不是缓存建议。

Python 为 `lewm` 环境的 CPython 3.14.7。本表是一轮源分析，包含模型校验和报告
构造的开销，不是 clean workload benchmark、收益或 LeWM 加速比。固定源码重放
仍有重复校验成本；没有据此宣称分析已轻量化。

## 反例驱动的修复

1. 重复 formal slot 现在被核心 SG 校验拒绝，不能由集合化覆盖检查掩盖。
2. 不受支持的比较保留 dispatch/short-circuit typed boundary；旧 import resolver
   也保留 blocker，不能因新增 boundary 类型崩溃或误放行。
3. `is` 只覆盖原语。调用产生 operands、链式比较和用户 `__eq__` 不被执行或认证。
4. 原语报告的语义前提集合规范排序；strict graph 重建后证书能确定性回放。
5. typed-ID CFG registry 使用确定性记录数组；重复 ID、错误源锚点、suite cycle
   和过期源码被拒绝。保存的 query status 不能代替重新计算。
6. 类方法保留独立 scope；`match` 不再误落成线性顺序。opaque 区域中声明的
   function 也与声明时的执行路径分开。
7. suite 祖先索引一次建立，break/continue/return 边界不再逐边重复遍历父链；
   source/node/edge/work/nesting/query 超限有明确失败或 UNKNOWN。

上述为 SCAR 模型/实现修复，没有修改 LeWM baseline。

## 归档核对与复现

两个压缩报告均已严格解码，重新进行 CFG/source 和 primitive fixed-rule replay。
输入、报告 SHA256 与实现摘要核对一致；LeWM git 工作区仍干净。

```bash
cd ~/AAA/scar
conda activate lewm
python scripts/run_gate.py gates/g7_2b_models.json
python -m pytest -q
PYTHONPATH=. python scripts/measure_source_proof_models_v2.py \
  testcases/proof_models/program.py \
  --out artifacts/reports/gates/g7-2b-models-example.json.gz
PYTHONPATH=. python scripts/measure_source_proof_models_v2.py \
  ../le-wm/stable-worldmodel/stable_worldmodel/solver/cem.py \
  --out artifacts/reports/gates/g7-2b-models-cem.json.gz
```

正式记录位于 `artifacts/reports/gates/g7-2b-models-*`：专项 JSON/Markdown、回归
JSON/JUnit、两个完整 gzip 报告及 measurement JSON。measurement 保存完整输入
哈希、Python、实际 executable、峰值来源和输出哈希。

## 接下来做什么

按 [G7_2B_PLAN.md](G7_2B_PLAN.md) 继续 Step 2。首先补完整 source fragment /
insertion 差量和单一直线 suite 上移的固定全义务证明；随后连接真实 Python 对象
身份与 bool singleton、精确 operand-site 和窄 REUSE 证明。任何正例仍需独立
Q、guard/fallback 与反例核对；不能把所有 UNKNOWN 改为 PROVEN。此验收不代替
正向证明验收，也没有新增 detector、backend 或目标源改写。

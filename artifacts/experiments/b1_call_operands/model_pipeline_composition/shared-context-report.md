# R3.2 P3 外部刷新与 P/V 共享内核

状态：IMPLEMENTED_WITH_FOCUSED_VALIDATION；仅本模块范围，非完整 R3/M0–M2 通过声明。
基线：`f0dbbd478095b07a684fe4d35ba3b53be20ed17c`。
设计记录：`design/evidence-lifetime.md`，SHA256 `48d2a52ea4641b2e9cccc2c0ef123f4c1e85fa736ef6868aca67904d563bd28d`。

## 实现

- `validation.refresh_external_context(base_ctx)` 复用已验证的 canonical flow/call 关系和基础缺口。
- `_external_stages` 是 construction 与 refresh 的同一序列：source inventory → resource → work → order → evidence binding → Q → D → source bridge → write → produced → V。
- 每次 refresh 创建一个新的 `ExternalSnapshots`；各派生结果重新建立。context 自有可变容器复制，catalog 仍是调用者输入，由新 resolver 核验与脱离；不向 construction context 回写。
- `ctx.external_preparation` 给出 `canonical_flow_reused`、实际 `stage_calls` 和 `cost_scope`。record/FK、容器准备、snapshot/replay、最终结果复制不伪计为 4096 次派生操作。
- `production_shared(ctx, read_id, *, budget: ValidityBudget, include_context_gaps=False)` 不 detach；每次 P 遍历直接计入同一个总预算，kind 为 `production_query`，P view 仍列原有细分成本。
- `validity_shared` 同签名，不调用公开 P 或中间 deepcopy。其 `budget_used/budget_costs` 是本次 read 增量；总账在调用者持有的 budget。
- shared 内部默认不复制 context 全局 gaps；顶层可列一次。read 局部 gaps 保留。公开 P/V 仍为原签名、4096 默认值、原 dict 结构和独立 detach 边界。
- 零余额不产生新 allowance：保留 read/demand/pending-source 与 `TRUNCATED`；顶层可以更早 skip 并保留 ledger。

## 已运行的有限验证

全部 Python：`source /home/zyf/miniconda3/etc/profile.d/conda.sh`、`conda activate lewm`、`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`。
具体 Python 版本、完整 pytest 命令、源码前后 SHA、stdout/stderr/JUnit 均随下列 attempt 保留。

1. `python .../model_pipeline_composition/focus.py shared_context tests/unit/test_execution_composition_refresh.py tests/unit/test_execution_composition_budget.py`
   - `shared_context/attempt001`：首跑 **16 PASS / 1.69s**，exit 0，无首败。
   - 随后仅把一个不等式断言改为精确核对 nested P view 不含全局 `source_runtime_unverified`。
   - `shared_context/attempt002`：最终 **16 PASS / 1.68s**，exit 0，绑定最终 owned 源。
2. `python .../model_pipeline_composition/focus.py pv_compatibility tests/unit/test_execution_production_query.py tests/unit/test_execution_validity_query.py`
   - `pv_compatibility/attempt001`：旧接口有限兼容集 **45 PASS / 4.57s**，exit 0。
   - 与上面有不同验收目的，不合计为全仓覆盖率。

新增用例使用现有真实 canonical fixture：resource-only allocation、work-only materialization、order-only EEG binding、真实 mixed queue/work ContentRead。
覆盖 catalog 内容突变拒绝、缺 catalog 保留 gap、基础/外部缺口重建、mutable map 不共享、一次 preparation inventory replay、两个真实 read 共用总预算、零余额、内部不调用公开 P/不 deepcopy、公开布局/预算 guards。
没有手写 FakeCtx、模拟 native ready 或手填 PROVEN。

## 冻结 owned 文件 SHA256

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/execution/validation.py` | `94dbd22027c328fa2a33b678f5a555f16c176f61c0d1f18bab80776a7260c930` |
| `scar/ir/execution/production_query.py` | `dd275a767d8da5f54f5abf5e67126ed6c471ba10a25ec9d00f22a773df7a1737` |
| `scar/ir/execution/validity_query.py` | `fbf10cb04c44f0e3562b7b746b846ca2c77d09905689f9ab1adb13f43f012780` |
| `tests/unit/test_execution_composition_refresh.py` | `205a4d49e9c2544842ab2a0d0ca12e61a1a575658bd883b0591ed7d3d59e8c80` |
| `tests/unit/test_execution_composition_budget.py` | `619d717ca4ae43f9c8fee818eb2d017a192adfe8770e09677c5c0db4f8390be9` |

## 边界

root 的公开 composition/ledger/scope/routes 不由本报告验收；它们须调用上述 fresh/shared 入口并只在最终边界 detach。
同一 resolver 表示一次查询中的按内容地址核验，不能宣称所有外部图处于同一个物理时间点。
共享预算约束派生遍历，准备/replay/record validation/复制成本另列；不宣称总 CPU 由 4096 完全限定。
本实现不新增生命周期、producer、state、wire、endpoint parser；不把 host RAISE/Return、work terminal、quiescence、borrow release、close、retirement 或 persistence 等同。
Source/runtime/native 可用性与完整捕获仍未证明，authority flags 维持 False；未运行 component/full、GPU 或 LeWM 工作负载。

# V 核心实现有限复核

结论：**PASS_WITH_SCOPE**。未发现本轮范围内的实质正确性阻断。审查只覆盖下列冻结快照中的 validity/public-query/codec 接线；不代表 R2 完成，也不证明源捕获闭合、native 可见性或数据就绪。

## 快照

工作树 HEAD：`f2b4672d9555348dcd05da62a8cd126711ef22f9`（产品修改未提交）。

| 文件 | SHA-256 |
|---|---|
| `scar/ir/execution/query.py` | `b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec` |
| `scar/ir/execution/validity_query.py` | `3291144d708a585a4bb4518d1634c35ade5a423657da0e448f31df23d1877ad7` |
| `scar/ir/execution/validity_validation.py` | `05d79cd278df1676da1ecdccfcfdef80c8bce5139e74517c9c9dcd9b7e189f1c` |
| `scar/ir/execution/validity_stability.py` | `c58f3acad50f8b62423335a17c118e9d62e0373aebb2d8c06bccb3242dab033b` |
| `scar/ir/execution/validity_order.py` | `f5324c4b78ec74c416038d787d2dff50286d4318225a2aad35063bde43552586` |
| `scar/ir/execution/validity.py` | `b197d4e06cebe789f5369abd9c50abafca478de623eed2c448d8e061a7c6e9e7` |
| `scar/ir/execution/validity_budget.py` | `e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10` |
| `scar/ir/execution/production_ranges.py` | `e657ea85c609c8e6f975b7bcfa9d0787f6ce00bc1cd704362a4de69c01f69f81` |
| `scar/ir/execution/production_validation.py` | `0692b7f40b3fbad9cf51742cc506ef87481e859023f8c6112ec28d21dd5d2366` |
| `scar/ir/execution/codec.py` | `b8520a675e5c07d1a6c6cfbba1d1efea790c445535fef4c2e3897d5b2bea7580` |
| `scar/ir/execution/validation.py` | `41baacad27c685901fd0aa2d2607b95d2211d76a3af1da66af6aa32b4231a1fc` |
| `scar/ir/execution/model.py` | `5b7bcefb18bfaaf4b8548f2ebdd4c8346046913dcb5adac528929f85306d5a6d` |
| `tests/unit/test_execution_validity_connections.py` | `ae8d232b20240c951655cc3c944125e3dbd6936f0d80d7fb4a60820d88f8098b` |

## 复核结果

- **预算与刷新顺序：** `ExecutionIndex.validity` 校验精确正整数预算、精确 `ContentReadID` 类型并重验 ID，再调用 `_content_context`. 无效参数不会刷新外部快照。新增的两个公共 API 回归均通过。
- **查询边界：** validity 查询从 P 的独立源候选开始，再接声明的 write、actual production 与 support；不接收调用方贡献清单。结果区分已知覆盖与 conditional 覆盖，`source_reconciliation` 固定为 OPEN；来源、native/runtime visibility、转换权限保持未验证。每个 needed portion 是 AND，各 fragment 的可匹配 support 是 OR；失败/取消的终态结果不能用请求范围补齐，删除 write 关联也不会缩小独立候选集合。
- **状态、区间与失效项：** Completed 支持核对 actual producer、域和到 read-start 的路径；Ordered 支持只接受 queued consumer，并查询该 writer 的 `WorkEnd → consumer WorkStart`. 稳定性检查使用完整读取区间、canonical WRITE/RW/调用边界、独立 source 候选、target lifetime 与 handle end。无法解析的 alias、native phase、来源完整性或协议保留为条件/缺口，不当作无写、无失效或 runtime proof。
- **Host / Work 分流：** `EstablishedProduction` 拒绝 `WorkWrite`；host ordinary completion 用 AFTER、INVOKE 用实际 EDGE。work 结果仍走既有 `OutcomeProduction`、准确 outcome 与 effect-frontier，不因 host establishment 旁路。未知/失败传播继续保留条件。
- **Byte-prefix guard：** 与基线 `f2b4672` 的旧 `produced_errors` 段逐项核对；提取后的 `resolve_actual_range` 保留 raw 行与 SHA、闭合 profile 字段、精确非 bool 字节计数、同一 scoped ValueGraph、materialization containment、allocation、连续 rank-1 `uint8` 形状/stride、offset、请求与实际长度、raw result locator/字面结果匹配。状态 frontier 和 work ticket 仍由原生产验证器核验。解析声明始终附带 native/source/content-stability 未验证缺口。
- **Wire/FK：** v6 仅在 validity 表非空时发出，含 validity 能力的图拒绝降级到 v1–v5；旧 schema vocabulary 不接受 validity tags/fields。保留的 v1–v5 golden 用冻结字节重放，独立 v5 proof 绑定原 codec revision/SHA；原 production codec 的“不支持版本”测试保留同一测试名/参数化 case 名，将不支持版本推进到 v7。

## 定向验证

实际命令：

```text
conda run -n lewm --no-capture-output env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_validity_connections.py --junitxml=artifacts/experiments/b1_call_operands/model_validity/review/attempt001/junit.xml
```

结果：**2 passed, 0 failed**（0.51 s，exit 0）。原始 stdout/stderr、JUnit、命令与 exit code 保存在 `artifacts/experiments/b1_call_operands/model_validity/review/attempt001/`。测试用真实 `host_lifetime_execution` 构造索引，并在无效预算（`True`、`0`）及 wrong-kind/subclass `ContentReadID` 路径上监测 `_content_context`，确认刷新未发生。

未运行 validity query 全套、组件门、全仓、LeWM、GPU 或任何目标 workload。本报告只核对代码与上述两个新增 guard 回归；不把现有未运行测试计作本次验证结果。

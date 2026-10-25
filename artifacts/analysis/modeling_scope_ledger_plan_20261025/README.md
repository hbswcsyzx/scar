# 统一 Scope / CoverageObligation 方案

2026-10-25。**设计规格，尚无生产实现或真实 ledger 生成。**
说明见 [MODELING_SCOPE_LEDGER_PLAN.md](../../../docs/MODELING_SCOPE_LEDGER_PLAN.md)。

- `proposed_api.pyi`：拟定公共记录、封闭 union、enum 与 API 签名；导入名称复用现有原类型。
- `record-schema.json`：由 stub 提取的精确字段/类型/tag 规格，附跨记录不变量；不是已部署 codec。
- `producer-map.json`：独立原分母、准确原定位、最小现档切口及完整 dispatch 库存发布缺口；可直接引用新 native-capture-batch artifact。
- `evidence-rules.json`：证据复核与拒绝规则；完整审核在 producer/发布 gate，普通 query复用精确既验收收据。
- `schema-changes.json`：实际需要的 schema 变更与原 IR/数据库权威不变的边界。
- `source-receipts.json`、`plan-receipt.json`：所读源码及本方案文件的 SHA/大小。

重建规格：在工作树根运行
`python3 artifacts/analysis/modeling_scope_ledger_plan_20261025/build_specs.py`。
该脚本只解析本 stub、读取列名源码和文档，不 import SCAR、不读原档或 raw、不执行目标或测试。
首次实现优先原全 source inventory 与当前 source/dispatch 分母；其余域有准确集合义务与不足，
保持整体 OPEN。当前 39,796 dispatch 是旧报告期望，不是本方案重测的数量，也不硬编码进 producer。

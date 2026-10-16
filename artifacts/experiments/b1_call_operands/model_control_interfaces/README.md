# C0 词法控制与协议值组件证据

- `language/`：独立CPython 3.14.7语言见证，19项通过；不import SCAR。
- `records/`：记录构造检查，118项通过，不证明图或运行语义。
- `graphs/`：三个手工IR结构图及16项组合检查；runner/fixture失败与终态分别保留。
- `review/INDEPENDENT_DESIGN.md`、`review/VALIDATOR_REVIEW.md`：独立设计/静态审查，明确C0/C1边界。
- `review/invoke-forwarding.xml`：首轮ProtocolValue漏接ProgramGraph允许类型的3项失败；`.final.xml`是修复后3项通过。
- `component/`：354项四准则正式验收；源指纹及全部case在report.json。
- `full/`：冻结implementation后的单次全仓回归；执行前只有独立driver。

原v5 wire由旧提交隔离导出，依据在 tests/fixtures/program_graph_v5_wire_provenance.json。
CLEANUP仅是词法声明，完整finally/context及source/runtime对应仍未完成，公开权限固定false。
后续C1设计若与正式回归并行，仅写ignored报告，不改变冻结源码；不把验收时间当性能数据。

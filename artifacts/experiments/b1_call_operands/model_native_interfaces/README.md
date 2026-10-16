# P1 thin native interfaces：证据索引

基线 `126d56e`；冻结实现 `79bf2a9`。规格见
[M1_NATIVE_INTERFACES](../../../../docs/M1_NATIVE_INTERFACES.md)。
这是类型/规范端口组合组件，不是自动 provider adapter、LeWM 建图或优化。

| 证据 | 含义 |
| --- | --- |
| [records](records/agent-report.json) | 30 项严格记录定向测试，未证明 artifact 的真实性。 |
| [graphs](graphs/owned-tests.post-cleanup.log) | fixture/query/codec/CLI 的有界定向结果；同目录保留启动和负例 harness 失败。 |
| [initial component](component.json) | 初版 164 PASS，不覆盖随后独立审查发现的 B1。 |
| [integration review](review/integration-review.md) | 未参与集成编写的代理审查；B1 合法旧 ID 子类索引回归。 |
| [original probe](review/results.json) | 四项检查 PASS，一项 REGRESSION；原证据保留。 |
| [after-fix probe](review/results.after-fix.json) | 相同五项 IR-only 检查均 PASS，不包含 Torch/workload。 |
| [closure](review/closure.md) | 限定关闭 B1；不将 records 自审或全模型算独立通过。 |
| [final component](component-final.json) | 168 PASS / 8.815s，376 文件冻结源指纹。 |
| [full regression](full/report.json) | 冻结全仓运行的实际终态、JUnit、源/fixture 前后哈希和专属临时目录清理。 |
| [v7 generation](freeze_v7.py) | 使用隔离原 revision/原 codec 生成旧 wire，而非新 dataclass 倒推默认值。 |

`root-exit-micro.log` 保留了一个错误 fixture 假设：既有 core 不允许无 terminal
的幽灵出口；后续测试改为要求拒绝，没有削弱核心验证。
组件与全仓成本均为验收成本，不能当作 workload wall-clock 或加速比。

[next-state-boundary](review/next-state-boundary.md) 与
[next-model-order](review/next-model-order.md) 仅为 Proposed 后续建议，不计本门实现。
旧的 `review/design.md` 是 P1 收缩前草案，不属于本次验收和归档清单。

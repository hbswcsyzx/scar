# 自动验收与版本管理

各 gate 由开发代理执行验收、记录证据、修复失败、重新验收和提交，不需要用户
逐项批准。阶段报告和 commit 是继续开发的检查点。

每个 gate 使用 `gates/gN.json` 声明验收条件与具体测试入口，通过以下命令执行：

```bash
conda run -n lewm python scripts/run_gate.py gates/g1.json
```

脚本为每条条件记录实际收集并执行的测试。测试缺失、跳过、失败、命令异常或测试
期间源码变化都不能通过。报告包含 Git revision、工作区状态、逐文件 SHA256、
命令和测试结果，避免未提交源码与报告中的 revision 不一致。

工作顺序：实现和反例测试 → gate 测试 → 修复 → 实现 commit → 测试该 commit
并生成报告 → 报告 commit → push → 进入已满足依赖的下一 gate。
完整测试只在阶段集成需要时执行，局部修复先运行对应反例。

## G1 复核

旧 `artifacts/reports/gates/g1.json` 保存为历史结果。2026-09-22 的复核发现：

- 多条验收条件共享一个测试命令的退出码，没有逐条验证；
- OIR 允许删除目标 region 外的定义；
- JSON 解码忽略 schema version，重复 ID 会静默覆盖；
- 部分循环、关系端点和跨图 materialization/version 不一致未被拒绝。

因此旧 PASS 不足以支持其完整声明，后续以 `g1-verified.json` 的逐项证据为准。
修复关注 schema 能否拒绝不合法结构；它不证明任意用户提供的 `PROVEN` 声明为真。
自动构造语义证明、选择 region 和确定修改方案属于后续 gate。

每个后续报告也必须注明 scope 和未验证项。FAIL 或 PARTIAL 不意味着向用户请求
验收；开发代理应继续修复，除非确实缺少本机无法获得的信息。

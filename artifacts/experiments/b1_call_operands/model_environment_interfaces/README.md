# 函数环境与入口分区组件证据

- `component/`：326 项中间通过记录；随后自审发现 formal/free-variable 静态槽身份冲突。
- `review/slot_collision.before.json`：修复前缺陷复现，不能当作合法例子。
- `component-final/`：修复及新增反例后的 327 项终版通过记录，源指纹独立标明。
- `historical/`：从原版本隔离生成 v4 wire 的依据；不能用当前类型反推旧版。
- `review/`：独立评审，旧评审对应各自列出的旧 source hashes；最后 slot 修复另存 closure。
- `full/`：首个调用只因短 HEAD 参数被 precondition 拒绝，未启动 pytest，原失败保留。
- `full-final/`：完整 HEAD 的一次冻结回归，2,835 项通过；运行前目录仅含独立 driver。
- `acceptance.json`：终态范围、revision/源指纹、完整报告链接及未完成项。

独立语言探针、类型构造检查和分区检查的原始证据位于
`artifacts/experiments/model_environment_interfaces/`；路径差异源于分工，保留原始文件。
本批验证静态声明，不代表自动恢复函数环境，不授权优化；完整模型仍未完成。

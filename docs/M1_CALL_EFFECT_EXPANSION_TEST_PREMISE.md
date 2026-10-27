# 新增 Graph 子类用例的前提修正

本补充在实际失败和隔离基线探针之后、再次修改新用例之前冻结。
不修改本门原范围、旧测试、旧 wire、已有地址校验器或任何优化规则。

root 初审仅从通用 `record_errors` 的 isinstance 推断 ProgramGraph 子类在公共入口
中应合法，新增一个回归要求加关系前后均通过。这个推断不完整。
首轮及修正 CFG 后的第二轮都在**添加新关系之前**返回原 `address_graph` 问题；
新增关系校验器尚未被调用，所以不能把该失败归因为新增 exact Graph 检查。

`subclass-baseline-probe.json` 使用隔离 `51a6eb3` 原代码，先确认原图合法，再构造
相同字段的 Derived：旧 reader24 的 `validate` 返回 `address_graph`，旧 ProgramIndex
以同码 ValueError 拒绝。原地址校验器 SHA 为
`03c1d4f8b3e9fe991f902a4e775051b2fbc8f048b49e4758fb3431833937a096`。
此限制在本门之前就存在；它与早期 ID 子类兼容性是不同问题。

因此只修正 **NEW** 测试
`test_valid_program_graph_subclass_retains_public_expansion_validation_and_read`
的错误前提，保留该节点和所有历史失败快照：

- 先记录 Derived 原来的受控 `address_graph` 拒绝，不能先假设公共通过。
- 加入完整展开后，既有公共 validate/require_valid/ProgramIndex 的拒绝必须相同，
  不能增加崩溃或用新关系掩盖原问题。
- 新关系局部校验对字段正确的 Derived 可正常返回，record 和 ID 仍 exact。
  普通精确 ProgramGraph 的新 public read 正例已由其它 CALL/INVOKE 节点独立覆盖。

新增局部校验器采用 isinstance 是与模型容器的通用契约对齐；不称为已修复旧公共
Graph 子类支持。此补充不将一个失败转换为广义通过声明，也不扩改其它旧校验器。

# Program27：保留旧义务的版本迁移

2026-10-20，基线5fd5a7f。新表必须有新的 capability wire；旧1–26不会多两个空字段。
Execution8不变，原Fixture不改。16个旧codec测试文件的原字节保存在本批归档
`legacy-codec-before/`，第一轮913/38f767…首败也保留原测试源码。

允许的改动只有三类：

1. 当前最高支持版本断言26→27，具体旧document版本26/25/24等保持。
2. “尚未支持的未来版本”输入27→28，bool输入与拒绝条件不变。
3. 旧document字段集合从当前dataclass投影时，显式排除新增两空表。

独立子进程旧encoder的max26/25等断言完全不改；它从冻结git源码运行，不从当前
codec配置反推旧wire。新增v26 oracle测试锁源码和fixture SHA，实际逐字节比较。

## 原case身份迁移

以下七个参数化节点只将`[27]`改为`[28]`，同一函数与原未来版本拒绝义务保留；
同函数的bool节点ID不变。其余原case身份不迁移。

| 模块 | 测试函数 |
| --- | --- |
| test_program_method_lookup_codec | test_program_graph_rejects_future_or_boolean_schema_versions |
| test_program_session_occupancy_codec | test_boolean_and_next_future_versions_do_not_enable_the_subject |
| test_program_lookup_fallback_codec | test_future_and_boolean_schema_versions_remain_rejected |
| test_program_call_effect_expansion_codec | test_boolean_or_next_future_version_cannot_enable_effect_expansion |
| test_program_async_initial_control_codec | test_boolean_or_future_schema_does_not_enable_async_initial_control |
| test_program_await_acquisition_codec | test_boolean_or_future_schema_version_is_not_a_capability |
| test_program_exception_match_codec | test_future_and_boolean_schema_versions_remain_rejected |

验收须核原catalog2135义务的身份守恒（含这些显式映射），以及上批231的直接选集
均在本次适用范围内复验。不能只报新节点数，也不能把新纳入的既有codec case计为
新实现能力。原case保留但未重跑整个目录的范围须在报告明示。

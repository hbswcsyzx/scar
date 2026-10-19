# D3一项旧反例的显式输入迁移

基线 `2fc957192e710d1db1210c7b7a1073313f2e16d6`；原完整文件字节另存
`original_test_program_await_general.py.txt`，旧case/失败仍在原归档与远端提交。

唯一旧文件变更为 `tests/unit/test_program_await_general.py` 的
`test_general_await_known_generator_coroutine_cannot_continue_as_iterator`：

```python
graph, details = await_general_program(result_kind=ResumableKind.GENERATOR_COROUTINE)
```

改用 `unqualified_general_program()`，另加局部import及两行迁移说明。该helper
保原GENCORO Create、正常CFG及推进操作；只移除typed qualification row、该row
consumer附件，并将两个Get展开qualification ref改具体gap。原原子操作/两分支
不删，legacy坏返回继续advance的原issue断言及caseID不变。

原因是D3区分静态不可行接受腿与实际错误接受：原完整typed check图应能表达
合法TypeError执行，不能静态全图拒绝。新独立tests覆盖qualified静态有效、真实
reject合法、真实accept矛盾、untyped仍拒、错bool/旁支bypass不能豁免。不是删除
旧安全义务或只更改期望让绿测；精确合同、独立反对性审查和首次2P4F均保留。

本轮归档门须逐字节复算这一个替换，其余全部已有tests/fixtures与基线相等。
不得写“所有旧tests字节不变”。所有上一1437 caseID仍须保留；无版本词汇迁移。

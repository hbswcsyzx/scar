# root work/materialization 集合连接：独立只读审查

结论：**PASS_WITH_SCOPE（静态源审，无新增测试/实验）**。只核此次集合对应，不签核runtime捕获完整性/Endpoint协议或整个R3。root所报before 10F7P / after联合148P是root执行记录，本agent未重复运行。

- `work_validation.materialization_key` 取原artifact SHA/schema/size + MaterializationID，不用URI；因此URI alias不产生新identity，metadata/hash不同仍不会按裸ID合并。
- `check_work_materialization` 只读取传入exact ticket的不可变声明集合；COMPLETE漏原read/write/Mat-retention target为结构issue，PARTIAL/UNKNOWN为gap。其它ticket有同Mat不补当前ticket。
- `content_validation`对ResourceConsumer已存在ticket和非Unresolved placement调用helper；StorageContent/EndpointContent均提供其原Mat，未知endpoint selector不豁免其明确声明的Mat集合关系，也不因此解释endpoint协议。
- `production_validation`只对确切WorkWrite调用；HostWrite/External不会被迫造ticket。placement即使后续有独立FK问题仍不会通过错误ticket成员表归并。
- `work_validation`对retention.target精确MaterializationRef才把其视为Mat borrow并检查；仅以Mat作AllocationTarget的佐证，不等同内容version被借用，未把整个allocation的所有Mat加成义务。
- 一次work_errors按model.submissions构建per-context frozenset；fresh `_content_context`浅复制的是相同immutable model的成员声明，随后用新ExternalSnapshots重查实际VG/D/Q/P。该缓存不保存外部可变graph/source解析或native满足状态，未发现会因URI alias或前一次query结果修改而授新成员关系。
- helper不把COMPLETE声明升级为native capture/held/free证明；existing source/native/protocol gaps保留。

当前17case覆盖read/write/retention各自complete遗漏、partial/unknown gap、合法complete、URI alias、错ticket及placement unknown。此文件没有单独Endpoint正反和Index构造后external graph变更用例；上面的两项仅静态审读，不能写成此17case实测。已有fresh-source机制的其它验收不能自动改名成此新组合已测。

本审查没有确定的阻断问题，不新增无具体风险的测试请求；后续统一组件由root运行。

## 所审文件指纹

- `scar/ir/execution/work_validation.py` SHA256 `1cccc760cb93268f4e282417e1d5fe8f1034870c474866237246ea7bae9e6984`
- `scar/ir/execution/content_validation.py` SHA256 `92afdb38caf716c4187c4a2a9173207c8dc2cc6110a3fd3d83f22852b67ed49a`
- `scar/ir/execution/production_validation.py` SHA256 `6eda717b717581c91b9301fcb6995e199ae98fb2f618066f79dfe509819da256`
- `scar/ir/execution/query.py` SHA256 `94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a`
- `tests/unit/test_execution_work_materialization_connections.py` SHA256 `a2587b6546130b62231857f9b1b5e761364148f3689a6095518f519161a6bbf7`

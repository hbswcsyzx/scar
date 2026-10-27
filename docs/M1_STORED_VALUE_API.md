# 原存储值关系与来源查询

依据[计划](M1_STORED_VALUE_PLAN.md)及[设计补充](M1_STORED_VALUE_DESIGN.md)。
规范节点仍是 Operation / Value / StateLocation / Region / Resource。

## 两条薄关系

`StoredValueWrite(site, effect_index, payload, completion=None)` 直接引用原地址精化
的准确 effect 和 owned payload Use。其含义是：所选完成后的该直接槽含此输入值。
普通访问使用原 StateAccess.after；INVOKE 必须指定自身准确 ControlEdgeReference，
分别定位原 signature 的 state slot 和 landing formal。未声明 R 不代表异常回滚。

`StoredValueRead(site, effect_index, result)` 声明：own result 是原 before-state
下该直接槽的值。result 为原 OperationResult 或 InvokeLiteralResult（已有通用
completion-slot 载体，其名字不要求内容是 literal）。INVOKE 读取只能选 own NORMAL。
payload/result 仅普通 Data/Reference，不是 state、binding token 或异常协议包。

新表是 `ProgramGraph.stored_value_writes` / `stored_value_reads`。owner、selector、
输入、版本及结果没有复制成第二份事实。相同 read result、重复 write key 及
同完成静态可判同最终槽的多 post 声明拒绝；stage 不代表可任选的最终版本。
动态 selector 静态冲突键使用原 Data ValueID，不使用 UseID 或用户 `__eq__`。

未知地址仍可保留为合法 IR；它的存在不授来源支持。关系本身是所供直接槽合同，
不是从属性名已经验证 getter、setter、descriptor 或 native 访问。

## 执行查询

```python
index.stored_value_sources(result_site, operation_occurrence_id, budget=4096)
```

此处 result_site 是准确原读取结果 site。接口刷新外部上下文并返回 detached
receipt，先保全部原 read/write 声明与实际 operation 库存，再做共享预算的派生。

| 字段 | 含义 |
| --- | --- |
| read_inventory / write_inventory / operation_inventory | 完整原分母，缺采或预算不删源。 |
| read | 原声明、实际操作、输入、before/current、own result、所选完成及缺口。 |
| candidates | 每个原 Write 的每次实际 occurrence；不按静态操作合并 loop/call。 |
| candidate.binding | 真实输入、payload Use/value、当前 state、post 及准确 AFTER/EDGE。 |
| candidate.address | owner 的原 copy 或独立 scoped ObjectIdentity、selector 比较。 |
| candidate.interval | 原 state_preservation 的全部实际路径/效果/调用/阻断依据。 |
| match / source_value / recipe | 唯一条件性来源成立才 True；不是持久 copy edge 或变换授权。 |
| budget / cursor / gaps | 一个总派生预算；截断清除候选 True，保原库存及未完成位置。 |

当前执行求值明确支持 ReferenceOwner 的一个直接单槽。ObjectField/CellContent
直接比较；DynamicField/Element/NamespaceKey 只使用准确 Data 端点的原 copy 或
builtin LiteralOrigin 依据。Reference key、未知 owner/selector、聚合范围、多层
解引用路径保持 Unknown。相同 Use 文本、类型、字段名或不同 Location 不是证明。

普通 copy 有共同原祖先才核 copy compatibility；独立候选身份不同是局部不匹配，
不能污染其它候选。同对象不表示对象内部内容不变。最终 payload→result 支持来自
新 pre/post 合同、真实端口、当前版本和透明区间，不要求它原先已经有 copy edge。

透明区间沿用现有任意 WRITE/RW 保守失效、原 CFG/selected visit、准确 caller
和完整 callee effect expansion。旧 P 被新写阻断；新 Q 的 post 可重新提供来源。
同完成不确定 alias 的多个 post 来源不能任取一个；预算不足不能授成功前缀。

## 能力与权限边界

仅有新表时使用 Program27。旧1–26字段/tag/字节及 Execution8 保留；新表空不能
以27伪装能力。旧码最大/未来版本测试的[显式迁移](M1_STORED_VALUE_MIGRATION.md)
不修改旧 wire 应保持的版本。独立冻结 Program26 encoder 核旧字节。

source/native/runtime/value 身份与 transformation 权限均 False。该查询不自动
从 Python 源或 native 层生成合同，不替 F19 消费者完成后续整合，也不证明任何
Tensor 版本恒定或可以 cache。完整第一阶段与 LeWM 自动建图仍按原门验收。

# Native schema → 原有 ports 与实际 ETO 参数槽

状态：已实现，并对已保存的最新成功 LeWM 联合原档完成一次公共 reader→schema桥→
全量槽位/端点核验。没有执行新采集、forward 或测试套件；完整程序建模仍 OPEN。

## 真实原档验收

2026-10-23，[完整记录](../artifacts/experiments/first_stage_native_schema_20261023/README.md)：
100 个唯一 schema 全部解析，100 个原定义新增 481 个 ports、100 个 PARTIAL effects、
593 条原 SG 边。642,778 个实际 Tensor 槽全部核验：467,756 个连接到准确 formal slot，
175,022 个保留 UNQUALIFIED，原因均为原 provider 观察没有 op_schema。无解析或
类型/ordinal 失败；此数量不代表 optimization rejection。

原 instance/ValueGraph 身份及全部实际槽 path/reference/locator digest 保持；公共
IRBundle 校验和独立全端点核对通过。独立报告 gzip 34.2MiB，SG delta 108.3KiB，
绑定原 bundle 的 stored SHA，没有另存整个 2.09GB 原图。

```python
from scar.trace.native_schema import recover_schema_contracts
report = recover_schema_contracts(native_result, provider_revision="cf30153c4c131c8164ee7798e5022d810682e2cb")
```

调用方先导入 native 原档。模块核对 imported provider、本机 Torch git revision 与
支持版本完全一致；只解析已有 definition.metadata.op_schema，不打开其声明的路径、
不执行目标、不重新计算输出。返回独立 JSON-safe 报告，同时写入
`native_result.report["native_schema"]`。

## 创建的原有实体

- `SemanticGraph.ValueSlot`：每个参数/返回值一个真实节点，按 schema 原顺序接入
  definition.input_slots/output_slots，配 consumes/produces 边。
- `EffectSummary`：schema 声明的 may-write 参数和 alias 参数；接 definition.effect_summary
  与 HAS_EFFECT。may-write 还有附带 DECLARED 证据的 WRITES_SLOT 边。
- 完整原 schema、real_type、kwarg-only、out、默认值是否存在及局部 before/after alias
  集合保留在真实 slot/definition。未写标注不等于对象不可变，slot.mutable 不被设为 false。

它们属于原 SemanticGraph，没有再造 operator graph、Tensor graph 或新的 protocol。

## 实际槽如何连接

每个原 ETO instance.tensor_slots 已有 role、ordered_path、provider_reference 和原档
locator。模块逐项检查首个 ordinal 对应 schema 参数/返回顺序，再按 JIT 类型检查
实际 List/Tuple/Optional 容器路径，直到 Tensor 叶；核 provider reference 确实存在。

合格记录在原 tensor_slots 附加 `native_schema_binding.formal_slot`，指向上述实际
ValueSlot 节点，报告 bindings 同时保存两端 ID、原有 slot index、完整 path、原档
locator 和 QUALIFIED 状态。非 Tensor、越界、vararg、未支持类型保留 UNQUALIFIED
及原因；不会丢掉原始观察。重复实际引用仍保留不同槽位。

没有可解析 schema 的 instance 也逐个列入 `unqualified_without_schema`；其每个原
tensor_slots 都附 UNQUALIFIED 原因，原 path/locator 保持。报告不再复制这些原始
大数组。collector marker 的空 schema 同样不会被发明成应用函数签名。

这不是新增 `SLOT_VERSION` correspondence：当前逻辑版本尚未建立，不能发明
ValueVersion 来满足字段要求。此绑定只证明 provider 观察的位置与 formal port 的
对应。ETO boxed 输入顺序遵循固定 provider/schema 契约；scalar 值和整体原档 arity
没有被重新读取，未宣称它们完成了数值核验。

## alias 与 effect 边界

- alias 字母只在一条 schema 内有效；可能相交只表示 may-alias，不创建实际 ALIASES。
- Python AliasInfo 未暴露 C++ containedTypes。Tensor(a!)[] 的外层集合可能为空；
  容器 alias 明确标缺口，不当作无 alias。wildcard 只作保守可能相交。
- `str(arg.type)` 可能把 SymInt[] 显示为 List[int]，原 schema 与 real_type 必须保留。
- schema 不关闭 RNG、外部写、异常、ordering、allocation、free 或 ready。所有效果
  summary 保持不完整，registered alias-analysis kind 也未从 schema 文本恢复。
- `a→a` 不能推出一定 view；may-write 不能推出值确实变化、全覆盖写或异常未写。

已有最新 LeWM 原档压力核对（只读解析，发生于模块实现前）：zero_ node37
`Tensor(a!)→Tensor(a!)`，copy_ node63 的目标 a!、src 无写标注，view node1505
`Tensor(a)→Tensor(a)`。这些不是按算子名称触发的规则，模块不包含这些名称。

## 后续原有 IR 的连接

canonical 操作/调用对应成立后，才能把 formal 参数连接到原 StateAccess 和
StateAddressRefinement(ReferenceOwner)。alias 未闭合时保留共同 memory 状态域，
不能按 ObjectID 拆成互不相交的状态。写入推进状态代次不等于已经证明内容变化。

ProvenanceRecord 需要真实输入版本和 producer；Materialization 需要逻辑版本、
representation、device、实际 allocation/region 及 ready 证据。此模块不生成这些
当前证据尚未支持的实体，完整程序建模仍保持 OPEN。

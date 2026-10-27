# 当前对象身份与历史状态的独立依据

依据[M1_FRAME_IDENTITY_GUARD_PLAN.md](M1_FRAME_IDENTITY_GUARD_PLAN.md)。本接口不添加
核心实体、codec或optimization backend；它是原ValueOccurrence及其身份声明的派生比较。

## 1. 三种关系分别问

| 关系 | 回答 | 不能代替什么 |
| --- | --- | --- |
| original copy | 这个准确值由哪些原Use/CFG/call端口传来？ | 相同内容不等于copy，相同对象不等于已知来源。 |
| current object identity | 这两个准确Reference occurrence是否声明为同一对象？ | 不证明对象内部数据版本不变，也不证明中间堆字段未变。 |
| historical F | 当前所见frame是否有已完成且未重置的真实终结历史？ | 请求COMPLETE、native closed bit、资源release及可缓存性。 |

例如Create时R保存B1，随后R字段被写为B2：Create/body来源不能压过当前READ独立
提供的B2身份。另一方面，若当前predicate确实读取B1，R的其它变化或未知数据内容
也不能自动抹去B1的历史F。这个推导仍依赖原no-reset生命周期合同及实际顺序。

## 2. `ExecutionIndex.object_identity(source, target, *, budget=4096)`

参数是准确ValueOccurrenceID，公开入口检查type/FK并使用fresh external context。
内部比较与history共用一个ValidityBudget，不改变`pair`或任何copy recipe。

`inventory`始终有source/target两个原端点，包含原definition、denotation、
declared/resolved basis、process/run、registry检查结果。缺采和budget不删掉端点。

- 两端为Reference、同实际process/run，独立ObjectIdentity对应相同精确artifact
  namespace及已注册同ObjectID：条件性True，`DECLARED_SAME_OBJECT`。
- 同namespace的不同ObjectID：局部False，`DECLARED_DISTINCT_OBJECTS`；比较其它
  候选不是断言copy，因此不往全局ctx写copy conflict。
- 缺声明/目录、跨namespace、端点/执行scope未解或预算不足：None，`UNPROVED`；
  截断保cursor，不留True前缀。ValueGraph binding扫描和来源gap筛选都扣预算。

namespace采用已有`artifact_key=(sha256,schema,size_bytes)`，不是URI相同。
**ObjectRef没有epoch字段。** 外部ID分配必须区分对象世代；同一裸Python地址被
复用不是same-object依据。刷新后目录缺失不能用旧缓存；已供graph/hash矛盾仍由
原snapshot校验拒绝。

basis可以仍Unresolved，所以True是**给定这些当前身份声明时**的关系，不是
运行时身份guard已验证。原basis、相关denotation路径来源gaps及目录错误保留；
`source_runtime_verified/native_identity_verified/runtime_identity_verified/
value_identity_verified/transformation_authorized`全部False。只返回两端相关
source gaps，避免在每个候选嵌入整个模型的无关诊断。

## 3. 接入历史查询

`body_state_history`在现有unknown copy之外增加独立身份依据。identity receipt与
`ordinary_binding`分开；`DECLARED_SCOPED_OBJECT_IDENTITY`不会添加copy边或全局union。
已知不同ID先做局部身份比较；其ordinary_binding=None表示没有执行普通比较，
不可以改称ordinary False。其它ordinary True/False保持原义，硬冲突不被救回。

条件性same-body仍须核真实terminal/commit、Create与Drive全部原端口/当前状态、
准确caller链、同native lifetime/no-reset scope及host顺序。缺实际READ Use、当前
state或Create/Drive输入，身份声明不能补齐。所有原denotation、Drive和commit
库存先保留，完整兄弟不能填缺本实例。

删RequestAssociation会使R来源缺证，但当前B的独立身份仍可能支持B的历史F。
本接口不会因此恢复latent、R→Create或字段load来源，更不会把整个请求分析翻绿。
原没有denotation的fixture继续未知，语义不迁移。

## 4. 明确未解决的能力

自动stored-reference payload→状态版本→后续READ result的来源关系仍缺；本批
没有用新native immutable假设掩盖它。实际source/native/epoch/对象身份采集对应、
完整F19后续体及第一阶段仍须按原分母验收。同ObjectID不证明Tensor内容不变，
不构成自动cache/hoist/delete权限，也没有新的LeWM加速结论。

# P1：原生图的薄边界与跨表示义务

2026-10-16。**已实现并通过静态组件与冻结全仓验收。** 基线 `126d56e`，冻结实现 `79bf2a9`。
遵循 [集成设计 7.2](MODELING_INTEGRATION.md)：不复制 PyTorch 的 TreeSpec、
graph signature 枚举或 def-use 图。LeWM 不参与类型、规则或 fixture 条件。

## 1. 本门交付和边界

把 provider 自身表示的入口/出口接到既有规范端口，并表达不同表示之间需要
核对的关系。原生 signature、input/output TreeSpec 仍由不可变 artifact 保存。
本门不打开 artifact、不执行 flatten/unflatten、不运行 capture、也不实现新的
source lowerer、detector 或 backend。真实 adapter、artifact 重放及跨表示证明
分别验收；本门通过不能关闭完整 T1/M1/M2。

## 2. 冻结 API

`NativeBoundaryID` 与 `BoundaryRelationID` 是独立 ID 命名空间。

| 记录 | 字段及含义 |
| --- | --- |
| `EntryPortRef` | `region, value`；必须是本区域实际 entry block 参数。 |
| `ExitPortRef` | `region, exit_name, index`；指逻辑 ExitPort 的一个槽。 |
| `NativeInputSlot` | `position, role, evidence, port: EntryPortRef`。 |
| `NativeOutputSlot` | `position, role, evidence, port: ExitPortRef`。 |
| `CoreInputPort` / `CoreOutputPort` | `port, reason`；不在原生 flat signature 中的规范辅助端口。 |
| `NativeBoundary` | `id, provider, region, signature, input_tree, output_tree, inputs, outputs, core_inputs, core_outputs`。 |
| `BoundaryPortPair` | `left, right, evidence`；两侧同为 entry 或同为 exit 的声明对应。 |
| `BoundaryObligation` | `domain, reason, evidence`；未闭合义务，证据是上下文，不是自动 discharge。 |
| `BoundaryRelation` | `id, left, right, ports, conditions, obligations, rule`；两端 NativeBoundary 属于不同 Region。 |

`signature/evidence/rule` 使用已有 `ProviderFactReference`；树引用可以为 None，
含义是没有该结构事实，不能解释为空树。`role` 为原生 provider 的非空字符串，
核心不解释 `BUFFER_MUTATION` 等工具枚举名。辅助 artifact 可以被引用；声明
不证明它与 primary artifact 的真实来源关系，后续 adapter/replay 必须核对。
不为了通过校验编造原生 placeholder、树叶或 canonical Value。
Export call_spec 通常只覆盖用户调用/返回结构，不包括所有 lifted、mutation 或
gradient 槽；本门不解释树的适用槽范围，更不要求叶数等于全部 native 槽数。

NativeBoundary 每个区域最多一份，且只允许其 P0 定义表示 owner 声明。
两组 native position 都连续、严格按 0..N-1 保存；顺序不必等于 core 物理顺序。
native 与 core-only 端口严格分区全部 entry 参数和全部逻辑 exit 槽，不能遗漏、
重复或跨区域。不存第二份 actuals、producer、类型或前后 state。

`(y,y)` 在规范退出中必须有两个槽和独立 Use；两个槽可引用同一个 Value。
一个 opaque tuple ReferenceValue 不会因树引用自动被拆成两个值。返回路径多时，
ExitPort 查询保留所有实际 Return/Raise 的 UseSite，不选一个 producer。

## 3. 跨表示关系不更改程序事实

BoundaryRelation 只引用已声明的两个边界，不改 callee、parent、provider owner、
producer 或 canonical Uses。映射可以是部分、多对多；完全相同的端口对不能
重复。没有声明对应不表示没有依赖，也不能因为类型相同自动建立对应。
关系两侧不能引用对方/第三个区域的端口，entry/exit 方向不能混接。

八个域各有一条不可省略的未闭合义务：

- `NUMERICS`
- `STATE_WRITES`
- `ALIAS_IDENTITY_LIFETIME`
- `AUTOGRAD`
- `RNG_MODES`
- `COMPLETION_EXCEPTIONS`
- `EXTERNAL_HISTORY`
- `RESOURCE_ORDER_READY`

证据及 conditions 为声明来源，不设置可写的 verified/proven/authorized 位。
同 provider 的两个表示也不自动等价。TreeSpec、shape、相同名称和 raw role
都不能证明内容、对象身份、alias 或当前状态相同。

原生 mutation 输出通常是写回载荷；载荷 Value 与 StateVersion 的实际区别由
规范类型保留。因本门不读取原生 artifact、也不解释 role，**不能**宣称已验证
raw role 的真实类型或完整写回。参数/buffer 当前实例、lookup/content state、
normal/raise 写回和 partial failure 必须在后续 adapter 合同中接通。
INVOKE 的当前接口禁止普通 StateAccess；本门不以新注释绕过该约束。

## 4. 查询、wire 和公开入口

ProgramIndex 提供边界/关系索引、entry 参数解析、exit 全部 UseSite、native
各槽的规范解析结果。类型和结果从已有 core 派生，记录顺序不改变结论。
原生树和 signature 不解码，不依 label、role 或 artifact locator 猜测端口。

schema v8 承载 `native_boundaries/boundary_relations`；无新能力的 v1–v7 保持
原字段与编码。v7 golden 由隔离的原 revision、原 codec 产生，不能由新类型
倒推出旧默认。公共 `check-program` 只校验声明/结构，权限仍为 false。

## 5. 自主验收顺序

| Gate | 交付与实质反例 |
| --- | --- |
| G0 | 冻结本规格与来源分工，独立审查原生 artifact / core-only 分区。 |
| G1 | 严格 records、ID、未知字段及畸形嵌套记录拒绝；不读文件/执行 provider。 |
| G2 | 规范 entry/exit 全覆盖、错区域/错出口/错 owner 拒绝；重复 Value 的独立位置、多 Return 和顺序变化保持。 |
| G3 | 跨 Region 对应及八域义务；原图实际调用/state 不被覆盖；部分与多对多对应可表达。 |
| G4 | v8 codec/query/public CLI、原始 v1–v7 合同；不授 artifact 真实或优化权限。 |
| G5 | 独立反例审查、定向组件验收，失败原因和修复保留。 |
| G6 | 冻结产品与测试源后一次全仓回归；保存指纹/fixture 哈希、报告并正常提交推送。 |

未完成模型清单继续见 [第一阶段矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)。本门
不替代 cleanup/resume、owner/selector/literal、动态 resource-ready 和
occurrence/denotation 等剩余接口；完整第一阶段通过后仍先停下来向用户讲解。

## 6. 当前实现与有界证据

**Implemented：** 两张原 core 表、严格记录/ID、canonical 分区/关系校验、派生
端口查询、v8 codec 和公开 CLI。树及 raw role 仍只作原生来源声明。

**Verified（组件范围）：** 最终 [168 项 / 8.815s](../artifacts/experiments/b1_call_operands/model_native_interfaces/component-final.json)
通过，376 文件源指纹
`7a476a2e161109dc924615cd1c5aeb17fc4ca39176ffade393e15917dbb6fb17`。
这是手工通用 IR fixture 的组合验收，**不算程序自动分解/导入**。
原 v7 golden 由隔离 `126d56e` 的原 codec 生成，wire SHA 为
`67e5c54e8971952d070975df9268bdb3453da1485c8e48853ff6455b5d6dc35e`。

原始结果保留，不以终版覆盖：

- 子任务首次脚本启动缺少 repo PYTHONPATH，在 IR 执行前失败；修正运行路径。
- 一份缺失端口的负例同时破坏 native position 连续性，先在构造期失败；修正
  反例，使其实际检验图级 partition，而不削弱构造规则。
- 根代理的 unused-exit 样例违反既有 `unbound_exit` 约束；修正预期为拒绝，
  不因新增端口接口允许幽灵出口。

- 首版组件 164 项通过后，独立审查实际复现 **B1：合法旧 ID 子类图无法建立新
  ProgramIndex**。改为用原 typed-ID 对象坐标索引，而非对所有旧图强制构造新
  strict 引用；也没有按 ID 文本归并对象。新增 ValueID/RegionID 子类 × 旧 core/
  含无关 native 子区四组合回归。原五项探针中的一项 REGRESSION 已在同探针
  [修复后结果](../artifacts/experiments/b1_call_operands/model_native_interfaces/review/results.after-fix.json)
  中全部 PASS；新声明的 exact-type 规则保持。

后续 v9 C1 对此增加有界区别：真实 cleanup entry 捕获的潜在语言出口可因清理
发散或替换而没有实际站点；查询返回空 UseSite tuple，不补 producer。只含 P1/
旧 schema 的原规则不变，闲置声明或额外 entry 参数不能触发该区别，见
[C1 控制合同](M1_CLEANUP_INTERFACES.md)。

独立审查限定于其未参与编写的集成层，见
[原报告](../artifacts/experiments/b1_call_operands/model_native_interfaces/review/integration-review.md)。
冻结 G6 在 `79bf2a9` 完成：[3,215 PASS / 431.085s / 1,027,692KiB](../artifacts/experiments/b1_call_operands/model_native_interfaces/full/report.json)，
零 fail/error/skip，三项警告；前后 HEAD、干净状态、376 文件源哈希及18份 fixture
哈希逐项相同。唯一 full 运行无重试，子进程退出后专属 basetemp 已删除。
该时间是全仓验收成本，不是目标程序性能。详见[证据索引](../artifacts/experiments/b1_call_operands/model_native_interfaces/README.md)
与[组件验收记录](../artifacts/experiments/b1_call_operands/model_native_interfaces/acceptance.json)。

完整第一阶段、真实 artifact 适配/重放、当前 lifted-state/写回、运行对应和等价
仍未完成。下一批建议只归档为 Proposed：
[state/selector/literal](../artifacts/experiments/b1_call_operands/model_native_interfaces/review/next-state-boundary.md)、
[其余模型接口顺序](../artifacts/experiments/b1_call_operands/model_native_interfaces/review/next-model-order.md)。

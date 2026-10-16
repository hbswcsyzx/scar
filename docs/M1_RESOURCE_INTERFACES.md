# M1 子项：资源身份接入规范程序 IR

日期：2026-10-16。**有限静态接口组件通过；整个 M1 和第一阶段仍未完成。**

## 1. 模型到代码的对应

本子项把 Resource 接入原 `ProgramGraph`，没有复制另一套操作、状态或 def-use：

| 规范接口 | 代码与约束 |
| --- | --- |
| ResourceDefinition | 独立 ResourceDefinitionID、kind/role、CreatedResource(OperationID) 或 ExternalResource(RegionID, port)。 |
| ResourceRequirement | 独立 RequirementID、Operation/Region owner、类别/角色、容量和关系约束；不是资源实例。 |
| ResourceUse | 具体 OperationID、requirement、可选 definition、可选本操作的准确引用 UseID。 |
| ResourceLocation | 资源身份与已有 StateLocation 的对应；前后版本仍只由原 StateVersion/StateAccess 保存。 |

同一静态定义可在多次执行中对应不同实例；不同静态 ID 不构成运行时资源不同
的证明。未解析 definition 可为 None；这保留要求，不伪造已存在/可用实例。
本接口不证明 handle 实际所指、动态约束已满足、GPU 就绪、无别名或纯性。

实现：[resources.py](../scar/ir/program/resources.py)、
[resource_validation.py](../scar/ir/program/resource_validation.py)，规范表挂在
原 [ProgramGraph](../scar/ir/program/model.py)；由原 validator/codec 校验。

## 2. 关系的作用域与不变量

- 操作 owner 的要求按该次 operation occurrence 绑定；Region 入口 owner 的要求
  按该次 activation 绑定。当前静态关系只允许引用同 owner 的其他要求；跨 owner
  需要显式 occurrence pairing，当前未实现，不能默认把循环/调用实例合并。
- SAME_RESOURCE 取同 scope 闭包；其类别/角色须相容。DISTINCT 与严格 CHILD
  不能落在同一等价类；严格 containment 不允许环。CHILD + DISTINCT 合法。
- 验证 owner、creation、definition、location 和 handle 是否存在及是否属于准确
  的操作；不能用 ValueID、RequirementID 或别处的 Use 冒充 handle/definition。
- 容量是声明要求，不是可用资源测量；静态定义匹配不等于运行时满足所有约束。
  device/context/access/ownership 等更完整约束及动态满足证据仍待 M1 后续实现。

## 3. wire 与公开入口

新增资源能力用 `scar.program-graph` **v4**，严格要求新增表与 capability。
无资源的普通图仍写原 v2，有 binding 的图仍写原 v3；v1/v2/v3 只接受原字段。
两个 golden wire 由隔离的原始 `dcd4986` 包生成，不从当前 dataclass 反推历史格式：

- [v2 fixture](../tests/fixtures/program_graph_v2_frozen.json)
- [v3 fixture](../tests/fixtures/program_graph_v3_frozen.json)
- [生成依据](../tests/fixtures/program_graph_wire_provenance.json)

公开 `scar check-program graph.json` 能验证新接口并明确不授予变换权限；资源
图额外报告实例/ready 未验证。代码审查同时定位旧 CLI 的 baseline defect：
LocalBindingType 没有 `.kind`，旧 counts 路径会失败。现分别统计 local binding，
新增 binding+resource 组合回归；这是模型工具正确性修复，不是性能优化。

## 4. 自主验收

[gate manifest](../gates/m1_resource_interfaces.json)的四项准则全部通过：

**198 passed，15.922s，0 failures**；测试期间 source fingerprint 不变，
`7c2a655a57eb8cdaaf11b0333755852e9dd7b5ecc6f4fc088d2c4e6a0caea3cd`，339 文件。
报告记录当时 HEAD `e95fed8` 及未提交工作树；它验证的是记录的源码 hash，
不把 e95fed8 原提交误称含有本实现。冻结提交/全仓回归另行记录。

- [逐准则与案例](../artifacts/experiments/b1_call_operands/model_resource_interfaces/component/report.json)
- [独立审查与两项缺陷的关闭记录](../artifacts/experiments/b1_call_operands/model_resource_interfaces/review.md)

初次 focused 命令引用不存在的测试文件，exit 4，没有执行测试；随后 162 passed /
1 failed，原因是旧兼容测试用当前 dataclass 字段生成历史期望。改为原始隔离
golden 后 168 passed，随后包括公开 CLI 的正式组件 198 passed。前置结果在
同目录 `prior-attempts.json` 保留，不能混为全通过或修改旧验收数据。

## 5. 尚未完成

动态 ResourceInstance/realization、occurrence/denotation、WorkTicket/typed ready、
环境、pending completion、挂起恢复与完整协议约束尚未接通。没有自动 LeWM
图或化简结果。本子项不能关闭整个模型阶段；后续仍按
[第一阶段模型门](WHOLE_PROGRAM_MODEL_PLAN.md)落实。

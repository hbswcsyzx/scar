# M1 static resource interface review

2026-10-16。只读审查 root 当前未提交第一块 M1；未改产品代码、未跑整仓。
范围：`resources.py`、`resource_validation.py`、ProgramGraph 四张资源关系表、
codec v4 与 `test_program_resources.py`。小探针结果见 `review-probe.json`。
本审查不是 M1 gate 通过声明，也不要求这一块实现动态 instance/ready。

## Findings

### P2 — 把兼容的 CHILD + DISTINCT 约束错误判为矛盾

位置：`scar/ir/program/resource_validation.py:40`。

当前 `seen[other]` 仅存一个 relation，发现第二个不同 relation 就报
`contradictory direct requirements`。对同一 other 同时声明 CHILD_RESOURCE 与
DISTINCT_RESOURCE 是兼容的：严格子资源本身就不是其父资源。这不是两个冲突
的 bindings，而是同一资源要求的两个可同时成立的约束。

探针：对现有 `resource_graph()` 的 queue requirement 增加另一个 requirement，
再添加上述两条 relation；`validate` 返回一个 `resource_constraint` 错误。

建议只检查实际不兼容组合，明确 CHILD 的严格性；不能将“不同枚举”作为矛盾
规则。验收至少包含 CHILD+DISTINCT 的两个顺序均合法、SAME+DISTINCT 拒绝、
严格 CHILD+SAME 拒绝。无需在本块增加一般约束求解器。

### P2 — requirement 的 kind/role 和 SAME 的单角色类型未闭合

位置：`scar/ir/program/resources.py:123` 及
`scar/ir/program/resource_validation.py:44`。

`ResourceDefinition` 明确要求 MEMORY_POOL 为 MEMORY、FILE_ENTITY 和
OPEN_FILE_DESCRIPTION 为 FILE，但 `ResourceRequirement` 仅检查 enum 类型。
因此构造 CPU+MEMORY_POOL requirement、保留未解析 ResourceUse 后，整个 graph
`validate` 返回空 issues。按照本块已有定义类型系统，无法构造匹配该要求的合法
ResourceDefinition；这是可本地发现的类型矛盾，不是正常的“实例暂未观测”。

另一个探针：两个 FILE requirements 分别要求 FILE_ENTITY 和
OPEN_FILE_DESCRIPTION，同时声明 SAME_RESOURCE；`validate` 仍为空。当前每个
ResourceDefinition 只有一个 role，而 ResourceUse 要求 definition.role 精确等于
requirement.role，因此该 SAME 关系不可能由一个合法定义满足。模型还明确区分
文件实体和 open-file-description，不能用同一 kind 抹去这一区别。

建议将已有 kind/role 兼容规则统一供 definition 和 requirement 使用，并在 SAME
约束中按本块的单角色类型系统校验 role。未解析 requirement 可以保留，类型自相
矛盾的 requirement 应单独拒绝；不需要实例观测或容量测量才能做这两项检查。

## 范围判断

- 新表引用既有规范 Operation/Use/Location；ResourceLocation 不另存一套状态
  版本，未发现因此直接把资源 identity 当成状态版本的路径。
- requirement、definition 使用不同强 ID；ResourceUse 不直接制造 instance。
  validator 声明 well-formedness，当前实现未据此授予动态 availability、ready、
  purity 或变换许可。不能把“通过校验”在后续调用中升级为这些结论。
- codec 的旧 v1/v2/v3 字段集移除了新资源字段，v4 明确要求资源能力；本次阅读
  未发现直接 wire 字段兼容错误。没有重复 root 已运行的 focused/full tests，
  此项阅读不能代替实际兼容回归证据。

## 审查快照与探针

探针用现有 `lewm` conda Python，从测试文件 `runpy.run_path` 取得 graph fixture，
仅 `dataclasses.replace` 构造三组约束并调用 `validate`；exit 0，未执行目标/GPU。
结果依次为：兼容组合错误拒绝；CPU+MEMORY_POOL 错误接受；SAME 不同文件角色
错误接受。探针只证明这些结构行为，不证明一般约束体系完整。

审查代码 SHA256：

```text
resources.py             37618a21e2b07683ed0f47ed236a940e2cadc3e8ff8f10dc1844cc8af5752311
resource_validation.py   bb1c86bece42360748be8ea0fec6f4fc9e1bbe7e62af7e206822dab6093e0702
model.py                 6753b9bb174c013c71ec8c9a83f47b6b75a22c8d6812ebceb3898ee844fd13f4
codec.py                 edaccd7599987471aa9316cd06e313102911c391a5a8902ef61b8799d5c600b2
```

## 修正后终态复核

上述初始问题和探针结果保留，以下结论针对修正后的当前代码，不覆盖旧证据：

- `_require_kind_role` 现在同时用于 ResourceDefinition 与 ResourceRequirement，
  关闭 CPU+MEMORY_POOL 等本地类型矛盾。
- 同 owner 的 SAME 先建立等价闭包，再检查分量内 kind/role；DISTINCT/严格 CHILD
  与 SAME 冲突及严格 CHILD 环分别校验。CHILD+DISTINCT 不再被错误判为冲突。
- relation 只允许同 Operation owner 或同 Region owner；分别解释为同一 operation
  occurrence 和同一 region activation 入口绑定内的比较。跨 owner pairing 需要
  将来显式接口，当前拒绝未定对应的关系。这个有限实现与完整模型不冲突，也不
  将静态 ID 的闭包冒充跨运行实例身份相等。
- 已同步澄清 `docs/model/RESOURCE_PROTOCOLS.md`：Region 入口绑定不能随每个内部
  use 改绑；四张资源表通过只表示静态接口一致，未实现 instance/ready 或动态
  constraint satisfaction 的证明。没有把本块有限约束作为完整模型永久限制。

只读检查了修正代码和相关反例测试，并核对现有组件报告：
`component/report.json` 状态 PASS、exit 0、198 passed，source fingerprint
`7c2a655a57eb8cdaaf11b0333755852e9dd7b5ecc6f4fc088d2c4e6a0caea3cd`。
当前 `resources.py`、`resource_validation.py` 与 `test_program_resources.py` 的 hash
均与该报告一致。没有重复执行测试；报告的 198 项不表示整个 M1 或全程序模型通过。

当前两项 finding 判定：**已修正，可关闭此资源子组件的审查问题**。同 owner/闭包
规则在此有限静态接口范围内可接受，未发现新的实质问题。剩余完整资源生命周期、
动态对应和自动建模能力依主计划继续保持未完成。

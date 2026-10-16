# M1：函数环境接入规范调用与状态边

日期：2026-10-16。状态：**327 项组件检查及 2,835 项冻结全仓回归通过；仅关闭本组件。**
依据：[整体模型](WHOLE_PROGRAM_MODEL.md) §3—5、
[现成图的集成合同](MODELING_INTEGRATION.md) §3—4。
本批落实函数环境这个完整接口，不实现 source lowerer、采集器、detector 或 backend。
整个 M1/M2 和第一阶段仍有其他未完成项，不以本组件通过替代它们。

终版组件源指纹为
`efefa8a50396c4637935a488fca04663d738f4430679bd4f0975fd07be0c00cd`
（346 个产品/测试/门文件），用时 16.941s，四项准则均通过。此前 326 项中间
结果仍保留；自审额外复现并修复了同一 body 的 formal/free-variable slot 冲突，
新增反例后才得到这份终版报告。报告目录：
`artifacts/experiments/b1_call_operands/model_environment_interfaces/component-final/`。
这些是结构声明检查，不是程序运行数据或性能结果。

冻结 implementation 为 `e8267134b5daf40e5a2b89b1a00a73186284e864`。全仓一次
2,835 PASS / 0 failed / 0 error / 0 skipped，driver wall 411.858s、峰值
1,026,996KiB；三项既有警告。前后 HEAD、干净工作树、346 文件源指纹及8个 fixture
文件 hash 完全相同。独立 slot 修复闭环 PASS；未重跑目标程序。全仓原始证据为
`artifacts/experiments/b1_call_operands/model_environment_interfaces/full-final/`。
最初 `full/` 仅因调用方传短 revision 而在 precondition 拒绝，未启动 pytest；保留
该失败并在全新目录用完整 HEAD 运行，没有覆盖旧记录。测试时间是验收成本。

## 1. 为什么需要这条连接

仅有 `f(x)` 的显式 x 不够。函数还依赖函数对象、globals、创建时关联的 builtins、
defaults/kwdefaults 和闭包 cell；同 code 不代表这些相同。同一 cell 可由多个函数
共享，其内容也可能跨调用更新。参数/buffer 所属 module 同样由实际引用及当前状态
确定，不能用同名 get_attr 连接。新接口用于表达这种边界，不能直接证明 reuse。

Python builtin/function/code 语义优先使用语言与 compiler 见证，不重新写解析器。
FX/Export 的 lifted slots 以后通过相同的引用/状态/环境对应接入；这批不捕获 Tensor 图。

## 2. 表达选择：复合接口，规范参数唯一

`EnvironmentInterface` 是现有 Region 入口引用参数的**复合接口**。它不要求额外
pack 成一个新 EnvironmentValue，也不另存一份 actual/call arguments。这个表达
细化旧控制提案的封装形式，不改变环境身份与内容状态分离的原则。

```text
EnvironmentInterface
  id: EnvironmentInterfaceID
  region: RegionID
  code_definition: OperationDefinitionID
  members: ordered EnvironmentMember

EnvironmentMember
  role: FUNCTION_OBJECT / GLOBALS_NAMESPACE / BUILTINS_NAMESPACE
        / DEFAULTS / KEYWORD_DEFAULTS / CAPTURED_CELL
  reference: existing entry ReferenceValue's ValueID
  locations: required existing entry state domains
  cell_slot + cell_position: only for ordered captured cells

FunctionEntryLayout
  environment: EnvironmentInterfaceID
  parameters: ordered FormalPort(slot, existing entry reference ValueID)
```

前五个 role 有固定位置和独立 formal 引用端口；缺省 defaults/kwdefaults 的
actual 可以是 None 引用。cells 跟在后面、位置从0连续，slot独立。实际多个端口
可以指向同一个对象/cell，因此不能拒绝相同 actual 引用或共享 location。

cell_slot 是本 body 的 free-variable 接口槽位（对应 co_freevars），不是外层
binding 的来源槽位，也不是动态 cell identity；它与本 body 的 formal slots 必须
不交。外层formal与内层freevar的关系由来源对应连接，不共用静态slot身份。
formal 被子函数捕获而成为本函数 co_cellvars 是合法的，不归本函数 CAPTURED_CELL；
实际引用/cell/location 仍可 alias。

每个环境恰有一个 FunctionEntryLayout。它给出显式 Python formal 的逻辑顺序，
与环境引用及全部现有 StateVersion 入口参数组成完整不交分区。Python formal
必须是入口 ReferenceValue；unboxed DataValue 需另有 ABI/表示合同，不能因源注解
就当普通 Python 参数。物理 entry 顺序可以不同于逻辑分区顺序；以准确 ValueID
映射，不能按前 N 个端口或固定偏移猜。这样也保留 provider 的原始端口顺序。

code_definition 是静态声明符号，不是已验证的 code snapshot/函数对象对应。
FUNCTION_OBJECT 所指的普通对象状态还能表达 annotations、dict、type params 或
code/defaults 字段的改动，不将其余对象属性误判为不存在。

locations 表示此接口声明的必要域，不是完整 read/alias 集合；省略不推出 NONE。
状态值仍由现有 block argument、StateAccess、call/control 实参传递。不同 ID 不证明
运行时不重叠；未知 target/coarse world 保留，不能造独立 cell chain 绕过共享状态。

## 3. 必须接到现有 core

```text
caller Operation.uses
    -> canonical call_arguments / invoke_arguments
    -> callee Region.entry.arguments
        ├─ ordinary data/reference parameters
        ├─ references selected by EnvironmentInterface.members
        └─ current StateVersionValue parameters
              -> StateRead / write -> result and updated state
```

新增 `ProgramGraph.environments` 与 `function_entries` 接口表；两表只标记现有
入口角色，不存 producer/actuals/state 的副本。EnvironmentMember.reference 必须指向
准确的同区域 entry ReferenceValue，不能使用 literal、别的 block 参数、操作结果
或跨区域 ValueID。locations 必须已存在并是该区域入口携带的状态域；已知 ref.targets
不得矛盾。每 Region 最多一个接口，接口ID图内唯一。

调用实际绑定从原 callee entry 顺序与 call/invoke arguments 推导。有几个 formal
就必须绑定几个原有 Use；环境不绕过作用域、domination、状态版本或 normal/raise
约束。新增查询分别返回既有 formal/environment/state 端点，status 只为 DECLARED，
不发明新 producer/Use，也不声称 runtime actuals 已经采到。缺少接口/目标时明确
NO_DECLARED_ENVIRONMENT/NO_DECLARED_CALLEE，不以空结果证明没有环境。

旧 source BodyEntryInterface profiles 保留原义；它们不生成新环境/入口 layout。
后续 source adapter/replay 必须按 FunctionSignature 的完整 slots/顺序与新的规范
layout 核对，并替换旧 record_body 的 `index+1` 源 actual 偏移；不能把环境/state
混进 CallArgument 或把 DEFAULT_STATE/star-pack 计划当真实值。这项自动接线尚未完成。

## 4. 自主验收节点

| 节点 | 交付与证据 | 必须拒绝/明确的边界 |
| --- | --- | --- |
| E0 类型与语言核对 | immutable 环境接口；独立 Python 函数环境小探针；完整角色含义。 | 错 enum/ID、bool index、cells乱序/重复slot、端口重复；builtins不能从当前globals字段猜。 |
| E1 core 结构与依赖 | 接原 ProgramGraph/validator/index；入口分区；父子区域真实 canonical call 与状态图。 | 缺失/跨区/非entry引用、遗漏/重叠分区、将env/state当formal、错误location、state stale、错误call arity与invoke完成；actual alias必须允许。 |
| E2 wire/公开入口 | capability选择 v5；保留原 v1—v4；CLI明确未验证环境实现。 | 改tag夹带新字段/空capability、缺字段/错namespace、v4退化不一致。 |
| E3 冻结回归与独立审查 | 正反例、逐准则报告、source fingerprint、冻结revision与全仓回归。 | 旧wire从原版本隔离生成，不按当前dataclass反推；不得把组件结果当完整模型。 |

v4 resource golden已从 `f80af0f` 的隔离 git archive/原fixture/原codec生成，
不用当前 dataclass 推导；v2/v3保留已有原始golden。原v4 wire SHA（无换行）：
`3acea0f9832eb501374a56e6191b06c030e7c11d0ac1846dc4724aa765058d3e`。
生成依据与后续报告位于
`artifacts/experiments/b1_call_operands/model_environment_interfaces/`。

## 5. 不由本接口授予的结论

结构校验只证明声明能组合：不证明当前 Python callable 与该code/env相符，
不证明哪个动态实例/版本满足 formal，也不证明alias完整、纯性、数值等价、来源
闭合或资源ready。动态 occurrence/denotation、typed cleanup/resume、资源实例/
WorkTicket/readiness、完整location owner/selector和provider对应仍有独立未完成项。

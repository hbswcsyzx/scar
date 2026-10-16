# 第一阶段 M2 逐字段规格独立审查

2026-10-16。审查冻结版本 `d5311a63211470500c6892af484f500e71c0d61f`。
**结论：GAP，尚不能关闭 M2。** 本报告不判定 M1 实现完成，也不判定 M3 自动建图通过。

## 方法、守恒与证据范围

逐段审读 `PYTHON_DATA_DEFINITION_PROTOCOLS.md`、`PYTHON_CONTROL_PROTOCOLS.md`，
核对资源分册与 `WHOLE_PROGRAM_MODEL.md` 的规范事实来源、完成、状态、资源及身份
关系。数据/控制分册不是本审查者所写；资源分册由本审查者撰写，此处对其作交叉一致性
检查，不能冒称独立第三方资源协议验收。

`field_coverage.json` 为人工按规则赋值后的机器可读清单。每个 field 记 phase、实际
求值/metadata 规则、精确 section 和 COVERED/GAP；没有用 keyword 搜索来生成通过。
`build_field_coverage.py` 只把人工表落盘，并用本机 CPython 3.14.7 反射校验集合与字段
守恒；它不验证语义规则正确性。四份文档原快照及 SHA 随 `documents.initial/` 保存。
审计结束时原快照与当前冻结文档 hash 全相同，未修改 tracked 文档、产品或测试。

| 项目 | 本次实际结果 |
| --- | --- |
| canonical 具体构造 | 113，全部有人工归属，无遗漏/多余 |
| `_fields` | 196，全部逐字段列出 |
| 无字段构造 | 35，均有节点协议/marker归属；不是因无字段而跳过 |
| 字段 COVERED / GAP | 184 / 12 |
| 构造 COVERED / GAP | 103 / 10（包含 2 个无字段 GAP） |

抽象 sum/base 与旧兼容 API 单独排除；排除表在 JSON 中，不能把其数量算到 113。
`lineno/col_offset/end_lineno/end_col_offset` 等通用 `_attributes` 另归 source metadata，
不混入 196 fields，不制造运行操作。TypeIgnore 的 lineno 本身是 canonical field，仍
必须审查，不能用“通用位置信息”跳过。

## 必须关闭的五组规则缺口

### G1 — 无 RHS 的 AnnAssign 与 simple 标志（2 fields）

位置：数据分册 §8.2。影响 `AnnAssign.target`、`AnnAssign.simple`。

现有规则明确有 RHS 时的赋值和 annotation 的懒求值，但没有规定无 RHS 时 target
的运行依赖。`owner().field: int` 仍求 owner；`owner()[index()]: int` 仍求 owner/key，
却不调用最终 getter/setter。Name target 不会因此建立一个值绑定。把“annotation
不执行”误当成整条语句无运行步骤，会删除真实调用/异常。

同时应明确 `simple` 为编译选择 0/1：括号 Name `simple=0` 不能仅因 target 是 Name
就收集为 simple-name annotation。需要说明无值 Name 的 binding/scope 与 annotation
收集分别发生在哪个 phase；资源/状态/异常按既有接口组合，不增加新节点家族。

本机独立 probe：无 RHS 两条语句输出 `owner, owner, index`，没有 getattr/getitem。

### G2 — 条件上下文的 UnaryOp(Not) 桥接（2 fields + 1 marker）

位置：数据分册 §10.1、控制分册 §0.2。
影响 `UnaryOp.op`、`UnaryOp.operand`、无字段 `Not`。

数据分册给出值上下文 unary：先求 operand，not 再 Truth；这条本身不是错误。
控制分册 T 已对 BoolOp/Compare/IfExp 作 continuation 组合，但没有明确
`T(Not e)` 应将 `T(e)` 的真假 continuation 对调，而不是先 `V(e)` 再 Truth。

本机 probe 的精确区别：

| 形式，a 恒假 | bool 调用 |
| --- | --- |
| 值上下文 `not (a and b)` | a、a |
| 直接条件 `if not (a and b)` | a |

因此不能把 V 和 T 统一成一条“已经知道真假就缓存”的规则，也不能将直接条件的
一次调用无条件套到值上下文。需要在两分册明确 V(Not e) 与 T(Not e) 的桥接。

证据修正说明：最初交互探针将可变 events 列表直接放入结果，后续 clear/条件探针
污染先前记录，误报值上下文也只有一次。原错误 JSON 保留于
`probe.initial-alias-bug.json`；最终 `probe.py` 使用 `list(events)` 快照，最终结果才是
上表。该探针缺陷不作为模型结论。

### G3 — List/Tuple/Starred 的 ctx target 协议（3 fields）

位置：数据分册 §8.1、§8.4、§9、§11。
影响 `List.ctx`、`Tuple.ctx`、`Starred.ctx`。

各处已描述 Load 容器/调用展开和 Store 解包，但没有将 ctx 的选择闭合为明确规则；
特别是 `del (a,b)` / `del [a,b]` 要递归删除 targets，不应创建容器、读取它们的值或
按 iterable 解包。Starred 在合法 Load/Store 位置有不同角色，Del/非法位置需要编译
拒绝，不可给 generic AST children 执行路径。

关闭方法：增加小型 ctx 表，交叉引用既有 Store/Del/expansion 协议；明确 target
子节点何时求 owner/key、何时只绑定/删除。无需新 framework 或 backend。

### G4 — Expr、Pass、TypeIgnore 的精确归属（3 fields + 1 fieldless node）

位置：数据分册 §2、§13 与资源分册 §2.2。
影响 `Expr.value`、无字段 `Pass`、`TypeIgnore.lineno/tag`。

- Expr：catalog 提到结果释放，三分册尚没有直接的 expression-statement 规则：
  求 value、区分 ordinary discard 与 interactive displayhook、临时引用释放/异常
  及完成。一般 lifetime 规则不能代替决定谁消费该结果的连接。
- Pass：catalog 有分类，但三分册没有明确其无运行 fields、普通 Fallthrough、
  source/编译归属与所需观察合同；不能因“pass简单”就从守恒审查消失。
- TypeIgnore：Module.type_ignores 泛称行号/type metadata，未逐字段规定 lineno
  与 tag 的来源元数据含义。补字段说明即可，不需要执行操作或新 Value。

### G5 — ClassDef header 的跨字段顺序（2 fields）

位置：数据分册 §5、§9。影响 `ClassDef.bases`、`ClassDef.keywords`。

现有 §5 规定各 bases、keywords 内部源序，给出一条典型 metaclass 路径，但未明确
starred base 与 keyword 在源码交错时的跨字段顺序及展开。§9 已有 Call 的相应规则，
不能假设 class header 自动继承它而不说明连接。

本机合法源码 `class Header(metaclass=meta(), *base_pack()): pass` 观察到
`base_pack` 在 `metaclass_expression` 前。需要明确 header 位置/星号部分、关键字/
映射部分的求值、展开、重复名/失败端口，再走 base resolution/metaclass selection；
不能仅按文本顺序或任意 `_fields` 遍历。可直接复用既有 argument-preparation 协议。

## 与整体模型的一致性检查

三分册在以下已写规则上保持一致：静态定义与动态 occurrence 分离；局部 binding
与对象内容状态分离；state 只引用规范 StateVersionValue；Raise/cleanup 后态不回滚；
Suspend 保存 frame-private、恢复使用当前共享状态；host 返回不代表资源 ready；
provenance、数值相等与可替换物化分开；native 接口覆盖不冒充内部已展开。

资源四表仅静态接口 well-formedness 的实现边界也已明确，没有将整个 Resource/
WorkTicket/Ready 规格写成已实现。未发现需要新增顶层业务实体来关闭这五组 AST
缺口的理由；它们是已有协议的精确定义和连接不足。

但 AST 字段全部有条目只是必要条件。用户从加载到输出的完整程序模型还需要库边界、
观察合同、运行对应与后续自动恢复验收；本报告的 COVERED 仅表示本次审读存在明确
字段级规格，不能作为全路径实现证明或化简授权。其余未逐类型穷尽的 native/custom
实现按版本化边界规则保留，不因本报告消除其证明义务。

## 关闭顺序

先保持当前冻结回归完成；随后作者修正文档中 G1—G5。复审时保留本原报告/JSON，
另保存修订后文档 hash 与逐项关闭证据；不要覆盖原失败事实。上述都是规格修订，
无须为它们启动 LeWM、GPU 实验或添加优化实现。全部关闭后才可重新判断 M2 规格
是否通过；M1/M3 及后续门继续独立验收。

# D1：入口优先的自动程序展开

状态：Proposed，尚未实现。前置 D0 见 [紧凑源码见证](N2_CALL_SEEDS.md)。
本门直接修复“新真实调用见证没有进入自动展开队列”，不增加 detector/backend。
完整 actual→formal、函数环境、循环、状态与化简指导仍按原 C1/C2/E4 门验收。

## 1. 输入与交付

输入仍是原程序入口、项目范围、原始 calls trace 和独立预算。不要求函数名单、
业务常量、手写图或 pure 声明。新增 calls 输入启用 inventory v6；即使没有
eligible seed，也保留原始输入、版本和具体缺口，不能回退成仅文件名匹配。

v6 必须实际输出：

1. 自动发现的入口/import/source 范围及未解析边界。
2. 紧凑 calls report 和每个分组的 scope/definition/body 接入结果。
3. 有类型来源的确定性展开队列与实际构造成本。
4. 最终准确的 definition→core region 链接，或不支持/预算/准备失败原因。

源码见证只选择应分析哪里，不证明实际函数对象、参数路由或纯性。D0 group
没有完整 caller 链，不能把 first/last anchor 时间先后当成运行层级。

## 2. 来源与版本

旧 `BodyExpansion.OBSERVED_CODE` 要求旧 `observation_indices`。不能把新 group
序号、call anchor 或 invocation 编号塞进那个字段。

v6 用新版薄调度记录及有类型的 DemandOrigin，区分：

| 来源 | 必须保存的对应 |
| --- | --- |
| EntryRoot | 原始程序入口及对应源码作用域 |
| LegacyObservation | 旧 RuntimeScope 的具体 observation 身份 |
| EnteredCallCode | 本次重放的 compact report 中 `(process_id, code)` 分组 |
| SourceCallCandidate | 具体 caller source use/operation 及条件目标见证 |
| Remainder | 明确无观察证明的静态剩余定义 |

同一定义可以有多个来源，只构建一次。多个 PID 的分组分别保留，不合成一次
虚构 invocation。新记录共享 lowerer、状态/预算核算，不复制一套程序图。
旧 v1–v5 的 decoder、排序、profile 和规范重放保持原算法。

**作用域 frontier 与普通函数 body 队列分开。** EntryRoot 对应入口模块初始化
作用域，不是一个伪造的函数 DefinitionID。现有 `_Inventory.module` 已取得
来源模型的 module initializer 身份；v6 应保存其 snapshot/owner 对应并据此
索引调用。模块、class、函数和 comprehension 的 source owner 要区分；普通
C0 函数 body lowerer 不支持的作用域继续有明确边界。不能为了“入口优先”把
模块当作已建好的 C0 Region，也不能把默认值/装饰器归入被定义函数的调用期。
入口来源用于 frontier；后续函数任务沿具体 SourceCallCandidate 及其 frontier
原因连接。两个 ledger 共用来源类型和预算服务，但不混淆任务对象。

## 3. 准入与最终连接

只从 D0 `eligible_groups()` 准入，再核对本 PID capture、VERIFIED link、完整
唯一 definition/source/snapshot 与新 discovery、prepared context、FileInventory
精确对应。跨视图 snapshot 用 canonical path + decoded UTF-8 fingerprint 对齐，
不是整对象直接相等：discovery 保留实际 encoding 且 python_version=None；既有
witness snapshot 默认 encoding=utf-8 并记录当前 Python major.minor。输出 witness
仍保留原字段约定。相同 filename/qualname 不补对应；验证到准备之间源码漂移拒绝。

`call_source_scope` 保留每组的接入结果。最终 body 链接在 FileInventory 完成后
统一形成；构造失败、文件回滚或无 body 时不能留下悬挂 RegionID。

未知/不支持/预算边界分项报告；不把成功 indexed、成功 source match 和成功
core body 合并统计。需要 module/class/lambda/comprehension 接口的定义也单列，
不能通过增加普通函数尝试次数掩盖它们。

源码格式不能仅由后缀决定：D0 反例已经证明 Python code filename 可以是
`.json` 或其它名字。v6 对完整核验的非 `.py` 来源应有明确准入/不支持结果，
不能让旧 additional-entry 后缀检查使整个自动分析意外终止，也不能把它直接
当成数据文件。旧 v1–v5 的既有后缀接口不在本门静默变更。

## 4. 入口依赖调度

目前两处旧策略不足：discovery 把 additional entries 放在 entry imports 前；
body heap 同级按 source.path 排序，可能让字母靠前的 callee 抢到 caller 前面。
v6 单独采用以下可重放策略，旧版本不静默改序：

1. 原始入口及其依赖 frontier 优先。
2. 从入口初始化作用域的源码调用按源顺序展开直接条件目标。
3. 处理一个 owner 时只推进直接需求，不预先递归耗尽所有 witness 预算。
4. 尚未连到入口的 entered-code 定义作为独立观察根，优先于 remainder。
5. 文件路径仅作最终确定性 tie-break；不能靠文件名实现层级。

这里的源码候选关系仍有条件，不声称已证明实际 dispatch；缺失动态调用边的
观察根必须显示未连接。优化的提升位置以后根据实际值/状态/控制依赖求得，
不能以调度顺序冒充合法提升点。

## 5. 共享准备与模块依赖

D0 `_Sources.context` 已调用 prepare/index。直接 resolver→现有 expansion 会
重复准备 seed 文件，不能再声称 prepare 一次。实现应通过私有组合工厂共享
轻量索引及 PreparedContextStore，保持独立 source/raw 校验和 spool 预算。
如果首版仍重复准备，报告真实次数/耗时，再依据成本修复。

已由单文件 cProfile 及代码审查确认第一步的具体边界：`_Inventory.index()`
遍历后调用 `snapshot()`，后者为 `SourceContextDigest` 计算三个完整图摘要；
`_Sources` 仅消费 snapshot、definitions、coverage，从不消费该 context digest。
先新增私有 source-witness index 发布路径，复用同一个 walk、完整 source-atom
coverage 检查和原 identity factory，只返回所需三类内容。原 `index()/snapshot()`
及其历史报告仍保留全部摘要。新匹配结果必须逐字段等同冻结 D0 的 code/source
见证，再根据实际成本推进共享 spool，不能删验证换取表面速度。

进一步 AST-only 索引另作论证：annotation 内 lambda、match case 内 def 等
位置可能没有 legacy call-time operation，现有 identity 会走 inventory fallback。
不能按函数名和行号重新计算一套看似相同的 ID。

其 atom ordinal 来自完整 `ast.walk`（包括未变为 atom 的节点），operation serial
来自同 base 的原发射顺序。需比较重复 def、decorator 首行、annotation lambda、
match 内 def、编码 cookie、type-ignore、root `__init__.py` 的完整见证。彻底跳过
prepare 还会去掉旧 CFG 的 node/edge/work/nesting 边界，可能把历史失败变为成功；
这需要版本/策略分派，不能冒称仅是等价提速。先去掉未消费摘要的步骤保留这些
原边界，独立验证全部成功与失败 CodeSourceLink 不变。

还需处理现有依赖环：call_seeds→call_edges._Sources→program_inventory._Inventory。
inventory 不应再顶层反向导入 call_seeds。抽取共享 source-witness/index 接口，
让协调层注入有界准备/索引服务；原完整调用路径与 D0 使用同一源码核验规则。
不提供外部 `trusted=True` 以跳过验证，也不因抽取而复制核验算法。

## 6. 自主验收

| 门 | 验收结果 | 必须阻断的反例 |
| --- | --- | --- |
| D1.a | typed 来源、v6 严格记录/预算/重放分派 | call group 冒充旧 observation；跨 PID 补 capture；无唯一 definition 仍接 body |
| D1.b | 原始多文件程序自动 scope→队列→body，入口依赖优先 | 无关且字母靠前的 seed 抢预算；caller/callee 按路径倒序；同定义多来源重复构建；失败退款或悬挂链接 |
| D1.c | 冻结必要门与回归、原 LeWM 同入口/trace/预算复验、文档与版本提交 | 删改 anchor/源码/预算/准入/优先级后仍通过；零 seed 丢输入；旧 v1–v5 重放变化 |

外部报告给出自动发现文件、代码/definition 准入、尝试/支持/未支持、source→core
准确连接、未接观察根及 prepare/compile/restore 次数、耗时、RSS、磁盘新增量。
不以 body 数量增长宣布完整连接，不以分析耗时冒充 LeWM 加速。

开发者自行逐门验收并保存失败/通过报告，完成后提交推送；无需用户逐门批准。

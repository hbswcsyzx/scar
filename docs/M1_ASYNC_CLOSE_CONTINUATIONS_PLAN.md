# F19：关闭请求、真实终结与后续体

2026-10-20。基线 `b2f7e1ec58c5726a61753ffbe8d9ca125c89a162`，上一门为
`model_async_terminal_semantics/verified-current`（不是中断的 verified-final）。
原2104条相关case、899个源码文件、Program26/Execution8的意义保留。

## 范围与顺序

本门落实原F19，不增加detector/backend，不运行新的LeWM性能实验。规范实体仍为
Operation / Value / StateLocation / Region / Resource。以下均为原操作、Uses、CFG、
SSA state和实际occurrence的连接；派生查询不能变成第二份producer/control图。

原F19的完整验收单位保持：

1. **实际终结后新请求**：先有真实BodyReturn(None)或BodyRaise以及F，再有新
   athrow/aclose的无Drive回复；同R重试与新R分开，原参数不必被规范化。
2. **graceful close**：GeneratorExit进入finally，允许AWAIT/HOLD，同R用当次S
   恢复，直到真实terminal；body完成和request迭代器回复是两层转换。
3. **illegal close-yield**：错误constructor之前R完成，但B仍Suspend；同R重试、
   新R无Drive、同B之后恢复finally及真正终结贯通。constructor own N/R保留。
4. 上述组合的原输入、当前全state、host/caller、错误连接、删附件、实例缺采和
   tiny budget；不以已通过组件代替未供采组合。

**当前实施批次只关闭第1项及共用无Drive查询接缝；第2/3项仍开放，F19整族
不予关闭。** 这个批次边界用于控制改动与测试成本，不缩减原F19或第一阶段分母。
F19后仍有F20/F22/F24/X25/X26/X27、P4 component/full、P5及M2原113/196。

## G0：已确认的证据与接缝

- 固定CPython3.14.7 `genobject.c` 2108–2140：先R CLOSED、再frame finished、
  再active session和ag_closed；finished frame的新athrow/aclose回复StopIteration，
  不执行后续raw throw normalization。上一门native-probe的22调用与两编译观察复用。
- 原`async_session_sources.source_inventory`只枚举BodyDrive后继；
  `request_admission`只枚举FinalBodyGate。不能据此宣布无Drive路径不存在。
- RequestAssociationRead的双B/L结果不能冒充仅读取R.agt_gen的操作。
  已有RequestAssociation允许body精确own结果、latent显式StaticProtocolGap；
  应分别解析角色。无L声明仍是不完整关联，不能自动授予latent来源或纯性。
- R.COMPLETE、active session、ag_closed字段、真实B终结F独立。普通字段读写
  及准确owner/selector建模ag_closed，不能用BodyStateCondition.IS_CLOSED冒名。
- graceful close的两层转换是数据依赖加控制依赖；新异常构造不是旧包copy。
  第2批须沿matcher→own bool→branch→实际constructor→host展开，不放宽copy规则。

## G1：当前批次合同与实施责任

1. **无Drive库存**独立来自async driver原entry/receiver/S、原branch、INVOKE N/R、
   host边界和BodyDrive。附件删除不能删去原库存。有限CFG行走停在Drive/首host，
   cycle、缺口、预算显式保留；不能把未访问边界称为已证无Drive。
2. **按角色投影**从原R/Create求body来源；仅需要body时不追latent/normalization，
   不制造L result/Use。不完整整体关联继续明确partial；这是既有声明的派生视图，
   不是字段名、同类型或generic READ自动证明字段内容。
3. **两条真实terminal主链**复用原真实Return/Raise骨架、F和当前state，后续新
   athrow/aclose只走原predicate/branch/COMPLETE/own constructor/host；保留完整
   未选CFG但不造实际Drive、body segment或新的B。
4. 原input/producer精确复制与原路径上的fresh value分别报告。native适用、
   source对应、runtime身份、变换和性能权限继续false。

公开接口决定：`ProgramIndex.request_no_drive_paths(scope=None, *, budget=4096)`
使用独立预算；原async报告只新增廉价`request_no_drive_inventory`原记录库存。
不把新CFG扫描塞进旧共享预算，避免改变旧消费者配额和截断含义。库存以原
ASYNC_REQUEST DriverInterface及ASYNC_GENERATOR body为分母，不依赖可删除scope附件。
query作者另拥有`queries.py`一处薄委托。整个prefix已核并到首host才可以报告
`declared_no_drive=True`，它不授native适用或变换权限。

源码责任在明确分配后冻结：query作者只改原async查询及新薄派生模块；fixture作者
只加新fixture/test；root负责计划、archive、串行执行、修正协调、验收和版本管理。
作者不运行Python/pytest/probe/compile；root仅在全部源码作者FROZEN后执行。

## G2–G4：自验与记录

- G2：真Return与真Raise后都覆盖新athrow/aclose，检查同B/新R、own N/R packet、
  当前全state与host/caller；同R拒绝仍由原独立组件保留。对错包/错state/错F至少
  各选有区分力的连接反例，不做请求×路径×缺采的无谓乘积。
- G3：删关联附件保原操作库存；缺一次新request实际call保完整兄弟；budget=1保
  原分母与cursor。串行保首败源码/命令/JUnit；旧fixture和case身份不变。
- G4：所有源码冻结，root只做必要定向及受影响回归；独立复审确认剩余原义务。
  写实际验收报告，普通commit/push并核远端SHA、tracking和干净状态。

Observed是既有native观察；Implemented/Verified只据本次实际代码与测试填写。
提供的结构fixture不能算自动拆解LeWM；测试耗时不能当LeWM加速比。

# D6：原拷贝消费者与调用展开视图

2026-10-19；基线 `5c8b60a0f81739445fa240224b101197cb93db5d`。
**D6_FROZEN**：经A/B/C有限只读审查，补根caller边界及条件消费含义后冻结。
沿用完整A–H/16/P5/M2，不改变验收终点。

## 与核心模型的关系

Operation / Value / StateLocation / Region / Resource不变。调用参数、entry formal、
RETURN/RAISE Use与caller result仍取原规范图。本稿是原图的查询投影，不引入
第二producer、ValueID、InvocationID或wire。source/runtime/value验证和变换权限
全False。原Program23/Execution8不变，不增加detector/backend或业务规则。

新增通用 `ProgramIndex.copy_consumers(source, guard=None, budget=4096)`。
此图追踪**同一来源的原copy**到消费者前沿，计算/转换产生的新值不变成该来源的
alias；完整值来源图与整体程序图仍在原路线中，不将本查询称为全部依赖恢复。
现await库存复用同一查询内部实现及其ConnectionContext/shared budget。

## 调用上下文与端口

报告含 `source/choices/frames/inventory/status/gaps/cursor/budget/preparation`。
`frames`为平坦tuple，根key=()，child key=parent key+(call OperationID,)。
这是静态调用路径投影，不是动态调用身份。相同callee不同call-site分别保frame。

每frame保 `key/region/parent_call/may_seeds/must_seeds/inputs/consumers/calls/
returns/boundaries/status/gaps`。may/must seeds是原ValueID集合，child entry seeds按本call准确
actual ordinal→formal建立。inputs保本call的**全部**参数，不只被source命中的参数，
每项 `ordinal/actual:OwnedUse/formal:BlockArgument/may/must/binding`；state参数亦保
原对应，不断言state写入前后相等。root为状态版本时可跟踪该原版本的读/转发；
WRITE产生的新state版本不是旧版copy，状态仍由原state SSA管。

消费者项保 `key=(frame key,OwnedUse)/actual:OwnedUse/role/kind/slot/may/must/
binding/status/gaps`。每个原Use保独立项；RETURN(x,y,state)的x只对应slot0，
RETURN(x,x,state)两Use都保，HostTerminal仅可用于兼容展示分组。
kind/slot是原terminal的ExitKind和完整ordinal，不能用去掉state后的序号代替。
ordinary算子消费者role=OPERATION，call actual为CALL_ARGUMENT，出口为EXIT。
binding.match表示must-copy结论；may=True、must=False是已知条件性消费，status为
CONDITIONAL，不是CONTRADICTED。must=None才是该检查未能完成；False不证明值不相等。

call项保 `key/operation/callee/arguments/child_frame/status/gaps`。原call inventory
先于may结果；未命中的call保NOT_APPLICABLE，未完成的membership保None，不按
expected root或某条好route反选唯一caller。inputs.arguments全tuple保守恒。
未知native INVOKE、effects不完整及递归保准确边界，不伪造callee或consumer。

returns保原callee terminal Use→该frame父call准确结果的接口，字段
`kind/slot/actual:OwnedUse/caller_result/landing_position/may/must/binding`。
普通CALL仅NORMAL的OperationResult；INVOKE按原N/R、CompletionResult.ordinal
和landing position分别映射。forwarded state只保原edge Use/position，不能冒充
callee产生的post结果。子frame的RETURN是返回边界，不是整个查询的最终输出。
根source若位于有原caller的region，key=()不选择某个invocation；其可能上返的
出口保所有原caller边界到boundaries，无法确定上下文就pending，不任选caller、
不漏掉外层消费，也不宣完整库存。本轮不将未完成上返改称图已完整。

## 计算规则

1. 原fresh may-copy按位置membership和Value→Use索引枚举原消费者，不全图逐Use
   重扫。must-copy独立核；may候选不升级为must。给定root来源后，本call的actual
   是copy，才使该ordinal的entry formal成为seed，不能仅凭来源仍在fresh集合中。
2. child may seeds保所有可能输入，child must seeds只保已证输入。多参数一起传播，
   不将两个独立recipe的成功拼成整个tuple成功。局部copy证明与root→frame输入
   支持分开，未证的父输入不能被child局部True盖过。
3. 复用ProtocolFlow/CallReturns的源重执行reset、CFG并行拷贝、所有原出口与
   kind/slot摘要。局部摘要可复用；调用frame和其输入证据不能因同callee而合并。
4. caller/descendant guards保原完整tuple。同一shared callee的无frame限定静态
   选择若不能确定适用的调用，保 `copy_consumer_guard_context_unresolved`，不扩大
   ControlEdgeReference权限。递归不无限展开，保原call锚与具体pending原因。
5. 只展开已知callee。计算结果、异常组件打包/提取等不是普通copy边。effects未知
   或opaque/native内部未建模，局部Use复制仍可证，内部库存不能宣完整。

## 库存与预算

一份ConnectionContext/ProgramIndex与一份shared budget；不在每个consumer重建
公开source_binding包装器或重置4096。原索引准备成本单列；frame、每indexed Use、
参数、返回端口、去重、path复制与派生关联均收费，缓存仅query局部。

inventory至少保 `enumerated_frames/checked_frames/frames_total/enumerated_consumers/
consumers_total/known_inventory_complete/proofs_complete/cursor`。
只在关联库存完整时给total整数，否则None。未证must不等于没枚完may库存，
proofs_complete按检查是否完成定义，已知False也可完成；未知或未查保False，
并不表示所有must都成立。它与known_inventory_complete分开。budget1/late-budget保根及已知原
锚和cursor，不能用visited prefix充完整分母。流求解未完成时保原call边界，即使
还不能证明该call的actual消费source，也不将未知变NOT_APPLICABLE。

公开返回deepcopy，query-local结果和guard缓存不污染构造ctx。保原await targets/
support兼容字段，在ledger及其公开consumer项增加 `consumer_graph` 引用；旧单层
targets不是跨frame总库存。仅当新图关联完整时，原callee-expansion pending才可
清除；原最终提取语义审批不由copy图自动授予。

## 本轮自主验收与原范围

先冻结合同，独立作者写新fixture/tests，root存真实首红再改产品；所有Python/
pytest由root串行执行，执行时全体作者冻结，旧tests/fixtures不改。
至少覆盖：普通/两层callee、共享callee两个来源、多个参数、两个出口payload与
重复payload Uses、INVOKE的N/R与非同序landing、mutating state不伪copy、source
重执行/合流、递归/opaque、删附件、budget1/late-budget、detach。
以原await结果链插入转发helper，原source、helper actual/formal/内部Use、真实
extractor、own N/R与最终target均保留，不因helper名字识别，也不冒称它是extractor。

本轮图的转发连接不是最终提取合同闭合，不关闭原A–H/16或M0–M2。随后继续原
跨callee的语义结果/执行连接、C1及剩余组合，原16齐后才组件/full与P5/M2。

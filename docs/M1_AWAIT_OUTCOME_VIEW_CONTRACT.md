# D4：原source、结果端点和消费者的临时查询视图

2026-10-19；基线 `69ed9e334a479132935d3493ab4f879ae181081d`。
延续原 [完整单位计划](M1_AWAIT_OUTCOME_PLAN.md) 和
[三路审查](M1_AWAIT_OUTCOME_CONTINUATION.md)，不改D0–D3字节及原A–H/16组。
**D4_FROZEN**：经B有限反对性审查，补齐source自身RAISE与不伪造completion
两项后冻结。此为查询合同，不是完整A–H/16组验收。

## 实体、权限与原key

保持Operation / Value / StateLocation / Region / Resource及Program23/Execution8。
只在现有 `protocol_obligations().connections.families.await` 增加查询派生字段，
无新wire、producer、普通copy/identity边、native实现证明或变换授权。

`outcomes` 中一项是静态义务，key为
`(scope, source_operation, advance_operation, input_guard, choices, DriveOutcomeRef)`。
同advance的N/R记录归同原operation，分支保在子legs；原caller context及所有route
保在binding/tuple覆盖中，必须全覆盖，不把本key称InvocationID。
key不含可选adapter/consumer附件；删附件不能删原outcome/原consumer。

每outcome保 `key/scope/source/source_operation/advance_operation/input_guard/choices/
drive_outcome/payload/kind/conversion_legs/consumers/status/gaps`。
`kind` 为HANDOFF / RETURN_COMPLETION / EXCEPTION / UNRESOLVED，来自原body终端。
`payload`为原DriveResult；原公共payload各Uses及state支持分别保留。

## 原库存与四种路线

先由已有source-first job和原BodyDrive所有successors枚举outcome，再左接metadata。
未完成source→advance适用性不能假装总数完整；已知Drive后继表是原索引库存。

1. Suspend的HANDOFF：原export→中间consumer，不要求完成值提取。
2. BodyReturn：固定GENERATOR/COROUTINE_RETURN_TO_STOP_ITERATION转换own NORMAL
   →原PacketDefinition whole packet→driver RAISE→本advance RAISE→最终提取。
3. 同转换own RAISE：自身whole packet传播，是CONSTRUCTION_FAILURE。
4. BodyRaise及其他失败：自身packet或准确已声明适配，非第2种完成。

`conversion_legs` 每项保 `operation/edge/own_result/role/input_binding/packets/terminals/
bindings/states/status/gaps`。role为COMPLETION / CONSTRUCTION_FAILURE / EXCEPTION /
HANDOFF；缺转换保原outcome和具体gap。原op全部N/R来自原completions而非现存row数。
同advance RAISE在caller合流，仍按各转换leg的原choices核，不能混成完成事实。
条件语义投影不进入普通copy闭包；不是比较body值与extractor输出相等。

## 消费者及最终提取

`consumers` 从原advance result按原may-copy与原Use索引建立，后核准确case的must。
每项保 `actual/advance_result/choices/binding/final_rows/legs/status/gaps`。
actual是原OwnedUse或HostTerminal；不能由final_rows先决定actual或库存。
每leg保 `edge/own_result/kind/targets/bindings/states/status/gaps`。
提取器own NORMAL最终值与own RAISE异常传播分别保原端口和消费者。

原Value→UseSite索引用ProgramIndex._consumers；按may flow逐位置membership取候选，
不能把不同位置fresh集合并集作为消费证明。may None是未完成，不是空集合。
真实call actual先保为原consumer边界，准确actual→entry formal再展开；未知callee、
递归、opaque或预算缺失保pending，不宣跨region库存完整。所有已知callee返回
kind/slot、caller guards与current来源均沿现有CallReturns/bind/correlate核。

有准确转换COMPLETION链的consumer若无最终提取合同，保原consumer和原operation
实际存在的全部completion legs；ordinary/onlyRAISE不得补造另一腿，
记 `await_final_adapter_missing`。已知自己的输出被原附件所列最终target替换为
另一同型值，必须报告矛盾；不能只看targets非空或某一guard成功。
删除producer转换附件保 `await_completion_adapter_missing`，不凭原op名称猜语义。

## acquisition失败路径

`failure_paths` 从原source scope/operation、展开stage及原控制边建立，不依赖成功
advance。key为 `(scope, source_operation, stage_operation, ControlEdgeReference)`，
可选acquisition ref只作属性，删row仍保原scope的source自身失败义务。
每项保 `key/scope/source_operation/acquisition/stage/edge/choices/terminals/status/gaps`。
stage为ACQUISITION_RAISE / WRAPPER_CONSTRUCTION_RAISE / LOOKUP / METHOD_CALL /
QUALIFICATION_REJECT / QUALIFICATION_RAISE。source own RAISE从原scope subject的
真实INVOKE后继建立，即使无展开或成功advance也保留；不是只遍历展开metadata。
前两种及INVOKE资格使用自己的RAISE；bool拒绝取准确branch polarity的另一原边，
携此前stage NORMAL选择，绝不在BRANCH伪造InvokeLiteralResult。

每terminal保 `terminal/packet/binding/states/consumers/status/gaps`。packet只能是
该原终端的whole exception packet Use；binding连接本次parent RAISE准确result。
state按原signature location与slot逐项保各自terminal post→parent post关系。
未知/非RAISE终端不能当合法失败；不能把早lookup RAISE代替qualification拒绝。
原packet组件证明不等于异常类别证明，缺类别证据不靠TypeError标签补齐。

## 同一预算与公开计数

全部沿一个ConnectionContext/shared budget；原raw索引准备成本单列。
候选提取、indexed Use访问、去重、CFG/packet/各端口、binding/tuple均扣实际预算；
缓存仅当前ctx，并区分source、准确端口、choices/caller和mode，不重置4096。

`outcome_inventory` / `failure_path_inventory` 至少保
`enumerated_count/checked_count/pending_count/jobs_total/known_inventory_complete/cursor`。
jobs_total只在相关原关联库存完整时为整数，否则None；pending_count同理。
outcome另保 `drive_successors_total`（原索引全部Drive后继总数，不冒source组合数）。
预算1保准确原总数或明确未知及cursor；不得把prefix len叫原job总数。
NOT_CHECKED保持原锚，未查bindings/semantic结论不伪造成成功。

## 原验收，不缩范围

先保真实首红，再实现原公开接口与有限反对性复核，作者冻结后root串行回归。
旧tests/fixtures及旧codec字节保留；新test与产品由不同作者负责。
同一原流水线覆盖：零/多cut、三路来源、W/B、转换自身RAISE、BodyRaise、最终
提取N/R、mixed/crosscaller/current、全删附件、缺capture及budget1。未覆盖者继续
OPEN，不拿本稿字段或局部green关闭完整A–H/16/P5/M2或宣自动whole-LeWM建图。

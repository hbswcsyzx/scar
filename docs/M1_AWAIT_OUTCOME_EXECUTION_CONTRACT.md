# D5：结果与失败义务的逐次执行投影

2026-10-19；基线 `287c906c95658d25200d057fe9002fc3d1f8479c`。
沿用原A–H/16组和D0–D4，不改原验收分母。**D5_FROZEN**：经A/B/C有限
只读审查，补齐类型、完整parent计数、适用腿与准确callee completion后冻结。

## 目的与边界

原Operation / Value / StateLocation / Region / Resource不变，Program23/Execution8
不变。在 `ExecutionIndex.await_body_links(scope, budget=...)` 增加临时查询视图，
从D4原静态义务左接实际capture。不是新的执行记录、优化器或native实现证明。
所有source/runtime/value验证及transformation_authorized继续False。
本门不声称完整A–H、跨callee consumer展开或自动whole-LeWM建图完成。

## 库存先于capture

复用同次查询的 `ctx.await_flow`、`ctx.body_program_index`、shared budget及原
await inventory；不调用会重建预算的公开ProgramIndex接口。
先按原parent/source scope限定静态义务，再关联capture，不按观察到的Drive、
成功advance、final adapter、receipt或现存packet筛静态分母。

新增顶层 `outcomes/outcome_inventory/failure_paths/failure_path_inventory`。
每个静态项保 `key/definition/occurrences/status/gaps`，key和definition来自D4；
即使零capture仍保该项。outcome动态key为
`(static_key, advance.id, drive.id|None)`，failure为 `(static_key, source.id)`。
同原operation各N/R保子legs，不能把静态key称InvocationID。

inventory保D4的 `enumerated_count/checked_count/pending_count/jobs_total/
known_inventory_complete/cursor`，另列 `occurrence_count/checked_occurrence_count/
pending_occurrence_count`。occurrence_count为原已捕获parent-site发生数，分别按
静态义务计数，不是本次检查prefix，不是程序实际总执行次数；关联搜索未完成的
job总数仍None。预算1保原锚、未知分母和cursor，不能冒称未见义务已检查。
checked/pending也按同一parent锚计数；该锚下全部候选routes检查完才计checked，
不按派生 `(advance, drive)` 行数计checked。

## outcome逐次投影

动态项保 `key/advance/source_candidates/matched_sources/call_chain/drive/
body_outcome/selected/conversion_legs/consumers/status/gaps`。
advance/drive/body_outcome/source/stage/operation均为原OperationOccurrence或None，
call_chain保原resolved CallActivation视图，不把drive字段复制造成另一query报告。
先从确切advance沿原CallActivation链取本次Drive，再取其BodyDriveExecution
与实际outcome。不同原outcome、case或source guard对应NOT_APPLICABLE；
缺association/transfer/outcome为None与gap，不能反选expected source。

conversion leg保 `definition/occurrence/selected/own_value/input_binding/packets/
terminals/states/status/gaps`。candidate仅限本次driver activation及实际Drive后的
host路径；不借同静态site另一activation、旧segment或loop之前的capture。
own N/R按原selected transfer，另一leg保NOT_APPLICABLE。

packet保 `definition/occurrence/value/exception_use/exception_value/binding`；
constructor NORMAL Reference到准确PacketDefinition.exception是组件关系，
whole packet另取准确pack结果，不把Reference与whole packet放进copy闭包。
constructor RAISE、BodyRaise和中间HANDOFF继续分开。

consumer保 `definition/operation/use/advance_value/binding/selected/legs/status/gaps`。
原actual可为OwnedUse或HostTerminal；只查本次advance caller activation且在该
advance之后的准确host路径。缺operation或UseOccurrence仍保原consumer和None/gap。
已知callee内部consumer未展开继续pending，不能由全局同site补端点。
final leg保 `definition/selected/own_value/targets/states/status/gaps`；target保
`definition/operation/use/value/binding/status/gaps`。按原N/R、slot和landing位置。
缺final metadata时原consumer及own legs不消失，静态gap传播。

## source失败投影

动态项保 `key/source/call_chain/stage/selected/prefix/terminals/consumers/status/gaps`。
source自身RAISE/WRAPPER_CONSTRUCTION_RAISE检查其own edge，即使无advance仍保。
expanded lookup/call/Q先取同一source的准确CallActivation，再查对应callee发生。
prefix保 `edge/occurrence/selected/transfer`，QUALIFICATION_REJECT核原branch极性，
不伪造Invoke结果。另一实际stage选中的edge令本path NOT_APPLICABLE，不冒充成功。
expanded terminal须是该source准确CallActivation的completion；parent须选本条RAISE，
通过此调用outputs的准确ordinal/formal核packet和state，不能借同activation别的出口。
terminal保 `definition/operation/packet_use/packet_value/parent_value/binding/states/
consumers/status/gaps`。exact helper terminal→parent R result，source-own路径则
parent R result→caller terminal；方向来自D4原binding，不交换source与target。

## 证据、状态与预算

动态copy证据走原CFG/CALL/BODY recipes及bounded ancestor闭包，返回
`source_value/target_value/match/support/compatibility/gaps`。
仅root相等、同ObjectID、同类型或compatible()成功不替代原copy支持。
缺copy链导致不同root不能单独证明值不同；确切不相容另列issue，缺采保None。
state保D4原definition、准确source/target、slot或forwarded position；
forwarded state不发明post result。所有子项False/None/gap向上汇总。
NOT_APPLICABLE只由准确outcome/transfer/guard否定产生；缺记录不是不适用。
只汇总适用子项，另一未选leg不污染本腿；已选腿内错packet/copy/state仍为矛盾。

所有path、call、packet、consumer、recipe ancestor、state和关联检查扣同shared
预算；只准备原索引的成本单列。缓存仅query ctx，不污染构造ctx，返回deepcopy。
DECLARED只是原声明与本次捕获条件连接；NOT_APPLICABLE、NOT_CHECKED、PARTIAL、
CONTRADICTED分别保留。缺captured endpoint不能成为DECLARED。

## 自验收

新测试作者与产品作者分离；旧tests/fixtures逐字节保留。root在所有作者冻结后
串行执行，先存真实首红，再修产品，逐attempt保命令/log/JUnit/前后SHA。
覆盖零/多cut、constructor与extractor自身RAISE、HANDOFF、双instance缺准确Use/
suffix、整删final metadata、source-only失败和缺CallActivation、budget1、detach。
检查scope不受无关Q污染；原scope通过ExpandedAwaitCallee指向的Q仍保合法覆盖。
保上一全部1477精确caseID；本次focused不替代历史full或原整门验收。

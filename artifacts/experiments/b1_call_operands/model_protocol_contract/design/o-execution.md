# P1-O：持续 body 与本次 Drive 的最小发生合同候选

基线 `f9a568182e1672541261020bb9f919609179bb05`，只读设计。父计划 `docs/M1_PROTOCOL_FAMILY_PLAN.md` 的 **F01–F24/X25–X28 完整分母保持不变**，本文件只细化 O（尤其 F02/X27），不以此关闭 raw→delivery、adapter、delegate/no-body、取消等 F 义务。
未修改产品/docs/tests，未运行 Python/compile/pytest/GPU/LeWM；以下为 Proposed，字段需 root 联合冻结，非已实现或运行采集证明。

## 1. 唯一规范事实与最小 records

根已决定两表使用自然键，不为现有框架镜像新的人工 association ID。constructor 为 frozen/slots、exact typed IDs/unions，嵌套重新校验（含 ID 内 exact nonempty str），无可写 verified/identity/generation/phase/actuals/state 字段。

```text
BodyDriveExecution(
    drive: OperationOccurrenceID,
    activation: RegionActivationID,
    entry: BlockVisitID | Unresolved,
    outcome: OperationOccurrenceID | Unresolved,
    source: FactSource)

BodyActivationOrigin(
    activation: RegionActivationID,
    creation: OperationOccurrenceID | Unresolved,
    source: FactSource)

ExecutionModel.body_drive_executions: tuple[BodyDriveExecution,...] = ()
ExecutionModel.body_activation_origins: tuple[BodyActivationOrigin,...] = ()
```

- Execution 主键 `drive`；Origin 主键 `activation`。当前 `_Context` 只对显式列出的表走 `.id` registry；新表建立各自自然键索引，不改旧 registry 或 CallActivation。model.uses/transfers 也有无 id 的自然键先例。
- 不另存 segment：从 entry.visit.segment 派生；若仅 outcome 已知，从 outcome.visit.segment 得到该次候选 segment并校验。双方都已知必须同一 segment；双方未知则 segment=None+gap。
- 不另存 body：由原 BodyDrive.target + `program.driver_flow.body_drive_target` 派生；activation.region 必须匹配。
- 不另存 owner：由原 BodyDrive.instance 的原 UseID→该 drive 的 UseOccurrence→ValueOccurrence 派生；缺采集保留该原 Use 和精确 gap。
- 不另存创建 handle/captures：由 creation 所指原 ResumableCreate、其 NORMAL port、CreationCapture、实际 completion edge/visit/UseOccurrence 派生。
- `Unresolved(reason, EvidencePoint)` 是缺捕获/外部来源接口，不是空值、成功或新的运行事件。EvidencePoint 的已知 run/process 仍核对对应 activation/drive；process=None 表未知，不虚构进程。
- 一次 Creation 可以有0次 Drive；一持续 activation可有多次 Drive/segment。no-user-entry、delegate-only、拒绝都没有父 BodyDrive，O 不为它们造发生；走原 F host/helper/adapter 路径。

## 2. 多重性与必须保留的区别

1. 每个 drive occurrence 至多一 Execution row；每个 activation 至多一 Origin row。相同静态 Drive site 的不同 occurrence 是不同键。
2. 已知 entry visit、派生的已知 selected segment、已知 outcome occurrence 不得被两个不同 drive row 双重认领。至少一个端点已知即可参与这些唯一性检查；两端未知不能凭空认定冲突或完成。
3. **同一具体 ResumableCreate occurrence 的 NORMAL handle 只能对应一个持续 body activation**，限固定 native frame-create/no-reset 合同。不同 creation 可同 body code，但不可合并 activation。外部 creation=Unresolved 不加入此反向唯一键，不能因其相同 reason/fact 就判重复创建。
4. 一个 activation 历史上可经历多个线程的不同 Drive。不得套 CallActivation 的 onecaller、全 activation 同线程、activation nesting DAG；这些同步 call 规则在 `call_validation.py:301–322,401–415` 保持不变。
5. 本次 drive 与其实际 selected segment 的 known thread 必须一致；未知是 gap。creation→后续Drive可以跨线程，不比较所有历史 body segments 的 thread。
6. 同一 ObjectRef 不是内容不变，也不证明调用有效/无反射/互斥。所有模型对应仍为条件声明，真正采集和实例识别属于M4；**O接口及机器拒错属于M1，必须本阶段落实**。

## 3. 结构解析顺序与坏 FK 边界

建议新 `execution/resumable_validation.py`（名称可机械调整）分两层，核心 resolver 放 `execution/resumable_flow.py`，供 validator/query 同用。不 import ProgramIndex 整图再 validate；复用 pure program.driver_flow、resumption.saved_actual_use 与现 ctx 的已验证索引。

### 3.1 先核所有已知端点；不因另一端 Unresolved 而跳过

在 `_coordinates`/`derive_flow` 已通过后：

1. registry/FK：drive occurrence、activation、已知 entry/outcome、已知 creation 必存在；缺 FK是Issue，不是 gap/KeyError。activation.region 必为声明 ResumableBody。drive 原操作必须确为 canonical BodyDrive 及 typed terminator。
2. 原 Drive 所属 DriverInterface.body、BodyStart/BodyResume 选定的 region 和 activation.region 全部一致。
3. derive 当前 drive 的 run/process，以及 activation、entry/outcome segment、creation 的 run/process。已知不同 run/process 为Issue；不从raw PID/TID复用或fact URI推scope。Unresolved.point单独核scope。
4. 独立核 entry 和 outcome 的activation/segment/thread/source；例如 entry=Unresolved、outcome在另一known thread/region仍必须Issue。driver thread未知不能豁免entry/outcome在两个已知不同segment的矛盾。
5. entry/outcome 两端都未知仍保留原 drive target/input/output静态分母，并报各自缺口；不挑相同代码/值/时间相近的另一记录填上。

### 3.2 初入 Start

entry已知时必须是 body.entry 的真实 BlockVisit，segment.ingress 为 InitialEntry；不是循环回访、resume/capture landing或同静态block另一visit。原 `_segments` 已限制一个activation一个InitialEntry（`flow.py:70–84`），O再核该visit是否确为本次声明选择。重复/歧义已知入口不自动挑first。

若 entry未知、outcome已知：仍从其segment验证该segment的known ingress与Start不矛盾；CaptureIngress仅意味着capture缺前段，不能据此证明完整初入。保留 `drive_entry_unobserved`/`drive_initial_path_unobserved`，不把中段观察改写为InitialEntry。

### 3.3 恢复 Resume：generation由原关系定位，不加计数

已知 entry 的 block 必等 BodyResume(suspend,successor) 精确 landing。该entry segment的ResumeIngress必须：

- suspension 指真实旧 OperationOccurrence，其原 operation 等 target.suspend；所属 activation等本持续activation；successor_index等target.successor；
- 旧 occurrence 真实 term为Suspend；旧segment与本次segment不同；原 ControlTransfer精确从旧suspension到本entryvisit，index一致；
- saved source 只取该**确切 suspension occurrence**上的原 saved UseOccurrence，不能取同site的另一次visit、最近一次tensor值或上一个driver的原始参数。

已知不一致是Issue；原 transfer 未捕获是gap；没有 entry但已有 outcome时，也要检查 outcome segment 的 ResumeIngress 及其 sourceScope/case，不能整段跳过。CaptureIngress在partial capture中保留未知，不伪造一个匹配的ResumeIngress。缺采集不是“换用另一generation”的许可。

旧 `flow.py:15–46,85–100` 的exact temporal transfer继续是规范，无第二控制边表。一个实际suspension发生的唯一outgoing已防止同generation重放到两个entry；多个静态loop iteration必须有新visits/occurrences。

### 3.4 实际首 outcome、路径和未完成

- outcome已知必须属于选定 activation/本次selected segment，原term是Suspend/RETURN/RAISE；static source在该target的first frontier。
- 已知 entry→outcome 应有本次segment内的真实ControlTransfer路径及block内顺序，首次碰到body outcome即停止。路径断采给 `drive_path_unobserved`，不补边；已捕获的相反路径/更早outcome/不同segment给Issue。
- 同一次selected segment若有两个已捕获的body首outcome（排除同步helper子activation的exit）则矛盾；不能因entry未知豁免。历史别的segments有其他Suspend是合法的。
- driver的实际 outgoing Transfer若已捕获，selected BodyDriveSuccessor.source必须等 outcome原OperationID；换另一个相同type/source-kind结果为Issue。outcome未知时保留真实已选static source但不把它冒充已捕获body occurrence。
- outcome已知但driver transfer未捕获：保留body原outputs和声明candidate successor，caller实际landing/formal=None+gap，不补NORMAL。BodyDrive不是INVOKE，不凭Return/Raise命名推它的host完成。
- outcome=Unresolved表示未获得该outcome观察：可以是进行中、发散或截断，**不单凭缺记录区分三者**。静态frontier空合法，不能发明completion；查询可列静态发散可能，但不声称实际已发散。

## 4. owner→creation→capture的必要关联

### 4.1 Origin检查

已知 creation必须指当前snapshot中 ResumableCreate 的真实发生，其声明body等activation.region。其actual NORMAL edge/landing handle按原handle_result.index精确派生；已知taken RAISE不能作为这个NORMAL-handle来源（Issue）。NORMAL边/handle值未捕获则保留Original port+具体gap，不任选其他Create正常结果。

Origin.creation是此activation的声明来源，不保证所有actual identity已观察。其存在不把source/native/runtime证明变真。可独立存在Origin但没有Execution row；不生成body.entry/InitialEntry或假执行。

creation=Unresolved可明确外部实例或缺创建采集；它不取消body代码接口，也不捏造captured arguments。Origin row缺失时仍有static instance-frame recipe与 `body_origin_missing`，不将缺来源当外部来源已完整闭合。

### 4.2 owner一致性：三值而非按ID名字强配

每次Drive owner从它自己的UseOccurrence取得。与Create NORMAL handle，以及同activation其他已声明Drive的owner比较：

- 原actual→formal的真实CFG/call/saved route可支持**声明的引用来源**；使用现 ControlTransfer、CallActivation已解析input/output、saved_actual_use及ctx.results/uses。这里不是新canonical alias图，不将ValueOccurrence IDs合并。
- 也可读取原ValueDenotation的ObjectIdentity(ObjectRef)。artifact scope采用现 `(sha256,schema,size_bytes)` key，URI是locator；同artifact不同ObjectID为已知矛盾，同ObjectID为相容的声明identity；跨artifact无显式已支持桥则UNKNOWN/gap，不按FactRef或URI不等判对象不同。
- known route准确来自另一具体Create，且与声明origin在固定native frame-create/no-reset合同下矛盾，拒绝；“同Region/code/LogicalVersion/内容相等”不弥补错owner。
- 缺source/denotation/route只给 `body_owner_correspondence_unresolved`，不反推无alias，不将SourceFact存在直接计为runtime证明。
- 两个不同activation双claim同creation occurrence按§2拒绝；creation未知不受此规则乱拒。同一owner在不同代码接口/已知origin冲突时须报告；仅跨artifact无法比较则保留条件。

**不新增ObjectID/lifetime表。** 当前ObjectRef的底层provider范围/真实identity仍依现denotation边界，不能从裸内存地址重用或Torch `_version`推body对象。

### 4.3 capture路由

Start的每个Reference formal按原CreationCapture.formal查准确source Use；其动态source只在该creation occurrence上取原UseOccurrence，entry端只取ctx.results[(entryVisit,formalID)]。函数对象/default/globals/cell等仍是原EnvironmentInterface/FunctionEntryLayout分区。captured Reference内容可变，当前内容依本次共享state，不复用creation-world。

每个capture row保留 `formal_definition, formal_occurrence, capture_declaration, source_definition(原Use), source_use(UseOccurrence|None), source_value(ValueOccurrence|Unresolved|None)`。漏一端保留该row+gap；两个形参引用同一Python对象仍各有独立Use，不去重。不要从actual值相等来找对应位置。每个已知source/formal还必须执行§5.1的兼容检查，不能只返回一条mapping便省略矛盾核对。

外部creation未知时返回原InstanceCaptureInput(ownerUseSite,formal) recipe和None actual+具体gap。**本最小O不自动解析外部frame内容**。若以后要验证外部capture actual，应由已建模的真实读取/helper/native原端口及source对应提供；不能用字符串field名或任选body entry Ref当“已观察capture”。当前Origin+recipe已能准确保守表达未知，不将它计为完整capture证明。

## 5. 当前/已保存inputs与本次outputs只做派生映射

推荐共享resolver输出（plain dict/query view，非新增Graph表）：

```text
{
  association, drive_occurrence, drive_definition, activation, origin,
  entry, segment, outcome, selected_transfer, selected_successor,
  owner: {definition:原Use, actual:UseOccurrence|None, value:ValueOccurrence|Unresolved|None},
  creation: {occurrence, declaration, normal_successor, transfer, handle_definition, handle},
  inputs: tuple[原formal + 源recipe/原UseSite + 动态sourceUse/sourceValue/formalOccurrence],
  outputs: tuple[原bodyUse + 动态bodyUseOccurrence + 原BodyDriveResult或forwardUse + 实际driverformal],
  gaps, conditions,
  source_runtime_verified=False, runtime_identity_verified=False,
  value_identity_verified=False, transformation_authorized=False
}
```

- 逐Location复用 `ProgramIndex.drive_input_bindings` 的派生规则（`queries.py:669–705`），不重复调用全图ProgramIndex/validator：Start STATE来自本Drive.state_inputs；Resume STATE同样来自本次current输入，payload来自精准resume_inputs.slot。
- SavedInput只从精确ResumeIngress.suspension的saved Use解析；这包括frame、LocalBinding、C1pending/savedcontext。它们保持body BlockArgument producer，不作为driver额外actual打包。
- 旧ValueOccurrence/旧state伪forward由现derive_flow的incarnation/current-state检查继续拒绝；跨边映射只是原端口对应，不要求driver与body formal的两个ValueOccurrence ID相等，也不声明其内容凭Location相同就相等。
- outputs只用实际outcome的原body_outcome_uses及当前Drive所选successor。BodyDriveResult.index匹配本源的原Use，extra driver state用本Drive独立forwardUse。缺actualsource不能从另一bodyvisit借值。
- INVOKE/BODY_DRIVE在`flow.py:210–217`没有common AFTER；后态按真实EDGE保留，RAISE部分写不回滚。实际body Suspend不是host方法已终结，O不选择SessionPost/adapter结果。

### 5.1 所有跨区域 binding 的已知矛盾检查

此规则统一用于capture、resume saved和delivered payload、body输出的BodyDriveResult，以及driver的forward Reference；不是只检查instance owner。先按原端口定位左右两端，再查各自原ValueDenotation，**不从denotation反向选择端口**。

- 两端为Reference且均有ObjectIdentity：同exact artifact scope内不同ObjectID给 `drive_binding_identity` Issue；相同ObjectID仅为相容声明。跨artifact没有已支持桥给具体gap，不因FactRef/URI不等拒绝。
- 一端未采集/Unresolved或denotation缺失时，在该binding自身保存 `drive_binding_identity_unresolved` gap及原端口/原denotation，不能只靠顶层false flags掩盖未检查项。已知transport/copy映射仍保留；不因此改原producer或合并ValueOccurrence IDs。
- State formal不应用对象身份比较；核其真实Location/slot/current来源与actualvisit。不把两个StateValueOccurrence ID不同当矛盾，不新造跨activation世界版本或内容相等事实。
- Data身份保留原DataIdentity/VersionRef及双方证据：同一个精确scoped VersionRef可报告DECLARED同logicalversion匹配，仍非runtime/value等价或transform证明。不同VersionRef（包括同lineage不同revision）不能推数值/内容不等，逐binding保留 `data_correspondence_unproved`；不同LogicalValueID/artifact也不作内容不等判断。未知不能删copy输入输出义务；不新增数值/alias求解器，既有exact literal facts只复用，不扩capability。

必要反例：sent source声明ObjectRef A、body SENT formal声明同scope B；body yield A、driver产生formal声明同scope B；capture source A、首次body formal B。这三种图的本地SSA/flow可以各自合法，O必须在实际对应处发现已知矛盾。反例不要求native identity已证，但不得把已声明矛盾悄悄记成一致。

## 6. 接入位置、预算与旧scope

1. records建议 `execution/resumables.py`；model append两表；自然键索引 `ctx.body_drive_executions[drive]`、`ctx.body_activation_origins[activation]`。预建 `by_activation`/`by_segment`/`by_creation`、occurrences_by_visit等只读派生索引，不每个Drive扫全模型。
2. 结构阶段：在canonical coordinates/flow通过后解析scope/entry/outcome/transfer和当前ports；保留CallActivation原校验不变。若要复用动态copy路由，在call_errors之后完成只读route索引，但不能把它伪装为CallActivation。
3. 来源阶段：owner ObjectIdentity检查在content denotation解析后，复用现`ExternalSnapshots`/`resolved_denotations`；每次fresh `_content_context`重新校验外部catalog。不能在构造Index后信任旧mutable外部图。结构部分不依赖URI读取。
4. `resumable_flow.py`共用输入/输出/creation端口resolver供validator与query；不要query自行重走另一套slot匹配。当前program.driver_flow.body_drive_target/body_outcome_uses/body_outcome_types及resumption_flow.first_body_outcome_operations直接复用。
5. 如扩host HB，只由**已匹配本次**Drive→entry第一已捕获op BEFORE、实际bodyoutcome AFTER→本Drive实际EDGE派生；需本次same known thread/scope且原path关联准确。缺第一op/outcome/transfer/thread不猜边。不得用O证明GPU完成/ready，不套activation DAG；只在真实occurrence因果路径上查已知矛盾cycle。
6. Public最小建议：`drive_execution(drive_occurrence, budget=4096)`、`body_activation_origin(activation,budget=4096)`；可另有activation_drives只读列表。返回DECLARED/MISSING及原record+缺口，不叫VERIFIED。无Execution row时仍返回原Drive/input/output静态分母及missing，而非None=没有执行。
7. 查询完整分母从**所有已捕获canonical BodyDrive occurrences**派生，不能从两新表行数反推完整。删row/origin不使未配对Drive消失；budget截断保留未检cursor/原inventory。source replay/record校验/detach成本另列；派生path/copy/identity/端口joins用共享ValidityBudget，不每formal重置。
8. 新execution capability显式版本化（现max7；如采用8需root冻结），旧v1–7字段/tag/bytes不变、不允许新字段或tag偷渡；无新能力不升旧wire。ProgramGraph不因O新增producer/字段；F所需新静态协议能力独立决定。

## 7. 有限验收矩阵（候选验收，不是已执行case）

| O组 | 正例 / 错接或缺口 |
| --- | --- |
| O01 | 一Create、一个持续activation、Start后Suspend再Resume后Return；两Drive用不同driveractivation、同bodyactivation不同segment。 |
| O02 | 第一次Drive线程A、后来Resume线程B合法；本次Drive A配selected segment B已知不符拒。creation历史thread不同不拒。 |
| O03 | 相同staticDrive循环两次必须新occurrence/visits；旧entry/outcome/同segment双claim拒，actualgeneration不靠静态ID排序。 |
| O04 | 同code两Create分别绑定两bodyactivation；双claim同具体creation拒。不同owner仅内容相同不能混配。 |
| O05 | 外部creation=Unresolved、缺Origin row、缺handle/capture Use分别保gap和完整capture端口；不任选多Create。 |
| O06 | entry未知+outcome已知跨run/process/thread仍拒；outcome未知+entry已知错landing/case仍拒；二者未知不补normal。 |
| O07 | Resume错旧Suspend occurrence/静态site/case/activation/targetvisit拒；缺原transfer保gap。 |
| O08 | input slots物理顺序打乱仍按Location/slot；旧currentstate和saved来自另visit拒，C1/local/frame anchors保留。 |
| O09 | 正常与异常bodyoutcome分别落真实selectedsource及精确BodyDriveResult；同type结果换接/伪commonAfter拒。 |
| O10 | bodyoutcome已知但drivertransfer缺采保source outputs和gap；entry→outcome中段断采不伪补path。 |
| O11 | 静态含无穷loop/空frontier、捕获截断、pending未知outcome都无假terminal；O不猜实际发散。 |
| O12 | Creation NORMAL结果按真实索引反排；RAISE origin拒，缺正常edge/handle保gap。 |
| O13 | sameObjectRef+不同Reference ports声明相容；sameartifact不同ObjectID矛盾；跨artifact无桥/URIalias分别未知/同scope。 |
| O14 | 真实dynamic CFG/call/saved copy连Create→Drive，错Create来源拒；未知copy不能当无alias。 |
| O15 | 无body入口的Created.throw/Created.close/delegate-only/rejection无O row、不造父Attach；F原路径分母仍存在。 |
| O16 | 删除新关联仍保allcapturedDrive分母；预算1保cursor；旧wire严格、新view detached、坏FK变Issue非crash。 |

这些O组映射原F02/X27并与F03–F24/X25–X28交叉，不额外累计成新的全家族分母，也不把手工IR称为native捕获。

## 8. 必须联合冻结的少量决定

- **已收敛：** 两自然键records、多drive持续activation、current segment核线程、Creation NORMAL单activation、跨artifact未知、无新actual/state/producer或generationcounter；no-body/delegate走F。
- **待root精确冻结：** 新表/模块/公开query名字与wire版本；是否在P3同时接入conditional host HB（若暂不接，必须公开gap，不能靠静态跨call order冒通过）；外部capture读取协议不在最小O自动解析，保持recipe/缺口不能写fully joined。
- **P1独立复审补足与root决策：** 首稿SHA `ff8ad19bcf02044ac4e3b8265a3eaa8081bae12d06b80f1d0873b847c20adf24` 的owner兼容条款未充分明确所有binding分母；已补§5.1。中间稿SHA `fbad0a15f7cfb7d23877f38d3b47beaab32d43689fd903e19042ec06250a505a` 保留Data判据待定；root现冻结“相同scoped VersionRef为DECLARED匹配、不同者不推值不等而保逐binding缺口”，已写入§5.1。不得把逻辑来源差异等同内容差异，也不把所有Data一律标unknown。
- 所有来源/native/frame-interposition/实际实例互斥条件继续UNKNOWN。以上结构规则在固定native合同下拒错，不把FactRef存在或手工匹配升级为runtime/value identity证明。

### 8.1 原端口蓝图的有限只读核对

root另行运行并保存 `port-blueprint-attempt001.json`，其scope明确为既有IR与Proposed FK，status=`DESIGN_PORTS_CONNECTED`，不是新O validator/identity/runtime采集验收。本审查仅阅读该JSON及 `port_blueprint.py`，未执行脚本：三个activation中两driver分别Start/Resume，同一body有两个真实segment；Start的state来自原Drive Uses，Resume保存的x/frame来自确切旧Suspend Uses，本次sent和当前states来自第二Drive；每次output按实际selectedsource原Use定位各driver landingformal。

蓝图保留未解InstanceCaptureInput，current/source ValueOccurrence IDs没有合并，source/runtime/transform为false；这与本文最小接口前置一致。蓝图不含Origin/Create来源闭合、known denotation对照、逐次换线程、错误端点/缺边和预算矩阵，不能把这次既有core合法性当O01–O16通过。本段仅接纳已有端口可连接的有限证据；其source603未变/旧core校验结果以root原JSON为准。

### 8.2 root最终模块/API/wire及conditional host HB决定的有限补审

root现冻结实施命名：records=`execution/resumables.py`，resolver=`resumable_flow.py`，validator=`resumable_validation.py`，query=`resumable_query.py`；公共面为 `ExecutionIndex.drive_execution(drive_occurrence, *, budget=4096)` / `body_activation_origin(activation, *, budget=4096)`；Execution新能力v8，v1–7字段/tag/bytes守恒。P3同时接入conditional host HB。此段收敛§8先前待定命名/版本/HB，不声称这些产品已经实施。

**有限结论：上述两类桥独立取足自身端点条件，规则自洽，没有新的设计阻断。**

1. entry桥是 `Drive BEFORE → entry第一已捕获operation BEFORE`。要求其原entry visit/target、当前selected segment、run/process和本次known same thread准确，第一op确为该entry block的首操作发生；不是“任取entry后第一个采到的中段op”。outcome未知不删除这条已足条件的entry桥，支持仍附原O row及相关未解条件。第一op/entry未知则无entry桥，不能补造。
2. completion桥是 `实际body outcome AFTER → Drive真实taken EDGE(index)`。要求实际outcome属准确selected segment、原source在该Drive目标first frontier、真实Drive Transfer选中同source、两端本次known same thread及scope相符。entry或中段path未捕获时，这条桥仍可作为 **DECLARED conditional completion关系** 保留，但必须附 `drive_entry_unobserved` / `drive_path_unobserved` 等原缺口，不能显示fullpath/入口已观察。它只陈述这个已声明outcome与已记录Drive完成边的条件顺序，不反推完整body执行。
3. 任一已知entry/target/path/segment/source/thread矛盾仍先产生Issue，不因另一个端点Unresolved降成gap；该非法关联不派桥。已捕获的相反路径/更早outcome也不应靠“path缺采”掩盖。完全无captured path与已知captured path矛盾必须分别处理。
4. 两桥仅约束真实host控制顺序；终点明确是Drive的实际EDGE，不给BODY_DRIVE/INVOKE生成common AFTER state，不证明GPU完成、work quiescence、visibility、对象identity或source/native适用。
5. 联合旧CALL桥、O桥、本地actualpath检查的是**真实occurrence点**的因果cycle。不得在RegionActivation节点上强制DAG；同一持续activation多次驱动/逐次换线程合法。发生层出现已知有向环则拒，单纯缺路径/不同capture component不给反向边，不以absence推先后。
6. 可实现的有限算法：一次建所有桥端点（含phase/实际edge index）的集合；按原static block operation位置和同visit phase顺序排序，仅连接相邻端点；再按已捕获ControlTransfer的visit链连接相邻端点/链边界。加入现CALL/O bridge edges后用Kahn或同等线性拓扑查环，支持原桥来源回查。不同run/process组件不混合，unknownthread不凭空派跨调用桥。保留实际temporal transfer的因果关系，但不把它说成同一物理线程执行。
7. 上述压缩只压**已有精确可达的local链**，不能跨断采、丢actual successor条件或用bbox式“时间覆盖”补边；同visit phase排序不应用于不同visit/static循环iteration。构图索引O(N+E)，端点局部排序最多O(N log N)；不得对每Drive扫所有操作或全pair O(N²)比较。原端口/路径缺口照常保留，拓扑成功只意味着所声明因果边未发现环。

本次只更新授权ignored文档，无产品/docs/tests编辑，无Python/compile/测试或重跑蓝图。前稿SHA `a65600134d525e82c9ab3f53ccf5dadc741834fdd2f7c4025674a1a8c4a758e8` 保留为本补审之前的证据；最终hash另行回报root。

## 9. 本次审读源指纹

b026b709ffb8c5d6c42a95781175f675225dea4c04299d2bbe763e5e2c11b49f  docs/M1_PROTOCOL_FAMILY_PLAN.md
b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09  scar/ir/execution/coordinates.py
a6a4287df931d21221be181023df0233f0b7b8cfbe0fdb69798fc9238ea2c0b8  scar/ir/execution/common.py
14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126  scar/ir/execution/model.py
e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc  scar/ir/execution/flow.py
a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f  scar/ir/execution/calls.py
9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2  scar/ir/execution/call_validation.py
9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42  scar/ir/execution/call_query.py
ae13abeb29d54800a20bd15096a1d9b97a9fb8483e9235102c92035851a62372  scar/ir/execution/query.py
5350936fe93eac37edbfc26a2c9748debde727a488b03c02366556ea53b0352e  scar/ir/execution/validation.py
1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e  scar/ir/execution/content.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f  scar/ir/execution/content_validation.py
a3dacaf57ec45fc1e57d3139a82675c5af6a1b3d19409cdec3b990edc2fabc02  scar/ir/execution/host_order.py
90b6499f128fc1e716549c34de5ff42546d9d7af8554659499913004e5359be3  scar/ir/execution/codec.py
d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd  scar/ir/program/drivers.py
1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa  scar/ir/program/driver_flow.py
4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3  scar/ir/program/driver_validation.py
ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac  scar/ir/program/resumption.py
c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc  scar/ir/program/resumption_flow.py
189a66e66e81eead682adeeaf316ce14af023f9b6c4a453e123f67adcfc2c89d  scar/ir/program/queries.py

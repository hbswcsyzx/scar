# P1 联合协议字段独立复审

基线由root指定：`f9a568182e1672541261020bb9f919609179bb05`。
**初始OPEN，非P0重复审计，非设计/产品PASS。** 只读；不运行Python/probe/测试，不改主docs/产品/fixtures。
本文件记录初始具体约束/问题与后续关闭依据，后续追加不覆盖原推断。

## 1. 起始阅读与适用范围

已复用P0五待决、F01–F24/X25–X28完整分母、root5IR/6原观察与首exit1，以及当前core原端口事实。
第一次读取时A `f-static.md`、B `o-execution.md`尚未落盘；不把未读候选说成已审。
主联合合同尚未出；下列先行约束已消息root/A/B，不能据此宣布字段已冻结。

```text
da0b30175af7387c4794957e4f52be2a91298103a4921d98453450ff562a333f docs/M1_PROTOCOL_FAMILY_AUDIT.md
b026b709ffb8c5d6c42a95781175f675225dea4c04299d2bbe763e5e2c11b49f docs/M1_PROTOCOL_FAMILY_PLAN.md
fb9377699540576fcf292fc8fa078476d2b17b8ae53220d20547e23be9c85497 P0 design/independent-scope.md
a252e2b377fcbd227f1a188278f52dee9667b41b5a3d88c2e7d287768b0ebc0d P0 created_throw_witness.json
```

## 2. 先行约束与有限最小反例

| ID | 具体风险/反例 | 必须冻结的有限规则 |
| --- | --- | --- |
| I1 | 相同enum/FactRef给两个payload不同来源的操作，都自称SEND delivery正确 | 语义锚是闭合版本rule+准确原operation/owned输入/原结果或selectededge；same type/字符串/FactRef不构成copy或语义证明。 |
| I2 | 删除一个规范化/adapter binding后checker只枚举剩余rows，缺项空成功 | 全clause分母从启用scope/profile固定派生；bindings仅指原site，不携带可删义务清单。未映射保持具体MISSING，不能降成generic而假完整。 |
| I3 | loop一次迭代满足source，另一次把owner/request交换；把origin集合union后配对 | 每条原edge先同时改名并核角色相关性，再must合流；静态clause/site只存一次，不枚举每路径或把静态ID当动态历史许可。 |
| I4 | outer throw观察closed，于是任何名为normalizer的RAISE都授F | **下节纠正**：F只接准确source-relative terminal契约，内层factory/normalize RAISE本身不决定终结。 |
| I5 | async R/S/B/E在同world上各有合法类型，S与latent反选后仍进入body | 固定R/S沿原copy；B/E由真实当前association/选择/guard绑定；不同ownedUse保留；不能强制独立AssociationRead或仅按同RAW类型猜。 |
| I6 | delegate直接回item，填一个父BodyDrive以满足O表 | delegate-only/no-user-entry只F的host/helper/adapter原发生；O只真实Drive。两者不可宽union共用不存在的entry/outcome。 |
| I7 | exception factory或host adapter可能callback/raise，却被声明为纯pack、原state不动 | 真实INVOKE N/R与partial后态保留；构造结果语义只绑定准确原produced端口。pure pack只封装已求值引用，不执行normalize/lookup/用户构造。 |
| I8 | 两Create同body，O任选其一填capture；或合法copy后的不同ValueOcc ID被误拒 | origin只绑真实成功Create的NORMAL handle及原captures；沿原copy/已声明scoped denotation查identity。已知相反来源/identity矛盾拒；未知alias/外部creation为具体gap，不能按同body任选或按ID不同判不等。 |
| I9 | entry=Unresolved时跳过已知outcome/thread/source核对 | 独立核每个已知端点；部分捕获不吞另一端已知矛盾。不能补NORMAL、entry或结束事实。 |
| I10 | body跨多drive换线程，但套同步CallActivation所有历史segments同thread；或本次drive与选中segment knownthread不同却不拒 | 只核本次同步drive/selected segment/thread；creation线程与未来drive不强制同，持续activation可多drive。真实缺thread保持gap。 |

### I4 初始过强简称的撤回

我先行消息使用了“normalizer RAISE且closed”的过强简称；root立即指出六原观察只属于**整个throw**，
不能定位内层normalization/factory的RAISE是否直接对外。内层异常可被catch、封为待注入packet，并由normalize Region NORMAL退出。
该提醒成立，已向root/A明确撤回，不把它当作者设计必须满足的错误形状。

正确决定是先固定契约粒度与真实source路线：前置拒绝、被选用于初入注入的值/packet或失败、最后的no-user-entry terminal，
各自引用真正原边与当前后态；F只从经合同解释的最后terminal source建立。任意helper RAISE仍可只是partial state。
不要求为凑这个阶段表添加原程序没有的异常，不按normalize阶段名称统一决定Closed。

本报告到此仍OPEN；等待A/B准确草案及root联合合同再对I1–I10逐项判断。

## 3. O首稿实际复审（ff8ad19b，未冻结联合合同）

已读`design/o-execution.md`，SHA
`ff8ad19bcf02044ac4e3b8265a3eaa8081bae12d06b80f1d0873b847c20adf24`。
两自然键BodyDriveExecution/BodyActivationOrigin、无派生instance/segment副本、已知Create反向唯一、
entry/outcome分别检查、selected-segment线程、多drive/first-outcome/partialcapture等可实施，未见需增加另一生命周期实体的理由。
它明确只O真实Drive、creation=Unresolved不合并、输入/输出复用原端口、fresh denotation重查和共享预算。
I6/I8/I9/I10的大部分约束已有准确落点；尚未读root主合同，不预授通过。

### S1：跨区域input/output也须三值检查，不仅owner

O §4.2明确owner三值检查，§4.3/§5主要描述跨区域端口映射。
需要显式把同样规则用于capture、Resume delivered Reference和BodyDriveResult两端，否则实现者可能只列对应而不拒已知冲突。
最小例：本次SENT source的已声明ObjectRef为A，body landing formal为同artifact的B；
或body实际export为A、driver projection formal为B。两个本地SSA/flow可各自正确，桥接点仍有已知矛盾。
建议复用已声明的同scope ObjectIdentity/可用原copy路线，known contradiction为Issue，未知逐binding gap；
不同ValueOccurrence ID本身不代表不等，不能强求跨区域formal与source ID相同。
StateVersion跨区域仍由原端口/当前producer检查与明确未证条件承载，不新造state identity或世界版本图。

此为候选字段/validator合同的具体歧义，不是运行复现或当前产品bug；已消息B/root待修文案。

### S1候选关闭及O Data细则（待联合合同照录）

已核O更新SHA `fbad0a15f7cfb7d23877f38d3b47beaab32d43689fd903e19042ec06250a505a` §5.1：
capture/saved/delivered/output/forward均在先定位原port后查已声明Reference identity；same exact scope不同ObjectID Issue，
跨artifact/缺denotation/未采集逐binding gap，不只给顶层falseflags。State保持原Location/current/visit端口规则。
因此S1在O候选文案层关闭，不代表新validator/测试已实现。

root进一步明确Data细则：同exact scoped VersionRef可标DECLARED同logicalversion匹配，非runtime或transform证明；
不同VersionRef（含同lineage不同revision）不能推出内容不等，逐binding保`data_correspondence_unproved`，
原copy义务不消失。不加新literal/值等价求解器，不把不同来源标签当数值不同。待root主合同和B最终hash核对应文字。

## 4. root既有端口蓝图的有限核对

只读`port_blueprint.py`及`port-blueprint-attempt001.json`，不执行脚本。
原JSON为`DESIGN_PORTS_CONNECTED`，两个不同driver Region中的Start/Resume Drive发生指同一body activation的两个segments。
每个input/output沿现ProgramIndex原drive bindings和现ctx的UseOccurrence/ValueOccurrence/transfer取端口；
saved来自准确Suspend，state来自各次Drive；Start的外部InstanceCaptureInput明确为UNRESOLVED。
原ExecutionIndex报告issues为空，仍有evidence_missing/source_runtime_unverified，产品603源指纹未变。

这支持两自然键关系可用现FK端点构造的设计可行性；新records/validator未出现，两个owner身份、capture内容、
F协议adapter、实际运行及O对应并未因此验证。脚本使用已有generic D1 graph，不能将它的bodyReturn→driverReturn认作family合同。
本审查没有把它算作pytest/native/产品PASS，也不重跑序列化产物。

```text
9e2722fb065bf51fc12f4b7bae485be18f63a6acf168f52732e48cf2c9736cee port_blueprint.py
fe14c92fe03592ce81786d5d8a4c26acb84eea3d1447c5582d5083defc6ed9ba port-blueprint-attempt001.json
a0fb1409017d9ef1f82aca0e0227b24dd90c28d058cecb9d3e5f3b163ec39697 port-blueprint-attempt001.program.json
217689902a84748d813962e7b685790bf890f4fa40abb358b49fe51cf278587b port-blueprint-attempt001.execution.json
```

主联合合同/F精确方案尚未读，整体继续OPEN。

## 5. F精确草案的实际阻断（02bda999，尚待修订）

已读F `design/f-static.md` 当前SHA
`02bda9999214771ad3c2c4f46aa98ff594fb134e8e21b5560cc416533585ba32`。
下列是字段/解释合同的源审问题，不是已运行的错误graph，也不是当前产品缺陷。

| ID | 具体位置/最小反例 | 最小修正 |
| --- | --- | --- |
| F-S1 | F:91 `BodyDriveResultPort(drive,index)`未选择source。同一Drive有两个首出口，二者index=0的payload不同。 | 端口须含准确`DriveOutcomeRef(drive,source)`+index，或准确Drive successor edge+index；再派生对应body Use/formal。 |
| F-S2 | F:92使用`execution.coordinates.AccessRef`/`InvokeBoundaryStateEffect`，它们引用动态OperationOccurrenceID/UseRef，不是静态OperationID。 | 复用`program.state_addresses.ExistingAccess(operation,index)`及`InvokeStateOperand(operation,state_use)`；INVOKE后态由准确原edge/CompletionResult派生，不复制after。 |
| F-S3 | F:73的Unresolved若直接使用execution.common版本，会要求EvidencePoint/run；纯ProgramGraph缺口不应被迫造运行。 | 使用静态missing-binding reason变体或等价可解释缺口；FactSource的MissingEvidence(reason)本身可复用，不能混同动态Unresolved。 |
| F-S4 | F:60裸OperationDefinitionID没有本ProgramGraph注册表/准确artifact；F:59还要求ResumableBody，普通wrapper/helper不一定属于body。 | 主体收敛到原DriverSubject或准确OperationSiteSubject(region,operation)；编译/代码来源只引用原scoped provenance，不造新definition registry。 |
| F-S5 | F:68–80只有可写relation和manifest描述，尚无有限operation-contract/关系解释。填另一个同型packet Q、列全row、引用可达edge，并不证明Q来自选中规范化/委托结果。 | clause固定语义rule和命名角色；记录绑定该原operation的owned输入、该operation自己的准确N/R结果与现state site。下游输入按实际COPY/准确构造关系核来源，row不能选择更弱relation逃避。 |

F-S5的有限可实施核为：

1. Request processing/协议lookup-call/host adapter/no-entry terminal按原边界分别有封闭contract变体；
   字段引用原raw/receiver/ordered arguments、准确selected result/edge及原state site，不携带新payload或world。
2. COPY沿真实CFG actual→formal同时改名后must合流；不按constructor/port来源集合相等，不枚举loop每条路径。
3. PACKET只复用现`ExceptionPacketDefinition`的exception/tb Uses；若合同结果是exception/tb，后续pack必须来自这些准确结果。
   若原opaque helper本就返回packet，引用它自己的准确packet结果；不能用另一操作的同型Q替代。
4. factory、规范化、PEP479转换、item/return adapter可产生新结果，不强求结果与输入是同Value；
   其语义为版本化operation-contract的**条件声明**，不是原copy，且原callback/INVOKE N/R和partial state仍在。
5. 一个真实opaque边界可由profile承接多个固定clause；不能为了表的阶段强拆不存在的operation或捏造异常边。
   单NormalResultPort不覆盖异常路线；统一准确ControlEdgeReference+CompletionResult可覆盖真实N/R。

这里没有要求M1验证任意native源码、自动枚举全部source sites或实现完整compiler。
固定F01–X28及其适用clause分母是本门接口义务；真实程序site inventory未知应明确UNRESOLVED。
原helper的输入/结果接线可机械核对，helper语义/版本适用未证仍保条件；二者不能用同一个MATCHED或FactRef混为证明。
上述问题与最小决定已发root/A；等待修订F和主联合合同，**本节OPEN**。

## 6. O最终候选与HB决定的有限收口

已核O最终SHA `a65600134d525e82c9ab3f53ccf5dadc741834fdd2f7c4025674a1a8c4a758e8` §5.1/§8.1：
S1和root Data细则已准确照录；两自然键`BodyDriveExecution(drive,activation,entry,outcome,source)`、
`BodyActivationOrigin(activation,creation,source)`没有复制instance/segment/currentstate。
O候选在所审字段范围可实施；不是O产品/测试PASS，更不替代F语义合同。

root另决定records/resolver/validator/query分别为resumables.py/resumable_flow.py/resumable_validation.py/resumable_query.py，
公开drive_execution/body_activation_origin，execution新capability8，旧1–7无能力时原bytes。
这些是待主合同照录的机械命名决定，不声称当前max7产品已实现。

HB采用逐端点条件语义，已与root达成：

- entry桥仅需准确entry/target/本次segment/同known thread/已捕获首canonical op，不能因outcome缺采丢已知entry。
- completion桥需准确bodyoutcome+实际Drive transfer/static source+本次same-known-thread；entry/path缺采时可保留
  conditional completion-pair桥与具体drive_entry/path_unobserved，不能伪补完整运行路线。
- 任一已知矛盾禁止生桥；缺端点/transfer/首op/thread不猜NORMAL或WorkEnd。body挂起/host返回不授GPU完成或ready。
- 必须在原捕获local CFG和派生桥组成的**occurrence因果邻接**拒绝真实cycle；持续activation多次Drive不能套activation DAG。
  预索引有限端点/邻接、toposort/共享预算，不能每Drive扫全模型或全端点两两比较。

对照只读原`host_order.py:83–101`已分别派生Call entry/completion端点；SHA
`a3dacaf57ec45fc1e57d3139a82675c5af6a1b3d19409cdec3b990edc2fabc02`。
这里是拟议O扩展与已有Call部分端点语义的兼容设计，不是修改/运行host_order或证明native同步。

最终联合合同未读，F-S1–S5未关闭，P1整体仍OPEN。没有执行任何脚本/测试或更改产品。

## 7. F修订与联合O正文的后续复核（仍P1_REVIEWING）

F修订SHA `b812e938515870df077b92c6f031652941b1d4a09923821d499ebb9ae2da6659`，
保留02bda初稿并由Revision1显式撤回旧schema。Revision1 A/B核对静态state/缺口/subject及source-qualified
Drive结果，C撤自由relation而绑定原operation contract，E把NoEntry transition与真实terminal分开。
F-S1–S4在修订候选文字层关闭；F-S5方向已改，尚须实际有限profile/clause/rule表，不能仅凭“closed”一词关闭。

另两处具体形状已发A/root，等待最小修订：

- F:235的RequestProcessing不能把normalizer的owned operand Uses等同RawRequestDefinition构造op拥有的Uses。
  normalizer只接RAW、本地pack不存在的外部RAW均是原接口允许的形状。只有真实展开args时才列该op独立owned Uses，
  其与原raw ordinal按准确投影/封闭contract连接；不能强迫新增实际参数或共享一个UseID。
- F:238的OutcomeAdapter仍只接DriveOutcomeRef；delegate-only item/方法失败和无入口helper结果的host adapter
  没有父Drive。source须由rule固定为准确Drive source+result或前一helper自己的准确普通/N/R结果端口；不造Drive。
  NoEntry嵌套contract也不再重复outer的scope/clause/slot/source/operation；真正transition可用outer.operation。

已读root `docs/M1_PROTOCOL_CONTRACT.md` SHA
`9d706792affa6f5915febea55314fde2d6da0382e241d81a23c3c3cfab18eb93` §§1–5。
本版只有O/HB正文；按root指定，本节不因F尚未整合重复给泛缺项。
O两自然键/v8/每端点独立检查/换线程/原ports及Data细则/conditional HB/occurrence cycle均准确承接既有决定。
建议把B已有的两条不变量直接照录，已消息root：

1. owner对照准确列为本次Drive.instance与Origin的Create NORMAL handle、同activation其他Drive owner。
   known原copy来自另一Create或same-scoped ObjectIdentity冲突为Issue；未知逐pair gap。
2. 同selectedsegment两个已捕获body首outcome（排除同步helper子activation出口）为矛盾；entry未知也检查，
   不能仅查row选中outcome而忽略另一个。B O:80有明确要求。

这是合同源审而非运行反例；不存在本审查新脚本/新测试结果。联合F未定稿，整体P1继续OPEN。

## 8. 有限表最终复审及实际关闭依据

已完整核A F-final附录F.1–F.8，SHA
`986d2e6276ece7fec5c83d502a27a634d1121dfd3501e68d58185159eae2cbd7`。
中间阅读快照`75d45abdb6ce7e47105d63c6790d818146f559c8d74b54650c784adc4ea5e3b5`
保留为当时发现的依据；本节不是说该中间稿当时通过。

| 后续实际问题 | 最终依据与关闭范围 |
| --- | --- |
| pack Q用自己的exception Use作source，自证“来自normalizer” | F.7固定每种packet规则的前置exception/tb角色，目标自己输入/result不能当来源；缺真正来源保gap。 |
| ContractResult引用自身/非required行/同op另一个同型结果 | F.7准确`scope,clause,operation,slot,result_port`，必须等required producer row自身结果；self/无源环不授事实。 |
| 同clause多静态分支缩成一条，或INVOKE finished污染另一边 | F.4/F.7按原successor index派生各slot；NoEntry slot等selected edge；lifecycle/session仅该边原post贡献。 |
| CreatedThrow“one applicable”由作者任选一条 | F.7撤该解释，source inventory+原CFG决定全部适用分支，缺一MISSING；未知inventory保global gap。 |
| raw-only/external RAW被迫提供本地pack及同UseID operands | F.4/7允许原raw-only，不造expanded args；存在额外owned Uses才按ordinal/must-forward核，缺投影gap。 |
| delegate-only被迫借父Drive，async被迫独立Create/AssociationRead | F.4/7允许准确前置helper结果；async检查R/S/B/E当前角色，可来自真实combined helper/gate，local records仅存在时核。 |
| GeneratorCoroutine direct clause命名不一致 | F.7统一DIRECT_HOST_ADAPTER。 |
| 新NoEntry row重复outer身份/transition | F.4/7以outer.operation为真transition，nested无重复key/source/disposition。 |

已读B后续O §8.2补审，当前SHA
`c57915180cb408d68f3319d5255fda1bd811b972501416c1b4b56cc804448f7b`。
前述`a656...`是补审前的真实快照，不静默改写其历史。§8.2准确收敛模块/API/v8、
首canonical op而非任取首采样op、逐端点conditional HB、known contradiction禁桥、
原local链与桥的occurrence查环及有限索引成本；与root决定一致。

## 9. 联合合同终稿审读：PASS_WITH_SCOPE（P1设计范围）

已完整读root `docs/M1_PROTOCOL_CONTRACT.md` SHA
`a448c012e4c4fd8518031ba4d0e88af5c4621aa6f217fc10e919ea1b41e1d501`。
其前一快照`50573ee169a3a499b254d8ee11c30f2ce95947be3d8a80819e6e3c366c635405`
仍有一处确切union抄错：NoEntry.selected_input采用AdapterInputPort，反而允许DriveResult且漏直接helper结果。
已通知root；当前§6.1显式`NoEntryInputPort = ProtocolResultPort | ContractResult`，禁DriveResult，
允许本helper/transition原结果或前置结果。该具体问题在设计文字层关闭。

终稿其余有限关闭依据：

- §2/§6.1以OperationResult/InvokeLiteralResult复用准确原result端口；不调用NORMAL/Data/Ref专用literal_site，
  不放宽旧literal guard；静态state用ExistingAccess/InvokeStateOperand，Drive结果带准确source。
- §6.2固定11 profiles、原clause/rule集合及来源分母；PacketConstruction、adapter均有原角色而非自由relation。
  main正文明确优先纠正F简称：helper返回完整EXCEPTION_PACKET则整体copy，只有真实exception Reference结果才组原packet。
  不混型，不拆造opaque内部operation，也不凭该声明证明native实现。
- §6.3消费者从原raw/选中结果到gate→Drive→准确resume slot；普通YIELD→host item为原exact-copy派生，
  Closed+raw路线用准确RequestProcessing N/R/current Closed来源→host terminal，不造Drive/INITIAL_THROW/F seed。
  此决定填上原F07/F10必需路线，未要求添加不存在的adapter操作。
- §6.3明确NoEntry真正transition/selected edge/terminal/currentstate；普通helper RAISE不等于terminal。
  现lifecycle_flow的op-wide seed不能直接套用，P2须按准确EDGE分别种F/T与body-only rebase；不是现产品已实现。
- §3已照录owner↔Create及同activation各Drive逐pair、全binding三值对应、缺一端仍查另一端、同片段双首outcome拒绝。
  §4逐端点conditional HB和真实occurrence因果cycle，不套activation DAG，不给缺桥/缺路径补NORMAL/WorkEnd。
- §7冻结Program17/Execution8各自能力边界、公共resolver/query与原版本守恒；共享派生预算/有限worklist及cursor，
  preparation/FK/snapshot/detach单列，不声称所有CPU工作被4096封顶。

### 原分母与后续实施门保持不缩

| 原组 | 本合同的明确落点 / 后续必须验收 |
| --- | --- |
| F01–F04 | 四family原create/capture/外部实例、原RAW四kind及有序THROW、admission/启动与拒绝；§3/6，P2/P3，不以创建当执行。 |
| F05–F08 | CreatedThrow多真实路线/内层callback N/R/selected-edge no-entry，Running拒绝、YIELD/SENT、packet/context；§6.2/6.3，P2全state×raw表。 |
| F09–F11 | Return/entered StopIteration adapter、Closed精确无body路线、Created/suspended close和非法yield重试；§6.2/6.3及F-final固定rules，P2。 |
| F12–F15 | coroutine/gen-coroutine direct与await、wrapper/local site、handoff vs最终表达式、reentry/reuse；固定profiles/ports，P4，不把普通generator自动升await资格。 |
| F16–F19 | async request SOURCE/association/current R/S/B/E/delivery、ASYNC_YIELD vs AWAIT/session/body terminal/版本差异；P4，native bits和续体仍分别建模。 |
| F20–F24 | delegate lookup/advance/raw throw/close/item/exhaustion、无父入口路线、Task请求/交付/捕获/最终状态；各局部profile和真实CALL/INVOKE，P4；未解析边界保具体gap。 |
| X25–X26 | 原C1/private/frame/saved-context/current state及多cut/merge；edge-specific终结、session后态、release；P2/P4组合仍需实际新正反例。 |
| X27 | O两自然键、真实输入/首出口/持续activation/逐次线程/identity条件、partial endpoints和causal cycle；P3，不把蓝图当动态native捕获。 |
| X28 | 固定ledger/缺source scope不空成功/共享预算/旧wire/公共query和CLI；P5；仍须113构造/196字段及整体M0–M2验收。 |

**结论：在上述准确合同SHA及引用的F-final/O补审范围，未见剩余实质字段矛盾，可作P1字段与关系设计的PASS_WITH_SCOPE。**
这不是F/O产品或P2–P5通过，不是全家族native语义、source适用、真实实例/捕获、自动建图或变换证明。
没有运行Python/probe/pytest/compile/full/GPU/LeWM，没有更改产品/docs/tests/fixtures，没有新增producer/state。
M0–M2仍OPEN，完成后按用户要求先停讲解；不以保守opaque表示能力替代后续协议验收。

实际核读相关source SHA（用于接口事实，不是本轮测试受测hash）：

```text
5659733ce7138c56cf9070bbc970a4a954860aa121db5faed90447658f674152 scar/ir/program/model.py
6ff4052771e4c92cf248f298131037f9a25a5bda8059e1547da44410d3577b61 scar/ir/program/state_addresses.py
1c0cc6ce2464804dfb29fced4cdf9ba7f4f0ffa65407b62073e0f17fd91436ca scar/ir/program/literal_validation.py
8adaa530a1801949a0706948c9aef2410148782fa95e49da18706ed5c794fae0 scar/ir/program/lifecycle_flow.py
88d2640c7cb23c454f95888ced4130784fd829e8d1d60292a17000278fbe4ef2 scar/ir/program/control.py
a3dacaf57ec45fc1e57d3139a82675c5af6a1b3d19409cdec3b990edc2fabc02 scar/ir/execution/host_order.py
```

本结论绑定P1_REVIEWING字节；若root仅更新冻结状态/进度元数据，另追加最终字节receipt，不覆盖本节历史。

## 10. 最终冻结字节 receipt（停止写入）

已只读核最终联合合同SHA
`2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac`。
相对§9已审`a448...`，root报告的末次调整为header冻结状态及§6.3补充派生拒绝路线；本次实际读取并核对这两处。

- header明确`P1_CONTRACT_FROZEN_IMPLEMENTATION_OPEN`，只冻结字段/原端口/义务，P2–P5待实施，未升级为产品能力。
- §6.3:342–343明确RAW_ADMISSION前置失败与Running重入拒绝也从自身处理结果/当前后态接host terminal，
  不制造BodyDrive或终结seed。与已审Closed无body派生路线一致，保留F04/F06的原分母，无新增状态机或异常边。
- F-final仍为`986d2e6276ece7fec5c83d502a27a634d1121dfd3501e68d58185159eae2cbd7`；
  O补审仍为`c57915180cb408d68f3319d5255fda1bd811b972501416c1b4b56cc804448f7b`。

**PASS_WITH_SCOPE保持，仅P1设计冻结。** 本轮未独立审root所称其余7份进度同步文件，未把同步声明算成新产品或测试证据。
没有新run或产品/docs/tests编辑。完整C2/D3、P2–P5、M0–M2、native/source对应、自动建图和变换权限继续按上文边界。
本receipt之后停止本批所有文件写入，等待后续明确实施/审查授权。

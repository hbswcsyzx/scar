# C2/D3 独立分母审计：已有骨架、协议接线及下一批闭合范围

基线由root指定：`08c4cbfc6b675919ab15e8654567889727f3c466`。
**结论：OPEN_WITH_BOUNDED_PLAN，非设计/产品验收PASS。** 本轮只读文档、源码、已有fixture定义和root已有IR观察；
未执行Python、probe、pytest、编译、full、native workload、LeWM或GPU；未修改产品/docs/tests/fixtures。
作者历史验收数字只按原报告归属，不把未读的测试算本轮已通过。完整M0–M2仍未完成，完成后先停讲解的边界不变。

## 1. 核心判断

**generic core的表示能力足以承载绝大多数家族协议操作；仅有generic图并不足以证明某张图满足家族协议。**
现有四种ResumableKind及flavor兼容检查不是缺失，不能再加一套同义enum来关闭D3。
真正缺的是把版本协议的请求处理、正常化/委托、实际body进入、host适配及request更新义务，
接到原操作/有序Use/实际CFG结果/当前状态，并按完整固定分母检查。仅写PYTHON_RESUMPTION_V1+FactRef不完成该关系。

分两块推进即可：**F：协议的原CFG/端口义务；O：实际Drive与持续body activation/本次segment/outcome的薄关联**。
F/O共享原canonical producer/Uses/state，不另造permit、request历史机或可写world图。
具体source/native implementation是否满足某个抽象协议仍是独立条件；自动恢复/采集是M3/M4，不是本门要求造新编译器。
但“能表达并校验给定声明的连接”是模型阶段责任，不能以自动恢复未做为由省去该接口。

## 2. Observed：当前已经有的实物，不能重复列为待实现

| 当前源码 | 已有的机械关系 | 没有因此得到的结论 |
| --- | --- | --- |
| `program/resumption.py:27–64`、`resumption_validation.py:154–161` | 四body家族、四flavor及家族兼容；SavedRole、SENT/THROWN/DELEGATE输入 | 不验证源码code flags或全部family行为。 |
| `resumption_validation.py:99–137,141–290`、`validation.py:363–427` | Initial/Attach/Detach、private token生产/逃逸、逐边caller精确copy；logical CFG与cut availability；各当前共享域ResumeInput | 不证明真实frame/context切换、body owner/generation排他。 |
| `resumption.saved_actual_use`与binding/C0/C1原接线 | private saved只引用原owned Use，绑定、pending、saved-context经原formal；重新进入/当前cleanup activation规则 | 不是把引用内容或旧world保存成永久值。 |
| `drivers.py`、`driver_validation.py:101–179` | RAW四kind/有序原参数、已绑定Create、async request创建/association的NORMAL原端口 | 没有执行异常正常化、原方法lookup或真实R/B关联证明。 |
| `driver_validation.py:209–365` | fixed receiver/S、ASYNC session精确copy；最终gate N/R全D后态；唯一私有gate-NORMAL→Drive；Start/Resume位置/类型/域 | gate的当前关联/资格是条件合同，不是已执行的native guard。 |
| `driver_flow.py`、`resumption_flow.py`、`queries.py:669–824` | 当前target输入recipe；首Suspend/Return/Raise完整有限frontier；源签名由原Uses派生；不跨Suspend且不公开saved | 不算host outcome adapter；空frontier不证明dead/total。 |
| `lifecycle_validation.py:51–132`、`no_body_validation.py` | opt-in DriverLifecycle；每真实source私有首commit；CreatedCloseTest→真实bool BRANCH→true私有首mark；false替代路径和predicate-only合法 | CreatedClose不是所有无body路径；typed true不证明真实guard成立。 |
| `lifecycle_flow.py`、`session_flow.py`、`lifecycle_analysis.py` | E/F布尔must后求解释T；F多锚共享release；P按原边同时改名/合流，unknown写失效、body-only重基；NORMAL后置与RAISE部分态分开 | 不推实际instance/owner、nativephase；不把HOLD/COMPLETE/ABANDON当完整家族状态表。 |
| `session_release_validation.py:76–114`、C1/C2组合 | 精确后态及窄TerminalFrameRelease/宽INVOKE区别，pending/context不传opaque helper | 不保证free/refs仍held/只释放一次、最终化完成或资源ready。 |
| `execution/flow.py:15–108` | 原Suspend occurrence→准确ResumeIngress/new segment/同activation；禁止一个occurrence两transfer；实际loop用新visit | 尚未连实际BodyDrive occurrence与该body segment及其本次outcome。 |
| `execution/call_validation.py` | 同步CALL/INVOKE与实际child入口/返回原端口关联 | 不能借来代表可多次drive的持续body activation。 |

本报告未重审所有旧算法的正确性；上表确认当前接线与声明边界，不用历史case总数代替新family组合。

### 2.1 历史文案容易误读的具体位置

- `WHOLE_PROGRAM_MODEL.md:295–298`称temporal设计“尚未成为产品capability”；当前C2B已实现，该句是历史规格状态。
- `M1_RESUMPTION_INTERFACES.md` §3.1仍称“拟议Attach”，§4称新release profile待实施；当前Attach/Detach及D2 release已存在。
- `M1_RESUMPTION_BODY_COMPONENT.md:128–130`的“专用driver ingress/outcome尚未接入”是C2B当时范围，D1之后不能当当前事实。
- `M1_DRIVER_INTERFACES.md:3,55–78,153–164`保留未实施/可传递permit候选；其§开头已指第二稿撤回。不得复活permit或通用RequestGate/U-A历史。
- `M1_DRIVER_CONTRACT_V2.md` §4/§6写D2候选未冻；当前冻结依据应看LIFECYCLE_CONTRACT及D2.1–2.4各验收，旧草图的SessionUpdate.source、release.completion字段没有实施。
- `M1_DRIVER_ACCEPTANCE.md:103`和SESSION_RELEASE_ACCEPTANCE的“后续D2/D2.4未做”是各组件交付时边界，不能覆盖较新组合验收。
- 当前总矩阵/WHOLE_PROGRAM_MODEL_PLAN §3正确列C2B/D1/D2.1–2.4已验收而D3开放；应以该顺序判当前scope。

这些是文档时代/优先级问题，不是要求回写已封存原报告，也不是当前产品失败。

## 3. Inferred：协议接线的准确缺口及最小反例

以下未执行新reproducer；前四条另有root既有IR观察支持，余项为可定位的接口/校验范围推断。

1. **body Return不是host正常Return。** `driver_validation.py`完整核first outcome及其原signature，但没有检查outcome之后普通host CFG的家族适配。
   所以generic generator图可把body Return payload直接接driver RETURN；这满足D1，不等于§7.2的next/send StopIteration.value协议。
   相反主动body Raise(StopIteration)不能被适配成自然Return；C0 packet只是exception/traceback引用，不表达这两个原因的等价性。
2. **receiver组合允许不等于Python家族合法。** BODY/ASYNC_REQUEST是结构角色；当前D1可给GENERATOR配ASYNC_REQUEST。
   这在generic层并非旧bug，但完整D3必须校验该protocol实例、latent请求与当前scheduler方法的适用组合，不能宣称“enum都在所以家族齐”。
3. **typed payload正确不等于请求交付正确。** RAW pack只核kind/arity，gate只核实际role及ResumeSlot类型。
   SEND的另一个Reference可能被接入SENT_VALUE而仍类型正确；THROW fallback packet可来自另一构造，或S/latent在普通helper后被反选。
   F应连接本case的原raw操作数、准确normalization产出/失败和最终delivery，不只比较payload类型/constructor集合。
4. **SessionPost是后置声明，不是family选择规则。** 当前P能证明某条SessionUpdate的准确当前后置，却不验证为什么该family/body source应选择它。
   ASYNC_YIELD item可完成一个request而body仍暂停；AWAIT可能保持同request占用。不能随填COMPLETE就认为已符合await-in-progress协议。
5. **Created.throw初入异常是字段冻结前实质阻断。** 控制分册§7.2要求启动位置异常路径、未进入body/finally，以及normalization自身失败的不同影响。
   当前BodyStart禁止dynamic resume inputs，Start entry非state是capture引用；没有本次THROWN_PACKET端口，NoBodyFinish只锚CreatedCloseTest。
   必须冻结正确规范化：是显式初入异常入口/分支，还是typed no-user-entry终结及host adapter；两者都不能伪成Send、伪执行用户body/finally或借CreatedClose的F种子。
   此处不擅自断言CPython内部一定不执行任何解释器指令；root已交语言作者核旧见证/版本源码，未决前不能宣称设计通过。
6. **delegate-only与父body ingress不同。** DELEGATE_REFERENCE和DELEGATE_VALUE/PACKET能携带所需值，但未要求哪个真实delegate调用产生它、是否直接返回item、是否根本没进入父body。
   raw `throw(type,value,tb)`可能直接转交delegate，normalization不能统一前移；lookup/normalization回调可嵌套drive，返回后必须取新state。
7. **await中间yield不是await表达式结果；取消请求不是已交付/已终结。** AWAIT flavor只是typed suspension；缺await iterator获取/校验、零挂起完成、scheduler输入→iterator→返回值的协议连接。
   CANCEL及Task本身不是RawRequestKind新成员的必然理由：实际scheduler取消请求、实际throw packet、被捕获/清理再次await以及Task最终状态须由真实操作/原CFG区分。
8. **缺实际Drive→body桥。** 一个driver的准确Drive source边和一个body的准确ResumeIngress可各自合法，但当前没有record定位这两个发生是同一次body执行。
   同static Region/同source FactRef/同payload不能选择child；同步CallActivation一caller一activation、初入及全segments thread规则不能照搬。

root已有观察：`current_core_probe.json`记录4张旧D1合法IR（start/value/packet/BODY与ASYNC_REQUEST）及1项wrong-flavor拒绝；
产品603源指纹未变，报告明确family_adapter_validated=False。尤其value例body RETURN→driver RETURN、ASYNC_REQUEST+GENERATOR有空structural_issues。
这不是native Python运行/协议测试PASS，也不是原D1合同的bug；它精确说明当前验收停在generic结构层。

## 4. Proposed：最小可实施F，不造新的状态机或自证claim表

### 4.1 固定义务优先，绑定只指原端口

1. 使用现有ResumableKind、RawRequestKind、receiver kind及DriverInterface.rule；**不再造一套家族/phase状态enum**，不赋予ProviderFactRef解释执行能力。
2. 下一门先冻结有限版本profile的**不可由调用者删减的协议clause清单**（见§6）。给定协议scope后由checker派生分母；
   删除一个adapter/normalization声明只能使对应clause MISSING/PARTIAL，不能使分母消失或让generic D1报告冒全family。
   旧v11等generic声明继续合法，只保持原scope；新增完整协议层显式opt-in，迁移不能悄悄重解释旧图。
3. 先尽量从原CFG、RawRequestDefinition、DriverInterface、DriveOutcomeRef、SessionUpdate、NoBodyFinish及原端口派生。
   **确实缺少语义锚时才增加局部协议契约附件**：它必须定位真实Operation/准确Use/原结果端口或真实edge；
   不能是`case=SUCCESS`、`phase=CLOSED`、`family_valid=True`之类可写结论，也不能再存actual/formals/before/after副本。
4. 本地契约至少能表达下表关系。它们是抽象操作合同的精确绑定；其native实现适用性仍有条件，不因记录存在就提升runtime authority。

| 必需关系 | 最小原引用和检查 | 不可偷换 |
| --- | --- | --- |
| raw选择/解包→normalization | 原RAW Use、原ordered raw Reference Uses（或准确解包产生的原端口）；真实lookup/normalize操作；NORMAL原result→packet pack，RAISE实际后态 | omitted≠None；不能把多个THROW参数压一packet或强制所有分支先normalization。 |
| 分支资格→进入/无进入 | 原predicate bool/BRANCH及所选ControlEdgeReference；实际gate/Drive或无body路径；固定B/S/R/E精确copy | false合法走替代路径；不能为非Created close造RAISE；未知guard不冒已执行。 |
| delegate/await协议步 | 原delegate Ref及原call/invoke有序Uses、NORMAL/RAISE produced port、保存/恢复源与parent分支 | 真实method lookup/调用可回调，不能变纯intrinsic；父body未进则无假Attach/outcome。 |
| body source→host adapter | 原DriveOutcomeRef及本边payload/state Use；真实adapter操作的结果/异常packet/出口原Use；固定profile的精确结果关系 | Return->StopIteration.value与body Raise->RuntimeError、yield/item与request completion不得混接。 |
| 原异常语义结果 | `ExceptionPacketDefinition`只保exception+tb；必要构造/匹配/转换契约指真实factory/handler原结果与cause/value输入 | 不能凭异常名称字符串、Reference类型或相同packet字段证明类型/链。可能callback/RAISE的构造仍普通INVOKE。 |
| family后置及finalization | 原session更新点/实际N或after、原commit/no-body锚及当前状态；窄release或宽helper原边 | typed post只描述准确后置；选择依据须有本profile对应source。Suspend/host异常不种F；release不推出free或ready。 |

建议API层只有一处派生入口，例如`protocol_obligations(graph, driver_region)`返回完整固定clause ledger、
每clause原site/Use/CFG/result/state连接与具体missing/contradiction；它不是新的可修改图或人工标pure清单。
validator校机械连接/完整范围，query保原端口与条件；完整source重放/运行实际身份留外部证据。
局部contract确需新records时，应沿现CreatedCloseTest/BodyOutcomeCommit模式严格冻结原site与shape；
不能把本报告中的关系表直接当某一实现分解顺序——normalize/delegate/acquire的真实版本路径须先明确。

### 4.2 F检查是有限CFG关系，不要求任意路径定理证明

- 原core先验证类型/ownership/状态SSA。F再按已启用profile派生必需case，检查其真实分支/调用/结果连接。
- 每条普通edge用原owned actual→formal**同时改名后**合流；复用driver_role_copies/C1 must规则，禁止origin-set交叉配对。
- Host adapter必须锚当前source/case及当前owner/request/delivery；不能从远期body source、任意NORMAL helper或静态callee猜。
- 所有可raise阶段均保原INVOKE N/R当前后态；异常构造/lookup等回调以后重新gate，不让旧资格跨callback存活。
- callback-free只用于明确的抽象小intrinsic（现context、metadata publication、协议值pack及冻结predicate）；真实用户协议调用不放进去。
- 只检查结构可达/实际端口，不要求求解一般条件可满足性。保守case可有条件；编译非法或无适用协议的分支必须显式缺口/拒绝，不能生假运行body。

## 5. Proposed：O的薄发生关联及不能借用的约束

最少关系可冻结为一条原发生绑定，形状供下一轮字段审查，**不是已实施API**：

```text
DriveActivationLink(
  drive: exact OperationOccurrenceID,
  activation: exact RegionActivationID,
  ingress: exact ExecutionSegmentID | Unresolved,
  outcome: exact OperationOccurrenceID | Unresolved,
  source: existing FactSource)
```

id可按现registry约定另定；不新增frame/generation计数器、state、保存列表或规范producer。
“generation”应直接锚原Suspend occurrence及被选case；多次合法执行同静态site用新occurrence，不能拿静态整数代替。

- drive须是原BodyDrive occurrence；activation.region必须匹配静态target body、同process/run；entry/resume segment属于该activation。
- Start接该activation真实InitialEntry/原entry visit；Resume接静态目标对应的真实Suspend occurrence→ResumeIngress/transfer。
  这里复用准确`drive_input_bindings`、原SavedInput/ResumeInput、ValueOccurrence/UseOccurrence；Start capture来源缺时明确gap，不选唯一Create。
- body actual初入/恢复状态须连本次gate/driver真实produced后态，body真实outcome的public Uses连本次Drive source projections；
  不能按同Location、相同类型或capture时旧world配对；所有saved仍私有。
- outcome须同activation并由本次入口沿原普通CFG到达的第一个Suspend/Return/Raise；不越下一Suspend借远期结果。
  pending/partial/diverging capture用Unresolved及精确gap，不填NONE、RETURN或虚假发散result。
- 一持续activation可有多个按序drive；同一次原Suspend occurrence最多被一次真实temporal transfer消费，复用现fork/visit检查。
  同一driver实际发生不能任意选两个ingress/outcome；缺捕获不补边。no-body/delegate-only没有Drive occurrence就不造body link，absence也不证明没有发生。
- 每次同步body进入可核该caller与所选segment的已知thread关系；不能强制body**所有历史**segments同thread。
  外部/线程未明保gap，不从FactRef相等推时间、owner或身份。
- 动态driver回调嵌套是新的实际调用/drive发生；不能强制“一外部host方法只准一次body执行”。

这只验证给定声明/发生连接；把真实实例、source、当前关联、所有generation和线程恢复出来是M3/M4。
因此O应属于M1模型接口分母，但不要求在本门实现完整collector/调度器或native parser。

## 6. 完整原范围的有限验收分母

每行须绑定具体新图/原端口正反例、expected error/gap及scope；不是24/28个case总数承诺。
同步generator必须保留§7.2的Created/Running/Suspended/Closed×Next-Send/Throw/Close全表；
其它family按自己的request/body组合，不把一个枚举状态表硬套到async request/Task或native flags。

| ID | 必须正向连接 | 必拒或必须保留的不同路径 |
| --- | --- | --- |
| F01 | 四kind创建/分类、已绑定参数/完整环境capture；创建不执行body | 不可达yield仍参与分类、嵌套code不串、编译非法不生正常body；源码恢复未证。 |
| F02 | 多Create/外部实例共享接口，当前world启动 | 不选唯一静态Create、不保存创建时共享world、裸Ref/CodeID不授实例身份。 |
| F03 | NEXT/SEND/THROW1–3/CLOSE原有序参数、omitted/None、真实normalize和失败 | packet提前化、错raw来源、忽略warning/lookup/callback/N-R部分态。 |
| F04 | Created Next/Send(None)首次进入；非None失败而未进入 | 不运行body/finally、不提前种F、不把拒绝变终结；后续合法请求仍可进行。 |
| F05 | Created.throw初入异常与normalization失败分离 | **字段未决阻断**；异常不能变发送值或走普通body entry后伪运行未进入handler/finally。 |
| F06 | Running重入拒绝，包含Next/Send/Throw/Close；callback嵌套真实发生 | 不产生第二个同时活动continuation；不把所有nested driver都一刀禁止。 |
| F07 | Generator Suspend(YIELD)→本次next/send item；准确发送引用→yield expression | 本次发送值不是旧保存值、导出不是最终Return；所有新state当前。 |
| F08 | Suspended Throw当前packet可被handler捕获/再yield或传播 | wrong packet/cause/tb/context、旧caller token、丢RAISE/误判已关闭。 |
| F09 | generator Return(value)→迭代完成packet.value；主动StopIteration逃出另适配 | 直接hostReturn原value或把bodyRaise当自然终止；异常名称同字符串不算证明。 |
| F10 | Closed next/send、throw、close各自无body结果 | 不重进body、不重复上次return value；闭合返回与抛请求异常不同。 |
| F11 | generator Created-close、suspended-close、正常return值/GeneratorExit/其它异常 | ignored-GeneratorExit再yield：host错误但body仍有续体；失败不统一Closed；重试另走原路径。 |
| F12 | native coroutine创建、获取/校验await iterator、零挂起完成 | 非awaitable/非iterator结果失败；不能把任意iterable当awaitable。 |
| F13 | coroutine中间Await handoff→scheduler，恢复iterator→表达式结果/最终返回 | 中间yield不能冒await结果；参数/资源ready不随await自动成立。 |
| F14 | coroutine重入、已消耗重复await、close/throw对应适配 | 不把可恢复generator的Closed表无条件套来；失败后态/复用资格按profile。 |
| F15 | GENERATOR_COROUTINE的generator直接驱动与await使用接口分别连接 | 普通generator不因同YIELD flavor获得await资格；不另造同义family。 |
| F16 | asyncgen __anext__/asend/athrow/aclose request创建与实际await分开 | 创建request零body；首次非法nonNone、request错误复用/并发不借另request的状态。 |
| F17 | ASYNC_YIELD item完成本request但body暂停；内部AWAIT可保持同R/B session | S与latent不互换；不能用COMPLETE结束仍活动await的占用，或以HOLD抹掉item终结义务。 |
| F18 | asyncgen自然完成→StopAsyncIteration；主动终止异常独立转换 | 不准nonempty asyncgen return的源协议；未知Ref不猜None；body异常不伪自然完成。 |
| F19 | asyncgen athrow/aclose及closed/no-body/失败路径按版本表 | 不把同步Closed/Throw抄来；native ag_closed/inspect标签、request终结、续体FINISHED分别保留。 |
| F20 | YieldFrom表达式/GetIterator/首次Advance→item或exhausted.value | 获取/lookup失败不是delegated自然结束；初始无item可零次父suspend。 |
| F21 | delegate Next/Send(None)/Send(nonNone)真实调用和当前结果 | 缺send不能一律fallback next；原args/结果/异常/后态不得交换。 |
| F22 | delegate throw原raw参数、method缺失/失败、item或StopIteration.value/回父 | 不统一提前normalize；normalizer重入、delegate-only不造parent ingress。 |
| F23 | delegate close/GeneratorExit、异常覆盖、父pending/context | 不把close当send；callback可见context随真实路径，不先统一Attach父frame。 |
| F24 | scheduler取消请求→实际注入→捕获/抑制/清理再await/最终状态分别连接 | 请求被接受不证明已交付/Task已结束/资源完成；未知scheduler保typed边界，不加应用专用规则。 |
| X25 | C1 nested cleanup、saved pending/context/local binding、多cut/loop合流 | 复用resumption_cleanup_invoke_program；旧pending、旧Enter结果、普通helper逃逸和旧world拒绝。 |
| X26 | 每有限source commit、多锚shared release、未知callback后P失效/重建、N-R部分态 | host错误≠body终结；Suspend不F；COMPLETE不free；窄drop与宽raising helper不能互换。 |
| X27 | O桥：一持续activation两drive/同site不同visit、多owner、实际entry/resume/outcome | 错body/另activation/错generation/未来source/双消费拒；缺capture保gap；不同已知run/process不接。 |
| X28 | 严格wire/query/CLI、完整clause分母、预算cursor与未解析source条件 | 删optional joins/缺root不能缩分母；旧generic图只保原scope；不按方法名/FactRef授native/runtime/transform。 |

可复用且已核准确名称：`program_driver_graphs.driver_program(target=..., create=..., extra_domain=..., async_request=..., body_graph=...)`、
`create_only_program`、`async_request_program`、`multiple_creates_program`；body侧`resumption_program`、`resumption_loop_program`、
`resumption_two_cuts_program`、`resumption_cleanup_invoke_program`；`program_lifecycle_cleanup_graphs.driver_cleanup_release_program(helper=...)`、
`program_lifecycle_body_composition.body_cleanup_lifecycle_program(...)`。使用它们只是复用canonical合法骨架；
必须增加真实family adapters/结果连接，不能将旧case原样再跑就称F/O完成。

## 7. 字段冻结前确切待决项与建议实施次序

**必须先关的五件事：**

1. F05 Created.throw如何接启动异常、何时真实终结、normalization失败是否仍Created；明确context/entry/capture规则，不用猜测凑NoBodyFinish。
2. F的版本clause适用范围：复用现四bodykind与receiver/raw角色；明确具体protocol entry/await-wrapper语义如何选定，不能仅同名方法或一个全局profile标签。
3. 局部raw选择/正常化、delegate结果和host异常转换的最小精确契约锚。哪些纯descriptor/predicate可intrinsic，哪些真实lookup/factory/调用必须INVOKE，normalization不强制统一顺序。
4. O桥的缺捕获表示、Start/Resume与已保存capture/当前state实际绑定、非终结outcome及多drive持续owner关系；不借同步onecaller约束。
5. scope/兼容/完整ledger规则：旧图只generic，开启F后省掉关系不空成功；未解释native适用性单列，不写手工verified。所有query预算计派生遍历，snapshot/FK/copy准备另列。

建议一次冻结F+O共同合同（以上五项有决定才称设计收敛），随后分三批连通实施：

- **F基础闭环**：原raw→实际选择/normalize→gate→body source→host adapter；先同步generator全表，但合同/固定分母不删除其它family。
- **O发生闭环**：同一body activation至少两次drive，准确Start/Resume、saved/current输入与first outcome/N-R；缺捕获与重入同时验。
- **全家族组合**：coroutine/GENERATOR_COROUTINE、async request、delegation/await/cancel及C1/context/session/release；完整F01–X28映射后再验公共面与冻结回归。

不需要在此门实现完整Python lowerer、任意Task框架、native自动parser、GPU驱动或优化backend。
但全family可声明的输入/状态/完成/适配关系与其机器拒错不能推迟到M3；否则“模型完整”被偷换成“generic图理论上能画”。
M3负责从source/code/协议实现恢复这些绑定，M4负责实际object/owner/activation/generation/调度/物理对应；手工IR不提前授这些事实。
整个M0–M2完成、逐项验收后，按用户要求先停下来解释，再做自动建图及化简。

## 8. 实际阅读源指纹

下列为本轮读取/定位的文件；hash仅绑定阅读范围，不是全source gate或任何运行证明。

```text
abf0b303243a1f23773da34418d3dbc85a5c138dc5356b1bc9e005082c9f9e6c docs/FIRST_STAGE_COMPLETION_MATRIX.md
ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509 docs/WHOLE_PROGRAM_MODEL.md
00db11f1e7c3956ff52159f71d555e6ceaa306529614d554596e6607098f1be0 docs/WHOLE_PROGRAM_MODEL_PLAN.md
1d42e97c34c7288067c867026369ee29db1725b4b9525a93204d5bc419a405b2 docs/M1_RESUMPTION_INTERFACES.md
e775feb2ef44e5f73fcdf94a963974a377e984b9c99a12e0231507bf4cb30c25 docs/M1_RESUMPTION_BODY_COMPONENT.md
4ce49de650d58d77dc78a5d98184b57739b28a1f721d68b31eb54c6da4b32a79 docs/M1_DRIVER_INTERFACES.md
4a943058b1accf60e8be708c1770a958d914e77ef772a82f37065b296ca57f0a docs/M1_DRIVER_CONTRACT_V2.md
7fa94e7858b4c280e9739bce2c8c6eae05df124bf6df3778e46a54e0cb723fe0 docs/M1_DRIVER_IMPLEMENTATION.md
447f1ec8dbf71c704ed4f0bb6f3063ee8e6528d64b88ff6322ab276b33824d63 docs/M1_DRIVER_ACCEPTANCE.md
77ddb36f6df80cff92bfa859b6e22929d76421dba97007060a489db57fcc5951 docs/M1_DRIVER_LIFECYCLE.md
94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699 docs/M1_DRIVER_LIFECYCLE_CONTRACT.md
7d6883f2192451cff59b6e626e9f2dcac06c46da50fc79eddca4737b0073e51a docs/M1_LIFECYCLE_COMPOSITION_PLAN.md
8e219e718f8bf811bc65e02c2ccada28e607151e5c1884eebfe8dd71b82ca990 docs/M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md
db0269f2fd50e9da3fde14986d4f1e69d19c0751f63f24661b53a1ed62c7707d docs/model/PYTHON_CONTROL_PROTOCOLS.md
ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac scar/ir/program/resumption.py
3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a scar/ir/program/resumption_validation.py
c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc scar/ir/program/resumption_flow.py
d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd scar/ir/program/drivers.py
1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa scar/ir/program/driver_flow.py
4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3 scar/ir/program/driver_validation.py
326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7 scar/ir/program/lifecycle.py
49dee4e82ebe09964a1a72c0d5d19fc91b67645822e7b1abc4961d13ba381daa scar/ir/program/lifecycle_validation.py
22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea scar/ir/program/no_body_validation.py
b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc scar/ir/program/session_release_validation.py
8adaa530a1801949a0706948c9aef2410148782fa95e49da18706ed5c794fae0 scar/ir/program/lifecycle_flow.py
13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387 scar/ir/program/session_flow.py
153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7 scar/ir/program/lifecycle_analysis.py
985bdf491c4714a26180a2e91ca87e57170d9a4e49fa839147026648fb79e92f scar/ir/program/validation.py
189a66e66e81eead682adeeaf316ce14af023f9b6c4a453e123f67adcfc2c89d scar/ir/program/queries.py
88d2640c7cb23c454f95888ced4130784fd829e8d1d60292a17000278fbe4ef2 scar/ir/program/control.py
deae20c2c5056a5feac096bce4202cf7c646c334267f01c9f73d3a1ab945ed3a scar/ir/program/control_validation.py
17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0 scar/ir/program/native.py
a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f scar/ir/execution/calls.py
9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2 scar/ir/execution/call_validation.py
b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09 scar/ir/execution/coordinates.py
e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc scar/ir/execution/flow.py
51aaa2ebdda244aae1c0afddd22f881422c163200e120ba8c3d06d9c0e191d09 current_core_probe.json（root既有产物）
b07e7587b66a6ec73284fcd16552bbebed1452d547a9b26b6f3915d7b4f55c62 current_core_probe.py（只读未运行）
```

所有语言行为分母来自本轮已读`PYTHON_CONTROL_PROTOCOLS.md` §7及其版本链接/既有见证归属；
没有新增语言运行事实，没有把规范文档/类型声明/自动导入/运行实测混成同一层。到此停止。

## 9. root新增Created.throw原始观察追加（保留上文未决与反例历史）

报告初稿后收到root既有新产物。本审查只读JSON、原script和first_failure.txt，**未运行其中任何脚本**。
这组数据由root的CPython3.14.7有界stdlib见证产生，原脚本先保存六组JSON，再因错误预期assert退出1。
所以不是“六项断言PASS”；不能把后续只读JSON核对脚本误报为再运行native见证。

| 原case | JSON实际观察 | 对先前推断的修正 |
| --- | --- | --- |
| generator/ValueError实例 | GEN_CREATED→GEN_CLOSED；ValueError外传；body_log_at_throw为空 | 必须表达无用户body entry的初入异常终结。 |
| generator/非法42 | TypeError；仍GEN_CREATED；随后next可得item | 前置拒绝不应种终结F；后续启动必须保留。 |
| generator/异常类构造回调raise | 调用exception-constructor；RuntimeError；GEN_CLOSED；body log为空 | 原script把它与非法42同归CREATED的推断已被实际反证；“normalize失败都保持Created”必须撤回。 |
| generator/StopIteration实例 | GEN_CLOSED；StopIteration原样外传；cause=None；body log为空 | 原script后续PEP479 RuntimeError预期也被已保存观察反证（该assert未运行到）；不能将初入注入当body内部主动Raise。 |
| native coroutine/ValueError实例 | CORO_CREATED→CORO_CLOSED；ValueError；body log为空 | 不能只为generator补一条Send替代路径。 |
| asyncgen/ValueError实例 | 创建athrow request时仍AGEN_CREATED；实际驱动后AGEN_CLOSED；ValueError；body log为空 | request创建≠真正驱动；需保持不同阶段及session/owner角色。 |

inspect标签与body日志是此六个样例的实际观察，不单独证明完整native frame状态、内部指令执行数或对象free。
F05的设计阻断因此更精确：必须区分**前置校验拒绝 / 正常化及其失败实际进入哪条终结路径 /
无用户entry的注入终结 / body内部Raise**。终结和异常适配不能只由异常类型、错误发生在normalize还是host RAISE来猜。
Source/implementation对应仍须准确版本合同；当前NoBodyFinish只CreatedClose，不足以给此新分支直接授F。
字段冻结前仍需root/A明确真实关系与phase顺序；本追加不将语言观测当实现验收，也不把设计改报PASS。

```text
a252e2b377fcbd227f1a188278f52dee9667b41b5a3d88c2e7d287768b0ebc0d created_throw_witness.json
511abb54885c693fd10910fda359e247ed3ebcb3815dcab076d54f15f46009df created_throw_witness.py
c81ed318a4f7c4a9f8c74c0cb071a3f53fb6953ba813ccfb65d9b09bcd2890b9 created_throw_witness.first_failure.txt
f8677439978582015b14f0676def17fe8694d6b53839819957a6262bc759ff11 check_created_throw_observation.py（只读未运行）
```

此追加保留所有原分母和OPEN_WITH_BOUNDED_PLAN；不扩大新框架/新native实验。现在停止本独立审计。

## 10. P0文档收束只读receipt

按root新任务只读复核以下实际终稿；未运行任何script/Python/test，未改主docs或产品。

```text
92288c862f23e72574d558dad75f2867b136d5986c9f4a9b3ec5b5a014a42c15 docs/M1_PROTOCOL_FAMILY_AUDIT.md
ede938f3430d0090d16725d35f31f258e710778aea8a19645e75ade303e50429 docs/M1_PROTOCOL_FAMILY_PLAN.md
f5d6d117bb980d2bdac4f1bcf4fff73bf76d6ffe75ac05684028c336d12067ac design/family-obligations.md
```

**P0承接一致，未见需要改主文档的实质不一致；P1精确字段继续OPEN，不授设计/产品PASS。**

- AUDIT §2准确承认已有C2B/D1/D2结构、四kind/flavor检查、条件FrameRules/适用性；
  未把旧permit或UNKNOWN/EXTERNAL不存在的枚举当新方案，未把历史“未实施”覆盖为当前事实。
- PLAN §2逐行保留F01–F24/X25–X28，且明确同步generator全状态/请求表、其它family独立组合；
  未用generic capability、28行数或旧组件数量代替完整协议。M2的113构造/196字段仍独立保留。
- AUDIT §3/PLAN §3保留F协议原CFG/Use/result/state与O实际drive发生两主线；
  “给定关联可表达/拒错是M1、从运行恢复是M4”边界准确。O候选改以entry visit派生segment，
  不复制其值/保存列表，不借同步CallActivation一caller一activation/全历史同thread限制。
- PLAN §4五项与本报告§7一一对应：初入异常源路线、协议入口/版本、局部效果契约、持续实例/发生、完整ledger/兼容/预算。
  no-user-entry方向已选，确切normalization/注入/失败/终结/host锚尚未冻；没有将此方向决定写成P1通过。
- AUDIT §4.1与root既有JSON一致：四个generic合法IR和wrong-flavor拒绝合为五观察；
  family_adapter未验证，GENERATOR+ASYNC_REQUEST及裸Return不当旧D1产品bug或native等价。
- AUDIT §4.2准确保留六组原JSON先落盘、首assert实际exit1；constructor错误分组已撤回，
  StopIteration→RuntimeError错误预期未执行但被已保存结果反证，未说成第二次执行失败。
  后续只读checker不是重跑native/pytest，也不将其通过冒原script断言PASS。inspect/body log不升级内部机器状态证明。
- A最终family-obligations正确更新Created.throw六条、request创建时点、无用户body/finally日志、
  constructor失败已Closed及startup StopIteration原样，并把自己的源推断与root后置错误assert分别归属。
  A的no-user-entry推荐仍Proposed，未拿CreatedCloseTest为THROW授F。

**保留一个P1候选shape约束（已消息root，不是本轮主docs阻断）：**A“动态关系”候选段把
BodyDrive occurrence起点和NO_USER_ENTRY/DELEGATE_ONLY outcome写在一个宽形状内。
真实未进入父body时没有对应BodyDrive occurrence，不能为满足该候选伪造它；实际host invocation的
no-body/delegate-only路径与真正Drive→body关联须分别定位再组合。AUDIT当前O只讨论真实Drive，
PLAN把具体fields留待P1，故两份主文档没有提前采纳这个宽union。未来P1必须明确该区别，
也应从原Drive.instance ownedUse派生实际instance，避免另存可矛盾的第二份actual。

本轮仅关闭P0报告/计划承接复核；完整C2/D3、P1和整个M0–M2依然开放。用户要求模型阶段完成后先停讲解，
主计划已明确保留。此receipt追加后停止所有写入；没有新运行、实验或测试。

### 10.1 O候选shape窄修订最终核对

root/A随后落实上述具体风险后，仅核三处新文字，没有扩展源码/协议审计：

```text
da0b30175af7387c4794957e4f52be2a91298103a4921d98453450ff562a333f docs/M1_PROTOCOL_FAMILY_AUDIT.md
b026b709ffb8c5d6c42a95781175f675225dea4c04299d2bbe763e5e2c11b49f docs/M1_PROTOCOL_FAMILY_PLAN.md
54dffe02e15494ce5e038d5afc7403e3372e96c238dc1083dd0b6622acfb70e7 design/family-obligations.md
```

- AUDIT O段现明确NO_USER_ENTRY/delegate-only锚原host/helper/adapter的F关系，不为O伪造Drive、body入口或outcome。
- PLAN §4第4项现明确O仅真实BodyDrive；instance/segment能从原Use/visit派生时不再存第二事实。
- A“动态关系”已撤去原宽union：真实body驱动才有O；no-user-entry/delegate-only另为F路径，
  不要求不存在的body segment/first outcome。原instance Use及segment均派生，不造重复actual字段。

因此§10指出的候选shape风险在P0文字层关闭，原发现和旧hash保留；它不是已实施/已测功能关闭。
F01–X28、六观察/首exit1与两推断归属不变，五项精确字段仍待P1。没有设计或产品PASS，
没有重跑/启动任何脚本。当前阶段只是P0审计与计划收束，完整C2/D3/M0–M2继续OPEN。
本节为最终receipt，停止写入。

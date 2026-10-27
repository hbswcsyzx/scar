# S：state-addresses 独立有限复审

初始状态：**OPEN，产品作者尚未交付最终阅读 SHA；未作首轮产品通过判断。**
基线 clean `78dbac3dcd7a303d84ce645a68f52a6a4cf8f1a2`。本人只读源码/合同和已存日志，
不修改产品/测试，不运行 Python、pytest、组件/full、OS/LeWM/GPU。
本报告只在本 ignored artifact 追加历史；不得用后续 closure 覆盖初始 OPEN/发现。

## 1. 审查合同与实施方协作

- 已读 `docs/M1_STATE_ADDRESS_PLAN.md`（SHA `cecdf5f396db9ded0d3e19c2a377da0cd612fd20fc7fcdda950cad1df56518b2`）。
- 原设计 `design/state-interfaces.md` SHA `5b424fa85eefa06cd15024971ae677fcbc52628103aced2d00a55f7d9a9b7c19`。
- 另读 `design/alias-and-coherence.md`；该草案与本人草案不是产品能力/测试证据。
- 已向 A/B 请求 exact site/rawreference 规则、交付源码 SHA 与实际 test nodes；首轮源码审查待作者完成后进行。

保持的硬约束：Location 为唯一 coherence carrier；地址不造细 state chain；多 owner/mode/stage
不自动 complete/pure；INVOKE 引用原实际输入及两种 completion 的原后态；partial RAISE 不回退输入。
原 Use 不复制/去重；局部 whole owner 不能冒 root full_overwrite；地址/来源缺失不缩 unknown/opaque 威胁分母。

### C0：原 reference 的合同解释尚待 root 明确

这是冻结解释的差异，**不是已经发现的产品缺陷**：本人设计对非None原reference建议同 canonical
owner且不越其selection；alias-and-coherence草案允许多owner且以原reference为已知anchor，complete时
保留anchor、partial可列其他项。PLAN写“不越其已声明引用/envelope”，尚需实施时精确定义。
已向root提问：`reference=a, targets=(world,), WHOLE`，其他 RefOwner(b) 同targets 是否可接受，
取决于原reference是整个summary上界还是其中一条anchor。最终按root明确合同审，不把任一旧草案强加产品。

## 2. 原分母映射账本（初始均待实际实现/test node）

只给测试总数或引用未携带新refinement的旧用例，不足以关闭下表。原生语义/自动恢复不作为本声明门
必须实现的新编译器，但必须有图级组合或准确保留未证边界；没有对应原端口的手填字符串不计覆盖。

| ID | 原 design§5 / alias审查分母 | 本门需见的真实组合/反例 | 实际node/结论 |
| --- | --- | --- | --- |
| D01 | 同carrier namespace/field/cell/element；A05/A06/A07 | 粗写后细读、细写后粗读均读current；旧state拒绝；不新增独立细链 | 待作者 |
| D02 | 环境共享cell、alias actual、原Use不去重；A01–A04 | 原env/call参数与新地址组合；两activation/loopvisit实际owner分别解析；不同引用不授disjoint | 待作者 |
| D03 | atomic多地址/mode/stage；A17 | srcA/srcB READ、out WRITE共用原aggregate；错ownedUse/index/role/resource scope；partial余量 | 待作者 |
| D04 | INVOKE N/R；A18 | 无StateAccess的原state operand；owner/key实际invoke_arguments；各边不同槽序；missing completion不补after | 待作者 |
| D05 | 动态key/index/slice及回调边界；A09–A12/A16 | 原operand保留；None与omitted不同；hash/descriptor/raise不被路径名字抹掉；局部full_overwrite拒绝 | 待作者 |
| D06 | branch/loop/call/resumption | owner/key与root同时沿原actual→formal；反选/旧visit不串；恢复shared state来自本次输入 | 待作者 |
| D07 | storage坐标与exact原effect/Mat；A13/A14 | BYTE/ELEMENT/ABSTRACT不重解释旧Footprint；geometry不复制；错误物理关联仍拒绝/未证，不能靠地址绕guard | 待作者 |
| D08 | ResourceLocation/ResourceUse；A15 | implicit无fakehandle；原requirement/instance/handle生命周期不被新owner混同；错归属明确拒绝 | 待作者 |
| D09 | 独立威胁/partial/预算；A19 | 删除地址/对应不删coarse或source库存；未知/截断完整保留；不授native authority/disjoint | 待作者 |
| D10 | records/wire/query/legacy；A20 | 严格嵌套/namespace/rawreference；program v15；v1–v14空能力守恒；原Use端口与detached结果 | 待作者 |

D06 不能仅以旧 branch/call/resume 回归通过替代带新地址的组合；D07 不要求本门新增 native parser，
但 exact physical mapping的已知守卫不得弱化，未完成项必须在API/查询保留。任一真实声明接口分母缺失
就不称“整个state-address完成”；源码/运行别名或真实native解释仍是独立未证范围，不等同本门bug。

## 3. 初始结论

现在只确认审查范围和分母。尚未审新产品源码，尚无产品 blocker 或 PASS 结论，
尚未读取/宣称任何新 test PASS。等待作者明确可审文件/hash后，再追加具体源码发现与实际测试映射。

## C0 合同解释关闭（尚非产品 closure）

root 已明确选择保持原reference语义：它是此summary声明的owner/envelope，**不是仅一条anchor**。
非None时RefOwner必须同canonical ReferenceValue（不同ownedUse可以）；ResourceOwner仅在其原handle
也指同该value时满足该owner约束。Domain/Unknown不能借metadata绕过原限制；未知可保留PARTIAL的
准确未证条件，不能授complete。真正多owner aggregate.reference=None。
新typed selector不解释旧无单位INTERVAL；Whole/Unknown/partial envelope条件分别保留。
本门优先保留原ContentRead single-reference alignment，未有新准确物理关联时不降低旧guard。
已同步A/B；后续产品按此合同核对。此时PLAN文件仍为上方初始SHA，root宣布将追加正文澄清，
最终receipt须绑定更新后的实际文档hash，不把消息决定误称已写入初始文档。

随后只读核对：PLAN新增“S0冻结解释补充”§104–108，实际SHA为
`c14d929f60c43a93a48f5f3c717367ac7b89160e77fba6cf08b11806f5e4a635`。
该正文与上述root决定一致，C0文档接线已闭合；这仍不替代未开始的产品首轮审查。

### C1：INVOKE ORDER 假设被既有 core 反证

root/A源审指出曾拟允许严格root replacement的INVOKE STATE_ORDER形状实际上不被core接受。
本人只读复核 `program/validation.py:225–227`：terminator的每个StateVersion Use一律必须
STATE_CONTENT（control_state_role）；直接CALL亦保留内容依赖。故这不是产品拒绝合法图，
也不应列为待补正例。新refinement不得放松该旧角色守卫；严格 root full_overwrite/ORDER
只属于普通ExistingAccess的既有形状。未运行反例，后续绑定root修订后的PLAN hash。

## 首轮可读源码记录（尚非最终 PASS）

B宣布model/codec/staticquery已可读后，已读这些实现及两份新增unit源码。
model的AccessMode是同一个enum重导出；新table严格并递归检查row，不改producer。
codec15仅新capability选择，旧field sets/tag paths保留；原golden测试源码逐版核bytes。
ProgramIndex.state_address保留各条INVOKE completion原formal/argument，forward Use不伪造after，
重复operand与同Value的独立Use端口保留；移除精化仍返回原粗site。当前未见B范围具体阻断；
尚未读取其首测结果，不能把这些unit源码称PASS。

root宣布S3可读后，已读execution/state_addresses.py、public wrapper与新增integration源码。
动态地址沿原effect resolver/occurrence查询，不依静态名字选activation；原before/after/actualtransfer保留，
completion单列actualformal/forwardUse而不把Unresolved effect.post补成结果。预算在operand/resource/
completion joins前扣；canonical declaration与phase cursor保留，准备/验证/重放/最后deepcopy另列成本。

### R1 OPEN：合法旧UseID子类forward被动态view漏掉（source-inferred）

`execution/state_addresses.py:139–140` 只在 `type(port['argument']) is UseID` 时查原forward UseOccurrence。
普通completion edge的原UseID允许子类（core与saved_actual_use均按isinstance），新strict address字段
并不需要引用这个额外forward Use。最小机制：把现forwarded-state正例的forwarded.id换成旧UseID子类，
保留其他新字段精确类型；staticquery/原flow仍能保留actual，但dynamic completion.forwarded_use错误None。
无对应缺capture gap，且不是实际未观测。已通知root最小改为isinstance、保留原key不按.value归一。
本人未运行该变体，也未修改源码；等待作者修复/实际结果。

首轮所读局部SHA（后续按实际最终源码追加）：

```text
bb9993520ee76ab6dd5531884944f96a990379fff74d7935c81a10b818df4d61 program/model.py
8d841907f306ee66996b9b45b3c7b5a6a4c799361e818851dff66534e0ee519e program/state_modes.py
81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089 program/codec.py
18482a721ba9f02a687cb1a396f0b24b83cde426d487f581459aa4010a937273 program/queries.py
82661bc66d8955a2dbf354282e0bd7d701e367c01777a61d3c52339075e48e8e program/__init__.py
a57fd889c69881ee7bf26e112403bd8379a14a2bc2057e9ac812cdad24a3de15 execution/state_addresses.py
450535f82df6a48ea66953480b9bfc3dfad12cfbb5356898db43fefc010fa131 execution/query.py
47dc7d3368afc0ccea9c4a0642e1cfc394236acde787777224c1dda016bf5199 tests/integration/test_execution_state_addresses.py
41b2cb8ea6ef73fab4639718952723ebe8592dc90566cb1c95e032cdd19a9aa0 docs/M1_STATE_ADDRESS_PLAN.md
```

program/execution相对scar/ir/。尚未审A主validator，D01–D10账本未关闭。

### R1 适用范围更正与窄实现关闭（保留原推断）

root指出原最小构造未检查动态record准入；本人补读 `execution/coordinates.py:235–247`
及其 `_identifier` 后确认 UseOccurrence.use 必须 exact UseID。因此“可完整捕获的合法旧UseID子类图”
这项表述过强，**撤回其作为已证可达产品blocker的判断**，不称实测旧产品失败。
root仍将canonical branch判定改为isinstance以保留原key，并补真实可达的缺forward UseOccurrence情形：
actualtransfer/landing存在但forward Use未捕获时，completion保留原port/formal，forwarded_use=None，
新增 `state_address_forward_unobserved`；不拿formal的存在补造原Use，也不补Unresolved after。
只读已见该实现（dynamic模块SHA `321875f5327920c33dcef0ed48a785096720c4252076830005397d23a3770221`）；
该必要变体的root测试正在收尾，未将新增源码断言计为已通过。

### A 首轮有限源码审查

已读 records、完整主validator、fixture与两个owned测试。主校验保持原site/derived `(op,LocationID)`唯一、
READ/WRITE/RW子集与声明complete mode union、原reference同Value envelope、原ResourceUse/词法owner，
INVOKE所有owner/key为实际invoke_arguments；root replacement只限完整DomainWholeWRITE。
普通access本身与INVOKE completion仍由原core验证，未产生第二套current state。
截至此阅读未见A另一具体产品阻断；未知Footprint单位/selector解释始终由公开conditions和false authority保留。
这些不等于namespace/field/storage所有声明级组合已经测试：下方分母仍按实际node逐项收口。

已核作者存档（本人均未运行）：A address_records/attempt005 JUnit15 tests/0failure/time0.454s；
B codec_queries/attempt003 JUnit45 tests/0failure/time1.063s；root dynamic/attempt002 JUnit16 tests/
0failure/time0.820s。三者范围不同；早先44P1F/15P1F的forward fixture签名错误仍保留，不能累加为独立case。
这些版本早于root补新的两向stale/缺forward用例，不替代其后续实际结果。

## 最终有限 closure（保留以上 OPEN、原推断与更正）

结论：**PASS_WITH_SCOPE：本门 typed state-address 声明、原端口与实际 occurrence 组合；无剩余已知产品阻断。**
不是完整 owner/alias/native/source 自动恢复或完整 M0–M2 通过。既有 carrier 始终原链，
新精化不另起 field SSA，不改变 effects_complete/current-state/ContentRead 对齐规则。

R1原“完整UseID子类capture”候选已按上文撤回；实际可达缺forward capture现有明确gap。
其 source fix 与新 `[missing_forward=True]` 测试已核对，不把它冒称旧UseID子类运行复现。
C0 owner/envelope 与 C1 INVOKE STATE_CONTENT 解释已在终版PLAN正文闭合。

root按账本补了三项明确组合差口，均为新metadata+真实原IR端口，不只是重跑旧case：
六类selector/stage的graph→declared_path→新query，branch两条实际边的owner/key配对，以及
精化ReferenceOwner合法别名Use不能绕过原ContentRead subject精确Use守卫。
只读核到 `dynamic/attempt004/junit.xml`：29 tests、0 failures/errors/skips，JUnit time1.112s；
runner report exit0/wall1.812s。本人未启动该测试或任何其他测试。

### 原分母终态映射

下表函数名均指实际已读测试；R=unit records、V=unit validation、Q=unit staticquery、I=integration
`test_execution_state_addresses.py`，codec另列。引用通用前缀 `test_` 省略，不是新发明case ID。

| ID | 实际新能力覆盖 | 有界结论/保留范围 |
| --- | --- | --- |
| D01 | I `address_refinement_cannot_hide_stale_state_between_coarse_and_fine_requests[False/True]`；atomic原before/after | 两向旧carrier被原stale_state拒绝，合法路径读唯一after；没有独立field链。不同roots的运行隔离仍不由ID证明。 |
| D02 | I `shared_callee_address_operand_is_bound_within_each_child_activation`、loop；Q path同Value独立Uses；I selector[cell] | cell路径/原引用端口可表示，调用与重复静态site按实际occurrence分开。该call正例断言的是Data operand route，不冒称已采到共享Python cell或同scoped ObjectRef。 |
| D03 | V `mixed_owner_access_and_real_invoke_ports_form_valid_overlay`、foreign/index、mode、reference envelope、duplicate carrier；I atomic与selector stage2 | 多owner共用唯一summary，逐项mode/stage/Use原样保留；PARTIAL余量和root.full_overwrite限制保持。 |
| D04 | V invoke actualargument/contentrole；I N/R两例、forward两例；Q reversed completions和forward | 各边原CompletionResult/formal与forward Use分开；缺post不补结果、不默选NORMAL、不把freshstate当物理写。 |
| D05 | R allselectors/omitted-vs-None；I selector六参数 namespace/field/dynamic_field/cell/slice/storage；V local_full_overwrite | 实际原key/name/slice/range Uses及stage已接graph/query；不执行hash/eq/descriptor，不因field名字授纯性/非alias或回调已完成。 |
| D06 | I branch `[0/1]`、loop、sharedcallee、resume `[0/1]` | 新地址确实接选中边的owner/key源、不同loop当前state/childactivation、恢复freshstate与saved-ref route；不是只引用旧case计覆盖。 |
| D07 | I `address_declaration_cannot_bypass_original_content_read_reference_alignment[False/True]`；selector[storage]；R AddressUnit | 同canonicalReference的第二ownedUse可作合法地址owner，但不能代替原ContentRead subject Use，错接仍content_effect_reference。BYTE文字不解释旧Footprint/非uint8/strided几何，物理映射的其余事实仍沿既有G/D/P/V条件。 |
| D08 | A fixture implicit ResourceOwner/原ResourceUse；I `resource_owner_keeps_original_requirement_and_captured_instance_binding` | 不伪造隐式handle，动态仅匹配同occurrence原requirement/access。dup/OFD/重新open的native identity不因新路径重新推断，原资源门/未证边界保留。 |
| D09 | I tinybudget、missingowner、absentrefinement；Q strippedrefinement；旧V独立扫描未改 | canonical声明/原before-after/未完成cursor保留；删除精化不是NONE。不授外部alias库存完整性或disjoint；来源/native捕获仍未证。 |
| D10 | R strict variants/frozen/nestedmutation；codec15及v1–v14守恒；Q exactFK/N-R/duplicateUses/detachment/false flags | 实际typed/wire/公开面已覆盖；旧能力不默认升级，FactRef/DECLARED_COMPLETE不产生解释或转换权限。 |

原alias草案20组是原分母的机制清单，**不是20个新实测PASS**。A01–A04的真实对象/共享cell，
A09–A15的真实Python key/descriptor/NumPy alias/view/OFD语义，以及完整native读写/别名closure，
没有因为上述声明路径测试而变成运行证明；它们的source/native对应仍OPEN。当前门已覆盖这些
路径的保守表达与不授证明边界，不能据本结论宣称完整state/alias/coherence语义完成。

### 实际日志与非重复计数

- A最后owned：address_records/attempt005 **15P**；不是把attempt001–004逐次相加。
- B最后owned：codec_queries/attempt003 **45P**；原44P1F是forward测试漏删produced signature slot，
  原core正确拒绝。只有测试修正，不是放松completion守卫。
- root dynamic/attempt001 **15P1F** 同类构造问题，attempt002 **16P**，补stale/缺forward后
  attempt003 **19P**，补三项分母后attempt004 **29P**。前三个成功子集不与29P再相加。
- 尚未把最终统一组件或full计为已完成；由root冻结运行。所有时间是验收成本，不是目标程序加速。

### 本次 closure 实际源码 SHA256

```text
6ff4052771e4c92cf248f298131037f9a25a5bda8059e1547da44410d3577b61 scar/ir/program/state_addresses.py
03c1d4f8b3e9fe991f902a4e775051b2fbc8f048b49e4758fb3431833937a096 scar/ir/program/state_address_validation.py
8d841907f306ee66996b9b45b3c7b5a6a4c799361e818851dff66534e0ee519e scar/ir/program/state_modes.py
bb9993520ee76ab6dd5531884944f96a990379fff74d7935c81a10b818df4d61 scar/ir/program/model.py
277c32f7434bf1a7c08c0ac458792b5dd6971dc3b14f8b7ccbfcd50ba7923a09 scar/ir/program/validation.py
81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089 scar/ir/program/codec.py
d3519de9474369bb20d25950ae7f45d151f5ca54a78d367452d6c30825116134 scar/ir/program/queries.py
82661bc66d8955a2dbf354282e0bd7d701e367c01777a61d3c52339075e48e8e scar/ir/program/__init__.py
321875f5327920c33dcef0ed48a785096720c4252076830005397d23a3770221 scar/ir/execution/state_addresses.py
450535f82df6a48ea66953480b9bfc3dfad12cfbb5356898db43fefc010fa131 scar/ir/execution/query.py
606edb185da3499a27235bfca566f7c314f936d7567b28c3440e8c940e121eb0 tests/fixtures/program_state_addresses.py
c0722f5683c11f1f568260459514cd6f5ce97997cd378796f4ec6eaffbdaf282 tests/fixtures/execution_state_addresses.py
39b861b5ac478a304b33e6ad825d3ecf0d26c9882872c6939632f746b863e378 tests/integration/test_execution_state_addresses.py
41b2cb8ea6ef73fab4639718952723ebe8592dc90566cb1c95e032cdd19a9aa0 docs/M1_STATE_ADDRESS_PLAN.md
```

只写本ignored报告；本人未修改任何产品/fixture/test/docs，未运行Python/测试/OS采集。
若后续产品改动，仅按具体diff追加receipt；不能用上述hash替代新版本。完整M0–M2、native/runtime/source
authority与transform仍未授予，不产生LeWM/GPU结论。

# L：独立有限复审与原分母账本

初始状态：**OPEN；本次仅核冻结计划，尚未作新产品源码首轮审查或测试通过判断。**
基线clean `13201ad24e0d8236623e28709f86e13a887ed4fb`，worktree `/tmp/scar-structured-model-280qf4mi`。
本人不改产品/fixtures/tests/docs，不运行Python、compile、pytest、组件/full、workload或GPU；
只写本ignored报告并只读已有源码/日志。后续发现、原hash与closure必须追加，不能覆盖初始OPEN。

## 1. 计划范围核对

已读：

```text
2d31a4f12936ca384c06cbf6098aa564c6c70625abc558aec2230734abfd18f6 docs/M1_LITERAL_PLAN.md
749a6fdcd248b418d2f318be4d3232ad9d538a340628c3bde1283e51ed221095 design/independent-scope.md
29a4f843ecb62101756c7aacc8b1a361c1ee95b0a69e87db1c690704c4ed7548 design/core-migration.md
daf7f5abbc287d262319f05e8b07f074e0f8796d052f667ce91389c6836b6abf design/payload-budget.md
```

短design路径相对本model_literals目录。PLAN覆盖三轴（内容/来源/原求值），Data-only exact origin、
原direct与INVOKE NORMAL Data/Reference附件、准确scoped code-slot声明、uninterpreted边界、
共同固定预算、v16/旧family隔离和动态visit/activation。没有用“增加bytes/complex enum”代替关系模型。
10组独立分母与20组迁移分母均保留；目前没有理由删掉direct/INVOKE/loop/call/构造格式化组合。

关键准入：附件是原结果上的内容声明，不能重写origin/Uses/effects_complete/current state。
SourceExpression不宣称AST Constant；CodeConstant FactRef+slot不授解析成功/identity；
Unlocated/Uninterpreted不能授exact payload、type-match、native/source或transform证明。
Reference不进入activation literal预装。对象身份仍通过原ValueOccurrence/ValueDenotation，
不是payload、code hash、静态ValueID或同constant slot。

## 2. 计划级具体风险 P1：连续surrogate代码点不能仅靠普通escaped JSON

PLAN要求STR保留所有代码点/孤立surrogate并用escaped JSON。两个Python代码点D800、DC00与单一
U+10000不是相同字符串；若都用普通JSON字符串的同一 `\\ud800\\udc00` 表示，会失去区别。
本机标准库 `json/decoder.py:120–124` 明确将相邻high/low escape合并为单个补充平面代码点。
该源码SHA：`dc98d3e677612ea7311303f06a144cec6b91ebadc7ec037d1777501647578a07`
（`/home/zyf/miniconda3/envs/lewm/lib/python3.14/json/decoder.py`）。本轮未运行任何probe。

已通知root/A：须在本门明确精确表示或严格有界fallback，不能仅测孤立surrogate就宣称STR全部无损。
可复用固定payload encoding/tag；不要求重写JSON parser，旧wire字节另守恒。该项是源推断的表示风险，
不是已经运行复现的新产品失败；等待合同/实现落点。

预算候选报告根深度为1，冻结PLAN明确改为root depth0/max64，审查以PLAN为准，不把该决定算矛盾。
实际正界/越界、总payload计量单位和共享子树展开计费仍须在A实现/测试中核对；不靠全局int限额放宽。

## 3. 独立 I01–I10 分母映射（原报告ID为L01–L10）

为避免与core-migration的L01–L20混淆，本表把前者记为I，下一节把后者记为C。初始全部待实际node。

| ID | 本门必需关系 | PLAN落点/owner | 实际测试与结论 |
| --- | --- | --- | --- |
| I01 | 八类标量+tuple、type/bits、complex | §3 A payload；§2 B type/site | 待源码/实际node |
| I02 | NUL/Unicode/surrogate/任意bytes、signedzero/NaN/inf、snapshot | §3–4 A/B/root；P1尚待闭合 | 待源码/实际node |
| I03 | depth/nodes/bytes/int、nested mutation/cycle、转换前预算 | §3 A/record/v2消费者 | 待源码/实际node |
| I04 | SourceExpression/CodeConstant/Unlocated、原scope/const slot | §2 B；来源未解析不能冒验证 | 待源码/实际node |
| I05 | direct原Data/Ref producer、类型匹配、原effects/Uses | §1–2 B/root | 待源码/实际node |
| I06 | INVOKE NORMAL Data/Ref原result、N/R/forward/missing completion | §2 B静态/root实际边 | 待源码/实际node |
| I07 | 两loopvisit/两childactivation、原denotation与错接 | §2/5 root动态组合 | 待源码/实际node |
| I08 | 两同payload结果、同result重复Uses、is/alias | §1/2/5 B/root | 待源码/实际node |
| I09 | tuple/list/dict/set/展开/partialraise、f/t边界，均带新metadata | §1/3/5 root有限组合；不新增完整解释器 | 待源码/实际node |
| I10 | shared消费者family隔离、v16/旧core、strict tags/public query | §4 A/B/root | 待源码/实际node |

## 4. C01–C20 迁移分母映射（原core-migration ID为L01–L20）

| ID | 原必需正反关系 | 与I分母/PLAN的连接 | 实际测试与结论 |
| --- | --- | --- | --- |
| C01 | legacy scalar/Ref、v1迁移、v2–15独立golden bytes | I10/§4 | 待 |
| C02 | Exact Data-only，Ref/State/Binding/Protocol拒绝 | I01/I05/§1–2 | 待 |
| C03 | exact-origin-only与evaluation-only两种v16 capability | I10/§4 | 待 |
| C04 | 所有旧schema新origin/表/tag拒；普通label文本不误拒 | I10/§4 | 待 |
| C05 | bool/int/±0/NaN/inf/bytes-str/complex bits | I01/I02/§3 | 待 |
| C06 | direct原slot/值；错owner/index/缺producer/错kind | I05/§2；Data扩展也须覆盖 | 待 |
| C07 | INVOKE反排/多state/准确NORMAL produced槽 | I06/§2 | 待 |
| C08 | forward/RAISE/无actualcompletion不能补normal结果 | I06/§2 | 待 |
| C09 | 两次求值/loop同payload不同occurrence、不无证判同/不同对象 | I07/I08/§1–2 | 待 |
| C10 | 同pool/不同code同index/sourcepayload，准确scope与条件 | I04/I07/§2 | 待 |
| C11 | Exact Data可用性；对象附件dom/crossregion守卫 | I05/I07/§4 core迁移 | 待 |
| C12 | Suspend前Data与对象saved/unsaved cutavailability | I07/§4；不以旧C2回归替代新origin/附件组合 | 待 |
| C13 | Exact Data动态activation；附件Op/Visit；旧incarnation拒绝 | I07/§4 | 待 |
| C14 | denotation/state_address/frame/call/composition原producer查询 | I07/I08/I10/§4 | 待 |
| C15 | literal INT native count匹配/矛盾、bool/float伪count | I01/I10/§4；仍不证真实返回槽 | 待 |
| C16 | 深tuple/大payload/int/循环篡改/截断，不改全局设置 | I03/§3 | 待 |
| C17 | surrogate/NUL/非ASCII/bytesFF/坏JSON/重复键，旧wire不变 | I02/I10/§3–4；含P1区别 | 待 |
| C18 | subtype/custom repr/hash/eq/to_python不被执行，可变nested拒绝 | I03/I09/§3 | 待 |
| C19 | AST/unary/binop/tuple/compilefolded表达与效果/失败保留 | I04/I09/§2/5 | 待 |
| C20 | 旧SourceSemantics/OIR新kind拒绝、旧evaluator/reference profiles | I10/§4 | 待 |

10组与20组存在重叠，不能相加成30个独立测试；每组需实际node/参数与正反预期，不按总case数填PASS。
旧回归可证明兼容，不自动证明带新origin/evaluation的loop/call/suspend/容器组合。

## 5. 初始结论与后续审查边界

PLAN在声明接口范围覆盖原分母，没有被对象only或payload-only收窄；P1连续surrogate表示仍须落实。
本报告尚未审任何作者本轮新产品源码，不预判其实现通过或失败，不读取/宣称任何新test结果。
待A/B/root source-ready后只审具体有限风险：原producer与effects、类型/未知边界、准确scope/site、
actual N/R/forward、全消费者能力门控与预算/快照。没有新增完整compiler/parser的要求。
M3/M4来源/身份自动对应、运行/物理证明与完整M0–M2仍OPEN；任何声明或测试不授transform/LeWM加速。

## 6. P1设计决策追加：显式exact profile，保留legacy边界

本次只读核对后的PLAN SHA：
`1c76cdd7bec032f81d9e9eb2b609fa26362abf670b3a86a304b6d68ea93465de`。
前述初始风险与旧hash保留，不改写为已运行失败或产品已修。PLAN §3–4及冻结解释补充已明确：

- 新精确字符串profile使用STR_CODEPOINTS表达含surrogate的代码点序列，每代码点8位小写hex；
  普通STR保留无surrogate原payload。必须能区分D800/DC00两个代码点与单一U+10000，
  不能仅以孤立surrogate通过代替该关系。escaped JSON仍用于wire，但不单独承担此无损保证。
- `from_python(value, *, exact=False)`默认保持旧kind/raw STR及complex拒绝契约；
  `exact=True`才启用新complex/STR_CODEPOINTS，tuple递归保持同一profile。
- STR构造器继续接受旧raw surrogate。递归`require_exact_literal`只在新ExactOrigin/附件入口
  拒该raw形式、要求STR_CODEPOINTS；不能全局拒绝旧PythonLiteral/SourceSemantics原合法输入。
- 旧family的`require_legacy_literal`拒两新kind而保留原raw STR。旧pair JSON合并准确记为
  baseline defect；本门新Program16验收完整代码点表示，不宣称修复全部旧family/schema。

这些决策关闭P1的计划级歧义；产品源码、精确pair反例、默认/显式profile与family门控仍待
source-ready后审查和作者实际测试。I02/I10、C17/C20分母未缩减，不要求升级所有family或削弱旧测试。
本追加未读取本轮新产品源码、未执行Python/probe/测试，也不授本门实现PASS。

## 7. 冻结源码有限审查（保留前文OPEN历史）

本轮实际读取A/B/root新源码、fixture、测试和既有JUnit；没有执行Python、测试、probe、编译或目标代码。
审查者没有修改产品/tests/docs。以下是源码事实与作者实际结果，不是独立运行或runtime/native证明。

- `program/model.py:194,218,312`与`literal_sources.py:84`：ExactLiteralOrigin只准Data；typed payload
  精确匹配builtin全名。Reference/State/Binding/Protocol不借附件进入activation预装。Uninterpreted只准附件，
  不进入exact origin、不授type/content匹配。原Reference的identity/targets/selector规则保持。
- `model.py:487,503`与`literal_validation.py:7`：site指原direct结果或准确NORMAL逻辑CompletionResult；
  唯一formal从原successor.arguments中该index派生，不按landing前缀猜。原core仍校验completion_slots、
  origin、region、dominance、Uses和current state。附件不增加producer/actual/world图。
- `literal_sources.py:22,45`和`program/queries.py:348`：SourceExpression带原versioned span；CodeConstant
  带原scoped fact容器及独立index。源码明确没有code/slot/source replay；这些声明不能判真实常量池identity。
  查询分别列Uninterpreted、Unlocated、SourceExpression、CodeConstant条件，不把条件抹成纯性或已解析来源。
- `literals.py:194,252,313`：物化树、wire树、Python builtin树迭代预检，root0/depth64、展开节点16384、
  累计payload1MiB、整数4096十进制digits/13608bit预检；共享子树按展开计。scheduled_nodes在推入前预留；
  exact长STR在surrogate扫描前长度拒绝。整数分块转换不修改进程全局限制。STR_CODEPOINTS按UTF32代码点计量。
- `record_codec.py:54,109`及`v2/_validation.py:115`先复用受限payload检查；本地tag在每层由有界decoder核对。
  `semantics_v2.py:199`、`v2/codec.py:188,348`、`v2/optimization.py:261,266`守legacy profile；两原frontend
  显式exact=False。未把共享新kind静默推广为旧evaluator/SourceSemantics/OIR新能力。
- `execution/literals.py:29,73`：只绑定准确occurrence和实际transfer的原结果；缺NORMAL、不选NORMAL、缺结果、
  缺denotation保持具体gap/NOT_TAKEN；原操作有序Uses逐个绑定，不按payload借另一visit/activation。
  预算在刷新前校验，截断保留canonical声明、cursor和pending_operands；返回detached view。
- `execution/flow.py:157`、`execution/validation.py:316`、`execution/query.py:85`、`state_addresses.py:66`
  仅把旧origin/新Data origin视为抽象内容；对象附件不匹配is_literal_origin。cut、stale-incarnation和activation
  守卫未更改。`production_ranges.py:194`只取exact INT（非bool）；`validity_validation.py:184`仍保留原返回槽未证gap。
- Reference-only `analysis/frame_queries.py:69`、`call_operand_routes.py:135`仍按原OperationResult/完成边界分类；
  没有把附件对象改成LITERAL_REFERENCE。`composition_routes.py:141`从原occurrence/visit/activation派生producer；
  `content_validation.py:404`仍分DataIdentity/ObjectIdentity。这些旁路是源码核对，不谎称新增专属frame/composition测试。

截至上述源码，没有确认的新产品阻断。一个实际验收分母缺口C07（新metadata+多state）已报root；
root决定补有限新组合，完成前不把初始一state的反排fixture写成多state实测。

## 8. 实际focused证据与首败

已读三组精确command/report/stdout/JUnit。均由各作者使用激活lewm的Python3.14.7运行，非本审查者运行。
不把25+65+54相加成语言覆盖率，也不把重复子集累计。

| 证据相对目录 | 实际终态 | 范围与历史 |
| --- | --- | --- |
| payload_budget/attempt005 | JUnit25、0failure/0error；stdout/receipt25P | A两个unit文件；001–004旧通过子集保留。root源审发现STR预检、scheduled节点、nested generic tags后加实际回归；没有伪造修复前pytest失败。 |
| core_literal/attempt001 | JUnit65、0failure/0error、1.070s | B三个unit文件。preflight.initial.log保存tuple分支size未初始化的真实构造异常；作者修后首pytest65P。 |
| dynamic_literal/attempt004 | JUnit54、0failure/0error、1.579s；runner wall2.2867s/exit0 | root两个文件；001的48P1F仅错期待stale_incarnation（实际早被use_activation拒），00249P；00351P3F是新fixture违反Initial/Attach位置。仅修新fixture/断言，旧守卫未放宽。 |

v15独立fixture为15511bytes、SHA `0bd50636fb4f18c85239917b2895f71b9a0cfff0b0c1fdf77cb715068851dd8e`，
proof绑定冻结13201ad与旧codec `81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089`。
新test核旧golden重新编码及原state_address_program编码字节；没有从新codec重造旧期望。

JUnit SHA：

```text
305c313dad80b08c51efd4ae6b4f1d91edc6d20d52222198d2fefcc936d7afe4 payload_budget/attempt005/junit.xml
87435740440e38ed6cd5eba4b97feefcfc8cb1726ad78f660da83852b95ddbfe core_literal/attempt001/junit.xml
e6975543608320905a71f198ac7d3ac6aacb0964d7313f775c54168dcb9ba787 dynamic_literal/attempt004/junit.xml
```

## 9. I01–I10终态映射（实际节点与保留范围）

短文件名：A=`unit/test_literal_payloads.py`，AL=`unit/test_literal_codec_boundaries.py`，
B=`unit/test_program_literals.py`，BW=`unit/test_program_literal_codec.py`，BQ=`unit/test_program_literal_query.py`，
R=`integration/test_execution_literals.py`，RC=`unit/test_literal_consumer_connections.py`；均位于tests/。
下表不是把未执行的子项填PASS；“源核”与“新声明IR实测”分别写明。

| ID | 实际新证据/源码落点 | 范围结论 |
| --- | --- | --- |
| I01 | B `exact_data_payload_family`；R `exact_abstract_content_has_activation_availability_and_no_object_identity`；A `complex_components_keep_binary64_bits`/profile | 八标量/tuple的typed内容接入；不等于AST自动导入。 |
| I02 | A `surrogate_profile_roundtrips_adjacent_codepoints_without_pair_merge`明确pair≠U10000；BW `exact_escaped_payload_survives_utf8_snapshot`；A binary64 bits | P1新profile实际闭合；旧raw STR pair基线缺陷保留，非全family修复。 |
| I03 | A integer/depth/shared-subtree/payload/oversized-STR/scheduled-node/wire预算nodes；AL nested tags/decoder；R `tiny_budget_*` | 边界/循环/篡改/转换前预检和query截断覆盖；非整个JSON/parser/所有CPU预算。 |
| I04 | B definitions/code_slot/nested source mutation；BQ conditions；R loop/call code_definition+construction SourceExpression | scoped引用/slot声明可表达且明确未重放；不认fact locator为已验证code容器。 |
| I05 | B direct错site/type；BQ `direct_query_keeps_original_objects_order_and_effects`；R direct Data/Ref | 实际原producer、RW状态、effects_complete=False、重复Uses保留。 |
| I06 | B invalid_original_site；BQ invoke两个逻辑槽反排；R actual NORMAL/RAISE/missingcompletion | 新Data/Ref N/R/缺完成已测；C07多state补充待下节receipt。 |
| I07 | R 两loopvisit/两childactivation Data/Ref；same/different既有ObjectIdentity；stale/otherchild；两resume ingress+unsaved拒绝 | 新metadata组合真实接原execution；ObjectIdentity是声明，不是运行采集或自动恢复。 |
| I08 | BQ direct两独立Uses同value；R loop/call相同payload可同/异denotation与literal.observe两Use | 保留alias/identity观察所需原端口；literal.observe是保守opaque观察，未新实现Python is解释器。 |
| I09 | R `runtime_construction_keeps_unknown_inputs_repeated_uses_and_effects`六参数；A mutable/nested拒绝；R真实INVOKE RAISE | tuple/list/dict/set/f/t仅附件+opaque构造边界；未展开unpack/回调/partial构造内部，仍属M2，不能把六labels冒六完整协议。 |
| I10 | AL SourceSemantics/OIR/decoder守门；A默认exact=False；BW capability/golden/旧schema；BQ/R publicquery与无附件/预算 | 新接口与旧family分离已源审/新测；旧全部regression由统一component/full另验，不从54/65推全覆盖。 |

## 10. C01–C20终态映射（不删除原设计子项）

| ID | 实际证据/源核 | 准确边界 |
| --- | --- | --- |
| C01 | BW `independent_v15_golden_bytes_and_current_factory_unchanged`；旧state_address_codec原goldens/v1 migration断言保留 | 本focused新增独立v15实测；v1–14兼容留统一门，不能说全在65中重跑。 |
| C02 | B exact Data-only/type及private_corruption；model._value_fields+ProtocolValue构造 | Ref/State实际反例；Binding/Protocol按原exact origin准入源核，非伪造各有新test。 |
| C03 | BW `either_capability_selects_v16`三参数 | origin-only/evaluation-only/both实际选择16。 |
| C04 | BW old1–15空字段拒、v15新origin偷渡、wrongtag/authority/missingfield；codec版本能力后检 | 全旧field门实测；新tag不靠扫描所有字符串；label文本仍普通文本。 |
| C05 | A complex bit两参数/profile；B/R标量；BW complexNaN往返 | descriptor不按Python==/is合并；不是所有IEEE位串穷举。 |
| C06 | B invalid_original_site/direct-state/out-of-range/absent；BQ original origin/slot | 机械原result约束实际覆盖；外region producer由原core守卫。 |
| C07 | BQ invoke反排Data/Ref/1state；root已接受需补2domain新组合 | 暂留OPEN验收子项；不把一state谎记多state。 |
| C08 | R NORMAL/RAISE/缺transfer；InvokeLiteralResult exact CR与literal_site positions源核 | forwarded Use不能成为本次新产出；带forward原Use的新组合已请求与C07并入，待receipt。 |
| C09 | R loop两visit、same/different denotation两参数 | 不按内容选同/异identity；均声明IR，不是实际LOAD次数证据。 |
| C10 | R 同CodeConstant两child/同slot但same/different对象；B CodeConstant准确非boolindex；BQ未重放条件 | 不同code同index不会被本接口按裸index接线；无code parser故不谎称source-scope矛盾已重放检测。 |
| C11 | R activation exactData；原core普通producer/dominance/region源核；R wrongsite/oldchild拒 | 附件不进入literal availability豁免；不是完整frontend dominance验证。 |
| C12 | R `suspension_keeps_abstract_content_but_restores_object_only_through_saved_use[0,1]`和unsaved拒绝 | 真saved Use路由；不凭immutable内容恢复对象。 |
| C13 | R exactData origin activation、direct Op、INVOKE Visit；loop stale/call use_activation | 同静态site不同incarnation有实测；不跨activation借值。 |
| C14 | R denotation/state_address/CallActivation；composition_routes/frame/call_operand_routes源码保留原producer | 新frame/composition专属参数未跑；已验证的是共享原origin接口不变，不宣称其全协议通过。 |
| C15 | RC builtinINT4/5/True/str/complex/inf；RC equalcount仍result_port_unverified | 4对/5错，非INT只gap；无native返回槽或physical write证明。 |
| C16 | A预算/循环/nested mutation；R tinybudget+pending；B nested record mutation | 全局int设置守恒；超限拒，不截为合法值。 |
| C17 | A/BW pair/NUL/nonASCII/bytesFF/strict shape；record_codec.loads原duplicatekey/nonfinite guard源核 | 新码点实际反例与wire闭合；坏JSON原回归另统一门。 |
| C18 | A拒subclass/用户对象/可变nested；exact类型预检源核 | 未调用repr/hash/eq/to_python来验证用户payload；不把此有限检查描述成任意恶意Python对象沙箱。 |
| C19 | R SourceExpression+opaque构造，direct computed结果保原producer；原frontend exact=False源核 | Unary/BinOp/compile-folding自动导入未实现，准确保留M3；不把payload当AST分类。 |
| C20 | AL SourceSemantics/OIR构造+解码+mutated writer；A legacy默认拒complex、rawSTR保留；frame/call保持Reference旧分流 | 新kind不授旧evaluator支持，旧whitelist/全regression等统一门。 |

当前有限源审结论：没有确认产品blocker；C07/C08补充actual组合待root实际日志后最终receipt。
未实现的M2构造内部、M3来源/constpool解析和M4运行身份不计本声明接口的证明，也不能从表中删掉或称已完成。

## 11. 本轮实际阅读指纹

以下sha由只读sha256sum核对当前文件，与作者final manifests中对应项一致。

```text
a2ef2cb826378d034143134f3c85f0e3fb91c9adb67415ce88e74b64812f24f9 scar/ir/literals.py
0954c05e53a6dcb31f449461db71c63fdcdd9f95a9c053424d86bf5217a89ef3 scar/ir/record_codec.py
f1c640101d6d9ffc8baa7a647cad2862353fcdcd196c698f1f97b7764be04ede scar/ir/v2/_validation.py
25cb12cdb94e0e907d4dee649812a14da038ce2d8fc5226733170cbfcb5d6147 scar/ir/v2/codec.py
5d943b7d48b159cfb8512ffff228236aee29d3c4f795ff0319d44489a81a4094 scar/ir/semantics_v2.py
429313a4b30d82fb0dbbb908d48caec5d4849142ac72cc1ab10cdf2bd919620f scar/ir/v2/optimization.py
2c20b09a3affc372f1103904bdf100dd3e0963c6ed89463bd57dbcae1e512a96 scar/analysis/source_semantics_v2.py
acc97151e208982c35ef0c49dc8b45105508f202aab97ec008f189cc861e7dfc scar/analysis/local_statement_semantics_v2.py
9b3e99c0335d4177ee1814301a0be0da52039dfa10575bb78e46f411ba5c7a06 scar/ir/program/literal_sources.py
5659733ce7138c56cf9070bbc970a4a954860aa121db5faed90447658f674152 scar/ir/program/model.py
6c2cfdd03cbc4f70f32a7bf483f5914e406d10171821792bb5234e821750e336 scar/ir/program/codec.py
985bdf491c4714a26180a2e91ca87e57170d9a4e49fa839147026648fb79e92f scar/ir/program/validation.py
189a66e66e81eead682adeeaf316ce14af023f9b6c4a453e123f67adcfc2c89d scar/ir/program/queries.py
1c0cc6ce2464804dfb29fced4cdf9ba7f4f0ffa65407b62073e0f17fd91436ca scar/ir/program/literal_validation.py
dcd0fa8514577f38d9b9bc3a3daf9e0ea7d51085fea3e45bad3d87f6e37bb390 scar/ir/program/__init__.py
ac1a100d74f333cc0f85efeb5e4624ec0ef838ceb3ab95a0986c037d29f09598 scar/ir/execution/literals.py
ae13abeb29d54800a20bd15096a1d9b97a9fb8483e9235102c92035851a62372 scar/ir/execution/query.py
e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc scar/ir/execution/flow.py
5350936fe93eac37edbfc26a2c9748debde727a488b03c02366556ea53b0352e scar/ir/execution/validation.py
db6f8668024098cb58698a14d03388953f508685bb8579ed1f7162d2524b37d4 scar/ir/execution/validity_validation.py
2ce0377920a5b07e9268fbcb91404afc414a129385b155255998b75b718dc49b scar/ir/execution/state_addresses.py
42778b9c3ede578e1f664c5689aa4471f4df096855c273434bde589b429ca292 scar/ir/execution/production_ranges.py
4db3d0ca485ef345ad2625673a97f5a5490d4c42a682f752864e99632ac6ca40 scar/analysis/frame_queries.py
43c5b3d603bc95b80f270fe9376cd4b9d6f236e7ad2d98b2bc583291f2f3db54 scar/analysis/call_operand_routes.py
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca scar/ir/execution/composition_routes.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f scar/ir/execution/content_validation.py
1c76cdd7bec032f81d9e9eb2b609fa26362abf670b3a86a304b6d68ea93465de docs/M1_LITERAL_PLAN.md
cec829c3ef21b7368d67e0c5fd55a520f394379a329904dd30e779f452199663 docs/M1_LITERAL_INTERFACES.md
```

新fixtures/tests精确hash亦已读核作者core_literal/source.final.json和dynamic_literal/source.final.json；
C07后续仅新fixture/test变化时将在追加receipt绑定新hash，不静默把旧focused视为其验证。

## 12. C07/C08补充关闭与最终有限结论

在前文实际验收缺口反馈后，root只新增fixture/test，没有扩字段或放宽产品。
已读`execution_literals.py:153::two_domain_literal_invoke`与
`test_execution_literals.py:108::test_two_state_domains_and_leading_forwarded_reference_keep_exact_produced_slot`
（Data/Ref×NORMAL/RAISE四参数），以及`:126::test_forwarded_operand_and_second_state_slot_cannot_be_new_literal_producers`。

本fixture有真实第二carrier：direct READ_WRITE产生独立post，INVOKE NORMAL包含DATA/REF/state1/state2，
RAISE含REF/state1/state2；NORMAL landing前缀是独立owned `invoke.forward` Use（指同constructed值），
而不是invoke_arguments中的原`invoke.ref` Use复用。原formal位次随之变化，Data在physical3、Ref在physical2，
附件仍按原CompletionResult逻辑index取产出。forward原Use保留formal_route；state2不能当literal结果。
RAISE时查询不借NORMAL结果，真实第二RAISE state保持。这关闭C07多state及C08新metadata+forward的实际组合分母。

首补充attempt005为**54P5F**：新fixture复用同Use同时作为调用actual/edgeforward，被原`control_binding`
正确拒绝。root只增独立forward ownedUse修fixture，未改validator。attempt006实际**59P、0failure/0error**，
stdout1.72s、JUnit1.727s，report exit0/runner wall2.452701s；旧54P与59P不累计。
本审查只读取现有日志/源码，没有独立执行。最终两新增文件及新JUnit绑定如下：

```text
471e16ea0b9a4610b8326b6818d311a2572112d51196616bfd1da10118bd71e2 tests/fixtures/execution_literals.py
277196aef16b49e12827852a2f8355c6e3aa834634e6a0873e397fc4cce265eb tests/integration/test_execution_literals.py
ffb7e8bfdef7bc0ce7f2bbc128a4c4f19c110028e60b61658d43c7b1ba858584 dynamic_literal/attempt006/junit.xml
```

此receipt保留§11原fixture/test manifest时间点，不把它的旧hash静默说成attempt006源；
§11列举的产品/API/PLAN hashes本次补充未改变。C07/C08表的暂OPEN由本节关闭，其余I/C映射与范围限制不变。

**最终结论：PASS_WITH_SCOPE。** 在已冻结的有限内容/来源声明/原求值端口接口范围内，未见剩余确认产品阻断；
原20组设计分母和独立10组均逐项保留，不能将表中“源码核对/条件未证/旧回归等统一门”重写为每项专属实测。
P1有新精确profile与pair≠U10000实际反例；旧rawSTR问题保持baseline defect。

本结论不把以下缺口包装成L门已验证事实：真实AST/compile/source/code-slot对应、运行对象身份与捕获完整性、
容器/格式化/展开内部协议、所有旧family/front-end能力、native效果/返回槽、纯性或transform/LeWM加速。
特别是I09/C19为保守opaque边界，完整M2仍OPEN；C10的CodeConstant scope只是明确未重放的声明，
C14部分旁路仅源码保持，不虚构新增运行证据。完整M0–M2/M3–M4未完成。

统一component/full由root按冻结流程另验，本报告不预授最终full通过。本次最后写入仅此ignored报告；
审查者现在停止写入/测试，等待root联合冻结。

### 最后序列化接缝receipt（仅追加新test，产品未改）

按root后续明确通知，只读核对新增
`test_existing_execution_wire_roundtrips_v16_program_snapshot_and_original_result`：
用原execution.codec dumps/loads往返同model，核snapshot schema16，再由新查询返回原computed结果，
transform仍False；没有新增execution schema/原producer/Use。attempt007仅该节点，实际1P/0failure/0error，
stdout0.74s、JUnit0.744s、runner wall1.497218s/exit0。不是重跑59节点，也不将重复子集累计。

最终test文件hash由§12的`277196...`迁移为
`aa300f024fdf5125bccfd739af9a2f3940cb1a90a57c30dd3d03ec64a5cc0d41`；
该新增JUnit SHA为`7b22920a831e473aad90006d3d12b169248ef7afa42f3f6528d509060509b50a`。
§11产品/PLAN/API和§12fixture hash未变。有限PASS_WITH_SCOPE及所有原范围限制不变；
作者当前root两个文件共有60节点，最终统一组件负责在同冻结源上一次验收，不冒称此1P已跑全部60。
此为本轮最后追加，不新增运行或测试。

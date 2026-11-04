# 当前状态

**第一阶段未完成。当前按形式阶段重新验收：F0 → F1 → F2 → F3 → F4 → F5 → F6。**
阶段定义见 [ARCHITECTURE](ARCHITECTURE.md)。F0/F1/F2及F3全部子层和组合已按声明profile与866源范围验收；F4-A结构类型域已验收，当前F4-B操作签名及产生规则尚未完成。
现有后层代码及成果保留，但不能代替前端完整性证明。

## F0：原始材料

当前模型声明的866个源单位、12,655,117原始bytes已全部保存并逐项fresh核验。
每份材料保存唯一原bytes blob、SHA/长度、解释器profile、编码/解码结果与准确错误。
没有执行目标lexer、parser、symtable、compile或LeWM；没有据此宣布后层通过。

| 核验 | 结果 |
|---|---:|
| 保全 / fresh核验 | 866 / 866 |
| 来源 | 866份均与文件原始版本精确匹配 |
| 原扫描remaining / issues | 0 / 0 |
| 原21,666分片、旧unit字段与关系发布 | 保持 |
| 初次归档 / 最终fresh核验 | 38.72 / 4.77秒 |

边界：866/866是声明材料目录的完整性，不证明所有程序依赖已发现，更不证明词法、AST、绑定或执行图完整。
独立F0入口支持语法非法、编码/解码失败的bytes；失败仍保原文，预算/不可用输入明确报错。
CP932等非可逆codec不能仅凭相同文本恢复；候选必须匹配原raw SHA/长度并再核解码文本。
partial不覆盖当前模型；归档仅追加owned材料，保所有旧端点，fresh核验不改模型。
当前F0是独立命令，旧static入口尚不能视为自动执行它。

证据：`artifacts/current/queries/formal-frontend-f0/{run.json,acquisition/result.json,verification/result.json}`。
纯API与独立材料集成2例通过；集成强制禁止ast.parse/symtable，并核不可逆编码、缺文件、预算和并发新增文件保留。
补审发现unicode_escape解码warning受外部warnings-as-error影响；已固定忽略codec警告并恢复调用方过滤器，
并行归档改用spawn隔离。3例通过；866份补充fresh核验4.72秒，材料与manifest未变。
补验：`artifacts/current/queries/formal-frontend-f0/warning-policy-verification/result.json`。

## F1词法

**F1词法已验收**：866份声明源码共1,961,177个token，全部真实EOF；4个spawn进程采集44.41秒，
独立fresh重放109.73秒。866个词法分片共82,316,986压缩bytes；没有运行parser/symtable或目标。
保存全部TokenInfo字段、exact_type、可逆换行视图、三种坐标、source gap、native错误参数、warnings及预算状态。
闭合schema含69个terminal与48个exact operator；实际源码观察13种terminal，不能混作69种均实际执行。
7个聚焦检查通过（2.57秒），有限族独立核源码引用/覆盖区间，并覆盖全部48操作符和140个前缀引号组合。
捕获后去掉新增词法收据可精确还原F0 manifest SHA；旧22,532分片及端点保持，fresh核验不改模型。
证据：`artifacts/current/queries/formal-frontend-f1/{run.json,acquisition/result.json,verification/result.json}`。
验收限本机profile与声明目录，不证明依赖发现完整，也不是穷举任意输入字符串或错误消息。

## F2语法

866份源码全部PARSED，1,511,372个occurrence、2,551,189个field槽和3,931,984个attribute槽。
8个spawn进程采集110.91秒，独立重读/还原并与官方新解析逐字段核验157.32秒；没有执行目标或symtable。
新增866个语法分片共33,269,423压缩bytes。保显式presence、列表None空洞、精确IEEE/complex/bytes/代理码点。
113个constructor×196field及288attribute槽的339种合成形态通过；实际源码见101种constructor，二者分别计数。
F1/F2共11个聚焦检查通过（5.21秒），含四mode、独立wire核对、预算与上游禁止解析。
新表去掉新增收据可精确还原原F1 manifest；旧23,398分片、unit字段、关系与ID保持。
语法成功不等于scope合法，也不是最终执行依赖图；现有ast.walk身份不因新parser参数而静默重排。

采集证据：`artifacts/current/queries/formal-frontend-f2/acquisition/result.json`。
完整核验与汇总：`/var/tmp/scar-f2-recovery-7w7nd_0z/{verification/result.json,run.json}`。

## F3-A材料（已验收，单独不授AST连接）

**Implemented/Verified**：完整类型化public compiler材料、canonical append、collect-only独立store和fresh reader。
866份源码全部CAPTURED，40,411个scope、208,528个symbol；866分片共2,981,301压缩bytes，解释前沿0。
8进程采集162.00秒、独立核验162.33秒（均包含完整F0/F1/F2重验；纯native双pass审计为6.24秒）。
6个聚焦检查通过，含4个F3-A族与2个F1/F2集成；eval.py单文件9scope/89symbol亦独立验证。

原序参数/符号、原始integer flags、nested/type及child别名均保存；不持久化历史native地址。
修复了adapter错误冒充compiler诊断，以及store摘要/预算/权限声明未验证的问题。
实际跨seed实验确认free-symbol补入顺序不同；profile现在保有效hash上下文，跨worker/replay不匹配则拒。
PUBLIC_COMPILER_VIEW/UNJOINED始终显式；这不是完整lexical scope、名字绑定或第一阶段完成证明。

本轮材料/汇总在`/var/tmp/scar-f2-recovery-7w7nd_0z/f3a/{materials,verification,run.json}`。
/home仍emergency_ro；通过同一main的变更源码缓冲运行，原模型manifest和消费分片不变。
真实模型尚未注册新材料（canonical_model_published=false）；fixture已验证追加端点保持及canonical fresh读回。

## F3-B字段角色（已验收，尚不含绑定）

113个constructor、196个field和288个attribute的484条共享规则全部核对。
866/866源码CLASSIFIED；6,483,173槽精确对应F2的2,551,189个field和3,931,984个attribute，四分区计数闭合。
保存563,522稀疏ports；867个分片含唯一catalog，共6,462,596压缩bytes，不重复保存文本、字面量或坐标。
8进程采集167.00秒、独立fresh核验170.78秒（含完整F0/F1/F2重验）；无预算前沿，不执行symtable或目标。
最终5个聚焦检查10.00秒通过，另4个F2 reader回归3.15秒通过；规则/实例覆盖分开核对。
修正literal None与optional None投影混同；增量赋值/仅注解/import派生binder等均按原字段和ctx机械分类。
`SyntaxRoleView`一次构建索引后复用查询任意原槽；runtime_effects=NOT_CLAIMED，scope_binding=NOT_COMPUTED_IN_F3B。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3b/{materials,verification,run.json}`。
原模型与全部消费收据不变；因/home只读，实际模型尚未注册F3-B材料，canonical_model_published=false。

## C1源码上下文（已验收，尚不含名字绑定）

50特殊/12描述符/95继承child字段及327metadata槽均显式派发；metadata与祖先求值抑制分轴。
866/866源码CONTEXTUALIZED：33,752个source scope、65,171个求值region、3,210个private策略、94,813条稀疏边界。
全部6,483,173槽与563,522个原B端口逐项校验可唯一查询；scope/region引用闭合、无环，抑制不能被子lambda解除。
867个分片含唯一catalog，共5,792,726压缩bytes；不复制AST、逐slot/port上下文或Tensor值。
8进程采集262.13秒、独立fresh核验266.26秒（含F0/F1/F2/B重验）；无预算前沿，无symtable/目标执行或真实frame。
函数/类/lambda/推导式/type alias作用域数还与已验收F2构造器数独立精确对账，非仅核生成器自身摘要。
3族上下文检查8.32秒、最终C1/B两个集成6.64秒通过；修复Interactive future directive漏识别。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3c1/{materials,verification,source-definition-agreement.json,run.json}`。
原模型及B输入store不变；/home仍只读，canonical_model_published=false，源码缓冲与主工作区待同步。

## C2a名字投影与声明账本（已验收；本层仅含声明）

16个lexical字段/15类规则完整核对；866/866源码DECLARED，563,522原B端口都有明确disposition。
72,731个共享名字键、392,706条声明贡献、33,752份scope摘要，conflicts=0；source/home、操作意图/visit flags/visibility/C1抑制分轴。
SELECTIVE按原typeparam访问前缀，ALL读取原ClassDef名字；投影阶段明确SYMBOL_VISIT_PROJECTION，不授runtime地址。
867分片含唯一catalog，共16,042,314压缩bytes；8进程采集358.73秒、独立fresh核验368.58秒（含F0/F1/F2/B/C1）。
3族单元10.97秒、C2a集成7.14秒、C1集成回归4.36秒均通过；原模型及B/C1 store不变，采集不执行目标、调用symtable或生成目标bytecode。
额外独立对账：866份已明确对应的exec根scope中，26,214个声明名字均见于原官方根符号表；不代表内部scope已join。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3c2a/{materials,verification,root-symbol-agreement.json,run.json}`。
lookup_resolution=NOT_COMPUTED_IN_C2A；/home只读，canonical_model_published=false，主工作区及实际模型同步仍待恢复写入。

## C2b条件化namespace与捕获（已按声明范围验收）

866/866源码RESOLVED；563,522原B端口、33,752原C1 scope均保原引用与完整处置。
83,117逻辑bindings、112,631环境接口、86,775共享读计划/116,873步、10,224捕获需求/10,295共享父链hop、8,375隐式需求；冲突/前沿0。
8进程转换473.15秒、独立全量fresh479.73秒，均含F0/F1/F2/B/C1/C2a重验；全部原收据、引用与逆边一致。
867分片含一份catalog，共16,090,990压缩bytes；exec ROOT独立对账26,205键一致/0差异，排除104键、31个零比较项单位不计通过。
最新profile的3族检查与存储集成已通过：namespace 5.41秒、capture/codec两族30.01秒、集成10.33秒。
本层保存独立读/写/删路径，prepared mapping与class-dict namespace、local/typeparam与class协议分域；不假设真实globals字典相同。
初次产物因共享annotation只采用首region、future参与轴混淆而拒收；已修为逐原region/anchor与analysis_visibility，字面量无port亦覆盖。
原首批派生分片已按owned收据删除，只保失败统计；修正后的source profile重新采集，未给旧产物授新语义。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3c2b/{materials,verification,root-symbol-agreement.json,implementation.json,run.json}`。
SOURCE_NAMESPACE_TEMPLATES、runtime_binding=NOT_OBSERVED、compiler_projection=NOT_COMPUTED_IN_C2B；原模型及三上游store不变。

## C3-T编译器拓扑（已按声明范围验收）

113 constructor=21特殊handler+92有序访问；484字段=54特殊child+91普通child+12marker+327payload，闭分区逐项核官方规则。
866/866源码PROJECTED；44,032模板保留原附着边，33,752原source scope全部有投影，全部65,171 region可查询。
公开行40,411、内联1,279、future脱离2,342、detached后代0，3,621条显式改写；不按name/line或地址接线。
8进程采集506.00秒、独立重放506.91秒，均含C1及F3-A全量fresh；无前沿/对应矛盾。
867分片含一份catalog，共1,923,028压缩bytes；独立守恒对账逐项核全部source scope/region、native行/父边/有序子边，0失败。
额外10,280个无C1 scope的header模板逐原occurrence等于函数体数18,669减原header scope8,389，未按空symbol形状猜。
最终profile 3族单元11.38秒、唯一存储集成9.34秒通过；普通49构造/91 child字段另逐case核官方visit顺序，0差异。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3c3/{materials,verification,topology-agreement.json,transparent-visitor-audit.json,run.json}`。
原材料及model不变，canonical_model_published=false；symbol_origin_projection/parameter_projection=NOT_COMPUTED_IN_C3T，runtime_execution=NOT_OBSERVED。

## C3-S符号来源与参数（已按声明范围验收）

原标量visitor重放→versioned Fact DAG→沿原T树分析→inline copy/keep/delete、cell/free转发→原A行和参数序投影。
866/866源码PROJECTED：220,704 compiler slots、447,785 raw贡献、392,706源码贡献处置、433,867事实、4,388变换、2,604协议需求。
44,032块的208,528原native symbol整字及63,315有序参数位置全部匹配；scope code与低位mask分域，不冒充runtime co_varnames布局。
16进程采集638.22秒、独立全量fresh643.98秒，严格重验T及D各自输入；0前沿/投影矛盾。
867分片含单一catalog，共19,950,831压缩bytes；独立对账全部符号/参数/D贡献/B端口/Fact DAG及447,785原F2锚点，0失败。
76个零低位行全有FREE_RELAY来源；实际slot=208,528 PUBLIC/4,388 INLINED/7,788 DETACHED，DELETED真实0另由micro覆盖，不混为观察值。
Raw两族3.63秒、solver手写两族0.44秒、存储集成19.08秒、8个关键联例14.97秒通过；collector替换native答案仍得到相同raw输出。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3c3s/{materials,verification,symbol-agreement.json,anchor-agreement.json,proof-query-examples.json,run.json}`。
输入及原model保持，canonical_model_published=false、runtime_binding=NOT_OBSERVED、runtime_local_layout=NOT_CLAIMED。

## F3-D原引用组合（已按声明范围验收）

类型化组合view复用原B/C1/D/Q/A/T/S，不复制AST、函数体或逐端口闭包。
866/866源码strict fresh通过；563,522端口、392,706源码贡献、208,528原符号及63,315有序参数位置全部闭合，0冲突。
8,375隐式需求中8,182匹配、193按future规则明确省略；6,891个原synthetic header保compiler-only来源。
16进程977.14秒，含Q/S及全部父层重放；七store/原模型不变，仅输出773,329 bytes验收summary。
两族查询9.56秒、唯一存储集成6.92秒通过；真实材料查询2.99秒验证DIRECT/COPY/KEEP、参数及原Fact DAG。
预算前沿最多一条且带remaining；KEEP不授flags因果，DELETE仍可沿先前投影到原符号。
规则域与实例域分别验收：真实DELETE/grammar/detached-super为0，正例来自micro；synthetic .0没有原B端口，SKIP边仍保原编译表，不补造源码入口。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f3d/{fresh/result.json,formal-contract.json,unit-check.json,integration-check.json,query-examples.json}`。
canonical_model_published=false；原目录只读，材料与当前源码缓冲尚未同步到主工作区。

## F4-A结构类型域（已验收；F4整体未完成）

输入按13官方ASDL域闭合113构造/484槽，保原F3-B规则引用；输出按canonical late-bind闭合205记录/733字段、18 ID、60枚举/313成员、75有序union。
可达Any/object/未解类型为0；RECORD/ENUM/ID严格登记，伪造枚举成员、ID payload/prefix、未登记子类均拒；类型递归与值循环分开。
新`program-types`导出两份共享目录共27,315压缩bytes；采集0.089秒、最终fresh读取0.168秒，输入保持，仅写新验收summary。
输入2例0.66秒、目标两族1.27秒、唯一目录集成2.06秒通过；预算用惰性遍历，不先铺满大tuple。
证据：`/var/tmp/scar-f2-recovery-7w7nd_0z/f4a/{materials,verification,source-unit-check.json,target-unit-check.json,material-unit-check.json}`。
仅证明结构域与本层形状/构造规则；未证明opcode/效果、CFG或全部source lowering。没有运行LeWM或改原图。

## 下一层：F4-B产生规则

先统一操作家族、参数化签名和源码原引用：现core只有label/Behavior，操作语义还散在32源码Opcode、88 PythonProtocol及typed侧表。
已实证旧generic校验能接受ADD的0/1/3输入且无result（不声称可绕过完整source replay）；label还有cleanup/class/native实际派发消费者，须显式分离。
旧prepare_source会重parse并按name+line合scope，不能作为新F4权威；迁移时必须消费F2/F3原材料与ID。
先完成这些形式产生规则，再在F4-C生成/逐项验收共享图；不新增detector、backend或程序变换。

## 当前模型与已有后层证据

`artifacts/current/static/manifest.json` SHA-256：
`f1c5834c5e0fc115954f87dc77fa4f0d2be55788e920bcdbbbfa64842bf7bb1e`。
24264个压缩分片、2,579,129,690 bytes；包含材料、索引和诊断，不能全算实现图。
规范主体仍8098个、1,264,142操作；无图诊断与未展开声明继续单列。
旧CALL/class/import关系仍仅覆盖原basis，F0/F1/F2追加不能升级这些覆盖范围。

先前保存的CEM probe（人工quadratic cost、2轮×4候选）已有81次CALL、9条Python返回、580条双向核查边；
不是完整模型或episode。证据在`artifacts/current/queries/lewm-native-callables/graph-cleanup-returns/validation.json`，
属于F0追加前的局部运行对应，不能作为当前形式前端的验收结果。
待前层通过后，再继续组合控制、generator创建/恢复、native/runtime/kernel及状态/资源连接；
不做化简、backend扩展或目标改写，也没有LeWM加速比结论。

当前/home仍只读；同一main通过/var/tmp临时Git索引、对象库和少量变更源码缓冲继续开发。
本地HEAD/index仍在f4cc1afc；恢复可写后先核原hash，再同步缓冲与文档、注册材料；不覆盖用户更改。

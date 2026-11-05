# 当前状态

**第一阶段未完成。F0/F1/F2、F3各子层及组合、F4-A及全域模板接口已按声明范围验收；F4-C正常路径图、F5跨函数/展开参数/容器及名字空间关系已生成并核查；原生生成接口已接通到算子声明；继续补硬件资源图及未覆盖的外部接口。**
按用户最新要求，本轮优先LeWM正常成功运行；应用报错、异常展开及引用清理细节暂不作为推进门槛。
范围为CPython 3.14.7、866份声明源码及其原收据；编译器材料另固定analysis hash seed=0。
这不证明依赖发现完整、运行对象绑定已观察或最终执行图已闭合。阶段契约见[ARCHITECTURE](ARCHITECTURE.md)。

## 实现与历史验收

下表证据已核实存在。`R`为`/var/tmp/scar-f2-recovery-7w7nd_0z/`；秒数为采集/独立fresh核验。
F3耗时包含其声明的父层重放，不能相加当作单次建图时间。各层计数保留各自类型与分母。

| 层 | 已验收的机械输出 | 秒数 | 证据（相对R） |
|---|---|---:|---|
| F0 材料 | 866份、12,655,117原始bytes；编码/错误与精确还原 | 38.72 / 4.72 | 当前目录`formal-frontend-f0/` |
| F1 词法 | 1,961,177个token；全字段、exact_type、换行/gap与真实EOF | 44.41 / 109.73 | 当前目录`formal-frontend-f1/` |
| F2 语法 | 1,511,372个occurrence；2,551,189个field及3,931,984个attribute槽 | 110.91 / 157.32 | `run.json`、`verification/result.json` |
| F3-A compiler材料 | 40,411个scope、208,528个symbol；原序参数/flags与child引用 | 162.00 / 162.33 | `f3a/{run.json,verification/result.json}` |
| F3-B 字段角色 | 484条共享规则；6,483,173槽、563,522个稀疏port逐项闭合 | 167.00 / 170.78 | `f3b/{run.json,verification/result.json}` |
| F3-C1 源码上下文 | 33,752个source scope、65,171个region、94,813条边界 | 262.13 / 266.26 | `f3c1/{run.json,verification/result.json}` |
| F3-C2a 声明账本 | 72,731个名字键、392,706条贡献；全部原port有disposition | 358.73 / 368.58 | `f3c2a/{run.json,verification/result.json}` |
| F3-C2b namespace/捕获 | 83,117个binding、112,631个环境接口、10,224项捕获需求 | 473.15 / 479.73 | `f3c2b/{run.json,verification/result.json}` |
| F3-C3T compiler拓扑 | 44,032个模板与40,411个公开行；原scope/region及父子边对账 | 506.00 / 506.91 | `f3c3/{run.json,verification/result.json}` |
| F3-C3S 符号来源/参数 | 433,867个fact；208,528个原symbol与63,315个参数位置一致 | 638.22 / 643.98 | `f3c3s/{run.json,verification/result.json}` |
| F3-D 原引用组合 | 866/866 VERIFIED；全部port、源码贡献、原symbol/参数闭合，冲突0 | — / 977.14 | `f3d/{fresh/result.json,formal-contract.json}` |
| F4-A 结构类型域 | 205记录/733字段、18 ID、60枚举/313成员、75有序union | 0.089 / 0.168 | `f4a/{materials,verification}/result.json` |

F0/F1当前目录为`artifacts/current/queries/`下的同名目录。
F2保缺失/显式None/空列表、列表None空洞及精确IEEE/complex/bytes/代理码点；存表可还原官方AST。
113个constructor、196个field及288个attribute槽的339种合成形态与实际源码101种constructor分别计数。
F3各子层的866份材料均有fresh结果；F3-D正式契约已accepted，不能把已实现的绑定工作退回“尚未开发”。
F3-D的8,375项隐式需求中8,182匹配、193按future规则省略；合成header仍保compiler-only来源。
F4-A仅验结构类型域：可达Any/object/未解类型为0；没有据此宣布opcode、效果、CFG或全部lowering闭合。

实例与规则域分别验收：真实DELETE等零观察项有独立micro正例；单例operator仍按语法occurrence区分。
只做静态官方ONLY_AST/compiler材料分析，不执行LeWM、目标bytecode或Tensor数值采集。
语法成功不等于scope合法；F3条件化namespace不是已观测的runtime对象、地址或co_varnames布局。
旧ast.walk ID与新F2局部ID保持原域，不因parser参数不同而静默重排或按name/line接线。

## 恢复、同步与当前存储

SSH推送已恢复，本轮已验收实现已同步至GitHub `main`。

`/home`已恢复可写；只读期间的源码缓冲已取回并入当前唯一工作区，合并后的相关回归已通过。
F3七层材料已正式登记到当前模型：6,062个unit片及6个共享catalog，原字节共69,243,786 bytes。
固定原F3-D验收SHA，核七层报告/DTO/父链与当前profile后复用；没有伪称本轮重新执行全量语义。
本次登记659.93秒，包含串行typed预检和七次持久发布；8个copy线程不代表预检已并行化。
去掉新增收据可精确重建原manifest，所有旧字段/ID/片收据不变。正常strict reader保持，原R材料仍作为历史依据保留。
真实eval.py仅从canonical的10份材料strict查询成功：419ports、89native symbols、0conflicts，8.21秒。
集成还验证隐藏七个外部store后可独立查询；登记来源`HISTORICAL_FRESH_ACCEPTANCE_REUSE`不扩大证明范围。
登记/原组合/持久性共8项相关检查通过（15.69秒）；拒绝错pin、输入/profile/catalog漂移、伪预算完成和既有目标冲突。
证据：`artifacts/current/queries/frontend-registration/{publication/result.json,preservation.json,canonical-query.json}`。
F4-A共享类型目录已恢复到`artifacts/current/type-grammars/`，重新fresh读回一致（0.184秒）。

最初发现manifest、F2报告及2个F2分片为空；两片已从原F0/F1重建，F2本轮全量fresh重验155.21秒。
同轮F0/F1/F2及持久性20项检查通过（7.08秒），包含独立字段核对和发布故障注入。
合并远端后，F3材料/组合与持久性10项集成检查通过（29.08秒）；F2/F3-A reader六项检查另通过。
随后在`R/syntax-materials.tar.gz`找到完整manifest，已按原SHA精确恢复全部metadata及CALL/class发布范围。
恢复时manifest SHA-256：`f1c5834c5e0fc115954f87dc77fa4f0d2be55788e920bcdbbbfa64842bf7bb1e`。
其866份F0/F1/F2收据与本轮fresh输入逐一一致；恢复过程未改原source/body ID或原关系的证据范围。

恢复收据：`artifacts/current/queries/formal-frontend-f2/recovery/exact-restoration.json`。
中间的投影恢复及query-metadata bridge已由精确恢复取代；不得继续描述为原metadata永久丢失或原CALL/class未恢复。
F0/F1/F2发布已补文件/目录/manifest fsync、完整报告发布与故障边界检查；两次目录rename之间仍有可恢复窗口。

当前manifest SHA-256：`601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0`。
当前30,332个压缩分片、2,648,373,476 bytes；包括材料、诊断、局部图与关系，不能全算实现图。
核心body：局部图8,098；未尝试23,645；入口适配缺失4,200；不支持326；形状不支持437。
13,108个原核心分片的长度/SHA一致；36,706个lexical entry与body entry_key逐项一致。
历史关系仍限定原basis；形式层追加或材料注册不能自动扩大其授权范围。

## 下一层与整个第一阶段缺口

F4-B1已验收有限端口代数：六种pattern、四种显式参数、五类原ground type及ordinary/invoke两种形式。
所有选择分支先静态核验；空重复不展开、非空重复先核大小；接口匹配沿原Use和完成边，不依赖label。
8项针对性检查通过（0.51秒），原canonical类型目录2项通过（1.31秒）；未改原类型根或graph wire。
真实LeWM `get_dataset`的66操作原片已读回，核其中1个typed TRUTH接口，错误normal结果类型准确拒绝。
这是端口形状查询，不是完整家族或源码证明；其状态参数仍为显式原域，未完成参数来源授权。
证据：`artifacts/current/queries/operation-signatures/{result.json,lewm-port-query.json}`。

F4-B2已接入完整PythonProtocol声明域：67 invoke、19 ordinary、2 opaque明确拒绝；共享压缩目录3,739 bytes。
新增按原OperationID选择规则的上下文索引，自动绑定入口world、区域异常ABI、unpack/slice与部分frame参数，并核原状态连线。
保留comprehension两套输入顺序及子lambda/generator的raw ABI；不按实际arity反推参数，不把BOUND_FRAME混入structured协议域。
17项针对性检查通过（1.85秒）。4个LeWM原函数片（含CEM solve）中728项协议全部自动匹配；未匹配0，无端口冲突。
frame退出向量从原UseSource组和ValueSource.slot解析，再独立核UseID顺序；CONTROL角色的合流token仍保绑定类型。
call/map/string/assert参数也沿闭合原端口组解析；空组保DECLARED_EMPTY_GROUP，未伪造源码空参数证明。
这只证明声明一致，不证明保活集合完整。4片共1,609个操作，本轮只核其中728项协议；读取/旧图验证/查询10.93秒。
这不是全程序建图或LeWM运行时间。仍需核其余core/control家族，不能用协议覆盖率代替全程序覆盖率。
该查询不重放源码产生规则、不授权源码/效果/变换；canonical图/manifest保持，第一阶段仍未完成。
证据：`artifacts/current/queries/protocol-signatures/{result.json,lewm-queries.json,catalog.json.gz}`。

源码身份层已全域验收：866份原F2（1,511,372 occurrence），849个旧SG的892,364个Atom全部精确对应；17份无旧SG输入单独保留。
不改旧ID，不按name/line配对；BFS只重放身份。采集288.80秒、独立fresh307.25秒（8进程），失败0；849片共25,910,730 bytes。
本轮核心/CLI/批量读写由主代理实现；仅保留一个代理做独立测试。6项身份反例及1项source-only集成检查通过（2.07秒）。
真实eval/cem原body的4,830条操作来源、65,086条来源引用已接回原F2及已有F3查询；CEM的4个旧OPAQUE可读出Gt/Eq原selector。
这仍不是执行语义证明。证据：`artifacts/current/queries/source-anchors/{materials,verification}/result.json`及`{eval,cem}-origin-query.json`。

源码产生规则当前v25：126记录/362字段、4 ID、33枚举/264成员、29 union、69步骤变体；与canonical图分开。
113个构造器已分派为28表达式、28语句、3执行根、21父属描述符、32 selector及1非执行FunctionType。
构造分派不等于所有用途、上下文、效果或最终图闭合。现在只从原F2/F3材料生成局部recipe，保持原ID和输入manifest。

共享的参数化编译上下文接口继续保留：每个区域有端口，入口边按step ID与类型字段/tuple序号定位；
区分调用、子表达式、代码声明、类型工厂、循环条件/正文/退出、完成处理和恢复。
不同调用位置仍指向同一共享模板；声明不执行正文，循环不按迭代展开。
源matcher从原F2/F3重建整表，拒绝缺表、漏边、错目标、错代码环境和遗漏fact use。
内联scope保原源码身份并共享外层code owner，延迟入口另接自己的环境。
这是F4-B接口接线，不是native调用上下文实例化，也不是canonical CFG/SSA。

本轮补核心签名：源码recipe强制声明抽象world和异常ABI，检查EvaluateChild、语言操作、名字访问、值构造及隐式literal五类步骤。
调用/类构造参数、解包结果、slice可选项和tuple布局数目从原F2推导，固定端口另作shape检查；不从现有arity倒推参数。
9份源码共有12,867处core签名检查。无profile样本只授结构证明；源码入口拒绝缺profile、错ABI、缺操作数及错源码数目。
模板字符串的strings/interpolations tuple现已分开；未有源码产生规则的预留枚举拒绝放行。完整效果、清理和native准入仍未证明。

九份真实源码重生成并独立fresh逐记录一致；五源为eval、cem、buffer、world、spaces，另含policy、format、envs/utils和外部callbacks/registry。
本轮各域结果如下，秒数包含父层strict重验，不能当作LeWM运行或完整建图耗时：

| 材料域 | 原域及局部recipe | 采集/fresh秒 | 压缩bytes |
|---|---|---|---|
| 五源语句 | 998语句，915局部+83父属，199条件模板 | 29.00 / 28.34 | 1,178,543 |
| 五源表达式 | 5,314表达式，4,875局部+345抑制+94父属，29条件模板 | 36.55 / 36.13 | 1,704,675 |
| 五源根 | 5根recipe，72项子接口义务 | 24.19 / 24.17 | 18,001 |
| policy语句 | 226语句，201局部+25父属，53条件模板 | 21.29 / 21.32 | 267,188 |
| format语句 | 52语句，47局部+5父属，5条件模板 | 5.38 / 5.27 | 80,190 |
| utils/registry语句 | 193语句，181局部+12父属，16条件模板 | 13.67 / 13.65 | 247,298 |

这六组材料共有8,722个区域上下文端口、9,306条入口边、40项编译事实使用；共享边是静态引用，不是动态调用计数。
入口边中7,110条仍是外部子模板接口，不表示已经完成全图组合；其余含1,327调用、345代码声明、183完成处理、86循环正文、84循环条件、149循环退出、22恢复边。
九源未出现类型工厂入口，泛型factory的直接依据来自静态micro；普通finally的多调用共享同样由micro验收，不冒称真实九源出现。
原代码注解登记仍有15个已证producer上下文，可按代码版本/常量路径/偏移绑定；从caller到具体native路径的传播仍未获证。
材料gzip流共3,495,895 bytes，解压69,838,355 bytes；不含catalog/收据或原模型，不能当成整个程序图大小。
19份展示recipe均由v25新材料提取，不改旧header冒充迁移。验收外壳已精简，详细计数直接引用materials/verification结果。
证据：`queries/source-{productions,expression-rules,statement-rules,root-rules,scope-annotations,annotation-state,compilation-contexts}/`。

此前4项定向检查，85.14秒：结构/strict wire、core参数反例、全部局部表达式家族、共享入口与代码边界；未跑整套。
覆盖缺操作数、缺profile、错ABI、错误源码参数计数、错tuple布局拒绝，以及原九类入口规则。
九源材料另经独立fresh验收；源bytes与manifest保持。866源初次扩展扫描已为已定位的接口缺口主动中止，未验收部分流已删除，诊断留在`queries/source-statement-full/result.json`。本轮没有执行或修改LeWM，没有新增subagents。

全语料扩展：当前生成器的866源语句采集及独立fresh均通过，149,848语句=141,185局部recipe+8,663父属，另28,849条件模板，规则前沿0；1,740.89/1,148.37秒，170,946,339压缩bytes。证据在`queries/source-statement-full/{materials,verification}/result.json`。语料为849份.py与17份.pyi，不能把类型声明当成已绑定的运行实现。
当前生成器的866源表达式采集及独立fresh均通过：741,076表达式=709,740局部+13,668抑制+17,668父属，另1,901条件模板，规则前沿0；2,012.94/1,373.79秒，238,480,316压缩bytes（解压5,514,025,618）。三域当前材料均已验收。
全域模板接口已接通并发布：866源、882,537个共享模板、889,242条子接口，32进程707.80秒，图表84,464,265压缩bytes（不含原模型及父recipe正文）。实参与形参、完成出口、逻辑编译环境及局部state顺序均由接线器检查；这不是运行时函数调用绑定、canonical CFG/SSA或第一阶段完成。证据为`queries/source-template-links-full/result.json`。
强类型图读取器另核当前类型/协议目录与编译器参数，阻止只有父报告自洽却与当前声明漂移的材料；3项定向检查通过（9.53秒）。全866源图表经16进程独立读回，60.24秒，核哈希、计数、原输入/profile及模板引用闭合，见`reader-verification.json`；未重新授予源码语义证明。临时副本中的压缩损坏、悬空callee及异域state profile均拒绝，见`reader-integrity.json`。eval入口与CEM循环已按原ID展开，见`body-expansion.json`。这些证据均在`queries/source-template-links-full/`；原接线报告/图表不改写成新reader版本，新增收据保留各自实现SHA。
新增独立的F4-B模板接口层，五份完整三域材料连接6,023个模板、6,046条子接口；实参与形参、完成出口及逻辑编译环境逐项一致。按源文件保存模板表与绑定表，正文由父材料展开。定向检查1项通过（5.16秒），覆盖不同purpose、缺目标拒绝、冲突模板拒绝及strict codec；这不是canonical图或完整子图语义证明。
接口接线按源spawn并行，worker只有各自的只读父索引和本源输出；新增局部world顺序约束，包含内嵌调用，拒绝类型相同但来源过时的state，并禁止循环state作不变量。两项定向检查通过（7.61秒）；当前五源双进程复跑43.61秒，5个header及10个数据分片与上一版逐字节一致，见`queries/source-template-links/verification.json`。五源诊断涉及7,580区域、22,724步骤、22,905项state使用及73个循环模板，未发现旧state输入；不据此证明全部参数来源、native效果或引用清理。采集生成器指纹不变，时间不是LeWM运行或加速比。
按原解压大小自动选择的最大根模板也通过局部state顺序检查：11,451区域、54,623步骤，62.23秒，见`queries/source-root-full/state-sequence.json`。这是cv2类型声明材料，不是已准入的运行实现。

**当前真正缺口及顺序**：

1. **F4-B当前正常路径基础已具备**：全域模板、参数接口及局部state连线已接通；完整异常/引用清理移至后续，不再阻塞本轮。
   shape遍历预算已接入三类规则、CLI、材料limits及模板读取；跨进程错误保留类型、字段、备注和源路径。3项定向检查通过（8.45秒），覆盖精确预算边界与spawn后进程池继续可用。九源现已重新生成并独立fresh通过，接口计数及recipe wire不变。新版全域根入口已完成866源采集及独立fresh：1,054.19/1,287.06秒，866个根模板、规则前沿0，7,451,855压缩bytes（解压177,809,003）。显式visits预算为20,000,000；证据在`queries/source-root-full/{materials,verification}/result.json`。新版全域语句、表达式也已正式验收。
   全语料模板接口接线及图表读回已完成（包含局部state顺序约束）；源码recipe wire仍为v25，旧材料不改header冒充迁移。
   已有引用清理诊断保留作后续依据，本轮不继续展开。应用异常不在当前NORMAL_SUCCESS契约内，不能据此授权保持异常行为的程序变换。
   当前上下文表解决了入口接口的显式表达，不替代native路径实例化、frame布局、调用准入和完整效果证明。
   原协议查询覆盖的728项仍仅限其声明范围；core/control家族、版本化根和强制reader仍需接完。
   每批沿“类型/接口→原字段规则→独立重放”推进，不以九源规则前沿0宣布全层完备。
2. **F4-C正常路径边表已实现**：以既有SourceProductionPlan的操作/区域作节点，只新增有类型的控制、数据、状态及声明边索引；不复制另一套指令或函数正文。
   调用/返回边用原步骤及字段路径配对；循环状态通过回边接区域参数，不按迭代unroll。函数声明不执行其body，挂起恢复用独立transition表示。
   `python -B -m scar.analysis.normal_graph --templates SOURCE_TEMPLATE_STORE --out FRESH_OUT --jobs 16`生成；`read_normal_edges(store, unit)`读回。默认全域，可用`--source PATH`选择输入；核心无LeWM名称规则。已有N1扁平IR适配不作为这份层次图的前置条件。
   正常路径边语法为9记录/28字段、4 ID、9枚举/43成员、9 union。五源已生成并读回：22,724操作、73循环；7,340个调用/恢复入口及19,834条返回关系配对通过，79条state回边及782条分支守卫已核。证据在`queries/normal-graph-five/`。
   LeWM目录内全部582份声明源码已生成正常路径图：457,866模板、553,118区域、1,661,663操作、2,308循环，16进程596.62秒。边表为4,946,837控制、2,666,942数据、4,331,137状态、10,763声明，压缩285,025,448 bytes；全部分片header/压缩哈希及汇总计数已核，见`queries/normal-graph-project/{result,publication}.json`。这些是静态操作而非动态执行次数；原操作正文仍共享在父材料中，不含原模型/父材料空间，也不是LeWM运行时间。
3. **F5当前接线实现已全量传播并可查询**：849份运行.py，17份.pyi不冒充运行实现。当前事实schema v3，包含80,761调用点、28,134容器、26,165下标访问、6,346更新及8,712迭代接口；24进程重建191.35秒，见`queries/normal-link-facts-containers/result.json`。原SourceProductionPlan及ID不变。
   当前结果schema v4：52,382个调用有可能目标、18,611个有源码目标、63,501条调用连接、9,504条可能内容边及43,415条名字空间查找关系；传播276.54秒、队列前沿0。28,379个调用仍无目标，不能将固定点当完整分派覆盖。证据为`queries/normal-targets-namespaces/result.json`。
   内容边只传可能的引用，保留下标访问的输入/输出world，明确FLOW_INSENSITIVE_MAY_CONTENT，不证明数据不变或缓存合法。函数环境是投影，STATE是因果依赖。支持原构造容器、已知键、复制/追加、迭代、固定解包及globals映射；自定义getitem不冒充内建容器语义。展开参数仍保留实际包端口，不捏造包内容或包到形参的别名。
   名字空间关系连接原接收者/结果端口、名字、原模块及开放绑定；2,031项导入模块候选来自原F2，标准导入条件下可接编译子模块边界，不以是否有.py主体决定该节点是否存在。空的源码值集表示绑定仍待接口提供方，不表示成员不存在；binding_proven保持False。实现为`normal_namespaces`，没有LeWM特例。
   LeWM四源267条调用连接、22条内容边及169条名字空间关系经类型读回和分片收据核验，15.79秒；CEM的torch.randn/ones/cat/topk已连到原torch名字空间/源码端口，源码绑定值仍为0。证据为同目录`verification.json`；这些仍是静态可能关系，不是实际kernel、transfer、alias或效果证明。
   `NormalCallGraph.calls/contents/namespace_lookups/expand`只读原图及共享body。下一项：复用安装版native声明和Python绑定生成规则，接通原生导出、参数规范化、schema/dispatch及资源要求；不靠同名硬接ATen，不把dispatch候选或.to()当已发生的kernel/拷贝。应用异常和引用清理暂不阻塞本轮。

4. **生成式算子接口已接入原图**：隔离torchgen工具恢复2,839绑定、1,703完整导出族/wrapper（含62个deprecated绑定），不import torch或执行LeWM。不是按函数同名推断；Python parser、C++转换、ATen schema保持不同端口和分支。全域生成7,912条名字空间接口关系；源引用经过原alias/name/参数/返回/容器传播，2,732个源调用点产生8,667条有条件的原生接口候选，422份canonical NativeBoundary、5,328条声明转换依赖，250.89秒。证据在`queries/python-bindings-full/{result,verification}.json`。
   原调用ABI（包括无已知目标的调用）可经`NormalCallGraph.call_sites`读取；实际候选保留positional/keywords/包/result及输入/输出world。全2,839定义类型读回，LeWM四源逐项核原调用ABI，通用赋值别名传播、factory/options/out/多返回接口及按binding过滤查询已核，6.97秒。CEM的7个调用点已有19个生成接口候选；未证明namespace当前绑定、实际重载、override是否分流、alias或完整效果，不作执行次数/加速比结论。
   资源层新增763个资源/状态相关schema输入和575个dispatch声明，按422个NativeBoundary机械投影，7.87秒。Optional/List只保类型路径，不展开为资源实例；Device/Tensor/Generator类型不证明实际消费，CUDA key不证明GPU执行或copy。证据为`queries/native-resource-declarations/result.json`。没有创建无条件ResourceUse或物理资源实例。
   按用户最新边界，软件展开至算子/外部动作接口；保留调用转换/状态契约，不再继续拆CPython解释器及kernel内部。下一项集中在目标硬件图、资源容量/连接约束、状态/数据生命周期与软件区域的完整关联，以及生成器之外的Python/NumPy/文件/环境接口。第一阶段完成前不实现图化简或codegen runtime。
   后端设计已固定为C++20，算子ABI v1、执行计划schema v1；本机GCC 13.3.0，安装Torch CMake target声明CXX_STANDARD 20，ATen/torch/library头文件编译期语法核验通过。仅编译，不链接/运行目标；证据为`queries/cpp-target/result.json`。

第一阶段仍未完成；当前不扩detector/backend、不变换程序，没有完整LeWM episode优化或加速比结论。

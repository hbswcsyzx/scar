# 当前状态

**第一阶段未完成。F0/F1/F2、F3各子层及组合、F4-A已按声明范围验收；当前下一层是F4-B操作签名与产生规则。**
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

全语料扩展：866源语句采集及独立fresh均通过，149,848语句=141,185局部recipe+8,663父属，另28,849条件模板，规则前沿0；906.01/1,330.21秒，170,946,339压缩bytes。证据在`queries/source-statement-full/{materials,verification}/result.json`。语料为849份.py与17份.pyi，不能把类型声明当成已绑定的运行实现。
866源表达式已采集：741,076表达式=709,740局部+13,668抑制+17,668父属，另1,901条件模板，规则前沿0，1,727.12秒；独立fresh尚未完成。全量根入口未通过：cv2大型根模板超过默认一百万次shape遍历预算，跨进程异常的pickle又遮住了原错误。已用原类型材料作只读诊断取回BUDGET_FRONTIER；该诊断不授新的上游fresh证明，见`queries/source-root-full/serial-diagnostic.json`。
新增独立的F4-B模板接口层，五份完整三域材料连接6,023个模板、6,046条子接口；实参与形参、完成出口及逻辑编译环境逐项一致。按源文件保存模板表与绑定表，正文由父材料展开。定向检查1项通过（5.16秒），覆盖不同purpose、缺目标拒绝、冲突模板拒绝及strict codec；这不是canonical图或完整子图语义证明。
接口接线现支持按源spawn并行，worker只有各自的只读父索引和本源输出；五源双进程运行87.95秒，5个header及10个数据分片与串行结果逐字节一致，2次原正文展开通过。证据为`queries/source-template-links/parallel-verification.json`；没有据此报告LeWM加速比，也未改变采集生成器指纹。

**当前真正缺口及顺序**：

1. **继续F4-B**：闭合参数和状态来源、正常/异常引用清理，以及完整操作家族的源码产生规则。
   shape遍历预算已接入三类规则、CLI、材料limits及模板读取；跨进程错误保留类型、字段、备注和源路径。3项定向检查通过（8.45秒），覆盖精确预算边界与spawn后进程池继续可用。九源现已重新生成并独立fresh通过，接口计数及recipe wire不变。cv2只读诊断已通过20,000,000预算：11,451区域、54,623步骤、3,166,165次shape遍历，100.16秒；未重放上游全部语义，不能替代正式验收。全域根入口正以显式预算重新采集/fresh；全域旧证据仍限定其原生成器指纹。
   随后恢复全量根入口验收、全量表达式fresh与全语料接口接线。recipe wire仍为v25，预算/错误传输的实现指纹已更新；旧材料不改header冒充迁移。
   当前上下文表解决了入口接口的显式表达，不替代native路径实例化、frame布局、调用准入和完整效果证明。
   原协议查询覆盖的728项仍仅限其声明范围；core/control家族、版本化根和强制reader仍需接完。
   每批沿“类型/接口→原字段规则→独立重放”推进，不以九源规则前沿0宣布全层完备。
2. **F4-C**：在F4-B闭合后生成统一共享CFG/SSA，明确控制、数据、状态及各类完成端口。
   函数/循环可展开但共享模板，不按执行次数unroll；不重parse或按name/line猜接原scope。
3. **F5/F6**：接跨子图、native/runtime/kernel及可影响执行的资源依赖，再核依赖发现前沿和全程序覆盖。

第一阶段仍未完成；当前不扩detector/backend、不变换程序，没有完整LeWM episode优化或加速比结论。

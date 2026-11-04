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

源码产生规则v13的输入语法已落地：86记录/233字段、4 ID、20枚举/219成员、20 union、50步骤变体；不修改canonical类型根和旧ID。instruction标签由全部variant自动生成，create/set/bind等同字段形状不会在wire中混淆。
检查exact类型、区域归属/值顺序、共享调用、循环不变量/携带接口、异常完成到handler的payload/captures连接及strict codec；不授完整控制/效果语义。
暂停接口子门已通过：明确handoff、normal/raise两种后续入口、异常ABI及保存引用；禁止保存旧STATE，核恢复完成并集。12项语法/接口检查通过（3.41秒）；driver/frame/context适配尚未证明。
委托/循环接口子门14项检查通过（3.65秒）：4种运行时协议强制核签名，await/yield-from必须具备delegate，普通yield不得带delegate；循环保持全部escaping completion。RepeatCondition不造求值工作，空完成接口不造返回边。
惰性入口的类型/局部接口及原F3桥已核验：代码声明不执行body或保存旧world，后续入口必须先激活环境并按原序接收已准入参数。参数使用声明/resolution而非write_target；活跃转交路径包含仅为内层转交的cell，初始默认值显式接原表达式。v3材料已以v4重采集和fresh核验，不是自动升级。
异步接口子门15项检查通过（3.74秒）：共7种有限协议及两种异常ABI；新增异步iterator获取、已取得的await iterator推进及StopAsyncIteration匹配，尚不授driver/native展开证明。
原结构验收25项通过；本轮修正区域出口汇总：前面步骤的异常必须保留，不能只取最后一步的normal结果。
真实eval/CEM核419/537项原role引用描述符，查询1.03/1.31秒（父层fresh及索引另9.76/12.12秒）；没有生成新执行图或重放逐构造规则。
记录在`artifacts/current/queries/source-productions/`；旧manifest不变，LeWM未执行或修改。

F4-B现有28类表达式局部规则，async clause及异步GeneratorExp已接入共享await推进和正确耗尽/导出路径；规则内核直接消费原F2/F3，strict读取重放父层，不执行目标。
规则目录对113构造分流：28类局部规则、11类父上下文描述符、32类selector metadata、42类规则前沿；新增ExceptHandler父属描述，不授全构造/全部上下文闭合。
真实eval/CEM及buffer/world/spaces五份源码共5,314个表达式：4,879个局部recipe、345个已知不单独求值的源码、90个父属表达式、表达式规则前沿0，分区精确闭合；另记733个父属描述符，含79个声明docstring Constant、113个arguments、303个arg、4个withitem及4个ExceptHandler等。函数docstring由创建metadata拥有，类docstring由namespace初始化拥有；6个增强赋值target仍由父语句安排读/改/写，没有丢弃源码。
4处Lambda、3处GeneratorExp及先前6处Yield/2处YieldFrom均有规则。仍有3,483项child接口义务，不能以局部规则代替完整图。Await及异步上下文在静态micro源码中检验；未声称LeWM样本出现了Await。
345处SUPPRESSED_SOURCE主要来自future注解，材料v2保留原C1原因/槽并单独计数；它们不是缺失规则。该分类由真实样本发现后修正，未丢弃原源码。
表达式5个流式压缩片共1,472,008 bytes（解压32,888,820）；5进程采集32.62秒、独立fresh32.48秒，见`queries/source-expression-rules/{materials,verification}/result.json`。
本轮只做3项接口/wire/共享调用检查（0.77秒）与2项try/with专项（13.34秒），含两种异常ABI与静态compile/dis对照；未重跑整套。主要验收仍是原材料生成和独立重放。全部由主代理完成，无新增subagents，未执行目标bytecode。
`source-statements`现为26类局部规则，新增普通Try。按序匹配并恢复异常状态，else异常绕过同级handler；异常名的None写入/删除沿原声明授权。正常离开handler先恢复再清名，异常离开先清名再恢复。一份SHARED finalbody接受各pending路径，正常保留原完成、异常/return/跳转覆盖它；共享调用必须同activation/namespace并显式传参。编译器提供的字面常量已去除伪异常边，裸return不多出RAISE。class namespace内部操作、native frame/清理及lazy body仍未证明。
真实五源998个语句分为919个局部recipe、79个父属docstring Expr、0个语句规则frontier，另有2,199项child接口义务。新增4个Try recipe；保3个With、8个ClassDef、109个函数定义及98个annotation factory。Try模板含4次type match、4次异常安装、13次恢复及12次保存异常的重抛准备；这些是静态模板步骤，不是执行次数。
语句5片共675,625 bytes（解压13,252,480）；5进程采集26.73秒、fresh26.39秒。样本没有finally、命名handler、AsyncWith、泛型或TypeAlias，相应规则由静态micro核验。完整分布见`queries/source-statement-rules/result.json`；CEM的try recipe在`queries/source-productions/cem/try-specimen.json`。98个函数注解请求仍是独立child义务。
样本规则缺口0不代表全语言或完整图：TryStar/Match、根入口、child/lazy请求body、状态与引用清理、目标编译选项和native/resource仍待闭合。原manifest与五份源码bytes保持，v13材料已重采集/fresh，未改旧header冒充迁移。
Call的140个原规则前沿已消除；单星、多星、kwargs连续组和大组路径均有规则，复用已有协议强制核签名。未把位置漂移的bytecode当作F2节点身份。
容器更新/分组/哈希时机、解包先于目标写入、f-string转换先于spec、模板捕获不立即转换已有静态对照；implicit literal只描述值，不授对象身份或分配证明。
推导式每子句一份循环模板，外层先求首个iterator、局部scope内赋目标/过滤/求结果；仅advance的StopIteration转为耗尽，body异常保持传播。引用不变不代表内容不变。
recipe不是canonical CFG/SSA；state来源、child实现与effects未证，不能发布全图或开启变换。

1. **F4-B后续规则**：接完整操作家族、typed参数来源、状态/access契约和源码产生规则，再接版本化根与强制reader。
   旧core操作语义仍散在32个源码Opcode、88个PythonProtocol及typed侧表；label还承担cleanup/class/native派发。
   旧通用结构校验可容纳ADD的0/1/3输入或缺result，说明缺少统一签名；这不代表可绕过完整source replay。
   三种域不能互代：32 Opcode、88协议和113语法构造器×上下文分别核验；B1不授新图发布或优化。
   下一步将原声明端口接到F2/F3产生规则，并补function/class/comprehension等参数来源；保活完整性另验，不能抄端口来证明。
   形式顺序：输入/输出结构已固定；当前持续闭合构造×用途×上下文的字段消耗及完成端口，再重放核验，全部闭合后才生成CFG/SSA。
   普通Try等26类语句已有局部规则。接下来仍在F4-B：①TryStar异常组拆分/合并及Match模式规则；②根入口、lazy请求和class namespace内部操作；③参数来源和正常/异常引用清理闭合。不能以五源语句frontier0代替全层完备。每批保持“接口→原字段产生规则→独立重放”，全部闭合后才进F4-C；调用准入、闭包/native布局及driver/frame/context合同仍须接通。
   四片其余881操作已分类为控制434、binding246、source invoke201；这是识别结果，不等于其接口/产生规则已通过。
   签名witness仍须进入版本化typed根及强制reader；不能把本层独立查询当作完备。根扩展后重验F4-A目录。
   实读FRAME_BIND为READ_WRITE、UNKNOWN footprint、非full overwrite；不能照旧审计摘要强制WHOLE或升级未知事实。
2. **F4-C规范共享图**：消费已验F2/F3原材料与ID，生成并逐项验收控制、状态、效果和完成端口。
   旧prepare_source重parse及按name/line合scope的路径不能作为新F4权威；函数/循环保可展开共享区域，不按迭代unroll。
3. **F5/F6**：接通跨子图、native/runtime/kernel、资源与数据来源；重新核依赖发现前沿和完整覆盖。

LeWM仍是外部testcase。已有CEM probe仅人工quadratic cost、2轮×4候选的局部运行证据；
当前不做detector/backend扩展或程序变换，没有完整episode优化或LeWM加速比结论。

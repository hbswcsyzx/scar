# SCAR 宏观编译器架构

第一阶段只完成程序建模与建图；化简、改写和性能优化在后续阶段。
实体和关系定义见 [MODEL](MODEL.md)，实测范围与剩余缺口见 [STATUS](STATUS.md)。
LeWM 是外部 testcase；通用规则由语言协议、原端口和证据派发，不按业务名称选择。

## 当前实施顺序

第一阶段按以下五层推进；既有局部原型不代表整层通过。以`run_inference.py`及已存推理配置验收相关依赖；不强求排除孤立文件，也不把一次未执行作为删图依据。

| 层 | 输入→输出 | 验收 |
|---|---|---|
| 1 统一接口 | 已验F4材料/旧core→同一类型化节点、端口及依赖查询 | 身份双向可追；原边/类型/调用路径不丢；不重造指令语言或遍历器 |
| 2 局部状态 | 原控制/名字/效果→局部读写版本与来源 | 循环保共享回边；绑定、对象、内容版本分开；缺规则不冒充UNKNOWN |
| 3 跨层接线 | 原定义及接口→参数/返回/捕获、配置/导入、构造/算子关系 | 每个相关调用有接口或字段级未决目标；新材料先过前两层 |
| 4 资源/事实 | 值/状态/外部动作→设备内存、存储及执行证据 | 读权重/数据、计算、搬运/同步、保存输出接到具体端口；候选与Observed分开 |
| 5 全图验收 | 上述关系→统一分片、查询及覆盖报告 | 正常推理链可追；无漏建构造、无未解释断边或预算截断；动态未知逐字段列出 |

统一接口复用`ProgramDependencyGraph`：F4适配投影到既有类型ID，保原Step/Region/Port和完整G.Edge；旧N1图按原representation路由。`get/expand/producers/consumers/explain`使用同一接口，不伪造canonical正文。
五类实体之外，Use和控制端口是辅助角色：`kind=None`表示“非独立实体”，不是未知节点。操作原始类型仍来自封存的F4 instruction，不能按label猜效果。
②现已把C2绑定、隐式类名字与属性/索引/聚合请求接入统一接口，69种指令的效果请求分类闭合；3单元内容接口与gcrl完整单元的63条自动局部状态链已验。内容状态沿原world投影，尚不授物理槽/逻辑版本或效果闭合。下一步先将已有canonical native单元的类型、world与scoped may-alias声明接入同一局部接口，再补其余namespace并扩入口相关单元；原生声明不是实际写入，跨源调用仍属③。增量不改已验数据时继承精确指纹证明，只核新增关系。
CFG边是CONTROL_FLOW，区别于控制依赖CONTROL；完整CallSite/path及completion保原映射。普通walk不证明调用/返回已匹配或节点实际执行。
每层通过后提交一次；只维护本架构、MODEL与STATUS，不新增逐门文档。后续形式细节是已有材料协议，本轮入口以此表为准。

## 三个主阶段与后端决定

SCAR以Python程序为输入，在统一图上处理程序依赖及硬件映射；不是仅产生源码修改建议的工具。

| 主阶段 | 产物与职责 |
|---|---|
| 1 建图 | 自动建立控制、值、状态、效果及资源图；静态优先，真实未知保留到字段/关系。软件展开至算子/外部动作接口，保留接口转换；不继续展开CPython解释器或算子kernel内部。 |
| 2 化简与规划 | 一类是结构化简：常量传播、无效依赖消除、循环不变量外提、复用等；另一类是hardware-aware：分批/分块、流水、驻留、buffer生命周期、搬运/计算重叠、并发与算子实现选择。两类可迭代影响，均服从Q与资源约束，并以M估价。 |
| 3 落实代码 | 从优化后的执行计划生成C++宿主调度代码，调用算子后端；交付代码/库、计划与必要的Python入口及显式兼容调用。完成正确性验证和独立性能测量。 |

**统一后端为C++20**（`-std=c++20`）；不规划Rust后端。算子插件ABI版本为1，执行计划schema版本为1，
两者独立于C++语言标准管理；版本基线位于`pyproject.toml [tool.scar.codegen]`。
构建时继承现有Torch CMake target的编译/链接ABI，不自行猜测或覆盖`_GLIBCXX_USE_CXX11_ABI`。
第一版优先交付Python可加载的C++库；可完整降低的程序区域后续可形成独立可执行产物。
Python是输入和兼容边界，不承担默认的优化后调度循环；SCAR当前前端用Python实现不改变这个目标。

宏观执行计划显式描述循环、依赖、分块、buffer放置/寿命、队列、异步完成及外部效果顺序。
逻辑batch/候选数量与执行分块分开：物理分块受等价性/RNG/归约契约约束，不能随意更改算法输入规模。
目标资源图包含CPU、DRAM、加速卡及设备内存、磁盘/存储与连接；容量、带宽、延迟及并发约束参与规划。
未知资源属性保留符号量，不根据算子名字猜一次GPU执行或数据搬运。

算子后端采用可注册接口：官方高性能库及外部算子生成agent均可提供单算子、通信算子或融合区域实现。
接口需声明支持的操作/类型/布局/设备、读写/alias/RNG及数值契约、workspace、执行/传输代价与可调用产物。
C++宿主通过版本化C函数表接入插件（仍是C++后端），传递描述符、buffer、stream/event与所有权契约；
不把第三方C++类布局作为长期插件ABI。宏观编译器选择区域边界和调度，算子后端负责区域内部高性能实现。
上述为后续阶段的设计基线；当前不新增优化backend或调度runtime实现。

## 形式阶段与顺序

先验收前层的输入域、全部类型/字段及转换不变量，再开发后层。已有后层原型保留，当前只推进第一阶段；
功能样例通过不能证明前层完备。当前 Python 前端按本机 CPython 3.14.7 的版本化接口核对。

这里的“层”是形式转换，不是功能分组。每层固定为
`L = (输入类型域, 输出类型域, 转换规则, 不变量, 错误域, 资源上限)`：
输入必须来自前层已验材料；合法构造逐类有规则，规则的前提、字段来源和输出引用明确。
输出必须是有效结果、带位置/原因的错误或预算前沿之一；未实现规则不能转成未知值继续放行。
验收分别核对规则域闭合、实例逐项守恒、非法引用/越界/预算拒绝及原输入保持。
实例覆盖不能替代规则覆盖，构造数量相等也不能替代逐字段和逐边核对。
通过只限声明的语言/profile与材料域，不冒称对任意 Python 程序的全部行为已获数学证明。
字段本身运行时不确定仍可保存符号量/UNKNOWN；这与转换规则缺失是不同状态。

F3 内部也遵守这个标准：B 的域是全部484个官方字段槽；C1 是其上下文属性路由；
C2a 是原名字端口的声明归约；C2b 是34条规则与8类环境接口的条件查询；
C3-T 是113类构造/484字段的模板投影；C3-S 是29类原贡献、14类事实和4类变换的求解。
F3-D 只组合原引用：`B端口→D声明/C2b接口→S来源→slot→投影→A原行`，
并独立连接语言隐式需求。COPY传递来源；KEEP_PARENT仅表示保留已有编译槽，不授予flags因果；
DELETE不能抹去先前投影路径；无来源、忽略、脱离及预算停止分别保原因。
它必须核完全部原端口（包括无名字贡献端口）、隐式需求、投影和逆边，再提供有界查询；
保存材料的交叉审计不等于strict fresh组合验收。当前两者已在声明profile与866源范围通过；F4仍须先固定自己的类型与产生规则。


| 阶段 | 封闭输入 → 机械输出 | 验收对象 |
|---|---|---|
| F0 材料 | 原始bytes、来源/版本 → 原字节blob、编码结果或结构化错误 | SHA/长度/精确还原；不调用lexer/parser |
| F1 词法 | F0材料 → 官方全部token字段/exact_type、源码区间与gap、EOF或错误前缀 | 与官方流逐项相等；源码覆盖并集+gap无漏无重分区 |
| F2 语法 | 同源词法输入、固定parser参数 → 完整constructor/有序字段/子节点槽/带类型标量/坐标 | 无损还原官方AST，含None、空列表及字段存在性 |
| F3 绑定 | F2 occurrence及官方symtable → scope树、全部名字来源字段的角色/绑定关系 | 全scope/symbol/namespace链及名字字段分母；不按名称+行号猜 |
| F4 规范IR | F2/F3及版本化语言规则 → Operation/Value/StateLocation/Region/Resource、CFG/SSA/完成端口 | 每个语法类别×上下文有构造规则，控制/状态/效果约束成立 |
| F5 接线 | 原定义和端口、静态契约及可选运行事实 → 跨区域/函数/库/资源关系 | 原端口、条件与作用域逐项对应，动态仅补实际选择 |
| F6 推理与发布 | 已连接关系 → 条件固定点事实、分片及完整覆盖清单 | 来源可重验；字段未知、预算前沿与缺实现分开 |

每层都须对其全部输入给出有效记录、准确StageError或BudgetFrontier；失败不能改名为UNKNOWN或悄悄跳过。
记录实例覆盖与实现规则覆盖分别核查；新发现材料仍从已验收前层进入，不能绕过前层。
F1/F2使用官方前端，不重造Python lexer/parser；AST是语法输入，最终程序图仍可共享、成环和展开。
F0当前是独立命令，旧static入口不能视为已经自动执行它；现有AST目录计数不证明F1/F2通过。
F0的V1解释规则忽略codec警告（原bytes保留），不继承调用方warnings-as-error；
串行解释或spawn进程隔离，避免共享warning过滤器相互干扰。
F1固定官方token表和实现指纹，通过显式CRLF/CR→LF视图调用generate_tokens，不增加末尾换行。
原生行列、原decoded字符区间及view UTF-8字节区间分开；虚拟EOF不裁剪，gap不全是trivia。
string/line以共享精确文本引用存储；相同文本引用不代表同一源位置，原token extent另存。
TOKENIZED、TOKENIZER_ERROR、BUDGET_STOPPED、UPSTREAM_DECODING_ERROR分开；真ENDMARKER并确认耗尽才算EOF。
词法warnings单独记录；spawn进程隔离过滤器。budget前缀不覆盖当前模型，fresh读取逐字段重放。
F2用官方compile的ONLY_AST|TYPE_COMMENTS，dont_inherit=True、optimize=0及当前feature版本；
记录parser实现、完整结构化schema、整数位数/递归限制和literal预算，不执行bytecode。
按parent/field/list occurrence存平面局部ID表，保声明字段/属性的显式presence；None、空列表、缺失分别记录。
精确literal保IEEE位与代理码点，预算超限不是语法错误；还原使用官方类__new__并逐字段核对。
语法表不是最终依赖图，也不授予scope合法性；新occurrence身份不冒充旧ast.walk SourceID。

## F4的形式顺序

当前按用户要求采用NORMAL_SUCCESS范围推进：应用报错与异常引用清理暂缓，先生成LeWM正常控制/数据/状态图。既有异常端口材料保留，不扩其证明范围；for的迭代耗尽属于正常控制协议。

F4-A先闭合输入/输出结构语法：官方13 ASDL域、113构造/484槽引用，以及canonical IR的205记录/733字段、18 ID、60枚举。
目录按原类型和字段引用共享；exact shape检查拒未登记子类、伪枚举成员、错误ID、循环值和预算前沿，不生成程序图。
F4-B再定义`构造×原字段×C1上下文 → 操作家族/有序端口/完成与状态签名`，使用F2/F3原引用，不重解析或按name+line接线。
实现顺序为B1有限端口签名代数与接口匹配，B2完整家族目录/原参数来源/状态及源码产生规则，最后版本化根和强制reader接入。
B1允许显式类型、拼接、参数引用、重复、有限选择和异质类型向量；只核端口形状，不授家族身份、源码对应或效果证明。
接源码前，先以原F2 fields/list重放旧SourceAtom的BFS身份公式，并核全源ID/kind/完整reference集合；这是身份层，绝不是求值顺序。
旧SG不存在的source-only输入单独处置，保留其F2/F3，不捏造旧ID域。桥接内核不parse；strict读者仍重验F2上游。
执行产生规则必须另按语言规则定义；symtable/compiler拓扑的visitor顺序不能当执行边（如decorators/defaults、DictComp key/value）。
产生规则的输入语法为`SourceProductionPlan`，与canonical执行图分开：v25含69种有限步骤，源码槽、namespace端口、区域参数及结果引用分别有类型。
隐式字面值复用已有`PythonLiteral`精确编码，不断言相同值具有同一对象身份或发生了分配。
`ApplyPythonProtocol`复用已有88种协议及签名，参数必须显式绑定，输入/完成端口强制核验；不把协议名当作效果证明。
区域共享，不按调用/迭代复制；循环显式分不变量前缀与携带值后缀。异常完成通过payload＋captures接入handler参数，不冒用normal结果边。
模板接线还核局部world顺序：包括内嵌调用操作数，已由正常结果更新的world不得退回旧输入；只读操作保留当前world，循环state不能放入不变量前缀。这项依赖约束不声称已理解所有native效果或引用清理。
引用值端口仍需声明借用、持有、转交及消费责任，并接正常/异常清理；值可用或端口类型一致不证明寿命正确。清理关系沿原REF及完成边，复用现有FRAME协议，native效果未知则保持开放。
迭代循环的`IterationCondition`连接advance和exhaustion predicate；元素只进入body临时端口，当前world替换携带端口，不增添伪造的item回边。
引用端口不变不表示对象内容不变；iterator/container的内容版本仍由state边表达，不能直接据此reuse。
当前只核记录、归属、有序值引用及部分接口；cleanup/resume完整控制语义、逐构造求值规则和效果仍须后续重放，不能由shape验收替代。
Operation.label仍有旧派发消费者、名义类型字符串及分散协议签名，须显式收紧；结构通过不授opcode/效果/变换正确性。
F4-C由已验产生规则生成层次控制/数据/状态边，操作和区域复用原SourceProductionPlan；NORMAL_SUCCESS下先接主路径，之后进入F5跨调用/资源连接。扁平N1适配与完整异常清理另行推进。
当前F4-A及全域模板接口已验收，F4-C正常路径边表已生成；完整效果与异常清理另列。`max_visits`只限前置shape遍历；构造器核验复用原验证器，不冒称总步骤预算。

F4-B继续按原字段识别、局部产生规则、原材料重放的顺序推进。当前28类表达式规则只生成局部recipe，child仍是带用途/状态接口的原槽义务；
不把未实现的构造变成OPAQUE成功节点。短路/条件/比较保分支区域，异常出口汇总前面所有步骤，不能只抄最后一步。
状态域/异常ABI由显式profile提供，效果及实际state来源尚未证明。先闭合剩余构造/上下文规则，再进入F4-C；不以局部recipe计数代替规范图覆盖。
Call区分普通参数与展开参数；唯一位置实参为星号表达式时保留至最终调用，其余星号和keyword连续组按协议顺序处理。
keyword/Starred是受父Call字段约束的描述符，不是独立求值节点；规则不重放method/super/builtin编译优化，也不据此断言物理分配次数。
Starred也可归属显示/赋值目标；解包在写目标前完成，Dict的覆盖更新与Call的重复键拒绝分开。容器与字符串规则分文件维护，仍共用同一输入语法。
f-string先转换再求格式说明；模板插值只捕获值和转换标记，使用独立构造，不复用立即格式化操作。
同步推导式的首个iter在外层求值/取iterator，然后进入原C1局部namespace；每个for子句一份共享循环模板，过滤短路，DictComp先key后value。
局部scope激活、逃逸cell保活及物理inlining/清理仍是合同义务；不回滚walrus等外层写入。async clauses及惰性GeneratorExp仍有显式规则前沿。

暂停规则按三个小步推进，不跨层：①先验source recipe的handoff／normal与raise恢复端口；②消费原C1 owner产生yield规则并对照静态compiler；③再补委托驱动的await／yield-from及惰性body。
source recipe v2的SuspendExecution显式导出值和world，恢复端口输入新world及保存值；禁止保存旧STATE，所有恢复完成取并集。NEXT/close的driver准入与规范化、frame/exception context保活仍须后续产生规则证明。
v3为await/yield-from增加显式delegate端口和4种有限运行时协议签名；SEND同时给出完成判别、值及world，异常另走ABI。委托恢复端口接收driver处理后的结果/异常，不等同于原始throw请求；driver内部绑定仍是后层义务。
Await/YieldFrom的局部规则已接入一份共享SEND循环；普通SEND错误直接传播，只有挂起后的driver完成异常进入CLEANUP_THROW分支。RepeatCondition表示无条件控制边，不造True求值；空完成接口可表达没有正常/异常出口的循环。
recipe v4把代码声明、环境/cell引用及后续激活分开：DeferRegion不执行body，body入口显式接收环境、原序已准入参数和新world；捕获沿原C2b活跃转交hop，包括仅为内层转交的cell，不提前读值。参数沿PARAMETER_INTERFACE声明及resolution接原binding，不冒充普通STORE；初始默认值显式指向原创建时表达式。原序参数/捕获不冒充native布局，调用准入与物理frame/closure映射另行证明。
Lambda及同步/异步GeneratorExp规则已接通原F3接口；生成器仅在创建时求首个iterator，body/过滤/内层循环在DEFERRED区域，共用推导式循环模板且不造容器。
recipe v5增加GET_ASYNC_ITERATOR、GET_ASYNC_NEXT及StopAsyncIteration匹配的有限签名；GET_ASYNC_NEXT返回已取得的await迭代器，不再重复acquisition。异步推进在advance区域复用共享SEND循环，只有advance的StopAsyncIteration代表耗尽；target/filter/body的异常继续传播。
异步属性沿原C1求值owner传播：eager comprehension会使外层求值异步，创建惰性generator不会；首个iter仍按原创建阶段归属。异步generator的元素使用ASYNC_YIELD，与内部AWAIT分开。
语句规则另按同一typed recipe生成：7类linear语句保RHS单次求值、原序写入、正常路径临时引用释放及RETURN出口；global/nonlocal只保编译声明关系。
recipe v6增加原F2 `SourceLoopTarget`，局部子图可以导出外层循环完成端口，不造本地假父节点。suite按原序接STATEMENT child，正常完成才接下一语句；没有正常前驱的尾部仍保原slot disposition。If取分支完成接口并集；For/While/AsyncFor各保一份循环模板，iterator引用是invariant，world由backedge携带，item只进当前body。耗尽才进else，break绕过else；嵌套循环else中的跳转接仍活跃的外层循环。
`source_statement_interfaces.py`在原F2上机械归约各语句的may-completion上界，定义body不内联；try/finally的完成替换及with的异常抑制影响接口。上界不是可达性证明，也不代表child实现已经接通。27类局部语句规则已接接口，含函数、类、类型别名、with、try及try-star；Match及其余清理仍须闭合后才发布CFG/SSA。
recipe v7先固定三类接口，再接AugAssign/AnnAssign/Assert/Raise。增强赋值保存一次地址、读旧值、求RHS、原地运算后写回；其target由父语句处理。没有RHS的注解只检查必要地址分量，不造get/set或多余slice/tuple；原C1决定局部抑制、字符串化发布或延迟登记。延迟annotation请求body仍是独立child义务。assert保目标编译选项的符号输入，不能照分析进程的优化flags删除检查；失败分支才求message。raise按exc/cause顺序求值，再规范化并导出异常ABI。
v8区分ImportRequest/ImportMember/ImportStar，三种接口先验再接产生规则。原F3投影依据导出已知请求名、成员名、from-list和相对层级；bind继续引用原namespace write port。普通点路径绑定head，dotted-as沿IMPORT_FROM路径逐层取成员；普通from-member保私有名改写，点路径分量不改写。star保动态namespace写效果，不捏造静态名字集合。请求不等于实际初始化或I/O；importer/frame/registry实现和清理仍未证明，不能据此删除import。
v9区分函数创建、annotation factory、decorator调用和generator/coroutine异常翻译。创建按decorator表达式→defaults→annotation factory/函数对象→逆序decorator→原name write port；body单独激活，正常fallthrough转RETURN None，escaping StopIteration在用户handler之后翻译。Lambda/GeneratorExp共用此退出路径。docstring保编译元数据；注解按CPython的args→posonlyargs等原顺序形成延迟请求接口，不提前求值。
v10显式激活原TYPE_PARAMETERS scope：外层defaults只求一次并传入工厂；bound/default捕获原lazy evaluator，不提前运行；逐项create→set default→bind，最后构造参数tuple并关联原function引用。绑定使用原TYPE_PARAMETER_INTERFACE而非伪造Store。工厂传递的是逻辑source输入，非隐藏tuple/dict的native ABI。所有instruction统一带类型标签，避免同字段形状的create/set/bind在存储中混淆。
v11的类定义把callback模板交给实际选择的builder，不直接调用类体；入口显式接环境、builder提供的namespace和新world。初始化拥有docstring等namespace动作，只有body正常完成才进入收尾，返回class cell或None而非类对象。类与普通调用共用base/star/keyword组装规则；泛型base先创建、后接到用户bases末端。类型别名保存原TYPE_ALIAS evaluator和名字来源，声明不求值；泛型定义复用原type-parameter工厂。namespace内部操作、builder准入及lazy请求body仍待展开，不能据此授予完整效果或native证明。
v12将with清理表示为完成路由，移除未使用且未闭合的CleanupControl占位。每个withitem一份嵌套模板：先求manager、按type-special规则取exit再取enter，成功进入后才保护as写入和后续manager/body。正常/return/break/continue调用exit(None,None,None)，忽略其返回值并保持原完成；异常路径安装handled exception，调用exit后才判断抑制，所有退出/真假判断/await失败都经恢复路由。参数取exception当前traceback，重抛不伪造新raise位置；native frame/lasti与引用清理仍须证明。async enter/exit分别标记await准入上下文，再复用共享SEND模板。may-completion也包含as写入及后续enter失败被抑制后的正常路径。
v13将try body、按序catch type测试、handler、else与共享finalbody分别接线。else只接body正常出口，其异常不进同级handler；匹配/初始绑定失败恢复旧异常。异常名字沿原write port绑定，人工None写入后由原CLEAR_ON_HANDLER_EXIT贡献授权删除，不伪造Del port。正常handler出口先恢复再清名，异常出口先清名再恢复。`SHARED`调用可从词法子区域复用祖先所拥有的模板，强制同activation/namespace及显式端口；finally正常完成保留pending值并替换world，非正常完成覆盖pending结果。编译器提供的DefineLiteral不制造分配或异常边。上述仍不证明native frame、引用寿命或完整效果。
v14将except*的原异常、remaining和accumulated list分开：每个catch type都顺序求值/校验，SplitExceptionGroup条件更新handled状态；不能因remaining为None跳过后续type。仅body异常收集后继续，初始绑定/清名/split错误直接离开分派；每个clause不恢复旧handled值。最后将remaining（可为None）加入list，再按原异常及当前元数据MergeExceptionGroup；整个分派的正常/异常出口统一恢复旧状态。ReferenceIsNone是无world的身份判定；PrepareReraise只消费异常引用和当前world，旧traceback不再作为输入。流程依据固定[bytecodes](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c)、[ceval](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c)及[exceptions](https://github.com/python/cpython/blob/v3.14.7/Objects/exceptions.c)，native实现/效果仍未获证。
v15区分VALUE与CONDITION，修正先求短路对象再truth导致的重复__bool__。条件BoolOp/Not/IfExp/比较链沿原字段传递控制决策；其余表达式委托同occurrence的VALUE模板后truth一次，NamedExpr不能改为给目标绑定布尔量。if/while/assert、IfExp.test及推导式filter接CONDITION；InvertCondition只翻转已准入的布尔决策。材料v3在原分区后流式保存按请求生成的上下文变体，依occurrence/purpose做有限工作队列；每源每材料域只生成一次，跨域canonical合并仍待F4-C。依据固定CPython codegen_jump_if，未授frame/效果证明。
v16接Match及八类pattern。PATTERN区域的成功端口按原捕获顺序返回引用，失败端口仅返回world；整个模式成功后再写namespace，guard为假不撤销写入。OR和case后续路径共享模板，guard复用CONDITION；九类native边界按原字段重新推导端口，native实现及引用寿命仍待证明。
v17接Module/Interactive/Expression根，入口显式接已准入globals、locals和world，不假定两映射相同。模块注解callable经[annotation placeholder展开](https://github.com/python/cpython/blob/v3.14.7/Python/flowgraph.c)在用户语句前创建；请求body另计义务。STORE_NAME与STORE_GLOBAL的mapping/dict语义分开，future注解setup保留已有值，docstring受目标编译选项控制；交互Expr显式显示，普通常量Expr不制造求值。外部准入、native/frame及引用清理仍未获证。
v18将BuildFunctionAnnotations/BuildLazyExpression接到DEFERRED请求模板，不以创建边调用body。入口显式接捕获环境、format和新world，保原F3 scope及活跃cell转交；format比较/异常、按序求注解、最后建dict及星号单项unpack各自接线。future字符串从原F2子树经固定编译器的受控wrapper推导，不执行目标，临时query编号不改原ID。材料v4单列request模板/字符串，不再把已展开的函数请求计为整块child占位；scope汇总、准入、native/frame/引用清理仍待完成。
v19删除整块class namespace init/final边界，按原F3 resolution表示隐式nameop，另以class-owned binding表示protocol cell。qualname、first line、static-attribute tuple及编译选项按源码规则推导；frame/capture物理传递不由logical binding存在替代。泛型tuple来自callback创建，body正常完成才发布static attrs/cell；class注解callable仍为待展开汇总请求。这里的self识别只重放固定CPython metadata规则，不推断对象类型或优化机会。
v20结合原C2 FREE resolution与C3 compiler FREE事实补齐无显式读写的捕获需求，包括仅转交的中间scope。补充边以源单元内`(scope,binding)`共享键和parent引用存储，保留原F3整数hop；入口另列owned_cells逻辑要求。输入新增原C3材料SHA，不把逻辑cell要求当作物理frame布局、分配或效果证明。
v21将模块/类变量注解的创建动作接到DEFERRED请求体。静态查询从原F2槽恢复临时AST，以不与原编译常量冲突的标记获取三个优化级别的登记顺序、私有key及conditional index；保留try/else/except的编译顺序和finally重复登记，各表达式仍引用同一原槽。未执行目标。被原编译单元裁掉的类另保源码模板，显式标记emitted_in_original_unit=False；投影只放宽其外层控制，保该类子树，不把投影的frame/capture布局当作证据。隐式capture可引用原C2需求，不强求公开symtable存在FREE项；登记来源/native路径选择、准入及引用清理仍待证明。
v22将PublishAnnotation降为源码描述符，展开条件登记的namespace查找/PySet_Add及future字符串/当前mapping写入；无条件class声明不制造运行步骤。AnnotationStateAccess显式区分写入端LOAD_NAME、请求端LOAD_GLOBAL与原class protocol binding。重复源码的编号保留完整编译参数域，单值折叠；ReadCompilationAnnotationIndex没有runtime world输入，不是实际执行的选择器，native上下文绑定仍未证明。不可达模板投影保留被放宽控制表达式里的原绑定，避免丢失walrus/nonlocal等静态关系。
v23由source_compilation_contexts静态查询原代码的登记生产位置。临时tuple标记保原表达式/符号影响；常量路径只提出对应，原owner指令、布局、异常/位置表、非code常量和子项元数据逐项一致后才授权。记录原代码指纹及lookup/index/insert/discard偏移，不把查询代码当原代码、不按name/line接线。AddAnnotationIndex携完整参数/位置证据，literal单值也保来源；bind接口可按精确原代码上下文返回唯一登记。未保留owner、已证owner但无该写入、布局未证三者分开；共享region调用端的上下文传播仍是后续义务。
v24增加参数化上下文接口表。按原F3代码owner生成区域端口，按有限入口引用规则生成带类型的边；调用位置用step ID及字段/tuple序号区分。source matcher强制从原材料重建整表，拒绝漏边、错端口和错上下文；shape reader仍允许无源码的接口样本不带此表。声明与执行、循环模板与迭代、逻辑接口与native实例化分别验收，后者未由本表证明。
v25为源码recipe增加显式状态/异常profile，补五类core步骤的端口合同。固定签名在shape层检查，变长参数在source层从原字段推导；保留独立的shape检查与source-count检查标记，未证明完整参数来源。tuple布局明确区分三种产生规则；没有源码产生规则的预留枚举不放行。旧无profile接口样本只授结构证明，不能经source matcher进入源码规则材料。
前两步的局部规则已通过：Yield由原C1 owner区分普通／异步形式，bare yield导出None，嵌套定义header仍归外层执行owner。静态compiler只作独立规则对照，不以bytecode位置接源码身份。
后续语句／定义／cleanup规则闭合后才进入F4-C；每步先验类型/接口，再接源码规则，再在原材料独立重放，不以节点存在或局部计数授予全层完成。

## F3的形式边界

源码名字/求值角色、compiler block与runtime frame分别表示；三者没有固定一一对应。
公开symtable会移除内联comprehension表、重挂子表、共享annotation表，不能直接作为源码scope树。
原生id是已释放C AST的历史地址；namespace按名字派生的stdlib视图也不是绑定证明。

严格顺序为：F3-A保全官方原序symbols/整数flags/varnames/children及profile/error/budget；
F3-B按全部constructor×field×context声明名字角色；F3-C建立源码scope/phase和名字→namespace接口，
再以显式投影witness对应编译器视图；F3-D全量fresh验收。前步未通过不新增后步实现。
名字角色按语法类别派发；属性名、keyword标签、import路径、常量文本不能当局部变量读取。
词法存储绑定与实际值/运行类选择分开；缺静态规则不是动态UNKNOWN，未知值也不抹掉已知端口。

继续复用官方前端；现成scope库仅在已验证能力内复用。LibCST1.9.0的walrus实测反例与
Ruff对class-cell的显式近似表明不能把工具输出无条件升格为优化事实；不按name/line或ast.walk猜接线。
依据：[CPython](https://github.com/python/cpython/blob/v3.14.7/Python/symtable.c)、
[LibCST](https://github.com/Instagram/LibCST/blob/v1.9.0/libcst/metadata/scope_provider.py)、
[Ruff](https://github.com/astral-sh/ruff/blob/main/crates/ruff_python_semantic/src/scope.rs)。

F3-A已实现类型化编译器视图与独立材料store；显式flags、原序参数/符号/children和别名均可fresh重验。
编译器补入free symbols的顺序受Python hash上下文影响；profile保有效指纹，worker与parent必须相同。
完整转录保原序，不能用排序掩盖差异；分析进程固定PYTHONHASHSEED，不能靠启动后改env假装生效。
原生compiler错误、adapter协议错误、资源与预算分别处理；外部store摘要需由fresh事实重新计算校核。
collect-only保留原模型，只写新分片并绑定必需四种源码收据；无关manifest元数据变化不使其失效。

F3-B以113个constructor的196个field和288个attribute建立484条共享规则。
全槽按ABSENT/None/空列表/有值分区计数；名字、属性标签、keyword标签、import规格分别分类。
增量赋值、仅注解、普通赋值、walrus等使用原父字段和ctx选择角色，不声称运行时读写。
实例只存F2槽引用、角色和必要上下文；字面量、文本、坐标仍只在F2保存，catalog每store一份。
`SyntaxRoleView`一次建立父槽索引，查询任意原槽，包括不落稀疏port的字段；循环查询不重复扫AST。
schema未覆盖则拒绝；预算停止不发布部分角色表。F3-B通过也不代表scope/名字存储绑定完成。

F3-C按以下形式产物逐层实现和验收；C1/C2/C3-T/C3-S已按声明范围通过，F3-D也已完成声明范围组合验收，不能以旧图计数跳过后层形式验收：

| 层 | 输入 → 输出 | 通过条件 |
|---|---|---|
| C1 属性路由 | F2/F3-B原槽 → SourceScope、EvaluationRegion、共享SlotContext及private策略 | 157个child字段和全部484槽规则闭合，866源/全部port归属可独立重验 |
| C2 词法接口 | C1归属及整scope声明 → name-key、local/cell/globals/builtins/class-mapping查询或绑定接口 | 16个lexical字段/15类全覆盖；无名字、wildcard、派生binder分别计数；不冒充实际dict/StorageID |
| C3 编译器投影 | 原源码接口及F3-A → 直接/内联/共享/省略/合成关系witness | 原引用、参数序、symbol贡献及重挂关系逐项对账，不按name+line或地址猜，不要求scope/table双射 |

C1先做结构owner/env路由，再按归属汇总yield/await，最后派生触发条件；nested def的defaults/decorators仍可能属于外层。
source scope、求值region、compiler block、runtime frame分别表示；类可见annotation、future字符串化、选择性mangling需显式规则。
公开symtable丢失部分源结构，仅作已证明投影后的校核；C2不能直接把其混合flags当每个Name的存储地址。
依据为上述pinned symtable及同版[codegen](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c)，不执行目标。

C1字段路由的封闭分区为50特殊selector、12描述符、95继承child字段；其余327槽为payload metadata。
metadata自身不求值，但继承所属操作上下文；表达式被annotation策略抑制是另一轴，不能遇nested lambda就解除。
共享ContextState分别引用求值owner、源码environment、region、private策略和声明路由；原结构owner沿F2父槽查询。
实例只保存scope/region/private记录及发生变化的SlotRef边界；任意槽或原B端口由共同view查询，不复制AST或逐槽上下文。
参数/默认值/注解、typeparam name/bound/default可在同一节点内分属不同上下文；选择性mangling保原group/位置，C1不计算名字key。

C2内部先验收C2a名字投影和整scope声明账本，再实现C2b条件查询与捕获传播；C2全层要求两者完成。
C2a覆盖16个lexical字段/15类及所有原B端口disposition；global/nonlocal先汇总，walrus贡献先归入接收scope。
有效名按SYMBOL_VISIT_PROJECTION归一并intern，SELECTIVE按原typeparam访问前缀；这不是已验证的codegen地址。
声明、候选写/删、参数接口、directives及cleanup分开保留，未知运行值不妨碍确定逻辑声明；SUPPRESSED保源码模板而不授实际效果。
C3内部严格分两步：C3-T先完成compiler模板构造/附着、future detach与comp splice，并逐边对应公开图；
C3-S随后重放名字贡献、合成参数、符号合并与传播，核原整数位与varnames，T未验收不开发S。
T的身份为原occurrence＋固定语法role；没有source scope的空header annotation仍有原Def.args依据。
source scope、求值region、compiler template及public row分别引用，只有类型/名称/行号相同不足以接线。
T只验type/name/lineno/nested/children；symbol_origin_projection与parameter_projection明确NOT_COMPUTED_IN_C3T。
S以(原模板,有效NameKey)建立compiler slot，先重放原标量名字贡献与参数，再沿原附着树求解scope、inline合并/删除、cell及free转发。
raw contribution保源C2a引用或真实原槽；SymbolFact是带低位mask、独立scope code及前置事实引用的版本化DAG，不记录每次set插入。
PUBLIC符号与参数位置逐原F3-A序号投影，合成/relay无source port仍有固定规则来源；detached/ignored/merged/deleted均有明确处置。

C2b将class mapping、local/typeparam slot、closure及class-protocol cell分域，分别输出读计划、写/删目标和共享capture父链。
ROOT_GLOBALS只指根环境模板；非根使用各自ENV_GLOBALS/BUILTINS参数，不据源码相同断言运行字典相同。
class prepared mapping与captured class-dict namespace分开；mapping miss与其他异常分开，非局部写不能写回class mapping。
内层global、逃到root的walrus和语言隐式协议均保来源；隐式需求逐原region/anchor保存analysis_visibility，不能用共享scope首个region概括。
SUPPRESSED源码参与、future detached模板及实际执行保持分轴；cell_required仅表示已建跨source-scope捕获义务，不反推合成compiler cell不存在。
这些是SOURCE_NAMESPACE_TEMPLATES，不授实际cell布局、compiler projection或运行地址。

## 共享子图与可组合接口

源码 AST/CST 是识别输入；执行依赖由可共享、可成环的规范图表示。
模块、函数、类体使用各自的原主体身份；未建主体保留缺口。
分支、循环和异常保留控制结构、合流及适用出口。
每个定义主体保存一份，调用与循环迭代引用它，不复制函数或按迭代展开节点。
循环视图引用原成员、header 参数、初始边和回边；它不另造一份 CFG。

接口必须保留输入、环境、正常/异常等完成的 payload 与前后状态。
数据返回、引用返回和状态返回分别连接；引用相同不证明可变内容不变。
每条关系携带原 namespace/typed ID、上下文、条件与证据；缺边不证明无依赖。
字段可以是已知、符号值、候选或 UNKNOWN；一个字段未知不能抹掉整个节点。
区域 cut 只描述输入、消费者、状态、效果与资源，不授权替换区域。

## 静态模板与动态实例

静态侧建立子图和可组合端口；动态侧观察实际选择，再对应到原端口。
两者按事实是否可静态确定分工，不按文件边界分工：跨文件的已知关系直接静态连接，
同一文件里的不确定分派也保留条件或补充观测。文件负责材料、版本、存储与构建调度；
函数、类、循环等 Region 才是共享结构和可展开接口的单位。
运行绑定必须限定 run scope、process/thread、InvocationKey、attempt 及事件锚点。
静态 context 是接口选择；None、闭合栈和 Open 后缀有不同含义，均不是 Invocation。
同一调用点的不同 attempt、同一函数的不同激活不能因共用模板而合并。

[call_operands.py](../scar/trace/call_operands.py) 复用 CALL 事件采集；
[python_call_targets.py](../scar/trace/python_call_targets.py) 记录实际 callable，
[code_snapshot.py](../scar/trace/code_snapshot.py) 提供完整代码身份及指令位置。
采集仅保存必要原事实；静态对应、接口建图和推理在离线侧完成。
代码对应核完整 CodeID、编译路径、解释器 profile 和原位置；名称或行号只用于筛选。
有历史源码指纹时必须核对；没有时可静态建立当前源码子图，但运行对应只授权匹配的 Code 作用域。
子函数匹配不证明父模块执行、factory 创建来源、globals/defaults/closure 内容或兄弟定义的运行版本。
实际类对象的调用证据不证明它来自某条类声明；创建来源须另有证据。
一次观察只限定该运行事实，未覆盖路径与未知状态继续保留。

## 分片存储与统一读取

artifacts/current/static/ 是唯一当前程序模型；源码/主体/关系按分片保存。
每片附 stored/decoded SHA 与原 ID 引用，跨片引用不复制原图。
共同 reader 共享有界缓存、校核原收据；原输入稳定期间复用解码结果。
增补缺失主体保持已有主体和关系原样；旧关系仍只覆盖其原输入范围。
无图诊断不是已完成主体；仅fresh读取确认原收据内无图/端口、源身份不变，才允许补建并保留诊断输入。
既有规范/partial图不走此替换口；实际支持尚缺时报告static rule，不消耗无效的补建请求。
artifacts/current/queries/ 保存派生查询证据，不是第二份权威程序。
形式阶段模型更新先同步全部分片、目录与manifest，切换目录并同步父目录后才清旧owned片；报告先完整落盘再发布。
两个rename仍有可恢复窗口。恢复包按原SHA读回，前端材料与图身份不因恢复而重建或猜填。
材料登记可在固定历史F3-D验收摘要下复用原七层收据：逐原字节复制、核父链与当前profile，不重签历史证明。
运输登记与新语义重放分开；原strict reader不放宽，旧图和证明范围不因登记扩大。

## 已有后层能力与当前开发边界

已具备源码层、局部规范图、共同依赖查询、部分条件属性推理和循环边界查询。
真实 CEM 的81个CALL实例及9条函数接口已接入共同图的显式观测端口查询，静态邻接不变。
实例端口引用原点及run/Invocation/attempt/事件作用域；只有实际选中的return形成返回接口。
参数未定不丢入口/状态/返回；ABI布局保留条件备选、默认值义务和pack依赖，不猜receiver或容器身份。
对应 owner 是 [program_observed_dependencies.py](../scar/analysis/program_observed_dependencies.py)。
选中 CEM 循环的边界查询已在原预算内完成；这不证明状态、效果、资源或整个程序闭合。

可证明的线性编译栈来源已接原cleanup返回；跨跳转合流继续保留候选，不按None猜来源。
这些是已有局部结果，不证明完整执行图闭合。F0至F3及全域源码模板已在声明范围验收；当前按NORMAL_SUCCESS进入F5跨函数、库与资源接线，应用异常和引用清理暂不阻塞。
不得把裸 context=None 的观测边注册为全局事实；当前正常路径图不授予保持异常行为的变换许可。
Python→native/runtime/kernel、Tensor 属性、alias/effects 与资源连接仍需按实际缺口补齐。
第一阶段只有在实体、结构、连接、属性和覆盖均经核查后才完成。

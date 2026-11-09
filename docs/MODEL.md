# SCAR 程序模型

SCAR 是宏观编译器：用有类型、可展开的图统一表示程序及硬件资源，支撑结构化简、hardware-aware规划与C++20代码生成。
当前阶段到自动建模、建图和查询为止；图中出现重复或候选，不构成变换许可。
范围、已知关系及缺口必须如实列出；缺口存在不算相应部分已完成。
当前没有做到所有 Python 行为的精确静态求解。

## 五类核心实体

统一查询使用`ProgramView`与既有`ProgramDependencyGraph`。源码ID由原unit、编译/绑定profile、template和原Step/Region/完整Port限定，不随查询函数或展开顺序改变；节点投影保双向来源，不重新生成操作语义。
`get`返回公共节点元数据，`original`保原强类型记录，`expand`展开共享区域，`producers/consumers`查询依赖，`explain/explain_edge`保来源及原调用路径。Use、control等辅助端点有独立role，`kind=None`不是UNKNOWN，也不作为新计算值。
统一视图按单元发布：namespace/material各存一次，节点与边使用既有类型ID引用，原G.Edge以封存F4 template＋ordinal定位，不重复保存完整端点/来源对象。原指令正文不复制。
数据生成器、wire类型和材料协议精确核版本；facade producer SHA保来源，选中单元总由当前同版本映射规则重推验收。增加查询方法不要求重建未变的前端材料；改变映射/数据合同必须重新验收。

入口：`python -B -m scar.cli program-view --catalog CONTEXT_CATALOG --unit UNIT --out FRESH_VIEW`；可重复`--unit`。`--read VIEW --unit UNIT`对该完整单元按当前合同重推，而不是只检查文件哈希。

局部状态通过`ProgramView.state(unit)`接入同一查询。`BindingLocationTemplate`由源版本、原C2接口/绑定槽和key限定；实际frame、mapping或cell仍为实例参数。同一源槽不同激活不因此成为同一个物理位置；C2 binding索引也不是CodeScope ordinal。`BindingVersionTemplate`另保原函数、定义类型/站点及执行occurrence参数；绑定到同一引用不能证明对象或Tensor内容未变。读取保匹配recipe栈的全部may定义，`BINDING_READ`带条件和MAY精度；`STATE_LOCATION`统一为位置→版本。写入/删除、形参入场和开放来源分别表示；None payload不是Python None。

隐式类名字沿原C2分类或ordinary规则投影：prepared mapping、frame globals、frame builtins和捕获cell分开，有序lookup不是所有位置都已读取。显式环境/mapping参数通过条件ENVIRONMENT边绑定地址owner；没有原C2接口索引时保None，不借用另一scope的索引。`ReadBuildClass`是当前frame builtins中的语言查找，不等于导入builtins模块或已选择默认builder。escaped-root等原路由优先复用，无法确定不能自行改成源码globals_scope。

注解lookup按原`AnnotationStateAccess`分派，creator与deferred request scope分开：LOCALS_CHAIN不能借同名GLOBAL计划，class-cell保原implicit/binding/read_plan。`ReadAnnotationNamespace`可产生registry引用；`ReadAnnotationRegistration`产生bool，namespace read的payload为None，contains/index仍保原组合指令，不虚构registry GP。无显式owner时保实例参数，不拿world冒充dict/cell。namespace store使用原key/value端口；ensure只作条件UPDATE。默认求值器及type-parameter tuple关联也只是UPDATE输入，不执行其延迟正文。

`state.content()`将属性/索引协议接入同一namespace：地址是`(receiver引用发生实例, Field/Item/SliceBounds)`表达式，不是已选物理槽。属性lookup名复用已封存private-name投影，并以完整world对/receiver/action/payload定位原fact；索引DELETE直接来自原操作，不能依赖缺少DELETE的旧items表。原owned receiver Use、动态key及bounds均连到地址，不重造slice对象。`ContentStateProjection=project(world,address)`是原world上的符号状态变量，前后ID不同不证明写入或LogicalVersion不同；GET可能调用有副作用的descriptor，仍保前/后态。payload与GET结果保原端口，不建立结果等于slot内容的alias。实例、协议与实际内容版本保持明确开放前沿。

聚合更新用`WholeOwner`选择整个目标内容，不人为分配未知element key；UPDATE的payload是元素或源容器输入，不表示整个新内容等于它。DICT_MERGE保callee/目标/源三个原端口，comprehension用原ChoiceBinding区分LIST/SET/DICT。条件由原操作、owned Use、地址和真实completion端口限定，不用全局收集序号决定身份，便于独立并行构建。

保留的环境值与可变namespace地址分开：`ClassTypeParameterProjection`保原`ReadClassTypeParameters`、完整ClassBodyInterface/类型参数SlotRef、environment及其owned Use、结果和world对。它是当前callback环境→tuple结果的带activation条件依赖；不是环境与tuple的alias，也不是后续`__type_params__`字段读取，不造LocationID。`state.environment_values`提供类型化查询记录；持久化依赖边引用已共享的原操作/端口，完整interface不再复制到通用状态表，reader机械重建。实际创建上下文及版本尚待③选择。

源码函数接口保原callee来源、signature绑定、参数/env/world、pack/default及data/world返回，并索引所有未接调用和父前沿。`scar function-interfaces --calls DECLARED_CALLS --out FRESH --jobs N [--unit UNIT]`发布条件接口；`scar function-call-view --interfaces INTERFACES [--unit UNIT]`打开其统一视图。`SourceFunctionCallProvider(view,store)`默认不物化任何单元，查询按需求接入；原source bodies继续共享。进入使用包含目标body Region的完整Frame，返回须匹配pop；未知外层保持None/open suffix并显式报前沿，不能并入所有caller。FUNCTION_ENVIRONMENT和pack只是依赖，默认值创建上下文未选时留前沿，deferred creation没有普通正文/返回边。静态候选不授dispatch或内容版本证明。

Native单元沿原codec namespace、entry/exit Value/Use和world投影。Tensor与Generator状态地址是`boundary slot＋Optional/List类型路径＋选中值实例`，不是已观察元素、StorageID或内容版本；列表不展开，Optional保存在条件。输入保原before/normal/raised world，返回仅在normal存在。原alias before/显式after字段保留，其阶段是annotation字段而非程序执行时间；标签按原declaration与boundary限定。分组是声明关系记录，查询时才产生条件MAY/PROJECTION边，禁止传递合并成对象或storage身份；wildcard、空after、无annotation与False may_write都不授无副作用/RNG或no-alias结论。

入口：`python -B -m scar.cli native-state-view --source BINDING_NATIVE_MATERIALS --out FRESH_VIEW`，`--read VIEW`独立重推所有native分片。`NativeStateSession(materials, view=existing_view)`复用同一查询和原core loader；基础core记录优先于扩展metadata，扩展状态不伪造canonical正文。新状态指向原图与声明，不复制原native图，也不声称已选择Python/native调用或dispatch。

`SourceEffectRequest`保原操作和69种指令的闭合分类，动作标签可重叠，只表示待解释能力；不授pure、真实搬运、分配或RNG结论。已知绑定接口与尚缺的地址规则分开，`missing_rules`不伪装为运行时UNKNOWN。CLI为`python -B -m scar.cli program-state-view --catalog CONTEXT_CATALOG --unit UNIT --out FRESH_VIEW`，默认根据READ、原C2槽域/owner和原函数body作用域选择所有可跟踪局部槽，随后发布内容接口；捕获不冒充当前帧的局部槽。`--slot C2_LOCAL_SLOT`可缩小查询，`--interfaces-only`不求绑定固定点。schema `scar.source-state-view/1`中绑定与内容分表，均引用同一单元namespace与既有ID。`--read VIEW`独立重推全部已存记录及覆盖数，拒绝虚假的完成/内容证明标志；类型/求解器合同精确核版本，投影适配器SHA保来源，其变化必须通过全部表和计数的当前规则重推。缺少新环境合同的旧单元还须确认没有该投影；有则重新发布。跟踪的操作/控制边索引引用原正文投影，不复制指令。

| 实体 | 含义 | 对应程序部分 |
|---|---|---|
| Operation | 消费端口、产生结果并具有效果的操作 | 调用、计算、绑定、读写、分配、搬运、IO、等待 |
| Value | 原定义或区域参数产生的值 | 数据、对象引用、状态版本；局部绑定和协议令牌使用独立类型 |
| StateLocation | 可读写的位置或抽象状态域 | 对象字段、容器内容、Tensor 内容、module、RNG、文件状态 |
| Region | 有入口、出口和内部结构的子图 | 模块、类体、函数体及受支持的控制结构 |
| Resource | 执行或承载状态所需的资源 | CPU/GPU、内存、存储端点、文件、队列、stream/event |

这是实体分类，不是把每行源码划入一个互斥类别。一行代码可展开为多个操作与关系。
输入/输出是端口角色；常量/不变量是限定范围的性质；shape/dtype 是属性。
Block、Use、控制出口等是连接上述实体的强类型记录，不能合并成无类型字符串边。
实际定义见 [核心 IR](../scar/ir/program/model.py) 与 [资源 IR](../scar/ir/program/resources.py)。

K / Σ / A / R / Q / M 分别观察控制、状态、动作、资源、契约和证据，彼此正交。
Action 的 VAL / REP / MEM / XFER / STATE / CTRL / ORDER / IO / OPAQUE 也是可重叠标签，
并非五类实体或底层 `Behavior` 枚举的替代品。Q 保留假设；M 区分静态依据与运行证据。

## 图、端口与层次

图用规范化记录和 ID 引用保存；源码对应、包含、数据、引用、状态、控制及资源关系分别表示。
F2语法输入按F0/F1收据、parser profile和局部occurrence ID定位；字段/列表槽是有序子引用，保留精确presence。
语法occurrence由后续语言规则映射到核心实体和端口；一个表达式可产生多项操作，parser单例不合并计算身份。
文件及版本是并行构建和存储的分片单位，函数/循环是可展开区域；文件边界不强行划分静态与动态。
文件内外已知关系均静态连接，动态只补实际选择；未执行路径继续保留条件，不因缺观测消失。
结果/参数通过有序 Use 连接消费者，`f(x, x)` 的两个实参端口不可去重。
端点以原 artifact/namespace、版本、类型 ID 和适用上下文定位；名字或行号不能单独证明身份。
静态调用上下文不是动态 Invocation；未知外层上下文也不能冒充已闭合的调用链。
源码位置与求值用途也分开：同一表达式的VALUE模板返回对象，CONDITION模板返回控制布尔量，不能把短路返回的对象再truth一次。当前source recipe以限定profile/输入下的occurrence＋purpose区分模板；条件请求按需展开，原源码分区与上下文变体分别计数。
条件保留主体、有序操作数和依据；“在条件成立时精确”不等于条件已经获证。

函数体共享一个原始模板，调用点通过实参、形参、环境、状态及返回/异常接口连接。
F5事实的code_scope来自原CompilationContextFlow；声明子图存在不等于函数体被激活。入口求解按模块、调用及显式区域接口准入事实，未准入模板仍保留。
普通外部符号不自动成为namespace；只有模块或provider声明允许继续限定名展开，其余属性仍是原receiver/result/world关系，不制造无限符号字符串。
词法包含关系与调用边分开。F4-B recipe的`SHARED`区域允许同一词法所有者下的多个子区域通过显式端口调用一份模板，但不得跨namespace或延迟执行边界；原区域参数/结果不能变成隐式跨区引用。普通try/finally据此共享一份finalbody，不按pending completion复制源码。这是局部recipe能力，尚未生成canonical共享图。
字典显示沿分配、顺序求值、更新及异常状态展开；空字典也不能当共享常量。旧有限文件图保持原覆盖。
展开查询返回原 Operation/Value/Use，而不是为每个调用复制整份源码图。
循环也可作为整体展开：当前 `LoopTemplateView` / `LoopConstructView` 是原图的投影视图，
保留成员、嵌套关系、初始输入、header 参数、回边、正常退出、break/continue 及来源缺口；
它们尚不是独立 canonical Region，也不把每次迭代静态展开成一份新图。
见 [循环模板](../scar/analysis/program_loop_views.py) 与 [循环成员](../scar/analysis/program_loop_regions.py)。

跨边界接口必须保留正常返回、异常、挂起及适用的状态输入/输出，不只连接返回 Tensor。
循环外引用可以指向可变对象；引用不变不能证明对象内容跨迭代不变。
初始化输入、循环携带值、迭代局部值和退出值须沿原端口区分。
F4-B source recipe另以原F2 `SourceLoopTarget`连接局部子图的break/continue端口；对应共享循环消费自己的跳转，耗尽与break分开连接else/后继。suite只沿正常完成接下一语句。语句may-completion上界、局部产生规则与最终CFG/SSA是三种不同的证明范围；iterator引用不变不授内容不变或引用释放时序证明。
编译条件与运行状态也分开：`ReadCompilationOption`保目标的符号编译事实，不读取分析进程flags冒充目标事实。注解的声明、字符串化发布与后续请求沿原C1求值阶段连接；deferred来源不等于声明时已求出值。增强赋值的地址/读/运算/写由同一父语句安排，不能当作两次独立地址求值。
注解状态访问显式区分locals→globals→builtins、globals→builtins及class protocol cell；来源相似不能证明它们引用同一对象。查找消费当前world，不能冻结初始化时的容器。源码编译元数据不计为运行操作；重复编译展开的登记编号是编译上下文参数，不是多次执行或运行时任意选择。有限取值域已知而上下文未绑定时，保留参数及缺失证明；单值可静态折叠。
编译上下文通过原代码版本、优化策略、常量引用路径和指令偏移标识；不是动态Invocation。代码指纹保指令、参数/捕获布局、异常/位置表及精确常量树，含编译生成的slice/frozenset。源码参数可以拥有多个已证生产位置；可由某一具体位置机械绑定。没有保留的生产位置不证明消费者无用，未证路径也不能抹掉其他已证边。
共享模板另带`CompilationContextFlow`：每个区域有逻辑编译环境端口，每条入口引用按原步骤ID及类型字段/tuple序号定位。边区分调用、子表达式、代码声明、类型工厂、循环条件/正文/退出、完成处理与恢复；break/continue目标及实参里的区域引用不算入口。代码声明不执行正文。
`SourceTemplateGraph`进一步把不同局部recipe的子表达式/子语句接口连接起来：节点键为原occurrence＋purpose，并由源输入及版本限定；边保存调用步骤和有序实参，完成端口按kind/target/ordinal连接。节点引用已封存的原recipe，展开时核对原字节指纹；不复制正文、不展开循环，也不据此证明native调用或完整效果。这仍是F4-B接口图，后续canonical CFG/SSA另验。
当前F4-C的NORMAL_SUCCESS视图以这些既有操作/区域为节点，新增DATA、STATE、CONTROL、DECLARE边。端点沿原模板、区域/步骤ID及端口序号定位；调用/返回用相同CallSite配对，避免共享body的返回连接串到别处。循环携带量回接区域参数，不变量只接初始化输入。应用报错暂在契约外；迭代耗尽仍按正常控制连接。
源码recipe同时声明抽象world类型及异常ABI。核心操作的参数、正常结果和异常出口必须匹配；Call/ClassDef的显式与隐式参数、扩展解包、slice缺省项及tuple构造数目沿原F2字段推导，不能从待检查的端口数倒推。普通tuple、模板字符串段tuple和插值tuple是三种明确布局。无源码的shape-only样本可省略profile，但源码入口拒绝缺失profile；这些签名不是效果、清理或native准入证明。
同一模板的不同调用位置通过各自的边限定环境，循环重复使用同一静态边。进入函数、类或延迟求值器时更换代码环境；内联scope保源码身份而共享外层code owner。端口的source_scope表示当前逻辑代码环境，原语法namespace仍保存在region.context中，两者不能互代。编译事实使用者显式引用端口；这些是参数化接口，尚不是caller到原native指令位置的完整实例化证明。
区域 cut 查询列出已有跨边界依赖，不自动证明可外提、复用、删除或整体替换。
见 [公共依赖查询](../scar/analysis/program_dependencies.py) 与 [边界分析](../scar/analysis/program_regions.py)。

## 身份、版本与不确定性

CodeID 指向代码版本与位置；InvocationID 指向一次真实调用，两者不能混同。
对象身份、storage/allocation 身份、内容版本和逻辑来源也互不等价。
同一对象可以被原地改写；不同对象可以复制相同内容；同一 storage 可以有多个 view。
地址复用需要 allocation/epoch 约束，view 需要 offset/shape/strides；地址相等不证明同一分配。
引用来源路径解释“引用如何传入”，不自动证明读取结果、实际 callable 或数据内容相同。

F5按需引用视图用`(原Endpoint, 配对调用栈)`作为查询状态，不复制程序Operation；
alias、完整LEXICAL binding、实参、初始default、data return及构造结果使用不同边类型。
反向跨返回口进入调用时压栈，形参只匹配该调用再出栈；捕获环境及递归截断保留未决项。
`NEW_RESULT`是构造协议结果，`__new__`可返回旧对象；只有原OBJECT_NEW/EXPLICIT_OBJECT_NEW提供分配位置候选。
同一候选位置的字段SET→GET只产生带scope、实例、descriptor及版本条件的may-content边，保原world；
它不变成alias，也不证明当前内容。由此推导的方法接口独立于入口准入及runtime dispatch。
声明正文上下文以原函数body和类型化class-input为键，调用边显式连接原实参/形参、数据返回和world。
同键共享正文，递归保回边；它不是Invocation。descriptor包装的原调用、builtin查找和前序miss条件均保留。
非NORMAL连接仅声明创建边，不因创建generator/coroutine就进入正文。声明状态接点另表引用这些边，不改历史CallLink。
调用后状态视图复用原F4 STATE/CONTROL端口、guard及CallSite，不以事实表行号推断执行顺序。
原子操作的world输入→输出另记OperationStateTransition，表示状态变化，绝不是数据copy或内容不变。
迭代器耗尽沿原advance的RAISE world及匹配StopIteration控制退出；普通应用异常不因此扩大。
后继状态cut是保调用标记/分支条件的may路径；可达不证明must执行、当前版本、匹配上下文或效果已消除。
状态访问的地址另记原根端口＋有类型字段/索引selector，并保访问前后world。动态key引用原值端口，不按repr猜值。
仅同CodeScope的完整LEXICAL binding可用于局部路径推导；捕获、模块查找、循环及预算截断显式保前沿。
call-result是独立不透明根，不因参数来源相似就把返回对象或deepcopy输出当成原输入。
跨函数返回图分别保存world return、data return及引用路径依据。先沿已选择的声明上下文连接，再保留历史may-call的独立调用点；
引用路径未接通时只停止该引用的传递，world仍可返回。world返回不证明内容保留。图节点共享原body，不为循环迭代复制。
调用消费者另记原callee/位置/关键字/参数包端口、来源路径和形参route。字段投影是对根对象的数据依赖，不能变成根对象alias。
形参接线保原world输入/输出与函数创建种类；生成器创建不进入正文，未解析target、pack或构造协议不等于没有消费者。

正文值流保原DATA/STATE/CONTROL/DECLARE边，并为每个非结构操作保存原instruction及类型化输入/输出接口。
输入→操作→输出表示可能的数据推导，不是alias或LogicalVersion等价；零输入操作同样保留。
局部读写以完整(CodeScopeRef, LEXICAL Namespace)位置节点连接，避免writer×reader展开；跨作用域捕获和非词法内容另保边界。
DATA包含bool、协议值等，不只对象引用。轻量查询只传播DATA与操作的数据输入/输出，不以world序列污染全部后继值；
原world、调用配对标签、分支及循环回边仍在图中。该flow-insensitive may查询不证明平衡执行路径、当前状态版本或实际影响。
派生调用输入可另接原CallLink的actual→formal、world与返回接口；根形参→派生actual的may依赖仍在父值流图，不能拼成根形参alias。
历史may-target与当前caller上下文匹配分开；接到compiled函数的声明接口也不等于已展开或运行该正文。
普通源码与compile-context使用同一材料接口，按原catalog格式选择reader；compiled计划仍引用其原domain、行号、digest及编译profile。
正文展开用原函数端口去重，已有正文只存跨工件引用，新增正文才写本地表；入口分别保原binding/形参/world条件。
展开静态函数正文不选择动态activation；后续来源查询仍保may-dependency限制，循环仍用原回边。
调用上下文引用查询另以原incoming CallLink为条件：形参只沿当前栈顶接口回到它的实参，data return先压入该接口再由其形参配对弹出。
外层caller未选定时保边界，不合并其他caller；非词法namespace、捕获、deferred及构造结果各保原协议边界。
同一正文共享多个incoming接口；查询栈是静态路径证据，不是Invocation或循环展开。来源匹配与开放上下文分开记录，原may候选不被删除。
若引用路径得到原函数定义，可用原signature binder生成带路径条件的函数接口；函数环境仍来自原callee，不以CodeID替代函数对象状态。

构造是独立协议区域。SOURCE_NEW保cls/原参数/world，数据返回NEW_RESULT、状态返回NEW_WORLD；其结果可能是已有或foreign对象。
SOURCE_INIT从NEW_RESULT/NEW_WORLD入正文，只把world返回原调用；完整构造的数据仍来自new结果，init数据被丢弃。
OBJECT_NEW/OBJECT_INIT、foreign返回、new/type-test/init未决都保原stage/class及证据，不把pending无输出阶段补成完成路径或分配证明。
构造class输入只从单一ARGUMENT引用投影：init的NEW_RESULT给请求类的兼容INSTANCE，new的原class参数给CLASS_OBJECT。
兼容INSTANCE可能是子类；精确类型、MRO与override仍未证明。pack本身不当作单一class引用，无关参数包仍留在原接口而不增加类型缺口。
多个原构造entry可共享同一声明正文/类型上下文，其实际对象、world与entry条件继续由原connection分别保存。
构造兼容输入可作为声明成员展开的根；旧正文引用共享，新正文按source callable去重并按源码单元批量读取模板。
instance上的classmethod只有在绑定class等于记录source class的附加条件下采用该class参数；未确定子类分支另保前沿。

namespace来源图以原GlobalPort及待选择的属性序列为查询状态。源码slot写入只产生带namespace/版本/作用域条件的引用来源，
不宣称当前slot、对象或内容相同。编译exec的globals字典与普通source module分别保身份条件；compiled单元不进模块导入候选索引。
导入按原Import.module解释返回模块候选，requested_module保完整请求；所有路径/名称映射候选均保留。
GET属性选择与IMPORT_FROM的registry fallback分别记录，属性receiver与结果不成为alias。
标准`import a.b.c`返回`a`时，父包上安装子模块的每个已匹配属性前缀另保来源边；仍需当前slot及标准导入条件。
namespace来源子图按原端口共享，使用点以原callee查询/state锚定，因此各caller栈不合并。函数接口保原调用ABI与环境版本条件。
进入被解析函数正文时，outer stack取原调用者查询的根；factory内部的来源stack仍是来源证据，不能代替调用者的实参frame。
派生接口的data return另有完整caller-stack许可域；读取同一静态result端口必须匹配该域，不能把某个caller得到的目标推广到其他caller。
历史may接口保原开放条件。所有正文共享，成员递归路径保边界/原回边，不通过迭代复制正文。
源码声明图按原callsite及CodeScope覆盖完整选定源树，namespace路径可在没有选中incoming的情况下单独分析；它不伪造Invocation或scope激活。
同一原callsite的caller查询另保调用栈，两种视图不能相互冒充。生成绑定按完整路径连接，保所有overload和原source ABI；转换依赖不当作alias。
分析状态（尚未选定、尚未证明）保在请求证据及状态字段，不能当作运行时guard与“选择该binding”合取。
生成绑定可独立链接到精确版本的canonical ATen接口。实参→parser转换→native端口是推导依赖；wrapper返回形状与native返回slots分别保留。
source world→native world、native normal world→source result_world也是依赖；wrapper前后effects开放，不能折叠为同一StateVersion。异常边界留在canonical接口。
一个native整数数组参数可依赖多个显式位置实参，聚合单独标记，不可只取第一个实参；fixed/optional列表的广播或vararg选择未证时保转换OPEN。
词法名字的事实不是执行次序：WRITE记录的value是RHS，真实写站点须锚定原AccessBinding及world；参数是函数入口的独立定义。
到达定义以原控制端口＋匹配recipe调用栈为状态，成功WRITE/DELETE做GEN/KILL，未知world效果弱加入开放来源；循环通过回边固定点求解，不展开迭代。
不同词法槽的传播结果引用共享函数控制边/操作和共享名字锚点；这些原图记录不按分析的名字数复制，分析器也复用原函数值流投影。
读取在READ入口观察，合并所有保留上下文的may定义。只有原C2本地slot所属环境匹配、锚点及控制求解覆盖足够时，正常路径查询才排除不可达的显式写；捕获和未知入口保开放。
原声明图不覆盖或删除。NORMAL_SUCCESS过滤另带路径条件，不能从该投影排除应用异常/resume路径或证明当前内容、纯性、dead work及优化合法性。
原生Tensor/Device/Generator类型投影通过原归一化依赖接入硬件图；Optional/List投影不是实际元素、分配或副本。native输出到Python包装结果也只是依赖，不把整个Python容器置于GPU。
host执行、native executor与目标内存池分别保候选；保留CPU/GPU/内存/存储拓扑不等于证明程序使用这些资源。source文件所在磁盘也不是运行I/O。
类基项保原求值端口、顺序和CLASSES fact所属创建scope；packed ABI仍含body/name，不能直接当base列表。
namespace图的class-definition来源是附条件的源码声明产物，不是运行时class或MRO证明；当前版本、builtin及动态属性缺口仍逐字段保留。
继承成员记录原有序base槽及完整来源路径；每条descriptor选择可追至记录，不选择第一条基类或写入作为实际MRO/当前成员。

源事实材料与程序的数据Materialization分开。旧集合相对证据URI通过`FactMaterialRoute`沿原`unit_parent`目录选择定位到primitive分片，
核每级目录和叶stored/decoded收据、unit及原locator；不按同哈希任找文件。compiled事实保原variant unit与JSONL records/0。
图保原证据键，`FactMaterialResolver.resolve`提供可实际读取的物化引用；源材料路由不声明对象alias、内容等价或运行I/O。

[逻辑值 IR](../scar/ir/v2/values.py) 已定义 LogicalValue、ValueVersion、ProvenanceRecord、
Materialization 和等价声明，用于分开逻辑来源、推导关系、版本及物理表示。
这些类型的存在不代表任意 deepcopy、transform、CPU/GPU materialization 已自动统一溯源；
当前静态值/引用分析与运行观测也尚未全面接通到该逻辑值体系。
不能以 Tensor ID + `_version` 作为通用内容证明：NumPy 共享写入和 inference tensor 等需另行约束。

UNKNOWN 应落在确实未知的字段、效果或关系上，不能吞掉已知操作、端口及 shape/dtype 等属性。
已知、条件成立时已知、符号值、候选集、未知事实，与未分析/不支持/材料缺失/预算耗尽分开报告。
求解达到不动点只表示当前规则不再产生事实，不证明整个程序已覆盖或所有目标已解析。
未见消费者不证明无用；未见异常不证明不会抛错；没有记录写入不等于 NONE。

脚本入口契约引用原源码版本、root及namespace读取端口，并声明argv、cwd、环境和初始globals。
argv/environment记录可变位置的初始内容，不作为不可变tuple/dict常量。初值字段推导受整个入口契约约束。
编译上下文保filename/mode、请求flags、继承策略、source有效future位和优化级别；未知继承不是0。
同路径/同bytes不保证同一编译上下文，compile也不等于执行；parser-only flags与运行代码flags分开。
compile/exec边界按原namespace/reference来源识别，保留全部actual、world和caller scope；同名局部变量不因此成为builtin。
语言默认值、原F2直接literal和一般source value分别记录，不把单个may候选升级为唯一值。
compile结果到exec输入只增加条件引用关系；payload解释、有效编译版本和body绑定需要分别完成，不伪造root展开。
文本候选与标准str(path)可供给filename；编译使用显式继承flags及dont_inherit=True隔离分析器上下文。
CompiledSourceCandidate保存代码值digest与独立source-only控制版本；相等也不自动证明F4对应，不同则不能沿用旧body。
编译变体沿C1→声明/绑定→带flags原生符号→C3对应→F4生成，命名空间由源码和编译输入限定，调用见证另存，不按调用复制body。
F4复用原规则，只为其编译查询绑定局部服务；根future策略与有效flags一致。新图和原source-only图可共存，exec的namespace/world路由另行接线。

有限标量字段沿原scope、参数/默认值、数据返回、模块/属性及content关系传播；world、环境及参数包不作标量alias。
`ScalarTransferGroup`保父表行、原端口及条件，以线性大小私有join传递；join不是程序节点。字段上限4，宽化保open，不从singleton may集证明常量。

content的READ_SELECTOR_V1标签表示读取选择条件；未知位置的写入连接全部已订阅selector。
None用于整体/未知选择或未指定selector的直接依赖，literal None键仍有独立PythonLiteral。
dict.get默认值保直接来源边，不广播为容器内容；编码因子只分解已有关系，不据标签证明版本或身份。

算子结果的声明类型由`ValueShape`及`ReturnTypeEvidence`连接原结果端口，元组字段和序列元素有显式投影。
这些记录是Value的条件属性，不能代替ObjectID、StorageID或LogicalVersion。序列转成list/tuple只传播元素类型摘要。
绑定/未绑定方法的receiver独立保存，原调用的实参、参数包和输入/输出world保持原样；手写接口没有生成映射时不虚构ATen selector。
语言运算保留原Operation及有序operand/world端口；`DeclaredOperatorCall`连接协议分支、声明及有条件的wrapper实现。
stub契约与注册实现是不同依据，不表示发生两次计算；C++注册目标与生成wrapper的实际符号对应，不能按Python名字猜算子。
隐式实例调用通过类上的`__call__`接线，查找中间结果不写回原对象端口；反射优先级、NotImplemented与原地fallback保留条件。
协议依据为固定[Python 3.14.7数据模型](https://github.com/python/cpython/blob/v3.14.7/Doc/reference/datamodel.rst)，不是运行观测。
属性接口单独保存GET/SET/DELETE/IMPORT_MEMBER、receiver、输入/输出world及读取结果或赋值RHS；不伪装成源码CALL。
property accessor复用`FunctionConnection`的参数/环境/状态接线。getter返回连接原属性结果，setter/deleter丢弃Python返回值。
字段、类namespace及模块namespace路由分别标型；字段fallback的descriptor/MRO条件未获证时仍是may关系，不授对象身份或版本等价。
实例字段以`allocation来源＋receiver class＋member`分区；同一源码分配点可能返回多类，不能只保分配端口。
`AttributeContentLink`显式保存SET RHS→GET result及原读写表坐标，原world仍从站点查询；相同抽象内容的不同写入也保留。
它是可能供给关系，不选择读取版本，不证明先后顺序，也不因DELETE或未见写入而清除其他路径的内容。
密集content边可按完全相同的目标邻域存为`ContentFactor`；因子是连接关系的存储表示，不是新的源码动作或数据等价证明。
源索引投影环不能逐位置展开：增量队列处理内容变化，下降闭环保留start/stride/path；UNKNOWN_POSITION是保守位置宽化，原投影边仍在。
类调用分为`__new__ → 返回类型判定 → 条件__init__ → 返回`。`ConstructionPort`以原调用结果和原class端口为锚点，
区分分配结果与分配后world；它是派生协议接口，不伪造源码`G.Port`。初始化消费分配后world，丢弃init的数据返回。
已声明自定义new时不预先生成默认实例；默认object分配要求源码继承链及namespace条件。MRO/metaclass仍是条件，不当成已观测目标。
变参formal的tuple/dict内容与每次绑定的有序实参分开；只有原构造/协议证明形状封闭，才展开调用参数包，不从may内容数量推断长度。
参数包不封闭时，已知函数体仍可在`CALL_SIGNATURE_ACCEPTANCE`条件下接入；`ArgumentProjection`分别表示位置元素、命名元素及剩余参数。
`SYMBOLIC_PACK`与`CLOSED_PACK`分开，默认值缺席条件、原包和未决需求保留；投影传播may内容，不建立包对象到参数的alias。
这只补充条件静态图，不证明调用实际发生、绑定完整、路径可满足或变换合法；生成器/异步创建仍不激活body。
同步生成器分离创建、取iterator与advance：创建保存引用路由，advance才接body，并使用当前推进的world。
yield导出接循环元素；sent输入与terminal return分开，正常return经StopIteration接口表示耗尽，不当作元素。
挂起/恢复旁表引用sealed F4原端口及摘要；稀疏F5没有的world端口仍用其原G.Port，不伪造源码身份。
F4局部图先按源码单元投影为`UnitSourceInterfaces`，再由F5连接；摘要是原图接口表，不另建一套程序节点。
迭代保全部完成端口，惰性body按原code owner选择挂起；映射保确切协议、world及端点映射资格。
非直线模板、无匹配协议、未映射端点与缺摘要分开；这些状态均不授无副作用、参数包闭合或值等价证明。

效果至少区分 reads、writes、allocates、frees、aliases、escapes、RNG、异常、外部及顺序影响。
未知效果保持开放；异常前已经发生的写入、IO 和清理不可回滚成“无效果”。
`.eval()` 不证明纯函数，推理也不默认无 autograd；模式、hooks、buffers 和可变参数属于相关状态。
见 [效果模型](../scar/ir/effects.py) 与 [状态地址](../scar/ir/program/state_addresses.py)。

## 静态结构与动态证据

静态前端依据保存源码、语言版本、编译来源和受支持的库契约建立结构、可能路径及条件关系。
动态层只补必须运行才知道的实际 callable、entry、实例、运行路径或资源事件；两者保留不同依据。
一次观测可以选择该次调用的目标，不能关闭其它路径、将动态目标集合当全集或授权优化。
动态补图以静态图的未决接口为采集目标，限定时间、调用次数及新事实量；函数/循环始终复用静态模板，重复迭代不复制正文。
同一调用位置只有出现新目标或所需状态事实时才增补证据。达到本次需求或预算即停；未观测分支及失效条件继续保留，不能声称全路径已观测。
静态/动态按事实分工，不按文件边界：已知跨文件边可静态连接，同文件多态也可能需要观测。
运行 code 与原实现图的连接须核完整 descriptor、compiler path/profile 和已记录的源码版本，不能靠 qualname/行号猜测。
没有历史全文件指纹时，当前源码仍可建图；匹配函数 Code 只证明该作用域的对应，不证明历史文件、父模块或运行环境。
缺失 body 可由真实 code 证据驱动按需静态展开；已有规范图、原 ID 和端口继续复用。
见 [调用观测](../scar/analysis/observed_call_bindings.py)、[函数接口](../scar/analysis/observed_function_interfaces.py)
与 [按需展开](../scar/analysis/observed_body_demands.py)。这些接口不是静态全程序闭合证明。

## 语言、native 与资源边界

Python 建模遵守求值顺序，区分定义阶段与调用阶段、绑定与对象内容、全局/闭包/类命名空间。
import 的 module 引用、namespace 和初始化状态分别表示；属性访问描述 lookup 请求，
不能直接当作 `__dict__` 读取或推断其结果身份。类定义最终产物取 decorator 链返回值，不保证是类。
导入的请求参数和名字投影可静态保存为已知字段；实际importer/module实例、registry命中及初始化另属状态/证据。IMPORT_FROM保导入回退语义；star import保动态namespace写范围，不能当作已知静态binder列表。
短路、比较、索引、赋值、调用及解包都可能调用用户代码、产生部分效果或抛错。
受支持的 try/finally/with 保留 pending completion 和清理顺序；generator/async 创建与恢复分开。
函数定义的创建、注解请求与调用激活分开，docstring属于编译元数据；decorator可返回任意对象，最终绑定沿实际decorator结果，不保证仍是原函数。初始defaults和cell引用保持来源，不承诺后续内容不变。
泛型工厂使用原type-parameter子scope；外层已求出的defaults通过显式端口进入。TypeVar等对象、惰性求值器、初始化绑定和参数tuple分别表示；bound/default属于后续请求，不能因其源码出现在声明中就提前求值。
复杂异常组、模式匹配、动态生成代码及部分异步/委托协议仍可能有明确前沿，不能宣称全语言闭合。
见 [源码降低](../scar/analysis/program_lowering.py)、[控制结构](../scar/ir/program/structured.py)
与 [恢复协议](../scar/ir/program/resumption.py)。

PyTorch/native 边界可以声明参数、结果、状态和可能效果；这不等于已证明 ABI、alias 或 kernel dispatch。
Python → operator → runtime API → kernel 的每条跨层连接需要对应契约或真实证据，当前尚未完整覆盖。
CPython调用协议已有共享声明子图：实际callable与原显式实参作输入，输入/正常/异常world分别保留。
协议输入和声明完成端口不生成Invocation；条件C ABI描述与真实实现进入、C参数、kernel执行分别表示。
不能将 native 节点无依据展开为物理调用，也不能因缺实现源码就删除已有输入/输出与状态接口。
见 [native 接口](../scar/ir/program/native.py)；目标止于可指导程序改写的 runtime/kernel 边界，不下钻指令。

资源要求与真实资源实例分开：静态 CPU/GPU、主机/设备内存、文件/存储端点、stream/event 约束，
不证明实际设备型号、DRAM/HBM 容量、SSD/NVMe 拓扑、allocation 或数据搬运已经发生。
同设备 `.to()` 可能不复制，`expand()` 可能是零步长 view；host 返回不等于 GPU 完成或结果已可见。
queue/enqueue、执行、完成和跨 stream 可见性不能合并；没有证据不能补造同步。
保存视频与保存 Tensor 都沿 buffer、表示转换、编码/序列化、写入及 finalize 等操作表达，
不需要人类用途分类；只在已支持的协议范围内声明相应读写、生命周期和异常效果。
OS FD/OFD 表、驱动内部结构和硬件指令不是当前要求重建的实体，原生效果边界仍须保留。

已实现的是上述强类型基础、受支持源码降低、共享层次查询及部分静动连接；尚未完成的是
全 Python/native 协议覆盖、统一逻辑溯源和所有跨层依赖的自动闭合。实际验收范围见 [STATUS](STATUS.md)。
架构组织见 [ARCHITECTURE](ARCHITECTURE.md)，后续只能在这些边界内扩展，不把设计目标当成现有能力。

exec的连接区域保留命名空间选择、条件builtins插入、closure检查、audit、共享根调用及释放阶段；
正常结果是None，根body返回值只进入discard。显式globals且locals缺省时二者共用原引用；
默认优化frame locals是新字典快照。此协议连接只覆盖正常成功路径。
命名空间接口分别保留ROOT_LOCALS、ROOT_GLOBALS、ENV_GLOBALS、BUILTINS、词法绑定及类映射，
不把exec字典登记成module。名字访问保原C2有序lookup、WRITE/DELETE目标及F4 world；
函数globals保实际创建参数与ReferenceEnvironment来源，builtins按frame入口/函数创建时选择。
内容边保原容器成员、key、赋值端口、引用路径及读写world；有条件的may-reaching边不是常量证明。

实际入口的编译context与source-only输入分别持有共享图。exec字典不进入import registry；
caller frame globals须由原frame/capture关系绑定，不能以源码module名代替其身份。
builtins在根frame入口或函数创建world选择；选中的map内容保普通读依赖，标准fallback单独保guard。
类关系查询只在单次查询中共享DAG子问题，依赖变化后重查；不缓存过期的False/UNKNOWN结论。

FrameGlobalsBinding连接原函数factory、选中callee、创建world与frame globals引用；根namespace
由原globals/locals formal输入描述，字典view不是新的allocation，也不是module对象身份。
StaticInputPort以输入contract版本和字段路径标识声明初值，独立于原源码端口；content因子可引用该
外部输入端口。初始字段版本不等于当前内容不变；普通名字访问和字典读写、浅拷贝保持同一内容依赖。

新增依赖源码从F0→F4进入独立provider；F5目录按原source、compiled context、新source的顺序追加。
已有qualified端口和数值offset不变，源码正文及局部接口仍向各自父收据读取。compiled context只由exec边激活，
不成为import候选；同module的不同源码保may候选，不以路径或名字合并身份。源码准入、body激活、实际调用选择和字段值求解是不同事实。

F5的纯引用transport可在已安装的有向copy约束中迭代闭包，包括已准入alias、参数及数据返回，不必逐条线等待普通事件队列。
它只传播已有抽象token，不计算目标操作或合并物理storage；原端口、边和普通事件保留。
闭包经正常add可提前触发原有module激活，工作量另计；当前不宣称全部顺序敏感transfer的固定点等价。

下一输入层分开记录三件事：数据材料节点（scalar/map/seq、原bytes/tag/span和子引用）、
版本化组合操作（defaults/package/override及lazy引用）、与原call actual/formal/world绑定的输入候选。
map/seq不是PythonLiteral；mandatory-missing、null、缺键和未知字段不混用。解析材料不冒充程序执行事件，
组合结果也不能越过deepcopy、删除和callback效果直接冒充当前cfg。文件内容版本、逻辑组合版本与物理对象身份分开。

数据材料的DataNode表示scalar/map/seq定义，DataReference表示一次源码出现并携带独立span；
children/root引用reference ordinal，reference.target引用node ordinal，因此alias共享/循环不展开。
材料层的representation_literal只解释YAML表示；`???`和`${path}`此时仍是字符串。
已安装OmegaConf loader的完整函数AST与工具bytes固定到profile，仅复现resolver和内建scalar解释，不调用自定义构造器。
每材料独立保存source.bin、node/ref/obligation三表和小header；普通读回核全部收据及图不变量。

配置请求由版本化库API的SourceCallLink识别，不按workload名称或参数变量名选择。
参数候选保原formal/actual、literal来源及有向alias路径；factory到decorator及task创建也保独立路径。
CLI值由声明输入端口及明确的option projection推导，初始argv不冒充当前argv。
文件候选优先用实际compile context filename；环境覆盖、搜索插件及输入变更未闭合时继续带条件。

配置组合以有序ConfigurationStep保存根版本链，MERGE_MATERIAL引用共享材料及package，
只排除该文件根defaults；不展开所有字段成巨型字典。ConfigurationDependency保原reference与子实例，
显式package_override和已解析package分开；同文件不同package共享材料，不共享实例。
组override是选择约束，不是在声明位置进行merge；缺失provider以OPEN_PROVIDER及obligation保留。
库隐式根、每文件同名schema、CLI和lazy引用尚未闭合时，局部payload顺序只在列出的条件下成立，
不得把组合版本、已解析cfg或运行时对象身份等同。

初始argv覆盖以独立表达式图及有序写入保存，原输入端口、完整token、字符区间、quote和类型均保留。
复用固定版本的ANTLR生成语法工具，不初始化Hydra、不调用visitor或用户函数；CALL/SWEEP保结构和未求值义务。
覆盖图的版本0显式引用组合图的选中根版本，后续写入各有input/output版本；这些ID只在对应工件内定位。
普通字段候选与组选择保不同条件，missing/插值在此层仍非已解析值；不把初始argv投影冒充当前argv或当前cfg。

输入值层把上述步骤编译为共享代数DAG：EMPTY/INPUT/OPEN_PROVIDER/EMBED/MERGE/ASSIGN/UPDATE/DELETE。
每个根版本只引用已有表达式；字段投影以(root expression, selector path)定位，保原材料/argv来源、依赖及条件。
映射/序列另有members_complete，不因存在几个已知字段便认定整个容器封闭。merge missing保旧值与scalar assign设missing分开。
插值复用固定生成语法；惰性引用使用该查询选中的根和安装后的父路径。动态key先重建路径再拆分，循环保依赖环。
中途地址读取有独立read demand：update可指旧snapshot；merge内部尚未降低的状态点保None，不冒充最终root。
未知provider、schema、当前argv与未支持的别名效果继续阻止无条件结论；本层是输入来源图，尚非任务当前cfg或物理对象身份。

SourceStateProjection把输入内容候选连接到原调用的(receiver reference, result_world)，
同时保存world_before与独立data_result；返回None的修改操作也能产生新内容版本。
接点保原call/attribute坐标及所属scope的alias证据。声明接点不证明调用激活、输入版本匹配或后续任务内容，
不得越过callback、deepcopy、删除及环境效果直接向形参注入字段。

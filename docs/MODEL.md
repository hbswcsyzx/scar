# SCAR 程序模型

SCAR 用有类型、可展开的依赖图描述程序，为后续化简保留必要结构与正确性条件。
当前阶段到自动建模、建图和查询为止；图中出现重复或候选，不构成变换许可。
范围、已知关系及缺口必须如实列出；缺口存在不算相应部分已完成。
当前没有做到所有 Python 行为的精确静态求解。

## 五类核心实体

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
同一模板的不同调用位置通过各自的边限定环境，循环重复使用同一静态边。进入函数、类或延迟求值器时更换代码环境；内联scope保源码身份而共享外层code owner。端口的source_scope表示当前逻辑代码环境，原语法namespace仍保存在region.context中，两者不能互代。编译事实使用者显式引用端口；这些是参数化接口，尚不是caller到原native指令位置的完整实例化证明。
区域 cut 查询列出已有跨边界依赖，不自动证明可外提、复用、删除或整体替换。
见 [公共依赖查询](../scar/analysis/program_dependencies.py) 与 [边界分析](../scar/analysis/program_regions.py)。

## 身份、版本与不确定性

CodeID 指向代码版本与位置；InvocationID 指向一次真实调用，两者不能混同。
对象身份、storage/allocation 身份、内容版本和逻辑来源也互不等价。
同一对象可以被原地改写；不同对象可以复制相同内容；同一 storage 可以有多个 view。
地址复用需要 allocation/epoch 约束，view 需要 offset/shape/strides；地址相等不证明同一分配。
引用来源路径解释“引用如何传入”，不自动证明读取结果、实际 callable 或数据内容相同。

[逻辑值 IR](../scar/ir/v2/values.py) 已定义 LogicalValue、ValueVersion、ProvenanceRecord、
Materialization 和等价声明，用于分开逻辑来源、推导关系、版本及物理表示。
这些类型的存在不代表任意 deepcopy、transform、CPU/GPU materialization 已自动统一溯源；
当前静态值/引用分析与运行观测也尚未全面接通到该逻辑值体系。
不能以 Tensor ID + `_version` 作为通用内容证明：NumPy 共享写入和 inference tensor 等需另行约束。

UNKNOWN 应落在确实未知的字段、效果或关系上，不能吞掉已知操作、端口及 shape/dtype 等属性。
已知、条件成立时已知、符号值、候选集、未知事实，与未分析/不支持/材料缺失/预算耗尽分开报告。
求解达到不动点只表示当前规则不再产生事实，不证明整个程序已覆盖或所有目标已解析。
未见消费者不证明无用；未见异常不证明不会抛错；没有记录写入不等于 NONE。

效果至少区分 reads、writes、allocates、frees、aliases、escapes、RNG、异常、外部及顺序影响。
未知效果保持开放；异常前已经发生的写入、IO 和清理不可回滚成“无效果”。
`.eval()` 不证明纯函数，推理也不默认无 autograd；模式、hooks、buffers 和可变参数属于相关状态。
见 [效果模型](../scar/ir/effects.py) 与 [状态地址](../scar/ir/program/state_addresses.py)。

## 静态结构与动态证据

静态前端依据保存源码、语言版本、编译来源和受支持的库契约建立结构、可能路径及条件关系。
动态层只补必须运行才知道的实际 callable、entry、实例、运行路径或资源事件；两者保留不同依据。
一次观测可以选择该次调用的目标，不能关闭其它路径、将动态目标集合当全集或授权优化。
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

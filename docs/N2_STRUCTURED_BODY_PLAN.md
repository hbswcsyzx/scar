# N2：完整程序建模与 STRUCTURED_BODY_V1

状态：**Proposed；实施前设计，本文新能力均未验收。**

日期：2026-10-16。设计审查基线为 `8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`。
新工作树 `/tmp/scar-structured-model-280qf4mi`。本计划的最终目标是原始程序从
**启动、加载模型/数据、推理与环境推进，到保存视频和其他可观察输出**的自动
建模；循环与局部绑定是第一批实现依赖，不是最终目标的替代品。

代理负责自动验收，用户不需要手工补图、逐参标类型、提供纯函数/常量名单或
指定 LeWM 中哪些函数要特殊处理。本文不引入新执行 backend 或新的 detector。

相关依据：[CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md)、
[N2_FRAME_LIFETIME_PLAN.md](N2_FRAME_LIFETIME_PLAN.md)、
[N2B1_PLAN.md](N2B1_PLAN.md)、[N2_CALL_BINDING_PLAN.md](N2_CALL_BINDING_PLAN.md)。
本计划承接旧循环提案；新 binding API 以第 5 节为准，不采用旧提案中的
`UnboundOrigin`。独立审查 artifact 位于主树
`artifacts/experiments/b1_call_operands/model_connection_audit/`，包括
`body_preservation_review.md` 与 `end_to_end_type_review.md`。

## 1. 目标和四个独立验收维度

| 维度 | 必须回答的问题 | 不能冒充它的证据 |
| --- | --- | --- |
| Structural coverage：结构覆盖 | 原始源码的定义、控制、调用及每个有序使用位置是否在图中有精确端点？哪些没有？ | AST atom 被统计、函数有 opaque 外壳、trace 出现了函数名。 |
| Semantic precision：依赖精度 | 引用、内容、绑定、状态、异常、顺序和外部交互的规则是什么？哪些依赖仍未知？ | 四类节点标签、相同对象引用、unknown effect 记录存在。 |
| Execution correspondence：执行对应 | 某次 invocation/attempt/load/completion 对到哪个源节点、core Use、控制/循环发生位置？ | 静态源码有调用、同 code、同 reference token、一次运行的时间先后。 |
| Transform authority：变换权限 | 被替换子图的所有必需输出/状态/顺序/交互及合同是否闭合，证据是否支持具体改写？ | 查询能穿过一条引用边、测试数量、程序执行成功、图更大。 |

“完整程序结构”仍可包含明确外部接口与未知协议；这不叫“完整精确依赖图”。
只有未知范围没有穿过待变换区域及其观察根，才可对该区域申请具体变换权限。
本计划各建图阶段均保持 transformation authority 为 false。

## 2. SG、EEG、OIR 的连接和类型边界

- **SG / Program：** 定义及其组合结构。统一 core 的四个顶层结构家族是
  `Operation / Value / StateLocation / Region`。输入/输出是端口角色；常量与
  不变量是有范围的事实。操作不是按代码行或业务名六选一分类。
- **EEG / Execution：** 真实 operation instances、load/argument occurrences、
  dispatch/completion、线程/进程、资源/物化/观察和证据。静态 ValueID 在循环中
  可以有多次动态出现；不能把它们合并成一个运行时值。
- **OIR / Optimization：** 从已连接程序图选出的替换区域、边界 ports、delta、
  contract、证据及成本。OptimizationRegion 不等于 Program Region；前者不能
  靠包装集合补出缺失的程序依赖。

**所有图并不只有四种类型。** 四个家族不能替代完整类型系统。Execution 层有
Resource、OperationInstance、StorageAllocation、StorageRegion、Materialization
等一等实体；OIR 有 region/port/delta/contract。需要新实体时按身份和不变量增加，
不以“四”这个数字限制设计。

当前具体缺口和落点如下。D=设计可表达，I=已有实现，A=已自动生成并接通，
T=该全过程有实测证据；“部分”不算关闭缺口。

| 类型/接口 | 规范落点及最低不变量 | 当前 D / I / A / T |
| --- | --- | --- |
| reference/data/state/local binding | Value 强类型；binding 指槽的绑定状态，state version 指 location 的逻辑版本 | D 可表达；I 前三类已有，binding 为本计划；A 旧有限子集；T 新门未验收。 |
| FunctionObject/environment/cell | 引用实例、隐式环境端口、globals/defaults/cell owner 和版本；不是额外 Python formal | D 有设计；I/A 完整接口缺；T 未闭合。 |
| file/handle/encoder | path 值、handle 引用、open/offset/buffer/content/namespace 状态、写/flush/close 完成；编码器是有状态协议 | D 可表达；I legacy FILE/resource 类别存在但完整协议缺；A/T 当前全过程未闭合。 |
| RNG/external environment | generator/外部 owner、读写前后状态和交互顺序；未知别名不能因不同 ID 判为 disjoint | D 可表达；I coarse world/legacy effect 类别已有；A 部分；T 未闭合。 |
| storage/view/materialization | logical content/version 与 allocation/strided region/materialization 的 typed join，生命周期与 alias overlap | D/I legacy records 和部分构造已存在；A 未接通完整新 core；T 本门未验收。 |
| GPU/stream/async completion | Resource 与 execution instance；issued/ready/failed completion 和等待/消费边，不以 host return 当 ready | D 必须补齐；I resource 类别已有，program 只有 NORMAL/RAISE，legacy ready_event 仍为可空字符串；A/T 不完整。 |
| autograd/mode | mode state、求导关系、detach/view、数值和梯度合同 | D 有要求；I/A/T 完整接线尚未实现。 |
| observable outputs | 返回值、文件/日志/交互历史、异常、清理、顺序和所需完成条件分别作为根 | D/I 有部分合同；A/T 本全过程未闭合。 |

目前没有证明需要第五种 Program core 顶层结构家族；也没有证明四个现有类已
具备所有合同。强类型 completion value/port、resource identity、environment
接口等必须实际实现和校验，不能用 label、任意 metadata 或一个 unknown world
名称代替。如果后续接口不够，必须扩展模型并版本化。

### 2.1 必须实际连接的跨层接口（Proposed，尚未实现闭合）

完整 SCAR 模型由 Program、Resource/Representation、Execution 与 OIR 的强类型
关系组合。Program 的四个家族不覆盖其他图的全部实体，也不要求把资源身份塞成
StateLocation 的 label。现有资源记录需逐项迁移/接线，以下是验收接口：

```text
Operation inputs/outputs + state versions + completion ports
    --implementation correspondence-->
Execution instances + Resource identities + Allocation lifetimes
    --materialization correspondence-->
Logical data version + representation + storage region + readiness
```

- **文件与句柄：** 路径是值；路径绑定、文件内容、句柄位置/开闭状态是不同
  状态位置；文件及打开句柄各有身份和生命周期。两个路径可能指向同一文件，
  两个句柄可能共享/不共享 offset。磁盘读取连接具体内容版本；rename、重开和
  图外修改有失效关系，不能以 path 字符串不变证明内容不变。
- **逻辑值与物理表示：** 来源 lineage 不是数值相等证据。解码、归一化和编码
  是有输入及规则的 Operation；view 是访问关系；copy 是否保持逻辑版本需要
  明确合同。Materialization 必须连接 value version、representation、allocation/
  region、producer 与 completion；ObjectID/StorageID/采样值不代替这些关系。
- **设备与完成：** device/stream/线程/存储是 Resource；handle 值通过有类型的
  对应关系引用它们。Host return、enqueue、device completion、失败、等待和消费
  必须有各自事件端口；跨 stream 的消费者需要 ready/happens-before 证据。
  ready_event 字符串或 trace 时间先后不能充当这个合同。
- **生命周期与所有权：** 创建、取得/保留、转交、逃逸、释放、flush、close 是
  有输入、状态和完成边的操作/协议。引用释放、底层 allocation 释放、文件可见、
  持久化完成分别表达；不能把它们折成一个 free/ready 布尔值。
- **挂起与恢复：** generator/coroutine 是有实例状态的协议：create、enter、
  yield/suspend、resume/send/throw、close/cancel、normal/raise。未耗尽的 iterator
  与已耗尽的 iterator 状态不同；闭包/callback 保留的引用、执行许可与环境版本
  不能因栈帧返回而消失。

checkpoint 加载必须展开为外部版本读取、解析/反序列化、对象/分配生命周期和
模型状态写入；不能只挂一个“输入”标签。推理要连接权重/缓冲/RNG/模式状态和
物化就绪。视频保存要连接帧来源、编码器前后状态、输出顺序、文件前后版本及
flush/close 完成。通用类型相同不意味着这些操作的具体效果或等价规则相同。

类型体系是否足够以这些关系能否有无歧义的端点及可核对的不变量验收；现有类
装不下时扩类/接口。AST 占位、opaque 外壳和 generic metadata 不作为通过证据。

## 3. 真实全过程对门的要求

LeWM 只作为原始源码压力案例。以下位置用于审查和验收抽查，不成为构图规则：

| 阶段 | 原始源码证据 | 所需通用能力 |
| --- | --- | --- |
| 启动/加载 | `run_inference.py:17–75`；`eval.py:49–97`；`wm/utils.py:77–93` | env/module 初始化、compile/exec、decorator/default、文件/config/checkpoint、构造/参数状态写、设备和模式。 |
| 推理 | `policy.py:349–434`；`solver/cem.py:145–260`；`wm/lewm/lewm.py:58–108,126–151` | 循环/分支/解包/写入、method/keyword/pack、RNG、缓存状态、alias/表示、GPU 完成。 |
| 环境/帧来源 | `world/world.py:403–446,506–550` | generator suspend/resume、closure 回调、环境状态写、数据集来源、图像 copy。 |
| 输出 | `world/world.py:555–563`；`plot/video_utils.py:8–64`；`eval.py:157–169` | 多层循环、comprehension、try/except、writer append/close、文件/目录、with、日志/metrics 输出。 |

除 run/eval 外，路径相对于 `stable-worldmodel/stable_worldmodel/`。
加载→推理→视频的结构入口/输出必须都在验收分母里。只支持其中几个循环的
阶段可以单独通过，但不得据此报告“全过程完成”。

保存 Tensor 和保存视频使用共同的输入读取、表示转换/编码、外部写入及完成
协议；不新增按业务名字区分的 node kind。编码器缓冲与 frame 顺序、句柄状态、
close/flush、异常后的部分输出仍是必需依赖，不能因共用类型而省略。

## 4. 新 profile 与当前断点

新增 **`BodyLoweringProfile.STRUCTURED_BODY = "STRUCTURED_BODY_V1"`**。
它复用自动 discovery、typed demand、PreparedSource、source IDs、全局预算和
ProgramGraph。它不改变 `LEGACY / BOUND_FORMALS_V1 / BOUND_FRAME_V1` 的算法和重放。

旧 `program_lowering._Builder.run` 遇一个 `_Unsupported` 就丢弃整个 core graph
和 operation/value/use/call links；source inventory 虽在，调用端点不存在。
新 profile 用有独立合同的递归 lowerer，先解决已声明语法范围内的真实控制流，
并为允许局部降精度的操作保留未知效果，不能将一个 body 的每处调用全部抹掉。

方案选择：不直接扩旧 BOUND_FRAME；不增加一套不接 core 的 AST 图。新 profile
继续生成有 entry、SSA、state ports 和完成路径的 Region。循环本来可由 core CFG
表达，新增 binding Value/Type 与规范规则；不增加 LOOP/BREAK/EXHAUSTED 顶层实体。

诊断性的 opaque 函数外壳可以记录“主体尚未展开”，但它不能计为 body-preserved，
也不能使其 span 内的 Call 被计为 core-covered。首批不支持的控制必须明确报告
缺口，后续按 G4 扩展；不能通过把 AST 任意摊平来完成 G2。

## 5. 局部绑定：规范类型与校验

下列 API 是本门的类型方向；具体合法形状由 core validator 与源码 profile
共同校验，label 不授予规则：

```text
LocalBindingValue(id, region, origin, slot: ValueSlotID)
LocalBindingType(slot: ValueSlotID)
UseRole.LOCAL_BINDING

BindingDefinition(value, state: BOUND | UNBOUND | UNKNOWN,
                  payload: UseID | None, previous: UseID | None)
BindingRead(operation: OperationID, binding: UseID,
            normal_result: ValueID | None)
```

- BOUND 的 payload 是实际 Reference use；不是对象复制。UNBOUND 无 payload，
  不伪装为 None、unknown Reference 或未定义 producer。UNKNOWN 不是“任意新值”：
  必须消费同 slot 的 previous binding，并有 unknown/coarse READ_WRITE world
  关系、effects_complete=False，保留依赖来源。
- slot 属于已解析的函数作用域。LocalBindingType 的 slot 是类型的一部分；
  不能把 x 的 backedge token 传到 y 的 block argument。每个结果都有规范
  BindingDefinition；block arguments 由逐前驱绑定解释。
- BindingRead 的正常结果保持已绑定 payload 的引用身份；可能未绑定时具有
  NORMAL/RAISE 路径。确定未绑定可以保留 INVOKE 的结构性 NORMAL 端口，但其
  激活条件为 false；查询和解释器必须按绑定事实排除该边，不能构造一次实际
  成功读取。也可用 normal_result=None 的明确 RAISE 形状。具体
  UnboundLocalError 的生成及 source 对应由新 profile/replay 验证，不能只看
  exception reference 类型就声称异常种类正确。
- 确定 UNBOUND 的 BindingRead.binding 仍是最终 RAISE operation 的实际 Use，作为
  异常控制依赖；它不是 Python 异常 payload，也不占 ExitPort。只有该 typed
  `BindingRead.normal_result=None + RAISE` 形状可多带这一依赖。RAISE 仍转发由
  操作生成的异常引用与当前 world，不能借此允许任意额外未解释控制 Use。
- 首次赋值/重绑消费 RHS 引用并更新该 slot；不能为了释放旧值先做一次可能抛
  UnboundLocalError 的读取。旧引用、临时及 finalizer 效果由 frame/world 保留。
- 该 token 是不可变绑定状态值，不是 StateLocation。可变 heap/cell/global/
  文件/设备状态有各自 location/version；细化未知 world 时要有 alias/覆盖关系，
  不能把新细粒度 location 与 coarse world 按不同 ID 判为互不影响。
- 全部 formals 仍是明确 Reference ports，由 ENTER 持有，再产生对应已绑定 token。
  编译期 locals 用 symtable，包括未执行分支的定义；嵌套函数有独立作用域。
- SSA 参数、binding token、静态 ValueID 不增加实际 Python retain/release，不
  代表物理快照或运行时对象副本。

## 6. CFG 与状态：循环、分支和完成路径

预先确定本函数 locals 的稳定 slot 顺序；首版可以保守携带超集，不做最小 liveness
优化。loop header、if join、loop exit 的 block arguments 显式携带每个 binding
和当前 world，按**实际前驱边**逐一绑定，不能只按目标 block 去重。

### while

```text
preheader -> header: test expression -> truth
                          true -> body -> header
                          false -> else -> after
body continue -----------------> header
body break ------------------------------> after
```

test/truth 每轮重新执行，可写状态、raise 或不完成；false/continue/异常出口必须
使用各自最新 world。body return/raise 结束该路径，不构造虚假 backedge。

### for

```text
iterable once -> GET_ITERATOR once -> header: ADVANCE_ITERATOR
                                        NORMAL(item, Wn) -> bind target -> body
                                        RAISE(exc, We) -> MATCH_STOP_ITERATION
                                                           yes -> else -> after
                                                           no  -> unwind -> RAISE
body fallthrough/continue -> header
body break -----------------------------------------------> after
```

- 保留既有 NORMAL/RAISE completion 类别。next 的 RAISE 私有后继再做 builtin
  StopIteration 及子类匹配；不用用户可重绑的同名 global 或普通 isinstance 调用。
  其他来源的 StopIteration（iter/body/target/call）绝不能被捕成循环耗尽。
- 每个 INVOKE 先进入 NORMAL/RAISE 各自的私有单入边 target，再 JUMP 到共享 header
  或 join。目标私有性按实际边数验证。
- 迭代对象未知，不按 `range` 等源码名字认定 builtin、有限或纯。iter 支持语言
  协议，包括适用的序列协议回退；不能假装等于普通 `obj.__iter__()` 属性调用。
- 零次路径保留原 target binding 或 UNBOUND；else 只接自然耗尽，break 绕过 else。
  continue/break 由 loop stack 指向最近合适目标，嵌套 else 的控制归属要验。
- next 即使最终耗尽也可能修改状态；else 消费异常路径产生的正确后态。循环
  iterator 和中间引用需在 body/backedge 存活，耗尽/break/return/raise 的清理效果
  不能因 SSA 值消失而省略。完成签名不保证终止，回边也不被运行次数静态展开。

frame ENTER/BIND/DISCARD/EXIT 的固定未证 NO_FRAME_INTERPOSITION、unknown effects、
MAY_NOT_COMPLETE、UNRAISABLE、NOT_GUARANTEED release 仍保留。新 profile 明确允许
binding/protocol 普通操作并验证其来源，不能全局放宽旧“普通操作均为 frame”规则。
异常分支先按合法作用域 unwind，再退出；以后引入 finally/with 时必须先解释
pending completion 的替换/suppression，不能继续无条件立即 finish_exit。

## 7. 局部保留与每个内部调用

1. 每个源码 Call 使用同一 SourceSnapshot/SourceReference/definition 身份；即使
   target 未解析，也生成自己的 Operation、callee Use、逐 actual occurrence 的
   有序 Use、结果与 state completion。重复实参不能按 value/reference 去重。
2. 属性 callee、keyword、star pack 的 source core 节点和动态绑定能力分开。
   结构可保留其语法输入，不代表已有 receiver/default/pack 的 runtime route。
   pack 展开中的用户代码和进入 callee 前失败必须有完成/效果边界。
3. 对已知求值顺序的表达式，递归保留其 child calls，再用 typed unknown 操作
   表示尚无精细语义的计算/读写；unknown 操作消费全部真实输入和当前 world，
   每条发生完成的路径保持 post-state，effects_complete=False。
4. 不能把 `BoolOp / IfExp / Compare-chain` 的所有 children 提前执行。赋值、
   AugAssign、属性/下标写、解包也各有特定求值次数和顺序，协议未实现就列边界。
5. 未知控制子树不得用一个 NORMAL/RAISE invoke 假装表达所有 return/break/
   continue/finally/with 行为。子树里的未连接 calls 必须逐项列出；opaque 父节点
   的 source span 不覆盖它们。必要时该 body 仍失败，不能把失败藏进全局比例。
6. source coverage 已存在的 atom 账本继续无漏无重；另建/派生严格的 call-to-core
   对应检查，验证 Operation 唯一、每个 callee/actual Use 唯一且有正确角色与顺序。
   任意 ValueSource 命中 atom 不足以算 Call covered。
7. 当前 core 要求所有 block 从 entry 可达。`return x; hidden(x)` 后的死代码保持
   source-inventoried 且明确不 connected；不得加假 CFG 边。若以后要求这类源码
   也有 core 结构，需定义非执行结构的类型/版本，本门不伪造其执行路径。
8. definition-time defaults/decorators/annotations、class body、comprehension
   独立 owner/phase 不可混进普通 function body。内联 comprehension 的 runtime
   code owner 与 lexical owner 需要源码编译证据，不能因同文件就自动连接。

## 8. 查询与跨层连接的必要限制

现 B1 routes 只在已证 source/code/core 端点、精确 operand occurrence、动态
attempt/entry/正常 completion 上建立条件引用来源；没有内容/效果/变换权限。
新 profile 需要从 BindingDefinition/BindingRead 的规范规则导出引用路径，不能
一般化成“结果依赖某输入，所以结果与输入是同一引用”。

当前 query 以 `(invocation, static ValueID)` 连接 completion；一个循环 callsite
重复执行会出现多条候选。没有动态 block/iteration occurrence 对应时必须停边。
同一个 shared object 在两轮、两个实参或 default/receiver 中相同，不解决该歧义。
分支合流只有所有来源确为相同 SSA 定义时才可使用共同来源；否则必须明确缺少
control selection 证据。CFG 建好不等于动态路径证据自动存在。

未知调用仍 `callee=None`；某次观察的 actual target 不写成静态永久 callee。
跨文件 coarse world 还需要显式 state-port composition，不能因为两个文件各有
location ID 就默认互不影响，也不能仅改成同字符串就声称绑定已证明。

## 9. 历史版本和公开重放

建议使用当前下一空闲版本：

| 层 | 新版本/分派 | 历史兼容要求 |
| --- | --- | --- |
| ProgramGraph | v3：新增 binding Value/Type/UseRole/规范规则 | v1/v2 严格旧字段/旧记录检查，保留既有升级规则；旧 serializer/replay 不能自动增加新字段。 |
| SourceProgram | v3 + STRUCTURED_BODY_V1 | v1 LEGACY、v2 BOUND_FRAME 原样重建；旧 unsupported 结果不因新支持自动变成功。 |
| ProgramInventory | v7 + 显式 profile | v1–v6 按旧 source/lowering/schedule/compile profile 重放，保留 summary、gap、ID 和预算收费。 |
| call/operand link report | 若接纳新 inventory/core/query 语义，显式新增版本 | 旧 report 不用当前 CLI 默认或新 route policy 重算；raw trace v1 协议不因 body profile 改变。 |

最终 enum/wire 字段由实施冻结，但必须有上述版本隔离。不得以 trusted bool 绕过
原始源码/raw/typed model 的独立重建。先检查报告头、authority、独立 budget，再
进行 inventory/raw/source I/O。来源、compile context、源码 hash、profile 参与
重放；新 core ID 包含 profile，既有 source IDs 不重命名。

未来 environment profile 如占用后续版本，按届时下一空闲版本分配；不能复用本门
schema 意义。新 CLI 初期提供显式 profile，何时改默认应有冻结验收结果。

## 10. 按依赖排序的自动验收门

全部门当前 **Proposed**。单门通过只关闭该门能力，不自动关闭后续缺口。

### G0 — Core 强类型基础与结构校验

实施 binding Value/Type、Definition/Read、slot-aware successor ports 和新 profile
分派；严格 codec、producer/Use/ownership、state、异常完成与历史迁移校验。

必须反例：跨 slot carry；UNBOUND 充作 Reference；BOUND 无 payload；UNKNOWN
无 previous/world 写；正常值流入异常路径；异常 world 回退；重复 state/location/
Use；旧版本夹带新字段；可改 bool 提升 effects/free/termination。
手工 core 只用于此门校验器单测，不算自动源码验收。

### G1 — 原始源码自动循环与局部绑定

从普通 `.py` 自动构造 if/while/for/zero/backedge/break/continue/else、formals 与
局部 carry，SourceProgram 公共序列化/独立 source replay。不允许测试手补 IR。

正反例：零/一/多次迭代；`for item in []: ...; return item` 抛未绑定；原来已绑定
的 item 零次不丢；branch-only local；self-binding/rebinding；嵌套 break/continue；
next 先改状态再耗尽；iter/body 抛 StopIteration 必须外抛；truth raise；循环后
无读取的未绑定不应失败；可能不终止；iterator/frame cleanup 与异常后态。

### G2 — 局部降精度与内部 Call/Use 保留

已声明控制结构中的每个 Call 和每个有序 Use 自动落 core；在安全的局部表达式/
读写协议上使用 unknown effects，不抹掉 body。加入 BoolOp/IfExp、必要的普通
assignment/attribute/subscript/slice/unpack 与 assertion 编译条件规则后分别验收。
assert 的 `__debug__` 来自目标编译配置或明确未证环境端口，不能取工具进程的值；
message 惰性求值，构造 AssertionError 可失败。

必须包含：循环前/内/后都有 Call，内部同次 `leaf(shared, shared)`，nested call，
keyword/pack 结构输入不虚构 runtime binding；short-circuit 避免多求值；局部
unknown leaf 不令其他 calls 消失；unsupported control 不伪造边；删 call/删
ordered Use/改 phase/opaque 覆盖子 call 的 tamper 必须由源码重放拒绝。

### G3 — 公开 CLI、自动全程序 scope 与 LeWM 结构压力

原始入口 + 已有 raw archive → 自动 source closure/body demand queue → 新 profile
inventory → strict public check → source/core coverage/query。保持每文件昂贵
prepare≤1、全局 body/operation/spool budgets；失败和 rollback 构造成本不退款。

逐阶段报告源 atom/Call 分母、core bodies/calls/Uses、明确未连接原因、live/dynamic
matched endpoints 与所有成本。支持范围且预算准入的 body/interface 有效率和
call/Use 双射率必须 100%，缺失/重复为 0；总源码范围另报真实比例，不能剔除
不支持/预算失败后只报“100%”。每个 opaque 隐藏 Call 都在缺口分母内。

此门可以证明完整入口范围已自动调查、支持部分的结构已保留；不能证明加载到
视频的全部语义已闭合。既有 windows 原始 capture 可只读重用，不应因源码建图
改动重复执行目标或篡改采集输入。

### G4 — 全过程控制、环境及实际调用连接

补齐实际路径所需 generator suspension/resume/close、closure/cell、try/except/
finally、with suppression、definition/module initialization，以及 method/receiver/
defaults/keyword/pack 的真实逐 occurrence 绑定和失败阶段。需要隐式环境与新的
completion 合同时继续版本化，不用 UNKNOWN 套壳作为完成条件。

必须反例：finally 替换 return/exception；with 吞异常；yield 前后 world 与 locals；
generator 未耗尽即 close；同 cell 多函数/同 code 不同 globals/defaults；load 后
callee/code 变更；绑定前失败无 entry；body 失败有 entry；重复 loop callsite
不能串 completion。公共 query 必须有真实多文件正例和明确停边反例。

### G5 — 文件/资源/表示/异步/状态依赖闭合

自动接通 checkpoint/config/data 外部读、model state、RNG、view/storage/
materialization、device/stream/ready、environment/frame 来源与视频/文本写出。
通过通用对象/操作协议及实际来源证据确定类型，不使用业务路径名单。

必须反例：相同引用原位修改后保存；不同 view 重叠；不同句柄同文件；同 path
重新打开/rename；append 顺序不能覆盖前写；未 close 的缓冲输出；编码异常留下
部分文件；随机数调用不能复用；GPU enqueue 返回不能作为跨 stream ready；
inference mode/detach 不等于无状态或可忽略梯度。未解析项必须保守连接、明确
影响范围，不得计为协议已完整。

### G6 — 从可观察根回溯及 OIR 有限改写

从视频、metrics/日志、外部状态、异常与必要顺序/完成根自动回溯到帧来源、环境
推进、推理、参数和加载输入。至少一个通用小项目能输出可核对的最小必要子图，
并在别名、RNG、异常、文件追加、异步完成反例下保留相应依赖。真实 LeWM 以相同
通用查询检验，不能靠手工图补齐。

OIR 只对合同/状态/控制闭合的具体区域给出可审查 rewrite；未知 world 或未证
条件穿过区域时停止授权。通过 G3 的结构图或 conditional reference query 不算
通过 G6。本计划不承诺新 backend，也不预报 LeWM 加速。

## 11. 自动指标与实施文件

所有指标需有集合分母、逐项来源和固定预算，不能只报节点增长：

- 源码 atoms / definitions / calls 按 file、owner、phase 守恒，漏/重为 0。
- 启动/加载、推理/环境、视频/日志分别列 core Region、Call Operation、ordered
  Use、loop/control ports 与 unsupported/source-only/budget-boundary 数量。
- 每个 Call 的 source→core 唯一性和每个 actual occurrence 的位置/角色完整性；
  对 opaque 内部 Call 和 unreachable 源码单列，不能充当已覆盖。
- source/code matched、具有 core endpoints、满足 binding 条件、实际 dynamic
  routes、可选择 loop/control occurrence 分开计；不以 same-ref 增加正例。
- 精确状态域/unknown world、完整/不完整 effects、已知/未知 alias/ready、
  observable roots、仍阻断 OIR 的条件分别出数；authority 默认 false。
- 构造 operations 单调收费、每文件 prepare 次数、spool 失败、peak RSS、壁钟和
  replay 耗时；并行竞争下测量不是 workload benchmark。源码/raw hashes 前后不变。

首批实现文件：`ir/program/model.py,codec.py,validation.py,functions.py` 与
binding 规范 records；`frames.py,frame_validation.py` 的 profile 分派；新
`analysis/structured_lowering.py`；`program_lowering.py` 的 SourceProgram/profile/
source replay；`program_inventory.py,program_expansion.py,function_interfaces.py`
的自动接线；必要的 inventory/source metadata records；`cli.py` 公开入口。
随后才是 `call_edges.py,call_operand_routes.py` 和版本化 report 的新 profile
准入及 query；完整环境/资源协议按 G4/G5 列出明确接口后实施。

不得为了版本兼容复制多套 source discovery 或图模型。旧 profile 保留旧 builder
与严格 replay，新 builder 共享来源索引和 core 基础，新增字段有类型与校验。

## 12. 已验收结果（留给根代理更新）

**当前无本文新能力的验收记录。** 请逐门追加，不删除剩余门和未知范围。

| 门 | 冻结 revision / source fingerprint | 自动输入与命令 | 结果、JUnit/报告路径 | 实际完成范围与剩余边界 |
| --- | --- | --- | --- | --- |
| G0 | 待实施 | 待实施 | 未验收 | 不代表源码自动构图。 |
| G1 | 待实施 | 待实施 | 未验收 | 不代表所有 Python 控制。 |
| G2 | 待实施 | 待实施 | 未验收 | opaque 内部调用不得计覆盖。 |
| G3 | 待实施 | 待实施 | 未验收 | 不代表全过程语义/执行闭合。 |
| G4 | 待实施 | 待实施 | 未验收 | 不代表精确资源/效果。 |
| G5 | 待实施 | 待实施 | 未验收 | 不自动授予改写权限。 |
| G6 | 待实施 | 待实施 | 未验收 | 只授予经证据支持的具体区域/改写。 |

# 第一阶段：自动建立完整、最小充分的程序图

2026-10-26 更新。阶段仍为 **OPEN**。先完成程序建模、建图；完成后向用户解释交付，
随后才进入化简。本阶段不增加 detector/backend，不修改 LeWM，不报告优化加速比。

## 需要实现的四项核心功能

| 顺序 | 功能 | 实现内容 | 自行验收方式 |
|---|---|---|---|
| 1 | 自动拆解程序 | 从入口和依赖出发，静态恢复模块初始化、函数/闭包、调用、表达式、分支/循环、异常以及数据/状态读写；动态证据确定实际调用目标和执行对应。 | 对真实 LeWM 涉及的程序部分生成规范操作、端口和控制结构；剩余未支持部分逐项补实现。AST 外壳不算内部恢复。 |
| 2 | 自动连接依赖 | 连接实参→形参、callee 返回→caller 结果、捕获/全局状态；接 Torch 算子及其有序数据端口、存储/view/物化和程序资源接口；关联 runtime/GPU 工作。 | 查询能跨原命名空间连续追踪 producer→consumer，保留状态、alias、异常和异步顺序；上下文嵌套不能冒充直接数据依赖。 |
| 3 | 轻量构建和存取 | 以函数/区域及执行片段独立建存，共享 source/schema/资源定义，跨片用限定 ID 引用；主视图简洁且可递归展开。 | 原操作/Use/状态/控制不丢；读取单片无需载入整个程序，不重复保存整份 execution 或每次迭代的 Tensor 数值。记录真实存储和查询成本。 |
| 4 | LeWM 全链自动生成 | 通用入口组合上述结果，贯通模型/数据加载→CPU 处理→搬运→推理/规划→环境交互→render/编码→文件保存。 | 在现有真实 episode 证据上查询整条必要依赖链，静态未执行路径单独保留。必要连接未闭合就继续开发，不用退出码、节点数量或某一层的 100% 替代全图完成。 |

按照必要功能推进；每项用一条真实输入完成正常读回/查询即可，不围绕每个字段扩展
大量测试或重复 gate。只有影响正确性的具体疑点才补最小验证。报告和版本由开发者
自行完成，不等待用户逐项审批。各功能按隔离文件并行，集成顺序保持上述依赖。

## 当前直接实施的顺序

1. **把已恢复的函数接入正式图。** 保留原161个已发布body和原命名空间，增量接入
   新恢复的35个body。完整源码上下文在同一构建会话共享，避免每个body重复遍历整图；
   已写成的片段可续接，不因一个批次结束重跑全部。只有关闭并正常读回后才增加发布数。
2. **补齐阻断连接的通用语言结构。** 优先实现Lambda的创建、捕获和真实表达式body；
   同时把bytes等常量指向已核实CodeWitness中的原常量槽。常量内容、Python对象身份和
   内容版本分别处理，不用新对象或伪造AST填图，也不按LeWM/库名选择规则。
3. **打通程序侧IO。** 把现有实际流调用连到同一源码图的CALL、有序输入、world状态
   和正常/异常出口；内存流与文件流共用模型。先接已有事件，不重建完整FD表、不新增
   Linux内部模型，不把C调用返回当作持久化或数据就绪。
4. **收拢为整条LeWM依赖查询。** 在上述连接成立后，补必要的值版本、物化与资源
   边，查询加载→处理→推理/规划→交互→输出。只有缺失信息无法从已有静态/动态证据
   恢复时才定向补采，不反复重跑完整episode。

前三项并行实现，第四项集成。每项只保必要的实际路径验证、结果记录和版本提交；
不把新增接口、局部成功或候选数量当作整个第一阶段完成。

## 图中究竟存什么

基础实体为 **Operation、Value、StateLocation、Region、Resource**，每类有具体类型，
不能把这五个家族当作五个互斥操作类别。Operation 的计算、表示、内存、搬运、
状态、控制、顺序和 IO 行为是多标签；输入/输出是端口角色，常量是不变性结论。

边保留有序 Use/def-use、状态前后版本、分支/完成/顺序、区域包含/调用展开、
逻辑值与物理副本/view/storage、资源使用及实际执行对应。Code、对象、storage、
逻辑值版本分开；相同地址/shape/样本或来源不能证明内容没变。

静态规范图描述可执行结构，动态片段描述真实发生，准确的来源和端口关系连接二者。
同一函数定义共享一次，每次实际调用保必要发生事实；不复制整份函数图。证据和
成本附着到相关操作/区域，采集器和验证器的内部工作不进入目标程序图。

## 建模深度

保程序可调整的操作及其必要依赖：Python/依赖库函数→Torch module/operator→
runtime 的 launch/copy/allocation/wait→GPU kernel/copy/memset 与所用资源。
CPU/GPU、DRAM/device memory、文件/存储路径、线程/进程和 queue/event 等使用关系
必须有表达位置。NVMe/SSD、GPU memory 种类根据证据判定，不根据路径或设备名猜。

OS、driver、allocator 的内部算法、完整 FD 表、SASS/机器指令和微架构不默认展开。
保留程序侧 IO/资源句柄的必要身份、内容/range、游标、效果、失败和完成摘要；
不能以“不展开底层”为由删除上层合法性所需的依赖。具体边界见
[MODELING_SCOPE_AUDIT.md](MODELING_SCOPE_AUDIT.md)。

## 当前已落实和紧接着要做的事

- 源前端新增 expanded call、函数 Try、nested function 能力已合入主分支；归并后的
  函数内import、flat With及独立generator creation已分别补通4、2、1个真实body；
  新增Set显示式、既有AugAssign接线及通用heap/cell解包后，243个外部入口现在
  198个可恢复、44个未支持、1个resumable adapter缺口。
  这是源恢复结果，不是全部已接回动态调用。
- 161 个旧成功入口已正常发布；新能力对应的 body 还需按原 ID 接回正式模型。
  不重跑已完成的整批普通发布/读取。
- 精简 Region 视图已实现并对真实函数验证：239 操作→134 展示节点；714 Use、
  76 状态访问、121 控制边保留。折叠语言管理编码不等于删除运行工作。
- 跨函数 normal return 查询已接入 CLI。真实 LeWM 的一条调用可从原参数端口
  追到 callee 的两个可能 normal return，再到 caller 结果；未声称观测到具体返回分支。
  `--include-state`也已接通该调用的入口world及正常/异常后的world：2个正常、19个
  异常可能出口，均保原端点/条件。粗状态传递不是纯性或细粒度状态不变证明。
- source context/body分离已接入通用存储/区域查询入口：两份真实SP5共用一次context，
  5.15MB→2.74MB，原图视图相同。旧格式兼容，现publisher尚待迁移。
- 最新source-entry profile已自动按原函数AST选择已实现的Try/expanded-call/nested/
  import/flat With/generator creation/Set能力，AugAssign自动复用既有FunctionTry协议；
  generator创建/惰性body与未知消费接口分开。
  V7固定解包继续复用原heap/cell/global store；真实新PIL body92ops完整恢复，另一
  入口越过解包后停在Lambda，仍按未支持计数，不扩写成功范围。
  随后V8补通该原入口：187个操作中包含独立Lambda表达式Region（17个操作），
  结构和独立source/readonly CodeWitness正常读回通过；创建只产一个函数引用，
  捕获cell引用，未来调用读取内容。V8也按原AST自动选择CodeConstant能力。
  这是新增1个源body，尚未计入正式发布或当前运行绑定。
  model-run source-entries默认选择latest，API旧None/CLI legacy保留。
  它仍要求正常entry及readonly CodeWitness，不把选择策略当作运行对应证明。
- native端口全源流式生成已实际完成：310412原节点、230818算子实例、1256501端口，
  76片压缩后约22MB，已接入主树通用生成/局部查询。provider/descriptor查询能返回
  原input/output EvidenceEdge，但同ref不是同内容版本，不等于全数据/状态依赖已闭合。
- native引用流分组索引已全量生成：533490个Tensor引用端口匹配原EvidenceEdge，
  69362组、128压缩片约34.45MB。公共CLI一次输入→可能上游输出查询exit0/2.981s；
  不生成output×input笛卡尔积，ordinal不充当完成/因果证明。
- 新lean采集仅细采计划内CALL接口，未计划内部不因seen code递归扩张；局部gap
  不全局停，hook损坏仍使epoch失效。CLI和静态计划派生已接，通用CPU+Torch程序
  从进程启动实际capture/普通读回通过，0 instruction rows；小型GPU+OS联合capture
  也实际通过，记录1次H2D/3个kernel，准确plan membership及正常reader已读回。
  这些是插桩集成结果，不是LeWM全链或性能结果。LeWM新全链尚未重采；
  先完成必要source/value/资源接线，不为小字段反复跑episode。
- 最后集中补值/状态/物化及 IO 接口的必要跨层连接，生成可查询全链并汇报。
  已做一个真实native输出的符号payload投影：保原ReferenceValue/ObjectIdentity，
  另以Inferred关联连到LV/version/UNKNOWN provenance与region=None物化，未冒充
  已证内容、alias或ready；原主bundle未改。这是接线原型，尚未批量生成全程序值生命周期。
  原型进一步接成真实view→add_→view的operator接口：4个Tensor实参和3个结果各有
  端点符号，每个op只以本实例实参作为UNKNOWN/Inferred接口parents；声明may-write/
  may-alias指回原effect/formal slot，跨op引用仍是候选，不证明内容依赖或实际写入。
  完整native接口已由自动producer扫描：230818实例、1256501端口，Tensor descriptor/
  device533490项全解析；只持久化77514B声明index，符号/ValueGraph按需派生。
  formal仍有788745未解析，内容/状态/ready并未因此证明，不能改为全模型完成。
- source-entry共享存储模式已接公共入口`--shared-source-context`，保持可选，未改旧CP2
  格式边界。两个真实85/217-op body以1context+2body发布并正常读回：3.30MB→1.76MB。
  省的是存储/重复读取；仍先生成和验证SP5，尚未消除该生产成本。
  完整正常worker也实际通过一个自动选出的原8-op entry（0.566s），原fragment端点、
  worker terminal及普通共享session读回一致；未执行target/bootstrap/CP2。
- 程序侧builtin stream接口已接可选trace/普通reader/owned coordinates：接收者引用、
  原CALL、read/write/flush/close等接口状态角色及实际C完成，内存流和文件流共用表示。
  新GPU+OS小样例实际通过7次接口/1次H2D/1kernel；不读取流内容或重建FD表。
  具体范围及canonical/backing连接缺口见[STREAM_INTERFACES.md](STREAM_INTERFACES.md)。

每次提交记录具体完成的功能与保留的缺口。当前详细差距见
[FIRST_STAGE_GAPS_20261026.md](FIRST_STAGE_GAPS_20261026.md)；某个组件通过不把整体改为完成。

## 当前并行任务及完成判据

1. 补最高覆盖的源码语法缺口：按真实失败清单选通用结构，实现后用真实原入口读回；
   禁止按库名/函数名适配。完成的body按原命名空间纳入自动入口。
2. native端口跨实例引用导航已完成；继续连接准确内容版本/写入/alias与必要资源接口，
   不把引用候选当数据不变或因果证明。
3. source-entry共享存储可选入口及完整worker已完成；后续迁移正式publication的
   transport准入，避免每body重复context，不为此重建全部旧产物。
4. 集成前述结果，继续补文件/数据/状态与资源必要接口，最后查询LeWM加载到保存的
   连续依赖。完成前不进入化简，也不把局部成功改写为第一阶段完成。

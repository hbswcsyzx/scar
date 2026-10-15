# 自动建模现状、连接缺口与后续自验

日期：2026-10-15。**完整自动 LeWM 程序图、可信化简指导及加速闭环尚未完成。**
已实现的构图流程不要求手工修补 LeWM 图；当前问题是覆盖和连接不完整。

最新开发：v6 已把紧凑调用来源接入自动展开，303 项映射门通过；全仓与原 LeWM
离线复验进行中，尚未完成 D1.c，暂不替换下表的已验收真实范围。见
[D1 验收进度](N2_CALL_DEMAND_ACCEPTANCE.md)。

## 1. 自动化的输入与职责

目标输入是原程序入口/命令、环境、资源预算和行为合同。SCAR 自行发现源码、
拆解操作、建立类型化依赖图，最终给出有证据、条件和成本的详细修改指导。
不输入业务函数名单、人工整理的常量、纯函数声明或 workload 图；手写 IR 仅
用于核心测试。本阶段不直接改目标源码，也不增加新的 detector/backend。

源码索引、局部图合法、跨层依赖闭合、允许化简分别验收。能够给一行代码分类，
不表示已确定它的实际读写、调用目标和全部消费者。

## 2. 已验收事实

| 部分 | 自动产物与实际结果 | 范围 |
| --- | --- | --- |
| C0：源码与有限 frame 图 | 原 LeWM 入口/归档 trace 自动发现 151 文件、2,217 定义、10,235 源调用；44 个 body 生成带缺口的局部图 | 256 次尝试中 212 个不支持；1,961 个定义未尝试，包含需要其它作用域接口的定义；不是完整程序图 |
| 真实调用采集 | 84,319 个入口记录、168,638 个事件、850 份 code descriptor；drop/open/path gap 均为 0 | 包含 suspended code 段，不等同于相同数量的完整语义调用；不保存 Tensor 数值 |
| D0：紧凑来源桥接 | 自动读取全部原始记录，812 个 entered-code 分组中，548 个 code/source 核验通过，421 个具备完整唯一 definition；报告 gzip 266,292 字节 | 259 个 code link INCOMPLETE、5 个 MISMATCH；127 个 VERIFIED code 尚无唯一 definition；421 个是展开种子，不是优化点 |
| D0 自主验收 | 实现 `39e8f22`，196 项门检查、全仓 2,033 项通过，零失败/错误/跳过；原归档公共独立重放通过 | Source/raw trace、LeWM clean HEAD 均不变；没有新的 LeWM 执行、变换或 clean A/B 加速比 |

D0 源指纹：`81d6a6b675055eaa70a8e4dff566107dc3329859e999e7f918050bd983c26909`。
报告见 [D0 验收](N2_CALL_SEEDS.md)、
[实际外部结果](../artifacts/reports/gates/n2-call-seeds-real.json)、
[门与证据清单](../artifacts/reports/gates/n2-call-seeds-manifest.json)。
C0 历史压力验证见 [frame 验收](N2_FRAME_ACCEPTANCE.md)。

## 3. 模型里分成哪些部分

| 结构实体 | 含义 | 必须连接的关系 |
| --- | --- | --- |
| Operation | 调用、计算、读取、写入、复制、分配、等待等操作 | 有序输入 uses、产出、状态访问、完成与控制 |
| Value | 数据、对象引用或状态版本；输入/输出是端口角色 | 精确 producer/consumer、actual/formal、分支/循环携带值 |
| StateLocation | 可变内容或外部状态的位置/范围 | 前后版本、读写、alias、外部写入与稳定性 |
| Region | 可递归展开且带明确入口/出口的子图 | 包含、调用接口、控制/异常出口和可观察效果 |

这是结构类型，不是四种互斥操作。行为标签可以叠加；Resource、StorageRegion、
Materialization 和实际执行事件在实现/证据层有各自类型。程序 Region 子图与
storage 的几何区域不是同一实体。保存视频与保存 Tensor 都可拆为编码/表示、
搬运和目标状态写入，不按载荷业务名称设计基础节点。

源码结构、执行证据和优化区域视图通过 typed correspondence 连接。当前细粒度
状态连接仍不足，局部 body 多数用 coarse world 保留未知效果。不能把静态 ValueID、
引用相同或 shape/采样相同当作跨调用内容恒定证明。

## 4. 尚未接通的具体部分

1. **来源到展开队列。** 主线 D0 已取得 421 个源码种子。开发版 v6 已用独立
   typed origin 接入新队列，小程序自动端到端及严格重放通过；原 LeWM 复验尚未
   完成。没有把 call group 序号塞进旧 observation_indices。
2. **实际参数/返回。** 查询仍在 `ARGUMENT_ROUTING_UNVERIFIED` 停止；方法、
   partial、defaults、callee 重绑和绑定前失败不能靠同对象或源码签名推断。
3. **函数环境与作用域。** 相同 code 可以关联不同 globals/defaults/closure。
   模块初始化、class、lambda/comprehension 与函数调用期需要各自明确接口；
   EntryRoot 不能被伪造为一个已经成功构建的普通函数 Region。
4. **循环、状态和逻辑来源。** loop-carried 值/状态、异常后态、view、共享存储、
   NumPy 外部写入、copy/deepcopy/transform 的来源仍未统一闭合。
5. **区域化简指导。** 未能从要求保留的输出/状态/外部效果，自动求出完整依赖
   闭包并生成 LeWM 上可批准的替换、提升、共享或删除方案。没有可信加速比。

## 5. 下一步计划与自主验收

| 顺序 | 工作 | 完成依据 |
| --- | --- | --- |
| D1.a | 私有轻量 source-witness index、共享原 ID 规则与有类型需求来源 | 同一原遍历、完整 atom 覆盖、全部 CodeSourceLink 成功/失败记录不变；不重算未消费的完整图摘要，不接受外部 trusted 开关 |
| D1.b/c | v6 source scope/入口依赖 frontier/body queue；旧 v1–v5 原样重放 | 原始多文件程序自动接通 source→准确 body；入口依赖优先，无关文件不能按名字抢预算；原 LeWM 同入口/trace/预算复验 |
| C1/C2 | 实际 operand→formal→return/raise 与环境/状态 | 多层跨文件查询回到准确上层 Use；receiver/default/同引用多参数/重绑/闭包/异常反例不误连 |
| 循环与细状态 | loop-carried 依赖、位置/alias/版本和 logical provenance | 零次/多次循环、原位覆盖、共享 view、foreign write、RNG/autograd 的通用正反例 |
| 区域化简 | 从观察根反向裁剪依赖，给出具体修改位置、残余效果、条件与成本 | 通用源码自动建图与正反例后，再在原 LeWM 自动产生可检查指导；不靠业务名规则或手工补图 |

详细计划：[D1 入口依赖与来源迁移](N2_CALL_DEMAND_PLAN.md)、
[实际调用/环境连接](N2_CALL_BINDING_PLAN.md)。每门由开发者自行验收，保存失败
与通过报告、冻结版本、外部复验并提交推送；不等待用户逐门批准。

## 6. 分析成本与资源管理

D0 生成 349.361s、峰 RSS 230,564KiB；独立重放 352.998s、峰 RSS 237,716KiB。
重放期间有独立单文件诊断并行，时间不是 clean benchmark。以上均为分析成本，
不是 LeWM 加速数据。115 个匹配源码文件共 1,217,639 字节，分析仍偏慢。

按最大已观察源码 bytes 自动选取的单文件 cProfile 证实：`index→snapshot`
耗 38.225s 插桩累计时间，并计算了未被 code/source 见证消费的三个完整图摘要。
下一步先分离所需索引发布路径，保留原遍历、身份、预算/边界和公共严格校验；
更深入的 AST-only 索引还需共享发射规则及版本处理，不能悄悄改变历史失败报告。

本轮清理释放 102.629MiB：41 份文件无损压缩并核对解压 SHA256，清除项目缓存
及已结束测试临时目录。原始事件内容、源码、报告与 LeWM 环境保留；主项目
约 1.4GiB。明细见 [磁盘管理](ARTIFACT_RETENTION.md)。

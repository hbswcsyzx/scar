# 完整程序模型的实施顺序与自主验收

日期：2026-10-16。这是当前优先计划，修订旧 N2 中先推进局部桥接的顺序。
模型依据：[WHOLE_PROGRAM_MODEL.md](WHOLE_PROGRAM_MODEL.md)。用户无需逐门审批。

## 1. 阶段顺序与当前判定

```text
M0 规格一致性 -> M1 规范类型与协议 -> M2 构造分解完整性
    -> M3 自动全程序建图 -> M4 执行对应与值来源
    -> M5 观察根依赖闭合 -> M6 化简指导
```

M0—M2 是程序抽象建模阶段；M3—M5 是自动建图与精化阶段；M6 才申请化简。
已有局部图和 trace 保留为反例与证据来源，不能替代前置门。**目前未完成
整个程序抽象建模。** 新 detector/backend 暂停。

## 2. 每门交付与失败条件

| 门 | 交付 | 自主验收条件 | 明确不算通过 |
| --- | --- | --- | --- |
| M0 规格一致性 | 五类实体、身份/版本、规范事实归属、控制/资源/环境接口；迁移决定。 | 独立审查无未解决的实质类型矛盾；实际 Python 反例约束规格；全部缺口有落点。 | 写完文档即宣称 whole model。 |
| M1 类型与组合 | 在现 `ir/program` 扩展强类型控制/环境/资源/来源接口与 validator，复用现有 canonical Uses/state。 | 非法 payload/target/state/资源代次与错接必须拒绝；normal/raise/cleanup/resume/ready 不混用。 | 新建一套未接入现有 core 的 metamodel；只加 enum。 |
| M2 构造分解 | 目标 Python 版本全部构造的字段/phase/顺序/隐式调用规则，通用 native 边界协议。 | catalog 守恒；逐协议独立小程序覆盖路径与失败；源部分、scope 与接口无遗漏。 | 标签齐全但没有依赖规则；opaque 内部算已理解。 |
| M3 自动全程序图 | 从入口和依赖自动恢复 Region、操作、ordered Uses、状态/资源/完成端口。 | 支持范围逐项 source/core 守恒；未知子区域保留周围已知结构；完整分母与预算；公开构建及重放。 | 手工函数名单、pure/constant 标注、业务名规则；只报 body 数增加。 |
| M4 证据精化 | occurrence/denotation、实际 dispatch/environment、返回与资源实现、数据/物化来源。 | 重复调用/递归/循环/挂起不串线；copy/view/外部写/地址复用与异步反例；原始证据不变。 | 相同引用即数据恒定；只补更多 collector 标签。 |
| M5 依赖闭合 | 从返回、文件/视频/日志、外部状态、异常及完成根追溯的查询。 | 加载→参数→推理→环境→输出全过程连接；状态/控制/资源/生命周期边均可解释；剩余边界逐项定位。 | 人工路径图；只沿最终 Tensor；把未观测 consumer 当不存在。 |
| M6 化简指导 | 从已闭合子图自动导出具体替代、改接/删除/上移位置、理由、合同、成本与验证计划。 | 通用正反例 + 未修改 LeWM 同流程；具体候选的证明闭合；NO-OP 合法；不盈利明确拒绝。 | 每个候选笼统 UNKNOWN；重复模块自动 cache；未经 clean A/B 声称加速。 |

M1/M2 的工作允许按协议逐步落地，但门报告保留完整分母及未完成项目，不能
将已实现子集重新命名为整个目标。native 内部无需假装变成 Python 源码；其
接口模型必须完整保守，内部依赖不精确时化简权限受限。

## 3. 下一批落实顺序

当前代码与工具分工复审见[建模与复用决定](MODELING_REUSE_DECISION.md)。P0/P1
声明组件不是实际导入；不要继续以增加声明表、兼容测试或 Tensor wrappers 代替
自动连接。通用 SSA/Region 基础设施扩展前先对照 MLIR/xDSL，源 CFG/flow 扩展前
先对照成熟前端。现 collector 的名字猜写与异常/初始化缺口记录为具体待办，
后续用 schema/来源与采集完整性验证，不提前宣称效果完备。

先落实 [工具复用审查与集成设计](MODELING_INTEGRATION.md) 的 T0/T1：模型中明确
哪些事实直接复用 ast/symtable/dis、FX/Export、ETO/Kineto，及其类型/状态/范围
映射。不再扩大与这些接口重复的 Tensor tracer；Python source lowering 优先
评估成熟前端，不能把自写完整编译器当作模型完成的先决条件。T2 以后适配器
建图仍属后续阶段，不越过用户要求的第一阶段停止点。

native 接口按[集成设计 7.2](MODELING_INTEGRATION.md)收缩：原生 graph signature/
TreeSpec 保留在有版本的 artifact，优先复用原生解析规则；SCAR 只添加规范
entry/exit 引用及必须跨图查询的关系。第一阶段不以自制全部 pytree/Export 类型
作为前置；provider 自身子图可表示与原 Python 可等价替换分别验收。

复审细化了 [字段归属与替代准入](MODELING_INTEGRATION.md)：在继续新增 source
control lowering 前先明确现成前端可提供的 CFG/dataflow 和差距，不能把完整
Python 编译器作为 M0–M2 的前置。未展开部分保留 typed 边界、可能状态后态和
具体覆盖缺口；不将边界可表达算作内部已理解。Profiler 内存数据流的单次 CPU
能力探针已加入 [调研 3.5](TOOLING_SURVEY.md)，尚未接入当前 SCAR。

1. 统一 ControlPort / EnvironmentInterface 与规范状态参数，扩展既有 core 的
   completion target、pending cleanup 与 protocol adapter；先处理同步异常。
2. 按[C2B body合同](M1_RESUMPTION_BODY_COMPONENT.md)独立验收保存Uses、typed
   ResumeInput、temporal successors、cut availability及context/C1组合；499项组件及
   冻结`e6b4723`的3,542项全仓已通过。
   然后关闭完整[C2](M1_RESUMPTION_INTERFACES.md)的Create/driver/context/release
   字段与组合。body generation与drive epoch分开；不冻结yield时world或旧caller，
   不把接受请求等同实际body entry。完整C2.0/C2.4仍开放，不能以body组件代替。
   [Driver字段复审](M1_DRIVER_INTERFACES.md)已用语言反例否定旧raw请求/混合claim方案，
   先修复permit/session与owner/commit关系；共用的[首outcome查询](M1_BODY_OUTCOME_FRONTIER.md)
   按冻结的结构关系先行实施，不把它当作完整driver字段冻结或C2验收。
   后续[连接合同第二稿](M1_DRIVER_CONTRACT_V2.md)取消可传递permit和通用request历史，
   用gate真实completion→唯一BodyDrive表达资格与准入后态。先按[D1完整路径及验收矩阵](M1_DRIVER_IMPLEMENTATION.md)
   实施已收敛的规范连接；D2生命周期独立细化，不靠D1字段设计通过缩小完整C2分母。
3. 接 ResourceDefinition/Requirement/Instance、handle、WorkTicket/readiness，
   复用 allocation/materialization/provenance 的已有证据，消除未连接的身份表。
4. 在 M1/M2 内补齐构造协议、provider 端口映射与未展开区域的接口规则。
   source lowering/全程序 inventory 的实际扩展放在 M3；不越过第一阶段停止点。
5. 在第一阶段落实 occurrence/denotation、外部读写和观察边界的类型合同；真实
   证据连接在 M4、观察根依赖闭合在 M5，通过后才进入 M6。合同声明不算执行证明。

这些是同一个 ProgramModel 的扩展，不按业务阶段创建不同图模型。模型层
保持“值推导”和“物化推导”分离，避免 copy 构成逻辑值自环。

## 4. 版本、证据与资源要求

- 每门记录冻结 revision/source fingerprint、命令、版本、输入/输出 hash、
  定位明确的失败及终态。原失败保留；脚本错误不计为模型拒绝。
- 测试数只证明声明范围。冻结 d5311a6 的 2,686 项回归不覆盖尚未实现的新规格。
- 源码压力和离线查询的时间是分析成本；instrumented run 与 clean benchmark
  分开。未完成变换/正确性/A-B 时无 LeWM 加速比。
- tensor 只做有预算的元数据观察；不逐迭代保存大内容、不强持有 frame/object。
- LeWM 原仓库、输入数据、CUDA/PyTorch 环境保持受保护；不因模型改动重跑已有
  可只读复用的重型 trace。

## 5. 当前证据锚点

- [D1规范driver连接组件](M1_DRIVER_ACCEPTANCE.md)671项组件/13标准通过，冻结
  `382363c`的3,706项全仓/457.563s通过；415源文件/29份fixture指纹前后一致。
  独立raw行为标签反例已修复；原始失败、独立审查与全仓证据均归档。
  新增严格v11及原始input/output端口派生，不授D2/D3、source/runtime或变换权限。

- [D1连接第二稿](M1_DRIVER_CONTRACT_V2.md)及[实施矩阵](M1_DRIVER_IMPLEMENTATION.md)
  提供下一批代码的完整接口和正反路径；独立core/gate/lifecycle审查的原意见与修正
  均保留。六项corridor设计检查只验证现core可接线和专用检查需求；产品源码未改，
  不重跑旧全仓。D2、D3、完整C2及第一阶段仍开放。

- [C2F首outcome查询](M1_BODY_OUTCOME_FRONTIER.md)517项组件/7.384s、冻结`9f3d7e7`
  的3,549项全仓/433.223s通过，406源文件及26份fixture哈希前后一致。新查询只
  派生已有图中本次entry/landing的首终端，不跨temporal边。driver审查发现旧字段
  不足，8组生命周期断言、另3组claim/raw请求观察约束后续修订，不关闭C2D.0。

- [C2B静态body](M1_RESUMPTION_BODY_ACCEPTANCE.md)已验收：499项组件/7.077s，
  冻结`e6b4723`的3,542项全仓/432.922s，403源文件及26份fixture前后哈希一致。
  实现通用temporal输入、上下文与binding/C1组合，不证明完整driver或运行恢复。

- C2架构审查（2026-10-17）收束为同body temporal边和两个派生投影；23组初批动态
  观察、4种静态code shape、另4组delegate-context观察及5个availability设计检查。
  这不是C2产品测试；字段冻结、context/C1/frame组合与实际导入尚未完成，见
  [C2实施合同](M1_RESUMPTION_INTERFACES.md)。本批不重跑原有full或LeWM。

- M1 [C1 cleanup/context](M1_CLEANUP_INTERFACES.md)243项组件通过；冻结实现
  `0ea05e6` 的3,330项全仓回归通过，391文件源指纹及22份fixture哈希前后一致。
  只验证声明图的pending/context/当前state、LIFO与route组合；不证明真实unwind，
  with/except*、resumption和第一阶段完整接口仍未完成。

- M1/T1 [P1薄边界](M1_NATIVE_INTERFACES.md)168项组件通过（376文件源指纹），
  已接原生槽到规范entry/exit及跨表示八域待证声明，未复制pytree/signature解释器。
  独立审查发现并修复旧ID子类索引回归；`79bf2a9`的3,215项冻结全仓通过，
  源/18份fixture哈希前后一致，真实adapter仍未接入。

- M1/T1 [P0来源与归属](M1_PROVIDER_INTERFACES.md)225项、冻结全仓3,139项通过
  （implementation `b140708`，367文件源指纹与15份fixture哈希前后一致）。只验证
  声明合同、规范实体归属与有序端点；P1原生边界、artifact重放、动态occurrence
  和跨表示等价尚未实现，完整T1/M1/M2及第一阶段仍未完成。

- M1 [C0控制协议组件](M1_CONTROL_INTERFACES.md)354项、冻结全仓3,027项通过
  （implementation `54eb7ec`，源指纹含356文件）。该历史组件仅验证scope/port/
  pending/packet和CFG组合；C1由上面的独立组件接入，不称完整finally或M1通过。
- M1 函数环境/入口分区组件已接规范 Uses/state，终版组件 327 项、冻结
  全仓 2,835 项通过（implementation `e826713`）。它只验证静态声明，不证明 runtime/source 绑定，见
  [M1_ENVIRONMENT_INTERFACES.md](M1_ENVIRONMENT_INTERFACES.md)。其余完整分母见
  [FIRST_STAGE_COMPLETION_MATRIX.md](FIRST_STAGE_COMPLETION_MATRIX.md)。
- M1 有限静态资源子项已接原 core 并通过198项组件检查；仍未关闭M1，见
  [M1_RESOURCE_INTERFACES.md](M1_RESOURCE_INTERFACES.md)。
- M2 字段级协议分册已细化数据定义、控制及资源；独立语言探针约束规则，
  不代表全部新类型已落实或自动建图通过。

- 有限同步实现：`dcd4986`，组件 290 / 全仓 2,657，通过范围见
  [N2_STRUCTURED_BODY_ACCEPTANCE.md](N2_STRUCTURED_BODY_ACCEPTANCE.md)。
- 固定 256 候选源码压力：新 51 个 graph-with-gaps，205 unsupported；
  1,591 个源 Call 中 77 个有完整的本次 core 有序端点，**不是全过程建图完成**。
- 本轮规格审查及清单/反例检查：[WHOLE_PROGRAM_MODEL_REVIEW.md](WHOLE_PROGRAM_MODEL_REVIEW.md)。
- 旧 N2 控制子集计划继续保留，但与本文冲突时，以整体模型门和事实边界为准。

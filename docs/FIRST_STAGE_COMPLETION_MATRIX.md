# 第一阶段完整性分母：模型、接口、协议

日期：2026-10-16。**第一阶段未完成。** 本表按当前需求列出必须覆盖的部分；
它不把已实现组件重新命名为完整程序模型。阶段顺序见
[WHOLE_PROGRAM_MODEL_PLAN.md](WHOLE_PROGRAM_MODEL_PLAN.md)。

## 1. 当前类型分解及各自职责

Operation、Value、StateLocation、Region、Resource 是规范实体；输入/输出是端口
角色，读/写/计算/搬运/等待等是可组合行为，不是互斥的人类业务分类。
静态定义、动态发生、证据和可替换区域保持不同身份；显示的操作节点/数据边从
规范记录投影，节点可沿 Region 展开，不另存可修改的 producer/use。

例如“加载 checkpoint”和“保存视频”不需要分别造业务节点：两者分解为路径/
文件资源、读写/表示变换、对象/状态/分配、完成与外部历史；算法和合同不同，
使用同一组接口。能写出这个分解不等于自动恢复已实现。

## 2. 必须逐项关闭的模型范围

| 必需部分 | 已有实现/依据 | 尚需落实的接口或一致性检查 | 当前判定 |
| --- | --- | --- | --- |
| 源/代码版本与阶段 | AST/symtable/dis、snapshot/code witnesses、definition/call 分册。 | 将全部定义、编译/定义/进入/恢复阶段与规范操作/环境连接；不以行号当唯一身份。 | 部分实现。 |
| 操作、值及有序使用 | 原 `ir/program`，准确 producer、Use、block/region、data/reference/state/binding。 | protocol values 与 outcome/adapter 端口；不以 label/string 代替强类型规则。 | 有限 core 已实现。 |
| Python 函数入口与环境 | 环境及 entry-layout 组件接原 core；形参/环境/状态分区，引用与当前状态分开。 | source signature/replay 对应；真实 callable/code/各role/activation 映射；旧 `record_body` 偏移不能用于新入口。 | 静态声明组件 327 项、冻结全仓 2,835 项通过；不算自动绑定。 |
| 控制与语言完成 | 同步 if/loop/binding/invoke；[C0](M1_CONTROL_INTERFACES.md)词法scope/typed port、packet/pending构造及CFG case dispatch；[C1](M1_CLEANUP_INTERFACES.md)同步cleanup/context及entry-relative copy/fresh组合243项组件、3,330项冻结全仓通过。 | with/except*、完整跨边界case合同、实际context/source/LoopInterface对应；挂起中的active cleanup与resumption组合。 | C0/C1静态声明组件已验收；完整控制类型/协议未齐。 |
| 挂起、恢复与逃逸 | [C2B](M1_RESUMPTION_BODY_ACCEPTANCE.md)/[首outcome查询](M1_BODY_OUTCOME_FRONTIER.md)已验收；[D1连接组件](M1_DRIVER_ACCEPTANCE.md)已实施，671项组件通过，415源文件指纹前后一致。 | D1冻结全仓与归档；D2 no-body/session/release、D3全家族及source/runtime对应。 | D1待完整回归验收；完整C2.0/C2.4与第一阶段未关闭；不算自动恢复。 |
| 状态 owner、selector 与 alias | StateLocation/Access、footprint 与版本 SSA；v2 storage 几何。 | namespace key/object field/cell/元素 selector、owner 身份、粗细域覆盖/冲突；外部 alias 写与输入失效关系。 | 现有粗粒度域可保守表达，精化接口未齐。 |
| 所有 Python literal/表示 | 现 LiteralOrigin 支持 None/bool/int/有限float/str，普通容器有源码协议。 | bytes/complex/Ellipsis 等严格表示、非有限数值的无损 wire、identity/编译折叠与运行构造边界。 | 不完整；不能把缺项算成 UNKNOWN 后验收通过。 |
| 逻辑值、来源与物化 | v2 LogicalValue/Version、Provenance、allocation/region/materialization、binding。 | core ValueOccurrence→Denotation；值推导/物化推导、有效区间、状态版本与 producer/Use 的唯一来源；copy 不造逻辑自环。 | 既有 records 可复用，完整桥接未实现。 |
| 资源身份及要求 | 原 core 静态 ResourceDefinition/Requirement/Use/Location，严格 v4。 | 动态 instance/generation、handle realization、capacity/ownership/可见性与生命周期约束。 | 静态子项已验收，整体未完成。 |
| host 返回与资源完成 | 资源协议分册区分 enqueue、wait、work outcome、ready。 | typed WorkTicket/Ready 与内容/分配版本/consumer visibility 对应，stream/event、部分失败/取消。 | 完整 machine 接口未实施。 |
| Python/库/native 协议 | 113 AST 构造、196字段清单；数据/控制/资源分册及语言反例。 | 通用协议的输入/环境/状态/资源/完成字段逐条映射到核心类型；native 边界保守完整，内部未展开不算已理解。 | 分册已审补若干缺口，不等于 M2 整门通过。 |
| 现成图及捕获条件 | [工具调研](TOOLING_SURVEY.md)有实际小CPU证据；[P0来源声明](M1_PROVIDER_INTERFACES.md)已验收；[P1薄边界](M1_NATIVE_INTERFACES.md)的原生槽/规范分区、原生树来源引用及跨表示八域待证合同168项组件与3,215项冻结全仓通过。 | lifted slot 与具体实例/当前状态、真实tree映射和写回、artifact重放及动态occurrence对应。 | P0/P1声明组件已验收，完整T1及新adapter未完成。 |
| 运行证据接口 | 已有 sys.monitoring、module/dispatch、profiler/Kineto 和 raw records。 | 明确缺失/截断/冲突、clock/run/window 域；静态→动态→物理的强类型多对多对应；ETO 等字段导入。 | collector 已复用，统一对应未闭合。 |
| 合同与观察边界 | Q/M、effects/proof ledger、v2 contracts，whole-model 观察根规格。 | 将返回、必要状态、文件/视频/日志、异常/完成、RNG/梯度/identity/顺序合同绑定到规范接口与证据。 | 现有合同可保留，整体边界连接未完成。 |

第一阶段关闭要求是上表接口能组合并被机器校验，且 M2 的每个构造有明确
phase/依赖/效果/完成规则与反例依据。静态模型可声明外部约束，但不得把声明
当作已观测或已证明的实例。未知内部依赖保留具体边界，不吞掉周围已知结构。

## 3. 第一阶段与后续阶段的分界

- **第一阶段：** 规范实体/类型、身份、端口、组合与校验；完整构造规则；工具
  事实的映射合同。静态手工 IR fixture 只验证结构规则，不算程序自动分解。
- **后续建图阶段：** 从任意程序入口及实际证据自动生成上述记录，验证源码、
  signature/environment、occurrence 和物理实现的对应；报告完整分母与预算。
- **后续化简阶段：** 观察依赖闭合后生成具体可替换区域、位置、理由、合同、
  成本及修改指导。不能因本表或更多测试通过而自动允许 reuse/hoist/delete。

用户要求第一阶段完成时先停下来讲解；这个停止点保持。现在不扩大 detector/
backend，也不以新的重型 LeWM trace 替代模型接口缺口。

## 4. 下一批必须完成的顺序

1. 已关闭 [函数环境与入口组件](M1_ENVIRONMENT_INTERFACES.md)的独立审查、
   公开 codec/query/CLI 与冻结回归；只证明静态声明，其 source/runtime 对应仍待接入。
2. 将控制分册落为 canonical typed completion/cleanup/resume/adapter 接口，
   保留原 CFG/Uses/state，并验证错误目标、错误payload、旧world和恢复布局反例。
3. 完善 location owner/selector 与完整 literal 表示；接资源 instance/work/ready
   的强类型接口，复用现成 allocation/materialization 与 profiler 字段。
4. 接 core occurrence/denotation 与 provenance、provider envelope/角色映射；
   来源、变换表示和原程序之间不授无条件等价。
5. 逐条核对 M0/M1/M2 分母、独立报告及版本，满足后才汇报第一阶段完成。

完整 source lowering、动态采集与大 testcase 建图仍在后续门执行；第一阶段定义
接口及其合法组合，不通过编造 execution records 提前宣布自动完成。

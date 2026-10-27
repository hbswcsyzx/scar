# 第一阶段完整性分母：模型、接口、协议

**当前验收入口（2026-10-20）：** [第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)
同时要求设计、自动恢复、LeWM 实际全流程及软硬件资源覆盖。
[当前状态](FIRST_STAGE_MODEL_STATUS.md)为 OPEN。下表是保留的历史组件分母，
不能用这些 supplied-model 门的 PASS 代替自动模型验收，也不再据其编号盲目推进。

**2026-10-25 范围澄清：** 本文第3—4节将自动建图放到“后续阶段”的文字仅为旧版
历史范围，已被当前合同替代，不是执行指令。第一阶段必须完成自动 LeWM 建模及
所涉软硬件资源接口；当前执行顺序见
[FIRST_STAGE_EXECUTION_PLAN.md](FIRST_STAGE_EXECUTION_PLAN.md)。

最新F19完整链（2026-10-20）：[限定验收](M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md)
在相同922输入上通过30新项+302直接受影响既有项，两次冻结运行并集332。
原三完整单位和缺采/预算/release反例贯通，原copy、schema及旧tests/fixtures保持。
原16行现10限定接受/6开放；原F20/F22/F24/X25/X26/X27、P4 component/full、P5、
M2原113/196及完整第一阶段仍开放。没有自动LeWM恢复/变换或新加速结论。
[下一门F20](M1_YIELD_FROM_INITIAL_PLAN.md)已按完整父链规划，用户无需逐门验收。
以下旧状态条目保留为历史，以本条为当前状态。

最新消费者桥（2026-10-20）：[限定验收](M1_VALUE_SOURCE_CONSUMERS_ACCEPTANCE.md)
一次26模块292 PASS，21新增、917稳定指纹输入。查询局部多边来源保普通copy /
stored关系分列，准确load可接上层payload、owner、call/join及body普通None后的
独立薄分支。旧test/fixture、原copy/roots、Program27/Execution8保持。本门不把
薄分支算公开F19历史，不关闭F19第1项/整族、原七族、P4/P5/M2原113/196或完整
第一阶段；[下一门](M1_VALUE_SOURCE_CONSUMERS_NEXT_GATE.md)返回原F19，不继续
增加同类来源工具箱。没有自动whole-LeWM恢复、变换或新加速结论。

最新值关系（2026-10-20）：[原存储值限定验收](M1_STORED_VALUE_ACCEPTANCE.md)通过961
直接相关项，913稳定源码，40新增；原store payload/状态版本/load ownresult可作
条件性实际来源查询。Program27只由新能力选择，独立冻结26字节oracle保持旧wire，
Execution8不变；16旧codec的版本/字段断言及七个未来case有显式迁移，旧fixtures
不变。自动恢复及旧消费者后续[通用桥](M1_STORED_VALUE_NEXT_GATE.md)未完成。
本批不关闭F19第1项/整族、原七族、P4/P5/M2或整个第一阶段。

最新身份连接（2026-10-20）：[当前对象身份限定验收](M1_FRAME_IDENTITY_GUARD_ACCEPTANCE.md)
通过231项直接相关回归，907源文件稳定；217既有身份含上批全部196，新增14。
五类实体不变，原test/fixture及Program26/Execution8不变。独立当前对象身份可
条件性接同frame真实F，但不产生ordinary copy或stored-field来源/数据版本证明。
原无身份声明仍None；[下一门](M1_FRAME_IDENTITY_GUARD_NEXT_GATE.md)设计准确的通用
存储值→状态→读取结果关系，再返回F19原后续。F19第1项和整族、原七族、
P4/P5/M2及第一阶段不因该身份分支关闭。

此前子链进展（2026-10-20）：[F19 finished请求限定验收](M1_ASYNC_FINISHED_REQUESTS_ACCEPTANCE.md)
通过196直接受影响项，904源文件稳定；新独立路径库存、own N/R和当前状态已接。
动态association→同B/F历史桥及非finished native内部仍缺，F19第1项与整族不关闭。
九族接受/七族开放、P4/P5/M2原分母及第一阶段未完成的判定保持。

此前限定检查点（2026-10-20）：[原 F18 验收](M1_ASYNC_TERMINAL_ACCEPTANCE.md)
以 2104 项相关回归、899 文件稳定指纹，核源合法性、body内终止转换、准确后继
异常包与当前state/消费者。旧2058精确身份全保，新增46；无旧test/fixture或
Program26/Execution8改变，全部首败及两次静动来源反例保留。
原十六族中 F12/F13/F14/F15/F16/F17/F18/F21/F23 九族、await A–H 条件性结构接受；
其余 F19/F20/F22/F24/X25/X26/X27、P4 component/full、P5 与 M2 原113/196
仍开放。[下一门](M1_ASYNC_TERMINAL_NEXT_GATE.md)已合账F19既有selector及完整链真缺口。
真实 opaque/内容保持 Unknown 不要求翻纯；已有声明图不代自动 LeWM 恢复。
以下保留历史检查点，旧状态摘要不撤销后来的限定验收。**第一阶段仍未完成。**

此前限定检查点：[P3持续发生关联](M1_BODY_OCCURRENCE_ACCEPTANCE.md)接O01–O16
原端口、Create/owner/copy、activation/segment/首出口及conditional host顺序；
255定向、606组件/18标准和干净`8138986`的5,822冻结全仓通过，668源/99fixtures
守恒。首轮6失败full与test-only能力修复保留。P4/P5、原113构造/196字段及
完整M0–M2仍开放；[P4详细计划](M1_REMAINING_PROTOCOL_PLAN.md)保原16组义务，
不将profile存在当消费者已闭合。

此前限定检查点：[P2同步generator声明矩阵](M1_GENERATOR_MATRIX_ACCEPTANCE.md)
关闭16格及原输入/状态/当前结果/host连接；275定向、660组件/37标准和干净
`bd673cd`的5,676全仓通过，647源/92fixtures守恒。原full失败与确定性调度修复
保留。P3实际持续发生、P4/P5、原113构造/196字段及完整M0–M2仍未关闭；
以下历史基础检查点的P2开放状态不覆盖这一新结果。

日期：2026-10-16。**第一阶段未完成。** 本表按当前需求列出必须覆盖的部分；
它不把已实现组件重新命名为完整程序模型。阶段顺序见
[WHOLE_PROGRAM_MODEL_PLAN.md](WHOLE_PROGRAM_MODEL_PLAN.md)。

2026-10-18的[P2协议连接基础检查点](M1_PROTOCOL_FOUNDATION_ACCEPTANCE.md)限定通过：
155定向、334组件/11标准，以及干净`8a62a98`的一次5,401全仓；原5,294case与
78fixtures守恒，617源/82fixtures匹配。新增F合同和原端口/当前结果/no-entry
分支/生命周期连接；没有新的O发生能力。完整P2矩阵、P3–P5及M2仍未完成。
以下保留此前检查点的历史范围；不能据本批通过关闭下表任一未完成整体。

当前[C2/D3审计](M1_PROTOCOL_FAMILY_AUDIT.md)已把真缺口定位为协议到原CFG/端口
的义务，以及本次Drive到持续body执行段/首出口的发生关联。[计划](M1_PROTOCOL_FAMILY_PLAN.md)
保留F01–F24/X25–X28；P0审计及[P1联合合同](M1_PROTOCOL_CONTRACT.md)冻结完成，
F/O产品实施仍待P2–P5。五项旧IR与六项新启动throw
观察不等于产品协议已验收；原错误断言保留，603源/78fixtures未变，无新全仓。

此前限定接口：[L 内容/来源/原求值验收](M1_LITERAL_ACCEPTANCE.md)通过1,716组件/32标准、
冻结 `4bc55eb` 的5,294项全仓。原5,144 case/74 fixtures守恒；当前603源码/78 fixtures
指纹一致。精确Data内容与原Data/Reference求值分开，source/code-slot声明不证明
真实来源或对象身份；loop/call/resume、多state/forward与实际N/R已有有限组合。
下一项为C2/D3家族及M2构造原分母；**第一阶段仍未完成。**

此前限定接口：[S 状态地址验收](M1_STATE_ADDRESS_ACCEPTANCE.md)通过1,317组件/25标准、
冻结 `805c670` 的5,144项全仓。原5,055 case/72 fixtures守恒；当前590源码/74 fixtures
指纹一致。owner/selector精化原carrier，分支/loop/call/resume/INVOKE原端口和旧
ContentRead guard有组合验证；native/alias/实际source对应仍未证明。下一项为
literal预算/精确编码及core接入，随后C2/D3与M2。**第一阶段仍未完成。**

此前限定接口：[R3.3 验收](M1_PIPELINE_CLOSURE_ACCEPTANCE.md)通过722项组件/17标准，
冻结 `6947778` 的5,055项全仓；原5,011 case/69 fixtures全保留。跨同步调用host桥、
独立endpoint范围、同图buffer→flush→file与异常/pending/cleanup已有限组合，三项
真实OS见证单独归属。Q facet目标/基数、native/coherence/真实身份未闭合；下表
selector/literal/C2/D3/M2原分母仍完整保留，**不关闭第一阶段**。

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
| Python 函数入口与环境 | 环境及 entry-layout 接原 core；[R3.1](M1_CALL_ACTIVATION_ACCEPTANCE.md)将准确 caller→child activation/entry/actual completion 接到原 input/result/state，591组件、冻结`881cbfb`的4,951全仓通过。 | source signature/replay、真实 callable/code/role/activation 对应仍待恢复；旧 `record_body` 偏移不能用于新入口。 | 静态及限定动态关联通过，不算自动绑定或值身份/纯度证明。 |
| 控制与语言完成 | 同步 if/loop/binding/invoke；[C0](M1_CONTROL_INTERFACES.md)词法scope/typed port、packet/pending构造及CFG case dispatch；[C1](M1_CLEANUP_INTERFACES.md)同步cleanup/context及entry-relative copy/fresh组合243项组件、3,330项冻结全仓通过。 | with/except*、完整跨边界case合同、实际context/source/LoopInterface对应；挂起中的active cleanup与resumption组合。 | C0/C1静态声明组件已验收；完整控制类型/协议未齐。 |
| 挂起、恢复与逃逸 | C2B/首outcome及D1、D2.1–D2.4有限结构已验收；[D3审计](M1_PROTOCOL_FAMILY_AUDIT.md)保留28组义务，[P1合同](M1_PROTOCOL_CONTRACT.md)冻结原端口与发生字段；[P2](M1_GENERATOR_MATRIX_ACCEPTANCE.md)同步16格及[P3](M1_BODY_OCCURRENCE_ACCEPTANCE.md)持续实例/端口/host声明关联已验收。 | P4/P5接其余body/delegate/await/cancel家族的原消费者、当前状态及完整ledger；自动采集另属M4。 | P0/P1设计、P2/P3限定声明门关闭；完整F/O与C2.0/C2.4仍开放，不把声明当source/native/runtime证明。 |
| 状态 owner、selector 与 alias | StateLocation/Access、footprint 与版本 SSA；v2 storage 几何；[S接口](M1_STATE_ADDRESS_INTERFACES.md)接typed owner/selector、原Uses/实际occurrence和两完成端口，1,317组件/5,144冻结全仓通过。 | 真实owner/native地址身份、完整alias/partition及物理Mat对应；外部alias写与输入失效关系。 | 声明级精化接口有限验收；完整state/alias/native语义未完成，不授disjoint或变换。 |
| 所有 Python literal/表示 | [L接口](M1_LITERAL_INTERFACES.md)复用PythonLiteral，严格表示八类scalar/tuple、bits/complex/surrogate和预算；Exact Data及原direct/INVOKE NORMAL求值附件、v16与旧family隔离，1,716组件/5,294冻结全仓通过。 | AST/compile/code-slot与实际求值来源重放；运行对象identity；容器/格式化/展开内部协议与全部M2构造对应。 | 有限内容/来源/原端口接口已验收；声明不授恒值来源、纯性或删除/复用权限，完整M2及第一阶段未完成。 |
| 逻辑值、来源与物化 | v2 LogicalValue/Version、Provenance、allocation/region/materialization；G/D/P接原端口、scoped指代、独立来源与部分实际产出；[V验收](M1_VALIDITY_ACCEPTANCE.md)接source-derived带标签的actual/future贡献、每贡献替代支持、准确Mat范围与全读取区间威胁，649组件、冻结`550496f`的4,826全仓通过。 | 完整native writer/capture闭合、source/runtime及exact native slot对应；其它endpoint/native/coherence与whole-work实际来源对应；持久化仍需独立合同。 | G/D/P/V及R3.3限定buffered组合已验收；完整物理对应与第一阶段未完成，不证明ready或自动恢复。 |
| 资源身份及要求 | 原 core 静态 ResourceDefinition/Requirement/Use/Location，严格 v4；[R0](M1_RESOURCE_EXECUTION_DESIGN_ACCEPTANCE.md)六个CPU/OS见证；[R1验收](M1_RESOURCE_IDENTITY_ACCEPTANCE.md)的occurrence/instance/handle/requirement/access及当前支持302项组件、冻结`6fcac0f`的4,192全仓通过。 | 跨调用/denotation来源与物理身份仍待实际对应；不凭入口绑定授永久rights/capacity或ready。 | 声明级动态接口门已验收；整体未完成，runtime/source未授予。 |
| host 返回与资源完成 | R2.1接ticket/原效果、terminal、quiescence/retention；R2.2接event代次与consumer-start顺序；D/P接准确read/frontier/result/actual；[V](M1_VALIDITY_ACCEPTANCE.md)接Host/Queue/Endpoint支持与target lifetime，准确区段AND/OR，649组件/4,826全仓通过。 | 其它端点协议、native/coherence/捕获、完整Q facet及实际GPU对应。 | 已验收R3.3同图load/consume/save/flush与生命周期/Q限定组合；通用native协议与第一阶段未完成，不授ready/free/transform。 |
| Python/库/native 协议 | 113 AST 构造、196字段清单；数据/控制/资源分册及语言反例。 | 通用协议的输入/环境/状态/资源/完成字段逐条映射到核心类型；native 边界保守完整，内部未展开不算已理解。 | 分册已审补若干缺口，不等于 M2 整门通过。 |
| 现成图及捕获条件 | [工具调研](TOOLING_SURVEY.md)有实际小CPU证据；[P0来源声明](M1_PROVIDER_INTERFACES.md)已验收；[P1薄边界](M1_NATIVE_INTERFACES.md)的原生槽/规范分区、原生树来源引用及跨表示八域待证合同168项组件与3,215项冻结全仓通过。 | lifted slot 与具体实例/当前状态、真实tree映射和写回、artifact重放及动态occurrence对应。 | P0/P1声明组件已验收，完整T1及新adapter未完成。 |
| 运行证据接口 | 已有 sys.monitoring、module/dispatch、profiler/Kineto 和 raw records。 | 明确缺失/截断/冲突、clock/run/window 域；静态→动态→物理的强类型多对多对应；ETO 等字段导入。 | collector 已复用，统一对应未闭合。 |
| 合同与观察边界 | Q/M、effects/proof ledger、v2 contracts；[D](M1_CONTENT_CONNECTION_API.md)已接精确required output或显式endpoint/facet/protocol要求及实际观察根。 | 完整返回/必要状态/文件视频日志/异常完成/RNG梯度identity顺序合同的真实source/native协议及全过程组合；facet不自动生根。 | 显式Q声明连接已验收，整体边界自动恢复与证明未完成。 |

第一阶段关闭要求是上表接口能组合并被机器校验，且 M2 的每个构造有明确
phase/依赖/效果/完成规则与反例依据。静态模型可声明外部约束，但不得把声明
当作已观测或已证明的实例。未知内部依赖保留具体边界，不吞掉周围已知结构。

M2 的初始 `field_coverage.json` 是审计快照；后续
`artifacts/experiments/b1_call_operands/model_stage1_audit/closure/review.md`
已在限定文字修订范围关闭 G1–G6。不能把原 12 GAP 重报成当前新失败，也不能
由该文字复审宣布 M2 实现或全门通过；113 构造/196 字段的接口合账仍需完成。

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

# 完整程序模型的实施顺序与自主验收

日期：2026-10-16。这是当前优先计划，修订旧 N2 中先推进局部桥接的顺序。
模型依据：[WHOLE_PROGRAM_MODEL.md](WHOLE_PROGRAM_MODEL.md)。用户无需逐门审批。

2026-10-20 最新范围：[原存储值限定验收](M1_STORED_VALUE_ACCEPTANCE.md)通过961
相关项/913稳定源码，新增40。原访问上payload→state→load值关系与条件性执行查询
已落；Program27保持旧1–26 wire/Execution8，旧codec版本迁移显式保原义务。
[下一门](M1_STORED_VALUE_NEXT_GATE.md)先接准确load结果到通用旧消费者，检查构造
内新owner的原Region/边界表达，再返回F19原组合。不将未采native/source当已自动
恢复，不关闭原七族、P4/P5/M2或完整M0–M2，也不增加detector/backend。

此前范围：[当前对象身份限定验收](M1_FRAME_IDENTITY_GUARD_ACCEPTANCE.md)
已以231直接相关项/907稳定源码通过，保留上批全部196项、旧tests/fixtures与schema。
独立身份声明可接当前frame的真实F历史，不恢复stored-reference来源或数据版本；
原无声明None保持。[下一门](M1_FRAME_IDENTITY_GUARD_NEXT_GATE.md)据已有合同审查结果
先设计原访问上的store payload→state→load result关系，再返回原F19组合。
本批不关闭F19第1项/整族、P4/P5/M2或整个M0–M2，不引入detector/backend。

此前范围：[原 F18 条件性结构验收](M1_ASYNC_TERMINAL_ACCEPTANCE.md)
已以2104相关项/899稳定源码核验，累计九族接受，剩余七族。
P4 component/full、P5、M2 原113构造/196字段及完整 M0–M2 仍未完成。
[F19 finished子链](M1_ASYNC_FINISHED_REQUESTS_ACCEPTANCE.md)现有196直接相关项通过，
但动态同B/F历史桥和非finished native内部仍缺，不关闭F19第1项或整族。
[下一门](M1_ASYNC_FINISHED_REQUESTS_NEXT_GATE.md)先接已有端口/occurrence的真实残项，
不为正确的 opaque Unknown 无限加手工图。历史 M2 G1–G6 文字修订已限定关闭，
不重复计算为新 GAP。阶段验收后先向用户解释，再进入 M3 自动入口建图。

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

R2.3-D/P 已接原端口、消费者/Q 根、独立来源与实际产出；接续的
[V 内容有效性/贡献支持接口](M1_VALIDITY_API.md)通过
[649 项组件及冻结 `550496f` 的 4,826 项全仓验收](M1_VALIDITY_ACCEPTANCE.md)。
原 effect resolver 不再以 work 为 host INVOKE 存在前提；准确 actual/future 贡献、
区段 AND/OR、原 Mat 匹配、全读取区间威胁和精确 target lifetime 已接规范图。
完整 endpoint/native source/coherence 协议仍有准确缺口，MATCHED 不授变换权限。
[R3.1 动态调用及 work 物化集合连接](M1_CALL_ACTIVATION_API.md)现通过
[591 项组件与冻结 `881cbfb` 的 4,951 项全仓验收](M1_CALL_ACTIVATION_ACCEPTANCE.md)，
原参数/返回/状态端口没有复制；未知入口不能豁免已知线程冲突，声明不证明真实对应。
[R3.2 Q 与原执行证据组合](M1_PIPELINE_COMPOSITION_API.md)现通过
[677 项组件与冻结 `31bf2e4` 的 5,011 项全仓验收](M1_PIPELINE_COMPOSITION_ACCEPTANCE.md)。
完整 supplied-model 与期望合同义务独立保留；scope 未恢复不空成功，原 source effects
不依赖 read 偶遇；原端口、actual/future 与生命周期分别回查，一份 fresh context 与
一个派生总预算不代表 runtime/capture 完整。后续[R3.3计划](M1_RESOURCE_COMPOSITION_PLAN.md)
要求通用 load→produce→consume→output→flush/close/release 模型与有界 OS 见证，
明确端点、原生边界与生命周期，不把声明组合冒充自动建图。
随后继续 selector/
literal、剩余家族及 M2 构造分母。**完整第一阶段仍未完成。** 不增加 detector/backend，
不以手工夹具冒充 LeWM 自动恢复或以测试耗时冒充加速。

R3.3现按[接口](M1_PIPELINE_CLOSURE_API.md)完成
[722组件/17标准与冻结`6947778`的5,055项全仓验收](M1_PIPELINE_CLOSURE_ACCEPTANCE.md)。
原端口、host causal bridge、独立endpoint范围、buffer与flush内容边、empty/partial/
pending/cleanup在同图连接；三项真实OS见证不冒充automatic correspondence。该限定
R3计划关闭，下一步按原顺序补selector/owner、literal、C2/D3及M2全构造，不继续堆
资源协议小门。完整第一阶段未完成；不新增detector/backend或LeWM重型profile。

S现按[计划](M1_STATE_ADDRESS_PLAN.md)完成[状态地址接口](M1_STATE_ADDRESS_INTERFACES.md)：
1,317组件/25标准通过，冻结 `805c670` 的5,144项全仓通过。原5,055 case/72fixtures
保留，590源码/74fixtures指纹一致。多owner/selector共享原carrier，dynamic binding
按实际occurrence/分支/完成端口查询；native/alias/物理解释仍未证。不扩展detector或
backend。当时下一独立门为PythonLiteral精确内容/预算及core接入；其验收记录在下。

L现按[计划](M1_LITERAL_PLAN.md)完成[内容/来源/原求值接口](M1_LITERAL_INTERFACES.md)：
1,716组件/32标准通过，冻结 `4bc55eb` 的5,294项全仓通过。原5,144 case/74fixtures
保留，603源码/78fixtures指纹一致。精确内容、scoped来源与原求值分开，原Uses/
状态/效果保持；新Data可用性、loop/call/resume、多state与actual N/R/forward均
有有限组合。SourceExpression/CodeConstant不证明真实source/code-slot，容器内部
仍需M2；不以附件替对象identity。接下来先审计C2/D3原家族义务，再落实M2构造
与接口组合，最后核对完整M0–M2矩阵。自动恢复在M3/M4，不在本门冒充完成。
第一阶段仍未完成，不增加detector/backend或新的LeWM重型profile。

C2/D3现完成[源码与语言反例审计](M1_PROTOCOL_FAMILY_AUDIT.md)：既有C2B/D1/D2
结构不重做，缺F协议义务→原CFG/Use/result/state和O实际Drive→持续body入口/首出口
两条连接。[P0–P5计划](M1_PROTOCOL_FAMILY_PLAN.md)保留28组分母；P0审计及
[P1字段合同](M1_PROTOCOL_CONTRACT.md)已限定冻结，P2–P5产品实施尚未完成。
启动throw六观察推翻“构造异常失败总保持Created”等假设，原exit1与
JSON保留。此为审计/规划，不是新产品验收；603源/78fixtures未变，未重跑全仓。
现按已冻结F/O合同进行P2闭环实施，然后做全家族组合，不将模型接口缺失
整个推迟给M4采集，也不造native解析器/调度器作为前置。

此前[P2基础连接验收](M1_PROTOCOL_FOUNDATION_ACCEPTANCE.md)通过155定向、334组件/
11标准和干净`8a62a98`的一次5,401全仓。原5,294case/78fixtures全部保留；617源/
82fixtures匹配。只核限定F原端口、当前结果与no-entry生命周期连接，Execution
仍为7；完整P2矩阵、P3–P5、M2原分母均OPEN。它不替代当前门的完整交付。

后续[P2完整同步generator声明矩阵](M1_GENERATOR_MATRIX_ACCEPTANCE.md)现限定通过：
全部16格与原输入/状态/消费者连接，275定向、660组件/37标准，以及干净`bd673cd`
的一次5,676全仓；647源/92fixtures守恒。原完整回归1失败与确定性预算修复均保留。
该结果更新上述P2状态；Execution仍7，P3–P5、完整M0–M2及自动建图不因此通过。
下一步按原联合合同接持续body的实际发生与有条件host因果桥，再落实其余家族/M2。

随后[P3持续发生关联验收](M1_BODY_OCCURRENCE_ACCEPTANCE.md)现限定通过：
O01–O16接原端口、Create/owner/copy、持续activation/segment/首出口与有条件
host因果桥。255定向、606组件/18标准及干净`8138986`的5,822冻结全仓通过，
668源/99fixtures守恒；原full6失败与test-only能力修复各自保留。Execution8
条件选择，旧v1–v7字节不变。下一步按[P4详细规划](M1_REMAINING_PROTOCOL_PLAN.md)
落实F12–F24/X25–X27原消费者关系，然后P5与原M2分母。第一阶段仍未完成，
不新增detector/backend，不把supplied-model关联当自动恢复或LeWM加速。

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
   实施已收敛的规范连接（已验收）；[D2生命周期](M1_DRIVER_LIFECYCLE.md)按
   [冻结合同](M1_DRIVER_LIFECYCLE_CONTRACT.md)→body publication→no-body→session/drop
   →组合验收细化；D2.0已收敛，D2.1组件及冻结全仓已验收；[D2.2](M1_NO_BODY_ACCEPTANCE.md)
   836组件/21标准及冻结`006a0e0`的3,871项全仓已通过；
   [D2.3 session/release与E/F/P](M1_SESSION_RELEASE_ACCEPTANCE.md)974组件/27标准及
   冻结`f67037d`的4,009项全仓通过；[D2.4组合/公开范围](M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md)
   1,015组件/32标准及冻结`37baeaf`的4,050项全仓通过，后续补D3接口义务，
   不靠D1字段设计通过缩小完整C2分母。
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

- [R2.3关系合同](M1_RESOURCE_READY_CONTRACT.md)保留D/P/V：denotation/exact读取、
  来源派生贡献及Produced、读取区间/visibility/AND-OR；没有actual work的Host/Q
  root不造ticket。[共享G前置](M1_RESOURCE_COVERAGE_ACCEPTANCE.md)的原MatRef/scoped
  geometry查询432组件/6标准/9.768s通过，493指纹不变；三项真实CPU/OS见证通过。
  [clean冻结`aa2b917`](M1_RESOURCE_COVERAGE_ACCEPTANCE.md)的4,427全仓/473.159s
  通过，旧4,387测试与50fixture全保留；完整R2.3及M0–M2仍未完成，不用geometry代替其余义务。

- [R2.2 event/order](M1_RESOURCE_ORDER_INTERFACES.md)接准确record代次、原event状态
  和resource端口、实际wait及有限queue profile，到consumer Start的条件路径；
  497组件/7标准/9.382s通过，489登记文件指纹不变，历史v1/v2 wire保留。
  [clean冻结`e8121f0`验收](M1_RESOURCE_ORDER_ACCEPTANCE.md)的4,387全仓/476.489s
  通过，旧4,297测试身份与47fixture全部保留；后续R2.3必须
  接denotation/实际生产贡献和可见域，不能用条件顺序冒充完整ready。

- [R2.1工作基础](M1_RESOURCE_WORK_INTERFACES.md)接原Access/实际INVOKE completion、
  独立outcome/quiescence/retention，严格execution v2及独立历史v1 bytes；
  407组件/9标准/6.282s及[clean冻结`bb1b402`](M1_RESOURCE_WORK_ACCEPTANCE.md)的
  4,297全仓/461.721s通过，480源/47fixture前后一致，原4,192测试身份全部保留。
  [后续R2.2/R2.3](M1_RESOURCE_WORK_PLAN.md)仍须event代次、设备顺序到consumer-start、
  production/denotation/当前版本可用性；不得把R2.1重定义成整个R2已完成。

- [资源身份R1实现](M1_RESOURCE_IDENTITY_IMPLEMENTATION.md)接规范program snapshot、
  activation/segment/visit及原Operation/Value/Use、资源实例/handle/requirement，
  从原CFG/StateAccess推导当前发生，缺采不吞已知旧版本矛盾。
  302组件/14标准/4.575s通过；472注册源指纹不变，新增142项发生/资源检查。
  [clean冻结`6fcac0f`](M1_RESOURCE_IDENTITY_ACCEPTANCE.md)的4,192全仓/459.327s通过，
  472源/44fixture前后一致；原4,050测试身份/451源/42fixture全部保留。
  R2/R3、denotation/provenance及M0–M2未关闭，
  不把手工IR组合或证据引用当作自动恢复、runtime证明或LeWM加速。

- [资源执行R0](M1_RESOURCE_EXECUTION_DESIGN_ACCEPTANCE.md)完成三份独立终审与六个
  stdlib CPU/OS断言见证；core occurrence/旧EEG、资源/handle代次、INVOKE状态端口、
  work/host outcome及Completed/Ordered consumer支持的关系合同已收敛。
  在该设计检查点，[R1→R2→R3](M1_RESOURCE_EXECUTION_PLAN.md)仍待产品实现；
  当时451项注册源指纹与D2.4相同，没有重跑全仓、运行GPU实验或把设计当
  新runtime/ready证明。后续R1实现记录在上。

- [D2.4](M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md)通过真实body及driver active-cleanup
  组合、准确当前状态和私有pending/context转发；公开point保留原rule/scope与实际边，
  applicability保持UNKNOWN。1,015组件/32标准/18.022s，冻结`37baeaf`的4,050全仓/
  457.655s通过；451源/42fixture前后一致，原38fixture及4,009测试身份全部保留。
  下一批资源instance/work/ready、selector/literal、occurrence/provenance与M2守恒；
  不把手工组合图当自动程序恢复。

- [D2.3](M1_SESSION_RELEASE_ACCEPTANCE.md)实现逐边同时改名后的E/F must及解释T，
  当前R/B谓词P、current支持和callback失效；974组件/27标准/15.967s通过。
  冻结`f67037d`的4,009全仓/468.490s通过；443源/38fixture前后一致，原35份
  fixture和3,871测试身份全部保留。仅为声明合同内派生，不证明native/runtime。

- [D2.2 no-body](M1_NO_BODY_ACCEPTANCE.md)836组件/21标准/12.709s通过，
  冻结`006a0e0`的3,871项全仓/463.982s通过；430源/35fixture前后一致，
  保留原3,776测试身份。接通true mark与实际bool/owner/current-state，false
  保留原gate/Drive路径；不授native/source/runtime或变换权限。

- [D2.0合同](M1_DRIVER_LIFECYCLE_CONTRACT.md)已冻结字段及E/F→解释T、当前P的派生
  关系；同一有限方程脚本在conda lewm完成11场景/1,920有界单步核对，不是产品证明。
  [D2.1 publication](M1_BODY_PUBLICATION_ACCEPTANCE.md)741组件/17标准/10.937s通过，
  冻结`49201e7`的3,776项全仓/459.570s通过，423源文件/32份fixture指纹前后一致。
  v12及原Use/state查询已接通，独立审查和原始失败/完整证据已归档。

- [D2生命周期复审及实施门](M1_DRIVER_LIFECYCLE.md)已记录非raising no-body路径、
  多完成来源合流、callback后post失效及body/request状态分离。三项stdlib断言通过；
  另一脚本六组仅为观测，初稿错误与按原JSON修正均保留。该复审时字段仍OPEN，
  后续合同按上条收敛；
  本设计批不改产品或重跑D1全仓；原模型完整性分母保持。

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

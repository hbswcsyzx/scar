# 第一阶段后续执行与自行验收

2026-10-25。**执行计划，整体 OPEN。** 本文把当前实施对应回
[第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)的 S1—S5，不新设一个缩小的完成目标。
已完成的有限源码/接口门和失败均保留；不增加 detector、backend 或变换。

## 1. 顺序与可并行边界

| 合同节点 | 本次落实 | 交付与通过条件 |
| --- | --- | --- |
| S1 模型与来源 | 审计真实类/字段/codec/producer、身份与关系；固定声明/归档/索引职责 | 每个必需部分有明确表达及获取来源；缺失 producer 和重复权威逐条列明；审计通过不代表自动建模已完成 |
| S2 自动分母 | 复用已保存 source/call/native/OS 清单，保留定义、实际调用和资源的独立分母 | 入口自动发现，不手选业务函数；原缺采、未尝试和不支持项始终可查 |
| S3 自动连接 | 843快照已接回原真实运行；后继858静态快照已组合消费，继续汇总runtime增量与原生端口、内容/状态及资源关系 | 正规来源和有序端口接回唯一规范模型；source、引用、内容、state、ready 分别验收；不能以局部 PASS 关闭 S3 |
| S4 全流程 | 在所需新采集字段共同确定后跑未修改 LeWM 原完整入口，自动产生统一模型 | 从启动/import/加载，经推理/环境到视频写入和退出，全部必需关系无未解释断点；固定范围、版本和分母 |
| S5 汇报停止 | 给出实体、关系、自动流程、真实模型与覆盖说明 | 原合同 S1—S4 全部满足后停止讲解，不提前进入化简 |

S1 审计、已有数据的 S3 接线和独立产品复核可以并行；会改变同一规范事实或
同一 producer 的修改必须串行。长门运行前冻结实际依赖，执行中不修改其源码。

## 2. 当前实际下一门

当前正式静态源码快照为858个active bodies/2217个定义/151个文件，769 UNSUPPORTED、
590 NOT_ATTEMPTED。三kwargs图的846父快照上，后继12个既有图普通ADD及组合消费已完成；
resume02 actual exit0/651.143247s、12 ordinary-reader通过。原publisher消费失败396.750s
及首恢复失败140.046s保留；只修consumer顺序和module文本转交，未重publisher/lower。
更早三图门FAILED_ENV_FREEZE及metadata postflight0也不倒改。
[准确结果](../artifacts/experiments/source_frontend_remainder_composition_resume02_20261025/RESULT.md)
与[模型边界](SOURCE_CALL_MODEL.md)区分旧producer/新consumer及全部历史失败。

最新完整runtime接线仍绑定843快照：该fresh联合门已exit0，source binder1次、
不resume旧842；原100438调用中6699接其body，
其余source-only/unresolved全保留。source-membership ancestor API及private factory/
安装/公共消费均在此门实际执行。不能合并新旧snapshot数字。两项分别见
[revision](SOURCE_BODY_REVISION.md) 和
[ancestor](SOURCE_REVISION_RUNTIME_ANCESTRY.md)。

已通过的843 fresh门消费该快照、原完整 capture、原静态证明和准确 readonly compiler
witness，从当前 raw 独立读一次并调用既有 source→dispatch→SBA 公共链路。
不能 resume842 checkpoint、重 lower/compile/执行目标或移植历史动态身份。
计数由实际执行推导，保存新旧 namespace 及全部原未连接项。
准确结果、成本和剩余义务见
[联合门结果](../artifacts/experiments/first_stage_source_revision_current_review_20261025/RESULT.md)。

覆盖账本完整source/call门现已通过：2217定义、100438调用全部原成员入账，
其语义轴与另六域仍OPEN。全部637个stored chunk独立核过，查询只有12个样本；
不是完整依赖建模。[实测与成本](../artifacts/experiments/modeling_scope_retained_gate_20261025/RESULT.md)
及[独立审查](../artifacts/experiments/modeling_scope_retained_review_20261025/REPORT.md)分别保留。

native已推进到完整39796次dispatch，而非继续重复16-prefix：首次门暴露原生Tensor
与Python held Tensor并非一一对应，V2改为端口/对象/几何/内容四项独立资格。
第二门在20片后因处理成本主动中止，exit130；失败仍保留。静态快照/ABI复用已实施，
第三门在相同预算实际exit0：全39796次/127接口/156分片，Tensor端口111189，
held109288/未定1901，几何107483/缺口3706。GNU28:41.75，peak1091472KiB；没有目标重跑。
这只关闭dispatch端口接入，不关闭所有native内部或内容/state/ready。
[模型与实际结果](NATIVE_CAPTURE_BATCH.md)和444baadb保留范围、失败及准确版本。

当前并行实施边界：

| 分工 | 具体模型断口 | 下一项实际验收 |
| --- | --- | --- |
| native接入 | 全dispatch端口门已通过；逻辑内容/state/ready仍缺关系 | 保留全部动态资格与原分母；后继连接原生值、状态和资源，而非再跑prefix |
| source-call前端 | 65窗口产12成功图；原12ADD publication经修consumer后已组合为858静态快照，12普通reader通过，旧失败保留 | 汇总增量接线；runtime仍843，179calls仅潜在权重；原2FAILED/后续重试不在本12ADD，保留unwind/outer/effects和comprehension等缺口 |
| main组合查询 | 实际79592/39796完整一次导航门已exit0，5个不同角色的查询样本通过 | 160压缩块及一个派生关系样本独立复核通过；后继补实际数据/状态/控制连接，不把context当direct call |

计划及来源分别在`artifacts/analysis/kwargs_expansion_design_20261025`和
`artifacts/analysis/source_native_composition_20261025`。历史collector只有HEAD label、缺
执行时SCAR源码字节证明；同issuer实现机制是条件合同，不能据当前源码授原运行无条件
对象身份。首个组合查询因此不发布跨source/native的对象同一性结论。

后继采集的[collector来源profile](COLLECTOR_EXECUTION_WITNESS.md)已在唯一CPU样例完成
实际注册/关闭/普通坐标绑定。它只补未来采集的可验证来源，不升级原LeWM scope。
新episode仍待其它必要采集字段共同确定，不为此单独重跑目标。

已完成的源码窗口为65个此前未进入新前端的普通函数，关联原运行1713次调用、13文件。
它们来自原自动候选/实际尝试/新发布delta的准确qualified key扣重，不是业务函数名单。
590项NOT_ATTEMPTED中的260次已见调用属于class-entry接口，不能当普通函数批量补lower。
该窗口规划使用准确匹配的843 composition及其runtime报告；846仅作发布排除和后续ADD目标，
不能伪造846运行报告。新`eligible_body_keys`只缩调度窗口，保完整2217定义和100438调用分母，
选择及当前producer进入新plan digest/work key，不resume旧window。

本批已批准65/13的调度上限，计算预算4000ops/body、24000总ops、worker180s，
record/output128MB、outer300s、批准累计stored+decoded输入1GiB。实际65全terminal：
12成功/179calls、51不支持/1501calls、2失败/33calls，outer174.766s/worker144.349s。
process rchar430228980不含解码；累计I/O计费/上限验证仍OPEN，原570MB decoded/100MB
stored仅声明/代码估计。12图后继用1800s ceiling的普通ADD/consumer完成858静态快照，
完整runtime仍843；没有为每个body重扫100438调用或把2失败改为成功。

## 3. 关键缺口与处理原则

2026-10-25后继两门已按同一模型验收并接入main：

- 原生输入metadata的owned归档与普通成员归属：唯一CPU采集target/CLI0，原验收脚本
  因误读launch字段exit1；同一归档postflight0/1.760928s。2332条/3块、4个成员的
  `process_for`及归档前后RunID通过。只关闭artifact/actor归属，不升级旧LeWM采集、
  原生端口、Python对象或内容/state/ready。准确三源码及原失败/新consumer见
  [归档与成员](NATIVE_TENSOR_INPUTS.md)，main e5343347、隔离存档350b3bc4。
- GeneratorExp一主体门exit0/21.567357s，312静态操作；创建/lazy B/两个driver/
  固定解包consumer以原core表达，独立source/CodeWitness及公共SourceProgram5通过。
  main八文件精确接入后，同一图普通读回exit0/9.830950s，五Region全部保留。
  原900父调用是权重；尚未发布/运行连接，source858/runtime843不变。默认能力与
  `eligible_body_keys`保留，close/throw/effects等OPEN；见
  [创建与驱动](SOURCE_GENERATOR_EXPRESSIONS.md)，main792b1228、隔离存档aad9a534。

下一批源码只准备把三张已验收图（两string148/131、generator312）一次ADD/consume；
禁止再lower或按body重扫runtime。自动入口P0则先接`--from-capture`的metadata规划及
合法fresh monolithic链，原返回检查点handoff和partitioned frontend/schema接线仍是
明确阻断。引用型workflow root不取代规范图、不以存在根报告计完整。
准确接口、预算与分步验收见
[自动入口设计](../artifacts/analysis/model_run_orchestration_design_20261025/PLAN.md)。

- Python 源构造、函数环境、actual/formal、return、generator creation/drive：
  按实际失败类型补通用前端及协议接线，保持定义与动态发生独立。
- 逻辑值及物化：区分引用、内容版本、来源、view 和物理副本；不依赖裸地址、
  Tensor `_version` 或少量样本证明恒定，不默认保存 Tensor 全部数值。
- world/state/effects：把实际读写和不完整接口落到具体位置及前后态，不能因
  schema 或 `.eval()` 推出纯性，也不能把独立子图的 world token 直接拼接。
- OS/CUDA 资源及 ready/lifetime：来源选择覆盖和实际连续性证明分别处理。
  FD namespace 当前临时隔离不是终局；数值证据保留，继续补有范围的控制闭包。
- 完整入口及存储：复用原规范图与分块归档，查询索引可选。整程序组合必须由
  工具机械产生，不能最终依赖实验脚本里的业务名单或手填规范图。

## 4. 每门报告和版本管理

执行前写明原要求、输入/producer 版本、预算、输出及拒绝边界；实际运行后保存
exit、耗时/内存、产物位置与 receipt、观测范围、未满足项和下一动作。由 agent
复核其负责接口，root 审查组合与范围后提交；不让用户代替执行逐门验收。

验证只覆盖修改的必要风险和真实数据路径，复用已有归档及一次联合读取。
已发布artifact和实际PASS记录不因小修复重新生产；先做定向消费检查，必要全量接线
按批次统一运行，不为每个body重扫100438调用或重跑已通过的全native门。
失败与部分产物原样保留，不以增加测试数量或重复全量采集代替缺失的模型关系。
所有结论区分 Observed / Inferred / Proposed / Implemented / Verified / Rejected。

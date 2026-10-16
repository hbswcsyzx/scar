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

先落实 [工具复用审查与集成设计](MODELING_INTEGRATION.md) 的 T0/T1：模型中明确
哪些事实直接复用 ast/symtable/dis、FX/Export、ETO/Kineto，及其类型/状态/范围
映射。不再扩大与这些接口重复的 Tensor tracer；Python source lowering 优先
评估成熟前端，不能把自写完整编译器当作模型完成的先决条件。T2 以后适配器
建图仍属后续阶段，不越过用户要求的第一阶段停止点。

1. 统一 ControlPort / EnvironmentInterface 与规范状态参数，扩展既有 core 的
   completion target、pending cleanup 与 protocol adapter；先处理同步异常。
2. 接 SavedFrame / ResumeRequest / continuation generation，再处理 generator、
   closure/callback 与当前共享状态；不能冻结 yield 时 world。
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

- M1 [C0控制协议组件](M1_CONTROL_INTERFACES.md)354项通过，源指纹含356文件；冻结
  全仓回归待执行。仅验证scope/port/pending/packet和CFG组合，C1 cleanup/context/
  原token来源保持仍未实现，不称完整finally或M1通过。
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

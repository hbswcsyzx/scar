# 第一阶段后续执行与自行验收

2026-10-25。**执行计划，整体 OPEN。** 本文把当前实施对应回
[第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)的 S1—S5，不新设一个缩小的完成目标。
已完成的有限源码/接口门和失败均保留；不增加 detector、backend 或变换。

## 1. 顺序与可并行边界

| 合同节点 | 本次落实 | 交付与通过条件 |
| --- | --- | --- |
| S1 模型与来源 | 审计真实类/字段/codec/producer、身份与关系；固定声明/归档/索引职责 | 每个必需部分有明确表达及获取来源；缺失 producer 和重复权威逐条列明；审计通过不代表自动建模已完成 |
| S2 自动分母 | 复用已保存 source/call/native/OS 清单，保留定义、实际调用和资源的独立分母 | 入口自动发现，不手选业务函数；原缺采、未尝试和不支持项始终可查 |
| S3 自动连接 | 先把已发布843源码快照接回原真实运行；并行审查原生端口、内容/状态及资源关系 | 正规来源和有序端口接回唯一规范模型；source、引用、内容、state、ready 分别验收；不能以局部 PASS 关闭 S3 |
| S4 全流程 | 在所需新采集字段共同确定后跑未修改 LeWM 原完整入口，自动产生统一模型 | 从启动/import/加载，经推理/环境到视频写入和退出，全部必需关系无未解释断点；固定范围、版本和分母 |
| S5 汇报停止 | 给出实体、关系、自动流程、真实模型与覆盖说明 | 原合同 S1—S4 全部满足后停止讲解，不提前进入化简 |

S1 审计、已有数据的 S3 接线和独立产品复核可以并行；会改变同一规范事实或
同一 producer 的修改必须串行。长门运行前冻结实际依赖，执行中不修改其源码。

## 2. 当前实际下一门

当前正式源码快照为843个 active bodies/2217个定义/151个文件。新的fresh联合门
现已exit0，source binder1次、不resume旧842；原100438调用中6699接当前body，
其余source-only/unresolved全保留。source-membership ancestor API及private factory/
安装/公共消费均在此门实际执行。不能合并新旧snapshot数字。两项分别见
[revision](SOURCE_BODY_REVISION.md) 和
[ancestor](SOURCE_REVISION_RUNTIME_ANCESTRY.md)。

本轮已完成门消费新843快照、原完整 capture、原静态证明和准确 readonly compiler
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
第二门完成全域枚举和127接口，20个分片（5120次调用）验证后由root因实现成本主动
中止，exit130；其余34676次尚未构建，不能称frontier或已通过。失败产物及代码已提交
`codex/native-scalar-model` 的31198ff9。下一门先消除SCAR每片重复的静态图处理，
预算不增加，再执行完整新门。

当前并行实施边界：

| 分工 | 具体模型断口 | 下一项实际验收 |
| --- | --- | --- |
| native隔离树 | 同一静态图反复校验/编码；实际端口与对象身份必须独立 | 精确不可变prepared snapshot与原source/catalog绑定，所有动态ABI/producer/Unknown检查保留；同预算完整实档门 |
| source-call隔离树 | 通用Call中kwargs pack/merge/call协议未建模 | 复用原IR/world/有序Uses，显式能力与独立compiler/异常审核；仅机械选原四个必要失败body |
| main组合查询 | 原source ancestry与native actual occurrence尚不能有界联合导航 | 只读qualified endpoints和typed retained-context；不将祖先当direct call，不重扫100k stream |

计划及来源分别在`artifacts/analysis/kwargs_expansion_design_20261025`和
`artifacts/analysis/source_native_composition_20261025`。历史collector只有HEAD label、缺
执行时SCAR源码字节证明；同issuer实现机制是条件合同，不能据当前源码授原运行无条件
对象身份。首个组合查询因此不发布跨source/native的对象同一性结论。

## 3. 关键缺口与处理原则

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
失败与部分产物原样保留，不以增加测试数量或重复全量采集代替缺失的模型关系。
所有结论区分 Observed / Inferred / Proposed / Implemented / Verified / Rejected。

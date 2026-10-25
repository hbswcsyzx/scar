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

当前正式源码快照为843个 active bodies/2217个定义/151个文件；已冻结完整
runtime 报告仍属于842快照，不能合并数字。新 source-membership ancestor API
已通过 depth2 的实际查询和错误祖先拒绝，private factory/新快照的完整接线尚待
运行。两项分别见 [revision](SOURCE_BODY_REVISION.md) 和
[ancestor](SOURCE_REVISION_RUNTIME_ANCESTRY.md)。

下一门消费新843快照、原完整 capture、原静态证明和准确 readonly compiler
witness，从当前 raw 独立读一次并调用既有 source→dispatch→SBA 公共链路。
不能 resume842 checkpoint、重 lower/compile/执行目标或移植历史动态身份。
计数由实际执行推导，保存新旧 namespace 及全部原未连接项。

同时复核已有 native bridge 的终态：它只验过16个 dispatch prefix 中的13个
ATen调用、4种静态接口及27条 Tensor 参考；内容版本、完整状态与 ready 未闭合。
后继应扩到实际全部 dispatch 的自动接入，并按真实缺字段补内容/资源对应，不能
反复运行同一个小 prefix 来代替全流程。详见 [当前桥接](NATIVE_PROTOCOL_BRIDGE.md)。

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

# G7.2b 下一节点：先接通引用、操作数与返回使用的证据链

日期：2026-10-13。基线：`d5fa963`，已在 `origin/main`。
状态：**历史子门规划，已暂停并存档草稿，未通过验收**。后续宏观审查发现
更根本的状态/依赖模型缺口，执行顺序以 [CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md)
的 N0—N4 为准。本切片不是建立统一程序语义的必要前置。

实测纠正：下面原规划中 profile + monitoring 可共同提供完整指令证据的假设
未成立；CPython 3.14.7 后续探针显示启用 profile 会丢失所需 INSTRUCTION。
替代探针不等于 collector 已完成。完整 WIP、80 项组件通过及 1 项集成失败见
[存档分支](https://github.com/hbswcsyzx/scar/tree/wip/reference-evidence-20261013)。

## 1. 为什么调整原来的执行顺序

主代理与三个组件审查者、一个独立架构审查者复查了当前实现。
`proof_ledger_v2._reuse_obligations` 的四项义务仍固定为 UNKNOWN；
`_outcome` 对 REUSE 返回 NOT_YET_SUPPORTED。这是尚未实现的证明能力，
不能解释成已证明所有复用均不合法。

更前面的模型缺口是：当前 REUSE delta 只能删除 invocation，甚至禁止
substitution；已有 ValueSubstitution 只有版本替换，没有精确到某次 consumer
的输入使用。因此还没有一个完整的 before/after 可以交给证明器。

原工作草稿在四个文件中已有 2,295 行、尚无测试。不能以这些草稿决定架构。
本节点先缩减职责、复用现有 codec 和 code/source correspondence，再实现：

```text
函数入口实际绑定的引用
  -> 第几个源码 READ occurrence
  -> 这次执行的 primitive
  -> 这次产生的结果 occurrence
  -> 这次 Return 的使用位置
```

`is` / `is not` 只用作验证连接正确性的最小原语。它们本身成本很小，
不是本阶段的性能优化目标。若只能报告“两次 True 相同”，本门不通过。

## 2. 核心建模决定

| 实体/关系 | 本节点含义 | 明确不包含的命题 |
| --- | --- | --- |
| ObjectID | 本采集会话内真实 Python 对象引用的身份 | 内容相同、Tensor storage 相同 |
| ReferenceObservation | 在某个入口/返回事件直接采样到某个引用 | 创建时间、持续存活、未观察期间没有变化 |
| OperandOccurrence | invocation、READ operation、operand index、指令 offset/subindex 的连接 | READS_SLOT 集合能够替代有序的重复读取 |
| Result occurrence | 这次 primitive 与这次返回之间的特定结果关系 | True 单例相同就合并两次 producer |
| ReturnValueUse | 静态结果槽到 Return，再到函数返回槽的使用 | enclosing function 的所有外部消费者已闭合 |
| EventPoint | 单一 collector 会话的顺序钟 | 与另一 observer 同 ordinal 即同时发生 |

### 2.1 引用身份和内容身份分开

需要接入现有 EEG/ValueGraph 时，用明确的 `python.object_reference` 语义域。
这是引用值，不是被引用对象的 Tensor/NumPy/list 内容。一个对象在本会话内
保持同一引用版本；内容写入不会由此获得稳定性证明。

同一个引用对象复用一个 regionless reference materialization；多次采样
产生多条 observation，**不产生虚构的新物理副本**。该表示不声称对象分配、
storage、设备复制或 Tensor ready event。旧 `region=None` 记录不会自动升级
成有效对象证据。投影只需轻量对象表，不建设第二个通用 provenance registry。

输出 True/False 只按实际 `type(value) is bool` 及单例身份记录。单例的对象
表示可共享，每次结果的 producer、observation 与 Return use 必须分别保留。
从一个使用反查来源时，不能选择“这个 bool 的任意 producer”。

### 2.2 观察范围与可信性

默认用 weak reference 并以实际 `is` 核对，不能只按裸地址复用 ID。
不支持 weak reference 的一般对象仅在显式、有限 strong lease 下采集；
上限约束引用数量，不等于限制对象可达内存字节。关闭采集器释放这些引用。
采集会影响引用寿命和执行时间，报告应记录，不能称完全透明。

每个采集器有随机 capture namespace/scope 和一个公共顺序钟；不同采集器
不自动合并对象或时点。本节点不实现通用 lifetime interval、live reuse guard、
Tensor 内容比较、跨 observer 身份合并或未来调用有效性证明。

序列化记录是历史证据。结构校验和 source replay 不认证任意外部 JSON 的
真实性；活动 collector 的私有原始记录只核对本次真实采样，不是安全沙箱，
也不是未来调用的 guard。JSON 不能恢复进程内引用或运行时采集权威。

## 3. 观察到的事实与推导边分开

本机 CPython 3.14.7 探针已观察到 profile call/return 与 sys.monitoring 的
PY_START、INSTRUCTION、PY_RETURN。monitoring 回调没有 VM operand stack。

| 事实 | 状态与依据 |
| --- | --- |
| 函数入口 frame locals 的实际参数引用 | Observed：profile call |
| 实际执行的 load / IS_OP / return 指令 offset | Observed：monitoring callback |
| 参数引用对应第几个 READ operand | Inferred：精确 source/code witness、受限无写入指令序列 |
| 实际返回的 Python bool 对象 | Observed：profile return 与 PY_RETURN 一致 |
| IS_OP 结果进入这次 Return | Inferred：精确相邻指令与 source ReturnValueUse |

首个支持范围：普通同步 FunctionType，函数体恰为一条
`return Name is/is not Name`，操作数为必需参数。重复参数的两个 occurrence
必须保留。无装饰器、默认值、annotation、closure、调用、分支或写入。
源码与 loaded CodeType 必须按现有精确 digest 规则复现，不归一化 hash 来
强行匹配。只支持明确验过的 runtime/bytecode，其余给出具体不支持原因。

已有 profile/trace、其他相关 monitoring 工具、外线程事件、重入、丢失/额外/
乱序事件、code/source 改变、预算超限或异常退出不得形成完整样本。profile
没有普通 Python exception 事件；用实际调用异常及缺少有效 PY_RETURN 判定。
原函数只执行一次，失败也不能为补证据偷偷重跑。

## 4. 职责分工与代码范围

1. **对象引用表**：轻量 typed record、会话 ID、采样记录和可选 ValueGraph
   投影；复用 `record_codec`，不保留草稿中的未来 guard 框架。
2. **Source adapter**：复用 source semantics、primitive semantics 和
   `CodeSourceWitness`，补 operand occurrence、offset/subindex、Return use。
   必要时小幅提取 correspondence 公共 helper；不复制完整编译匹配框架。
3. **Capture/join adapter**：实际 profile/monitoring 回调、有限事件记录，
   重算完整序列并接入现有 SG/EEG。公共结果包含具体缺口，不能只给 valid=true。
4. **主代理集成**：独立检查上述接口、反例测试、已有图查询、外部 fixture、
   测量、gate、验收报告与 Git。子代理先报接口，职责不交叉；模型按任务选用。

本节点不改 OIR schema、REUSE outcome、backend 或目标程序。

## 5. 验收节点（开发代理自行执行）

| 节点 | 必须得到的结果 | 不能通过的情况 |
| --- | --- | --- |
| E0 设计冻结 | 本文、职责、证据范围及待办清楚 | 为兼容草稿扩大目标 |
| E1 对象与 source | 同/不同对象、等值不同对象、重复 operand、is not、精确源码失效和严格 serde | 调用用户 eq/hash/repr；identity 当内容稳定 |
| E2 实际 capture | 真实执行 fixture，原始事件连到 SG/EEG，Return use 可反查有序输入和来源 | 手填 Observed 代替运行事件；结果单例合并 producer |
| E3 反例与资源 | 错序/缺失/伪造关联、跨会话、code 变动、hook 共存、异常、预算和清理测试 | 偷偷重跑；失败后遗留 profile/monitoring hook |
| E4 自行验收 | 冻结实现提交，mapped gate、整仓回归、外部报告/分析开销、失败记录、验收提交及 push | 把证据门写成正向 REUSE 或 LeWM 加速 |

外部 fixture 至少包括普通对象和 PyTorch Tensor 引用（内容改变但身份不变），
有 CUDA 时记录真实 GPU Tensor 情况。普通观察不读取 Tensor 内容、不复制到
CPU。测量记录 runtime、设备、warmup/repetitions、min/max/median/variance；
这是采集/分析开销，不是优化 A/B。测试数量仅作实际记录，不作目标。

## 6. 停止扩展条件与后续依赖

证据链可由既有图查询消费且独立 gate 通过，就结束本节点，不增加其他原语
或包装成通用缓存。若仍需大量独立框架，先审查可复用职责与具体消费者。

随后重新设计精确变换差量：

1. 写出 before/after，区分删除的 primitive、保留的参数求值/调用/return；
2. 精确指定 consumer occurrence、替换结果与其可用事件；
3. 分离历史路径证明和未来 guarded plan，明确 miss fallback、失效与 Q；
4. 再实现账本的正向 REUSE；成本不划算仍选择原执行。

跨层上移仍需 region 输入来源、availability、支配、零次循环、跨越效果和
新增 live range；本节点没有解决这些义务。G7.3 的 import provenance →
CONSTANT 与独立 import DEAD 证明继续按原计划进行，随后 G7.4 用外部 LeWM
做压力验证。用户期望的顶层完整修改指导始终是目标；本证据门不是替代品。

目前 LeWM 无已选变换、无已验证加速比。此前 1,064 项回归及 MOTION 条件
正例属于 `d5fa963` 之前的验收，不能用作本节点测试结果。

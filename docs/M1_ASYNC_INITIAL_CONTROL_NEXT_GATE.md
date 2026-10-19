# 下一门：原分母合账，然后返回全程序模型验收

2026-10-19。当前门最终相关回归 2058 项通过；
[原 F16 条件性结构验收](M1_ASYNC_INITIAL_CONTROL_ACCEPTANCE.md) 已有准确收据。
本门实际尝试见 [进度](M1_ASYNC_INITIAL_CONTROL_PROGRESS.md)，
原 F16 与真实 Unknown 的区分见 [原要求审查](M1_ASYNC_INITIAL_CONTROL_F16_AUDIT.md)。

## 1. 先收当前门

保留两项旧产品首红、首轮四失败、联合来源反例和修订版三失败。
准确来源投影、普通 copy、内容 None、当前状态和 native 真实性分别记账。
原 2016 项通过 2010 个精确身份及六个显式 future-version 迁移保全；
最终只追加四个新模块的 42 项，不重复已有 selector。
全部作者冻结、root 串行；最终结果、源码指纹和原义务逐条相符后才关账。
正常 commit/push 并核远端 SHA 和干净状态；不等待用户逐门批准。

## 2. 有界剩余要求

本门按原条款接受 F16 后，16 族中还保留以下八族。它们是原分母，不是新
需求或每种 raw/出口的笛卡尔积。先核已有准确 selectors，再补真缺口。

| 原条目 | 已有证据应复用 | 仍需核实/补齐 |
| --- | --- | --- |
| F18 | 原自然完成、已知 nonNone 拒绝；本门第四次 Drive 的自然 Return→现有 constructor own N/R/packet/host | 主动 StopIteration/StopAsyncIteration 的实际转换来源、自然完成规则不可吞主动异常、源级非法非空 return；不能把本门有限 Return 补充当整族通过 |
| F19 | 四 raw 来源、THROW/CLOSE 正常化与失败全状态、request 不释放未结束 B | 限定版本的 closed/athrow/aclose 与非法 yield 后续体；request、native bit、continuation、frame release 分别核 |
| F20 | 原 GetIterator、首次 next lookup/call、backedge 拒绝 | 源表达式 own N/R→GetIterator、非法 iterator 与首次 exhaustion 的实际父消费者；不能凭零挂起制造 Suspend/Attach |
| F22 | 1–3 原参数 ordinal、方法 lookup 和 missing fallback | 同次 THROW 的 item/exhaustion/missing method 到合法父恢复或无恢复整链；原注入、新 lookup/new matcher 包分开 |
| F24 | 原 cancel 请求/target/packet 表达 | 实际交付→handler 抑制/C1→再 await 或准确终态、实际 waiter 转发；请求成功不代交付 |
| X25 | 已有 C1/pending/context/local 与 cut/merge | 对照原条目核跨至少两 cut/loop 的完整来源及 fresh Replace/旧 token 反例，已通过组合不重做 |
| X26 | 原 publication、session/post、release 和宽 helper | 核 partial RAISE、真实终结与当前 session 到释放的组合；request 结束不授 frame 释放 |
| X27 | 已有持续 activation/逐次 Drive、缺采和多实例 | 对剩余 delegation/cancel 族补真实 ingress/outcome/实例/run/thread 与缺采分母；不重建已通过 async 主流水线 |

近期开门优先合账 F18/F19：本门已有自然 Return 的实际桥接，不能重复实现。
先列“原条款→现有端口/查询→明确残项→有限反例”，确有无法表达的依赖才改
模型或固定 profile。已有原操作/状态/效果足够时连接它们，不再新增平行图。
native 探针只核限定运行时事实，不把观察 bool 或数值相同升级为 source proof。

## 3. 返回原阶段门

八族完成后核 P4 component 和冻结 full；再核 P5 原 F01–F24/X25–X28 完整
ledger、公共面、wire、预算/游标及独立复审。相关定向通过不能代替这些门。
随后逐项对照 M2 原 **113 构造/196 字段** 的求值阶段、顺序、隐式调用、
作用域、状态和完成规则；它们不是 113 个自制 lowerer，也不要求每项与全部
协议出口做参数积。旧计划的摘要要与近期准确验收合账，保留历史原文。

第一阶段是可表达、可连接、可拒错的完整建模合同；自动从真实程序恢复该
模型、核 provider/native 适用性是后续独立交付。两者不可互相代验，也不能
把后者所有未知无限倒灌成前者的新前置。

## 4. 全程序与自动化顺序

按 [第一阶段矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)、
[全程序计划](WHOLE_PROGRAM_MODEL_PLAN.md) 及
[工具整合](MODELING_INTEGRATION.md) 复用 source/bytecode、FX/Export、
profiler/provider。五类实体仍是 Operation / Value / StateLocation /
Region / Resource，数据、控制、状态版本、资源/顺序边具有不同合同。
可递归 Region 支持从入口到子调用、operator 和 runtime 证据的映射；不得
因同一图中重复节点或同型 Tensor 而授 reuse。

完整 M0–M2 验收后先停下向用户讲清核心实体、连接、范围与剩余真实性边界。
随后才进入入口驱动自动 Python shell→工具恢复的 tensor regions→实际证据
对应→观察根闭合→自顶向下化简指导。手工图只能验证模型，不能宣布已经自动
拆解整个 LeWM。本门不添加 detector/backend，不改 LeWM，没有新加速比。

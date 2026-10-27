# R2.3-V：内容有效性与贡献支持接口验收

日期：2026-10-18。**本门限定接口已通过；完整第一阶段 M0–M2 未完成。**
实现冻结提交：`550496f328dbe9941e0a06a6de8c76181fa28039`。
[计划](M1_VALIDITY_PLAN.md)、[接口及事实归属](M1_VALIDITY_API.md)、
[原始证据与只读 checker](../artifacts/experiments/b1_call_operands/model_validity/README.md)。

## 1. 此门解决的连接问题

查询从原 ContentRead 及独立来源清单出发，派生 write、实际产出、准确范围和
消费者支持；调用方不提供可任意删小的“完整贡献列表”。不是重复节点即复用。

| 关系 | 含义及约束 |
| --- | --- |
| canonical effect | 解析原 StateAccess 或本次实际 INVOKE 的输入、successor、CompletionResult 和 landing formal；不以 work membership 为 host effect 存在条件。 |
| EstablishedProduction | 无 Work 的 Host/External 原操作实际建立范围；不虚构 WorkOutcome，不绕过 Work 的 terminal/实际部分产出。 |
| TargetLifetimeEvent | 精确 target incarnation 的 LIVE/RETIRED 声明；handle end、借用结束、terminal 和 quiescence 不等于 allocation retirement。 |
| OrderAssociation | 严格 causal-before，连接原坐标；不作时钟换算。未知协议仅 assumption，不能充当已解析顺序。 |
| ContributionSupport | 准确 read/write/production/domain 内的 Completed 或 Ordered 替代项；每项有原依据、路径、条件及缺口。 |
| labeled coverage | 用原 RegionRef 和既有 G 几何计算各需求区段的覆盖，保留标签；每段 OR，再组合需求 AND，不把版本和范围交叉配对。 |
| whole-interval stability | 扫描独立来源、全部原写/未知边界、准确 lifetime/handle end；不因同 owner 或两端 state 相同而删除中间威胁。 |

不复制 ProgramGraph 的 producer、Use、StateAccess 或 state SSA。实际 Region 与
原 write Mat 的 artifact、allocation 及范围守卫独立于 BytePrefix 协议；未知协议
不能豁免已知结构矛盾。`placement_match=None` 不参与实际内容覆盖。

## 2. 已验证的机械区分

- A 已实际产出左半，B 为未来 pending 且到 consumer Start 的 Ordered 路径匹配：
  known coverage 为 INCOMPLETE，conditional coverage 为 COVERED、支持为 MATCHED；
  未来成功产出、错误传播及来源/native/stability 条件仍在。
- 两份实际部分产出可以覆盖 whole；缺 B、错版本、错 queue 或缺原 wait 不能借 A
  的支持补齐。FAILED/CANCELLED 保留实际 prefix，不能扩大为请求 whole。
- 原 stage 已有实际结果声明但缺 Outcome/Produced 对应时，禁止 pending 请求兜底。
  删除关联不会把已见 short result 改为未来完整写入，也不从 raw 另造 Outcome。
- 同贡献内一条 MISSING 替代项不否定另一条 MATCHED；当前有效片段已替代历史
  冲突片段时，另一个真正缺失区段为 MISSING，不被无关坏 leaf 污染为 CONTRADICTED。
  只有需求区段无好 leaf 而有匹配但被破坏的必要 leaf 时，才报告该必要冲突。
- 中间 write/restore、actual alias overwrite、准确 target retirement、地址/实例区分
  都保留；producer 内部可能被后写修复的写是 potential，不冒称必然冲突。
  请求范围重叠而 actual 为空/不交，也不能当成实际覆盖威胁。
- 共享预算计费来源、关联、几何、order、威胁与公式构造。默认仍 4096；密集历史
  片段回归显式 8192，未改变默认。记录/FK 校验、工件重放及 detached copying 另计。

## 3. 当前没有授予的能力

Host 原同线程顺序和准确 queue FIFO/event/wait 可作条件性匹配。EndpointDomain
可以表达并检查 target/Q 关系，但 read/flush/persist 的实际端点协议尚未解析，
相同 FactRef 也保持 UNSUPPORTED/MISSING。原 span 的 HB 没有 whole-ticket 起止角色，
不能因单一 WorkEvidenceBinding 升格为 WorkEnd→WorkStart。

完整 source/native writer/alias/window 捕获、实际物理 identity/coherence 和协议适用
尚未证明。查询中的 `source_runtime_verified`、`runtime_visibility_verified`、
`transformation_authorized` 始终 False；MATCHED 是准确声明组合的条件性匹配，不是
ready/free/transform 权限。free 仍需 ownership、pending work 及 quiescence。

## 4. 自主验收证据

| 检查 | 实际结果 |
| --- | --- |
| 联合组件 | **649 cases / 11 criteria / 18.653s**，全部 PASS；544 个源码哈希前后相同。 |
| 唯一冻结全仓回归 | **4,826 passed / 0 failed / 0 error / 0 skipped**；4 warnings。外部 494.393576s，pytest 492.17s，峰值 RSS 1,026,012 KiB。 |
| 冻结源码 | `72b0125417bc1bd78b1178873e8c8a18e9cfdfe4ff3dd897b4812212542731f9`；HEAD 前后均为 `550496f`，工作树干净。 |
| 守恒 | 原 **4,713** case ID 全保留，新增 **113**；原 521 源文件全保留，其中 505 不变、16 延伸，新增 23，共 544；原 **59** fixtures 不变，当前 **65** 全部前后相同。 |
| 清理与保护 | full 子进程退出后只删除其独占 basetemp；LeWM 和 SCAR main checkout 的 HEAD、干净状态不变。 |

Python 3.14.7、pytest 9.1.1、PyTorch 2.13.0+cu132、NumPy 2.5.2，使用既有
`conda activate lewm`。完整命令、明确环境、逐 case 结果、时间/RSS、失败及源码
哈希见 archive。以上时间是验收成本，**不是 workload A/B 或 LeWM 加速比**。

新增 113 cases：canonical effects 12、labeled G 8、strict records/budget 9、wire 28、
public argument boundary 2、domains 19、stability 10、query 19、actual placement 4、
OS witness 1、旧 codec 的新增 unsupported-v7 case 1。旧参数 case ID 保留。

## 5. 真实 OS 见证的精确范围

独占非阻塞 pipe：一次请求 **131,072 bytes**，实际返回/读取 **65,536 bytes**。
模型得到覆盖 `[0,65536)`、缺失 `[65536,131072)`，known INCOMPLETE，支持 MISSING。
这是一次真实 short write；不混淆旧 P 见证中的 desired 8、native request/return 4。

只把实际计数接入声明式 canonical fixture；没有自动恢复 pipe→core→RAM Region
或 lifetime/coherence 对应。构造夹具时先调整其声明容量，再走原验证 serializer，
没有 patch 产品 validator。首个夹具容量错误及修正后的实际 stdout 均保留。

## 6. 兼容、失败与独立复审

execution v6 仅在新表非空时自动选择；v1–v5 原字节、字段和 tag 隔离保持。v5 golden
从不可变 `f2b4672` 的旧 codec/旧丰富 wire fixture 独立生成，**64,321 bytes**，SHA
`3b6b736632012e17620c4f6233c8520f70db527d1391df67d7f3ef5cc2bef708`。
它是 codec fixture，不冒充已验证物理 execution。导入路径、旧 blob hash、命令、
首个不存在路径失败、清理 size/hash receipt 保留；重复 tar 和独占抽取目录已移除。

各测试 attempt 与 golden 生成失败均保留：Unresolved/协议参数、缺 prefix/resource、旧版本期望、枚举
联调、alias 声明、旧 implicit support、删除 work 的 prefix、默认预算截断及 endpoint
夹具错接。预算截断不是模型拒绝；曾过宽的 endpoint 正例不能证明实际协议。

独立交叉复审提出并关闭：原结果缺关联不能变 pending、unknown rule 的 Mat 错接、
同 OR 坏替代项污染、非必要历史冲突污染缺段、requested/actual 威胁混淆。
有限结论 PASS_WITH_SCOPE，原 OPEN 报告与 closure 均保留：

- `review/core-author-review.md`：`ae6f6205cb43bef574a4bf35848c683bbb035856f0578b2bdf10fef32b283370`。
- `review/query-author-review.md`：`fac30c4ddf83e715b7e3dbea8f8b9dbe73cafe3f445ec64a764c40c19a48eb5d`。
- `review/domain-author-closure.md`：`5ca8db04662e7fa926b5684d922daeb70f02d58c9eedc85bb0d4ae2350fd5c65`。

## 7. 下一阶段

继续 R3 的通用 load→produce→consume→output→release 组合审查与夹具，明确 endpoint
协议、跨调用/原生边界、contract 与生命周期如何相接；不写 LeWM 特殊规则。
随后按[完整分母](FIRST_STAGE_COMPLETION_MATRIX.md)补 selector/literal、剩余家族和
构造协议。全部 M0–M2 关闭后按用户要求停止并讲解；自动恢复/建图与化简在后续门。
本轮未新增 detector/backend/lowerer，也未新跑 LeWM profiling 或声称加速。

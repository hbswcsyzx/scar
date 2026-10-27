# 当前异步请求来源与状态连接：有限门

2026-10-19。起点 `9293836d75e9c1d9a64849749d1b8b92529908b1`；上一门为
verified progress：1854 affected focused、原1845身份保留、856稳定源码，归档
复核及推送已完成。本门不是整体M0–M2验收，不新增backend/detector。

## 1. 模型关系先于实现

Operation / Value / StateLocation / Region / Resource五类实体不变。R是请求
对象，B是持续body，L是R首次保存的raw请求，S是此次调用的scheduler raw请求。
它们不同的来源关系不能通过相同类型、名称或值合并。

后续THROW/CLOSE的目标关系为：当前S的原始recipe → normalization的原始raw
actual → 该normalization自身NORMAL结果 → 原BodyResume的THROWN_PACKET输入。
NORMAL/RAISE各自的完整状态元组仍在原操作上。旧IS_INITIAL_STEP布尔值可以
选择历史控制分支；经过helper后不能同时证明当前phase或gate资格。

现有 `request_delivery(first=False)` 对这条链无条件报告
`async_scheduler_packet_normalization_unresolved`。先以完整core有效供图证明
缺口，才修改公共来源连接。首次L路径、raw/packet类型和原codec保持。

## 2. 本门验收节点

| 节点 | 必须提供的证据 | 不允许替代的证据 |
| --- | --- | --- |
| S1 | 后续THROW和CLOSE各自S→normalizer ownN→实际packet，保留ownR和fullstate | 同kind的L、landing位置猜测 |
| S2 | 只把normalizer raw换成L的core有效负例；缺附件保gap与分母 | 坏core、删除delivery、把未知算False |
| S3 | 预算不足保cursor/原delivery；必要相关回归及原1854精确身份保留 | profiler计时、只跑新增测试宣称全仓 |
| R | 只读核F14/F16剩余原义务；若能有限构造真实完成→同R再call链则补NEW测试；否则明确原端口/连接缺口 | 单个COMPLETE布尔值冒充真实前次完成；多caller替代reuse |

不为关账补参数笛卡尔积；不会仅因S1–S3通过就关闭F14/F16。原16组及P5、
M2原113构造/196字段分母不变。已有A–H和F12/F13/F15/F17/F21/F23条件结构
验收保持。剩余原条款必须逐条给出自己的证据。

## 3. 执行与版本

root拥有公共产品、文档、归档、Git及全部串行Python/pytest/probe。协作者仅
在明确分配的NEW测试文件写入，不改旧fixtures/tests或模型schema，不运行
解释器；每次测试前所有作者明确冻结。失败尝试保存原command、日志、JUnit、
运行前后源码hash；区分构图错误与真正产品失败。最后冻结源码跑相关选择集，
核原1854身份与受保护仓库/旧归档，写验收报告，提交并核远端SHA。

下一阶段仍先补其余原族、P4组件/冻结全仓、P5与M2，然后按用户要求解释模型。
M3自动lowering与M4真实采集对应尚未完成；本门没有LeWM优化或新加速比。

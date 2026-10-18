# R2.3-V：读取有效性、可见域与贡献支持

实施基线：`f2b4672d9555348dcd05da62a8cd126711ef22f9`。上轮 P 的
477 项组件与冻结 `c84fbfe` 的 4,713 项全仓通过，源码及旧测试守恒已归档。
本门接续[完整 R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)，不新增 detector、backend
或 lowerer。本文是实施计划，验收结果另存；完整 M0–M2 范围保持。

## 目的

从原读取需求和独立来源图导出：哪些实际内容覆盖需求、每个必要贡献有哪些
可用支持、支持是否属于该消费者的可见域、内容是否在整个读取期间仍然有效。
不能仅由重复节点、完成状态、两端相同 state 或一个 ready 字段授权化简。

## 审查与实施顺序

| 节点 | 交付 | 自行验收依据 |
| --- | --- | --- |
| V0 模型审查 | 原 effect、带来源贡献组合、域/有效期三项独立源审，冻结接口及责任。 | 不复制 producer/Use/state；识别 P 尚不能表达的 Host 实际部分产出和 target retirement；协议条件不自证。 |
| V1 规范连接 | 共享原 StateAccess/实际 INVOKE resolver；Host/External 实际建立范围、准确 target lifetime、Host/Queue/Endpoint 域与支持关系。 | host 不造 WorkTicket；normal/raise/partial/unobserved 分开；实际范围不由请求或 COMPLETED 扩大。 |
| V2 贡献与覆盖 | 从全部 source candidates 接原 writer/actual selector，保留标签的 AND/OR 和需求覆盖。 | A completed+B ordered 混合支持；两部分联合覆盖；删贡献/work 不缩义务；同 stage 多证据不变多个独立 writer。 |
| V3 有效性与域 | 建立支持至整个读取区间的状态/alias/lifetime 检查；准确可见域及原事件代次。 | 中间 write/restore、alias、retirement/address reuse、错 queue/thread/endpoint；consumer End 不能代替 Start；retention 不能代替内容稳定。 |
| V4 联合验收 | 通用正反夹具、真实有界 CPU/OS 观测、D/P/order/resources 联合组件及独立复审。 | 原失败完整保留；预算/缺图/错图/旧版本/旧 case 与 fixture 守恒；不以手写夹具冒充自动 LeWM 恢复。 |
| V5 冻结归档 | 干净实现提交后一次完整回归，完整报告与 manifest，核对受保护 checkout，提交并推送核对远端。 | full 期间不改源码/文档、不启动其它测试；记录准确命令、源码指纹、耗时、失败及 owned temp 清理；checker 不启动测试。 |

V1–V3 的具体记录命名由 V0 审查冻结，不先堆表。每个关系只存原事实的引用及来源，
校验和查询从规范图重新派生结果，不接受调用者指定的“完整贡献列表”。

## 必须保留的建模区分

1. **原效果与 work 归属：** 解析原 StateAccess 或实际 INVOKE state input/landing
   是通用操作；是否属于某个真实 work 由调用者另核，不能把 work membership 当
   host effect 存在的前提。state transport 不自动证明 native read/write/字节范围。
2. **实际建立与请求：** P 的 Work Outcome.actual 只支持其原 selector；Host/External
   也需要可引用的实际建立范围，不借虚构 WorkOutcome 填字段。失败部分保留。
3. **生命周期与借用：** handle end、borrow release、work terminal、quiescence 和
   allocation/resource retirement 不互换。相同地址不能合并两代 target。
4. **部分贡献与血缘：** P.current_production 是精确 selector 的声明视图；V 必须
   检查全部来源候选中的部分写入。祖先版本不能仅由无重叠猜成目标版本的内容。
5. **选择器与支持配对：** OR 在同 stage/write/version/placement/selector/consumer/
   domain 内组合，再核必要部分的 AND。不同 tuple 的证据不能先 union 再交叉配对。
6. **读取区间：** 资源读取至少 WorkStart..WorkEnd；较窄 native 声明需要依据。
   Host anchor 的当前 state 只说明该点。两个端点相同仍可能发生中途写回。
7. **顺序与可见性：** 复用准确 event record/wait、FIFO/profile 与 consumer Start。
   host 点与 native 边界没有自动时钟对应；显式协议尚未解析时保留准确条件。
   host/queue/endpoint 的可读、flush 与持久化各自核对。
8. **来源闭合与权限：** P 的格式清单不证明所有 native writer、alias、进程及窗口
   已捕获。V 要计算有意义的条件支持和已知冲突，但不能将未闭合来源或任意 FactRef
   变成 ready、free 或 transform authority。

## 预算与正确性边界

原工件校验/重放有独立预算；图遍历、原效果/invalidator 枚举、路径及几何采用共享
且可报告的预算。fanout 和关联分组也计费；截断是未决，不是 independence。
返回 detached 的原需求、来源、每项支持、范围、冲突、条件及缺口。

构造字段、声明图有效、自动恢复、native 事实和优化权限分别验收。本门完成也不代表
R3、全部 M0–M2 或 LeWM 自动化简完成；之后按原分母推进，并在完整建模阶段结束时
向用户讲解节点类型与连接。不会把验收耗时作为 workload 加速比。

# R2.3-P：来源、写入阶段与实际产出

实施基线：`5ab22f8d8fcbabbc59d494b571651d480468f3d5`。本门接续
[内容连接](M1_CONTENT_CONNECTION_PLAN.md)，不增加 detector、backend 或程序改写。
以下是实施与自行验收计划，完成情况必须以验收报告为准。

## 要回答的问题

一条读取已经接到原端口和物化之后，仍需回答：该内容的来源是什么；哪些阶段
可能建立或改写它；实际 Outcome 支持多大产出范围；哪些关联仍无依据。候选来源
必须从独立来源清单枚举，不能让提交者通过删除 Work/贡献列表来使义务消失。

## 模型边界

| 连接 | 原事实 | 新关系与限制 |
| --- | --- | --- |
| 来源全集 | 给定运行的原始流、元数据 | EvidenceInventoryBinding 引用 manifest/index；hash/size/schema 精确校验，不打开 URI。给定文件格式闭合不代表捕获了全部实际写入。 |
| 规范化投影 | 原始物理 LF 行、既有 normalizer | 固定本包 recipe 重放，比较完整 bundle/coverage。不能把重新序列化的 JSON 当原始字节，不能仅比较计数。 |
| 来源端点 | 原 bundle 的 EEG 与 ValueGraph | 同 bundle 的结构关联自动派生；跨 artifact 身份必须用显式 SourceEndpointBridge，裸 ID 相同没有意义。桥本身不证明运行时相等。 |
| 写入阶段 | 原始行/EEG 边/native output | WriteAssociation 指向原 ValueOccurrence 或 StateAccess/实际 INVOKE completion；Host 写入不虚构 WorkTicket。 |
| 实际产出 | 原 Outcome/frontier/protocol result | OutcomeProduction 关联原 selector。COMPLETED 不等于整块写完，FAILED/CANCELLED 不抹掉已发生的部分产出。 |

source/provenance 祖先、当前物化的生产贡献、潜在失效写入是不同关系；不能把所有
祖先作 AND，也不能因同 ticket、同 host、重复节点或无记录就合并/排除。没有来源
清单、尚未重放、丢失关联、动态 alias、未知排序及外部写入均保留具体缺口。

## 接口冻结

ExecutionModel 新增默认空表 `source_inventories`、`source_bridges`、`writes`、
`produced`，非空时使用 schema v5；v1–v4 字段、tag 与字节保持，独立冻结 v4
golden。ProgramGraph 保持原身份，不增造 producer、allocation 或重复 state。

manifest 与 normalization index 为独立、严格、内容寻址的 JSON 工件。原始 artifact
的 hash 对应解压后的逻辑 JSONL 字节；压缩载体可另记 metadata。固定 recipe 只读取
本包 normalizer 的源码以核对版本，不读取/执行 recipe 提供的路径。任意用户 provider
代码不执行。缺少 bytes/未知 recipe/预算不足是 gap；已提供的格式、FK 或重放内容
矛盾是 issue。每次查询创建新快照，返回 detached 结果。

最小原生结果 profile 为 `scar.native.byte-prefix-write` v1，仅含 stage、requested_bytes、
written_bytes。它是待核对的原始记录，不是自动可信的原生事件。解释 uint8 连续一维
前缀还须同 artifact/allocation/起点及原 selector 子集；未知单位和布局不猜测。
wrapper 请求 8 字节、实际 syscall 请求 4 字节并成功返回 4、wrapper 随后抛异常，
不能写成 syscall 短写 8→4。原生阶段和外层 completion 始终分开。

公开 production 查询从读取与独立来源清单出发，分别返回 lineage、关联贡献、潜在
改写及未解析候选，包含遍历预算/截断；不接收调用者指定的“完整贡献列表”。所有
`source_runtime_verified`、`transformation_authorized` 保持 False。本门不签发 ready；
整个读取区间的稳定性与有效期留在 V 门。

## 自行验收节点

1. **P0 设计：** 来源全集、同 bundle 范围、显式桥、实际范围三项独立审查；记录原始
   评审和修正，不把 Proposed 当 Implemented。
2. **P1 结构：** strict records/schema、独立旧 golden、预算与 raw bytes 重放；已提供
   错误工件不能被“缺失”掩盖，未知 recipe 不执行。
3. **P2 关联：** 原端口/当前 state/实际 completion、来源 run、精确 selector/frontier；
   Work/Host/External 三类 writer 及部分失败；反例保留首轮失败。
4. **P3 查询：** 删除贡献或 Work 关联后来源候选仍在；缺 inventory 不空真；区分
   lineage/current/invalidator，不使用父调用猜测；预算不足保留未解决分支。
5. **P4 回归：** component gate、独立复审、旧 case/fixture 身份保留；冻结干净实现
   提交，运行一次完整回归，运行中不改源码/文档，不并发其他测试。
6. **P5 归档：** 精确命令、原始输出、源码指纹、退出码、失败修复、审查与验收报告、
   文件 manifest；核对受保护 checkout，提交、推送并核对远端 revision。

关闭 P 不代表 V/R3 或全程序 M0–M2 完成，也不构成 LeWM 优化或加速证据。

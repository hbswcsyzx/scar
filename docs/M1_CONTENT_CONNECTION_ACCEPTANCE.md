# R2.3-D 内容与消费者接口验收

**状态：声明接口组件及一次 clean 冻结全仓通过。** 基线 `6efbe27`。
设计见[计划](M1_CONTENT_CONNECTION_PLAN.md)、[API](M1_CONTENT_CONNECTION_API.md)。
完整 [R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)保留 P/V 全部义务。

## Implemented

五组连接已接原 ProgramGraph/ExecutionModel、外部图快照、validator、codec 和查询：

1. 原 ValueOccurrence 的 Data/Reference 指代；State/Binding/Protocol 从原图派生。
2. exact WorkTicket ↔ scoped EEG instance 的开放多对多对应。
3. 精确合同的 required output 或显式 endpoint/facet/protocol 要求。
4. 实际值/绑定端点/外部端点观察根，不伪造 work。
5. 原 Use/StateAccess/Q root 的内容读取、物化、selector、effect、当前状态与区间。

引用身份不等于内容版本；数据版本不依赖 storage 地址。Native 输入/输出沿原
P1 槽及本次 initial entry/Return/Raise 端口解析。EEG 没有参数槽序号时明确保留
exact-port gap，不用 role 字符串或同 host 调用补映射。

Execution schema v4 新增五表，v1–v3 字段/tag vocabulary/字节隔离，ProgramGraph
不变。ValueGraph/EvidenceGraph/SemanticGraph 共用严格、每查询 detached 快照。
公开 denotation/content_read/observation_root 查询返回原事实和逐项缺口。

## Verified

最终组件 **445 cases / 7 criteria / 9.995s PASS**，所有 **506** 登记文件前后不变。
指纹：`264df18c32498a03e637604de28a81912fd176b75eddeb79c7b818234bf22198`。
组件保存了实际 dirty 状态与基线 HEAD；该 HEAD 不能代替实现提交。

一次 clean 冻结实现 `f71740e1a6c5e71e4b3b1a71565d8dfb78cd0a73` 的 full：
**4,568 PASS**，0 failed/error/skipped、三条 warning；外部 wall
**477.6597996642813s**，pytest **475.53s**，最大 RSS **1,025,092 KiB**。
运行期间未改源码/文档、未并发启动其它测试、未重启。

全部旧 **4,427** case identities 和 **50** fixture 原样保留；新增141项：
records26、connections14、queries19、observations37、snapshots19、v4 codec25、
旧版本测试新增非法 v5 case1。旧493登记文件均仍在，482个未变、11个按本门扩展，
新增13个登记文件。当前54 fixture 前后一致。独占 basetemp 已在子进程结束后删除；
LeWM 与 SCAR 主工作区仍干净、HEAD 未变。完整清单见 `preservation.json`。

旧 v3 golden 来自不可变 `6efbe27` 的独立源码 archive，隔离 Python 路径并断言
codec 最大版本3，未由新编码器生成：117,878 bytes，SHA256
`8551cd9043cf0d13d20da40a41a7541b5781d4896fa8ed8ee473058006184b3f`。
旧 v1/v2 golden 和既有反例继续验收。普通 source catalog 的内部 helper 迁至
共享 snapshot，旧 once-hash 测试只迁 patch 目标，保留 case identity/断言。

这些是 IR 声明和验收成本，不是自动运行时恢复、LeWM profiling 或 A/B 性能。

## 原失败与审查修正

- 查询首轮 **5P/7F**：测试夹具把引用字段位置传成 full_overwrite。原输出、
  JUnit、退出码保留；修正后12P，再加入缺 pair/保守区间等反例14P；最终19项由
  组件/full 验收，不拿旧 focused hash 代表最终源码。
- connections 首轮 **11P/2F**：旧 pair 排斥断言不成立；native position2 实际是
  Raise 输出，错误预期为 actual mismatch，正确拒绝原因是 completion 不符。
  修正后14P。早期 smoke 构造/import 失败原样保留；未捕获的历史命令/哈希明确
  not-captured，不补造。原 records/Q/snapshot/codec focused 日志保留各自时点。
- 独立源审修正 resolver exact-type 错接、host 区间执行域漏检、URI 别名误拒。
- 对应表是开放多对多：缺 pair 是 gap，即便已有其它 pair 也不能推排斥；查询
  返回实际 matches，缺 join 不借同 host/parent 自动补足。
- 最终复审补 host exact-pair 的已知 PID 冲突；work 执行 process 从 Direct 线程
  或实际 queue ProcessRealm 派生，未知域不猜 enclosing caller。
- ResourceConsumer 的有效读取义务始终保守 WorkStart..WorkEnd，未解析的较窄
  native 声明另列，不能缩短稳定性要求。未知 Reference actual 也不能把 effect
  默认为 None。

组件历史441P、process 修正后445P、仅 EOF 规范化后的最终445P 分别保留；
没有相加成更多测试或覆盖旧报告。独立最终复审为有限 PASS_WITH_SCOPE，精确绑定
最终506文件；不把接口关联视为 runtime/native 证明。

## Rejected / Proposed / 尚未完成

Rejected：凭重复 node/module、相同对象/shape/storage、相同 host、partial pair
非成员性、retention 或顺序路径授 reuse/ready/free；凭协议 FactRef 缩读取区间。

Proposed：P 的 scoped source bridge、来源 inventory 对账、当前生产贡献/lineage/
invalidator 分类及实际部分 Produced；V 的整个读取区间有效性、visibility 与
每贡献 AND/OR；R3 的 load→consume→save/flush/close 全过程组合。
下一 P 草案仅在归档 design 下，未冻结 records、未实现。

**完整 M0–M2、全程序自动建图和 LeWM 自动化简仍未完成。** 本门没有新增
detector/backend/lowerer，没有新的 LeWM 加速比。原 producer/Use/state 唯一性、
读取的 source/runtime/native/applicability 与 transformation authority 继续分别核验。

证据：`artifacts/experiments/b1_call_operands/model_content/`。

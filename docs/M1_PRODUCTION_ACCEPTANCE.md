# R2.3-P 来源、写入与实际产出接口验收

**状态：声明接口组件及一次 clean 冻结全仓通过。**
基线 `5ab22f8`，实现 `c84fbfe53d76da2ea6ebaf7cec01b59b502eac17`。
见[实施计划](M1_PRODUCTION_PLAN.md)、[API](M1_PRODUCTION_API.md)及
[完整 R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)。本门不关闭完整 M0–M2。

## Implemented

1. 独立 manifest/index 封存给定原始流，严格核对物理 LF 行、hash/size/schema；
   复用既有 normalizer 重放，比较整个 bundle 与 coverage，而非只核计数。
2. 同 bundle 的 EEG/ValueGraph 关系自动派生；独立 artifact 通过显式 scoped bridge
   关联。ObjectRef 支持 ValueGraph binding 和 EvidenceGraph object registry。
3. Work、直接 Host、External 三类写入接原 value/state/effect/实际 INVOKE completion；
   直接 host 不伪造 WorkTicket。源 PRODUCES 不等于物理写入。
4. OutcomeProduction 引用原 Outcome/frontier/protocol result 与原 selector；固定
   BytePrefixWrite profile 解释严格字节前缀，保留 FAILED/CANCELLED 的部分产出。
5. `ExecutionIndex.production/write/outcome_production` 只读查询：来源候选独立于
   提交的 Work/Write/Produced，分别给出 lineage、当前生产关联、潜在 invalidator
   和未决关系。删除关联不缩候选全集，未知/截断不作空集满足。

Execution schema v5 新增四个默认空表；v1–v4 字段、tag vocabulary 和字节兼容。
ProgramGraph 的 producer/Use/state 保持唯一。每次查询重新核验外部快照，URI 不打开，
调用者 provider 不执行。相同 manifest/index 在单次查询内复用重放；不同清单仍各受
独立来源解析预算约束，图遍历预算不是全模型解析总量上界。

## Observed / Inferred 的界线

真实 OS 小程序向独占临时文件 pwrite `abcd`：原生请求 **4** 字节、返回 **4**，
文件从 `........` 变为 `abcd....`；随后外层抛异常。JUnit 保存期望总输出8、原生请求4、
返回4、实际文件 hex、host RAISE/native COMPLETED。**这不是 syscall 短写8→4。**

该观测的计数/完成事实接入通用声明夹具，用于验证它们可以分开表达；它不证明
真实文件端点已自动恢复成内存 Region，也不证明原生 writer/物化身份已自动对应。
normalizer 的结果观察、输入捕获与来源推导分别保留原证据等级；没有由返回 snapshot
推断实际写入，也没有由 COMPLETED 推断 whole/ready/quiescent。

## Verified

组件 **477 cases / 8 criteria / 11.647s PASS**，**521** 登记源码前后不变。
指纹：`66e35626809a14cde497346a97d56e94697958d4895bd253f48a1975e9662c10`。
组件绑定实际 dirty 状态与基线 HEAD，不能用该 HEAD 替代实现 revision。

一次 clean 冻结实现 `c84fbfe` 的 full：**4,713 PASS**，0 failed/error/skipped，
四条 warning；外部 wall **477.89904445502907s**，pytest **475.81s**，
最大 RSS **1,028,872 KiB**。运行中未改源码/文档、未并发其它测试、未重启。
这些耗时是验收成本，不是 workload benchmark 或加速比。

旧 **4,568** case identities 全部保留，新增145项：inventory28、produced41、
production codec14、query26、records6、source connections29、旧 work codec 新增非法v6项1。
旧 **54** fixture 原样保留；当前 **59** fixture 前后相同。旧506登记文件无删除，
493原样、13按接口扩展，新增15个登记文件。独占 basetemp 在子进程退出后删除；
LeWM 和 SCAR 主工作区 HEAD/干净状态未变。

独立 v4 golden 从不可变 `5ab22f8` archive 的旧 codec/夹具生成，隔离 import 路径，
断言旧 codec 最大版本4；**29,951 bytes**，SHA256
`55ed3e05850fbcb30c44c1894feb81062fc8aaba6976b8d4b0048d44da4735af`。
旧 v1/v2/v3 golden 继续通过。重复源码 tar/展开目录在记录 SHA/size 后删除，释放约
17.1 MB 逻辑文件；原命令、失败、import hashes、golden/proof 保留，可从原 Git 重建。

## 原失败与独立审查

- records 首轮5P/1F：63字符 digest 的错误类型预期不符；保留原输出，修正测试。
- codec 的 archive wrapper 自拷贝、导入/fixture 及 closed Identifier 处理失败逐次保存。
  新 EvidenceEndpoint 的 generic Identifier 最终只接固定白名单类型，并核 exact kind；
  所有 typed/string 端点 roundtrip、错类型/未知tag拒绝通过。最终 focused150P。
- produced 首轮33P/1F：坏 HostWrite FK 继续查 activation 触发 KeyError，已修；后续
  38P/1F 是 bool literal 被测试错标为 int。最终41项，原失败未覆盖。
- query 首轮20P/5F：夹具将 OccurrencePoint 传给要求 EvidencePoint 的 Unresolved；
  修正后通过，最终26项另核预算与 ESCAPES 保留。
- root source14P、补充后18P为历史记录；一次 wrapper-copy 未激活 conda 导致 shell
  exit127，未启动 pytest，只有事后说明且无预先 hash/JUnit，不补造。最终29项由
  组件/full 验证，不沿用旧 focused hash 代表最终源码。
- 两份交叉源审均 PASS_WITH_SCOPE：修复已解析空 manifest 的 absent stream 误作 pending、
  raw schema 漏检、known wrong family 被 missing catalog 掩盖、EEG ObjectRef 未解析、
  非整数 PID 的 scope 缺口、ExternalWorkSource consumer run 漏检。另收紧当前贡献到
  需求的原物化/版本/selector，对 lineage fanout 和分组关联计费，保留 escape 路由。

## Rejected / Proposed / 尚未完成

Rejected：裸 ID 跨 artifact 合并；结果观察直接当物理写；完成即整块产出；失败抹除
部分写入；来源全集从贡献行反推；祖先全作 AND；同 host/ticket 自动合并；缺源或预算
耗尽作空真；以协议 FactRef 或 bridge 声明直接授 ready/变换。

Proposed：下一 V 门接每贡献 AND/OR、整个读取区间稳定性和 Host/Queue/Endpoint
可见域。只读草案指出 host INVOKE 读取仍受 work-effect membership 限制，需复用一个
准确原 effect resolver，无需伪造 WorkTicket；本门没有提前实现或验收 V。

**完整 native writer/capture closure、V/R3、全程序 M0–M2、自动 LeWM 建模与化简仍未完成。**
本门没有增加 detector/backend/lowerer，没有运行新的 LeWM profiling、CEM/policy/episode
正确性或 clean A/B，也没有新的 LeWM 加速比。source_runtime_verified、readiness_verified、
transformation_authorized 仍为 False。

证据：`artifacts/experiments/b1_call_operands/model_production/`，包含只读 archive checker。

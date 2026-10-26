# 资源工作到完成／等待：有界交接

本次只读设计，未改生产、未运行目标或 gate。结论：现存 LeWM 证据可定位一个真实 GPU work 及 provider 活动结束点；尚不能无条件升级为成功完成、事件等待或某个 value ready。不能以 host return、时间邻近、相同 stream 数字补这三种关系。

后续固定 primary／现IR合同补核见 [COMPLETION_CONTRACT.md](COMPLETION_CONTRACT.md)：有效end可支持严格单activity的物理结束和独立quiescence；现类型足够，结果成功／child闭包／ready仍分开。下述初次取证范围和未实施状态保留。

## 现有实体和 producer

|关系|复用规范实体／现有位置|本档已取得与未取得|
|---|---|---|
|工作身份、提交来源、executor|`WorkSubmission`、`ExternalWorkSource`／`WithinOperation`、`WorkEvidenceBinding`（`scar/ir/execution/work.py`、`content.py`）|`scar/trace/native_import.py:337–428` 已导入原 Kineto `OperationInstance`、活动区间及唯一 runtime correlation 的 `SUBMITS_WORK`；这是 provider 关联，不是 canonical work/run 或先后资格。|
|完成、静止、保留|`ResourceOutcome`、`WorkQuiescence`、`WorkRetention`；`WorkStart/WorkEnd`（`order.py`）|已有类型与 validator；没有本 LeWM GPU activity→这些记录的受审 producer。`WorkEnd` 只是 ticket 的 order endpoint，构造它不证明观测到完成。|
|队列／事件等待|`QueuePrefix`、`EventRecord`、`QueueWait`、`EventSignal`（`work.py`、`order.py`）|必须保准确队列 lifetime、event generation、captured prefix、wait selection；当前所抽样记录没有这些字段。|
|值产出／ready|`WorkWrite`、`ProductionCoverage`、原 `MaterializationRef` 和内容／visibility 关系|活动完成不提供写入 selector、ValueGraph Version、完整贡献或 consumer read interval；不得造 ready 或 COMPLETE coverage。|

规范合同见 `docs/M1_RESOURCE_WORK_INTERFACES.md`、`M1_RESOURCE_READY_CONTRACT.md`。`content_validation.py` 仍明确报 work/run correspondence 未证；普通结构校验通过不是 native 协议证明。无需新增 ResourceWork 图或 backend。

## 实际样本与来源边界

主树根记为 `M=/home/zyf/AAA/scar-worktrees/structured-program-model`。本次取证来自既存派生 archive：
`M/artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions/evidence/instances/000064.jsonl.gz`。
stored **1,030,923 B**、SHA256 **b4788b880c114061abefe9df355bbba491f6a19193b7155f4d0d2ff29511a976** 与原 manifest 一致；只解码前 **4,000,000 B**，不声称验证此 chunk decoded EOF/SHA 或全片唯一性。

* **kernel**：archive ordinal **311808**；instance 后缀 `:kineto:387826`；原定位 **`sha256:256f688f0c767a6302fccaec088fab9b1232ca429c24de4254a984329c3be875#/traceEvents/387826`**。provider `Kineto`，correlation **4735**，External id **21511**，device **0**／context **1**／stream **7**；process **369749**，actor **`kineto-device-lane:0:7`**（不是 Linux TID）；保存区间 **1872204808725114–1872204808726842 ns**。
* **copy**：同片 ordinal **311720**，原 `#/traceEvents/387651`，correlation **4428**、External id **20932**，device0/context1/stream7，bytes **8**，区间 **1872204473122273–1872204473122625 ns**。这是 copy 活动，不证明哪个 logical value 被复制。

原 Kineto URI 为 `M/artifacts/experiments/first_stage_lewm_physical_20261023/trace/kineto.369749.72816598bfa183a810428fe30a7873ff.json`，原 decoded **215,705,815 B**。上述 SHA／URI／process membership 载于 `first_stage_native_protocol_bridge_attempt03_20261023/native-coordinates.json`（SHA **4d266b9ea62ed0d4c25cb5606dae31dea5aeab453405f79608ab5c038f012a25**），Run **`capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0`**。这里引用保存的 membership，不从 JSON 恢复 genuine owner；本次没有重新校验大原 Kineto。

provider 合同固定 Torch **cf30153c4c131c8164ee7798e5022d810682e2cb**／Kineto **094d3c1d072362d0a919a77299459eee94f97931**。已有 primary 在 `first_stage_native_scope_20261020/sources/manifest.json`：`output_json.cpp` SHA **7301286695d55122f45bd1c2150df89cccd02104182a2f6580b055dccc354db2**，L772–865 将 `timestamp()/duration()` 写为 complete event，并把负 duration 截为0；External id 来自 linked activity。**这份已审源码只足够解释保存区间，未闭合底层 CUPTI 有效 end／错误结果→成功完成合同。** `CuptiActivityProfiler.cpp` L435–513 还表明 event wait 受配置和 seen-stream 过滤，不能因没有 wait 行证明没有 wait。

读取账：2个派生 chunk；另一个 `000075` 完整 stored46,205 B+decoded1,089,154 B，仅见 allocator receipt，未用于 completion。合计 **6,166,282 B**（stored+请求 decoded），≤8MB；000064 前缀完整解析3648行，尾部残行未用。原大 Kineto／ETO／39796 dispatch／OS读取均0；原始 provider chunk读取0。原 locator是派生记录保存的来源指针，不冒称本次 raw 重验。

## 最小下一门与资格

**先接 work→准确 provider endpoint，不提前发成功／ready。** 最少2个实现文件即可：新薄 producer `scar/trace/native_work_bridge.py`，以及独立 checker `scar/ir/execution/native_work_protocol.py`；复用现有 binder、partition reader 和所有现有 IR。入口消费 genuine coordinates、exact EEG artifact／instance、上述原定位和固定 provider source receipt；每 work 独立 `WorkTicketID`，以 `ExternalWorkSource(EvidencePoint)` 表示，未知 executor／调度／效果／retention 保 `Unresolved`。已观测活动区间沿原 EEG 保留，`WorkEvidenceBinding` 精确绑定；不为凑关系创建未知 queue lifetime 或 host operation。

一次离线实际门仅消费这一个 LeWM work 的有界保存证据，不运行 target：先严格读 manifest 与所需 exact records，核同 Run/process、provider版本、原ordinal/locator、GPU lane、有效区间和唯一 source binding；独立 checker 对交换另一个 instance 的唯一负例拒绝。若必须重读215MB原 Kineto才能取得 genuine authority，应先报明确读预算，不伪装成≤8MB门或从派生 JSON造 owner。成功只授原活动绑定；无足够 primary 合同则 completion 判 **BLOCKED**。

要授 `ResourceOutcome.COMPLETED`，还需固定 CUPTI activity end有效性／错误语义及 exact activity→ticket 证明；event wait另需保存 context+event generation/record correlation、source stream/prefix、wait选择及协议结果，不能用 runtime API 名称或返回区间代替。**这些是本次未证／未测，不一概断言旧 trace 从未保存。** 要授 value ready，更需原 output/state effect→Version/Materialization、写入区域与完整贡献、consumer read interval、visibility、allocation/queue lifetime。后一组不是仅加 completion adapter 能解决；旧 collector 执行源码和共享 issuer 的历史条件也不因此消失。

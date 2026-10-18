# Proposed — P 上游 source inventory 的最小可核验接口

基线：父代理指定 clean `5ab22f8`。**Proposed／未实现／API 建议，非 runtime 认证。** 本轮只读源码和既有设计，未修改产品/docs/tests，未运行 pytest、probe、full、GPU、LeWM、采集或安装；没有新建 producer/state 图。

## 1. 现有输入究竟是什么

### 1.1 normalize 的两个实际产物

`scar/cli.py:_normalize_v2` 写一个完整 `IRBundle.to_dict()` JSON，另写以下 coverage JSON；目前没有实现跨文件的 canonical NormalizationIndex。

```text
schema = "scar.trace.v2.coverage", schema_version = 1
source, namespace, source_sha256
raw_records, accounted_records
status_counts = {normalized, ambiguous, opaque, unmatched, invalid}
kind_counts, records, graph_counts, scope, valid

records[i] 基础字段：
  line, raw_reference, sha256, kind, status, normalized, issues
  另可有 legacy_index/control/aggregate 等按原 raw kind 派生的字段
normalized 项：{kind, id}，并不列出 finish()/edge() 生成的全部 EEG 边
```

来源：`normalize_v2.py:106–147,315–377,413–496`。`raw_records` 等于送入 normalizer 的**物理行数**，包括 invalid/blank 行；`valid` 只是 bundle validator 结果，不证明每行是有效事件。`raw_reference` 是 source label 加 `#L...`，不是自动可信的文件地址。

IRBundle schema `scar.ir.v2.bundle` 当前版本2，固定含 semantic/evidence/values/correspondence/optimization/source_semantics/validation。现成 `bundle_from_json`、`bundle_from_dict` 严格解码并跨图核验 observation→version/materialization、producer→EEG instance 等。**同一个准确 bundle 可提供其三个 component 的明确 artifact scope 关联**，不必给每条 normalize 端点手填一遍 source→VG bridge；独立 EEG 没有该 bundle 来源时仍不能猜 VG。

### 1.2 现成 run 和 collector metadata

- `scar trace` 的 `run.json` 实际仅 `{command, returncode, wall_s}`；没有 raw/EEG artifact 清单、collector 完整性或规范 run/process incarnation。它能作为辅助 run metadata，不能当作已有 closed capture manifest。
- TraceSession 的 `metadata.<pid>.json` 含 python/platform/pid/started_ns，可能有 torch/cuda/gpu 等信息；close 添加 ended_ns/event_count/entity_count/exit_code，fork 另有 forked_from_pid。它没有全线程/native/external 写入覆盖证明，也没有完整输出文件清单。
- `TraceManifest` 是 `read_runtime_trace` 对选定流生成的 summary，字段为 logical_path/raw_sha256/raw_bytes/line_count/record_count/event_counts/supported_event_count/ignored_event_count。raw hash/bytes 是**解压后的逻辑流**；record_count 跳过 blank，line_count 不跳。不能与 normalize.raw_records 不加区别地比对。
- `CallTraceFile(path,family,process_id,raw_sha256,raw_bytes,lines)` 及 operand metadata.base_manifest 精确绑定 codes/events/meta 三文件；现成 operand reader 会重读对账并保留 drops/errors/io_failed。它覆盖特定 Python frame/operand collector，不是全部物理 writer。recorded `.lines` 与 binary read line count 需按 profile 核对；不得把 newline 数和末行未换行的物理行数混为一谈。

## 2. 最小 artifact 方案：一个 capture 清单，一个 normalization 索引

无需通用 manifest 框架或第二份 writer list。只增两个闭合、版本化 JSON artifact profile；两者的输入都是明确提供的 bytes/catalog，URI 只是诊断，不自动打开。

### 2.1 CaptureManifest（上游 raw 清单）

建议精确结构：

```text
schema: "scar.capture-source-manifest"
schema_version: exact int 1
run_metadata: tuple[ProviderArtifact, ...]
streams: tuple[{
  key: nonempty str,
  raw: ProviderArtifact,
  profile: nonempty registered-parser key,
  scope: ProviderRunScope | MissingEvidence,
  metadata: tuple[ProviderArtifact, ...]
}, ...]
```

- key 在 manifest 内唯一，raw descriptors 指逻辑 JSONL bytes；若源保留 gzip，容器可作为 metadata/transport，明确解压映射后才比较 raw hash/size，不混用 compressed SHA。
- profile 选择固定已知解析规则，不是可执行模块路径；未知 profile 的 bytes 可保留，但其输入语义/覆盖为 unresolved，不执行 artifact 里的代码。
- scope 复用 ProviderRunScope；它是 provider 坐标，**不是** ExecutionRun/ProcessInstanceID 的证明。多进程共享文件若尚不能准确给 scope，显式 MissingEvidence；不要用一个 pid 假装覆盖全部子进程。
- run_metadata/metadata 都是准确 bytes 引用。已提供的 run.json/metadata 文件按其已知 profile 解析指定字段；不能把不存在的 drop/alias/window 字段补成0/false。
- manifest 在 recorder 产物封存后由独立包装步骤写出，输入是实际 recorder raw/metadata 文件集合；不接受从 ExecutionModel.submissions、ContentRead 或 contribution 列表反推 streams。
- 现 run.json 不能机械恢复这个清单；**需要实现这个小包装步骤**，或外部提供同 schema 声明并保留 `capture_manifest_origin_unverified`。对旧目录仅扫描 glob 不能证明缺席的子进程/文件从未存在。

### 2.2 NormalizationIndex（固定格式投影的索引）

```text
schema: "scar.normalization-index"
schema_version: exact int 1
manifest: ProviderArtifact                 # 上面 CaptureManifest
entries: tuple[{
  stream: nonempty str,                     # 引 manifest.streams[].key
  projection:
    {kind: "normalized",
     recipe: {profile: "SCAR_NORMALIZE_V2", version: exact int 1,
              implementation: SourceVersion,
              source_label: str, namespace: nonempty str},
     bundle: ProviderArtifact,
     coverage: ProviderArtifact}
    | {kind: "unresolved", reason: nonempty str}
}, ...]
```

- 每个 manifest stream **恰有一项**，不得重复/省略/多列。unsupported profile 或未投影输入也有显式 unresolved entry，不能从清单消失。
- normalizer implementation 是现成 SourceVersion；仅支持已登记的版本/实现指纹，不能导入调用者提供的旧代码。实现版本不支持时是 projection replay gap，不能谎称已重放或把合法历史数据误判物理矛盾。
- source_label/namespace 必须保存，因为 normalizer 用它们生成 raw_reference 和 typed ID。它们只用于重放同一格式规则，不给 URI 或 native identity 权限。
- **不列 caller 自选 EEG/VG/SG tuple 或 writer IDs。** 解码原 bundle 后，用现有 canonical external_bytes/external_artifact 机械派生三个 component descriptors；它们是原来源的 scope。若另提供同 component catalog，必须核其准确 hash/schema/size。
- manifest→raw/run metadata；index→manifest/bundle/coverage，方向单向。原 artifacts 不反向引用 index；避免 hash 环。

### 2.3 execution/query 的唯一锚点

P 接口需要一个准确的 `ExecutionRunID → NormalizationIndex artifact` 声明关联，或 query 明确接收该 index artifact 和 run binding；引用现有 RunID/FactSource，不复制 run state。**不接收 arbitrary required_writer tuple。** 缺 inventory anchor 时返回 `source_inventory_unbound`，不能从当前已给工作列表补一个“全部来源”。

源 bytes catalog 可复用现 ProviderArtifact 身份约束：exact dict[str, bytes]，key为SHA；缺 key→gap，present None/wrong bytes type/已给 hash-size-schema 不符→issue。字节输入与现 three-family ExternalSnapshots 作用分开：index/manifest/bundle 是固定 source artifact parser，component graphs 继续复用现 codec/snapshots；不新增任意类型 registry/URI loader。

## 3. 机器核验顺序：重放原 bytes，不能仅信行计数

1. 严格 decode index 和 manifest：UTF-8、重复键拒绝、NaN/Infinity 拒绝、exact non-bool ints、封闭字段集/版本/variant、预算检查；核实际 bytes SHA/size/schema。输入对象不持久缓存；同 query 仅用已核 detached JSON/graph。
2. 从 manifest 枚举 expected stream keys，index entries 与其准确对账。删 entry 是已知清单不守恒 issue；raw/bundle/metadata 未提供是准确缺 artifact gap，不把缺条目或未解析 stream 当无写入。
3. 选 fixed recipe。现 `normalize_records` 会重新 JSON dump 数据，**不能用于核原 physical bytes**；现 `normalize_trace` 路径 API 也没有所需外部预算。最小新增方式是给现 `_Normalizer.raw/finish` 加一个受预算的 bytes/stream adapter，不复制其规则、不导入目标。
4. 按 binary `readline()` 或等价的仅 LF 切分遍历；不要用 `bytes.splitlines()`（会把其它控制字符当新物理行）。保留原始空白、CR、blank/invalid 行和末行未换行。最后 LF 不生成幽灵空行。每行 SHA 和全流 SHA 基于原 bytes；UTF-8/JSON 错误进入 normalizer 原 invalid ledger，不静默跳过。
5. 用 recipe.source_label/namespace 重放 `_Normalizer.raw(record,line,raw,error)`/finish。原 JSON parsing helper可复用；没有运行 workload。源原始损坏导致的 invalid ledger是 capture/source gap，可保留其它已知事实，不把它伪造成无事件。
6. 用现 bundle_from_json strict decode原 bundle，复算 validation；忽略文件自报 valid 的授权含义。比较**重放完整 bundle 和 coverage 的 canonical JSON 内容/hash**；raw_source_sha、物理行逐项 hash、status/kind/graph counts 也要一致。因为 coverage.normalized 不列全部 edge，仅检查其中引用存在是不充分的。
7. 对非 canonical 布局的 JSON，区分 ProviderArtifact 对实际存储 bytes 的 hash 与 canonical 内容 hash：前者核文件身份；后者比较相同结构的投影，不能要求 JSON空格必须一样。追加/删改 EEG edge但不改 raw 重放结果，必须被 projection mismatch 抓住。
8. 从已核 bundle 的原 edge/observation/provenance/Mat.producer 派生候选 inventory，保留 bundle artifact与component scope。再查现 D 的多对多来源 pair及 work/effect；missing pair是 gap，不因已配父A就排斥子B，也不靠 parent 补配。
9. 读取并对账现 collector metadata 的已知 counts、attempts/drops/errors/io_failed/open_invocations及 start/end 状态。仅在特定 profile 确认计数含义一致时比较；缺字段是 unknown，exit_code=0/ended_ns不是 native writer coverage。

### 预算边界

重用 RuntimeTraceBudget 的 uncompressed bytes／lines／line bytes 限额概念及现 strict JSON helpers。另需小的 max_artifacts/normalized_rows或总投影输出预算；`_Normalizer` 目前没有 public budget，不能宣称直接调用已是有界读取。超预算使投影/closure unresolved或按入口fail-closed返回，不把已读前缀当整段stream。所有错误/未观察行仍由已核 source root 留下待核义务。

## 4. 三层结论必须分开

| 可核结论 | 机械依据 | 不可替代的事实 |
| --- | --- | --- |
| 给定字节流已记账 | 原流 hash、每物理行、状态及重放完全一致 | 捕获器是否观察了所有实际行为。 |
| 此 index 没有漏掉 manifest 中的 source/normalized 事实 | manifest stream集合→index→原 bundle组件/边/逐行投影对账 | manifest 是否真实列出整个运行的全部collector/窗口/进程，或其 provenance/authenticity。 |
| 目标物化全部必要 writer/alias 都被覆盖 | 还需 target+selector+run/window scoped原生捕获规则、alias/外部写/opaque/drop边界与可解析来源 | 当前没有通用 provider 可以闭合这项；不能由上述两层或 COMPLETE+FactRef推得。 |

当前 TraceSession/normalizer 没有全写 inventory，normalized.outputs PRODUCES 可能只是返回原对象，inputs READ仍INFERRED；call/operand metadata只闭自身协议。对于跨 NumPy/FFI/opaque native、未捕获 thread/process、graph break、截窗、unknown alias、未解析 native写 selector，保留逐域 gap。若无法证明某缺口不影响目标 selector，不得因“其它已知贡献覆盖全 bytes”而丢掉潜在 invalidator。

即使格式投影完全一致，也不证明真实 runtime/source 配对。若调用者同时替换 raw、manifest、index 及根引用，那是另一份声明的 scope；没有上游可信捕获根时不能认证它等于原真实执行。不要暗加用户可写 verified/complete 权限位。

## 5. 删除为何不会缩 universe

- 删 contribution：源 bundle 原写边仍在，派生待对账项不变。
- 再删 Work：源边仍在，exact source→ticket join缺失，不能空 AND 成立。
- 从提供 catalog 漏掉 EEG：index仍绑定 bundle；缺工件/对应仍可见。bundle存在时可回查其组件；不能只扫描当前catalog中剩余图。
- 从 index 漏 stream/改其 bundle：与独立 manifest不等或重放不符，被抓住。
- 整个上游 inventory 未给：gap，不从 execution/contribution tuple新建替代清单。真实 capture closure仍按第4节保留，不夸称可防任意重造全部原始证据。

## 6. 建议最小验收（未执行）

1. raw非canonical空白/CRLF/末行无LF重放相同；空行/非法JSON保留invalid ledger；VT/FF等不额外拆物理行。
2. 修改一行 bytes但保持旧 SHA，或改 coverage counts/normalized refs/graph edge：分别artifact mismatch／projection mismatch；不能只复核counts通过。
3. raw/bundle/coverage都在，提供的独立EEG多一边或少一边：与bundle-derived component identity不符；去掉EEG catalog不删源义务。
4. manifest两streams，index删其中一个、重复一个、补无关第三个：清单对账issue；对应raw未提供则gap而不是zero writers。
5. 同bundle EEG/VG scoped bridge可派生；两个VG都含裸mat:x不因此跨bundle合并。
6. 移除work/contribution、保留raw/index，writer候选数/来源待核项不变；缺pair仍gap。给其它pair不升级为排斥。
7. metadata报告drop/io_failed/open invocation/unfinished或scope为unknown：给定文件格式账可闭，capture write closure不能闭；metadata缺字段不补零。
8. 只有run.json或某目录文件glob，没有独立source清单：source inventory scope未绑定；仍可报告局部候选，不能全运行empty universe。
9. 库输出只是view/原tensor、FAILED short write、无work Host/Q：原投影可成立，但分别不变新physical writer、不变whole Produced、不造ticket；属于后续生产语义而非inventory自证。
10. budget在中段耗尽、损坏gzip、presentNone或坏schema/额外字段：保留准确失败/缺口，不把前缀或错误源降为空集合。

## 7. 可实施切分与尚无provider的部分

第一小门只实施两个source artifact profile、fixed bytes replay与component/inventory只读查询，验收format-projection守恒及删除反例。再接现D source pairs/effects/selector与实际Produced。全写捕获/alias/external窗口闭合仍缺可验证provider；不能因这个结构小门完成就关闭完整P/V、R3或M0–M2。以上是可供root冻结的最小字段建议，本轮没有冻结或实现它们。

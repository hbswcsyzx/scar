建议先实现一个只读、按需的 source/native 组合查询 adapter。它发布“同 collector 对象身份”和“retained source context”两类明确关联，保留原端点与 frontier；不生成全局 ExecutionModel，也不把 ancestry 升为 direct call。此文待 root 审阅，尚未改生产。

1. **身份合同已能机械核验，但 source 端不是另一个 ObjectInstance 表。**

source/SBA 当前输出 `ReferenceOccurrence`、`ReferenceIdentityGroup`，端点包含 `CallRecordAnchor`、`InvocationKey`、ref、可选 core ValueID/UseID。environment 输出 `observed_reference` 及 owner basis。v2 `ObjectInstance` 由 `dispatch_import.py:243–254` 在独立 `dispatch-reference:<qualified scope>` 中创建；native V2 原样投影该记录，并以 `ObjectRef(projected ValueGraph artifact, original ObjectID)` 声明 B。

共享 issuer 有实际代码链：`sitecustomize.py:7–15` 把同一 `_scar_recorder` 给 operand observer 和 execution evidence；`execution_evidence.py:326–341` 再给 dispatch observer；operand `_reference` (`call_operands.py:551–559`) 与 dispatch `observe_dispatch` (`call_edges.py:163`) 都调用这个 recorder 的 `_reference`。该表用真实 weakref `is` 校验存活对象；新对象/地址重用分配新 epoch，非 weakrefable 或预算失败使用 event-local snapshot。不能只按 `weak:pid:epoch` 字符串匹配两个任意归档。

本次小 metadata 核对通过：source operand metadata 的完整 `base_manifest` = source `frame_files` = source report `trace_files`；这些原路径/SHA/bytes 与同 Run coordinate membership 一致，operand/dispatch 声明与 coordinates 保存声明一致；native manifest→dispatch 元数据的准确 hash/bytes、nonce、owner PID/ident 链一致。PID 369749，原 Run `capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0`。这些检查证明保存的数据文件及其声明一致，**不证明执行当时实际加载了本次读取的 SCAR collector 源码**。

补查原 capture 后，历史锚点只有 `scar-revision.txt` 的 HEAD label `49ea6f032c6a95c39801ccc0d188a2ae179ef14a`，以及 `run.sh` 中启动前记录该 label、指定工作树 PYTHONPATH 的脚本。脚本只记录 LeWM 的前后 status；未记录 SCAR 工作树 clean 状态、实际 imported module 文件/SHA 或这五个文件的执行期 frozen source receipt。原 archive 的 261 个成员无 `.py/.pyc`，coordinate membership 无 SCAR collector source artifact；call/operand/dispatch metadata 只绑定数据文件与协议 label。`execution-evidence.registration.source_sha256` 是 Torch ETO C++ 源码收据，不能证明 SCAR 的 `sitecustomize` / `execution_evidence` / `call_edges` / `call_operands` 实现。没有用 Git 操作补造历史证据。

因此必须显式保留 assumption：**原 369749 capture 使用了所声明的共享 CallEdgeRecorder weakref+epoch collector 合同；其执行当时精确 SCAR 源码未由已查原 metadata 证明。** 当前源码只能解释该合同及 adapter 如何条件核验，不能把当前 SHA、相同版本 label 或分析阶段 freeze 当成历史执行 receipt。旧文件也未序列化共享 issuer UUID。在此 assumption 关闭前，同 weak 对象身份仍是 conditional；首 patch 不做此身份连接，只查询保存的 retained ancestry。

最小身份判据必须同时满足：两边原输入 receipts/Run/process/issuer 链；source 原 occurrence 的准确 anchor/ref；native 原 held slot 的 phase/path/marker ordinal；原 `OBJECT_REFERENCE_ASSOCIATION` claim 和原 ObjectInstance；V2 exact native path/formal、每 Tensor 的 denotation；原 projection receipt 的 object locator/ordinal/记录一致。复用 `BundlePartitions.selected_records` 按原 ordinal 核选中对象与 ETO 实例，不扫全表、不相信 receipt 中自述的 verification boolean。两个投影 artifact 不同仍分别保留其 ObjectRef，不因原 ObjectID 文本相同合并 artifact。`snapshot:`、`operand-snapshot:`、`environment-snapshot:` 不跨事件；environment owner/cell token 也不是 base weak token。

该关联只说“这些准确 observation 引用了同一 Python 对象”。它不证明此 source Value 是本次 native 参数来源、不证明 copy/alias/storage lifetime/content/version/world/ready，也不合并同值或不同 occurrence。native-only Tensor 的 B 继续 `Unresolved`，不能借已有 ObjectID。

2. **已有 ancestry 可组成查询；direct source CALL、源 return 和异步完成仍无证据。**

`bind_dispatch_sources` 已发布 `RETAINED_ANCESTOR_CONTEXT`、`direct_callsite_established=False`，含原 source invocation/binding references、可选 body namespace/activation、marker instance、phase、原 ETO marker fact 和 source frontiers。V2 又核 exact nonce/sequence/owner、span 的唯一匹配 FunctionSchema child、output marker parent/thread，并将实际 invoke/normal Return 各绑定同一原 ETO instance；来源分别为原 `#/nodes/<ordinal>`、`#/nodes/<ordinal>/outputs`。可机械组成：

```text
原 SourceDefinition / InvocationKey / 可选 body activation
  -- RETAINED_SOURCE_CONTEXT（原 marker-source association） --> 原 dispatch span/output
  -- 原 ETO parent/child 与 ordered boxed ports --> native 实际 invoke / normal Return
```

这条链中第一段仍是 retained ancestry。observer 的 dispatch callback 已处于外层 RecordFunction 内，可能经过未跟踪 wrapper/frame 或模式引入的 boxing；不能从 inner schema child 推导 source canonical CALL 的直接 callee，也不能把 native normal Return 当源函数 RETURN 或设备完成。异常/缺 marker/缺 schema 等原 frontier 不造 activation。通用判据使用固定 provider ABI、schema 和端点事实，不写 op 名或项目规则。

3. **端点及局部关系复用现有 IR；缺的是薄的组合结果类型和有界导航。**

复用 `SourceDefinitionReference` / `SourceArtifactLocator` 的原 namespace，`ReferenceOccurrence` / `CallRecordAnchor` / `InvocationKey`，`ProviderArtifact` / `ProviderFactReference`，`ObjectRef`，`NativeInputRef` / `NativeOutputRef` 和 `OccurrenceEvidenceBinding`。`ElementReference.file_index`、chunk number、裸 ValueID 仅作导航，不能单独成为跨片身份。source occurrence 的 core ID 必须由该 InvocationKey 的原 binding 取回准确 body artifact/representation/namespace；source-only 定义保持无 canonical body。

现 `EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION` 只适合原 object→provider-reference marker 事实；`PROVIDER_SCOPE_ASSOCIATION` 是原 provider activity/scope 合同；`CallActivation` 需要真实 canonical caller/callee。三者都不能用于替代 retained Python ancestry。`SourceEndpointBridge` 的输入也是已存在 EEG endpoint，不接受原 source ReferenceOccurrence。最小新增应限于 adapter 的严格查询结果枚举/qualified wrapper，无需新增 producer/state/content 权威或改 core graph schema。

拟议公共入口（名称待 root 审阅）：

```python
SourceNativeComposition.open(
    *, composition, source_report: ProviderArtifact,
    source_operand_manifest: ProviderArtifact, dispatch_source_report: ProviderArtifact,
    native_batch_report: ProviderArtifact, original_native_manifest: ProviderArtifact,
    scope_revision: str, budgets: CompositionQueryBudget,
) -> SourceNativeComposition

view.native_context(sequence: int) -> NativeContextResult
view.reference_ports(source_occurrence: ProviderFactReference) -> ReferencePortResult
```

`NativeContextResult`：原 sequence + classification；原 source association fact / InvocationKey / SourceDefinitionReference / 可选 body namespace 与 activation；原 span/output facts；限定到原 execution artifact 的 invoke/Return ID 及其 binding facts；typed relation `RETAINED_SOURCE_CONTEXT`；原 frontiers。`ReferencePortResult`：准确 source occurrence fact+解码 ReferenceOccurrence，原 native execution artifact/ValueOccurrence ID+denotation+basis、原 ObjectRef及 projection→archive locator，typed relation `SAME_COLLECTOR_OBJECT_IDENTITY`，issuer evidence facts，未匹配原因与 budget cursor。结果仅引用原事实，不能仅据 caller 输入的 ref 或 trust flag 发布关联。

`scope_revision` 仅引用并核对已有验收范围；native report 另以准确 root receipt 保留。当前 `MEMBERSHIP_ONLY_V2` 不实现 semantic reuse，本 adapter 不写回账本关闭义务，也不声称旧 ScopeRevision 已绑定新 native execution 或新 adapter producer。新的完整输入/producer 集合若要进入 AnalysisScope，需独立 policy/revision 审阅。

source 的公开 `query_dispatch_source` 当前从 gzip 开头读到目标行；`CallOperandReport.from_dict` 则会重新 raw replay，均不能作为通用按需组合入口的反复读取路径。先补准确 manifest 绑定的派生导航：sequence/marker→source association 原行与 SHA，source occurrence→准确 operand shard/row，sequence→native dispatch inventory/port qualification/shard。现 source operand archive 及 V2 inventory 均有有限 chunks，但不能把按行号找到的派生副本当原事实。每个命中都核原 artifact receipt/row SHA/完整 qualified endpoint；跨片对象通过 `BundlePartitions.selected_records` 读取有限原 chunks。导航可重建，事实不另存第二份。

第一步只按显式 sequence/source occurrence 做上述两类查询：预设总 decoded 64MB、原 archive chunks ≤2、派生数据 chunks ≤4、结果 ≤100、wall 10s，预算不足返回完整已访问端点、未访问 cursor 和具体 frontier，不截断后声称无匹配。若某个原 chunk/shard 本身超过预算，直接 OPEN；批量 publication 需另审一次有界 retained-output indexing 计划，当前不启动。

root 审阅后顺序：先冻结上述类型/判据；只补 derived navigation/public reader；做同 issuer mismatch、snapshot、known→Unknown、借 ObjectID、错 native ordinal/phase、同 signature 不同 B、frontier/budget 的小 metadata 检查；最后在 native gate terminal 根 receipt 固定后做有限原端点联合验收。不得重调 `connect_current_capture`、`link_call_operands` 或 native producer，不扫描原 raw/100k。source/native 的 coordinate artifact URI 各保原值：native gate 用自己的 `OUT/native-coordinates.json`，不得因 payload 相等重写成 source 的原 profile URI；分别核 Run/process/完整 membership 链。当前 native session 的进行中产物未被本研究读取。

4. **一次联合补采应补真实 writer 缺口；现有事实缺 adapter 不应重采。**

| 缺口 | 最小一次采集字段与边界 |
| --- | --- |
| 实际 scope | 在真实 target exec/start 记录 cwd（并随 chdir/exec 边界变化）、argv、选定 environment/config、实际输入身份及代码/依赖 build；以 Run/process/区间和准确原 facts 绑定。`project_root`、源码绝对路径、分析机 cwd 均不能代替。原 run.sh 声明先 cd 到 LeWM，command/launch metadata 未保存 target 实际初始 cwd；本研究没有扫描 OS raw，不能断言其中绝无个别 getcwd/chdir 事实。 |
| 直接 source→dispatch | source CALL attempt/bytecode/InvocationKey/hook epoch 与 dispatch sequence 的显式同步因果 token、完整 frame/wrapper 边界和 gaps；保留真实输入/返回/异常 phase。现 `OperandCallAttempt` 只有 dispatch callable 与 `arg0` reference，marker 只有 nearest retained ancestor，不能恢复完整 actual/formal/keyword/default 绑定。 |
| 原 primitive/boxed 内容 | source load/参数/返回与 Python dispatch payload 的完整 ordered tree、准确 builtin kind+值（float 精确 bits、字符串长度/完整性），省略/default/None/空容器分开；native boxed formal kind 与路径、实际 scalar↔wrapped-Tensor 转换 token/标记及来源。现 Python collector 跳过 primitive 内容；ETO Double 的 `std::to_string` 不够精确，SymInt/enum/truncation 不猜转换。原 0D Tensor 不改成 scalar，native-only wrapped origin 仍是 inference。 |
| 环境/生命周期 | 共享 issuer UUID+generation 随 call/operand/env/dispatch manifest 保存；实际 globals/builtins/cell 读取、默认值在 entry 的真实绑定及变更版本、非 weak 对象生命周期（若要跨事件接入）。现 owner/cell 身份不含内容；defaults 是 dispatch-local snapshot，不证明 entry binding。旧 weak 合同已可条件连接，不以此新增字段为旧档必然重采理由。 |
| 内容/效果/ready 的后续闭合 | 若目标要越过 reference-only：实际读写/变换、逻辑版本与失效，Tensor native input/output metadata及转换来源，enqueue/完成/等待、资源/代次和 observer/target 归属；不要从 host Return、形状、allocation epoch 或相同对象推导。它们保持原必需 OPEN，不在本 adapter 假造。 |

完整来源 SHA/bytes 与小 metadata 检查见 [receipt.json](receipt.json)。本次 receipt pass 读取 1,924,565 stored bytes，仅解一个保存 header 1,035,272 bytes；原事件行、raw scan、archive chunks、SQLite、target/producer 执行均为 0。前序小源码/metadata 探查另计。此交付是实现计划和合同研究，没有实际跨片匹配数量或联合门通过结论。

root 审阅后的首 patch 已进一步收窄为 `native_context`，见 [FIRST_PATCH.md](FIRST_PATCH.md)。上文 `reference_ports` 是暂缓的后续方向，不在首 patch 中实现。native attempt02 已由 root 主动停止 exit130，20 shards 只是有限产物；本计划不把它们当 final batch root，也未读取其进行中或 partial 数据。

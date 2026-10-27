# D content/source 接线独立只读审查

结论：PASS_WITH_SCOPE（所审源码的有限静态结论）。三项本轮实质发现已由 root 修复并静态复核；不等于 root graph/query 定向测试、D 全门、P/V 或 runtime 已通过。

审查者未编写 content_validation.py/query.py/validation.py。本轮只读产品/现有 fixture/测试文字，仅写本 ignored 报告；没有运行 pytest、probe、LeWM、GPU、capture 或安装。下面行号绑定本报告 SHA 表的当前源码，原问题行号来自首次实际源码读取，未伪造当时未保存的 hash。

## 实质发现及限定关闭

### F1：StorageContent resolver 类型错接（原 content_validation.py:299–302）

原代码创建局部 class Catalog，只提供 graph() 再传 `_storage_coverage`。该 helper 严格要求 exact `_ValueCatalog`；因此一个原本合法的 StorageContent 在查询/validate 中会抛 TypeError，而非完成 coverage 或给 issue/gap。这是源码上确定的类型错接；本审查没有为它新跑复现。

root 已新增 `_ValueCatalog.from_snapshots(exact ExternalSnapshots)` 并在 resolve_placement 使用该 factory，共享当前 query 已验证 snapshots，不再 duck typing 或二次 hash。当前 content_validation.py:323–324 附近可查实际 `_ValueCatalog.from_snapshots(ctx.snapshots)` 调用（行号以实际源码为准）。这项限定修复静态关闭，独立回归由 root 执行。

### F2：HostConsumer interval 与实际 subject 的执行域未对齐

原 HostConsumer 路径仅 check_interval(start,end)；两端彼此同 run/process 即可，而 subject/anchor 仍可在另一已知 run。最小反例：READ AccessRef 与当前 support 来自 run A，ProtocolInterval 两端是已登记 run B 的 EvidencePoints；自身区间只给时间 gap，缺 subject-domain 矛盾 issue。

应区分：已知 run/process 冲突是 issue；跨 activation/时钟/协议尚未建立是 gap，不能把两者混合。当前 `_align_interval`（约60–74行）将 host interval 两端与原 subject occurrence 的 run/process 对照，并检查已知 host 区间不落到该实际操作外；HostConsumer 调用此检查，NativeWorkRead 核 run 但不把 native 异步区间强塞 host 生命周期。限定修复静态关闭。

### F3：Q endpoint 的 AllocationTarget URI 别名被误拒

原 ObservationConsumer 使用 target != placement.target；AllocationTarget 的 ProviderArtifact dataclass equality 包含 URI。两端同 hash/schema/size/AllocationID、仅 URI 不同也会触发 content_observation_target，违反既定 scoped artifact identity。

当前 `target_key`（约27–31行）对 AllocationTarget 使用 artifact_key(hash,schema,size)+AllocationID，其他 target 保留 exact typed target kind 和原 ID。ObservationConsumer 以 canonical target_key 比较。真正另一 incarnation 仍 issue，URI 不再虚构另一目标。限定修复静态关闭。

## 当前源码确认的防线

- DataDenotation 只赋 DataIdentity 给 DataValue；Reference 只给 ObjectIdentity；State/Binding/Protocol 不借 denotation 改型。实际 ValueOccurrence 不存在是 issue。
- 逻辑版本/materialization 必须存在于准确 scoped ValueGraph；当前 DataIdentity 的 EEG source_mat 会反查原 materialization.value_version，已知错版本/缺 mat 是 issue，不因 observation 没直接 version 就跳过。旧 namespace 无端口/跨图对应的不足继续 gap。
- 对 OperationResult 的 denotation，resolve_basis 接 actual.origin 的原 occurrence；`_paired` 用原 occurrence_evidence_bindings 比对已知 source instance。未知对应保留 gap，不按名称或最近调用猜 producer。此层不声称已解析精确 native 输入/结果 ordinal。
- NativeInputRef 先查原 boundary.inputs[position]，再按该原 EntryPort 的 ValueID 查本次 entry visit formal；不把 position 当 core physical index。需要原 initial entry、同 region activation，loop/resume/capture 不替代 initial entry。NativeOutputRef 必须命中该 activation 的实际 Return/Raise、exit_name/index 和真实 UseOccurrence；缺观测是 gap。
- UseRef 必须属于准确 operation occurrence 的原 Use；AccessRef 必须是原 StateAccess 并拒 write-only 冒读。原 before-state 必须在 support，support 由当前 canonical flow 核验，不自建 state。引用读取的 effect/reference 不匹配是 issue；缺 reference 对应保留 gap。
- 同 host 多 ticket 仍分别用 WorkEvidenceBinding 比较准确 source instance；不因 WithinOperation 相同就自动匹配。无 correspondence 留 gap；明示另一 source instance 是 issue。跨 activation/native mapping 缺失不是 ready 证据。
- Q root 反查明确 requirement/合同/required output 或 endpoint/facet、真实绑定/值/current support。缺已提供 FK 是 issue，source/protocol/external endpoint 对应未证是 gap；不据 EXTERNAL facet 本身宣布持久化。
- external catalog 初次核验走共享 exact detached snapshot。新 content query 用 `_content_context` 新建 ExternalSnapshots，重新核 caller ValueGraphs/EEG/SemanticGraph，而不是复用 Index 构造时外部 snapshot。返回 dict 统一 deepcopy，不把读取到的 mutable 外部行暴露回 catalog。
- query 的 missing caller lookup ID 正常可 KeyError；这与坏 graph FK 不得逃出 validator 是两回事。本轮审读的原端口/source/Q FK 先 get/存在检查；上游 coordinate/flow issue 会阻止 content pass。未新增异常 fuzz 或声称穷尽所有畸形输入。
- content/denotation/observation 查询均 `source_runtime_verified=False`、`transformation_authorized=False`，没有 ready=True 或因字段一致授原生证明。

## 范围与剩余事实

这是 D 声明/端口/来源连接的审查。EEG 无精确 Use/result ordinal、动态 native pairing、未知 state→version 对应、读取区间稳定性、原 production inventory、实际 produced frontier、每贡献 AND/OR 和 visibility 仍保留原 gap/后续 P/V 职责。没有将尚未做 P/V 判成此门必须实现 ready 的 blocker。

root 正在运行/补充对应 graph/query 回归；本报告不援引未收到的测试结果。三项修正之外，未发现另一个已定位、需阻断本门的源码矛盾。

## 审读源码 SHA256

- `scar/ir/execution/content_validation.py`: `dc72e873407f4507cb3bd677677cdae1d2ffd8ee758a396d7387e2219fb024b8`
- `scar/ir/execution/query.py`: `e0ed8df0868d8999be935ff187d38893a594f846f112b6890edeac9e6a5d377d`
- `scar/ir/execution/validation.py`: `49066eed09567850ae824fd8800b359be33f4c403d641e2fe117b0a786e63966`
- `scar/ir/execution/observation_validation.py`: `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983`
- `scar/ir/execution/coverage.py`: `43a0f21c7a5e5815f3e4408dcf76ff39eeb96f30f4fc0af655a8ccf0aff3a32b`
- `scar/ir/execution/snapshot.py`: `e3b4e071a865f8cb94bcf732ae8b45688ee33243e03921c551dc76690621ed5b`

## 追加：开放多对多 pair 非成员不构成反证（修正上一节相关认可）

只读语义复审。WorkEvidenceBinding 与 OccurrenceEvidenceBinding 没有 COMPLETE/exclusivity 合同，允许部分、多对多来源关系。设已登记集合 P(T)={A}，B不在P(T)并不推出 not-paired(T,B)。它只说明尚缺显式 join。当前 basis 又没有显式指定一个 BindingID，因此不能凭集合非成员性说源属于另一个操作/不可能属于此 ticket。

**决定建议：**完全没有 binding 与存在其它 binding 但缺当前 exact (owner,artifact,instance) 都报告 gap；可用不同 reason 区分 capture coverage 与具体 join 缺失。只有真实结构矛盾仍 issue，例如坏 FK、known run/process 冲突、准确原 native slot/actual 不符、scoped version/materialization/object 的已知冲突。若未来改成 basis 显式引用某 BindingID，而该 binding.owner 与当前 consumer 不同，那是明示字段冲突，可 issue；本门不能凭空假定这个并不存在的字段。

这项结论纠正前一版报告“_paired 有其它来源就可判已知不匹配”的认可。此前三个问题的修复结论不变，但 `_paired` 非成员分支需要按开放世界规则收窄，不能为了现有 negative test 保留不成立的否定。

### same-host 两个 work 仍不能串线

- ticket T1 已登记 A、T2 已登记 B。读取声称 consumer T1，但 basis 是 B：保留实际 T1/B/source refs，报告缺(T1,B)join，不借同 host/parent-child/时间接近补出。
- 这是一份允许不完整的声明，不是已闭合的 consumer/source relation。查询不能把未匹配 source 填成 resolved native input；后续 P/V 必须保留该 gap，不能以它满足 contribution/consumer/ready 支持。
- A 是父 wrapper、B 是 child kernel，可能合法覆盖同 core call；父已 bind 并不排斥 child，也不自动证明 child 的 exact ticket/input 对应。
- 若增加真实 T1/B 显式对应，当前 join 缺失可消除；native applicability/port ordinal 等其它义务仍不消失。无需新增全局历史状态机、COMPLETE 标签或业务名称规则。

### 应保留的最小验收用例（建议，未执行）

1. 仅(T,A)，basis child B：declaration valid + source join gap；不能 issue physical mismatch。
2. (T1,A),(T2,B)，basis B 却 consumer T1：同样 gap 且不能声称 exact native binding 已匹配。
3. 再增加(T1,B)：允许多对多，join 可找到；仍保留 runtime/ordinal gap。
4. 真正错 version、错误 native actual、源实例不存在等准确矛盾仍 issue，不因这个收窄一并降级。

本追加未修改产品或测试、未运行实验。pair 函数的实际源码读取如下；父代理若随后修改产品，应以新 hash/回归另记关闭，本报告不冒称已实现建议。

所读 content_validation.py SHA256：`e4602614780b4635ee0c4a2f3dc129302a14f59082f0a76eca97095453cd8730`。

```python
def _paired(ctx, artifact, instance, operation, ticket, path):
    matches = ()
    if ticket is not None:
        bindings = [row for row in ctx.model.work_evidence_bindings if row.ticket == ticket]
        matches = tuple(row for row in bindings if artifact_key(row.artifact) == artifact_key(artifact)
                        and row.instance == instance)
        if not matches:
            ctx.gap('content_work_source_unresolved', path,
                    'no exact work-to-source pair for this consumer; other partial bindings do not prove exclusion or supply this join')
    elif operation is not None:
        bindings = [row for row in ctx.model.evidence_bindings if row.operation == operation]
        matches = tuple(row for row in bindings if artifact_key(row.legacy.artifact) == artifact_key(artifact)
                        and row.legacy.instance == instance)
        if not matches:
            ctx.gap('content_operation_source_unresolved', path,
                    'no exact occurrence-to-source pair; partial bindings and parent relationships do not supply this join')
    ctx.gap('content_source_run_unverified', path,
            'EEG process IDs and association rows do not establish native run/port correspondence')
    return matches

```

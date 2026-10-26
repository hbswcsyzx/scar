# 单 snapshot 与跨片程序连接：最小结论及下一消费门

只读设计，2026-10-26；未改源码、未打开大graph/raw、未执行codec/lower/target。**不能归为①“通用整程序容器已完备、仅缺producer”：单图ExecutionModel确有跨snapshot类型边界；但该边界不阻止按原artifact联合查询，也不要求合并/重命名全部ProgramGraph。** 现有composition是限定原图查询视图；跨片调用/状态/提交关系的typed权威尚不齐。新GPU小根尚未获得准确路径，因此不推断它与858或旧native Run相同；本计划不判其UNATTACHED理由仅是snapshot。

## 五条实际接口证据

1. `ir/execution/model.py:63–111`仅一个 `snapshot: ProgramSnapshot`；`coordinates.py:55–62`只含artifact/schema_version。`validation.py:524–547`把传入program普通canonical bytes与snapshot schema=`scar.program-graph`、SHA/bytes/version逐项相核。858 composition不能充作该snapshot；`snapshot_for`也只能编码真实ProgramGraph。
2. `coordinates.py:117–126,216–232`的RegionActivation.region/OperationOccurrence.operation是本图裸typed ID；`calls.py:13–20`的caller/activation同样无artifact限定。`call_validation.py:295–313`还要求本ctx中caller静态callee存在、该Region与activation.region准确相等。因此既有CallActivation**不能**直接连两个独立snapshot；Run相同和时间相邻均不能补足它。
3. `analysis/program_composition.py:666–702,705–777,989–1017`保原namespace/locator/body，按需正常回读，不是ProgramGraph；`source_references.py:32–75,77–119`已区分原URI、stored/decoded SHA、pointer、namespace/snapshot/definition。`store/graph_index.py:804–828,879–916`仅以完整namespace+kind+local_id查现producer/Uses，不接受裸ID或产生第二份状态图。
4. `analysis/source_native_composition.py:137–179`已有 `QualifiedOccurrenceRef(execution artifact, occurrence, 原binding)` 与 `RetainedSourceContext(InvocationKey, SourceDefinitionReference, 原facts)`；`_Roots:249–294`严格对齐Run/process/coordinates，`_native_endpoints:731–778`保native自己的ProgramSnapshot/原CFG。公共 `NativeContextIndex.open/native_context:586–728`返回的唯一已证关系是 `RETAINED_SOURCE_CONTEXT`，不是direct CALL、实际参数/world传递或GPU提交。
5. `ir/execution/work.py:46–59,164–180`已允许 `ExternalWorkSource(EvidencePoint,source)`，故真实work本身不需要伪host occurrence；但其持有容器仍被ExecutionModel.snapshot要求卡住。`work_validation.py:89–98`对外部origin明确给external_alignment缺口；WithinOperation则必须确有本ctx occurrence。`execution/composition.py:1–25`只是query输入scope，`ExecutionIndex.resource_composition:41–70`仍基于一个已校验model；不是现成多snapshot全局容器。

## 下一最小实际切口：保来源的有界联合消费，不伪挂接

**已有实档可立即复用。** 原 `source_native_context_gate_20261025` manifest SHA `8cef855ccfe081830a4548aaee80b4226d10aab22d4aa5e102cd1ebe18be8fa6`，旧门已经有seq2331 body-linked、seq244 source-only、seq4 unresolved公共样本。一次新的普通消费只选其中一个已存qualified key，调用现 `NativeContextIndex.open(...原NativeContextInputs...) .native_context(sequence)`；不重建导航、不扫100k、无CompositionIndex全链读取。原样本每次1index/2data/1EEG，stored约21–23MB、decoded约43–47MB，仅作历史成本依据，未来门预算仍实际扣费。建议一query：stored≤64MB、decoded≤64MB、output≤2MB、10s；源码/runtime guard另列，不伪装成query I/O。adapter当前SHA变化须明确拒旧manifest，不绕过 `_producer()` 核对。

**新GPU挂接先核两件准确输入。** (a) 其现work记录+原protocol/provider facts/Run/process/所指profile或dispatch key；(b) 同Run对应native ExecutionModel及其真实ProgramSnapshot。若精确原submit/dispatch证据能唯一指本地native occurrence，可由producer在**该实际局部snapshot**范围补WorkSubmission/关联，普通ExecutionIndex消费；其source端继续用现qualified导航返回原定义/Invocation，不冒充跨图CallActivation。没有对应static graph/occurrence就保ExternalWorkSource与明确missing；Run不一致则只允许reuse静态source proof，不移植旧source invocation。858本身是static composition而非Run，必须逐个核source报告/coordinates，不能按“当前”名称认为同Run。

原导航固定旧source报告和原scope revision，**不能静默换858入口/新GPU input**。定位当前858 body需要严格 `CompositionIndex.resolve_definition/body_publication_state`（约1461/877行）及原publication/source-chain资格；现历史查询没有承担这笔全链读取。新消费先保原导航来源，858-current/body映射不足明确OPEN，而非为一个query重扫大链或伪报已连接。

## 真正类型缺口与完成判据

若新work没有任何真实局部ProgramSnapshot可归属，当前没有“只含真实Run/EvidencePoint/work/resource声明、无伪ProgramGraph”的正式ExecutionModel变体；一般多snapshot caller/callee与state/world/实际submit关系也没有可持久化的qualified typed endpoint/validator。需后继明确**原artifact限定的execution-fragment引用/跨片关系**合同或snapshot-free evidence/work片段容器，复用现WorkSubmission/Resource/Run记录与原facts；它们是缺少的关系/容器，不是新producer/use/state图。不能只把snapshot改成可空并让所有静态FK失效，也不能将retained祖先关系升级为direct submit。

下一门只在取得GPU准确小根后冻结选中原records、同Run局部snapshot与现导航输入；验收逐端点可回原locator、Run/process一致、已存在关系照原语义返回、缺映射保UNATTACHED/OPEN，资源ready/identity/effects不随挂接获证。整体覆盖分母与source858/runtime843历史均不改。若缺上述局部snapshot，先提交这个精确类型缺口供Root审，不运行注定只能造空图的“整程序PASS”门。

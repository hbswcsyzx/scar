# Retained native input → original allocation epoch

基线 `1d4d681d14e9d6e640f6f71f4b39ddb8bcc8bae5`；仅新增 `scar/analysis/native_input_storage_bridge.py`。未改 main/collector/原规范产物。该模块是通用有界只读连接，尚未作为 model-run 批量 producer 接遍全部端口；不是新 ValueGraph 或新事实身份。

## API 与原输入

```python
from scar.analysis.native_input_storage_bridge import query_native_input_allocation
query_native_input_allocation(
    navigation: ProviderArtifact, storage_index: ProviderArtifact, *,
    native_input: NativeInputRef | None = None,
    value_occurrence: ValueOccurrenceID | None = None,
    execution: ProviderArtifact | None = None,
    row: int | None = None, path: tuple[int, ...] | None = None,
    max_input_bytes=256_000_000, max_seconds=60,
) -> dict
```

`NativeInputRef`/`ValueOccurrenceID` selector必须同时提供准确原 `execution` artifact；只用其既有 denotation 选择，并普通解码原 execution/program。row/path 是原 locator 的可选定位提示，不是生产规则。未给 selector 时取普通导航首条。qualified selector 当前按已发布 navigation chunks 有界查找；尚无按 occurrence 的反向索引，后继按分片调用可传精确 row/path。超过预算或找不到准确 epoch 明确失败。

两个 `ProviderArtifact.schema` **不含 `/1`**，准确 path/hash/bytes 已存 `INPUTS.json`，也在 `attempt03/QUERY.json`：

- `scar.native-input-port-navigation`：main `native_inputs_full_20261026/attempt05/port-navigation/manifest.json`，146,783 B，SHA `4436b171be0dec2782e7843bc097227d675efa5e33155a6e8a2bf2408b4b6f72`。
- `scar.tensor-storage-locator-index`：source-entry-project `tensor_gpu_reference_query_20261026/locator-index/manifest.json`，499,687 B，SHA `d127c95a2ff1b1d848288c83ef3cb3785f55f0f2c68d0918f3ef7d280b1de7c2`。

## 实际正常读取结果

`attempt03/RESULT.json`：自持 session11520 **actual exit0**，1.861973900 s，RSS105,932 KiB；stored23,524,721 B + decoded43,885,446 B = **67,410,167 B**（含普通 reader 重读，非磁盘物理 IO）。原 input ValueOccurrence+execution 选择返回现有 AllocationTarget，query17,807 B/SHA `1d8b055cec1cc43fc021ae6ddce59c372fb87016b8a69e64545e80d0075f5d91`。原 attempt01/02 保留，都是同一端点的 API 收窄过程，不是新增主体/批量覆盖。最终源 SHA `8f890f2de40d2679f0ecde5692add9266f3ac1aaf87d2a821026c24b12457e73`。

准确同 Run `capture:ca66b69a8cfc3c1b88e0c22e8ec00d58d735fd016d16edf85e8cf0ac51eb5fc3`、PID1578961；未拼 source PID272038。样例原 companion row21/path[0]、ETO `#/nodes/18/inputs/values/0`。`OPERATOR_SCOPE.json` 独立核原 parent row 与正常 program/evidence codec：node25、`actor.scope=0`、rf_id21、name=`aten::lift_fresh`；原 EEG category=`cpu_op`；原 pinned interface 为 `aten::lift_fresh(Tensor(a) self) -> Tensor(a)`。这是**实际 ATen 输入**，不是 scar-dispatch input marker。scope 核对另读19,272,121 B原普通文件，decoded同量，1.766489510 s，与 query 计量分列。

链路：原 ValueOccurrence/Use → 原 NativeInputRef/denotation → 同一原 ETO input → 原 companion metadata → 同 owned profiler/result/process/device 的 provider allocation ID+birth SourceFact → 既有 StorageAllocation → 原 AllocationTarget。样例CPU float32 scalar，provider_allocation_id1、原 birth物理行7，原 allocation4 B。普通 reader 解码原 allocation chunk并核 scope/device/id/birth/receipts；地址只做矛盾检查，不作身份。native signature slot通过原 NativeBoundary.port 找原invoke Use，不假设 signature顺序=core Use物理顺序。

Observations：源对象身份沿原 `ObjectIdentity(ObjectRef)` 保留，未重新 mint；本 adapter 的 `python_identity_established=False` 表示不新增此资格。producer 的原 geometry flag 保留，不篡改旧 association。API新增的是准确分配归属查询。无新图节点、无 Tensor 内容读取、无 raw ETO/physical/OS 重放或 live LeWM 源读取/target执行。不是 CUDA、本样例GPU未验证。

## 保留边界与下一逻辑版本接点

allocation 是 pinned provider 的原 allocation epoch，不是永久指针身份、OS页驻留或完整 GPU allocation/lifetime 证明。storage_offset 未暴露；本次不创建 StorageRegion/range、Materialization、ValueVersion、实际 StateWrite、ResourceInstance placement 或 ready。原 INVOKE 两 completion/whole-world 且 `effects_complete=False` 原样保留。旧 denotation/object、allocation 与逻辑内容仍分开；没有把同 token/storage、`Tensor._version`、数值样本当同值。全程序仍 OPEN。

明确断口在 `NativeInputMetadataSession._candidate`：已产生 NativeInputRef、原 metadata SourceFact 与 provider epoch，却仍留 `geometry_allocation_qualified=False`；新 consumer 可沿准确原 allocation 读通上述一条物理关系。另一个断口 `build_native_operator_value_fragment` 只生成 endpoint-local symbol，UNKNOWN provenance/equivalence，Materialization.region=None；它的 validator 也明确限制UNKNOWN。此次不倒改其语义。

下一条 generic clone/copy 桥无需新图种类：已有 `ContentRead`/`VersionRef`、`ValueProduction`/`StateProduction`、v2 `ValueVersion`/`ProvenanceRecord`/`Materialization` 可承载。必须先把原输入**本次读到的内容版本**与动态 read/work/source 关联（包括未知别名/外部写失效），再以固定 provider 源码+确切 overload/schema 的 COPY/VIEW/WRITE 协议及实际 normal output 端口生成来源和输出物化；不能把本次 ObjectIdentity 或 endpoint-local symbol直接改称内容版本。实际 `aten::clone` 的复制关系可由明确准入的固定实现协议证明，不依数值采样；但输入 VersionRef、normal output/物化观察点尚缺的实际关系必须保留。`copy_` 的目标写版本/转换/全覆盖需独立确定，schema may-write 不等于已发生写；view 可共享allocation而逻辑映射不同。actual-op 的逻辑输出不得绑定另一 marker 时点的 region。现有已存 UNKNOWN fragment 仍保持旧合同；后继应新增受准入的 protocol producer，而不是改旧 JSON 标志或永远只留UNKNOWN导航。

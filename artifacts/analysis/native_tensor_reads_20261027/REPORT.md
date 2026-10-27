# Native input → read → symbolic version, under explicit conditions

基线main `d12d62bdab5365f0e0b01215db666c9e818a8153`。仅新增 `scar/ir/execution/native_tensor_reads.py` 与 `scar/analysis/native_tensor_reads.py`，显式依赖 native completion `00e0e46f9d82f4973338b4b90aeaaed7fa0024df`（本树cherry `7438f1e6`）。旧 ExecutionModel wire、旧强validator/default及UNKNOWN native value fragments未改；main/collector未改。

| 层次 | 本轮事实/边界 |
|---|---|
| Observed/retained | 同ca66 Run、PID1578961；实际copy_ node63/ETO `#/nodes/50`、canonical seq9，src input1来自原companion row53，原原生input Use与ObjectIdentity。原INVOKE唯一normal transfer→normal Return、原EEG输出引用、原world state transport。没有重放原raw。 |
| Implemented | 窄typed `NativeTensorRead`关联现有 `ContentRead → result:VersionRef`，原reference occurrence为独立input。ValueGraph新增本次read的1 LogicalValue/1 Version/1 read-local ORIGIN，未知数值/上游不阻止符号身份。 |
| Verified | attempt02自持session98430 actualexit0；完整normal build及strict typed reader，普通v2 ValueGraph解码；helper按原端口/source/state重核。 |
| Conditional | `CONDITIONAL_READ_RESULT`；固定provider implementation、实际storage-read分支、state footprint、区间内容稳定性、upstream origin均保明确typed条件。不是observed memory-read/content。 |

准确新边：原 `...:9:inputs:1` reference ValueOccurrence/原 `invoke:use:1` → ContentRead（basis为原NativeInputRef input1）→ read-local `VersionRef`；support是原 `...:9:inputs:3` world-before occurrence，effect沿原 `invoke:use:3`→normal `...:9:outputs:1`。区间BEFORE invoke→BEFORE normal Return，区间source保原 `#/nodes/50/outputs`，协议source是固定版本规则。HostThread沿原 `UnresolvedHostThread`，未猜Linux TID；Run/process/actor/interval没有混其他capture。

read ID与LogicalValueID由准确原execution URI/SHA、snapshot、NativeInputRef、原Use、state occurrence与profile限定，**不从ObjectID/storageID/Tensor._version生成**。ORIGIN只表示本次read命名域的符号根，producer=None、upstream未证；不宣称原始内容诞生于copy_。不同read符号不推出数值不同，也不自动相等。旧reference继续ObjectIdentity，未改为DataIdentity。没有新mint Use、ValueOccurrence、state、Object或allocation。

实际最终结果：wall6.551524870s、RSS107,932KiB。producer stored36,852,259B+decoded57,211,069B=94,063,328B；reader stored36,720,517B+decoded57,079,327B=93,799,844B；合计187,863,172B（含正常重复读，非物理磁盘IO/性能基准）。新规范小产物总15,041B：read.json11,339B、values.json2,769B、protocol.json933B。audit捕获raw/live LeWM源码open=0、target exec=0；无capture或201body读取。原attempt01为接入独立normal helper与ORIGIN之前的prototype实际结果，保原字节/旧source SHA，不用其冒充最终版本。

最终typed receipt：`attempt02/read/read.json`，schema=`scar.native-tensor-read`，SHA `61f1ab043dbc8453210b69c7c18447460da09e825af3f94bb7f4c75ce97ca837`。值图仍用 `scar.ir.v2.values`，SHA `592b146fb3c92243ba64b74893f0f865f8fec0ec81368a9bbcb0d6c1815a08de`。完整ProviderArtifact与原inputs见 `INPUTS_AND_OUTPUTS.json`。

source allocationTarget保原src epoch3引用，但ContentRead.placement明确Unresolved：allocation/派生几何尚不是带read内容的有效source Materialization；没有按另一个marker时点建立Mat，没有给输出内容、actual write、长期稳定性或ready资格。normal completion只是正常接口/Dispatcher返回走廊，不授kernel完成/内存read。新的符号read版本是可查询依赖关联，不是全scope建模完成。当前仅固定CPU copy_ src1 profile，其他primitive需明确语义规则；未自动批量枚举/import全部read。第一阶段仍OPEN。

API及Root CLI/model-run接点见 `HANDOFF.md`：normal consumer返回 `(NativeTensorRead, ValueGraph, measurements)`，每次重新核原不可变artifact和端口/state，无JSON恢复owner或mutable-IR验证缓存。后继copy保版本/新物化可以引用这条read的VersionRef，但须另核条件和本次输出的表示/region，不能直接把旧UNKNOWN改KNOWN。

# 下一门：owned native scalar observed-root provenance

只读设计；未改生产/main/index，未跑 target、producer、G1、capture，未读8MB association、qualification rows、privateDB或重解 ETO。依据仅 attempt04 小 result/report/manifests、2011B interface catalog 和现有模型/decoder 定义。

| 已知分类 | 数量与模型含义 |
| --- | --- |
| dispatch |261=260 normal canonical+1 frontier；normal 中4 complete-reference、256 partial-reference。RAISED 已记录 outcome，但缺实际 native witness/parent3900。|
| Tensor reference/geometry |776端口=520held+256Unresolved；现有独立C520qualified/256gap。均不证明Tensor内容。|
| metadata |3095原输入路径=516关联+2579 `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE`。后者是边界缺口，不能改称metadata未采。|
| retained输入形态 |3089 Tensor slots、6 TensorList（3empty）、2072 OPAQUE、3084 SCALAR_OPAQUE；单位为slot/list，不能相加当端口总数。0D与None/empty不混同。|
| 细分未知 |2579按内部op/observer/缺schema等拆分，516按B/C交叉分布，eligible scalar种类/值/次数、每schema调用直方图均 `NOT_MEASURED`；不扫大文件求数。|
| 软件/内容来源 |source0body/271unresolved；primitive值可能已有原ETO payload，但尚无owned scalar content链；Tensor内容没有采集。静态4个schema接口已表征，world/state/ready未知。|

优先补**native scalar输入的原生值来源**。它建立一个可复用的逻辑值入口，而不是继续只给metadata。暂缓RAISED native资格：writer只存RAISED/entered/output-none，没有exception对象/类型；此次缺实际operator节点，不能借正常cat接口补造invoke/exception/world。增加dispatch-outcome模型也不能补这条native证据。

复用 `LogicalValue`、`ValueVersion`、`ProvenanceRecord(ORIGIN, producer=None)`、`ValueDenotation(DataIdentity(VersionRef))`、`NativeInputRef`、`ValueOccurrence`、`ProviderFactReference` 和现有 `PythonLiteral`。每**occurrence×原端口**独立Version/逻辑身份；输入只为观测root，上游producer未知，绝不挂到消费它的invoke作为产出。相同scalar内容不合并身份、不宣称程序常量，不挂共享静态LiteralEvaluation，不把literal塞进自由metadata。

显式新scalar capability；原V1/V2 reference默认不变。owned replay取真实原ETO有序path、schema leaf `type.kind()`与`real_type.kind()`，调用既有 `decode_pinned_scalar`。仅原合同允许的Int/Bool/None/ASCII String可资格；Double（包括NaN、-0与非有限/字符串化）、Sym*/enum/Device、容器、截断/缺值均具体frontier。不可从schema default或companion SCALAR_OPAQUE补值。准确FactSource+Run/process/native producer/ordinal/slot/ValueOccurrence/VersionRef都必须由owned query独立复核。typed query返回原PythonLiteral及其来源；Reference/Tensor路径仍不证明内容。

实施上限4现有源码：

1. `trace/native_protocol.py`：V2 projection/occurrence builder生成scalar root versions与DataIdentity；静态Program/接口与B/C保持。
2. `ir/execution/native_port_protocol.py`：真实formal leaf kinds、owned scalar query及独立全slot/version/source核验；unsupported也入账，known→Unknown和错版本不能绕过。
3. `ir/execution/content_validation.py`：区分owned scalar-content结果与held-reference结果，不能把旧bool当内容证明；默认reference gap保留。
4. `trace/native_capture_batch.py`：显式cap、scalar全分母/预算/发布；复用同一CPU260边界与原source acquisition，不读取旧association大报告。无IR schema新增；若现有类型不够表达，先报精确关系阻断。

Root下一次真实门：**同一保存CPU capture离线一次**，genuine公共binder/owned source，复用260 canonical边界、原G1/partition与pinned program/catalog，261/2332/3095及RAISED/parent frontier不删。不再G1 import/OS-interface模型/target/GPU/LeWM，不读8MB association。原ETO值必须由新owner验证，先前JSON/SQLite不恢复authority。原program156893B+catalog2011B若作为额外输入各读一次，保守增加stored+decoded317808B：旧上界67280634+317808=67598442B，仍≤68000000B；catalog计control后864842B≤1MB，program单列IR输入。无其它额外读；最终入口冻结时逐项核算，whole120s/outer150s/RSS2GiB/index128MB/output64MB不抬。

门只做真实资格与一个必要negative：已有same-signature动态事实各获独立版本、owned query返回精确literal；从已资格的两个等内容None端口交换VersionRef/原FactSource（若真实符合，否则明确BLOCKED，不补数据），必须独立source/slot拒绝而非旧seal拒绝。counts由实际输入给出，eligible数量当前NOT_MEASURED。static ProgramSnapshot身份需精确对既有program/catalog；每occurrence的内容不进入signature。Tensor provenance、上游Python来源、state/ready、异常payload与whole-model仍OPEN。

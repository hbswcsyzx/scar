# 实际完整 GPU activity 关系门

Root持有session **44866**并确认实际 **exit 0**。GNU **100.02s**、peak **274632KiB**；gate whole **99.9119365719962s**。这是消费原LeWM证据的CPU离线门，**target执行0**、Torch import0，不是新的LeWM/GPU episode或速度收益测量。

|实际分母／结果|数量与含义|
|---|---|
|原Kineto provider记录|515398，完整原SHA/EOF扫描|
|原EEG instances|461242，全部76个chunk严格遍历|
|GPU候选记录|46142，raw与EEG逐项来源对账|
|已资格单activity quiescence|23000 = 22457 kernel + 543 copy；90个typed fragment分片|
|非物理work的annotation|22060；原frontier码 `GPU_CATEGORY_END_CONTRACT_UNSUPPORTED`，不作为未知GPU计算|
|物理活动尚未支持|1082 memset；原frontier码 `MEMSET_END_CONTRACT_UNSUPPORTED`，没有丢出分母|
|全GPU分母库存|47个有界inventory chunks；23000+22060+1082=46142|

普通public binder真实取得原Run `capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0` 与target process，再完整校验Kineto与原EEG来源。原instance namespace `native:2a622492625eb1b2a7a105036e0ac792b5a6249fc60cf111443bf7fe53140d88`、原ordinal/locator保留。标准EEG小projection保原记录；`origin.point`引用真实`start_ns`字段，quiescence引用不同`end_ns`字段。没有虚构raw `/end` 或由时间邻近生成HB。

现有 `WorkSubmission / WorkEvidenceBinding / WorkQuiescence` 经普通record codec回读和每片独立source检查；没有新IR表、profile、ProgramGraph或ExecutionModel。**ProgramSnapshot attachment = UNATTACHED_TO_PROGRAM_SNAPSHOT**。只授严格单activity停止访问；没有生成ResourceOutcome或借用释放，dependencies/effects/materializations/retention仍UNKNOWN。结果成功、child闭包、source/native执行归属、内容/state/ready与whole model均未闭合。

唯一实档负例使用同Run、同projection两条实际producer：把binding[0]的instance **kineto:385137** 换成 **kineto:385145**。独立checker以 `native work binding producer/artifact/source differs` 拒绝；`independent_semantic_rejection=True`、`seal_rejection=False`。未增加额外测试或重跑。

实际combined stored+decoded输入 **2,886,678,160B**（顶4,000,000,000），包括正常binder、OS二遍、Kineto再扫描、全76实例chunk；reservations **0**。输出write＋stored/decoded readback **295,469,147B**（顶512,000,000）。107个实际SCAR导入全来自本隔离树；独立source hash **16,147,425B**、control hash **1,854,470B**。这些是actual计数；budget-plan的2,885,804,963B是准备时bulk下界，不能混用。

freeze **6d3ebff0e0424f48298b034d52b688f4b523425d334cf47b1a8ccea218a1681b**：370源码、2runner、12controls、337项bulk声明。源码基线为frame-entry-routing的bc139/e017体系，不回填主树其它版本资格。实际普通reader在门中验证bulk SHA/EOF，prepare未读bulk字节。

两新增源码已冻结，main应用时均应为原路径ABSENT：

|文件|bytes|实际源码SHA256|
|---|---:|---|
|`scar/trace/native_work_bridge.py`|29256|`dc6754154fee5d54c20aed15f5fe0fc44d9fe320c14fb5d4a01cfc225d66cdb3`|
|`scar/ir/execution/native_work_protocol.py`|11110|`687f4de8c6d281dfaf97a2fce883cdd04c866cebca26f75738bfc99f25ceb68a`|

精确应用receipt见 `SOURCE_APPLICATION.json`，原通过字节另存producer快照。适用合同固定Kineto `DeviceProperties.h:25–42`：cu132声明下Kernel11、Memcpy5/PtoP4；准确primary链接/SHA保留在资源交接目录。实际历史编译flags、loaded provider binary及旧collector执行源码仍是已有OPEN条件，不能用本机头文件补历史事实。原frontier与runtime产物字节未改。

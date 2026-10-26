# Main V2实际完整资源关系门

Root持有session **79428**确认实际 **exit 0**。GNU **101.88s**／peak **290016KiB**，gate whole **101.77305573801277s**、producer **100.95074019097956s**。这是原LeWM证据的CPU离线消费，target执行0、Torch import0，不是新GPU episode或速度收益测量。

|实际分母／关系|Main V2结果|
|---|---|
|原provider记录|515398，Kineto完整SHA/EOF校验|
|原EEG instances|461242，全部76个chunk严格遍历|
|GPU候选|46142，raw与原EEG完整对账|
|已资格物理单activity quiescence|**24082 = 22457 kernel + 543 copy + 1082 memset**|
|非物理work的annotation|22060；原码 `GPU_CATEGORY_END_CONTRACT_UNSUPPORTED` 保留，不称未知GPU计算|
|分片与分母库存|95个typed fragment，47个inventory chunks；24082+22060=46142|

本次实际从main加载110个SCAR模块，真实public binder及Main V2 producer/checker/原typed codec完整经过；不是把隔离结果移植为main qualification。冻结 **371源码／2runner／15controls／337项bulk声明**，freeze SHA **81c976910b6d032d4c41dc9952dbc835d66d35c07e213bc96d721c755f843b1c**。实际输入combined stored+decoded **2,886,678,160B**；输出write＋stored/decoded readback **310,685,099B**；reservations0。独立source hash **16,458,992B**、control hash **1,866,940B**，均在原预算内。

唯一实际负例：把同projection的**memset原387936**的binding[74] producer换成**copy原387251**。原source为 `sha256:256f688f0c767a6302fccaec088fab9b1232ca429c24de4254a984329c3be875#/traceEvents/387936`。独立checker以 `native work binding producer/artifact/source differs` 拒绝；semantic=True、seal=False。投影片000001／原EEG ordinal311864／projection index74由一份小source-receipt元数据精确定位；该投影与首投影均保留，不重解EEG或原raw。

两新增main源码最终字节：

|文件|bytes|SHA256|
|---|---:|---|
|`scar/trace/native_work_bridge.py`|29256|`986a74bc6282deb7ab7a642874c2078850640088bc1077e5d4058ea5f03448d5`|
|`scar/ir/execution/native_work_protocol.py`|11124|`79979e0bdab0de1bd85c5c732ef40fa5f2c62ce20da2043c23cca77fed84ddd3`|

原 `APPLICATION.json` **824B**、SHA **6a4a13d6effc2d89c0ed23afb5d844025d5d1067c95fd5ab9402833438f24213** 是冻结control，仍为原candidate-pending状态，未倒改。实际应用/终态另见 `ROOT_APPLICATION_RESULT.json`、`ACTUAL_TERMINAL.json`。V2最小diff和合成typed API记录另存candidate-evidence，后者不授实际资格。

V1与V2分列：**V1**为隔离树bc139/e017依赖体系的session44866、23000 kernel/copy关系及6d3冻结，原259文件保持Git commit **461156466016859fb17559b2a8564b683694c4dc**；Root须从该commit blob取旧源码/材料。**V2**为本次main371冻结及session79428、24082关系，包含原k/c和真实memset。没有V2隔离全门或V1 main全门，不能混写来源。

每条只授原单activity的 `WorkSubmission / WorkEvidenceBinding / WorkQuiescence`；标准EEG projection保原namespace/ID/ordinal/source，start与end分别引用真实不同字段。没有创建ProgramGraph/ExecutionModel、新profile、Outcome、queue lifetime或BorrowRelease。**UNATTACHED_TO_PROGRAM_SNAPSHOT**仍成立；dependency/effect/materialization/retention coverage保UNKNOWN。结果成功、child闭包、程序执行归属、填充值、目的allocation、内容/state/ready及whole model均不因此闭合。历史provider binary／编译flags／旧collector执行源码的条件未消失。

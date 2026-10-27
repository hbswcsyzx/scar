# Memset单activity quiescence：只读最小扩展计划

状态 **PROPOSED / NOT_IMPLEMENTED**。既有全门已归档并push为 `461156466016859fb17559b2a8564b683694c4dc`；两源码和6d3冻结不改。此次仅核固定primary，未读GPU chunks／raw／projection，未运行目标或新门。

固定Kineto [DeviceProperties.h:25–42](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/DeviceProperties.h#L25-L42) 在 `CUDA_VERSION>=12000` 使用 **CUpti_ActivityMemset4**，cu132声明适用该条件。固定 [CuptiActivity.h:45–69、573–596](https://github.com/pytorch/kineto/blob/094d3c1d072362d0a919a77299459eee94f97931/libkineto/src/CuptiActivity.h#L573-L596) 沿同一泛型start/end时间转换，输出GPU_MEMSET及device/context/stream/correlation/bytes metadata。官方 [CUPTI13.2.1 Memset4](https://docs.nvidia.com/cupti/13.2.1/api/structCUpti__ActivityMemset4.html) 的start/end明确是该memory-set操作执行的起止；0/0表示时间不可得（字段段，网页抽取0-based283–306）。因此有效正区间可复用现有**单activity**停止访问合同，无需新IR类型或profile。实际历史编译flags／loaded binary仍是原provider适用性条件，当前安装头不补历史证明。

**最小diff仍只两源码：**

1. `scar/trace/native_work_bridge.py`：`_reason`把`gpu_memset`纳入已核end合同的类别集，去掉该类别的无条件unsupported返回；原严格正区间、完整raw/EEG来源、native lane、actor、缺项与矛盾规则保持。更新报告中的Memset4合同字段及已支持标记。
2. `scar/ir/execution/native_work_protocol.py`：独立checker的原source类别集允许`gpu_memset`；保持逐ticket binding、不同start/end FactSource、Run/process、原scope/ordinal/原record、完整库存及UNKNOWN coverage检查。现`activity_actor`的normal字段路径和`_check_original`已处理memset，保持同pipeline，不新建分支流程。

原1082条是**物理memset未支持**，不是非物理annotation；本扩展也不将22060条annotation变成work。旧门对memset提前返回unsupported，未保正区间／actor有效性细分，故新可资格数量 **NOT_MEASURED**，不得预填1082或24082通过。新门按全实际分母机械分类；无效／缺失依旧frontier，已知矛盾依旧拒绝。

只授该activity的 `WorkSubmission + WorkEvidenceBinding + WorkQuiescence`，仍为 **UNATTACHED_TO_PROGRAM_SNAPSHOT**。不新增ResourceOutcome，不证明child／host闭包、成功、release、logical Version或ready。Memset4虽有`value`字段，固定Kineto JSON metadata未保存它；不能从名字、bytes或“memset”类别推零值、常量内容、目的allocation或Tensor来源。

后继唯一实际门在新attempt目录由Root运行：同原LeWM capture，一次fresh public binder＋一次Kineto完整scan＋全部76 instances chunks；沿原4GB stored+decoded、512MB输出含回读、600/660s、2GiB预算，保持原门产物不动。不新capture／GPU／target、不重import全bundle、不从旧JSON恢复owner。唯一实档负例选择同Run一条**实际已资格memset**绑定并换成另一真实producer，要求独立语义拒绝；若没有充分实际记录则BLOCKED，不造数据。不增加前缀门或测试矩阵。

primary准确SHA／字段定位见本目录 `primary-receipts.json`；旧已通过门及其controls字节均保留。

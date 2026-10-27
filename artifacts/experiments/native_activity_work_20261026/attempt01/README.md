# 完整 native activity work 门：实际PASS_WITH_OPEN

Root session44866实际exit0；GNU100.02s/274632KiB，gate99.911936572s。原515398 provider／46142 GPU候选完整入账；23000个kernel/copy单activity quiescence，22060条非物理annotation类型拒绝与1082个尚未支持的物理memset分开保留。详见 `REPORT.md` / `RETENTION.md`。以下为原准备入口与预算说明，不是待运行请求。

本目录由Root执行唯一实门。实现仅新增 `scar/trace/native_work_bridge.py` 与 `scar/ir/execution/native_work_protocol.py`，隔离树基于bc139/e017的既有IR；未改main或其它生产。

`acquire_native_activity_work(capture_root, partition_root, output, *, budgets, on_verified_shard)`内部正常public binder一次，原Kineto一次完整流式扫描，全76个EEG instances chunks一次逐表遍历。manifest没有每片GPU类型库存，因此没有片号／raw locator白名单。所有provider类别与GPU候选进入分母，有效kernel/copy逐项构造原 `WorkSubmission / WorkEvidenceBinding / WorkQuiescence`；memset、annotation、缺／零／负区间或缺actor等保明确frontier。PtoP actor沿固定serializer的inDevice/inContext。

每256条使用标准EEG小projection，保原ID/namespace与原archive ordinal receipt；start/end指该真实artifact不同字段。typed记录经既有record codec回读，再由私有fresh-source独立checker逐片核来源／producer／端点／inventory；唯一负例仅交换同Run两条实际binding的producer。无目标、Torch import、全bundle重import、SQLite或新profile。

产物是可供原ExecutionModel扩展的typed fragments，**UNATTACHED_TO_PROGRAM_SNAPSHOT**；不伪造空ProgramGraph/ExecutionModel。只证明本activity已静止；不授COMPLETED结果成功、child闭包、retention释放、内容或ready，所有效果等coverage仍UNKNOWN。

真实primary适用：固定094d3c… `DeviceProperties.h:25–42`，cu132声明条件下Kernel11、Memcpy5/PtoP4；准确官方字段与SHA在 `artifacts/analysis/resource_completion_bridge_20261025/primary-receipts.json`。历史loaded binary／实际编译flags仍是OPEN条件。

预算：combined stored+decoded输入4,000,000,000B；输出write+stored/decoded readback共512,000,000B；wall600s／outer660s、RSS2GiB、256rows／16MB分片。`budget-plan.json`是声明与次数核算，不是actual IO：bulk下界2,885,804,963B，另有小control读量；runtime对真正read返回值计量，partition先reservation，完整SHA核后计verified decoded，二者分开。source hash64MB、control hash16MB独立列账。prepare不读bulk字节，只核stat／原writer声明；所有bulk SHA/EOF由真实公共reader在门中核。

Root实际使用的原入口（已执行，不自动重跑）：

```bash
bash /home/zyf/AAA/scar-worktrees/frame-entry-routing/artifacts/experiments/native_activity_work_20261026/attempt01/run.sh
```

本门独立于source代理计划中的858长门；现API没有resource消费hook，不为省扫描耦合两个pipeline。禁止从saved coordinates恢复owner。失败现场保留，不自动重试。

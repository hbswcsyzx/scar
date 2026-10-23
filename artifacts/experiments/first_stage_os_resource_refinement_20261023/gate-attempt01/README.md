# R2.1 唯一35port sparse gate

2026-10-23。有限端点/codec检查已完成；**原gate实际exit1**（最后metrics footer缺陷）。
独立finalizer实际exit0。没有重跑gate、22分钟CLI、raw importer、目标、GPU或全suite。

## Inputs / Implemented

原R1 base为`../../first_stage_os_interface_work_20261023/result/interfaces/manifest.json`
（从本目录定位），SHA256
`cbc6dcfd78ccca0961bdabecce94bc747b7b281fdbc3f49228c8b52b9b3aec14`。
运行producer绑定HEAD6e6b67b与R2 revised-freeze11模块SHA/补丁。3个executor观察来自
原audit真实known-process/native-thread代表locator；没有用程序/函数名字挑选。

生产adapter实现3records、独立ID/关联表、旧version门控、真实JSONL selector及两种
固定preimage精化。core无POSIX FD域限制；OS adapter保留非负int检查。R1原产物不变。

## Verified scope

- 一次流扫原1,067,768observations，发现35个created ports，接到22个原producer work。
- 35个原HandleBinding仅精化endpoint，原ID/target/start/end/rights/ownership/source保持。
- 13组pipe两端target/FD/lifetime不同；3个executor只改变原Work.executor。
- 38个provider accesses，全部selector/preimage核原chunk两层SHA、line、ordinal、行SHA。
- 35 ProviderHandle、73 ProviderRecordSelector、38 ProviderResourceAccess公共codec往返；
  实际新HandleBinding经execution v9 record codec往返。
- 6条旧版本拒绝：execution8新handle/role encode-decode，ProgramGraph4/27新role负wire。
  负wire未成为被接受的程序模型；无ProgramSnapshot或完整ExecutionModel构造。

`result/manifest.json`为443,446bytes，SHA256
`6b5e1ae12e2c05364c76364cf1b1cf7859d2f6ddb09380c8940a3980381bde5c`。
`selector-proofs.json`保存35个原target、lifetime与真实locator；`codec-boundaries.json`
保存6条实际错误，`selected-executors.json`保原ordinal。原10GB规范表没有重导/重写。

## 原gate失败与finalizer

`run.py`已完成上述全部assert、写出proofs/boundaries和ENDPOINTS_PASS；最后汇总metrics
时负wire局部变量`resource`覆盖了stdlib resource模块，AttributeError，wall55.03秒、
peakRSS592,948KiB、exit1。原失败代码/producer/stdout/stderr/time不覆盖，生产IR/adapter
没有因此修改。

`finalize_report.py`只核已有小delta/proofs/time，wall0.05秒、peakRSS18,484KiB、exit0。
`finalized-summary.json`状态为VERIFIED_SCOPE_WITH_ORIGINAL_GATE_REPORTING_FAILURE，
`completion-receipt.json`分别记录gate1/finalizer0。没有将原进程伪写为PASS或重跑gate。

## OPEN

35个table container仍未恢复，保Unresolved；INPUT/shared FD/VM/ancestor未实现。
完整ExecutionModel语义、新ProgramGraph28正向完整图组装未验，完整模型仍OPEN。
这些是建模关联，不是性能优化，也没有LeWM加速比结论。

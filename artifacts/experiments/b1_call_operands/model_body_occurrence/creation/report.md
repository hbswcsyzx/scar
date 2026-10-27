# O08：实际 Create RAISE 与缺创建证据的分界

2026-10-18。只新增 `execution_body_creation_graphs.py` 与 `test_execution_body_creation.py`，原33项及prefix4项的4个冻结源码、产品均未改。

## 原图反例

从 `resumable_execution()` 的同一 Program 重建 factory 的实际失败路径：`factory.entry` 的 Create 真正选择 RAISE → `factory.failed` 的准确 packet/state formal → 实际 RAISE terminal。原 factory NORMAL 路径及指向它的同步 CallActivation 被移除；Start/Resume activation 可保留为外部捕获，删除已移除值的 denotation。不是只改 transfer ordinal 却沿用 NORMAL landing。Origin 仍指这一具体失败 Create occurrence。

剥 O 两表后，原 canonical 校验必须 valid。带 Origin 后，精确要求 `body_creation_completion`；没有 transfer/producer/type 形状错误替它制造失败。另以实际 raw-pack普通 operation 冒充 creation，精确要求 `body_creation_kind`。

两个缺采对照分别删除 Create 实际 transfer、删除 NORMAL handle occurrence（所有实际引用改为原 Unresolved，denotation同步移除）。原 canonical 与 O 校验仍 valid，origin.handle 必须 None，各保 `body_creation_transfer_unobserved` / `body_creation_handle_unobserved`。6个原 capture 义务、Start8个输入与原 creation record均保留，不从同代码/现有owner反填成功 handle。

## 实际验收 / 冻结

`creation/attempt001` **4 passed / 1.35s**；首跑通过，没有隐藏重试。原命令、完整 stdout/stderr、JUnit、注册源码清单保留。before/after fingerprint均 `982f60284ca756f6b8f0499ecd5c06805882ccb0e7d9e4036297f18520764728`。只运行新owned文件，无组件/full/GPU/capture/commit。

冻结SHA256：fixture `71e417d98d545ff0ba6db306e8c3d3f176a09688ac198091de3089e6242aad0e`；unit `ebf351431d1c62908dd8c373b5c10b683dac811628c703fc32a5cbb533661c7d`；受测 root `resumable_flow.py` 为 `7d926f20870034d45574a43fa1e226c32914d1c5cb62efdfe99c18ac3726c156`。

结论只补齐 O08 的这些 supplied-model 发生关系；flags保持 source/runtime/value_identity/transformation False，不证明 actual native Create/自动恢复或整个 P3完成。新增两源码自本报告起冻结，root统一验收前不再写入或启动测试。

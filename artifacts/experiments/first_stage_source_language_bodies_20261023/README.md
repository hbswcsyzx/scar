# 单 source / 两原 body 语言建模验收：原失败保留

2026-10-23。**Observed：exit1；没有重跑或修改冻结生产源码。**
session78051，Python PID615136。`producer.json` 与实现 freeze 保留实际脚本、输入与
生产源码 SHA；`run.time.txt` 是独立 `/usr/bin/time -v`：27.23s wall、26.67s user、
RSS437276KiB。无目标、forward、GPU、新采集、prepare或compile；只读原CodeWitness。

`CompositionIndex.source(140)` 读取旧不可变三图，核当前 source exact fingerprint，
仅生成本file AST/symtable并构造 PreparedSource；没有准备151个file。
原三图/namespace/source/code链接见 `source-input.json`、`producer.json` 及 body原档。

- body11：在25.50s前构造118 operations，保存
  `result/body-11.source-program5.json.gz`。runner按代码顺序完成公共结构读取与canonical
  roundtrip、独立源码/CodeWitness协议核验、旧v4 producer/parser拒绝新协议、v5无独立
  options拒绝source proof。之后才写出body END。各检查的临时返回值在第二body异常后
  未保存成summary，故不冒称另有独立完整核验报告。
- body26：公开 source-environment validator 在新 INDEX load 的地址refinement集合
  检查拒绝，未返回body，无新完整body26原图。`failure.json`/stderr保留真实traceback：
  `source_environment_validation.py:164 unexpected or missing source environment address refinement`。
  新slice adapter增加了receiver/key/world Uses的Element READ refinement；旧validator
  只接env/store协议refinement，尚无合法新load adapter。不能删除refinement或关闭检查。

后继需根协调共同producer gate结束后，显式接并校验language load-index的地址子集；
其余env地址集合检查保留。当前能力为 Implemented、局部 Verified、完整gate Rejected；
不是LeWM目标失败，不是当前Run新body集成，不给速度/覆盖提升结论。

后续：窄适配经审查后实施，attempt02原实现作用域错误保留；attempt03仅重构body26，
已恢复65ops并PASS_WITH_OPEN。body11原图未重构，attempt03仅结构回读其canonical不变。
参见相邻 `first_stage_source_language_bodies_attempt03_20261023/README.md`。

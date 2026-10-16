# R1 编译上下文：有限验收记录

日期：2026-10-16。状态：**Verified R1 only**。
实现提交 `c3a7f83`；机器证据清单：
`artifacts/reports/gates/n2-compilation-context-manifest.json`。
基线主线 `9cb3805`；初次源指纹
`00ba7be52f91b21298ee92be7e79d34e0b127b1819280a5be178934b50bdaff8`；
补充缓存反例后的最终冻结指纹
`aefadf0d7b9b4bb6c2ccd0d8e5248bb6962c6cf79bbcbffb7406afa6d63f08bf`。
本门不交付参数绑定、完整程序恢复或变换许可。

## 问题与实现

Observed：原LeWM calls归档5个旧MISMATCH的源码未改；用captured code中的
future annotations编译可逐字段重现完整descriptor，零flags的3种optimize均不能。
Implemented：通用matching profile从记录恢复受支持future bits，明确排除
CO_NESTED等结构flags。缓存分别绑定canonical源码路径和原样compile filename，
并绑定源码fingerprint、profile、flags、optimize和解释器上下文。
未知bits或frontend未支持的语法有具体边界；成功仍需完整descriptor相等。
无文件名、函数名、行号补配，无执行或修改目标源码。

新seed schema v2保存 `RECORDED_FUTURE_FLAGS_V1`。旧seed v1显式使用
`LEGACY_ZERO_FLAGS`；inventory v6按嵌套seed版本分派，历史报告不静默升级。
编译上下文对应不证明历史loader、函数实例、环境、引用来源、内容或效果相同。

## 专项验收

最终冻结源：**287 PASS，4个判据全部通过**；pytest76.55s，门进程77.390s。
源码未变；报告：`artifacts/reports/gates/n2-compilation-context-final-verified.json`。

初次冻结源：**279 PASS，4个判据全部通过**；pytest75.37s，门进程76.072s。
测试期间冻结源码未变。机器报告：
`artifacts/reports/gates/n2-compilation-context-verified.json`；
门定义：`gates/n2_compilation_context.json`。

自动正例来自原始通用多文件命令、parent future compile/exec和嵌套调用。
覆盖同文件不同编译上下文、结构flags、未知flags、缓存、v1/v2与v6历史重放、
profile/schema/源码篡改、独立预算、输入/输出硬链接保护。新CLI测试最初有一项
fixture将外部 `<frozen codecs>` 错当项目源码MISMATCH；修正为明确外部边界后29项
全部通过，未放宽产品源码匹配。

## 补充反例与冻结调整

初版完整回归 **2,270 PASS / 282.88s**，进程284.553s，峰RSS1,028,444KiB，
3项已有warning。独立审查随后复现：Path把`/./`和重复斜杠折叠，原样co_filename
仍不同；初版cache键会混用编译输出。两个profile、两种顺序、两种路径共8个
反例均先VERIFIED再错误MISMATCH，复现记录保留于
`artifacts/experiments/n2_compilation_context/filename-regression.json`。

已修复为缓存显式保留原样compile filename，保留旧路径准入与完整descriptor比较。
聚焦15项通过，最终冻结后重新运行专项、必要回归及真实独立重算。
初次真实CLI生成成功（253.999s / 230,348KiB）；独立重放在67.790s时由开发者
主动停止，以便修复冻结源，退出143。仅停止已核对PID/命令/cwd/owner的本次子进程，
不是LeWM或产品运行失败。原始stop-reason与失败receipt保留，不记作最终通过。

## 最终回归与真实归档

最终完整回归 **2,278 PASS**，零失败/错误/跳过；进程290.334s，峰RSS1,028,636KiB，
3项已有warning。源指纹在全程保持最终冻结值；机器报告、JUnit、日志与time见
`artifacts/reports/gates/n2-compilation-context-final-full.*`。

公共独立重放已通过。为避免重复生成，最终check-call-seeds复用
初次生成的报告，但从原始raw/source完整重算当前报告并精确比较。
两阶段分别绑定上述源指纹，不声称初次生成采用最终源。只接受最终验证期间
冻结源不变、raw与匹配源码hash不变、LeWM Git状态不变的结果。
最终独立重算 **252.349s / 236,320KiB**，状态 `VERIFIED_R1_ONLY`；12项一致性检查
全部通过。812个entered-code分组、850份descriptor、84,319入口记录保持一致。
code link由548 VERIFIED / 259 INCOMPLETE / 5 MISMATCH变为
**553 VERIFIED / 259 INCOMPLETE / 0 MISMATCH**；变化恰好是原5条，
其它code links和其它model字段完整一致。eligible definition种子由421变为425；
新增的另1个VERIFIED是无唯一普通definition的module，不伪造function入口。
报告gzip266,162字节，SHA256
`c6ebc3cea23e9ab54f6f4a9ac66258e21f0de0626edf9a8fdd08141adee5f06d`。

raw三文件、115个对应源码路径、冻结SCAR源指纹和LeWM clean HEAD
`f70fed80288462ca4d006cb3607ec6da6eaa851f`均不变。结果、原始stdout/stderr/time见
`artifacts/experiments/n2_compilation_context/final/`；初次生成与主动停止记录在
同目录上层的`real/`。分析与回归有重叠，时间不作分析提速结论。

原输入为主仓保留的
`artifacts/traces/n2_call_edges_lewm_retry_20261015`，
旧对照为 `artifacts/experiments/n2_call_source_seeds/real/seeds.json.gz`。
实验driver及原始输出置于 `artifacts/experiments/n2_compilation_context/`。
这是离线对应复验，不是新的LeWM执行或clean A/B；不报告加速比。

## 下一门

完整交付 [跨层参数/返回查询](N2_CROSS_CALL_IMPLEMENTATION.md)，后续接环境、
循环与状态来源。自动化范围与可检验端到端目标见
[2026-10-16现状](AUTOMATION_STATUS_20261016.md)。不新增detector/backend。

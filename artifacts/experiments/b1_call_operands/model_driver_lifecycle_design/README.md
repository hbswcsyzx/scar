# D2生命周期建模复审证据

2026-10-18；产品基线 `cc44e14a2d173328a4e2f89f405a5add401d85e1`，D1实现
`382363c`已验收。本批是设计复审，**D2.0字段冻结仍OPEN，产品未实现**。
当前计划见 [D2实施门](../../../../docs/M1_DRIVER_LIFECYCLE.md)。

## 原始文件与范围

- `review/core.md`：独立body/no-body/状态覆盖复审。先提非Created guard失败用
  INVOKE RAISE，root反例后撤回，改真实bool BRANCH；没有运行实验。
- `review/session_release.md`：独立session post/partial effects/合流/drop审查。
  反对单锚强制，建议从原CFG逐路派生；不新造producer/world/历史状态。
- `review/session_release_probe.py/.json/.log`：本轮单次3项带断言stdlib CPU实验，
  3PASS、0FAIL；NORMAL后先前post被callback改写、RAISE已写部分状态、unraisable
  保留返回且保留写。Python3.14.7、torch/scar均未导入。不是native request adapter。
- `review/lifecycle_probe.py/.json/.log`：单独的最终stdlib CPU观测脚本，六组输出，
  **没有assert**；exit0只表示输出成功。`attempt1.*`为扩展前脚本的观测输出，其
  旧脚本bytes未保留，不能用最终脚本hash冒充绑定首个版本。
- `review/adversarial.initial.md`：保留误称async close重试后CLOSED的初稿。
  root逐项对照JSON后发现实际StopAsyncIteration后inspect仍AGEN_SUSPENDED。
  `review/adversarial.md`已修正，未重跑/覆盖脚本或原始输出。此传感器本身不是
  全machine状态，也不能从host结果推出续体消失。
- `review/root-decisions.md`：root逐项裁决、拒绝方案及仍未冻结的依赖。

旧的八组语言见证只读复用，未重跑；其hash引用在独立报告中，不另算本批实验。
本批没有pytest、LeWM/GPU profiling、Tensor采样、源码lowerer、detector或backend。
旧D1 671组件/3,706全仓结果仍绑定冻结实现，不能算本批D2产品通过。

## 下一步与验收

顺序为D2.0冻结字段/来源/失效 → D2.1 body publication → D2.2 no-body真实分支 →
D2.3 session/drop合流 → D2.4 wire/query/CLI与组合验收。具体正反例和未决项见
`docs/M1_DRIVER_LIFECYCLE.md`。M0–M2与完整第一阶段继续保持未完成。

`receipt.json`保存本次设计范围与源码未改的核对；`manifest.json`逐文件校验。
只核对已保存证据，不重新执行脚本或实验：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/check_evidence.py
```

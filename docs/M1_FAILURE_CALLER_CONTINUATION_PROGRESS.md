# 获取失败与 caller 当前完成：连接进展

2026-10-19；基线 `2c427b7b2923ac6e177b4ecac2200aa25ea31fa0`。
[冻结计划](M1_FAILURE_CALLER_CONTINUATION_PLAN.md)保留原字节。本轮延续原
A–H/十六组/P5/M2 原113构造196字段，未完成整个模型。

## Inferred：源码审计发现

先前 failure_paths 将内部失败出口、获取自身 RAISE 与 caller 最终终点混用。
既有 helper terminal→获取 RAISE 交付不能代替 stage packet→helper terminal
证明；资格拒绝的 candidate/branch 只提供控制条件，whole packet 有自己的
构造器、exception/traceback Uses。caller finally 若返回新值，不会改变获取
操作已经发生的 RAISE。

generic actual continuation cursor 原本只许可来自 anchor callee ancestry 的
来源，未支持 anchor 自己选中 completion 的 caller landing 值。新入口必须核
实际 transfer、CompletionResult ordinal、landing formal、准确 ValueOccurrence
及 typed signature，排除 forwarded/sibling 值，不能凭 same activation 放行。

## Implemented：两个接缝保独立收据

原 failure key、获取 RAISE source_result/source_edge 始终保留。C1 caller
视图使用既有 continuation_rows；helper terminals 继续核 stage packet→helper
与 helper→获取 own R，caller_continuations/caller_terminals 另接外层当前完成。
own acquisition/constructor 无内部 helper terminal，不伪造一个补计数。

资格拒绝保持 control_anchor；stage_origins 复用原 input_origins recipes，
动态 stage_packets 沿本 helper 实际路径核原构造器、whole packet、exception/
traceback Uses。其来源类型仍待 native 证明，未把候选与异常对象当作 copy。

原 source_consumers 独立参与 path 状态，即使 own helper terminals 为空也
不能绕过错误绑定。caller 当前 terminal 的 state_uses 指准确 tuple ordinal/
location/StateVersionValue/OwnedUse，动态只核对应实际 capture；不宣称旧状态
不变，不捏造外层 CallActivation，不添加最终提取义务。

generic actual cursor 支持准确 own-selected-result 入口，原槽位经过 forward
Reference 后位于 landing1，仍按 CompletionResult(0) 取值。另一个实例、另一
successor 或 forwarded Use 不会因此得到 ownership。所有本轮 Invoke 槽解析、
原结果入口和 state/terminal joins 使用同一共享预算，先计费后扫描。

## Observed：真实执行与有限复核

证据目录：`artifacts/experiments/b1_call_operands/model_failure_caller_continuations/`。
root 独占串行执行，作者每次先冻结，前后源码清单、命令、全日志及 JUnit 独立
保存，不覆盖首红或拿旧 SHA 的测试证明新源。

- first-red-static 0P/3F，三图均 core/full-valid；新测试误用不存在的
  ValueKind.PROTOCOL。此为测试作者 API 错误，不算产品缺口。
- red-after-type-repair 0P/3F：精确类型/源签名断言通过，产品缺 source_result
  字段。旧 report issues 为空；这是尚未表达 caller 续接，不是旧实现拒绝合法图。
- first-integration **29P/0F**，pytest20.25s，runner21.08490321226418s；
  841份稳定源码 SHA `7d6f5a2f3d487de25ddc9e7e401ef133844445e1338e1cfc9ef02ad5d26800e1`。
- source-and-budget-repair **31P/0F**，pytest21.13s，runner21.918162873014808s；
  841份稳定源码 SHA `952cf6d7734f8b10901ba23c3a3dd06279657a9ed81cbdf9d09a9d65b5918ff4`。
  新增错 source receipt 与 raw walker 完成后的真实预算中段项目均通过。

有限独立审查发现并修复 own 空 helper terminals 绕过 source consumer 绑定，
以及入口 ownership 之前的 Invoke 槽解析未计费；后二者修订包含在31P源中。
三路复核保持冻结，不给完整 A–H 或 native/变换授信；旧全仓结果不归本源。

## Verified：最终受影响回归与封存

最终 `verified-final`：**1747P/0F/0E/0skip**，pytest359.76s，
runner360.777431034483s，841份源码运行前后完全一致：

```text
952cf6d7734f8b10901ba23c3a3dd06279657a9ed81cbdf9d09a9d65b5918ff4
```

原1716精确 case identities 加31项新用例；新增15项静态、16项动态，均未改
旧 tests/fixtures。归档核验器要求逐项 identities 保留、所有旧测试输入/合同/
codec 字节和上轮证据不变、两个受保护原仓库 HEAD/status 不变；只校验归档，
不重跑测试或 workload。最终核验结果与文件散列见 `checkpoint.json`。

在当前 worktree 的 lewm 环境可复核：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_failure_caller_continuations/checkpoint.py --check
```

这是 affected focused 回归，不是当前字节的全仓回归或 Python 自动恢复测试。
同型错 source receipt 的特定拒绝码、source/slot/forwarded/sibling 反例、缺采、
opaque 和真实预算中段都只授各自已执行范围，不授整门或性能结论。

## 原范围与后续

原 A–H 八格与十六组仍 OPEN；本轮仅给原 B/H 补两接缝连接。helper 内更复杂
清理、其余 direct/native 来源、共享 incoming、重执行/刷新与完整 detach 仍
按原清单推进；不以新用例计数或单条供应图关闭整门。

所有源码/值/运行时/变换 authority 保 False；供应 IR 与发生记录的连接不能
冒充从原 Python 自动拆解整个 LeWM，也没有新 backend、profiling 或加速比。
完整 M0–M2 后再先向用户讲解模型。

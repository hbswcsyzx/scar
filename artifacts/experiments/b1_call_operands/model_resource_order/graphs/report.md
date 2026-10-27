# R2.2 record/wait/consumer canonical 组合

结论：**owned focused PASS**。本代理仅新增两个授权文件，未改产品、旧 fixture、docs；没有运行组件门、全仓、LeWM 工作负载、GPU 或 native 协议实验。

## 1. 稳定 API 与实际路径

`tests/fixtures/execution_order_graphs.py:118`：
`event_order_execution(*, same_queue=False, with_wait=True) -> (ProgramGraph, ExecutionModel)`。

完整单入口 canonical host CFG：

```text
P1(QA) → record r1(QA) → wait W(QB) → consumer C(QB) → P2(QA) → record r2(QA)
        → host_read → RETURN
```

- 六个真实 work ticket 稳定 ID：`p1/r1/w/c/p2/r2`；原操作 `order.{name}`、occurrence `0.order.{name}`，prefix 与 ticket 同名但类型不同。
- 原 StateLocation：content、QA、QB、E；各有 ResourceLocation 和准确 ResourceUse/ResourceAccessBinding。E 与 content 的原 Reference Use 保留两个准确 handle 关联，queue/executor 用显式的 ImplicitBinding，不造假 ValueOccurrence。
- record r1/r2 的 generation 是对应原操作第 0 个 StateAccess，真实 READ_WRITE E 并产生各自 StateVersion；同一个 event ResourceInstance 有两个 EventRecordID。marker 是对应 record 的 queued work，captured 是其 prefix.previous。
- W 是真实 ORDER/READ/WRITE 操作：E 只 READ、QB READ_WRITE；selection 是原 STATE_CONTENT Use `order.w.event`，实际读 r1 的 E 后态。没有把 ORDER 标签解释为 full_overwrite。
- 每个队列的 QueueOrderProfile.through 是其最终 prefix；with_wait=False 仅去掉 typed QueueWait 关联，保留实际操作/工作发生，以验证 host 提交顺序不足以构成跨队列依赖。
- same_queue=True 将 C 放在 QA；其他工作保留。所有六个工作都是 pending：**outcomes=()、quiescences=()**，借用/物理适用范围保留 Unresolved。没有填 PROVEN。

## 2. 第一次且唯一一次 owned pytest

原始目录：`artifacts/experiments/b1_call_operands/model_resource_order/graphs/attempt001/`。

```bash
#!/bin/bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_execution_order_graphs.py -q --junitxml=artifacts/experiments/b1_call_operands/model_resource_order/graphs/attempt001/junit.xml 2>&1 | tee artifacts/experiments/b1_call_operands/model_resource_order/graphs/attempt001/output.log
```

实际 **28 passed in 1.82s，exit 0**；没有首败、修改用例或重跑。source manifest 在 pytest 前记录，owned 两文件执行后 hash 未变。tool wall time 3.299s 包含 shell/conda 启动，不是程序性能。

- command SHA256：`e11cbfe7a7f7b2e993f14c5bcd23092bb0ed4f1d76b77aba61533393cd4188b8`
- output SHA256：`a84926d26ecad4e4d3d190c5ef7c4a42a7ba78524d317e5a8df65f1cd38d1ba2`
- `junit.xml`、完整 `output.log`、`sources.sha256` 均保留。

root 在本代理首次 pytest 前做过基础 fixture smoke，反馈 valid/gaps 与 P1→C/P2→C 查询结果；不将其计作本代理独立执行或额外测试分母。

## 3. 28 个用例的有限分母

| 范围 | cases | 实际断言 |
| --- | ---: | --- |
| canonical 原状态与 pending record | 1 | 六 ticket、两代同 event、W 读 r1 StateVersion、E READ 无 after/QB RW |
| 跨队列 wait 与同队列 FIFO | 2 | P1.end→C.start CONDITIONAL；不需要 Outcome/host sync |
| host 顺序与旧 record 边界 | 2 | 缺 QueueWait 不支持跨 queue；r1 不覆盖 P2，不随 r2 重录更新 |
| consumer/wait start 与 end 区分 | 1 | P1.end→W.end 成立，不能倒推 W.start |
| FIFO profile 的三个变体 | 3 | 无 profile 不授同队列 start；record capture 不依赖源 QA profile；无 QB profile 时到 W.end/PrefixEnd(c) 仍条件成立，到 C.start 不成立 |
| 缺 generation | 1 | 精确 r1 generation gap，不猜 selection 或授 P1→C |
| host read 边界 | 1 | 真实 host_read 原操作存在，但不生成 Outcome/quiescence/ready/free/persistence 字段 |
| generation/access/marker/wait/profile 错接 | 15 | event 实例、event_access、缺/错 marker、captured queue/未来 prefix、generation Location、wait access/缺错 ticket/r2 selection、错 Location/Reference selection、profile queue/缺 cutoff 均 issue |
| 已知另一 run | 1 | record 观察点不能借另一 run |
| 联合环 | 1 | Work 依赖图与两条 prefix 链各自无环；合入 event/wait/FIFO 后的回路为 cycle issue |
| **合计** | **28** | 声明级关系，不是 native 协议、内容或 consumer denotation 覆盖率 |

联合环仅令 P1.dependencies=(C,)；去掉新三表后仍 `require_valid`，确认不是旧 R2.1/core 先拒绝。合入 P1→r1 signal→W.end→C.start 与 C.end→P1.start 才成环；不将循环当作自证 order。

## 4. 首轮绑定 source SHA256

| 文件 | SHA256 |
| --- | --- |
| `tests/fixtures/execution_order_graphs.py` | `d4e21e8c63ebdb279bafae66ce14b5f78b917f05d3d1e37e3c56b94a2a203e2a` |
| `tests/unit/test_execution_order_graphs.py` | `9e12801664040125006d751f50ae91147a43d95d1c539969e3170d63995f1ab7` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/order_validation.py` | `9d7e4421593efdc27bf205213f6281532f8ea35142890c2036f6a4c6cd2497e4` |
| `scar/ir/execution/query.py` | `4a45323b4f213ac5fd86f2a9054f6adc1a9371fcee0414ee44348cf0505aee72` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d` |
| `scar/ir/execution/model.py` | `6d592afa5a7b8f9eab774c41f52322da6ad742c405a03e2f8448e06afdd1dd92` |

## 5. 边界与冻结

Observed：实际 canonical fixture 构造、完整 path、此次 pytest 命令/输出与原端口断言。Declared：profile、record 代次、captured frontier、原 selection state 和派生 OrderStep 的一致性。未证：CPU/GPU/native 协议适用、物理顺序/终结/内容、host wait/host read 可见性、free 与 persistence；本 fixture 没有执行真正的 host wait、设备消费或输出观察。

所有条件结果保留 gaps，`source_runtime_verified/runtime_order_verified/transformation_authorized=False`，没有 ready/free 字段。R2.3 的 denotation、贡献覆盖与 ready，以及 R3/完整 R2/M0–M2 均不由这 28 例闭合。owned 两文件以本表 hash 冻结，后续产品修复/统一组件由 root 管理；本报告不冒充独立审查自写 fixture 之外的全部产品。

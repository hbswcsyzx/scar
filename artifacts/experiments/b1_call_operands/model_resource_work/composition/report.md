# R2.1 canonical work/retention 组合验收

状态：**owned focused PASS；完整 R2 仍 OPEN。** 仅新增以下两个跟踪文件；未编辑产品、旧 fixture 或 docs，未运行组件门、全仓、LeWM 工作负载或 GPU。

## 1. API 与实际组合

- `tests/fixtures/execution_work_graphs.py:180`：`ordinary_work_execution(*, queued=False, two_tickets=False, kind=COMPLETED, quiescent=True, retained="resource", activations=1)`。
- 同文件 `:194`：`invoke_work_execution(*, raised=False, queued=False, quiescent=True)`。
- 两者均返回 `(canonical_program, execution_model, value_graphs)`；catalog key 为准确 artifact.sha256。

普通 fixture 复用 R1 `resource_execution_program` 的完整 acquire→两次实际 StateAccess→RETURN、原 UseOccurrence 和当前 StateVersion。新增 CPU EXECUTOR 与 QUEUE 的静态 ResourceUse/动态 ResourceAccessBinding；未知 realization/source 保留 gap，不为满足接口捏造 native 实例创建或运行证据。

INVOKE fixture 直接复用 `partial_state_invoke_program` + R1 `declared_path`，实际走 NORMAL 或 RAISE。world 在两个签名均为 result 0，但 NORMAL 进入目标 formal 0、RAISE 进入 formal 1；result 1 分别是 Reference/EXCEPTION_PACKET。InvokeBoundaryStateEffect 连接准确原 invoke State UseRef、实际 successor、CompletionResult index 和 landing 的 State ValueOccurrence；不造普通 StateAccess/results 或共同 AFTER world。

每次 work 有独立 WorkTicketID、WithinOperation 来源、原 effect、executor、Direct 或 Queued。prefix 是持久链，queue 指实例；ordinary prefix 观察点为真实 AFTER，INVOKE 为实际 EDGE，未将内部提交伪装到 op BEFORE。两个 activation 的同一静态提交产生不同 ticket 和 activation-local retention target。

FAILED 保留实际 effect_frontier，coverage 为 PARTIAL，不推导整个内容已产生。CANCELLED 可无 WorkQuiescence 且 borrow release 未知；terminal kind 不升级为 quiescence/free。正常 release 明确连接本 ticket 的独立 Quiescence。retention 分别复用原 resource、HandleBinding、ValueGraph allocation 或 Materialization；allocation/materialization 不增加平行 ResourceInstance，不改旧 materialization producer。

## 2. 首次执行记录

只执行一次 owned pytest，首轮没有失败；未修测试后重跑。

目录：`artifacts/experiments/b1_call_operands/model_resource_work/composition/attempt001/`。

精确脚本 `command.sh`：

```bash
#!/bin/bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_execution_work_graph.py -q --junitxml=artifacts/experiments/b1_call_operands/model_resource_work/composition/attempt001/junit.xml 2>&1 | tee artifacts/experiments/b1_call_operands/model_resource_work/composition/attempt001/output.log
```

实际结果：**38 passed in 1.50s，exit 0**。tool wall time 2.970s 包含 shell/conda 启动，不能当运行程序性能。
`sources.sha256` 在本轮 pytest 之前记录；owned 两文件执行后 hash 未变。

- command SHA256：`436407ddd346190551d6041450ea2743367dc600aadf86ebd5ae5380f6ba8d16`
- output SHA256：`2d30e0f35af685e226ded3d8b167ffe1344afe569e21b12cc0aa9504fc6aecab`
- 原始 `junit.xml` 与完整 `output.log` 均保留。

root 在首次运行前修复了 WithinOperation retention.start 不应被代理为物理 BEFORE 的处理，并通知 validator 冻结；这是 root 的预运行产品修正，**不是本代理实测首败**。

## 3. 38 个用例的有限分母

| 检验 | cases | 原端口/义务 |
| --- | ---: | --- |
| 普通 Direct / Queued，两 ticket | 2 | 原 AccessRef、精确 executor/queue、persistent prefix、独立 Quiescence |
| 实际 NORMAL / RAISE × Direct / Queued | 4 | 不同 formal 排列、真实 transfer、失败仍有 PARTIAL frontier |
| CANCELLED 无 quiescence/release | 1 | 不抹 effect、不隐式 free |
| 同静态 submit 的两 activation | 1 | 不同 occurrence/ticket、local retention target |
| 原 handle / allocation / materialization retention | 3 | 准确外键、current support、BorrowRelease→本 ticket 的 Quiescence |
| external source / unresolved actual post | 1 | 合法 unresolved，不伪造入口、post 或 source 证明 |
| N/R 各六种 INVOKE 错接 | 12 | wrong actual successor/result/formal/location/input/invocation |
| 原效果、角色、前缀与 ticket 错接 | 11 | access index、executor role、queue role、prefix ticket、prefix cycle、dependency cycle、outcome ticket、frontier ticket、quiescence ticket、过早 release、旧 retention state |
| Direct thread 另一个已知 run | 1 | 不借另一 run 的线程身份 |
| 已知矛盾 terminal observation | 1 | 不后写覆盖同 ticket 旧 outcome |
| retention 使用已结束 handle | 1 | R1 历史 binding 单独合法，新增 work borrow 在其已知 end 后被拒 |
| **合计** | **38** | 仅声明级连接分母，不是 source/native/协议覆盖率 |

所有负例先验证未改 baseline；实际修改的是 R2 关联或原有有效端口间的错配。最后的 handle 反例另移除 work 关联执行 `require_valid(history_only, program)`，确认历史 end 本身不使 R1 图非法，再要求 work retention 拒绝。

## 4. 绑定的 source SHA256

| 文件 | SHA256 |
| --- | --- |
| `tests/fixtures/execution_work_graphs.py` | `7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f` |
| `tests/unit/test_execution_work_graph.py` | `3c8fdef85aa02b72a63745c0be4b411426adf06da076bbda477789f7d1a60bb5` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/work_validation.py` | `5150570dc2c548a47f61f5d4daf5ee0aaf7ee000732d0ce693f961a5e1553a17` |
| `scar/ir/execution/model.py` | `274b30e249972f27053835819c090fa33695dae672a739706624c70935a27444` |
| `scar/ir/execution/validation.py` | `14f4817aab8b907d3d06a083d0e355db3018b5d6d30ac332d70136008e0c860c` |

## 5. 证据边界与冻结

Observed：本报告的源码构造、实际完整 IR path、首轮 38 用例命令/输出与端口断言。Declared：提交/资源/效果/frontier/queue/retention 的类型与准确发生关系。未证 source/runtime：物理提交、CPU/设备协议适用、真正完成/停止访问、内容、所有权和转换安全；ProviderFactReference 仅是 locator，fixture 使用 MissingEvidence/具体 Unresolved，不手写 PROVEN。

正例均断言有 gaps、`source_runtime_verified=False`、`transformation_authorized=False`。本门无 event record/wait/order/consumer ready 字段，不借此声称 R2.2/R2.3、完整 R2 或完整 M0–M2 已完成。owned 两文件以本表 hash 冻结，后续组件门由 root 统一运行。

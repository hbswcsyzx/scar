# R1 resource/execution 组合与有限源码复审

结论：**BOUNDED_PASS**。仅覆盖本报告列出的声明级组合和资源连接；最后一轮为静态修复闭合核对，未重跑测试。

冻结版本由 root 提供：`6fcac0f778d56d7fe4fdb90e546b23e545f86f96`。
root 组件门绑定的 472 个注册源 fingerprint：`131fa88c62901a016b88778ea975b3a63a6e59497d49740968bd3d49df190e3b`。
本代理未运行组件门或全仓门。

## 1. 交付与具体覆盖

仅新增两个跟踪文件，未修改产品代码：

- `tests/fixtures/execution_resource_graphs.py:40`：`resource_worker_program` 提供完整单入口、实际 Use/StateAccess/RETURN 的静态资源图；acquire/use/dup/open/close 是声明的普通资源阶段，不声称已完成 POSIX 调用前端或异常路径恢复。
- 同文件 `:136`：`resource_execution_program` 为每个 activation、operation/value/use occurrence 建立实际连接；同一个静态 CreatedResource 在两个 activation 中有不同 ResourceInstance，Region requirement 在本 activation 内复用。
- 同文件 `:87`、`:115`：真实 Data/State 端口的 dup/open 和 close；同 OFD 的不同 handle lifetime、独立 open 的不同 OFD、明确 EndedAt 后的旧 handle 拒绝。
- 同文件 `:221`：`resource_execution_with_allocation` 复用原 ValueGraph allocation，不另造 allocation ResourceInstance；pool 另为 MEMORY_POOL。
- `tests/unit/test_execution_resources_graph.py`：最终 **22 个用例**，包括 external/implicit、跨 activation owner/state 错接、stale support、错误 creator site、allocation/pool 类型及外键、lifetime 更换 target、同数值 descriptor 的不同发生、静态显式 handle 不可绕过、已知 endpoint 与原 ResourceUse 精确对应、capacity 的 current/stale support。

这些 fixture 没有执行设备或 OS 工作。重复 loop visit、resume/INVOKE 等由 root 的其他 execution fixture 验收，本文件的两个 activation 不能冒称 loop 证据。

## 2. 实际执行与首败保留

所有本代理 Python 命令先 `source /home/zyf/miniconda3/etc/profile.d/conda.sh`，再 `conda activate lewm`，`PYTHONPATH=.`；精确命令、原始输出和 source manifest 保存在各 attempt 目录。

| 目录 | 本代理实际结果 | 含义 |
| --- | --- | --- |
| `attempt001/` | construction/core smoke exit 0 | execution validator 尚未运行；输出明确 `execution_validator_run:false`，不能计为 execution 验收 |
| `attempt002/` | **20 PASS / 2 FAIL，0.69s** | 首次运行完整 owned 22；两个错误图被旧 validator 接受，原失败完整保留 |
| `attempt003/` | **22 PASS，0.68s** | 产品修复后同一套、未改动的 fixture/tests 通过；不与 attempt002 累加用例数 |

attempt002/003 精确 pytest 选择：`python -m pytest tests/unit/test_execution_resources_graph.py -q --junitxml=.../attempt00N/junit.xml`。
第一次两个产品缺口分别是：同一个 NativeHandleLifetimeID 可换成独立 open 的已知另一 target；UnresolvedHandle 带已知 endpoint 时可换成另一 activation 的 Reference 而仍绕过原 ResourceUse 对应。
修复由 resource validator agent 完成：lifetime 固定 `(target, namespace)`；已知 unresolved endpoint 检查 scope/availability，并与原 ResourceUse 的当前 UseOccurrence 精确连接。`None` 仍保留未证 gap。
对应不变的 regression：测试文件 `:113`、`:144`。

原始 output SHA256：

- attempt001 `3f259691a3c73ed969246bab3f5f9d3e77705a3d98061162a5933aeac094054e`
- attempt002 `f3bee389f023e2025e5def16627335fce5048ebc1e3cb6784c98944479ce848c`
- attempt003 `c5c0dada5c47d2f22e9d63e32fab5f52bb0645f8153139a0c6c7a0e39c24c008`

## 3. 独立资源源码复审及最终 closure

复审范围为 `scar/ir/execution/resource_validation.py`；不能把自写 fixture 的成功称为产品实现的独立证明。

1. **namespace 与 referent realm 不应相等。** 源审指出 ProcessRealm 的 fd namespace 可引用同 run 的 RunRealm 或 external referent；原相等判断会错拒。root 在 `flow/attempt003/` 实际复现两个正例拒绝（run/external）。最终 `check_endpoint`（`:287`）只独立检查 namespace 在 binding.start 的已知 scope；target 仍由 `check_target_realm`（`:168`、`:482`）检查。External 不授已知 scope，保留 gap；没有从 referent realm 推导 descriptor namespace。
2. **RequirementBinding 本身须检查 owner 点。** 源审指出无 access 时，另一已知 run 的 target 可逃过原仅 access 级检查。root 在同一次 flow/attempt003 实际复现。最终 `:458–466` 对 OperationOccurrence owner 取 BEFORE、RegionActivation owner 取 entry 并检查 target realm；不依赖之后是否存在 access。
3. **coverage 使用预索引。** 最终 `:44–48` 预索引每个静态 operation 的实际 ResourceUse requirement；`:653–657` 仅遍历每个 occurrence 对应项检查缺失。该 coverage pass 为索引加匹配项的线性遍历，不再 occurrence × 全部静态 uses；不据此宣称整个 validator 都是线性。

root 的 `flow/attempt003/output.log` 为 **33 PASS / 4 FAIL**：上述 namespace 两例、owner-run 一例，以及另一个 malformed external graph 崩溃用例。该运行由 root 执行，后一个崩溃不属于本代理发现；不能计入本代理的独立执行。root 随后报告组件门 **302 cases / 14 criteria / 4.575s PASS**，含 142 新增 execution cases；对应 `component/report.md` 存在并绑定上述 fingerprint。本次只读核对，未重复运行。

其余有限 closure：realization、requirement-owner、access 三层均拒绝重复关联；CreatedAt 与明确同 site 的不同 realization target 矛盾为 issue；未知 acquisition identity 仍是 gap。`:316` 的 support 使用 core 当前动态 StateVersion，不从静态 ID 或旧 activation 借版本。`:594–611` 精确原 handle Use，Implicit 不能绕过显式端口。`:627–641` 检查 start/end 与 access 顺序，unknown end 不冒称 live。`:660–670` placement 引用原 allocation 且要求独立 MEMORY_POOL；`:673` constraints 的 current support 与原 requirement tuple index 保留，typed capacity reference 不等于测量结果。

在这些具体范围内没有剩余阻断。没有扩展到新的工作/ready、GPU 同步、native 规则或优化后端。

## 4. 最终读取的逐文件 SHA256

| 文件 | SHA256 |
| --- | --- |
| `tests/fixtures/execution_resource_graphs.py` | `e72ea43784824f7c8f1d72eecd1672f69b99ace49ff5f74eb26d7cea370a05ce` |
| `tests/unit/test_execution_resources_graph.py` | `f073d309147e05e7c283eb61b7bb4e6b5f5a411487dfbe256b25bcabe1a0efea` |
| `scar/ir/execution/resource_validation.py` | `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08` |
| `scar/ir/execution/validation.py` | `2c60deee43107fe0310140fcd9e73a55288a45b7ebebda22b699d238e695cdfa` |
| `scar/ir/execution/flow.py` | `2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501` |
| `scar/ir/execution/resources.py` | `657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000` |
| `scar/ir/execution/model.py` | `f1b9941741f48bcfafc224e50722422450e6a07ef7c606c2422395d2de274411` |

## 5. 证据边界

Observed：规范图及发生图的实际构造、首败、修复后 owned22 输出；root 运行只作明确署名的外部验收记录。
Declared：资源身份、namespace/lifetime、rights/ownership、allocation placement、隐式选择和 constraint 关联的类型与当前 canonical use/state 一致性。
未证 source/runtime：实际对象/OS 资源身份、真实 acquire/close/dup 语义、线程顺序、内容、容量、rights/ownership、native source 对应，以及转换安全。正例仍有 gaps，`source_runtime_verified=False`、`transformation_authorized=False`。host 返回、设备完成、consumer 可见性及 persistence 不由 R1 推出；R2/R3 与完整 M0–M2 仍在本门范围之外。

# D1 driver graph / metadata 实施报告

2026-10-18；按任务基线 `306a789` 协作实施。仅拥有并修改：

- `scar/ir/program/driver_validation.py`
- `tests/fixtures/program_driver_graphs.py`
- `tests/unit/test_program_driver_graph.py`

未改 model/control/core validation/codec/query/docs，未执行 git、full、GPU、采集或安装。
root 提供 core hooks 与 driver_flow；records 及 wire/query 由其他 agent 独立完成。

## 实际交付

`driver_errors(graph, *, operation_blocks, region_domains, incoming_edges)` 返回 error triples，
在 canonical core/C0/C1/C2B 通过后执行；不构建 ProgramIndex、不递归 validate。
采用 root 的 body_drive_target/body_outcome_uses，共享 first-frontier，不建第二图/producer。

检查 raw 构造与边界、Create 全 references/environment/FunctionEntryLayout 及 function
source、normal result projection、async request Create/association、DriverInterface
入口 roles 和 `∅≠L⊆D`、全 incoming 有种子 must-copy、精确 final gate corridor/独立
Use、两 completion 全 D 后态、body state 按 Location、Start/Resume 槽与 first outcomes。
Start 非 state 非 Reference 会报 driver_start_interface；不同 body 的明确本地 Create
来源会报 driver_instance_body。后者仅沿真实 copies 与明确 call actual→entry 保守传播
已知 body 候选；未知外部实例继续合法，多 Create 同 body 继续合法，不证明实际 occurrence。

raw pack 为完整的普通无 callee/term/access 构造：one result、exact ordered operands、
无隐藏 Uses、完整 effects；behaviors 非空且属于 COMPUTE/CONTROL/REPRESENT 子集。
这些 tags 可组合，不引入全局互斥。READ/WRITE/MEMORY/TRANSFER/ORDER 不伪装 pure pack。
外部 entry/opaque NORMAL RAW 边界不强制本地 constructor。

## 有意义正反例

工厂公开为 raw_only_program、create_only_program、driver_program、async_request_program、
multiple_creates_program。driver_program 可选 Start/value/packet、真实 Create 前导、
外部实例、额外状态域、ASYNC_REQUEST receiver、其他既有 validated body CFG。

正例包括 Create→Start→Suspend、两种 Resume→Return/Raise、Create 后不驱动、四种 raw、
真实 request Create→association 两表、两个 Create 私有完成边后分支合流到同 driver、
C1+INVOKE 多 source、混合发散、完全发散空 frontier（不造普通 host normal exit）。
反例包括 raw 多余依赖/读 state/call/错误行为标签、capture/environment/function/result
错接、S 与 fixed receiver 整套替换、session 缺失、插入纯 op、新 owner 结果冒充复制、
gate 旧 state 转发、state location 交换、错误 target/case、Start 缺来源种类、越过
Suspend 的远期 outcome、漏 finite source、已知 Create 与 Drive body 接口矛盾。
这些是手工静态声明测试，不是 source/runtime 或 D2/D3 覆盖率。

## 实跑与原始日志

全部使用 conda lewm Python 3.14、PYTHONPATH=.；只运行拥有的 graph test file 或单项。

- `smoke.initial.log`：首 fixture smoke，ProviderArtifact 缺 schema 与 Reference UseRole
  错误已原样保留；仅修 fixtures。
- `smoke.attempt2.log`：8 个正例全部 validate 0 issues。
- `async-smoke.initial.log`：真实 async-create/association 正例 0 issues。
- `pytest.initial.log`：37 passed / 1 failed；失败是测试未预期 ProgramGraph constructor
  已拒 duplicate metadata，修为显式 pytest.raises，不放宽产品。
- `pytest.attempt2.log`：42 passed，0.62s。
- `raw-behaviors.before-fix.log`：独立 root 复审发现 effect tags 漏检；7 项修前失败。
- `raw-behaviors.after-fix.log`：修复后同7项 passed，0.28s。
- `pytest.final.log`：**52 passed，0.60s**，最终完整 owned file；无后续可选扩测。

## 保留的边界

不新增通用 RequestGate/U-A、permit 或 session 私有 token。final admission 当前关联、
无回调成功语义、原子性、目标与实际 instance 对应仍是版本/来源条件，不从静态 Use/
state/site 授 runtime 证明。raw→packet 语义与 actual callable 对应不靠类型自动证明。
D2 commit/session/release 与 D3 family 全协议仍开放；本门不冒称完整 C2D 或第一阶段完成。

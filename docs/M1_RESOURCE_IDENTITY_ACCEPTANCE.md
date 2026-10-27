# R1 发生与资源身份：自主验收

日期：2026-10-18。**R1 有限接口门通过，第一阶段 M0–M2 未完成。**

规范与实施：[R0 合同](M1_RESOURCE_EXECUTION_CONTRACT.md)、
[R1 类型、端口与公开 API](M1_RESOURCE_IDENTITY_IMPLEMENTATION.md)、
[后续 R2/R3](M1_RESOURCE_EXECUTION_PLAN.md)。

## 1. 实现了什么

**Implemented：** `scar/ir/execution` 连接原 ProgramGraph 的唯一 Operation、
producer、Use、StateAccess 和 CFG，增加有版本 snapshot、run/process/thread
incarnation、activation/segment/visit 及 operation/value/Use occurrence。
资源实例、取得位置、requirement owner、handle lifetime、当前支持和已有
allocation/ObjectID/旧 EEG 的工件内端点均使用强类型引用。

查询能从一次动态 Use 回查原静态定义和 producer occurrence；从 block formal
回查实际 predecessor 的 Use、CompletionResult 或 resume port。JSON 为独立
`scar.execution-model` v1，原 program v14 及 v2 wire 没有变化。

**Verified：** 声明级循环、挂起恢复、正常/异常 completion 和资源组合具有准确
端口、身份与状态连接。验证不授 source/runtime/native 对应或变换权限；
`source_runtime_verified` 和 `transformation_authorized` 始终为 False。

## 2. 实际失败、修正与复审

| 原证据 | Observed | 已实施修正及验收 |
| --- | --- | --- |
| `composition/attempt002`：20 PASS / 2 FAIL | 同 native lifetime 跨 target、已知 UnresolvedHandle.value 错接原 Use 未拒绝。 | 精确 lifetime/namespace/target 与 Use 检查；原反例不变，`attempt003` 22 PASS。 |
| `review/probe*`、`review/state_support*` | ingress/thread point 可跨 process；缺采掩盖后续旧 loop result/state；多 entry root 无对应 gap；非法公开参数可异常外逃。 | 按 scope 和实际 CFG 推导当前定义 visit；缺采仍拒绝明确旧定义，多 root 明确 gap，输入错误形成诊断。INVOKE 无 common AFTER，不能推造 post。 |
| `flow/attempt003`：33 PASS / 4 FAIL | RunRealm/ExternalRealm referent 与 ProcessRealm descriptor namespace 被误要求同型；未使用的 binding 跨 run 未拒；损坏外部 ValueGraph 导致 AttributeError。 | namespace 与 referent 域分别核对；绑定点即检查已知 run；外部形状/编码错误成为 Issue，不能伪装成缺失。最终组件覆盖原反例。 |

**Rejected：** 以静态提供点推 fresh、将所有 acquisition 强制等同首次创建、
以“当前观测缺失”允许已知旧状态、以 namespace 类型相同代替 denotation。
取得同一已有实例的两个 activation 可声明为两个 realization/handle/requirement，
仍只有一个资源实例；准确 owner activation 不因此合并。

两份最终独立限定复审见 `review/closure.md` 与 `composition/report.md`。
它们静态关闭相应问题，不冒称运行了 root 的组件或全仓；全仓由 root 单独执行。
原命令、失败、source hashes 和修正输出全部保留在归档中。

## 3. 组件与冻结全仓

| 项目 | 实测结果 |
| --- | --- |
| 组件门 | `gates/m1_resource_identity.json`：**302 cases / 14 criteria / 4.575s PASS**。 |
| 冻结实现提交 | `6fcac0f778d56d7fe4fdb90e546b23e545f86f96`，运行前后 clean。 |
| 唯一完整回归 | **4,192 PASS / 0 failed / 0 errors / 0 skipped**，3 warnings。 |
| 测试耗时/内存 | 外部 459.327089545317s；pytest 457.37s；max RSS 1,027,068 KiB。是验收成本，不是 workload 性能。 |
| 注册源码 | **472** 文件，前后 SHA `131fa88c62901a016b88778ea975b3a63a6e59497d49740968bd3d49df190e3b`。 |
| 历史保留 | 原 **451** 源文件、**42** fixture 字节不变；原 **4,050** 测试身份全部保留。新增 **142** execution cases、2 个 fixture，总 fixture **44**。 |
| 环境 | `conda activate lewm`，Python 3.14.7；pytest 9.1.1、Torch 2.13.0+cu132、NumPy 2.5.2，未升级环境。 |
| 运行纪律 | 定向检查及复审先完成；clean 冻结后只跑一次全仓，期间没有源码/文档变更或另开测试。独占 basetemp 在子进程结束后删除。 |

归档：[model_resource_identity](../artifacts/experiments/b1_call_operands/model_resource_identity/README.md)。
其 `check_archive.py` 只读核对 manifest、完整原测试身份、每文件 SHA、fixture、
源码冻结和组件映射，不重新启动测试、provider 或 workload。

受保护 checkout：LeWM `f70fed80288462ca4d006cb3607ec6da6eaa851f`；SCAR 主目录
`84f165fce1e2e37617c974ce9fee574ea816406b`，两者状态仍 clean。实现继续保存在
独立 `codex/structured-program-model` worktree/分支。

## 4. 本门不关闭的义务

**Proposed，尚未 Implemented：** R2 typed work/submission/outcome、event-record
generation、Completed/Ordered visibility 和精确 consumer ready；R3 通用
load→consume→save 组合。当前 host CFG 顺序不能证明 GPU 已完成或数据 CPU 可读。

完整 literal、selector/owner/alias、core occurrence→denotation/provenance、剩余
协议家族和 M2 构造守恒仍有工作。手工有限 IR fixtures 是接口反例，不是自动
拆解 LeWM 的结果。没有新增 detector/backend、LeWM profiling、TRANSFORM 或
clean A/B 加速比。M0–M2 全部完成后先按用户要求汇报讲解，再进入自动建图。

# 当前状态

**第一阶段未完成；当前只做自动建模、建图和读回。未进入化简或代码生成。**
LeWM 原仓库未修改；无可用 GPU，当前使用外部 CPU testcase：Sunfish、Gray–Scott、Cirq。
未来后端约定仍为 C++20 / 算子 ABI v1 / 计划 schema v1。

## 按层执行与验收

| 层 | 内容 | 当前结果与下一验收点 |
|---|---|---|
| 1 | F0 源字节 → F1 token → F2 语法 → F3 作用域/编译对应 | 已实现并实测；原源码和完整编译上下文限定身份 |
| 2 | F4 共享局部图：表达式、控制、函数、类、循环 | Cirq 173 单元已生成；正文共享，不按调用/迭代复制 |
| 3 | 实际 CodeID/CALL/回调 → 原源码端口与跨层接口 | 当前主攻；通用小图及注解请求已验，三个CPU案例已按当前合同接线；Cirq 5719 CALL全对应、35请求callback已发布，独立读回中 |
| 4 | 状态与资源接线 | 已有局部 binding/content/effect、native 候选和硬件库存；实际状态/资源关系仍须核对 |
| 5 | 原分片组装、独立读回、入口到输出查询 | 流程已实现；三个 CPU case 尚未全部在当前合同下验收 |

实体为 Operation / Value / StateLocation / Region / Resource；Use、控制端口、观察与契约是强类型辅助记录。
函数与循环可递归展开，调用 Frame 与真实 Invocation 分开。未知字段保条件，不删除已知节点；MAY 依赖不冒充精确参数、别名、版本或纯度证明。
后续严格依次完成：第3层实际调用映射与接口读回 → 第4层状态/资源 → 第5层统一验收。不加 detector、backend 或代码生成。

## 本轮真实进展

- **Verified：** Cirq 按原64文件预算分批准入，形成173单元、172份primitive材料；14份重复快照未重复入图。原681/681捕获CodeID有源码表示；后续独立读回确认689/689代码及35/35请求有正文对应。这不等于依赖已全部接通。
- **Verified：** 该目录的静态调用声明及函数接口已完成，1948.105s、8进程：16,982个静态调用声明，1,281个条件接口、1,266个已接静态调用、5,103条参数路由。未接声明不能直接视为实际运行缺口。
- **Implemented / Verified：** 编译器注解callback用独立记录连到原deferred region，不伪造普通FunctionFact。Cirq一源码单元的14个真实请求已独立读回；原recipe、代码常量路径与源码scope一致。format/创建实例/globals/cells未绑定。
- **Implemented / Verified：** 原生dispatcher可接普通函数、注解请求及可挂起callback的共享正文；请求保原3输入、2返回端口。通用micro的schema4边界独立读回通过；返回连dispatcher，未当成外层结果alias。
- **Implemented / Verified：** 采集支持LOAD_SUPER_ATTR及CALL_FUNCTION_EX。通用micro 21/21实际调用接回原源码，5个融合调用不按函数名选目标；606e62b2合同下的schema4接口及16条双向边经独立读回。参数包/代理分配/native入口仍分别保条件。
- **Rejected：** 将9个中间CodeID全局加入计划使Cirq导入期CALL扩大到62,142，native流触及原64MiB预算。该失败流原样保留，不升预算、不补造完整收据。
- **Implemented / Verified：** `scar refine-capture`从原frame/path及完整源码重放生成按父CodeID＋调用offset限定的补采计划。原4,622 selector保留，新增9个只在所需上下文展开；schema1仍可读，schema2保存路径范围。串行和并发共享CodeType小程序已验证，未选调用保接口，不冒充未执行。
- **Verified：** Cirq路径限定补采100.327s：689代码模板、4,900实际CALL及4,900 native事实，8/8流完整、零丢弃、严格reader零问题；14目标请求全部有直接调用者，数值观察与前次一致。旧规则发布1,010函数接口、695共享边界、203回调（含14请求）；独立检查发现4次多行方法CALL映射缺口，归为一个位置规则，停止剩余已知无法通过的验证。
- **Verified：** lean采集复用collector同步子树屏障。通用micro的SCAR安装子树entry 3295→0，应用对同一inspect函数的两次调用保留，6/6流完整；这是功能证据，非性能基准。
- **Implemented / Verified：** 新规则从原F2属性/调用终点推导末尾片段，通用micro 6/6 CALL通过。真实Cirq受影响单元独立读回113/113 CALL，原缺4次接同一共享原Call及边界，双向查询通过；未重跑应用或重建F4。新全目录叠加正在生成，旧观察报告保持原producer收据，不重签。
- **Observed / Implemented：** 全35请求补采已完成，5719 CALL、689代码、35/35直接caller、8/8流完整、零丢弃，数值观察相同；原4622 selector加10个路径限定selector。已发布35请求/190普通callback，当前独立读回；尚未将发布成功称为整图验证。
- **Observed：** 当前主耗时仍是整文件F4及目录的冷解码。新增观察连接复用静态材料，没有重建F0–F4。已消除每unit三次父接口解码，publisher和独立reader各只读一次，输入分片stat及原收据仍检查；micro五张表除输出URI外完全相等。目录预读/按CodeScope物化仍待改进；不以伪header绕过原材料校验。

已实现 `--source-model` 复用原F0–F3；独立输入收据、当前源SHA和后续F4完整验证均保留。micro13阶段/17.198s通过，原ID未改写。Sunfish/Gray已并行完成新版前端及观察接线（845.957s/1466.756s），没有重跑负载；正在组合当前状态/硬件分片并独立重开。

上述原材料位于 `artifacts/current/experiments/cpu-quantum-current/` 及同级 micro 目录；精简可复核收据汇总在 `artifacts/baseline/formal-frontend-results.json`。

## 已有基线与范围

| 外部程序 | 已测负载 | 建图历史证据 |
|---|---|---|
| Sunfish | 一般程序，7.143s，平均0.996核 | 原77/77代码、2481/2481实际CALL有源码对应 |
| Gray–Scott | 科学计算，512网格/5000步，68.72s单核 | 原38/38代码、88/88实际CALL有对应 |
| Cirq | FP64量子模拟，单核13.475s；8进程50.946s；长档636.085s | 当前主链见上文 |

长档Cirq为22qubits/depth20/12轮/8电路，平均7.74核，最大norm误差1.221e-14。
负载均为单次基准、warmup0，没有workload加速比结论。短采集不能证明长负载全部分支或进程关系。
早期材料保原收据；producer/schema改变后不手工重签，必须按当前合同重验。旧Sunfish/Gray结果不代表本轮整图验收通过。
SCAR自身局部建图缓存改进的中位数27.362s→13.721s（warmup1、3次）仅是建图速度，不能当作应用加速。

`scar build`按原ID组合源码、接口和硬件分片，`BuildSession`复用会话读缓存；硬件库存/资源候选不等于实际placement、分配或复制。
当前硬件库存可表示CPU、DRAM与存储拓扑；本轮9资源/8连接已采集，GPU接口不可用如实保状态，不扩展OS内部FD表或机器指令。
只有当前范围内的入口到输出、跨层依赖及资源分片均经独立读回验收，才将 `first_stage_complete` 设为true。

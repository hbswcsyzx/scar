# 当前状态

三阶段仍在开发，未完成整程序宏观编译器。当前主链已从原F4图降低到显式CPU资源任务图和C++20产物。
建图、模型求解、后端执行各有独立范围；局部通过不代表整阶段完成。LeWM未改，本机无可用GPU。

| 阶段 | 当前可用 | 关键未完成 |
|---|---|---|
| 建图 | F0–F4共享源码图、实际调用/恢复接口、分片查询；原F4直接降低区域并保端口来源 | 调用实例中的内容/状态来源、非纯效果闭合、完整运行资源接线 |
| 硬件化简 | 符号工作量、真实硬件拓扑约束、materialization/ready/生命周期任务图、固定放置资源求解 | 硬件代价模型、跨层结构变换与放置/搬运/融合/调度的联合求解 |
| C++交付 | C++20/ABI1、资源绑定计划schema2、同步CPU三任务链、原生临时CPU绑定/恢复/回退 | 通用多区域执行、buffer池/搬运/异步、完整程序交付；timed计划尚未接执行 |

**Implemented / Verified：图与资源主链**

- `compile-region --catalog`直接读取原F4操作、绑定、输入、返回与源码端口；F0编译仅恢复完整CodeID，不重新用AST选择表达式语义。
- 外部Gray–Scott自动接受1个区域，12节点、189条来源记录，其他10函数明确拒绝；来源记录不算计算节点。
- 原图→CPU资源任务图→C++真实CLI运行94.20秒。任务区分外部已就绪输入、输出分配、compute完成后就绪、导出逃逸；不展开循环。
- C++实际执行计划CPU集合的临时绑定并恢复caller/worker；资源sidecar及hash参与build/load校验，未知任务或附加约束不静默忽略。
- 跨调用world返回修复了compiled-context caller的过时拒绝；局部用例验证两层原状态边接通，不证明内容保持/LogicalVersion或全路径已闭合。

**Implemented / Verified：正向模型求解**

- 主链不编译多个硬件版本做黑盒性能排名。无成本模型时报告`PLANNING_REQUIRED`；固定线程参数仅生成未排名的可行预览。
- `plan-resources`从原计划推导CPU容量/需求、host增量预算池、切片输出shape及字节数；缺成本/预算不补零。
- 求解器覆盖固定放置、非抢占任务、显式duration、资源容量及分配/释放生命周期，返回解、下界、gap与搜索预算状态。
- 只在完整离散模型内声明`OPTIMAL_WITHIN_MODEL`，不声明真实物理最优，不声明已完成联合放置。
- 小图校验包含compute/copy通道重叠、贪心8而模型最优6 ticks，以及8-byte池最优5、16-byte池最优3 ticks；这些是模型例子，非硬件计时。
- 真实区域输入258²沿原slice图推输出256²/524288 bytes；只剩三个任务duration和可用增量内存预算未决。
- 显式示例成本2/7/1 ticks与8MiB预算，经CLI得到10 ticks模型最优；成本标记为示例、未校准，不是实测性能。
- timed后端准入核对同图/同模型/shape、依赖、资源和生命周期；返回必须落实的runtime guards，`execution_linked=false`、`deployment_authorized=false`。

**Verified：执行与验收**

- 原F4主链产物用于完整Gray–Scott：grid256、80步，warmup1、交替配对3次；20步轨迹、最终状态、stdout及PNG字节一致。
- 完整程序median 0.54753→0.52315秒，约1.0466×，节省未达5%验收门槛，保持NO_OP。不是全程序C++，不是LeWM加速。
- 68项针对性检查通过。SCAR以`--no-deps` editable方式装入已有lewm环境，`scar`命令可在仓库外使用；未升级Torch/CUDA。

下一层按依赖推进：
1. 建图：将原控制/效果/状态关系接入实例化call scope，不以同源替代同内容或已就绪。
2. 硬件化简：补有来源的代价参数及层次内存访问模型，再联合决定等价变换、驻留/重算、放置、搬运和执行时序；实测只校准及验收。
3. 后端：先兑现timed准入要求的guards，再扩展多区域、内存与传输任务；不能让后端偷偷改变上层资源计划。

真实产物：`artifacts/current/experiments/compiler-graph-hardware-v1/`；精简收据：`artifacts/baseline/formal-frontend-results.json`。

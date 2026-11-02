# 当前状态

当前唯一任务：整程序纯静态建模与建图。第一阶段未完成；目标程序未执行，LeWM 未修改。唯一 checkout 为 `~/AAA/scar`，分支 `main`。

## 当前首要问题

经代码和三个分工审查交叉核对，局部 canonical 已是 CFG/SSA/状态图，AST 只是解析输入。未贯通的核心原因是：`ProgramIndex` 只导航一份 ProgramGraph；跨主体参数、返回、环境、namespace 和 provider/class 关系分别由专项 loader/solver 解释，尚无统一跨分片依赖接口及一般数据/状态/控制/effects 联合求解。

部分引用和 G/state 关系已经被专项 solver 消费，不能说全部只是显示；同样，专用 reader 能读回这些关系，也不能算所有分析都能穿越主图。class provider 的原端口关系尚未进入通用 callee/effects 工作队列。具体设计与代码事实见 [程序分解 §3.4](PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

当前暂缓继续扩大材料和语法覆盖，优先接通统一逻辑依赖图。物理上仍分片、共享定义，使用原 namespace/ID，不合并成巨型文件或复制 callee。

## 当前已发布产物

`artifacts/current/static/manifest.json` SHA-256：
`a2b922efccbde55853a53fa75a1f3e74349d8af7c30252e84222b7d58b8d9ee3`。

| 项目 | 当前结果 |
|---|---:|
| 源码单位 / 实际文件 | 862 / 862 |
| 原始源码 | 12,447,536 bytes |
| AST occurrence / 词法入口及上下文 | 1,493,620 / 36,164 |
| 源码操作 / 关系 | 835,725 / 3,738,042 |
| CFG 节点 / 边 | 478,899 / 569,425 |
| 有限常量事实 | 124,535 |
| 有规范图的入口 | 8,089，原有主体未因材料扩展重建 |
| 规范操作 | 1,262,346 |
| lowerer / shape 不支持 | 326 / 404 |
| 缺独立适配 / 新单位未派工入口 | 3,731 / 23,614 |
| 当前调用索引 / class 接线索引 | 均未发布到 current |
| 压缩分片 | 14,511 个，2,399,531,667 bytes |

新一轮沿原 import 关系，自动把 264 份外部 Python 源码、16 份 stub 送回原前端，共 280 个正常 units；新源层没有读取或构造失败。阶段记录的 analyzer_seconds 为 207.190 秒，8 个进程；该字段在随后材料刷新前记录，不能当全过程 wall-clock。原 source/canonical 分片没有重建或改写。

`--inventory-dependencies` 定点盘点材料，`--expand-dependencies` 将材料送回现有前端并更新全范围索引。原 import/material 证明输入内容寻址去重，作为当前图的必要依据保留，不保存旧 checkout 或旧 manifest。源码、stub、native 和 namespace 候选以及运行选择条件分别保留，不把找到文件算成已证明实际 import。

扩展后有 42,074 条 import 关系、9,843 个模块查询。本轮材料刷新只处理 4,096 个，5,747 个是明确预算未处理；不能当作不存在。当前仍有 725 份外部源码和 135 份 stub 候选待处理，依赖闭包未完成。材料盘点的 external_source_analyzed=false 描述盘点步骤本身；前端已分析的新增单位另见 dependency_expansion。

当前保留 37 条早期 BrokenProcessPool 的 unit/body-worker 记录；对应样本主体后来已有规范图。这是遗留问题记录，不是本轮 280 份源码新增失败。其终态归属仍需统一，不以 summary 的旧零计数掩盖。

## 本轮代码和实际核验

- **调用点 G/state 投影**：schema v7，跨模块 factory、嵌套 creator、setter 原 payload、多层调用及上下文隔离；成功重算按 demand 原子替换事实和前沿，中断保留旧证据。唯一综合静态案例通过，241.37 秒；临时图有 16 个 CALL、16 条候选边、8 条 globals flow、5 个零 CALL 关系主体。另在新进程读回 7 个 shards，并核对 schema 1–6 迁移和篡改拒绝。lookup、加载及未知 effects 仍有条件；初始化的 G 写及显式 L/G 对应尚未完整，不能宣布状态语义闭合或可优化。
- **module 原 STORE_GLOBAL/LOAD_GLOBAL**：必要临时静态案例通过，FunctionDef、Assign 和 Name 使用原编译 opcode 选择 G，未误写 L；对应 lowerer/validator 一致。没有继续补初始化求解或把 L/G 默认合并。
- **class builder/suite**：有条件 provider 为普通 ProgramGraph，prepared namespace 为实际 prepare 结果，当前 G/saved B/closure 和 suite 的 cell/None 与最终 class 对象分别处理。唯一综合静态测试通过，3.92 秒。真实 CEM 原图接线约 7.08 秒；整范围有界 helper 读 6 个 body，产 3 个绑定及 1 份共享 provider，40.12 秒并通过公开读回。达到 max_bodies=6 后明确未枚举完成，完整 class 分母 2,306；未写 current，未进入通用 solver。
- **依赖材料与前端发布**：两条综合静态测试通过，1.94 秒；验证原指针、版本、namespace 分离、正常 units、原 lowerer 消费、原子发布与公开读回。随后与 class 接线合并复验，3 条通过、4.62 秒。LeWM 原材料上的实际全批发布见上表；新版 current 的公开依赖 reader 已核对 42,074 条原关系及 1,480 份材料。
- **长任务元信息**：调用链接记录单份 static-link-task.json，核对 PID 启动身份；微核查验证运行、最新失败 body、PID 重用和中断。进程消失但未写终态报告 STOPPED_WITHOUT_TERMINAL_RECORD。当前没有新的整范围调用链接任务在后台运行。

上述时间均为分析器或验证时间，不是 LeWM 性能/加速比。检测器、planner 和 backend 当前冻结，不执行目标、trace、profiling、benchmark 或改写。

## 尚需完成

1. 统一 qualified 端点、关系导航及跨主体接口，使一般分析可穿过已有调用、返回、状态和条件实现，而非逐特例解释。
2. 以原节点抽取区域切片，机械列出完整输入、消费者、状态版本、控制/异常/cleanup、逃逸及效果边界。
3. 统一调用、别名、逐地址 reaching writes、effects、常量/类型/Tensor 属性的联合求解与失效；显式处理 module L/G 条件。
4. 补齐原有主体结构：107 项模块后缀、8 项 deferred-child、45 项 class suite 后缀及其余规则缺口；新增依赖主体仍未派工。统一查询层不等于这些结构已完成。
5. 完成按需依赖闭包、库/native 接口及 CPU/GPU/DRAM/HBM/storage/stream 等资源关系。已有 Resource 类型不代表已填实；此前抽查的四份原图资源表仍为空。
6. 对完整范围构建、保存、读回与跨层查询。各预算/未支持/未定字段逐项保留；完成条件不缩小为测试样例通过或目录建完。

完整实施顺序见 [唯一计划](STATIC_ANALYSIS_PLAN.md)。第一阶段结束前不进入化简或优化。

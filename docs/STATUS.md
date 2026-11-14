# 当前状态

第一阶段未完成；当前只做自动建模、建图和读回，未进入化简或代码生成。
LeWM 未修改；本机无可用 GPU。外部 CPU testcase 为 Sunfish、Gray–Scott、Cirq。

| 层 | 已实现 | 当前剩余 |
|---|---|---|
| F0–F3 识别 | 字节、token、语法、字段角色、作用域与编译器构造图 | 新依赖仍须走相同前端 |
| F4 局部图 | 表达式、语句、函数、类、循环、deferred 正文和状态端口 | 共享正文，不按迭代复制 |
| F5 接线 | 实际 CodeID/调用、五类正文入口、完成与条件恢复接口 | 外部源码准入、恢复实例/位置、完整实例覆盖 |
| 状态/资源 | 绑定/内容版本及 CPU、内存、存储、设备的条件接口 | 实际 placement/transfer 不能由库存或源码调用推定 |
| 发布/读回 | 原 ID 分片、按需展开、双向查询 | 入口到输出及状态/资源整体闭合尚未验收 |

实体为 Operation / Value / StateLocation / Region / Resource。

## 本轮进展

- **Implemented：** 代码对应改为沿 C3 编译器构造图匹配；统一处理 12 类来源及 4 类投影。泛型工厂、内部函数/类、lazy evaluator 均保留原作用域、常量路径和入口协议，不伪造普通函数事实。
- **Verified：** 现有语言样例的 15 个编译代码对象全部对应。真实记录的正文进入从 16/30 提高到 23/30：项目内 7 处缺口已消除，剩余 7 次属于未纳入该目录的外部源码。
- **Verified：** 保存后读回 24 个入口/恢复 frame、270 个必需端口及 2362 条双向关系；读回用时 3.98 秒。仍保留上述覆盖缺口，不宣称整图完成。
- **Implemented：** 共享子图由逐节点读取改为依赖闭包批量读取；图读回复用已准入索引，避免重建一遍源码/运行索引。原材料校验和逐端口连接核对保留。
- **Observed：** Sunfish 旧版作业在正文连接阶段被主动中止（该步骤运行 1180.71 秒）；原失败收据和已产出的接口均保留，不改写为通过。
- **Verified：** Sunfish 当前记录的 1856/1856 次进入均有正文对应，未对应进入和来源操作缺口均为 0；127 个共享 activation、83 个正文接口。正文连接 82.21 秒；保存后读回 337 个入口/恢复 frame、4434 个端口、23485 条双向关系，用时 88.82 秒。只覆盖该份采集记录，不代表整个程序所有路径。
- **Implemented / Verified：** 来源选择改为先确认代码作用域再选择最内层操作，消除生成器迭代的 198 处错层定位；不按应用或 opcode 特例派发。
- **Running：** 当前结果接入统一 build，继续核对已有状态、资源及分片发布接口。

命令：`scar body-activations --catalog DIR --trace TRACE --project-root ROOT --out DIR --graph-check-out REPORT.json`。
单独读回：`scar body-activations --read DIR --graph-check --out REPORT.json`。

## 后续顺序

1. 完成 Sunfish 统一 build，报告状态/资源仍未接通的实际缺口。
2. 在同一图接入已有状态/资源接口，核对入口到输出关系。
3. 完成分片发布、读回与覆盖报告后再判定第一阶段完成。

实测收据集中在 artifacts/baseline/formal-frontend-results.json。
此前结果按原 producer 版本保留，不能替代当前版本验收。无新增 detector/backend，无应用加速比结论。

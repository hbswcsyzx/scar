# 当前状态

**第一阶段尚未完成：当前只做程序建模、建图与查询。**
NORMAL_SUCCESS / CPython 3.14.7；软件边界到算子/外部动作接口。后端设计为 C++20、算子 ABI v1、计划 schema v1。
本轮仅执行 SCAR 静态分析器，没有运行 LeWM、导入 torch 或实施程序变换。下面的加速只涉及分析器。

## 已落实

| 层 | 当前范围 |
|---|---|
| F0–F3 | 866份材料，849 .py与17 .pyi分开；原字节、词法/语法、作用域及binding |
| F4 | 按源码单元存储882,537共享模板、3,385,528操作、4,645循环、24,159,357边；函数/循环不按调用或迭代unroll |
| F5 事实 | schema6，22,171代码作用域组；849源的强类型、事实范围及body_scope原ID核对通过 |
| F5 局部接口 | schema1，852单元分片；8,750 iteration、709 deferred body、9,361 mapping模板/1,362 merge协议；沿用原端口和owner |
| F5 接线 | 入口按需激活；参数/捕获环境/world/返回；DIRECT/CLOSED_PACK/SYMBOLIC_PACK；构造协议、属性及同步generator驱动 |
| F5 发布 | source-target schema10；实例字段显式SET RHS→GET result，保原站点、owner、receiver class及may条件 |

原端口及共享body保留；函数引用不是内容版本，may候选不证明运行路径、对象/数据身份或变换合法。
同一源码分配点可返回多类，字段按allocation来源、receiver class和member区分。YIELD_FROM/AWAIT等未完成驱动仍保obligation。
factory依赖可由原inventory独立走前端，再以不可变引用加入852单元facts集合；没有复制已有事实正文或修改基础模型。
已有原生声明/资源旁表保留算子条件候选、CPU/NUMA DRAM/GPU及设备内存/SATA/NVMe关系，不声称实际placement/copy/kernel已发生。

基础模型为 artifacts/current/static/，manifest SHA：
601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0。
原压缩边表575,718,843 bytes，小引用索引231,760 bytes；本轮均未重建。

## 最新实测与证据

以下路径相对 artifacts/current/queries/。

- **Verified：** source-interfaces-full/完整覆盖852单元目录；48个真实worker完成局部接口投影，68.80秒，累计worker CPU 2,431.63秒，摘要正文2,680,976 bytes。每源独立写出；复用原F4收据，没有重跑F1–F4或改变基础facts6。
- **Verified：** source-interfaces-world/verification.json独立核全部48迭代、2body、29mapping/3merge的原F4端口、world、owner及挂起筛选；与旧产物已有的4迭代/1body子集逐项相等。4项针对性源码检查27.88秒通过。
- **Verified：** entry-local-interfaces/为最新完整发布的诊断前缀：274按需加载、2,001活跃scope、9,801调用候选、10,059字段内容边；4M事件后frontier168,070，仍非固定点。interface-equivalence.json核全部17张关系表，与entry-batched-read-write的记录数、压缩及解码SHA完全相等。
- **Observed：** 接线137.67秒，含本次全部局部接口预处理共206.46秒，旧同输入/同4M预算为428.86秒；单次总耗时少约51.9%。并非隔离重复benchmark或LeWM加速比。
- **Verified：** F5接线完整计划解码/恢复、suspension材料发现及模板池均为0；从摘要读取22单元的35迭代、20body、28mapping接口。输入压缩片仍核字节收据。接线约20.98秒入口准备、89.23秒传播、23.55秒主发布；逐表耗时可查result。
- **Observed：** entry-field-content-fixed/diagnostic.json记录一次20M事件试跑：传播1060.66秒、frontier1,113,127；已接通World._get_actions原body26，policy调用仍未接通。因旧逐条发布器在内容表输出超过100MB且未结束，主动中止自己的导出；该目录没有完整result，不能作为完整图收据。

## 剩余瓶颈与后续顺序

1. **局部接口层已验收。** 原scope/fact/port分母完整，按单元并行产出；跨单元接线不再恢复F4正文。后续新增依赖可独立补同类分片，不重建既有图。
2. **下一层：共享状态与内容关系。** 先形式化exact写槽、unknown-write槽、all-values聚合及增量订阅，再替换写×读展开。键存在性独立保存；dict.get默认值仍为本次读取的直接来源，不能当容器写入。copy/参数形状规则保持原准入。
3. **传播与覆盖。** 共享formal/heap仍较粗，协调队列仍单进程。局部约束按稳定ID汇合、按依赖分量推进；预算前缀不能代替固定点或完整程序覆盖。YIELD_FROM/AWAIT等驱动、配置/YAML/_target_、策略/solver及数据/输出/资源映射仍需接通，逻辑内容版本、shape/bytes仍未全面落图。

入口：先 python -m scar.analysis.source_interface_build --facts <facts> --out <interfaces> --jobs 48，
再 python -m scar.analysis.normal_targets --facts <facts> --interfaces <interfaces> --entry <entry.py> --out <fresh-out>。
局部接口池默认min(48, CPU affinity)，本机可用56核；worker只读不可变输入、各写本源分片，协调进程汇总收据。
第一阶段完成前不新增优化backend、不变换LeWM、不报告未经测量的LeWM加速。

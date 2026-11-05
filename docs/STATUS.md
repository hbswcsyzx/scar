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

- **Verified：** entry-batched-read-write/为最新完整发布的诊断前缀：852单元目录、274按需加载、2,001活跃scope、9,801调用候选；4M事件后frontier168,070，仍非固定点，不能称完整建图。
- **Verified：** 与旧同输入/同4M预算的555.74秒相比，本次428.86秒，单次对照约1.30倍。parallel-equivalence.json核对15张共同表实际stored/decoded收据，记录数及decoded SHA全部相等。并非隔离重复benchmark或LeWM加速比。
- **Verified：** 新增10,059条字段内容边；verification.json核25条World源码读取依赖的原读写事实/owner/class，含10个policy写读候选对及跨源码写入。它们不选择状态版本。4项针对性源码检查28.02秒通过。
- **Observed：** F5模板池配置48，实际6个worker、峰值6批并行，298个计划分79批；任务均关闭。全程约20.32秒入口准备、380.43秒传播、24.21秒主发布；逐表耗时已进入result。池wall包含单键调用者任务，不能直接与旧版仅并行池wall比较。
- **Verified：** 当前批量读取真实源码6模板：10.76→1.98秒且typed plans相同；4,000条真实ContentLink写出0.92→0.29秒且压缩字节完全相同。这两项是局部单次测量。每进程仅缓存2份已验单元图；命中仍核原字节/声明/父证明，选中plan及EOF校验保留。
- **Observed：** entry-field-content-fixed/diagnostic.json记录一次20M事件试跑：传播1060.66秒、frontier1,113,127；已接通World._get_actions原body26，policy调用仍未接通。因旧逐条发布器在内容表输出超过100MB且未结束，主动中止自己的导出；该目录没有完整result，不能作为完整图收据。
- **Observed：** source-unit-load-profile.txt仅剖析SCAR读一份真实29MB事实单元：约2.74秒，其中typed decode约2.04秒；不是目标程序profile，也不代表全程占比。

## 剩余瓶颈与后续顺序

1. **先补F4→F5紧凑接口摘要。** F1–F4已有分片和并行入口；F5仍为iteration的world/completion、suspension及DICT_MERGE判据回读完整材料。应在局部事实生成时机械产出原端口摘要，避免求解中恢复整单元；不重新执行目标源码。
2. **再把独立摘要任务跨单元调度。** 现批量读取减少重复，但仍按当前unit同步等待；仅调高jobs无法形成足够任务。以文件/函数生成独立约束，按稳定ID汇合；不能复制整个solver当作并行接线。
3. **收紧共享传播与存图。** 当前formal/heap是较粗may-union，容器内容采用写×读成对边，20M时显著膨胀。下一步设计共享内容接口及增量订阅，避免重复组合，再按依赖分量推进固定点；这仍属建图。
4. **完成真实入口覆盖。** 配置/YAML/_target_来源、策略/solver、数据与权重到输出及资源关系尚未全部贯通；字段/逻辑内容版本、shape/bytes等也未全面落图。达到当前规则固定点不等于第一阶段完成。

入口：python -m scar.analysis.normal_targets --facts <facts> --entry <entry.py> --out <fresh-out> --jobs 48。
F5模板池默认min(48, CPU affinity)，本机可用56核；worker只读不可变材料，所有准入/状态合并仍由协调进程更新。
第一阶段完成前不新增优化backend、不变换LeWM、不报告未经测量的LeWM加速。

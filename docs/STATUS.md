# 当前状态

**第一阶段未完成。当前仅做自动建模、建图和读回，没有进入程序化简或代码生成。**
LeWM 原仓库保持干净；当前无可用 GPU，主 testcase 已切换为外部 CPU 程序。
后端规划仍为 C++20、算子 ABI v1、计划 schema v1。

## 模型与流程

实体仍为 Operation / Value / StateLocation / Region / Resource；控制端口、Use、观察和契约为强类型辅助记录。
函数/循环正文共享，调用与迭代不复制正文；源码、局部依赖、跨层接口、运行证据与硬件库存分别存储并通过原 ID 连接。

已实现的统一入口：源码识别 → 静态子图 → 运行代码选择/跨层连接 → 资源接口 → 分片存储/读回。
`scar build --body-scope observed` 自动准入实际 CodeID 涉及的外部源码文件，保留未选正文的源码声明；不扫描整个 site-packages。
该模式默认跳过全局静态目标固定点，直接连接原 trace 的实际调用；未观察路径保持条件，未证明为死代码。
`--target` 接入独立的 CPU/DRAM/存储库存和拓扑；候选资源不冒充实际 placement、分配或搬运。

## CPU 主测试组：真实运行

| 外部程序 | 内容 | 实测负载 |
|---|---|---|
| Sunfish | 一般程序：国际象棋搜索 | 7.143s，平均 0.996 核 |
| Gray–Scott | 科学计算：512 网格、5000 步反应扩散 | 68.72s，单核配置，最终数组有限 |
| Cirq 1.7.0 | 科学计算：FP64 量子电路模拟 | 单核 13.475s；8 进程 50.946s；长档 636.085s |

Cirq 长档为 22 qubits、depth20、12 轮、8 个独立电路：平均 7.74 核，峰值采样 CPU807.4%，进程 RSS 和峰值约4.83 GiB（共享页可能重复）。
最大 norm 误差1.221e-14，容差1e-9；不保存完整 statevector，不使用 GPU，不以 sleep 凑时。
以上均为单次基准、warmup0，没有加速比结论。完整命令和配置见 `artifacts/baseline/cpu-workloads.json`。
依赖隔离于 `~/AAA/cirq/.scar-runtime`；未升级 LeWM 的 Torch/CUDA。Qulacs 缺匹配 wheel/Boost，保留干净源码及失败收据。

## 本轮建图证据

- **Verified：** 新增通用 `scar frontend`，按F0→F1→F2→F3→F4→调用接口推进，默认23步骤；小样本23/23通过，32.300s；加已有trace后24/24通过，34.495s。Gray–Scott全部2个Python文件的前21步114.024s，生成1315模板/1313连接。离线阶段没有运行目标程序。
- **Verified：** Sunfish两个核心文件的正式F4目录可直接读回，无全局namespace solver。生成器、链式比较、循环均可展开；重复展开保持同一ID与节点/边数，循环不unroll。三项查询12.884s。
- **Verified：** 当前同一目录接入385个静态调用、52个条件函数接口及110个共享外部CALL边界；完整build/保存/入口读回170.461s，接入1份Python观察接口和1份边界材料。三类边界的get/expand、参数/state/结果边及native字段读回31.978s通过。9个硬件实体/8条连接的读回已验；第一阶段仍未闭合。
- **Verified：** 对同一原trace补Lambda对应，code links从22到27，缺正文目标从107到23；按实际CALL区间接已有raw frame，缺立即entry从111到51。60次方法调用已有正文entry，receiver/参数身份仍未决，不保留用户对象或猜地址；剩余51次为生成器创建，不能当立即执行。
- **Verified：** 原生探针新采集5.415s，返回同一bestmove。1354次本地类型/原生/未分类调用归并为110个共享CALL接口，事件另表；763份已识别method carrier，591份carrier未知。参数/world/结果保原端口与条件，未宣布内部实现或effects闭合。
- **Verified：** 采集器按callback代码和私有owner识别自身清理，不按模块名排除；新Sunfish capture从4442降至3712事件，返回相同bestmove。原链式赋值现保RHS单次求值与有序store；3项局部检查及8项既有资源/build检查通过。
- **Verified：** 修复赋值目标切片中缺失的一元运算恢复。真实 `array[1:-1]` 对应函数由 UNSUPPORTED 变为225操作的可读正文；保 operand/world、动态重载及正常/异常接口，不做常量折叠。
- **Verified：** Gray–Scott 接图/保存/读回通过，85 scopes、32 Python interfaces、248 observed edges；仍有前沿，流程通过不代表完整建图通过。
- **Verified：** 正文适配复用既有有限 LRU；64个binding批内接callee，共享一次原trace索引。Gray 完整导出 SHA256 与旧实现完全一致。
- **Observed：** Gray 离线 admission 单次16.229s→10.405s；这是SCAR自身接图耗时，不是目标程序加速。
- **Observed：** FEM 原实现300s超时；批内接图在相同预算283.838s返回665 scopes、99 interfaces、1261 edges，仍有1109 issues/1280 frontiers。
- **Observed：** 新小窗口采集：Sunfish4442事件/78代码、Cirq10450事件/682代码，均无预算丢弃及I/O错误；Cirq仍有99个unknown exit，不能声称执行证据已闭合。
- **Implemented：** 外部源码按运行Code描述符和完整源码/编译身份匹配；源码文件精确准入，不递归扫描其安装目录。8项既有资源/入口检查通过；另有实际精确文件准入检查。
- **Rejected：** 两次过大的Sunfish采集及一次重型算子采集未通过完整性要求。失败摘要保留，2.49GB无用原始中间文件已清理；未作为通过的证据。

正常负载与建图采集使用不同规模：Sunfish采小残局，Gray采短时间段，Cirq采3 qubits/1 worker。短窗口不能证明长基准全部分支或进程关系。
统一构图/存储/读回现均已完成；全部 observed_admission=ADMITTED，但 first_stage_complete=false：

| 图 | 源码单元 | 观察调用域/边 | 总构建秒数 |
|---|---:|---:|---:|
| Sunfish graph | 13 | 187/330 | 79.78 |
| Gray–Scott automatic | 10 | 85/428 | 337.37 |
| Cirq graph | 169 | 2524/6730 | 792.02 |
| FEM verified（辅助回归） | 149 | 665/1261 | 279.01 |

这里ADMITTED只表示原采集通过准入并接入了部分接口，不表示所有CALL都已绑定。Sunfish仍有2294条、Cirq仍有1818条OBSERVED_CALL_UNBOUND（逐事件记录，尚须按原代码/位置归并）。
Gray旧的2文件小图与新的10文件自动依赖图范围不同，不能把17.4s/337.37s直接算作性能退化倍率。
原材料在 `artifacts/current/experiments/cpu-*-current/`；精简可复核结果见 `artifacts/baseline/cpu-graph-results.json`。
旧LeWM完整trace和F4材料保留，历史细节由Git记录。

## 接下来只推进第一阶段

1. 固定正式前端顺序；将现有CPU case逐一接到同一局部目录/动态接口路线，避免退回旧正文适配器。
2. 在现有CALL边界上细化真实构造阶段/native ABI与receiver字段；接通生成器创建/恢复，再接线程/多进程交接。正文entry与receiver身份分开，不再因单字段未知丢弃已知结构。
3. 接通软件端口与真实资源事件，最后验收入口→输出依赖和分片读回；库存或条件候选不能代替实际使用证据。

首要性能瓶颈是完整canonical正文和SemanticGraph的冷解码：FEM正文decoded约439MB。并行源码/正文构建已可用，接图的材料读取仍主要串行；不靠反复加budget宣称完成。
只有入口到输出及跨层/资源依赖验收通过，才将 first_stage_complete 设为true。

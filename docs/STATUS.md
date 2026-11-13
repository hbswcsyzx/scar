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

- **Verified：** 通用 `scar frontend` 按F0→F1→F2→F3→F4→调用接口推进：纯静态23步、已有trace24步；有编译audit时自动补匹配与生成代码局部图，共26步。当前小样本26/26通过，52.219s；同filename不同代码、延后执行旧code与失败compile分别保存。离线阶段不运行目标。Gray–Scott全部2个Python文件的前21步114.024s，1315模板/1313连接。
- **Verified：** CodeScope连接已区分CODE_ROOT/CLASS_BODY与函数binder。当前Sunfish采集77/77代码模板有源码对应、455/455回调有正文，3个类体的事件/展开检查通过；18单元共2936个局部CALL声明，观察函数接口141个。外部11文件368,193B由8个实际进程降低，287.791s，未执行目标源码；定向读回144.638s。自动前端29/29步通过，后续目录收据变更以复用材料的当前尾链验证。仍有123个CALL位置前沿，first_stage_complete=false。
- **Verified：** 接口层已区分declaration_units与importable_units（CALL声明schema v2）。7单元全部647个局部CALL有原分片，callers_without_parent归零；生成代码32迭代/7可挂起正文/7mapping、2merge/7suspension全部读回。仅解码25/2978份计划，未重建F4。定向验收74.646s，整体build/保存/入口读回228.654s；自动前端26/26步通过，56.002s。
- **Verified：** Sunfish新采集5.858s，保存12份编译文本共68,545B；完整CodeID匹配保48个兼容配方，不推断原编译选项或namespace。实际frame对应5个生成代码局部图，186.443s、文件合计4.62MB；与2个原文件图合并为7单元。5份材料复用后仅重建目录6.970s，读回也守原audit证据。 当前整体build/保存/入口读回216.255s通过；455个回调帧中451个有源码body，新增3个lambda正文通过8个共享回调接口接回267帧，无正文复制。定向读回112.042s通过，58个代码连接，重复展开及调用上下文正反检查通过。此轮当时尚缺4个外部源码回调和1个动态caller接口；后者现已解决，first_stage_complete仍为false。
- **Verified：** Sunfish两个核心文件的正式F4目录可直接读回，无全局namespace solver。生成器、链式比较、循环均可展开；重复展开保持同一ID与节点/边数，循环不unroll。三项查询12.884s。
- **Verified：** 当前同一目录接入385个静态调用、55个条件函数接口及117个共享CALL边界；完整build/保存/入口读回177.415s。425个回调帧归并为18个共享接口，其中154帧对应7个源码body接口；普通frame匹配、可挂起body仅结构接线、缺源码保CodeID及重复展开检查33.192s通过。9个硬件实体/8条连接的读回已验；第一阶段仍未闭合。
- **Verified：** 对同一原trace补Lambda对应，code links从22到27，缺正文目标从107到23；按实际CALL区间接已有raw frame，缺立即entry从111到51。60次方法调用已有正文entry，receiver/参数身份仍未决，不保留用户对象或猜地址；剩余51次为生成器创建，不能当立即执行。
- **Verified：** 原生探针新采集5.415s，返回同一bestmove。1354次本地类型/原生/未分类调用归并为110个共享CALL接口，事件另表；763份已识别method carrier，591份carrier未知。参数/world/结果保原端口与条件，未宣布内部实现或effects闭合。
- **Verified：** 本轮再补11个实际GeneratorExp代码模板，code links达38；既有153个本地可挂起回调帧全部对应源码。新识别了genexpr内部CALL，边界观察由1354增至1880、共享边界110增至117；这是覆盖范围增加，没有展开迭代。
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

1. 源码作用域缺口已从33降至0；下一步按实际opcode与原F4操作审计123个CALL位置映射前沿，补隐式语言调用接口，不能用77/77源码对应代替跨层依赖完整。
2. 保留原生ABI、生成器实例/恢复、线程/进程交接和状态/存储来源的未决字段；继续接通实际资源事件。目录增量必须保留各批源码证据，当前18单元、两个独立reader的增量读回已通过。
3. 将CPU三个case走同一正式前端/动态图路线，验收入口→输出、资源依赖及分片读回。库存、结构连接与条件候选均不代替实际执行或物理使用证据。

首要性能瓶颈是完整canonical正文和SemanticGraph的冷解码：FEM正文decoded约439MB。并行源码/正文构建已可用，接图的材料读取仍主要串行；不靠反复加budget宣称完成。
只有入口到输出及跨层/资源依赖验收通过，才将 first_stage_complete 设为true。

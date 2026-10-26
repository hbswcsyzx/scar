# 第一阶段还缺什么：完整跨层图的验收差距

2026-10-26。**OPEN。当前不能声称已完成 LeWM 全程序、全部软硬件资源的建图。**
本页按现有[验收合同](FIRST_STAGE_MODEL_CONTRACT.md)列缺口，不改变其分母或降低要求。

2026-10-26用户明确修订：建模服务于化简，以[范围审计](MODELING_SCOPE_AUDIT.md)的
最小充分依赖为准。完整Linux FD表、内核/驱动/解释器内部实现不作为必需展开项；
程序侧操作与必要状态/资源依赖仍须接通。以下历史细化缺口不自动成为开发任务。

## 三种状态分别回答

- **模型设计：**已有 Operation、Value、StateLocation、Region、Resource 及版本、
  控制/完成、别名、物化、效果和证据接口。输入/输出是端口角色，行为是多标签。
- **自动恢复：**已有静态分析和真实 trace 的自动处理，但源内部、调用、数据和资源
  的恢复范围不同，未全部覆盖。给缺项命名不是补齐该缺项。
- **完整跨层图：**尚未闭合。调用树、Tensor 引用图、事件清单、源码上下文关系，
  各自只能说明一部分，不能相加宣称整个程序已恢复。

## 必需关系与当前差距

| 必需部分 | 当前已有的实际结果 | 尚缺与验收条件 |
|---|---|---|
| 源码与依赖内部 | 正式原快照151文件/2217定义/858规范body。外部243候选归并为201成功、41未支持、1 resumable入口缺适配；其中196项已普通发布（原161+35增量），后补解包/Lambda/推导式/generator/starred display五项尚未发布。V7补通heap/cell解包；V8随后完整恢复另一Lambda入口（187 ops、子Region17 ops），结构与独立source/CodeWitness读回通过。 | 剩余语法及嵌套cleanup/驱动继续补实现；新增body须正常准入并接回相应运行。源恢复成功、普通发布、当前运行绑定分别计数。 |
| 层层函数调用 | 原完整100438调用均入账，6882次对应92个body groups；另88592 source-only、4964 unresolved。已有2516调用/6805条件参数端口；新CLI已在一条真实LeWM调用上连接callee正常返回Use→caller结果，并接入入口world和正常/异常post-world。 | 这些是原端点上的条件源关系，不据此断定实际选边、状态保持或细粒度写范围；捕获/全局状态及其余实际调用仍需连接。深层region不可用祖先上下文替代直接调用。 |
| 值、对象与可变内容 | 有引用、storage/allocation及view的真实记录和类型接口。 | 逻辑来源/值版本→物理副本、原位写入后态、alias范围和失效须接通。不能以相同ObjectID/StorageID/shape/样本或来源证明内容未变；采样仅用于排除。 |
| Python→Torch→GPU工作 | main新门72613实际exit0：24082物理work均有retained source context/code来源；11541 exact、12541 enclosing，6普通查询通过。 | enclosing仅为提交scope嵌套；内部host exact occurrence仍缺12541，static body member未核14932，state/content/ready均未证24082。不能当作每个kernel的完整源数据流。 |
| OS、存储与进程 | 原始接口及部分规范投影已在；新Run有34项registration backing条件连接。 | 程序侧文件/内容/range→buffer→反序列化、子进程/pipe/输出及完成关系仍需表达；优先上层接口摘要。完整共享FD表回放已移出必需任务，路径或FD数字仍不作数据身份。 |
| 设备、内存与异步顺序 | GPU/kernel/copy/memset、部分allocation/region/stream/provider actor已有事实；24082活动有单activity结束关系。 | allocation生命周期、读写range/版本、跨队列event/wait、consumer可见性及value ready须有证据。host返回、activity结束、同步调用三者不能混用。 |
| 采集时软件/资源身份 | 有固定provider源码合同与版本标签；新的collector注册见证已在独立样例验证。 | 历史LeWM缺失的信息不可事后补认。下一同Run需保实际callback代码、issuer/process incarnation、已加载映像及ordinary成员链；驱动/ABI/build对应和未采内容保明确边界。 |
| 加载到保存的整体依赖 | 已有实际完成的LeWM episode和输出文件；若干层已有独立图。 | 必须串起模型/数据加载→CPU处理→H2D/推理→action/环境→render→编码/pipe→文件保存，逐层能查询输入、状态、结果、资源与失败/完成。产物存在不能代替这些边。 |

资源逐项原审计见[资源覆盖报告](../artifacts/analysis/lewm_resource_coverage_20261026/REPORT.md)。
该审计写入时v2仍在运行，里面对应行保留历史状态；最新24082关系结果以
[主树实际报告](../artifacts/experiments/fragment_relations_v2_main_20261026/REPORT.md)为准。

“底层硬件”按既定合同包括程序实际可分配、调度、访问和等待的接口资源：CPU/GPU、
进程/线程、内存与allocation、queue/stream/event、storage/file等。SM/cache/控制器、
内核driver/firmware等内部实现不属于默认核心展开范围；保必要接口、资源属性及
按需证据，不宣称已恢复其内部，也不将必要的程序依赖改标为可忽略细节。

## 当前实施顺序与自身验收

按[FIRST_STAGE_IMPLEMENTATION_PLAN.md](FIRST_STAGE_IMPLEMENTATION_PLAN.md)四项功能推进：

1. 补剩余通用source结构；243项现为201成功、41未支持、1resumable缺口，196已
   正常发布，后补五项继续接回原命名空间。历史调用权重不计新运行绑定。
2. 接有序数据/状态依赖；已有条件参数、正常返回及粗world传递，接着补native端口
   引用流、逻辑来源/版本、必要资源与IO接口，不用引用相同代替内容不变。
3. 收敛存取及采集；共享source context、独立片段和局部索引接正常入口，复用已存
   事实。小型GPU+OS+lean联合入口已通过，完整LeWM重采尚未执行；避免重复episode。
4. 查询完整加载→处理→推理/规划→交互→保存链；缺必要边仍OPEN。采集器注册/ABI等
   是来源附着，不成为目标程序操作；不展开FD表、driver或其他不可调整组件内部。

当前不增加detector/backend，不修改LeWM，不进行优化或报告加速比。第一阶段完成后
先交付整个程序分解和可查询图的讲解，再进入后续化简。

# 第一阶段还缺什么：完整跨层图的验收差距

2026-10-26。**OPEN。当前不能声称已完成 LeWM 全程序、全部软硬件资源的建图。**
本页按现有[验收合同](FIRST_STAGE_MODEL_CONTRACT.md)列缺口，不改变其分母或降低要求。

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
| 源码与依赖内部 | 正式静态快照151文件/2217定义/858规范body；769 unsupported、590 not attempted分别保留。外部完整243候选当前161成功、81不支持、1 resumable入口缺适配；161项普通接入尚未终态。 | 支持的结构须自动恢复有序输入/结果、分支/循环、名称与环境、失败/cleanup；不支持的部分不能按AST外壳算已展开。新增body须正常准入并接回相应运行。 |
| 层层函数调用 | 原完整100438调用均入账，6882次对应92个body groups；另88592 source-only、4964 unresolved。 | 对应函数体不等于传递已闭合。须连接源实参Use→正式端口、返回载荷→调用结果、闭包/全局状态和准确调用/完成。深层region不可用祖先上下文替代直接调用。 |
| 值、对象与可变内容 | 有引用、storage/allocation及view的真实记录和类型接口。 | 逻辑来源/值版本→物理副本、原位写入后态、alias范围和失效须接通。不能以相同ObjectID/StorageID/shape/样本或来源证明内容未变；采样仅用于排除。 |
| Python→Torch→GPU工作 | main新门72613实际exit0：24082物理work均有retained source context/code来源；11541 exact、12541 enclosing，6普通查询通过。 | enclosing仅为提交scope嵌套；内部host exact occurrence仍缺12541，static body member未核14932，state/content/ready均未证24082。不能当作每个kernel的完整源数据流。 |
| OS、存储与进程 | 旧Run有大量read/pread/mmap、FD selector、exec/pipe/wait等原始接口及部分规范投影。 | 精确文件身份/内容版本/range→实际buffer→反序列化输出，FD/OFD与namespace生命周期、子进程/pipe/输出文件依赖仍需接通。路径、FD数字或进程退出不够。 |
| 设备、内存与异步顺序 | GPU/kernel/copy/memset、部分allocation/region/stream/provider actor已有事实；24082活动有单activity结束关系。 | allocation生命周期、读写range/版本、跨队列event/wait、consumer可见性及value ready须有证据。host返回、activity结束、同步调用三者不能混用。 |
| 采集时软件/资源身份 | 有固定provider源码合同与版本标签；新的collector注册见证已在独立样例验证。 | 历史LeWM缺失的信息不可事后补认。下一同Run需保实际callback代码、issuer/process incarnation、已加载映像及ordinary成员链；驱动/ABI/build对应和未采内容保明确边界。 |
| 加载到保存的整体依赖 | 已有实际完成的LeWM episode和输出文件；若干层已有独立图。 | 必须串起模型/数据加载→CPU处理→H2D/推理→action/环境→render→编码/pipe→文件保存，逐层能查询输入、状态、结果、资源与失败/完成。产物存在不能代替这些边。 |

资源逐项原审计见[资源覆盖报告](../artifacts/analysis/lewm_resource_coverage_20261026/REPORT.md)。
该审计写入时v2仍在运行，里面对应行保留历史状态；最新24082关系结果以
[主树实际报告](../artifacts/experiments/fragment_relations_v2_main_20261026/REPORT.md)为准。

“底层硬件”按既定合同包括程序实际可分配、调度、访问和等待的接口资源：CPU/GPU、
进程/线程、内存与allocation、queue/stream/event、storage/file等。SM/cache/控制器、
内核driver/firmware等内部细化未自动恢复，必须显式列出，不能宣称已完成其内部建图。
这不允许把缺少的必要接口依赖改标为可忽略物理细节。

## 当前实施顺序与自身验收

1. 保存并版本化已通过的完整24082关系和调用问题漏斗，不重复运行相同已通过范围。
2. 将完整243候选中161个成功入口正常接入，保81不支持及1 resumable缺口；函数Try
   原20入口已完成，继续按剩余实际语法缺口恢复，不为库名写分支。历史调用权重不计新运行绑定。
3. 实现源调用端口绑定，将语言的数据传递与捕获引用身份分开；复用原Use/Value/
   CandidateBinding/formal端口及真实dispatch/entry。保旧窄引用规则，不造动态值身份。
4. 补齐下一唯一联合LeWM采集需要的process/image/成员链字段；已有可离线连接的
   事实先离线接，不因添加一个字段反复跑episode。
5. 联合采集和正常消费者之后，按本表逐项检查完整分母和跨层端点。任何必需关系
   OPEN，第一阶段就继续OPEN；不以组件测试、源码行分类或某一层100%替代。

当前不增加detector/backend，不修改LeWM，不进行优化或报告加速比。第一阶段完成后
先交付整个程序分解和可查询图的讲解，再进入后续化简。

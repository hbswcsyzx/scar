# 建模现状、工具分工与实施边界

2026-10-16。审查基线 `78c5fda`，分支 `codex/structured-program-model`。
原工具审查是只读代码审计、官方资料复核和设计收束；没有新增采集、adapter、
detector 或 backend。2026-10-17/18 更新下面的 C1/C2B 实施状态；既有工具小实验保持
各自的版本与范围，不冒充本轮实测。

## 1. 当前完成了什么

| 层次 | 当前事实 | 不能据此声称 |
| --- | --- | --- |
| 模型规格 | 五类实体、分层表示、身份/状态/完成规则已有文档。 | 整个程序已自动建模。 |
| 机器接口 | 现有 `ir/program` 已有有序 Uses、producer、CFG、状态 SSA、资源/环境/控制接口，以及 provider 来源和薄边界声明。 | 新声明已由实际 FX/Export/ETO 自动产生。 |
| 执行采集 | 已调用 `torch.profiler`/Kineto、Python profiling/monitoring 和部分 Torch wrappers。 | 事件自动形成完整跨函数的数据依赖。 |
| 自动建图 | 已有有限同步 source lowering 与历史 LeWM 证据。 | 加载→推理→环境交互→保存全过程已连接。 |
| 化简结果 | 尚无可信的 LeWM 自动变换及 clean A/B 加速比。 | 测试数量等于模型覆盖率或加速效果。 |

当前 [D2.2 no-body](M1_NO_BODY_ACCEPTANCE.md) 的836组件及冻结 `006a0e0` 的
3,871项全仓通过；仅声明层的bool分支/精确owner/当前状态连接，不授runtime权限。
[D2.3](M1_SESSION_RELEASE_ACCEPTANCE.md)974组件及冻结`f67037d`的4,009全仓也已通过，
接通声明内历史终态/alias和当前session谓词的路径派生。后续[D2.4组合](M1_LIFECYCLE_COMPOSITION_ACCEPTANCE.md)
也已验收；[C2/D3审计](M1_PROTOCOL_FAMILY_AUDIT.md)定位协议到原CFG/端口义务与
实际Drive到持续body执行段/首出口的关联缺口。D3精确字段与完整第一阶段仍未
关闭；实际provider/runtime导入和新LeWM优化没有因此完成。

此前冻结实现 `e6b4723` 的3,542项回归通过，见
[C2B body验收](M1_RESUMPTION_BODY_ACCEPTANCE.md)；499项组件及403个源文件指纹匹配。
此前`0ea05e6`的3,330项原始回归保持[C1证据](../artifacts/experiments/b1_call_operands/model_cleanup_interfaces/full/report.json)范围。
[C1 cleanup/context](M1_CLEANUP_INTERFACES.md) 的六表、v9、栈/路由及 copy/fresh
组合校验已实施，243项组件检查通过。这是声明 IR 的回归结果，不是自动 source
恢复或实际异常上下文证明，也不关闭第一阶段。

## 2. 如何拆分：实体、行为、连接分别定义

### 2.1 五类基础实体

下表是核心设计的职责划分；owner/selector、动态资源和逻辑值对应等尚未全部
落地，具体差距仍按完整性矩阵验收。

| 实体 | 含义 | 例子 |
| --- | --- | --- |
| Operation | 一处操作定义；消费有序输入，产生结果，并声明状态、控制、资源接口。 | 调用、索引、加法、读文件、enqueue、write、close。 |
| Value | 一次定义的结果或区域参数；数据、对象引用、绑定、状态版本和协议值分别有类型。 | 图像数据、Tensor 引用、当前 buffer 状态、返回载荷。 |
| StateLocation | 可以变化的位置或状态域；具有 owner、selector 和覆盖/重叠关系。 | 对象字段、Tensor 内容、RNG、环境实例、文件 offset。 |
| Region | 有入口/出口和内部结构的区域；可递归包含/调用其他区域。 | 函数、循环体、一次导出的 Tensor 子图、pipeline stage。 |
| Resource | 执行或承载的身份；状态与具体生命周期另记。 | GPU、stream、allocation 所属内存资源、文件资源。 |

这不是“所有程序只有五种行为”。输入/输出是端口角色；计算、表示变化、
分配/释放、搬运、读写、控制、等待和外部交互是操作的多标签行为。一个操作可
同时有多种行为。保存视频和保存 Tensor 都可分解为数据变换与文件协议，不按
业务名称增加互斥类型。Q 和 M 是合同与证据记录，不塞进上述五类数据实体。

### 2.2 图的连接规则

- **数据使用：** producer/区域参数 → Value → 有序 Use → consumer。`f(x,x)` 有
  两个 Use，不能只保留一条去重后的 parent 边。
- **状态：** 操作读取当前 location/version；写产生后态。引用传递与内容读取分开，
  不能把同一 Tensor 对象当成恒定数据。
- **控制与完成：** 分支/循环/调用/返回/异常及逐边参数；挂起恢复和 cleanup 保留
  各自协议。返回到 host 和 GPU 完成分开。
- **别名与物化：** 引用/视图到 allocation 生命周期和 storage region；逻辑数据
  版本到物理副本、表示、有效区间和 ready 条件。相同来源不自动证明相等。
- **包含与实现：** Region 展开到内部操作；静态定义对应动态 occurrence，动态
  occurrence 再对应 kernel/copy/wait。对应可以多对多，需要具体依据。

用户看到的主图可以是“操作节点＋数据边＋可展开区域”。上述其他关系按需要
叠加显示；分析保留完整关系。每个表示内部的 producer/use/state 只有一个规范
来源，不能为了显示再维护一套可修改的依赖图。

## 3. 复用哪些工具

工具详细能力、版本与既有实验见 [调研](TOOLING_SURVEY.md)。本次决定如下：

| 工作 | 优先来源 | SCAR 补充的关系 |
| --- | --- | --- |
| 源语法、作用域和 code 定位 | 标准库 ast/symtable/dis；LibCST 可补定位与源码结构。 | 将源位置绑定到版本化操作/区域和协议；AST 不直接冒充执行 CFG。 |
| Python CFG 与跨过程 flow | 对照评估 CodeQL，而非继续默认全靠自建 lowerer。 | 按当前 Python 版本核验结果、关联状态/完成端口；不将 flow 当优化证明。 |
| Tensor 计算子图 | FX；可导出区域复用 Export 的 ATen 图、signature、constraints 和原生 TreeSpec。 | 入口环境/当前参数状态、mutation 写回、graph break 的外壳连接及适用合同。 |
| 实际 operator、kernel、copy、wait | 已有 profiler/Kineto；优先接 ETO 的机器可读动态关系。 | 同 run/window 的身份对应、实际有序 use、逻辑版本/物化和异步可见性。 |
| eager 图辅助与展示 | torchview；TorchLens 作为动态 provider 候选；torchviz 补 autograd 关系。 | 不从展示边或梯度图推断整个程序的效果完整性。 |
| SSA/Region 与通用图基础 | MLIR/xDSL 的既有结构、接口、校验/遍历；NetworkX 作明确投影上的算法对照。 | SCAR 的状态、证据和跨层合同；框架迁移本身不是模型完成。 |

**不以“其他工具粒度粗”作为自制理由。** torchview 已能表示 Torch functions、
中间 Tensor 和嵌套结构；FX 可到 ATen，profiler 可到 kernel。SCAR 的待补部分
主要是跨层连接与可化简所需的依赖精度，不是把每层再次记录一遍。

官方依据：
[FX](https://docs.pytorch.org/docs/stable/fx.html)、
[Export](https://docs.pytorch.org/docs/stable/export.html)、
[Profiler/ETO](https://docs.pytorch.org/docs/stable/profiler.html)、
[torchview](https://github.com/mert-kurttutan/torchview)、
[CodeQL CFG](https://codeql.github.com/docs/codeql-language-guides/analyzing-control-flow-in-python/)、
[CodeQL flow](https://codeql.github.com/docs/codeql-language-guides/analyzing-data-flow-in-python/)、
[LibCST metadata](https://libcst.readthedocs.io/en/latest/metadata.html)、
[MLIR IR](https://mlir.llvm.org/docs/LangRef/)、
[MLIR effects/speculation](https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/)、
[xDSL core](https://docs.xdsl.dev/reference/ir/core/)。
在线资料可能比本机 Torch 新；能力采用仍需本机对应源码/小实验支持。

## 4. 三种表示保持分工

```text
程序定义图：源码外壳 + 原生 Tensor 子区域 + 带类型的状态/控制/资源接口
                      │ 版本、端口与适用范围对应
执行证据图：调用 occurrence + operator + kernel/copy/wait + 实际状态/资源观察
                      │ 依赖及证据闭合后引用
优化表示：区域边界 + 必要依赖 + 替换/上移/删除建议 + 义务 + 成本 + 验证计划
```

一次观察到的路径不替代程序定义中的其他分支；同一次融合也不要求一个 source
node 对一个 kernel。优化表示引用前两者，不复制另一套可冲突的 producer/use。

## 5. 模型必须能说明的通用全过程

以下是设计检验，不是已经自动生成的 LeWM 图：

```text
文件读 → deserialize → 参数对象/内容状态
输入读 → normalize → CPU 数据 → H2D 物化 → GPU 数据
                                  参数/模式/必要状态 ─┐
GPU 数据 ───────────────────────────────→ encode → embedding
embedding / 可变候选 / RNG → rollout / update → action
action + 当前环境状态 → step → 新观察 + 新环境状态
图像序列 + 编码器状态 → 编码 → 文件 write / flush / close
```

每一步都要保留实际读写、失败出口和所需顺序。H2D 的入队、物理 copy 与 consumer
可见性分别连接；不能为画成直线而额外要求 CPU 同步。相同逻辑数据可有多个
物理副本；同一 buffer 原位改写后必须是新状态/数据版本。

对多层传参，沿真实 Use/绑定追到输入、环境和所读状态的来源，再在父级 Region
检查最早合法位置。仅知道一个参数来自第 3 层，还不足以把第 8 层整个区域上移：
其他状态、控制、异常和资源依赖也必须在新位置满足。目标是逐项解决这些依赖，
不能用一个笼统 UNKNOWN 代替追溯。

## 6. 下一步顺序及自验收

1. **完成模型接口与协议分母。** 按[完整性矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)
   关闭 cleanup/resume、owner/selector/literal、资源 work/ready 和
   occurrence/denotation 的组合缺口。每项写清事实来源，不要求先写完整 Python
   编译器或所有库内部。先复用已有协议/原生 artifact，再补跨边界合同。
2. **先停下来讲解第一阶段。** 交付实体/行为/边的含义、全过程分解、反例和剩余
   精度边界。类型可表达、自动恢复、证据接通、化简合法性分别验收。
3. **后续建图再做最小导入闭环。** 自动导入一个通用 FX/Export 子区及同运行
   ETO+Profiler，连接 Python 外壳。用重复实参、原位/out 写、view、RNG、异常和
   graph break 检查是否错接；采集成本/截断单列。不扩大平行 Tensor tracer。
4. **最后以外部 LeWM 压力验证。** 同样入口自动分解加载至保存；不手工指定业务
   节点或 pure/constant 名单。完成依赖闭合后才生成具体化简指导和测量盈利性。

本轮发现的 collector 风险另见[工具审查 §6](TOOLING_SURVEY.md#6-当前代码复核与下一步复用约束)：名字后缀猜写不能
当可靠的状态版本依据。先用原生 schema/记录提供写集合，缺失关系定位到具体域；
不靠保存 Tensor 全量数值来补协议缺口。采样只作排除，不证明恒定。

MLIR/xDSL 的采用仍是有条件的工程决定：继续增加通用 SSA/遍历/重写基础设施前，
必须先对照已有能力和旧 wire/查询的无损适配。它们不自带 Python 全程序前端，
也不能因此被排除为复用对象。本轮未安装或试迁移，不声称对照已通过。

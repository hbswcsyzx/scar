# 当前模型只读审计

2026-10-16；工作树 `/tmp/scar-structured-model-280qf4mi`，HEAD `78c5fdaaea5b189c0de8c3d9f26159912d615486`。
本轮只读代码、文档和既有报告；未运行测试、collector 或 LeWM，未修改产品。

**可以对用户负责的状态：已有可校验的静态程序 IR、有限自动 Python 建图和真实采集器；
完整第一阶段 M0–M2 尚未关闭，自动全程序图、跨表示来源闭合和化简权限尚未完成。**
这与 [总规格](/tmp/scar-structured-model-280qf4mi/docs/WHOLE_PROGRAM_MODEL.md:3)、
[完整性矩阵](/tmp/scar-structured-model-280qf4mi/docs/FIRST_STAGE_COMPLETION_MATRIX.md:3)、
[当前状态](/tmp/scar-structured-model-280qf4mi/docs/STATUS.md:117)一致。

## 五类实体：职责与代码落实

| 实体 | 含义 | 目前真实实现与边界 |
| --- | --- | --- |
| Operation | 静态定义中的一处操作；可同时计算、读写、搬运或控制。 | 有有序 Uses、结果、state access、terminator、callee 等字段：[model.py:516](/tmp/scar-structured-model-280qf4mi/scar/ir/program/model.py:516)。一次动态调用另有 OperationInstance。 |
| Value | 一次静态定义结果或 block/region 参数，不等于变量名或运行对象。 | Data、Reference、StateVersion、LocalBinding、Protocol 五种变体已实现：[model.py:175](/tmp/scar-structured-model-280qf4mi/scar/ir/program/model.py:175)。动态 occurrence→denotation 的完整桥接仍缺。 |
| StateLocation | 会变化的位置/域；其内容由 StateVersionValue 表示。 | 当前主体只有 id/label/extent/stability：[model.py:122](/tmp/scar-structured-model-280qf4mi/scar/ir/program/model.py:122)。Reference/Access 有 footprint，但通用 owner、动态 selector、粗细域覆盖/冲突尚未完整落实。 |
| Region | 有入口、blocks、完成出口的子程序/子图。 | parent 结构及 callee 引用真实存在：[model.py:637](/tmp/scar-structured-model-280qf4mi/scar/ir/program/model.py:637)。环境由独立接口表关联；不是默认纯函数，也不等于已经自动恢复其内部。 |
| Resource | 执行或承载身份，如 queue、pool、file；与可变资源状态分开。 | ResourceDefinition/Requirement/Use/Location 已接 canonical core：[resources.py:62](/tmp/scar-structured-model-280qf4mi/scar/ir/program/resources.py:62)。是静态声明；动态 instance/generation、WorkTicket/Ready 完整组合仍缺。 |

输入/输出是端口角色；计算、读写、表示、生命周期、搬运、控制与等待是可组合行为。
规格的这五类不是五个互斥的业务阶段：[WHOLE_PROGRAM_MODEL.md:45](/tmp/scar-structured-model-280qf4mi/docs/WHOLE_PROGRAM_MODEL.md:45)。

## 已有的边是什么

| 关系 | canonical 存储/校验 | 不能据此声称 |
| --- | --- | --- |
| producer 与 ordered def-use | Value.origin、Operation.results、独立 UseID；双向一致性校验：[validation.py:101](/tmp/scar-structured-model-280qf4mi/scar/ir/program/validation.py:101)。 | 相同值表示同一动态发生；重复实参是一次 use。 |
| CFG 与逐边参数 | Terminator.successors、actual Use→formal BlockArgument；类型、domination、顺序受校验：[validation.py:224](/tmp/scar-structured-model-280qf4mi/scar/ir/program/validation.py:224)。 | CFG 已恢复全部 Python 异常/挂起协议。 |
| 状态内容/必要顺序 | StateAccess before/after、StateVersionValue、UseRole.STATE_CONTENT/STATE_ORDER；当前版本检查：[validation.py:362](/tmp/scar-structured-model-280qf4mi/scar/ir/program/validation.py:362)。另有 OrderEdge。 | 不同 LocationID 自动互不 alias；粗 world 的内部 effects 已精确。 |
| 调用/区域归属 | Operation.callee、call/invoke arguments、完成签名与 Region.parent；接口校验：[validation.py:450](/tmp/scar-structured-model-280qf4mi/scar/ir/program/validation.py:450)。 | 所有动态 callable、default、cell、返回 occurrence 已自动绑定。 |
| 资源/环境关联 | resource use/requirement/location 及 environment entry references。 | requirement 已有真实实例满足，或 source/runtime 环境已验证。 |
| 跨表示/证据关系 | P0 provider 归属、有序端点；P1 native entry/exit 对；v2 correspondence/evidence/provenance。 | 这些声明等价于 artifact 导入、执行对应或可替换证明。 |

展示上可以把 Operation 画成节点、Value use 画成边；存储仍保留 Value 与每个 Use 的身份。
控制、状态、资源、包含和证据关系也必须保留；一张只画 Tensor 数据的图不能承担全部模型。

## 递归区域与多表示图：哪些确实存在

**静态递归表达已具备，通用自动递归恢复尚未完成。** Region.parent 所有权必须无环；
callee 引用没有被当作所有权，因此可以表示递归调用：[validation.py:126](/tmp/scar-structured-model-280qf4mi/scar/ir/program/validation.py:126)。
旧 `_Builder` 会在预算内扩展有限同文件候选，并给出带条件的 CallTarget：
[program_lowering.py:747](/tmp/scar-structured-model-280qf4mi/scar/analysis/program_lowering.py:747)。
但较新的 structured profile **明确只允许 root-only expansion**：
[program_lowering.py:204](/tmp/scar-structured-model-280qf4mi/scar/analysis/program_lowering.py:204)；
其调用 candidate region 仍为 None：[structured_lowering.py:510](/tmp/scar-structured-model-280qf4mi/scar/analysis/structured_lowering.py:510)。
不能将此称为任意层级/跨库子图已自动接通，也没有通用展开/折叠等价的完整验收。

**多张图的类型与容器真实存在，统一后的完整程序模型仍是目标。**
v2 IRBundle 已组合 SG、EEG、ValueGraph，并可带 Correspondence/OIR/source semantics：
[schemas.py:72](/tmp/scar-structured-model-280qf4mi/scar/ir/v2/schemas.py:72)。
LogicalValue/Version、allocation/storage region/materialization 也有实际记录：
[values.py:50](/tmp/scar-structured-model-280qf4mi/scar/ir/v2/values.py:50)。
ProgramGraph 的 provider/native 表已能声明多种 representation 的对应，但八域 obligation
明确 always-unproved：[native.py:181](/tmp/scar-structured-model-280qf4mi/scar/ir/program/native.py:181)。
IRBundle 尚未直接承载 canonical ProgramGraph；core ValueID→动态 occurrence→v2 logical
version 的完整桥接未实现。规格中的完整 ProgramModel 组合容器不能报为已交付。

自动 trace normalizer 已产生动态实例、父调用、部分顺序、资源/值快照，但语义定义仍标为
`v1_runtime_stub/source_semantics=unresolved`：[normalize_v2.py:199](/tmp/scar-structured-model-280qf4mi/scar/trace/normalize_v2.py:199)。
最终报告明确 G5 correspondence pending、snapshot-scoped identity、无跨快照等价：
[normalize_v2.py:482](/tmp/scar-structured-model-280qf4mi/scar/trace/normalize_v2.py:482)。
这是真实实现的部分图，尚未成为从 Python→operator→kernel→物化→输出的完整多对多连接。

## 四层进度分别报告

| 层次 | 已有内容 | 当前限度 |
| --- | --- | --- |
| 文档/规格 | 五实体、M0–M6、Python 字段/阶段/控制/资源分册、工具集成设计。 | 规格完成度不能替代接口实现与整门验收；M0 没有“整个目标全部关闭”的依据。 |
| 类型声明与组合 | canonical SSA/CFG/state、环境、静态资源、C0 pending/packet、P0/P1；codec/validator/query 已接。 | 对真实 callable、资源满足、equivalence 保持待证。C1 目前仍是未验收规格，未见产品类型。 |
| 自动恢复/导入 | 源索引、有限同步 expression/if/loop/binding/invoke lowering；真实 sys.monitoring、module/dispatch、profiler/Kineto 采集与 normalize。 | structured 不是全程序默认集成；FX/Export/ETO 新 adapter 未接；新静态声明不会自动由现有 lowering 填好。 |
| 实测/验收 | 有既有冻结组件、独立小程序和固定源码压力记录；本轮没有重跑。 | 只证明各记录限定范围。测试数不是建模覆盖率，工具独立 CPU probe 不是 SCAR adapter。 |

C1 的文档写明“冻结实施规格，尚未验收”：
[M1_CLEANUP_INTERFACES.md:3](/tmp/scar-structured-model-280qf4mi/docs/M1_CLEANUP_INTERFACES.md:3)。
当前 ProtocolValueKind 仍只有 pending/packet：[control.py:43](/tmp/scar-structured-model-280qf4mi/scar/ir/program/control.py:43)；
ProgramGraph 没有该文档要求的 cleanup 六表：[model.py:679](/tmp/scar-structured-model-280qf4mi/scar/ir/program/model.py:679)。
因此即使 C1 设计已评审修订，也不能称 cleanup 代码实现或验收完成。

既有源码压力的固定 256 个候选中，51 个有带缺口的图、205 个 unsupported；1,591 个源 Call
中 77 个有严格 core 端点。它不是全项目覆盖率，且 runtime/effects/transform 权限仍 false：
[N2_STRUCTURED_BODY_ACCEPTANCE.md:36](/tmp/scar-structured-model-280qf4mi/docs/N2_STRUCTURED_BODY_ACCEPTANCE.md:36)。
原始报告也保留这些 false：[attempt-005/report.json:24](/tmp/scar-structured-model-280qf4mi/artifacts/experiments/b1_call_operands/structured_model_source_stress/attempt-005/report.json:24)。
P1 验收收据的 scope 则明确只有声明，不包括 capture/import/equivalence：
[acceptance.json:5](/tmp/scar-structured-model-280qf4mi/artifacts/experiments/b1_call_operands/model_native_interfaces/acceptance.json:5)。

## M0–M2 还缺什么

- **M0：** 固定工具事实与 SCAR canonical 事实的归属、版本和可信边界；完成五实体、
  动态身份/版本、控制/资源与多图桥接的一致性审查。当前主规格自身仍标“规格修订”。
- **M1：** cleanup/context、with/except*；saved-frame/resume request/continuation generation；
  owner/selector/粗细域 alias；完整 literal；动态资源/WorkTicket/Ready；occurrence/denotation、
  值推导与物化推导；provider/native 实例状态与观察边界的组合接口尚不齐。
- **M2：** 各 Python 构造的 phase、求值/失败路径、隐式调用、状态/资源/完成规则必须
  接到可组合接口；现有 catalog 和语言探针不足以证明全套协议关闭。自动 source lowering
  属 M3，不能把“实现完整 Python 编译器”偷偷变成 M2 的验收条件。

完整缺项以 [矩阵:22](/tmp/scar-structured-model-280qf4mi/docs/FIRST_STAGE_COMPLETION_MATRIX.md:22)
与 [阶段合同:20](/tmp/scar-structured-model-280qf4mi/docs/WHOLE_PROGRAM_MODEL_PLAN.md:20)为准。
目前不能宣称加载→推理→环境→视频输出全过程已闭合，也没有可信自动变换或 clean A/B 加速比：
[STATUS.md:133](/tmp/scar-structured-model-280qf4mi/docs/STATUS.md:133)。

## 最大重复造轮子风险及应收缩的范围

最大风险是把“补齐跨工具的依赖与协议边界”扩张为同时自写完整 Python 编译器、
Tensor tracer、native signature/pytree 解释器和 GPU 活动采集器。现有代码已投入大量
source lowering/operand 观察，P0/P1 却尚未变成真实 provider 导入；继续堆静态声明和
兼容验收可能增加维护面，却不解决用户最关心的具体程序连接。

建议把第一阶段收缩为**可组合的薄边界模型**：保留 canonical Use/state/CFG、来源/范围、
输入输出、当前状态与 normal/raise/resume/resource 完成合同；复用外部工具的原生子图、
signature/tree artifact 和原始证据。新增字段须回答具体跨图查询或不变量。
优先明确现成 Python 前端、FX/Export、ETO/profiler 的事实边界，再决定 SCAR 必须补的空缺。
这一方向已写进 [计划:36](/tmp/scar-structured-model-280qf4mi/docs/WHOLE_PROGRAM_MODEL_PLAN.md:36)
和 [集成设计:48](/tmp/scar-structured-model-280qf4mi/docs/MODELING_INTEGRATION.md:48)，尚未完成接入。

后续自动恢复应让未知语义形成有定位、可续接的子区域边界，保留周围已知结构。
当前 unsupported 会使整个 body 没有 graph：
[structured_lowering.py:520](/tmp/scar-structured-model-280qf4mi/scar/analysis/structured_lowering.py:520)。
同时保留 SCAR 有价值的差异：跨图身份与状态版本、控制/环境/资源/外部输出的依赖，
以及具体缺失关系。成熟工具的单张图不自动提供这些事实；边界可表达也不算未知内部已恢复。

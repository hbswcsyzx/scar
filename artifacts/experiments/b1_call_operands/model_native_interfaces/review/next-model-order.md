# 下一阶段模型门：先闭合协议类型，再恢复具体程序

**状态：Proposed；仅供排序。** 基于 `79bf2a95` 的 [完整性矩阵](../../../../../docs/FIRST_STAGE_COMPLETION_MATRIX.md)、
[Python 3.14 构造目录](../../../../../docs/PYTHON314_PROTOCOL_CATALOG.md)、
[整体模型](../../../../../docs/WHOLE_PROGRAM_MODEL.md) 和 M1 控制/资源/native 接口。
不改变当前冻结验收，不把下列接口视为已实现。

## 收敛原则

M1/M2 要定义足以组合、校验且保守表达缺口的协议接口；不要求 SCAR 手写完整 Python 编译器或逐个解释 native 库。
M2 的 catalog 已覆盖 AST 构造族，但“字段有名字”不等于 phase、求值顺序、状态和完成规则已落到 core。
未展开内部只能保留准确输入、环境、可能状态/资源、normal/raise/suspend 和范围缺口；不得计为完整理解或无效果。

## M1/M2 必须闭合的接口

| 顺序 | 最小规范闭环 | 反例 | 已有依据 / 缺口 |
| --- | --- | --- | --- |
| C1a cleanup / 当前异常上下文 | 复用 `ControlScope/ControlPort`、`PendingCompletion`、`ExceptionPacket`、原 CFG Uses 与 StateVersion。增加可校验的 transfer→cleanup-entry→cleanup-exit/dispatch 路由；每条边携 pending port/payload 与该路径当前 state-domain 签名；显式保存/安装/恢复 handled-exception context。替代完成必须是另一条 typed transfer，不能只改标签。 | `return r` 的 finally 中写状态后再 raise：返回被覆盖，但先前写入仍留在异常后态；`except` 中 bare raise 使用当前 handler exception，而非旧 pending payload。 | C0 已有 lexical scopes、ports、packet/pending、固定点 dispatch；C1 route/context/partial-poststate 未实现。Python control catalog 已列 `finally`、`with`、`except*` 规则；需为 source contract 增独立构造证据。 |
| C1b resume / continuation | M1 定义 `ContinuationLayout(site, owner Region, live local-binding slots, live temporary Uses, handler/cleanup stack, pending completion)` 与有版本的 ResumeRequest (`NEXT/SEND/THROW/CLOSE`；async 协议另分)；resume 输入同时接 saved frame-private 状态和**当前**共享状态，输出新 pending/state 或 suspend。动态实例/generation 留给 M4。 | generator 在 `yield` 后，caller 改了 closure cell 或输入对象；按 yield 时 world 恢复会读旧状态。关闭失败后再次恢复也不能假定 Closed。 | `LocalBindingValue`、C0 completion 与控制分册可复用；现 core 尚无 continuation/save-resume 类型。Python control catalog 有本机协议反例，不能据此声称 SCAR 已实现。 |
| C1c resource instance / work-ready | 在已有 `ResourceDefinition/Requirement/Use/Location` 上补 `ResourceInstance(id,generation,scope)`、definition/requirement realization、带有效期的 HandleBinding；`WorkTicket(enqueue occurrence, executor/queue generation, ordered dependencies, state accesses, outputs)`；consumer-specific ReadyRequirement/Evidence 关联 content/materialization version、allocation generation 和 visibility domain。Host outcome 与 resource outcome 是不同端口。 | enqueue 已返回但 GPU 工作仍进行；旧 event 完成不代表同 allocation 后续写入已 ready。`record_stream` 延长 allocator 生命周期，不等于 producer/consumer 同步。 | 静态四表、StateVersion/StateAccess、v2 allocation/materialization/provenance 可复用。ETO/Kineto 和 profiler 有 activity、correlation、memory 字段，但现无 adapter 将它们接到规范 occurrence/work/ready。M2 需逐库版本化协议，不能按 API 名默认同义。 |
| C1d occurrence / denotation / provenance | 为 `OperationID/ValueID/UseID` 定义 scoped occurrence 坐标 `(run, process/window, activation, visit/resume generation)`；每条静态↔动态对应保存规则、证据、冲突/缺失状态。ValueOccurrence 再 denotate 到 ObjectID、LogicalValue/ValueVersion、StateVersion、Binding/Protocol 或 scoped unresolved。保留 `ValueDerivation` 与 `RealizationDerivation` 两种不同关系，Alias/selector 与有效期引用现有 locations/materializations。M1 定义类型和可连接字段，M2 明确哪些构造产生哪些 occurrence；不预填实测结果。 | 循环再次执行同一 static `ValueID` 是新 occurrence；同 `ObjectID` 原位写后内容版本变化。全局 `latest` 会把不同 visit、alias 和 caller 的值错误合并。 | Core 有静态 SSA Uses；v2 有 logical/physical/provenance records；provider/native 只给静态边界声明。Call-operands、ETO、Kineto 是不同范围的动态事实来源；occurrence↔denotation 统一桥接仍缺。 |

M2 应把上表规则接到已有 `Operation/Value/Region/State/Resource`，而非再造 parallel graph。尤其 location owner/selector/alias、bytes/complex/Ellipsis 等 literal、正常与异常后态、外部 history 都必须有明确类型或具体未解析域；不能以一个宽泛 OPAQUE 隐去已知的调用/状态边。

## 哪些留给后续建图与证据阶段

| 阶段 | 交付 | 复用什么 | 不能提升成什么 |
| --- | --- | --- | --- |
| M3 自动结构恢复 | 从入口/导入/动态源码恢复 source snapshot、定义/phase、Region、ordered Uses、CFG、显式 unsupported frontier；可接成熟前端或逐步扩 lowerer。逐文件预算与 replay 不变。 | Python `ast/symtable/dis` 提供语法、编译作用域和 code witness；现 program inventory/lowering 可按已支持子集复用；FX/Export 提供带版本的 Tensor 子图、signature/TreeSpec，torchview 可作展示/交叉检查。 | AST 守恒、filename/lineno、FX 捕获成功或 opaque 壳，不证明每个 body/副作用已恢复。M2 的规则 catalog 不是执行过的 source graph。 |
| M4 执行精化 | 按 run/activation/visit 将实际 CALL、Python 操作、ETO/Profiler event、资源工作、对象/逻辑值版本接到 M3 定义；保留 dropped/conflict/gap 与采集条件。 | `sys.monitoring` 的有界 call/operand 观察、ETO 有序 operator input/output 与局部 Tensor/storage IDs、Kineto correlation/kernel/memcpy、现有 profiler memory facts。 | 一次 trace 不覆盖未执行分支；Tensor/storage ID 不等于内容版本；host 返回不等于 GPU ready；同名/同地址不等于静态身份。 |
| M5 观察根闭合 | 从返回、文件/视频/日志、异常/完成、外部状态和后续 consumer 向前追溯；每个输入、state/resource/readiness、alias/lifetime 和未闭合域有精确 endpoint 或拒绝理由。 | 原 core dependency/query、provider facts、v2 provenance/materialization、M4 对应边。 | 只有 Tensor 数据路径、手工挑选的 source body、缺失 trace event 或 boundary pair，不构成观察闭合。 |
| M6 化简 | 仅对具体闭合子图生成 rewrite/delta、保持合同、成本和验证计划。 | 闭合后的 Program/OIR、观测合同与 benchmark 工具。 | 本报告、M1/M2 组件数、查询可达或重复图节点，不授予 reuse/hoist/delete 权限。 |

## 建议验收顺序与小型反例

1. **先 C1a**：共享 cleanup entry、不同 pending 来源、正常/异常后态；拒错 scope/target/payload、遗漏 cleanup 出口、将 old world 接到新异常边。
2. **再 C1b**：`yield/send/throw/close` 与 awaitable 的创建/挂起/恢复/关闭边界；拒 request 混型、同 generation 双恢复、复用保存的共享 world、把 host return 当 function completion。
3. **再 C1c**：同 static creation 多次 instance，queue/event generation、partial failure、cancel、消费者可见性；拒 requirement 冒充 instance、old event 覆盖新 generation、enqueue 当 ready。
4. **再 C1d 与 M2 构造闭环**：循环/递归、多次 call、duplicate argument、alias write、异常前部分效果、native/native-to-core boundary；拒 definition 与 occurrence 合并、ObjectID 与 ValueVersion 混同、TreeSpec 自动拆核心 Value。
5. 每个组件有通用手工 graph + validator/query/codec 反例；随后独立 source/runtime adapter 测试。类型覆盖、自动恢复、运行对应、观察根闭合和化简各自报告，不累计混称“覆盖率”。

## 复用边界

- Python 语言参考、CPython compile/symtable/dis：约束 phase、作用域与求值次序；不替代动态对象/状态证据。
- FX/Export：保留原 artifact、graph stage、ordered args/kwargs、signature/tree/capture constraints；沿 P1 `NativeBoundary` 引到 core ports，不复制 TreeSpec parser，不让 exported subgraph覆盖原 Python effects。
- `torch.profiler`/Kineto、ETO、`sys.monitoring`：分别提供物理工作、Tensor/operator observation 与受限 Python call 窗口；各自带 run/window/schema/flags，不能按时间邻近或共同字符串推断数据依赖。
- SCAR 自有工作应是上述记录之间的 typed correspondence、冲突/缺口和可重放校验，不应重复实现已有前端/工具图或因工具无法覆盖任意 Python 而启动全语言 tracer 项目。

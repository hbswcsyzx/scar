# 完整程序模型草案：最终一致性审查

日期：2026-10-16。范围：只读规格审查；只新增本文，未修改原草案、产品、测试或 gate，
未运行测试/目标程序。本文不复验草案末尾所列测试计数。

审查输入：

- `WHOLE_PROGRAM_MODEL.draft.md`，SHA256
  `ec170578182291747ab7623c7f46d3ee01c924c2480ab0383ffb1d08a970ffb0`。
- `../model_connection_audit/whole_program_control_model.md`，SHA256
  `3900cc19a2e2d2d247a10e38fc141c947d992929b650b31ee5060345357e0901`。

**结论：总体方向一致，但下列六项应在规格冻结前修正。** 这些修改是规范连接合同，
不要求本轮实现新功能。现草案尚不能仅凭类型清单充当可校验的整体模型规格。

## 一、必须修正的问题

| # | 草案位置 | 问题与最低修正 |
| --- | --- | --- |
| 1 | 第3节 `LanguageCompletionValue`；第5.1节 | `Suspend` 不能混在最终 completion 中。改为 `LanguageOutcome = Complete(LanguageCompletion) \| Suspend(Suspension)`；pending completion 只含 Fallthrough/Return/Raise/Break/Continue。yield 时 host 可以返回，但 generator frame 仍活着；finally 内 yield 还须保留原 pending completion。 |
| 2 | 第5.1节 `target是具体激活实例` | 混淆静态 Program 与 Execution。静态 target 是 scoped ReturnBoundary/LoopTarget/Port；实际 invocation/resume generation 由 Execution correspondence 绑定。不是每种 completion 都有同样 target/payload：Raise 通过 handler dispatch，Break 没有返回 payload。用强类型联合替代四字段的任意组合。 |
| 3 | 第5.1节 `Completion = ... + post-state`；第4节效果接口 | 不应让 completion 值或 overlay 保存第二份状态链。pending 值持有 kind/target/payload，当前 post-state 由规范完成边参数给出；cleanup 保留原 payload 时必须输出新状态。异常是完成接口，RNG 是状态域；效果概述应引用规范访问/完成关系，不能再独立维护一份可冲突的效果事实。 |
| 4 | 第3节 `ResourceReferenceValue` | Requirement、Definition、Instance 不是可互换的 referent。Requirement 是选择/能力约束，不能成为已解析 Python handle 的指向。Program handle 通过有类型关系指向 ResourceDefinition；Execution 的 realization 才给出 ResourceInstance。资源要求作为端口/操作的独立引用，保留未满足状态。 |
| 5 | 第5.2–5.3节 | 缺少足够字段以检查关键连接：ContinuationHandle/SavedFrameInterface、ExceptionPacket/handler context、FunctionEnvironment、HostOutcome、ResourceOutcome 和 scoped Ready。只列 create/enter/close、wait 等动作无法校验参数与目标。采用下节最小 schema，普通调用与 generator/resource 必须经 adapter，不能隐式强转。 |
| 6 | 第2–5、8节 | 有平行 metamodel 风险：五家族、Value catalog、协议表、效果表和 Execution 不能各保存相同的事实。指定唯一规范端点；protocol records 索引 core Uses/edges，Execution 只增加 occurrence 与证据。现 LocalBinding 状态继续由 BindingDefinition/Read 及 CFG 参数决定，不增加一个独立“合流状态”属性；FrameRules 不再复制为另一份 cleanup 规则。 |

## 二、推荐冻结的最小 schema

以下给出**同一模型内的规范类型和归属**，不是要求额外建一张控制图，也不是新增
顶层 structural family。字段中出现的 Use/Produced 均为现有 core 端点的有类型引用。

### 1. 静态端口和语言结果

```text
ControlPort = (id, owner: RegionID, protocol, payload_signature,
               state_domain_signature)

ControlTarget =
    FallthroughTarget(port: ControlPortID)
  | ReturnTarget(owner: RegionID)
  | BreakTarget(loop: LoopID)
  | ContinueTarget(loop: LoopID)

LanguageCompletion =
    Fallthrough(target: FallthroughTarget)
  | Return(target: ReturnTarget, payload: ReferenceUse)
  | Raise(packet: ExceptionPacketUse)
  | Break(target: BreakTarget)
  | Continue(target: ContinueTarget)

LanguageOutcome = Complete(LanguageCompletion) | Suspend(Suspension)

BoundaryEdge = (source_port, target_port, payload_arguments,
                state_arguments: ordered (StateLocationID, UseID | Produced)*)
```

`protocol` 为封闭的有类型协议联合或版本化规范身份，不能是操作 label。state
arguments 按声明域恰好覆盖当前状态，不允许旧状态回退、遗漏或无依据的新增域。
原始异常/return payload 与 cleanup 后态可以不同来源，这是正确行为。

只有需要把待完成动作送过 cleanup/合流/suspension 时，才创建
`PendingCompletionValue(id, region, origin, CompletionType)`；规范的 completion
construction record 指向 producer 的 typed target 和 payload Uses。普通直接 jump
无须人为新增 token。`LanguageCompletionValue` 与 `PendingCompletionValue` 应选一个
规范名称，不维护两个含义相同的变体。Fallthrough 与 host Normal 也不能同名混用。

`ExceptionPacket` 至少给出异常引用、传播 traceback 的引用关系与对应上下文接口；
cause/context/suppression 的可变内容由状态访问提供。当前 handled exception 属于
handler/execution-context state，bare raise 读取它。不能只用一个 opaque exception
reference 宣称异常上下文已恢复。

### 2. Suspension 与环境

```text
Suspension = (site: SuspensionSiteID,
              protocol: GeneratorYield | AwaitSuspension,
              exported_payload: protocol-specific interface,
              continuation: ContinuationHandleUse)

ContinuationHandleType = (owner: RegionID, site: SuspensionSiteID,
                          resume_protocol, saved_frame_interface)

SavedFrameInterface = (ordered binding_slots, live_evaluation_stack,
                       held_temporaries, handler_cleanup_stack,
                       pending_completion_type_or_none)

ResumeRequest = Next | Send(ReferenceUse) | Throw(ExceptionPacketUse) | Close
ResumeEntry = (resumable_reference, continuation, request,
               saved_frame_arguments, current_shared_state_arguments)
```

static interface 不保存动态 generation；Execution 的 continuation occurrence 另外绑定
generator/task identity 与 suspension generation，校验一次合法恢复和 reentry 状态。
不能把挂起时 world 作为当前共享世界。保存接口仅声明类型/slot，实际值由规范 Uses
和参数给出，不复制第二份保存值图。coroutine/async generator 使用各自 resume
协议，不能把 Next/Close 无条件套到所有可恢复对象。

`FunctionEnvironment` 是隐式 body 入口，不是 Python formal：

```text
EnvironmentInterface = (function_object_reference, code_definition,
                        globals_namespace, defaults_location,
                        kwdefaults_location, ordered captured_cell_identities)
```

各位置的内容版本从状态入口/读取提供；同 code 不等于同环境，同 cell 可供多个
function 读取。现 ObjectReferenceValue 可以承载有类型的 function/environment/
generator 引用角色，不必为每种角色新增平行顶层家族。

### 3. Host、资源和对应关系

```text
HostOutcome = Returned(typed payload) | Threw(ExceptionPacket)
HostCallInterface = (call_operation, ordered actual Uses, dispatch/environment
                    inputs, host_result_ports)

WorkTicketType = (producer_operation, resource_definition_or_requirement,
                  work_generation_interface, affected_version_obligations)
ResourceOutcome = Completed | Failed(typed diagnostic) | Cancelled(typed result)
ReadyType = (ticket_generation, content_or_materialization_version,
             consumer_visibility_domain, readiness_kind)

ResourceRequirement   --realization evidence--> ResourceInstance
ResourceDefinition    --realization evidence--> ResourceInstance
ObjectReferenceValue  --handle/resource relation--> ResourceDefinition
```

ResourceRequirement 可用于静态未执行分支的选择约束，不能因出现在 WorkTicket 类型
中就声称已经满足。物化 handle 未解析时保留未解析关系。Ready 绑定具体工作和消费
域；它可供多个消费者使用，不套 continuation 的一次性约束，也不授予变换权限。

HostCall 的 pre-entry failure 与 body completion 分开；只有真实/已证明 entry 关系
才可把 body return 接回这次 caller。Execution 另存 attempt/invocation/resume/work
occurrence，不能把动态 ID 填入静态 source target 后声称未执行路径已经发生。

## 三、必须附在 schema 上的五条组合规则

1. **finally**：finalbody Fallthrough 保留原 pending payload/target 并采用后态；新的
   Return/Raise/Break/Continue 替换原 pending；Suspend 保存它。无完成不造完成边。
2. **with**：enter 成功才注册 exit；只有 pending Raise 才按 exit 返回值求真并抑制；
   pending Return/Break/Continue 时忽略返回值，不额外求真。exit/truth 的异常替换
   原 pending。多 manager 按 scope 嵌套清理。
3. **generator**：create 不等于 enter；Yield 对应 next/send 的 host Returned，body
   Return 经 iteration adapter 对应 StopIteration.value。Close/Throw 有各自版本化
   规则，不能把 close 的失败强行标为 Closed，或把 yield 当 Frame EXIT。
4. **frame cleanup**：继续引用现 FrameRules 的未证 NO_FRAME_INTERPOSITION、未知
   effects、可能不完成、unraisable 与不保证 free。它的条件性 payload 保留规则不是
   finally/with 的替换规则。按源码完整生成与满足适用条件是两件事。
5. **资源消费**：stream wait 可只建立资源执行顺序，host 不必等待；host 内容读取
   另需其 visibility。提交返回、work completed、CPU 可见、allocation 可复用与
   文件持久化不得隐式等价。

## 四、避免重复体系的冻结原则

规范事实只保存一次：

- core Operation/Value/StateLocation/Region 保存 producer、ordered Use、CFG、
  state access 和结果；Resource 表保存独立身份及要求。
- typed protocol/interface records 规范解释这些端点，不能另存自由可改的 before/
  after state、payload producer 或另一张 CFG。验证器重算一致性。
- Execution 保存 occurrence、对象/资源实例和观察证据；correspondence 逐端点连接
  静态定义与实际发生。它不修改旧 source definitions。
- OIR 的合同引用上述事实，不以 Ready、完整类型或 reference route 作为纯度/等价
  证明。未知 effects 与未知运行对应不被统计覆盖率消除。

修正以上六项并纳入组合规则后，可将草案冻结为完整模型规格；哪些协议已实现、
哪些能自动生成和哪些有真实运行对应，仍需使用各自状态表。本文不扩大下一阶段
实现范围，也不把规格冻结解释为完整程序自动建图已经完成。

## 五、正式规格复审：原六项已关闭

复审日期：2026-10-16。**结论：PASS，仅指本次控制/接口规格一致性审查。**
前文保留最初草案的问题与建议；以下结论针对正式文档的新内容，不覆盖历史失败。

只读核对的正式输入位于 `/tmp/scar-structured-model-280qf4mi/docs/`：

- `WHOLE_PROGRAM_MODEL.md`，SHA256
  `6a15a9ca32f354b8f94796ff5dae9dee5d1fbaf0fc1b9aafd6346d4807c46967`。
- `WHOLE_PROGRAM_MODEL_PLAN.md`，SHA256
  `3d511e4a2eaff1c0ed2b98187a1f075c289c1d2b9a055582f62a168fe3c75a64`。

| 原必修 | 正式规格中的修正 | 复审 |
| --- | --- | --- |
| 1 Suspend 混入 completion | 第5.1节使用 `LanguageOutcome = Complete(LanguageCompletion) \| Suspend(...)`，挂起不完成原函数。 | 已关闭。 |
| 2 静态/动态 target 混淆 | 第5.1节明确 Program scope/port 与 Execution activation/loop/resume occurrence 的绑定。 | 已关闭。 |
| 3 重复保存后态 | 第4.2、5.1节将 state version 保留为规范事实，pending 只包装 variant/target/payload，完成边携当前后态。 | 已关闭。 |
| 4 Requirement 误作 handle referent | 第6节分开 requirement/definition/instance、Realization、HandleBinding，并明确 requirement 不是 handle referent。 | 已关闭。 |
| 5 必要 typed interface 不足 | 第5节已给 `ControlPort` 与 `EnvironmentInterface` 精确字段，明确 implicit body entry、非 Python formal 和规范状态参数；第5.1–5.4节给异常、continuation/saved frame、host、resource/ready 合同。 | 已关闭。 |
| 6 平行 metamodel/重复事实 | 第2.1节明确单一 canonical producer/use/edge/state；protocol/overlay 引用该事实；第3、9节另以 occurrence/correspondence 连接执行，未另建替代 def-use 图。 | 已关闭。 |

阶段边界亦一致：计划中的 **M0** 是规格一致性；**M1** 要实际强类型及拒绝错接的
validator；**M2** 要目标版本构造的求值/phase/隐式调用规则及逐协议反例。计划明确
M0—M2 尚不等于自动全程序图，后者从 M3 开始；已有局部实现和回归数不充当
M1/M2 全部分母通过。没有发现本范围内新的实质控制/接口矛盾。

此次 PASS 是 M0 的一份独立审查证据，**不单独宣布 M0 所有验收条件已满足，更不
代表 M1/M2、完整 lowerer、自动建图、执行对应或化简权限通过**。未执行任何测试
或目标程序；未修改正式规格、实施计划或产品文件。

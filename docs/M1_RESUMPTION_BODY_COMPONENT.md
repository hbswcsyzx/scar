# C2B：可恢复 body 的字段与组合合同

2026-10-17字段合同，2026-10-18实施更新；基线 `b4bc1a4`。body类型和组合已实施，
独立审查及最终499项组件通过；**冻结全仓回归尚待完成，不算发布验收关闭。**
本组件落实 C2.1–C2.3 的 body 结构。完整 C2 的 Create/driver/实例与代次/host adapter/
最终 release 仍按 [C2 主合同](M1_RESUMPTION_INTERFACES.md) C2.0/C2.4 继续；不改变
第一阶段完整分母，不将本组件称完整 generator/coroutine 支持或自动源码建图。

## 1. 记录与唯一事实来源

沿用已有 OperationID/RegionID/BlockID/ValueID/UseID/LocationID；新增四张表：

```text
ResumableBody(region, kind, context_location)
FrameContextInitial(operation, frame)
FrameContextAttach(operation, frame: UseID, caller: ValueID)
FrameContextDetach(operation, caller: UseID, frame: ValueID)
```

kind 为 GENERATOR / COROUTINE / ASYNC_GENERATOR / GENERATOR_COROUTINE 的静态声明，
不证明实际 code flags。context_location 必须是 body 入口已携带的 state domain；
若该 Region 还声明 C1 HandledContextDomain，二者必须相同。

新增两个协议类型 FRAME_CONTEXT / DRIVE_CALLER_CONTEXT。普通结果和参数仍只由
Operation.results / BlockArgument 定义。所有新增 records exact/frozen/slots；
没有 verified/authorized 位，不放运行对象/frame 或完整 Tensor 数据。

```text
SavedSlot(role, use: UseID)
SavedInput(saved_slot: int)
ResumeInput(resume_slot: int)
ResumeSlot(kind, location: LocationID | None)
ResumeSuccessor(inputs: tuple[ResumeSlot,...], block, arguments)
SuspendTerminator(flavor, exported: UseID, saved: tuple[SavedSlot,...],
                  handoff: tuple[UseID,...], successors: tuple[ResumeSuccessor,...])
```

Suspend 的 owned Uses 精确为 exported、saved.use 和 handoff；各输入端口用不同
UseID，所引用 Value 可以相同。逐边的 SavedInput 只索引这个唯一 saved actual，
不再复制一套 Use/value。arguments 的元素只能为 SavedInput 或 ResumeInput。
两个投影 record 用不同字段名作严格 wire 判别，不按 union 顺序猜含义。
同一保存槽可以明确绑定多个 formal，包括 FRAME_CONTEXT 槽；后者必须全都来自
该规范保存槽，Attach 可消费其中一个。额外未消费 alias 不作为 dead 或逃逸。
这不放宽下面对 Attached block 唯一当前 caller-token formal 的要求。

SavedSlot role 为 VALUE（Data/Reference）、LOCAL_BINDING、PENDING_COMPLETION、
CLEANUP_CONTEXT、FRAME_CONTEXT、DELEGATE_REFERENCE。拒绝 StateVersion 和 caller
token；角色与实际 Value kind/协议类型一致。FRAME_CONTEXT 恰一槽，必须精确是
本 Suspend 紧邻的 Detach.frame 规范结果，不能是旧 landing 片段或其他 Detach。
保存也可以承担引用保留：某槽未被某个恢复case使用不等于dead。C1 context捕获
仅放宽到当前active owning cleanup的私有保存槽；实际恢复目标仍须在合法子树内。

ResumeSlot kind 为 STATE / SENT_VALUE / THROWN_PACKET / DELEGATE_VALUE /
DELEGATE_PACKET。仅 STATE 带 LocationID；它对应 StateVersionValue。值输入为
无 identity/alias 精化的 Reference；packet 输入为 EXCEPTION_PACKET。每个 case
恰含一个 delivered payload 和本 Region 每个共享 state domain 各一槽；每个
ResumeInput 槽恰一次绑定到新目标参数。payload 是实际交付给 body 的输入，不是
外部 request 名；完整 driver 映射在 C2.4，不能按同名方法自动连线。

flavor 为 YIELD / DELEGATION / AWAIT / ASYNC_YIELD；按 body family 检查组合，
但不从声明推导源码合法性/实际 capture。每个 case 的 landing 唯一且独占该条
temporal incoming，没有普通前驱；初入 entry 不得成为 resume landing。

## 2. 初入、附着和卸载

Initial 只能是 body entry 第一项，产生恰一个 FRAME_CONTEXT 结果，无 Uses/state
访问，CONTROL、effects_complete=True。它是抽象初始 INHERIT 协议值，不是物理
frame allocation。下一项必须 Attach，消费该结果及当前 context-domain state。

Attach 只能在初入该位置或 resume landing 第一项：后者 frame Use 必须消费由
该 source Suspend 的 FRAME_CONTEXT saved 槽转发的新参数。Attach 产生一个
DRIVE_CALLER_CONTEXT 和一个 context 后态。Detach 消费本次当前 caller token，
产生一个 FRAME_CONTEXT 和 context 后态。二者普通非callee/非terminator；精确
CONTROL/READ/WRITE、effects_complete=True，仅 context 域 WHOLE 非overwrite
READ_WRITE，无 reference refinement；所有其余当前 state 域正常转发不造新值。

以上只描述无用户回调、completion-preserving 的抽象 switch。真实引用管理、
释放/hook/异常另有操作和当前状态；不能因本记录验证通过就认定真实实现符合。

全 logical CFG 推导 Detached/Attached：entry Detached，temporal landing Detached。
每个 Attached block（初入/landing 的 Attach 前除外）恰一个 caller-token 参数；
普通边必须将当前 active token 精确送入它。Attach 只从 Detached 进入，Detach
只从 Attached 离开并消费同一个当前 token。禁止 mode 合流冲突、重复Attach、
旧caller替代、caller进入普通call/容器/完成/保存槽。caller不是可以复制恢复的
body frame 状态；静态 use 数不是互斥/单次恢复证明。

Detach 必须紧邻 Suspend 或真正 RETURN/RAISE；未卸载不得 handoff/终止。Detach
后 body 不执行用户计算或回调。Suspend 不 FrameExit、不 pop C1；最终 release
属于后续 driver 生命周期，不套旧同步 FrameModel 的出口邻接合同。

## 3. 控制、可用性和当前状态

```text
本段定义 → Detach → Suspend ─export/handoff→ driver（后续接口）
                         └saved槽─SavedInput→ landing的新参数
driver的实际最新状态/输入 ──────ResumeInput→ landing的新参数
                                               ↓
                                    Attach → 本段使用 → …
```

图中的两种landing入参来源不同；temporal边不是立即执行，也不使旧定义直接可用。

Suspend 不是普通 RETURN；它没有 ExitPort.exit，也不增加 NORMAL/RAISE 的旧
INVOKE completion。导出的引用与 handoff 状态只描述本次交还 driver；temporal
case 描述若将来真实恢复时可到达，并不保证实际恢复/完成。

handoff 恰含本 Region 每个 state domain 的当前版本各一次。恢复 state 必须由
ResumeInput 提供，不保存旧 state。其来源合同是实际 body ingress 前最新后态，
包括任何 gate/delegate 已发生的写；上下文 Attach 再推进自己的域。

logical CFG 包含 temporal 边；availability 则以 entry 和所有独立 landing 为
roots，切断跨挂起未保存定义。所有 operation Uses 都须通过它，包括间接合流、
循环回边、传给下一次 Suspend 的保存值。literal 保持全局可用。源保存 Use 在
Suspend 处先验证可用，恢复只使用新参数，不给旧 ValueID 第二个 producer。

SavedInput → 规范 Use 的解析在一处派生，复用于 core 类型/reference_binding、
LocalBinding 的同slot/BOUND事实、C0 pending事实/逃逸及 C1 copy/fresh/私有context。
ResumeInput 不证明原 pending/context/binding。引用保存仍要检查目标参数无无据
identity/alias 精化；不是只比较 ValueType。普通 CFG/旧 INVOKE 规则保持。

C1 栈沿真实 temporal 边保持同一次 cleanup activation；landing 的词法归属与
source 相容，不侧入/离开保护区。原 pending/context 经 SavedInput 真实转发；
Enter前后的 freshness仍用logical dominators，不用availability roots重置。

## 4. 边界与明确禁止的捷径

普通 call/INVOKE 不准以 ResumableBody 作 callee：它们不能表达 Start/resume target
或 body Suspend。C2.4 的专用 driver ingress/outcome 协议尚未接入；当前可声明
一个独立完整 body，但不能据此制造原 Python call→body 的自动连接。

FRAME_CONTEXT 与 caller token 不作普通 Region input、exit/completion/user payload，
也不能给未知普通 Operation 伪造这两种结果。前者只Initial/Detach产生并给Attach/
合法保存使用；后者只Attach产生并在当前 drive 逐边转发/Detach。普通未知effects
仍按原模型表达；上述 protocol 类型不是通用可伪造Python数据。

body kind、resume family 与 source/legal return 的对应仍须代码/协议见证；不以
声明 family 将未知 Reference 猜成 None，也不把一次 manual IR 图算合法 Python
源码或真实 generation 的证明。完整 C2.0、C2.4 与第一阶段仍未完成。

## 5. 自验收

- records/graph：严格类型、slot索引和逐边绑定、独占landing、当前域/精化及私有值。
- 正例：值/异常恢复、循环多次保存、local binding、多个当前state、当前context片段。
- 反例：漏保存、第二cut后间接旧值、旧world、旧片段、旧caller/未Detach、未知精化。
- 组合：INVOKE部分后态、C1 finally中yield、恢复原pending/context、fresh-before-yield、
  新异常真实Replace；scope/activation不因恢复重建。
- wire/query/CLI：新v10仅该body capability；原v1–v9冻结wire/reader不夹带新类型；
  结构验证与实际source/runtime/driver/transform权限分开。
- 独立反例复核、最终组件报告、冻结commit/source/fixtures后单次完整回归并归档。

本组件必须形成上述闭环才能宣布 body 结构已实施；不因仅有 enum/records 就通过。

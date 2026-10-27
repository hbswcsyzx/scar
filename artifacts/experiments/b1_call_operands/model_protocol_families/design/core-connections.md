# C2/D3 规范 core 连接审计（只读）

- 基线 HEAD：`08c4cbfc6b675919ab15e8654567889727f3c466`。
- 本轮仅源码/原合同/既有 fixture、test 和既有语言报告审读；未运行 Python、compile、pytest、LeWM、GPU、采集或安装。末尾 SHA 绑定所审文件；不是执行验收。
- **结论：通用 core 能保守保存这些家族的操作/状态/失败，但当前 typed C2/D3 关系尚不完备。已有 body/driver/lifecycle 的有限结构通过不等于全 family 闭包。** 缺少可声明并机械校验的关系是 M1 工作；真实运行自动恢复这些关系是另一 M4 工作，不能以“以后采集”推迟 M1 接口。

## 1. 先纠正 UNKNOWN / EXTERNAL 的归属

`drivers.py:42–53` 的 DriverRule 只有 `PYTHON_RESUMPTION_V1` 和原 ProviderFactReference，没有 UNKNOWN/EXTERNAL 枚举，也没有可写的 proof 开关。`driver_validation.py` 校验类型、原端口/状态/CFG，没有解析 `rule.implementation` 的内容或执行 provider。不同 fact 的关系也不由字符串相等或不等判定。

UNKNOWN 出现在 `queries.py:137–149` 的 LifecycleScope.applicability（恒 UNKNOWN），以及 `frames.py:46–77` 固定 FrameRules 的 condition_status/effects。它们**不会关闭结构校验**：合法声明仍可产生条件 E/F/P；但不能得到真实 callable、版本条件、对象 identity、native effects 或 transformation 权限。EXTERNAL 的 state/resource/外部实例含义不等于 DriverRule 的另一分派。fixture `program_driver_graphs.py:32–34` 用不可访问的 fixture fact 声明，正体现这一界限。

D1-only 有 DriverInterface 但没有 DriverLifecycle 时不派生 D2 scope；`queries.py:505–516` 保留此区别。`codec.py:201–232` 依既有能力选 v10/11/12/13/14…；已有 family enum 并未意味着新 family 协议已实现。旧 wire 不能静默升格。

## 2. 保留：已经有正确唯一归属的关系

| 范围 | 当前原记录/校验/查询 | 有限含义 |
| --- | --- | --- |
| body family 与 suspend flavor | `resumption.py:32–60`；`resumption_validation.py:154–161` | GENERATOR/GENERATOR_COROUTINE、COROUTINE、ASYNC_GENERATOR 与允许 YIELD/DELEGATION/AWAIT/ASYNC_YIELD 有匹配检查。不是完整方法协议。 |
| 持续 private frame 与新 shared state | Suspend.saved、ResumeSuccessor、SavedInput/ResumeInput；`resumption_validation.py:162–203` | 保存原 Use、最新逐 Location 输入、私有 landing。未知/缺保存不能变 NONE。 |
| 当前 caller context / C1 | `resumption_validation.py:235–289`；`test_resumption_cleanup.py` | Initial→Attach，当前 caller 精确转发，Detach 紧邻 handoff/terminal；active finally 的 pending/context 不因 yield 重建或 pop。 |
| raw 与 request object | `drivers.py:66–162`；`driver_validation.py:101–179` | raw 原序 Reference Uses；NEXT/CLOSE 0、SEND 1、THROW 1–3；AsyncRequestCreate 与 RequestAssociationRead 有真实 NORMAL 结果，保留 RAISE/current post-state。 |
| bound Create / Start | `driver_validation.py:125–158,250–252`；`queries.py:663–705` | 形参与环境 Reference 全分区 capture，状态不保存 creation-world。Start capture 是当前 instance-frame 的 recipe，不任选静态 Create。 |
| final gate / body frontier | `driver_validation.py:293–365`；`resumption_flow.py:17–60` | 私有 NORMAL landing 只有 Drive；独立角色 Use 精确转发，D 全域 NORMAL/RAISE 后态；首 Suspend/Return/Raise 完整分母，发散不伪造完成。 |
| body output / lifecycle | `validation.py:265–332`；`lifecycle_validation.py:71–129` | BodyDriveResult 从确切 static source 的原输出派生；enabled scope 每有限源有首 commit，owner 不借 payload 冒充。 |
| partial effect / release | `session_release_validation.py:76–114`；`lifecycle_analysis.py:26–31` | Session post 仅 ordinary AFTER 或 helper NORMAL，RAISE 留部分后态；窄 release 要当前 owner 的条件 F，非 held/free/ready 证明。 |

这些记录、SSA、原 producer/Use、typed completion 和 current-state 校验应直接保留，不另建协议值表、状态图或配置路径枚举器。

## 3. 需扩展 A：源码 family 与 raw→delivery→host adapter 的静态连接

### A1. family 的来源关系尚未闭合

`functions.py:25–52` 的 source FunctionKind 和 `ResumableBody.kind` 是不同接口；`EnvironmentInterface.code_definition`（`environments.py:79–100`）可定位原定义，但当前 driver validator 不将其连接至编译 code 的 family/flags 或原 source signature。`ProviderRegion/ProviderBinding` 已能保存来源映射，NativeBoundary 已能保存原平面槽（`providers.py:245–320`；`native.py:119–153`）；不得再复制源码/code registry。

**最小提议：** 优先从原 EnvironmentInterface.code_definition + scoped provider/source artifact 的确切 code record 派生 family 声明；对 source signature/compiled flags/ResumableBody.kind 不一致给具体 contradiction，未解析给缺口。源码版本、compile flags/future/optimization 属原 artifact；同 code hash 不等于相同函数环境/对象。缺“可校验的来源声明”属 M1；自动取得这些 fact 属 M4。

### A2. raw/latent 与 delivered payload 尚未关联

`driver_validation.py:101–120` 只核 pack/arity/owned References；`263–273` 只核 resume slot 类型；`333–346` 只把 gate 的 delivery input 精确转发至 Drive。**没有规则把 SEND 的 operand、NEXT 的 None、THROW raw 参数经某条 normalization 或 delegate completion 路线，连接到实际 SENT_VALUE/THROWN_PACKET/DELEGATE_* 槽。** Async 的 scheduler S 与 latent E 已区分，但 FinalBodyGate 没有 E 的显式角色关系，不能借 S 类型相同补 E。

最小字段/规则草案（非已冻结 class）：在现 gate/driver interface 上附一个有限 protocol-site 关系，定位原 gate 的 effective-request argument（BODY 可直接同 S；ASYNC 须真实 AssociationRead/原 producer）及 delivery slot 对应的**原**源端口：raw operand ordinal、真实 normalization 的 NORMAL packet 结果、或真实 delegate completion 的原 Use。全部实际值/结果仍从 invoke_arguments/CompletionResult/ExceptionPacketDefinition/BodyResumeInput 派生；不能存第二份 payload。

Normalization 能 callback/raise/reenter，必须是原 CFG 中真实 helper/INVOKE；不能统一前移、用 THROW 标签表示“已构造异常”或由 packet 类型声称异常 normalization 正确。已封存 raw-throw 和 delegate 语言见证适用范围保留。

**Created.throw 是实质接口边界：** BodyStart 当前无 delivery (`driver_validation.py:263–266`)，Create captures 又只能是已绑定 Python References。不得把创建后 throw 改成参数或 SEND，也不得伪运行未进入 body/finally。需冻结为“真实初入前注入/终结”的 typed no-user-entry 路线，或新增明确的 initial injection 接口；优先用版本协议的 no-body helper/原 RAISE 后态表达，不修改函数形参。Created non-None send/reentry 则是真实 rejection，不是 body Raise。

### A3. host adapter 目前是任意普通 CFG，未校验家族对应

`queries.py:707–739` 的 drive_outcomes/drive_bindings 只提供原 source payload/state；`BodyOutcomeSite.kind` 是 SUSPEND/RETURN/RAISE，不含 host 方法完成。随后 host RETURN/RAISE 是原 core 出口，但 validator 没有检查：

- generator Return.value → next/send 的 StopIteration.value，主动逃出的 StopIteration → PEP479 adapter；不能按异常名称吞掉。
- generator close 的成功 return 值、GeneratorExit、非法 yield/后续仍 Suspended，与一般 next/send 不同。
- coroutine AWAIT 的中间 scheduler item 与最终 await-expression/host 完成不同，允许零 suspension 完成。
- asyncgen AWAIT 对应仍活动的 request，与 ASYNC_YIELD 完成当前 item request 而 body 仍暂停不同；自然 Return 的 StopAsyncIteration 与 aclose graceful success 不同。
- closed 的 anext 与 athrow/aclose 不可套同步 generator 同一结果表；具体版本见已有协议分册和原见证。

**最小提议：** 一个有限的 adapter-site 声明引用原 `DriveOutcomeRef` 或真实 no-body/helper completion edge，加上原 owning helper Operation/Use 与其 NORMAL/RAISE 端口；按现 ResumableKind/RawRequestKind 和版本 profile 机械校验角色及覆盖。复用 NativeBoundary 原槽/ProviderBinding，不镜像一套结果 producer。真正 lookup/包装异常/释放引起的新失败保留自己的 INVOKE 及部分后态；不能强迫 adapter 都 completion-preserving。必须从真实 driver CFG 列出所有分支分母，而非只写一条“返回成功”的 relation。

## 4. 需扩展 B：delegate-only、no-body、取消与生命周期的闭包

### B1. delegate-only 可保守表达，但不是完整 typed 协议

当前 driver Region 可在 final gate 前沿普通 helper/INVOKE 返回，不触父 Attach/Drive；这符合原合同，不应人为要求每个请求进父 body。DELEGATE_REFERENCE 仅要求 Reference（`resumption_validation.py:165–174`），DELEGATE_VALUE/PACKET 仅给 ResumeSlot 类型；没有连接“当前父保存 delegate → 本次 delegate callback 实际 receiver → 产 item 或完成/失败 → 父是否恢复”。

**最小提议：** 复用原 saved delegate slot、父 instance/current state、真实 delegate 方法 lookup/INVOKE、原 item/exhaustion/raise completion 与实际 host/父 landing 的关系；显式保留“没有父 ingress”的分支。不额外制造 delegate 调用、父 Attach 或通用 permission token。直接 delegate throw/close 的 callback context 不能从父 saved context 复制：既有 CPython3.14.7四组见证显示与 next/send 所处上下文可不同。

### B2. no-body typed 完成目前仅 CreatedCloseTest→true→NoBodyFinish

`no_body_validation.py:73–100,123–156` 对应这一窄合同。Closed/no-body 返回、Created.throw、已有终态的外部实例等仍能用普通有状态 CFG 保留，但不能假装都是 CreatedClose true。`lifecycle_analysis.py:26–31` 要 release 前 F；entry 没 F，不能从 host exhaustion、request COMPLETE 或 FactRef 自证已终结。

若 D3 要在无本次 body outcome 的终态 observation 路径提供 typed lifecycle，需一个**真实当前 lifecycle read/guard 的成功 edge**与原 owner/state 的版本合同，允许条件 terminal 事实；不是任意 `finished=True`、历史状态清单或“同名close”推导。与 CreatedClose 共用 body-only publication shape，避免重写 E/F/P。重复窄 release 并非一律非法；它不是任意 bundle 的 destroy-once 证明。

### B3. cancellation 不需要新增万能 CANCEL raw kind

取消请求、scheduler 决定交付、实际 packet 构造、某次 body ingress、body 捕获后继续，是不同操作。可复用普通 state writes/INVOKE、原 THROW raw 与实际 THROWN_PACKET；若尚未交付则没有 body edge。不得把 resource WorkOutcome.CANCELLED、request对象完成或 host CancelledError 当 body finished。现接口能保守存所有这些操作，但尚无协议把 request/current owner/交付顺序及 host outcome 闭合。source/version 条件与实际 control edge 必须同时保留，不能只加 family enum。

### B4. 生命周期细节保留，不统一成一phase

现 D2 的 F（固定 no-reset 适用条件下已完成历史）与 P（当前 session 版本支持）必须分开；`session_flow.py:100–134` 触域 unknown/helper/body 默认 kill P，实际 SessionUpdate 重新建立。D3 不能把 P=COMPLETE 推 F；也不能以 body Suspend 推 release/占用释放。不同 native closed bit、continuation/frame存在、request step复用资格、session occupancy、traceback保活不可压成一个 phase。

窄 FrameRules 允许 callback/unknown effects、unraisable、可能不完成且不保证free；真正 raising wrapper 保留普通 INVOKE。body DEL 在 Attached 内、终态 frame relinquish 在版本合同指定位置、traceback 最后引用消失在以后，不能重复计量或移到同一清理节点。

## 5. 需扩展 C：动态 Drive↔持续 body activation 桥（M1，不是纯采集）

### C1. 当前明确缺口

ExecutionModel 已有 RegionActivation/ExecutionSegment/BlockVisit/OperationOccurrence/ValueOccurrence/ControlTransfer；ResumeIngress 精确指上次 suspension occurrence 与 successor（`coordinates.py:113–156`）。`flow.py:15–40,70–100` 保证 temporal edge 留在同 activation 并进入新 resume segment。它**没有本次 driver occurrence**。

CallActivation 不能顶替：`call_validation.py:300–303` 要原 static callee，`319–322` 一个 activation 仅一个同步 caller；BodyDrive 正确地没有普通 callee，持续 body 又可被多个独立 driver invocation 恢复。强行放开 CallActivation 将破坏同步调用完成/线程/一次 activation 合同。

`composition_routes.py:73–78` 明确保留 BodyDriveResult 的 static source Use，却把 `dynamic_occurrence=None`；现测试 `test_execution_composition_routes.py:139–150` 断言只有 driver activation。这是诚实的缺口保留，**不是已有动态 body→driver identity 路由**。`ExecutionIndex.formal_route`（query.py:181–195）遇 ResumeInput/BodyDriveResult 也仅返回原 marker，不能从它推 driver/body 实际对应。

### C2. 最小 Proposed 关系（不复制 actuals）

```text
BodyDriveExecution(
    drive: OperationOccurrenceID,
    activation: RegionActivationID,
    entry: BlockVisitID | Unresolved,
    outcome: OperationOccurrenceID | Unresolved,
    source: FactSource)
```

entry 的 segment 从原 BlockVisit 派生，无第二 segment 字段；Start/Resume/source 操作、formals/actuals/结果/状态全从静态 BodyDriveTarget、ProgramIndex.drive_input_bindings/drive_bindings、原 UseOccurrence 和实际 ControlTransfer 派生。不存 generation 计数或第二份 result表。新ID/唯一键形式待 root 冻结，不能假称已实现。

机械检查至少：

1. drive 发生必须属于声明的 BodyDrive；activation.region 必等 body_drive_target 的 body，run/process 相容。未知 thread/missing source是具体gap；若规则要求同步，同一次实际 ingress 的已知不同thread矛盾拒绝。不同drive可在不同时点/thread恢复同一body，不套同步 CallActivation 的全activation同线程规则。
2. Start entry 必是真 body.entry 的 visit/InitialEntry；Resume entry 必为指定 landing，segment.ingress 精确来自该 body.activation 的实际 Suspend occurrence+case，且原 temporal transfer匹配。不能由相同 site、相同 payload 或 source时间排序猜前驱。
3. 多次 drive 可复用同一 body activation但必须关联不同实际 ingress segment/visit；同一实际 ingress 不可被两个已声明 drive 重复认领。Created-close/delegate-only/拒绝没有此关系；不凭缺 link推“没有执行”。缺 link由公开查询保留missing。
4. outcome 属该 ingress 的本次执行段，遇首 Suspend/Return/Raise停止，static source 必在该Drive首frontier；driver实际 taken successor.source 必同它，不能缺边时补NORMAL。未完成/未采集是Unresolved+gap；发散无假terminal。
5. inputs：原 gate NORMAL current state Uses→本次 body entry/resume STATE formals；payload按resume slot；saved从精确前次 Suspend的UseOccurrence→本次恢复formal。Start Reference 仍需当前 instance frame captures，而非任意Create site。动态 formal 的 canonical producer 仍 BlockVisit。
6. outputs：实际 body outcome原UseOccurrence→本次driver taken BodyDriveResult landingformal；driver多余域来自它自己的独立forward Uses。INVOKE/BODY_DRIVE没有共同AFTER，逐edge保留当前post。
7. 关系只是已声明端口对应；不把两个ValueOccurrence合并成逻辑/对象identity，也不因匹配就授native/source/runtime权限。

**实例/captures仍需另一明确连接义务：** 多个Create同代码时，当前 owner Reference→哪个 creation occurrence/capture recipe/持续body activation，现仅有静态 InstanceCaptureInput。优先复用现 ValueDenotation 的 scoped ObjectRef/原 handle结果与上述 activation 的薄关联；creation 可 Unresolved/外部实例，绝不能猜唯一Create。不再造 ObjectID 或复制 captures。是否需要独立一条instance association，取决于 root冻结时能否用现denotation+source映射表达并校验；不能仅在文档里声称已连接。该声明接口属于M1，自动观察属于M4。

## 6. 需审查：完整验收分母与最小反例（均 Proposed，未执行）

| 组 | 必需正例 / 拒绝或缺口 | 当前依据 / 缺失 |
| --- | --- | --- |
| F01 source family | 正确code/body来源；source SYNC或错误compiledfamily不可无条件宣generator | source FunctionKind 与 Body.kind 未闭合。 |
| F02 raw delivery | SEND原operand与currentstate；换同类型delivery必须发现 | 现只校类型/转发；缺protocol relation。 |
| F03 raw throw | 1/2/3原参数，normalize callback/RAISE；delegate raw转交不提前normalize | 既有语言见证；typed路线未闭合。 |
| F04 created/reentry | Created send(None)；nonNone/reentry拒绝无bodyedge；Created.throw不伪入finally | Start无payload，需明确初入前分支。 |
| F05 host generator | Return.value / 主动StopIteration / close成功返回 /非法yield后仍暂停 | 源§7语义存在；host adapter未检查。 |
| F06 coroutine | 零挂起完成、一次/多次await、已耗尽/reentry、抛入与捕获 | body AWAIT可表达，adapter/request资格未闭合。 |
| F07 asyncgen request | 创建不驱动；AWAIT HOLD vs ASYNC_YIELD完成request；closed family方法差异 | AsyncRequest与Body角色有；post可任意声明，缺family核验。 |
| F08 delegate-only | throw callback产item不父Attach；exhausted/失败才恢复父，context正确 | genericCFG可表达，delegate/parent连接未校验。 |
| F09 no-body terminal | createdclose/closed/Createdthrow区分；无真实guard不得种F | 当前仅CreatedClose typed。 |
| F10 cancellation | 请求尚未交付、真实交付、body捕获后继续；不借workCANCELLED终结body | 通用状态可存，协议桥缺。 |
| F11 dynamic body | 两drive恢复同activation；错activation/旧Suspend/错case/错outcome拒绝；缺采gap | 新动态桥尚无records/validator/query。 |
| F12 capture identity | 同site两Create/外部实例；错creation不能按payload冒充 | Static capture recipe保留，但动态instance对应缺。 |
| F13 context/C1 | yield in finally，原pending/context/freshness；错caller/旧state拒绝 | 现有限tests可直接复用，不重写。 |
| F14 lifetime | body DEL/terminal drop/traceback保活、Session helper RAISE partial、unraisable vs宽wrapper | D2结构已有；家族native适用仍未证。 |
| F15 native expansion | 同一opaque call与展开region对应；禁止效果/时长重复计量 | 复用NativeBoundary/BoundaryRelation，多对多关联不等价授权。 |
| F16 wire/query预算 | legacy保守语义、未知来源/边/对象不抹分母、完整pending/cursor | 新能力需明确版本；当前v10–16不是family完成标签。 |

**建议顺序：** (1) 冻结F01–F16的原端口/来源矩阵与适用版本，不把Observed旧探针升级为全协议；(2) 补M1动态Drive桥及instance/captures必要关联；并行冻结A2/A3/B1/B2的静态关系而不是只加桥；(3) 按原Use/State/Completion接入有限protocol-site→delivery/adapter/no-body/delegate规则，先通用手工IR正反fixture；(4) 跨C1/await/request/closed/cancel组合和独立审查、旧wire守恒；(5) 之后才是真实provider/M4自动恢复与运行对照。任何一步不产生detector/backend或LeWM规则。

## 7. 旧证据范围与剩余风险

沿用 `model_driver_interfaces/review/lifecycle-language-review.md` 的8组CPython3.14.7断言见证，以及 `model_resume_interfaces/review/language-delegate-context-followup.md` 的4组额外delegate-context见证；没有重新运行或把其数量算本门已通过case。协议分册 `docs/model/PYTHON_CONTROL_PROTOCOLS.md:335–416` 还明确区分规范依据与本地有限样例。早期 M1_DRIVER_INTERFACES 的 permit提案已由V2 gate corridor取代，不能重实施旧候选token。

目前未证：完整source/code绑定、反射/interposition排除、真实callable/native版本对应、异步scheduler全状态协议、真实动态body identity/互斥/代次、完整采集、自动建图或LeWM优化。以上缺口不允许用“UNKNOWN”等于空效果或“所有family都有enum”关闭。报告是Source-inferred审计/Proposed设计，非新测试PASS。

## 8. 所审源码指纹

d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd  scar/ir/program/drivers.py
ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac  scar/ir/program/resumption.py
4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3  scar/ir/program/driver_validation.py
1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa  scar/ir/program/driver_flow.py
3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a  scar/ir/program/resumption_validation.py
c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc  scar/ir/program/resumption_flow.py
326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7  scar/ir/program/lifecycle.py
49dee4e82ebe09964a1a72c0d5d19fc91b67645822e7b1abc4961d13ba381daa  scar/ir/program/lifecycle_validation.py
22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea  scar/ir/program/no_body_validation.py
b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc  scar/ir/program/session_release_validation.py
153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7  scar/ir/program/lifecycle_analysis.py
13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387  scar/ir/program/session_flow.py
189a66e66e81eead682adeeaf316ce14af023f9b6c4a453e123f67adcfc2c89d  scar/ir/program/queries.py
985bdf491c4714a26180a2e91ca87e57170d9a4e49fa839147026648fb79e92f  scar/ir/program/validation.py
6c2cfdd03cbc4f70f32a7bf483f5914e406d10171821792bb5234e821750e336  scar/ir/program/codec.py
14e9c16d89db388793236a3636adaac0557c410a5c633c65f7558d413db029f8  scar/ir/program/environments.py
8410a92b3e9645fd765a6234aa8bf70816e265ad7b8c670b7adc94f0661cb026  scar/ir/program/functions.py
4c24a8719043778fdfaec6285c5b579a8855b6b0c8b31bde6c9ec2e81613cba2  scar/ir/program/frames.py
17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0  scar/ir/program/native.py
fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343  scar/ir/program/providers.py
14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126  scar/ir/execution/model.py
b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09  scar/ir/execution/coordinates.py
e1daa97f865ff2cbd934a2d5a581c302f3185bfbd9990726bbaf312201c444fc  scar/ir/execution/flow.py
ae13abeb29d54800a20bd15096a1d9b97a9fb8483e9235102c92035851a62372  scar/ir/execution/query.py
9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2  scar/ir/execution/call_validation.py
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca  scar/ir/execution/composition_routes.py
4a943058b1accf60e8be708c1770a958d914e77ef772a82f37065b296ca57f0a  docs/M1_DRIVER_CONTRACT_V2.md
94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699  docs/M1_DRIVER_LIFECYCLE_CONTRACT.md
1d42e97c34c7288067c867026369ee29db1725b4b9525a93204d5bc419a405b2  docs/M1_RESUMPTION_INTERFACES.md
e775feb2ef44e5f73fcdf94a963974a377e984b9c99a12e0231507bf4cb30c25  docs/M1_RESUMPTION_BODY_COMPONENT.md
4ce49de650d58d77dc78a5d98184b57739b28a1f721d68b31eb54c6da4b32a79  docs/M1_DRIVER_INTERFACES.md
538e126a57435f087880232eec21d45945c3315a034653dc3f524e11aedc0fd8  docs/M1_BODY_OUTCOME_FRONTIER.md
db0269f2fd50e9da3fde14986d4f1e69d19c0751f63f24661b53a1ed62c7707d  docs/model/PYTHON_CONTROL_PROTOCOLS.md

# 原 await 最终链：接口、Region 实现和实际发生

2026-10-19；基线 `f35939ad9d91572d51e1e0d3d928d6ecc0f0647c`。
上一轮为已验证进展：1551 focused、原 case/fixture 守恒、归档和远端 SHA 一致。
本轮继续[原 A–H/16/P5/M2](M1_P4_EVIDENCE_AND_NEXT_WORK.md)，不另定较小完成门。
根负责产品、文档、串行执行及归档；A/C 仅写各自新增 program/execution 两文件，
B 只读对抗审查。执行时全部作者冻结，旧 tests/fixtures/合同/codec 不改。

## 模型决定

五类实体不变。原结果提取 INVOKE E 保它自己的 OutcomeAdapter 合同、原 N/R、
最终消费者和原 scope；E 现在有真实 callee Region，内部有 primitive F（或
E→G→F）。E 确实实现该语义接口，不是只转发原 packet 的 H。子操作保自己的
输入、结果、状态与正常/异常出口，不附假 AWAIT_SITE/lookup/call；纯提取 helper
若加这种 scope，会人为制造它本来不承担的获取义务。

接口语义声明与实现连接独立：入口 packet 的 copy 不授 F 的输出 copy；F 每个
own N/R/状态结果是独立 source。必须核 F result→本 frame 原 terminal Use，
再沿该 frame 准确 parent_call 的真实 exit kind/full slot/landing position，
逐级返回 E 原接口结果及 caller 最终 Use。共享 callee 不选全局唯一 caller。
类型只能排除不兼容端口，不能证明相等。不按名字、class 或数值角色选唯一 F。

source-consuming frontier 是可能的实现贡献者，不等于该 primitive 的 native
语义已证。每个 required interface exit Use 的候选贡献路径为 OR，各个原出口
和 slot 的覆盖为 AND；额外日志/旁路/不用的中间计算不是必需输出 witness。
某个候选 copy=False 不自动证明整个实现错；原图合法的重新抛旧 packet、其他
producer 或转换可令它不贡献。保该候选的 False 和未覆盖输出的 PARTIAL，不
因缺少期望 witness 擅自拒绝整个程序。语义正确性、native 和 transform 仍未证。

## 查询视图（无新 wire/producer）

原 await consumer 新增 `implementation`；无 callee 时为 None。已知 E 的值含：

```text
operation / callee / entry_frame / frames / stages / outputs
inventory / status / gaps / cursor / flags

stage:
  key=(frame_key, OperationID), frame, operation, expanded, inputs, legs
  inputs保原全部有序arguments（含state），每项ordinal/actual/may/must/binding

stage.leg:
  原 edge/kind/own_result/payloads/signature
  results: 每个原 produced slot（含 state）的 source 与 paths

result.path:
  hops / interface_result / binding / targets / status / gaps

hop:
  frame / call / source / terminal:OwnedUse / kind / slot
  caller_result / landing_position / binding / choices

output:
  source（E 的原结果端口）/ kind / slot / edge
  terminals: 每个 E callee 原 terminal Use 与其 witnesses
  status / gaps
```

`result={source,slot,paths}`；`path.targets` 是 `{target,binding}` tuple。
output.terminals 每项 `{terminal:OwnedUse,witnesses,match,status,gaps}`。
known-callee stage 的 expanded=True，可展示自身结果映射，但不能以未展开的
内部结果代替叶子贡献来满足输出覆盖。状态 targets 只接原匹配 state 结果的
OwnedUse，不绑定到仅分组非状态 payload 的 HostTerminal。
inventory 保 enumerated_frames/checked_frames/frames_total、enumerated_stages/
stages_total、enumerated_outputs/outputs_total、known_inventory_complete/
proofs_complete/cursor。未完成关联总数为 None，已知原 E 结果键仍保留。

`binding` 是每 hop must-copy 的 AND；路径完整到 E 后才给 interface_result。
targets 是 E 对应原 consumer leg 的原目标与绑定，不把 Reference→packet 作为
普通 copy。所有 source/runtime/value/transform flags 仍 False。

执行 consumer 的 implementation 保原 definition，并增加：

```text
frames: {key, definition, call, entry, completion, inputs, status/gaps}
stages: {definition, occurrence, inputs, legs, status/gaps}
stage.leg: {definition, selected, results}
result: {definition, value, paths}
path: {definition, hops, interface_value, binding, targets, status/gaps}
hop: {definition, call, terminal, source_value, terminal_value,
      parent_value, binding, status/gaps}
```

沿 parent 当前后缀找到 E 的 occurrence，再逐 frame 准确 CallActivation→entry
下降，不扫描同 site 的其他 activation。每 hop terminal 必须是该 association
准确 completion；缺 association/entry/completion/Use/selected transfer 保 PARTIAL。
own N/R 未选腿保 NOT_APPLICABLE，未知选择不伪未选；状态与 payload 各核原端口。

## 预算与自主验收

同一静态 ConnectionContext 和 shared budget 贯穿原消费者、frame、逐结果、
terminal、返回路径和最终绑定。复用原 CFG/copy/index/CallReturns，不重写求解器。
逐层 path 复制及出口关联均收费；raw 原键与派生完整性分开，截断总数 None 并
保 cursor。禁止仅因一个好 witness 就忽略另一实际 terminal。递归/opaque/
partial bounds 有精确边界，不授完整库存。

1. A 新完整 program fixture，C 新 execution fixture；root 记录真实首红。
2. 先接源→完整 frame tuple→内部 own N/R→原 child terminal→逐 parent 端口→
   caller consumer。零/两 cut、depth1/2、两实例、N/R、同型错源、删 parent adapter
   和缺 child capture 均保原分母；错误 fixture 与产品错误分记。
3. B 有限对抗审查→作者冻结→受影响 focused，精确保旧1551 identities；失败保留。
4. 合账原 A–H 已有 selectors 与真缺项。随后原三路来源/BodyRaise/C1 后继组合，
   原16齐后才组件/full/P5/M2。当前工作不能代替完整第一阶段或自动 LeWM 建图。

不加 detector/backend，不做 LeWM 特例、GPU profiling 或性能结论；原两 checkout
保持 HEAD/status。完整 M0–M2 后按用户要求先汇报讲解，再停。

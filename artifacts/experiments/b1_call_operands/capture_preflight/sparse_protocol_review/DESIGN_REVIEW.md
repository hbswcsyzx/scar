# CALL 窗口采集协议审查

状态：**Proposed；只读设计审查，尚未实现或验收。**

基线：`/tmp/scar-call-operands-fe9ytsud`，冻结提交 `c91876b`。
本次只阅读代码；没有运行目标、重跑测试或修改产品、测试、gate、docs。

## 结论

新增 `CPYTHON_CALL_WINDOWS_V1` 可行，且不需要新增 event kind 或 metadata 字段。
它应表示“按静态规则选择 CALL 的操作数窗口”，不能表示完整指令轨迹、完整
程序依赖、纯性或已证明不存在窗口外效果。保持原来的条件与权限限制。

不能只在现有 collector 的 `_emit(INSTRUCTION)` 前加过滤：必须同时处理窗口
控制流准入与 pending attempt 失效。否则保留下来的连续行可能来自不同执行
片段，而当前 reader 的“下一条 caller 指令”失效信号也会消失。

## 1. 现有隐含依赖

1. `analysis/call_operand_reader.py:273`：每条 caller INSTRUCTION 清除 pending。
   `trace/call_operands.py:492` 同样在下一条指令发出
   `PROJECT_FUNCTION_CALL_DID_NOT_ENTER`。稀疏事件流不能继续将“下一条被保留的
   指令”描述成“caller 恢复的第一条指令”。
2. `analysis/call_operand_routes.py:185`：取本 invocation 最后 N 条 instruction，
   与静态窗口逐项比较。全量模式中插入的其它指令会破坏这个匹配；过滤后不会。
3. `analysis/call_operand_routes.py:139`：静态计划目前只逆扫 LOAD/PUSH_NULL/NOP，
   没有检查窗口内部 jump target 或 exception-handler target。
4. `analysis/call_operand_reader.py:191`：frame watermark 是单调上界和活动区间
   约束，不是已经执行的 caller 指令计数，不能填补上述缺失。
5. `ir/program/call_operands.py:322` 当前只允许旧 rule；历史报告重放最终按完整
   canonical document 比较，不能用新默认采集规则解释旧 raw 文件。

## 2. 最小规则

### 静态选择与执行证据

- 为 exact code fingerprint 构建不可变的窗口计划。选中固定位置参数 `CALL`，
  窗口包含完整 callee load、每个 actual 的有序 load occurrence、其间支持的
  PUSH_NULL/NOP，以及 CALL 本身。纯 LOAD/LOAD 融合指令保留两个 suboperand。
- 窗口内部（首指令之后，包含 CALL）不能是任何普通跳转或异常处理入口；窗口
  内部也不能有分支/跳转/其它计算指令。首指令可以是入口。异常表缺失、不可解码
  或未知 opcode 规则一律停边，不能仅检查 `is_jump_target` 而漏掉异常表。
- 离线依据已匹配的源码及完整 code 重新推导窗口和入口集合，不信任 collector
  声称的窗口或过滤结果。动态行必须逐项等于完整窗口、同 invocation/epoch，
  且全部晚于前一次 attempt。LOAD 的 namespace/slot/suboperand、CALL 的水印和
  dispatch/entry 关系继续独立检查。
- 每次执行静态选中 CALL 均产生 attempt，包括 dispatch 为 OTHER/UNAVAILABLE
  的情况；不能因为本次对象不是支持的 FunctionType 而静默省略 superseding
  attempt。是否可连接来源仍由现有离线 admission 判定。
- DISABLE 只能由 code/offset 的静态规则决定；不能根据某次运行的 callable、
  值、未绑定局部、pending 是否存在来永久禁用该 offset。此禁用是 code 级的，
  不能假定每次 invocation 自动恢复。

### pending、缺口与 hook

- 保留候选 CALL 的 normal continuation 与对应异常 handler 入口作为失效检查
  callback；它们若不属于保留窗口，可以不写普通 INSTRUCTION。若发现未消费
  pending，则清除并写既有 GAP。此类 offset 不能在第一次没有 pending 时就
  DISABLE。退出 frame 和新的 CALL 仍清除未消费 pending。
- 这不新增程序图节点或 wire event；只是保留清除 pending 所需的观察点。
  source/bytecode 无法建立这种失效覆盖时，该 CALL 窗口应明确不可准入。
- 成功 handshake 仍需唯一的原 v1 entry、同 PID/TID、直接活动 caller、准确
  CALL site、同 epoch、严格前后区间；entry 消费 pending。不能用相同 code、
  引用 token 或“最近 entry”修补缺失握手。
- 有意省略的非窗口指令不是 dropped event，也不应逐条发 GAP。真实的窗口
  缺行、采集失败、hook 干预、预算耗尽仍是 GAP/metadata loss，继续阻断受影响
  的正路线。不能为了降低行数而省略这些边界。
- base profile 中 hook/monitoring setter 检查不能随 INSTRUCTION 禁用而关闭。
  既有未证 hook 连续性和观察非干预条件全部保留；窗口之外不保证持续无干预。

## 3. 类型、历史分派与 CLI

- 明确 `OperandCaptureRule` 的两个有限值，或等价的严格枚举解析；wire 的
  `metadata.rule` 仍是原来的字符串字段。未知值拒绝，不能默认解释为 windows。
- 每 PID 以自身经过严格解码的 metadata.rule 分派；同一进程内规则不可切换。
  多 PID bundle 可以混合两种规则，不能以第一个 metadata 代表整个 bundle。
- `CPYTHON_LOAD_OCCURRENCES_V1` 保留旧 reader/route 解释与旧 wire 输出；新
  单入口检查只适用于 windows 分支。不要使旧报告因新默认规则而静默改变推导。
- raw schema v1 与 link-report schema v1 可以保持：新 rule 本身就是有版本的
  协议分派键，metadata 与其 raw SHA 已进入薄报告。重放从 raw metadata 选择
  规则，不能从当前 CLI/env 默认值选择。无需修改 SourceProgram/inventory。
- 新 CLI 提供 `--operand-capture windows|instructions`，仅与 `--call-operands`
  一起有效。新门通过后默认 windows；instructions 显式保留诊断/历史模式。
  命令证据与 metadata 都记录选择，未知 env 值拒绝。旧 archive 重放不依赖
  用户补参数，也不重写 archive 的 rule。

## 4. 预算不放宽

- events/event_attempts/bytes/loads/references 仍严格计量实际尝试和写入的 sidecar
  rows。未选择的 opcode 不分配 event index，不计 dropped_events。
- 静态计划必须有独立可解释的有限扫描成本：当前 `_plan` 用 max_events 约束
  累计 examined instructions，可沿用，但应计所有扫描过的指令，而非仅计最终
  保留窗口。失败不反复免费重扫；不能缓存大量应用 code/frame/operand 强引用。
- 不新增 metadata 字段也能实现上述保守静态上限，须明示它与 row 数的不同
  含义。每 instruction 的 max_loads、namespace 扫描、弱引用 live limit 以及
  reader aggregate ceilings 不变。
- 真正执行大量受支持 CALL 仍可能耗尽预算；windows 不是无界采集的保证。
  达上限的 trace 继续明确不完整，不能以压缩采集为理由撤销 loss 阻断。

## 5. 有限验收反例

1. 原始两文件、多层实际调用，两种 profile 都穿过同一次
   `leaf(shared, shared)`，保留两个 actual Use/occurrence，只追被返回的位置。
2. 大量无 CALL 的内联 comprehension 后再执行支持调用：windows 不为每次迭代
   写普通指令行，后面的真实调用可查询；不声称 comprehension 无效果。
3. 跳转/异常 handler 从外部进入窗口内部，以及先执行半个窗口后异常离开、
   再到 CALL 的输入：离线拒绝拼接。首指令重新完整执行则可重新形成候选。
4. project function 绑定前 TypeError、异常被捕获后继续调用；未消费 attempt
   必须取消。后续同 code、同 CALL site 的循环迭代不能借用旧 attempt。
5. 同 code 第二次 invocation/递归/另一线程：不能因第一次 DISABLE 决策漏掉
   必需窗口或失效检查；重复 CALL 产生独立 attempt/entry。
6. 窗口缺首/中间/末指令、GAP、hook epoch 变化、缺 sidecar、真实 row 预算
   耗尽：均无正 route。合法非窗口省略不伪报成 collection loss。
7. 纯 fused LOAD/LOAD 支持；mixed STORE/LOAD、star/keyword、closure/attribute
   和未知 opcode 仍具体停边，不通过更宽松的 filtering 算法“恢复”。
8. 旧完整 report 原样重放；新规则 report 独立重建；metadata.rule 未知/篡改、
   多 PID 混合规则、错误 frame watermark/entry anchor 均按各自规则核验。

以上是下一门的设计要求，不能替代生产采集、公开 link/check/query 与真实来源
范围核验。新规则不建立环境、内容、效果、完整程序或变换权限。

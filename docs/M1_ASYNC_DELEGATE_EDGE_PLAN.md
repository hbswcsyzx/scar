# N1 / N2：当前 item 与 delegate 原结果的有限验收

2026-10-19；原始基线 `601faf6dc93e594b4542bcd58513e42c569d8ded`，
开始时工作树干净、远端已同步。上一 goal turn 是 progress：原 G 结构关闭，
1780 affected focused、原1747 identities 保留、归档/提交/远端核验完成。
本轮承接[下一组计划](M1_PROTOCOL_NEXT_GATES.md)的 N1/F17 与 N2/F21。
原 G 的关闭保持；其他 A–H、十六组的各自残项、P5 和 M2 原113构造/196字段
保持完整范围，不以本单位替代完整阶段。

## 1. 由模型决定关系

五规范实体仍是 Operation / Value / StateLocation / Region / Resource。
一项请求的后态、一个 body 的暂停、一次实际导出的值、一次 adapter 新产出的
值及其 packet 是不同关系。完成状态不证明输出来源；内容/类型相同不证明
两个原 Value 或两个 occurrence 是同一次结果。声明、静态路径、实际捕获、
native/source 适用与变换权限分别报告。

同理，delegate 调用的 own RAISE 与随后提取器的 own RAISE 有不同的原端口。
状态按准确 completion ordinal / StateLocation 传递。LiteralOrigin 的 None
可支持分流条件，不能授 runtime object 身份，更不能因 falsey 就丢 SEND 参数。

## 2. N1 / F17：精确当前 item

复用现有 async_pipeline_program / async_pipeline_execution：一个持续 B、
同一 request、三个真实驱动，前两次 AWAIT→HOLD，第三次 ASYNC_YIELD→COMPLETE。
不重建 session helper，不用不支配跨 cut 值制造假的协议负例。

- 静态：先完整 core/协议正例；准确当前导出→adapter 原输入；adapter own
  产出→packet 的原 component→实际 host。分别替换可合法引用的同型旧输入和
  旧包，core 必须先合法，再由准确的来源/消费者关系拒绝。旧值须有原来源与
  支配合法的 copy 路线；若仅是 UseOccurrence 与静态 Use 不同，则如实是
  core 错接，不伪报新的协议能力。
- 动态：保原一 B/三 segments/实际 Drive 和 ResumeIngress；当前 item 的
  输入、adapter、packet、host 的确切 Use/Value/call 记录不能借旧发生或缺采。
  不把静态 DECLARED 当动态事实，不从同型或相同内容选择 producer。
- 与既有 F17 的 HOLD/COMPLETE、body 暂停、AWAIT handoff、当前 state、共享
  incoming、删除、budget、缺采、fresh catalog 合账。F16 reuse、F18终止、
  F19 closed/version、其他 X27 家族是独立原要求，不凭空扩张 F17。

## 3. N2 / F21：三个具体缺项

复用 method_lookup_program、continuation_site_program 与现原 lookup 插入器。
必要本地变体仅写在 NEW 单元文件，不改旧 fixture。

1. SEND(None)→NEXT：原 pack 增准确 Reference literal operand，raw definition
   为 SEND；真实 NEXT lookup 和零参数调用保持。None 全图合法；known nonNone
   不能走丢参数的 NEXT。另有合法 SEND(nonNone) 原 ordinal0 正例，不将其拒绝
   错说成整个 nonNone 不能执行。保原 N/R/state/expected source。
2. advance 自身异常：NEXT 与 SEND 各保真实 lookup N/R、advance N→item 与
   advance R own whole packet/state→host，exhaustion=False，不制造 extraction。
   错换 lookup own R 与旧 source 必须拒绝；全 completion kind/slot 不混。
3. 旧 item 冒最终值：现 method_lookup_loop_program 的 previous Ref 已有完整
   seed/header/backedge。仅将回边原 carrier 接到真实 advance NORMAL item，
   使其成为支配合法的前次结果；基线仍用提取 own N，负例用 previous 替它。
   不从本次互斥 NORMAL 臂跨引到 RAISE/extraction，不假造 core 无效图。

保原 F21 next/send lookup/call/result/state、异常/缺方法、item/final、whole tuple、
重求值、删附件和 budget 既有 selectors。按原条目全部核齐才关闭 F21 结构格；
动态其他家族的实际发生仍归其 X27 原要求，原权限 False 不单独撤销结构能力。

## 4. 作者、执行、验收与版本

先三路只读检查，确认原端口和拒错层，再授权写入。

- A：仅 NEW tests/unit/test_program_delegate_next_send_edges.py；约6必要
  nodes，必要 helper 同文件，不增 family / schema。
- C：仅 NEW tests/unit/test_program_async_current_item.py 与
  tests/unit/test_execution_async_current_item.py；复用原三 Drive 图与捕获。
- B：独立原 F17/F21 条目→精确 selector→真实残项审查；先只读；不得交叉写。
- root：产品、文档、所有 Python/pytest/probe/compile、归档与 Git。作者全部
  SHA 冻结后串行运行；每次命令/日志/JUnit/源码前后清单独立不可覆盖。实际
  首红、作者 oracle 错误、产品缺陷分开；只修复真实公共关系问题。

先有限新例→必要公共修复→一次独立有限复审→作者冻结→原1780 identities加新增
的 affected focused→原 tests/fixtures/codec/合同/旧归档/两原仓库 HEAD/status
核验→提交/推送/远端SHA。已足够验证就停止可选复测，原16全齐才组件/冻结full。

当前不新增 detector/backend、LeWM 特例、native/GPU profiling、Tensor 数值捕获
或新的性能结论。N3 close/C1、其余原家族与自动任意源码恢复仍按各自阶段推进。
证据目录：artifacts/experiments/b1_call_operands/model_async_delegate_edges/。

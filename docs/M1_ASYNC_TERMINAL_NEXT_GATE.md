# 下一个原验收单位：F19，随后返回完整阶段门

2026-10-20。仍只做第一阶段建模；无 detector/backend 或 LeWM 特化。
本门记录参见 [计划](M1_ASYNC_TERMINAL_PLAN.md)、[实际过程](M1_ASYNC_TERMINAL_PROGRESS.md)
和 [验收报告](M1_ASYNC_TERMINAL_ACCEPTANCE.md)。F18 的限定结构验收不能替 F19。

## 1. 保原分母

原16族中，F18 完成后 F12/F13/F14/F15/F16/F17/F18/F21/F23 条件性结构接受；
F19/F20/F22/F24/X25/X26/X27 保持原要求，await A–H 不重开也不代验其它族。
P4 component、冻结 full、P5 和 M2 原113构造/196字段没有因此关闭。
最终整个 M0–M2 阶段成立时，再停下来向用户讲解类型、连接、建图和局限。
自动 entry→Python shell→现成 FX/Export region 连接仍是后续恢复门；不拿手供
fixture 数量冒自动拆解任何程序或整个 LeWM 的比例。

## 2. F19 先审原证据，再冻最小合同

复用本门 native-probe 的实际22条调用/两条编译观察与固定 CPython3.14.7源码。
这些不是 IR→本机源码/二进制对应证明；不重复相同基础实验，也不先新造profile。

只读 G0 对账已定位三组原缺口：

| 已有准确入口 | 目前能证什么 | F19仍缺的组合 |
| --- | --- | --- |
| `test_program_async_completed_reuse.py::test_completed_request_reuses_exact_r_and_latest_states_then_rejects_without_a_second_drive` | 同R两次调用/一次Drive、准确旧状态与own失败包；B是external | 真实BodyReturn/BodyRaise→F→新R athrow/aclose的无Drive链，不能把同步GENERATOR profile当async覆盖 |
| `test_program_async_connections.py::test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state[CLOSE]` 与 async_scheduler_packets 的later-scheduler测试 | L/S的CLOSE原包、ownN/R与状态；普通async pipeline跨AWAIT | 同R GeneratorExit→cleanup AWAIT/HOLD→实际恢复→body terminal→close reply |
| `test_program_async_connections.py::test_suspended_body_is_not_finished_when_its_async_request_completes` | 已拒request complete→frame finished/误释放 | 尚无async fixture实际贯通ASYNCGEN_CLOSE_YIELD_ERROR、同R重试/新R回复/同B finally续体及真正终结 |

固定 `reference-genobject.c.txt` 2108–2140 的顺序先R已关闭，再frame finished，
之后才active/ag_closed。finished-frame新request与illegal-yield后frame仍悬挂的
新request在本机已有不同回复，不能把两组控制路径合并为一个IS_CLOSED bool。
这些完整组合各自的删附件/缺采/budget也仍需供采；既有组件绿测不填未组合格。

1. **实际已结束的 B**：新 athrow/aclose 的无 Drive 回复，与新 anext/asend
   不同；同 R 重用单独拒绝。原 raw 参数、own N/R、当前全state、host出口需连全。
2. **graceful aclose**：准确原 GeneratorExit 来源、body handler、实际terminal
   和 request reply；允许 finally 中 await/handoff 后同 R 恢复，不假定一次驱动即结束。
3. **illegal close-yield**：同 R 失败重试、新 R 请求、同 B 仍有 continuation，
   之后真实恢复 finally 才终结。保错误 constructor own N/R、wholepacket 和 state。
4. **完成/释放**：Frame 实际终结证据 F、request complete、active session、
   native ag_closed 位是不同依赖。native位由普通状态地址/版本建模，不能从
   request complete 推 FrameFinished，也不能把 inspect AGEN_RUNNING 当正在执行。

针对上述完整原单位，只补已证实缺失的原操作/端口/连接。新native合同若确有
必要，先写明确版本和源锚，再实施；可以用既有类型则不增核心实体。

## 3. F19 自验节点

- G0：列已有 selector、准确缺口、原单位条款与机器可查映射；不重做已覆盖基础。
- G1：SourceSnapshot/provider/native applicability 与实际发生分别列证据，UNKNOWN
  写出准确缺哪个端口/版本/附件，不让 optional consumer 删除原 source 分母。
- G2：静态原 input/state/own completion→host 与动态 exact occurrence、raw、request、
  body、continuation 一致；同型旧包、旧state、错R/B、错误F/release 必须拒绝。
- G3：删附件、单实例缺采、tiny budget 保库存/原义务和 cursor，不借完整兄弟。
- G4：全体作者源码冻结，root串行运行有限反例和一次完整 affected selection；
  旧身份守恒，保所有首败、源码、命令/JUnit和独立复审，正常commit/push核远端。

F19 之后逐个完成其余原族，回到 P4 component/full、P5 和 M2 原清单；只在原
验收条件真正满足时关行。测试时间不作程序性能数据，当前没有可信 LeWM 自动
变换或加速比。原始程序 NO-OP 仍是合法选择，但它不代表优化目标已经完成。

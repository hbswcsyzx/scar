# 回到原 P4 分母：已有证据与下一完整交付

2026-10-19；只读总审后的执行顺序。不是新增 helper gate 或缩减第一阶段。
原分母仍是 [F12–F24/X25–X27](M1_REMAINING_PROTOCOL_PLAN.md)、完整
[await A–H](M1_AWAIT_COMPOSITION_PLAN.md)，然后 P5 和 M2 的 113 构造/196 字段。
下表是证据定位，**不是本轮统一验收逐行通过的收据**；16 行均尚未关闭。
已有 supplied-model 测试不能证明 source/native applicability、完整 capture、
自动整程序建图或变换授权。

## 一、16 组原义务，区分已有测试与真缺口

| 原编号 | 已有测试入口（`tests/unit/`） | 剩余连接/验收，不重做已有内核 |
| --- | --- | --- |
| F12 | `test_program_await_general.py`、`test_program_await_qualification_flow.py` 及对应 execution。 | 将获取/资格/合法失败与完整最终链合账；保持源码/native 适用条件，不以类型猜成立。 |
| F13 | `test_program_await_resume.py`、`test_execution_await_resume.py`、outcome/failure。 | 跨 callee 真正 extractor、其 own N/R 和最终 consumer 的语义与实际发生组合。 |
| F14 | generator admission/reentry 的 predicate/branch/current-state 内核。 | coroutine 自身 phase、重复 await、throw/close 后果不能借 async request predicate 替代；补专属连接矩阵。 |
| F15 | resume 中同 B 的 direct/await；wrapper 中 W/held B/Drive。 | `await_body_links` 选中路径不能替代独立 direct 来源桥；三路到完整终点合账。 |
| F16 | async connections 的四 request kind 和 latent/raw/admission。 | 四种 request 首次发送、复用/竞争均接准确实际 occurrence；角色 R/B/S 不混。 |
| F17 | async pipeline 的同 B、三次 Drive、两次 AWAIT 后 ASYNC_YIELD。 | 与四 request kind/错误后续共同核本次 session 与最终消费者；不把 item 当 body 完成。 |
| F18 | generator stopiter/close contracts、outcome/constructor failure。 | 原 BodyRaise 与自然完成、非法 return 的完整来源/适配/消费和实际发生合账。 |
| F19 | generator close retry/admission 中 closed 和覆盖/抑制。 | 版本限定 athrow/aclose、失败后续到 P3 occurrence；不能以 native closed bit 授 release。 |
| F20 | method lookup connections。 | 已有 initial-next 用例保 `continuation_source_unresolved`；首次 advance 来源桥与 lookup 异常类别仍须精确处理。 |
| F21 | bound-method own N/R、receiver/raw ordinal、continuation。 | NEXT/SEND 首步与后继直到 item/最终值的完整当前状态/consumer 合账。 |
| F22 | packet continuation edges、pending cleanup。 | THROW 原 1–3 参数及 E0/EL/EM、exhaustion/缺方法路径接实际 occurrence；保无 parent Drive 的情况。 |
| F23 | 同上及 close/Replace/覆盖内核。 | 本次 close 成功旧包继续/失败新包覆盖、context 和父后继接准确 occurrence。 |
| F24 | cancellation request/delivery/handler/status。 | `cancel_waiter_forwarding_unresolved` 不计闭合；补 handler 抑制/cleanup 再 await 或最终状态整链。 |
| X25 | active C1 跨两 cut、旧 payload 与新 Raise、state/context 拒错。 | 接入 await/delegation 最终链；不能用静态 pending 测试替代逐次执行关联。 |
| X26 | publication/session/release 与 partial RAISE、selected edge。 | 把取消/失败后继、当前 session 和准确 release 接成同一整条路线。NoEntry 跨 known-return seed 精化仍有限制。 |
| X27 | async pipeline/P3 的准确 activation/segment/entry/outcome。 | await 真正 child extractor、四 request、delegation/C1 等剩余家族逐次组合；缺采不缩分母。 |

## 二、下一完整交付：最终结果链，复用 D4/D5/D6

1. **先合账。** 把已有 self 零/两 cut、同 B direct/await、多 Create、旧状态拒错，
   以及 general/W/shared incoming 的准确 selectors 填回原 A–H。已经测过的局部
   连接不再笼统写成未实现；最终链尚断则保具体缺口。
2. **静态语义连接。** `program/await_outcomes.py` 目前仍只遍历旧
   `ledger.support`，final row 又要求直接指本 advance 的 `ContractResult`。
   D6 child extractor 的准确 Use 已在图里，但未成为最终提取义务。沿原完整
   frame tuple 接真正 extractor 的语义合同与 own N/R；纯转发 H 不是 extractor。
   先核原 region/scope 外键能否自然表达，不能伪挂合同。
3. **实际发生连接。** `execution/await_outcomes.py` 与 outcome evidence 目前以
   advance 同 activation/segment 后缀定位 consumer。沿 D6 frame 对应的准确
   CallActivation 下降，核 child 的本次输入、own N/R、出口和回 caller 的 final
   Use；缺 child/selected completion/return capture 保原义务，不能借 sibling。
4. **完整来源/C1 组合。** 将 native/self、general、W 三路已测来源接到零/多 cut
   和真正 BodyRaise 终点；复用 pending/port/Replace/Resume 处理两 cut 后继。
   现终端查询的 CleanupRoute/Dispatch/Suspend 边界不算最终消费已闭合。
5. **自验收。** 独立正反例→root 串行首红→修具体公共连接→冻结源→原 A–H
   用例合账。随后只补表中真缺项；原16齐后才整组件/冻结 full、P5 与 M2 总核。

不新增 detector/backend，不以 LeWM 名称/变量名/函数名选规则，不扩新状态图。

## 三、M2 与工具复用的边界

M2/T1 应按原 113/196 catalog 逐字段核唯一 phase、有序 Use/result/binding、
state/effect、隐式调用及 N/R/cleanup/resume/resource 接口。复用已有三分册和
编译见证，只为真实不能表达或漏拒错补 core；不把完整 Python 编译器作为前置。

source/code 归档及 `inventory-program` / `model-program` 已有有限入口。
FX/Export 子图、ETO/Profiler 同 run 对应、LibCST/CodeQL、TorchLens 等的具体
接口和复用设计见 [MODELING_INTEGRATION.md](MODELING_INTEGRATION.md)。完整
adapter/replay、跨 loop/environment/call 自动合图和实际采集仍在 M3/M4，不能拿
设计或 supplied IR 宣称已自动覆盖 LeWM。第一阶段 M0–M2 完成后按用户要求先
汇报讲解，再停下，不自行跳到化简开发。

# N3：close/C1 的下一次连接审查

2026-10-19；N1/F17、N2/F21 最终回归期间完成两路只读检查。这里记录下一门
原要求和具体起点；不把源码判断写成已复现缺陷，不增加家族分母或新 backend。

## 1. 原控制库存与可选输入声明

**源码 Observed，public API 首红待测**：当前 continuations 的 close-route
查询在可选 input cases 循环中调用。删除全部 DELEGATE_CLOSE inputs 后，原
两条 N/R Operation obligations 仍在，但其 close_routes/C1 后继视图会失去
遍历入口。单删 consumers 附件沿原输出 Use 库存处理，是不同接缝。

最小反例复用 packet_continuation_program(two_cuts=True,
complete_transitions=True)，保原 scope、两 close rows、CFG、cuts、pending
definitions，仅删该两 exact sites 的 inputs/consumers。要求先 core/full
合法，再按原(scope,clause,operation,slot)、selected completion 和原 landing
保两腿真实 C1/host/端口义务；没有声明不能定义库存分母。

RAISE 的源仍为 close own wholepacket。NORMAL 的源是独立原注入包，不是
close own None。缺注入锚时标记源未知，不能从实际 pending payload 倒选期望
来源自证；该腿的原控制目标仍须保留，bindings不授True。优先在现 walker
分开原控制/possible-port枚举与 expected-source 证明，不另起 producer 图。

## 2. 动态捕获必须真的有驱动

现 packet fixture 虽有 P 两个真实 Suspend/C1，却没有 BodyDrive 或外 driver。
`finally.invoke` 是 callee=None 的原 primitive INVOKE，不能编造 helper
CallActivation 或把该声明图当完整运行发生。

可复用原 driver_program / _driver_part / _Builder 和现持续 activation 捕获
方法，为 P 供应真实外壳：Start → DELEGATE_PACKET Resume → SENT_VALUE Resume，
共三次 Drive、一持续 P/三 segments。保持 P 的 pending/saved/context、cuts
及原 N/R CFG。外同步 D 各有独立 activation/segment，经真实 CallActivation
返回；primitive close 自身不因此成为新的 callee。

anchor 位于首次 resume：completion cursor 的 cross_resume=True 应只含 P
后两个 segments；False 应在第二个 Suspend 停止。不能把三完整 segments
都断成 cursor 的起点后缀。await_cleanup_final 的固定 SEND/value 外壳会改变
DELEGATE_PACKET，不能原封复用然后声称表达了本协议。

## 3. 来源许可的有限假设

**Inferred，仍须真实反例**：RAISE 原 own fullslot0 的选中结果已由 generic
cursor 许可；NORMAL 延续先前 InjectedPacketTrigger，目前可能保留
completion_source_anchor_association_unproved。不得全局允许同 activation 的
任意值，或将任意 forwarded Use 变成来源权限。

若实测需要修复，窄接准确 close NORMAL/原 input case/原 packet-forward Use
与实际 guard/copy 的关系；保 own None、原注入、新 own R、current replacement
分别有源。原 R 的 selected signature/slot 路径不放松。没有证据时保持未知。

## 4. 自验与版本节点

1. 先原端口/原分母合同与最小供应图，作者冻结后 root 实测首红，分别记录
   作者构造问题与公共关系问题；真字段阻断先写清，不直接扩 schema。
2. 两 completion 正例到真实 C1/current parent/host；整 inputs/consumers删除
   保原 N/R 库存和缺源说明。已有 opaque/预算/替换反例保留，不重写 helper。
3. 有准确实际 Drive 的动态图核 N 原注入/R own新包、full slots/current state；
   实例局部缺 pending Use、Resume transfer、terminal Use 不借 sibling。
4. 原1793或最新已验 identities、旧 fixtures/合同/codec/归档/保护仓库守恒，
   充分定向验收、报告、checkpoint、commit/push及远端核对。

本门仍受原 F23 与 X27 分工约束；其他家族、P5、M2 不代关。真实执行和自动
源码恢复不由供应图授予，M0–M2 真正完成后先按用户要求讲解模型。

# N3 close/C1：执行记录与原义务

2026-10-19；基线4ac61ec63161dfdb9e66fc5a51ce2df02453b5ea。
[冻结计划](M1_DELEGATE_CLOSE_PLAN.md) SHA
7a7d9411d23e00070ce51164e1511a416277bb5296b9b22820ea5175ef700706。
上一节点1793项受影响定向通过；F17/F21、原 G 的条件结构验收保持。

## 原模型与待测问题

原 Operation/CFG/SSA 决定两条 selected completion 及其实际后继。inputs 和
consumers 是来源或消费说明，删除它们不应抹除 C1、projection、host 库存。
NORMAL 原注入包、own None 与 RAISE own 新包分别有源；未知原来源不能从
实际消费者反选。结构、实际捕获、自动恢复和变换权限分开。

只读检查指出 close route 在可选 case 循环内建立，缺注入 trigger 时提前
返回；随后 public API 首测已真实复现整附件删除导致 route 消失。两作者仅写
新的静态/动态测试文件，原 fixture/合同/codec不动；root 独占所有实际执行。

独立复核曾把 shared 块的旧 RAISE 名字误当 close 的互斥异常腿。实际两条
selected completion 都经各自 jump 到 shared=finally.failed，再经共同
failed.jump 到第二 cut。该误读已在计划冻结前撤回，未据此改图或执行测试。

## 验收边界

原 F23 四条静态条件结构已有准确 selectors；本节点补整附件删除与 X27 的
delegate-close 实例发生交叉。只在本轮真实证据齐备后关闭 F23，X27 剩余
家族、其余原组、A–H、P5、M2 仍按各自原要求。不产生自动 LeWM
建模、性能提升或新变换结论。

## 由模型落实到代码

1. **Observed → Implemented → Verified（本门结构范围）：原库存不随附件消失。** 缺
   inputs 的 close row 仍从自己的 selected completion/landing 枚举 C1 与
   host。RAISE 用 own packet；NORMAL 缺独立注入锚用原 StaticProtocolGap。
   原初来源 binding 为未知，而原 target/action/projection/第二 Suspend
   库存不减。消费者附件删除沿原消费者分母报告缺项。
2. **Observed → Implemented → Verified（本门结构范围）：未知与矛盾分开。** unknown
   root 遇合法 CleanupReplace(RETURN) 原被判 CONTRADICTED。原 walker 现从
   准确 current token 单列显式 replacement 的 current source/role，保旧
   root gap 及该接缝的独立 None binding。Enter/Resume 不取得这项许可。
3. **Observed → Implemented → Verified（本门结构范围）：输入来源与 own result 分开。**
   实际 close NORMAL 的旧注入包不是 own None。动态许可限准确 typed row/
   input case、独立原 formal、准确实际 visit/最近 incoming guard，以及此
   NORMAL edge 的 wholepacket forward Use。现有 copy-pair 必须 True；任意
   同 activation、同型或 forwarded 值不够。own R 精确结果槽许可保持。
4. **Observed → Implemented → Verified（本门结构范围）：缺采不崩溃。** 保留的原
   UseOccurrence 可含 Unresolved，而不是只有“缺 Use”一种情况。真实反例
   已复现 AttributeError，现保 PARTIAL/association gap，不借完整 sibling。

不支持的输入来源 port 形式仍未知；这次窄许可直接支持声明的 BlockArgument
原来源，没有宣称所有 source port 或任意源码已自动恢复。规范 Program23/
Execution8 记录及 codec 未扩型，也未新增第二 provenance 图。

## 真实尝试

全部尝试保不可覆盖 command、stdout/stderr、JUnit、源码前后清单与实际用时，
目录 artifacts/experiments/b1_call_operands/model_delegate_close_continuations/。

| 尝试 | 实际结果 | 区分真实缺口与作者错误 |
| --- | --- | --- |
| first-red | 1P/3F，851源码稳定 | 整附件删无close_routes为产品红；动态2例是新helper `_use`名称遮蔽，未构造图。 |
| after-inventory-fix | 2P/3F，851源码稳定 | 原两删除例P；unknown root→RETURN Replace真实伪矛盾；动态是重复带入P literal的作者合并错误。 |
| after-current-replacement-fix | 2P/3F，851源码稳定 | RETURN例P；切换current时遗漏unknown root receipt被原删例抓住；动态是遗漏host最后未选NORMAL块的作者错误。 |
| after-root-receipt-fix | 4P/1F，851源码稳定 | 三静态+实际R正例P；N图/捕获合法且copy True，root association仍未知，是真许可缺口。 |
| dynamic-first | 13P/1F，851源码稳定 | N/R、三类×两实例腿缺采、两错源均P；合法Unresolved转发真实崩溃。 |
| dynamic-after-unresolved-fix | 14P，851源码稳定 | 全部新节点通过，未改oracle/原fixture。pytest8.85秒，runner9.621311208233237秒。 |
| verified-final | 1807P，0F/E/skip，851源码稳定 | 原1793准确identities全部保留+新14；pytest585.74秒，runner586.7159442473203秒。 |

新14项与最终1807项使用同一源码 SHA
`c7373a306d72103c8bedd56679a0d2ef4d35fb784e47dca95a68e16fe0a8a123`。
具体失败版本 SHA 在每次 result/source 清单，不将失败尝试从记录中删除。
这是受影响定向集合，不是完整component/full回归或LeWM性能benchmark。

## 逐原条目合账

| 原 F23 要求 | 保留与新增证据 |
| --- | --- |
| N 续原注入，R own 新包，None不是包 | 原 continuation close 正反例保持；新实际两腿及 two wrong-source 反例独立核 root/current binding。 |
| 当前 pending/context/C1 replace 与最终host | 原 cleanup/packet两cut selectors保持；新三Drive、一持续P、实际CallActivation及P→D→caller全结果/当前state槽。 |
| 不统一Attach，不臆造父Drive | 原 delegate-only/Attach失败selectors保持；新P真的有三Drive，但 primitive close保持无callee，不造helper CallActivation。 |
| 真实opaque/预算边界 | 原 packet continuation 与callee-opaque/select-port/budget保持；未将缺路径或截断当作成功。 |
| 整附件删除及X27本族交叉 | 新两删除变体保原两selected库存；三类缺采×N/R、Unresolved、两实例不借用，静态声明不代替实际发生。 |

独立复核在14项通过后未发现额外有限M1结构阻断，最终同源1807回归通过。
checkpoint逐原selector核准确JUnit identities、旧测试/fixture/合同/codec/归档
字节和两保护仓库HEAD/status；这些检查通过后F23条件结构格关闭，原F17/F21/G
保持关闭。X27其它族、其余十三组、P5和M2不代关。整个建模阶段完成后先按用户
要求讲解，当前未达该节点。

[下一门只读起点](M1_AWAIT_REEVALUATION_NEXT_REVIEW.md)保留已有E/H能力，提出
同caller两次获取同B仍应保本次own-result边界的有限待测假设，以及整pipeline
真backedge重求值的原剩余要求。该审查未新增测试、代码或通过结论。
